#!/usr/bin/env python3
"""Run bounded Lucario/Bellibolt search-teacher qualification on Azure.

This program never trains Grim, packages an archive, or submits to Kaggle.  It
screens each teacher at a bounded game count and, unless ``--screen-only`` is
set, expands only teachers clearing a 15% floor with zero runtime errors.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REMOTE_ROOT = Path("/mnt/ptcg/repo")


def command(args, *, capture=False):
    return subprocess.run(args, cwd=ROOT, check=True, text=True, capture_output=capture)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def azure_rate() -> float:
    filter_ = "armRegionName eq 'southcentralus' and armSkuName eq 'Standard_D8s_v6' and priceType eq 'Consumption'"
    response = command([
        "curl", "-fsS", "--get", "https://prices.azure.com/api/retail/prices",
        "--data-urlencode", f"$filter={filter_}",
    ], capture=True)
    rows = json.loads(response.stdout)["Items"]
    linux = [row for row in rows if row["skuName"] == "D8s v6" and "Windows" not in row["productName"]]
    if len(linux) != 1:
        raise RuntimeError(f"could not resolve Linux D8s v6 price: {linux}")
    return float(linux[0]["unitPrice"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resource-group", default="ptcg-train-south-rg")
    parser.add_argument("--vm", default="ptcg-train")
    parser.add_argument("--output-dir", default="artifacts/search_teacher_qualification_20260803")
    parser.add_argument("--screen-games", type=int, default=100)
    parser.add_argument("--qualification-games", type=int, default=1_000)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--cost-cap", type=float, default=10.0)
    parser.add_argument("--seed", type=int, default=20260803)
    parser.add_argument("--candidate-mode", choices=("prior", "exhaustive"), default="prior")
    parser.add_argument("--screen-max-candidates", type=int, default=6)
    parser.add_argument("--qualification-max-candidates", type=int, default=8)
    parser.add_argument("--agent-kind", choices=("rollout", "mcts"), default="rollout")
    parser.add_argument("--mcts-simulations", type=int, default=48)
    parser.add_argument("--mcts-max-depth", type=int, default=64)
    parser.add_argument("--mcts-puct-c", type=float, default=1.5)
    parser.add_argument("--mcts-tree-max-candidates", type=int, default=8)
    parser.add_argument("--mcts-leaf-rollout-steps", type=int, default=0)
    parser.add_argument("--mcts-rollout-weight", type=float, default=0.0)
    parser.add_argument(
        "--screen-only",
        action="store_true",
        help="write screen reports without automatically launching qualification games",
    )
    parser.add_argument("--lucario-model", default="artifacts/lucario_pilot/lucario_ppo2.npz")
    parser.add_argument("--bellibolt-model", default="artifacts/lucario_pilot/lucario_ppo2.npz")
    args = parser.parse_args()
    if args.screen_max_candidates <= 0 or args.qualification_max_candidates <= 0:
        parser.error("candidate caps must be positive")
    model_paths = {
        "lucario": Path(args.lucario_model),
        "bellibolt": Path(args.bellibolt_model),
    }
    for name, path in model_paths.items():
        if path.is_absolute():
            try:
                model_paths[name] = path.resolve().relative_to(ROOT)
            except ValueError as error:
                parser.error(f"{name} model must live inside the repository: {path}")
        if not (ROOT / model_paths[name]).exists():
            parser.error(f"missing {name} model: {ROOT / model_paths[name]}")

    output = ROOT / args.output_dir
    state_path = output / "azure_run.json"
    state = {
        "version": 3,
        "started_unix": time.time(),
        "stages": [],
        "scope": "adversary_qualification_only",
        "grim_training_started": False,
        "package_created": False,
        "submitted": False,
    }
    rate = azure_rate()
    state.update({"retail_rate_per_hour": rate, "cost_cap_usd": args.cost_cap})
    started = time.time()

    def checkpoint(stage: str) -> None:
        elapsed = (time.time() - started) / 3600.0
        state.update({"elapsed_hours": elapsed, "estimated_retail_compute_cost_usd": elapsed * rate})
        if stage not in state["stages"]:
            state["stages"].append(stage)
        write_json(state_path, state)
        if elapsed * rate >= args.cost_cap:
            raise RuntimeError(f"Azure cost cap reached: ${elapsed * rate:.2f}")

    command(["az", "vm", "start", "-g", args.resource_group, "-n", args.vm])
    ip = command([
        "az", "vm", "show", "-d", "-g", args.resource_group, "-n", args.vm,
        "--query", "publicIps", "-o", "tsv",
    ], capture=True).stdout.strip()
    state.update({"public_ip": ip, "status": "running"})
    checkpoint("vm_started")

    def remote(script: str, *, capture=False):
        elapsed = (time.time() - started) / 3600.0
        remaining = max(1, int((args.cost_cap / rate - elapsed) * 3600))
        shell = f"cd {shlex.quote(str(REMOTE_ROOT))} && {script}"
        return command([
            "ssh", f"azureuser@{ip}",
            f"timeout --signal=TERM {remaining}s bash -lc {shlex.quote(shell)}",
        ], capture=capture)

    synchronized = False
    try:
        command([
            "rsync", "-azR", "--exclude", "__pycache__", "--exclude", "*.pyc",
            "training", "ptcg_ai", "vendor", "tests",
            "freshstart/submission_template",
            "freshstart/decklists/iono_bellibolt_ex.deck.csv",
            "freshstart/decklists/mega_lucario_ex.deck.csv",
            "freshstart/decklists/grimmsnarl_marnie.deck.csv",
            *sorted({str(path) for path in model_paths.values()}),
            "artifacts/grimmsnarl_5k_reference.npz",
            f"azureuser@{ip}:{REMOTE_ROOT}/",
        ])
        checkpoint("inputs_synchronized")

        environment = "export PTCG_AZURE_RUN=1 PYTHONUNBUFFERED=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1; "
        remote(environment + "/opt/ptcg-venv/bin/python -m pytest -q "
               "tests/test_search_teacher.py tests/test_ppo.py tests/test_gae.py "
               "tests/test_invariants_1_6_and_1_7.py")
        checkpoint("remote_tests_passed")

        remote_output = REMOTE_ROOT / args.output_dir
        teachers = {
            "lucario": (
                REMOTE_ROOT / "freshstart/decklists/mega_lucario_ex.deck.csv",
                REMOTE_ROOT / model_paths["lucario"],
            ),
            "bellibolt": (
                REMOTE_ROOT / "freshstart/decklists/iono_bellibolt_ex.deck.csv",
                REMOTE_ROOT / model_paths["bellibolt"],
            ),
        }
        screens = {}
        expanded = {}
        for index, (name, (deck, model)) in enumerate(teachers.items()):
            screen_path = remote_output / f"{name}_screen.json"
            screen_command = [
                "/opt/ptcg-venv/bin/python", "-m", "training.evaluate_search_teacher",
                "--deck-a", str(deck),
                "--model-a", str(model),
                "--deck-b", str(REMOTE_ROOT / "freshstart/decklists/grimmsnarl_marnie.deck.csv"),
                "--model-b", str(REMOTE_ROOT / "artifacts/grimmsnarl_5k_reference.npz"),
                "--games", str(args.screen_games), "--workers", str(args.workers),
                "--agent-kind", args.agent_kind,
                "--determinizations", "1",
                "--max-candidates", str(args.screen_max_candidates),
                "--candidate-width", "8", "--candidate-mode", args.candidate_mode,
                "--rollout-steps", "320", "--seed", str(args.seed + index * 100_000),
                "--output", str(screen_path),
            ]
            if args.agent_kind == "mcts":
                screen_command.extend([
                    "--mcts-simulations", str(args.mcts_simulations),
                    "--mcts-max-depth", str(args.mcts_max_depth),
                    "--mcts-puct-c", str(args.mcts_puct_c),
                    "--mcts-tree-max-candidates", str(args.mcts_tree_max_candidates),
                    "--mcts-leaf-rollout-steps", str(args.mcts_leaf_rollout_steps),
                    "--mcts-rollout-weight", str(args.mcts_rollout_weight),
                ])
            remote(environment + " ".join(map(shlex.quote, screen_command)))
            screen = json.loads(remote(
                f"python3 -c {shlex.quote(f'import json; print(json.dumps(json.load(open({str(screen_path)!r}))))')} ",
                capture=True,
            ).stdout)
            screens[name] = screen
            passed_screen = (
                screen["win_rate_a"] >= 0.15
                and screen["teacher_search_errors"] == 0
                and screen["opponent_policy_errors"] == 0
            )
            if passed_screen and not args.screen_only:
                qualification_path = remote_output / f"{name}_qualification.json"
                qualification_command = list(screen_command)
                # Rebuild the few changed arguments explicitly to avoid ambiguous numeric replacement.
                qualification_command[qualification_command.index("--games") + 1] = str(args.qualification_games)
                qualification_command[qualification_command.index("--determinizations") + 1] = "2"
                qualification_command[qualification_command.index("--max-candidates") + 1] = str(
                    args.qualification_max_candidates
                )
                qualification_command[qualification_command.index("--output") + 1] = str(qualification_path)
                remote(environment + " ".join(map(shlex.quote, qualification_command)))
                expanded[name] = json.loads(remote(
                    f"python3 -c {shlex.quote(f'import json; print(json.dumps(json.load(open({str(qualification_path)!r}))))')} ",
                    capture=True,
                ).stdout)
            checkpoint(f"{name}_evaluated")

        command([
            "rsync", "-az", f"azureuser@{ip}:{remote_output}/", str(output) + "/",
        ])
        synchronized = True
        summary = {
            "version": 1,
            "screens": screens,
            "qualifications": expanded,
            "qualified": {name: report.get("qualified", False) for name, report in expanded.items()},
            "scope": state["scope"],
            "grim_training_started": False,
            "package_created": False,
            "submitted": False,
        }
        write_json(output / "final_report.json", summary)
        checkpoint("artifacts_synchronized")
    except Exception as exc:
        state.update({"status": "failed", "error": repr(exc)})
        write_json(state_path, state)
        raise
    finally:
        command(["az", "vm", "deallocate", "-g", args.resource_group, "-n", args.vm])
        state["deallocated_unix"] = time.time()
        state["elapsed_hours"] = (state["deallocated_unix"] - started) / 3600.0
        state["estimated_retail_compute_cost_usd"] = state["elapsed_hours"] * rate
        state["deallocated"] = True
        write_json(state_path, state)

    if synchronized:
        state["status"] = "complete"
        write_json(state_path, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
