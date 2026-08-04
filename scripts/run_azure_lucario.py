#!/usr/bin/env python3
"""Run the Lucario curriculum on the configured Azure VM and verify its artifacts."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from training.lucario_data import sha256_file
from training.run_lucario_curriculum import DEFAULT_DECKS, DEFAULT_GRIM_MODELS


REMOTE_ROOT = Path("/mnt/ptcg/repo")


def remaining_budget_seconds(cost_cap: float, rate: float, elapsed_hours: float) -> int:
    if rate <= 0:
        raise ValueError("Azure retail rate must be positive")
    return max(0, int((cost_cap / rate - elapsed_hours) * 3600))


def azure_rate() -> float:
    filter_ = "armRegionName eq 'southcentralus' and armSkuName eq 'Standard_D8s_v6' and priceType eq 'Consumption'"
    response = command([
        "curl", "-fsS", "--get", "https://prices.azure.com/api/retail/prices",
        "--data-urlencode", f"$filter={filter_}",
    ], capture=True)
    values = json.loads(response.stdout)["Items"]
    linux = [row for row in values if row["skuName"] == "D8s v6" and "Windows" not in row["productName"]]
    if len(linux) != 1:
        raise RuntimeError(f"could not resolve one Linux D8s v6 retail price: {linux}")
    return float(linux[0]["unitPrice"])


def command(args, *, capture=False):
    return subprocess.run(args, cwd=ROOT, check=True, text=True, capture_output=capture)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def repository_relative(path: str | Path) -> Path:
    value = Path(path)
    absolute = value.resolve() if value.is_absolute() else (ROOT / value).resolve()
    try:
        return absolute.relative_to(ROOT)
    except ValueError as error:
        raise ValueError(f"Azure Lucario inputs must live under the repository: {absolute}") from error


def localize_remote(path: str | Path) -> Path:
    value = Path(path)
    try:
        return ROOT / value.relative_to(REMOTE_ROOT)
    except ValueError:
        return value if value.is_absolute() else ROOT / value


def verify_synced_artifacts(output_dir: Path) -> dict:
    checked = []

    def verify(path_value: str, expected: str, label: str) -> None:
        path = localize_remote(path_value)
        if not path.exists():
            raise RuntimeError(f"missing synchronized {label}: {path}")
        actual = sha256_file(path)
        if actual != expected:
            raise RuntimeError(f"hash mismatch for synchronized {label}: {actual} != {expected}")
        checked.append({"label": label, "path": str(path), "sha256": actual})

    final_path = output_dir / "final_report.json"
    final = json.loads(final_path.read_text())
    verify(final["selected_model"], final["selected_sha256"], "selected_model")
    data = json.loads((output_dir / "data" / "manifest.json").read_text())
    verify(data["output"], data["output_sha256"], "filtered_replay_view")
    for index, report_path in enumerate(final["stages"], 1):
        report = json.loads(localize_remote(report_path).read_text())
        verify(report["candidate"]["path"], report["candidate"]["sha256"], f"stage_{index}_candidate")
        verify(report["rollouts"]["output"], report["rollouts"]["sha256"], f"stage_{index}_rollouts")
    result = {"passed": True, "checked": checked}
    write_json(output_dir / "sync_verification.json", result)
    return result


def write_program_report(output_dir: Path, state: dict) -> dict:
    lucario = json.loads((output_dir / "final_report.json").read_text())
    grim_path = output_dir.parent / "grim" / "final_report.json"
    grim = json.loads(grim_path.read_text()) if grim_path.exists() else None
    selected_local = localize_remote(lucario["selected_model"])
    report = {
        "version": 1,
        "status": "recommend_grim_candidate" if grim and grim.get("success") else "retain_live_5k",
        "success": bool(grim and grim.get("success")),
        "lucario_status": lucario["status"],
        "lucario_games": lucario["cumulative_games"],
        "lucario_candidate": {"path": str(selected_local), "sha256": lucario["selected_sha256"]},
        "grim_recovery": grim or {"status": "skipped_unqualified_lucario"},
        "azure": {
            "retail_rate_per_hour": state["retail_rate_per_hour"],
            "elapsed_compute_hours": state["elapsed_hours"],
            "estimated_retail_compute_cost_usd": state["estimated_retail_compute_cost_usd"],
            "deallocated": True,
        },
        "recommendation_only": True,
        "package_created": False,
        "submitted": False,
    }
    write_json(output_dir.parent / "final_report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resource-group", default="ptcg-train-south-rg")
    parser.add_argument("--vm", default="ptcg-train")
    parser.add_argument("--output-dir", default="artifacts/lucario_gap_20260803/lucario")
    parser.add_argument("--bc-shard", default="artifacts/lucario_gap_20260803/data/lucario_expanded_raw.jsonl.gz")
    parser.add_argument("--unseen-grim", default="")
    parser.add_argument("--stage-games", type=int, default=5_000)
    parser.add_argument("--max-games", type=int, default=20_000)
    parser.add_argument("--games-per-eval", type=int, default=500)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20260803)
    parser.add_argument("--cost-cap", type=float, default=30.0)
    parser.add_argument("--skip-smoke", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--skip-sync", action="store_true")
    args = parser.parse_args()

    output_rel = repository_relative(args.output_dir)
    output_dir = ROOT / output_rel
    state_path = output_dir / "azure_run.json"
    state = json.loads(state_path.read_text()) if args.resume and state_path.exists() else {
        "version": 1,
        "started_unix": time.time(),
        "stages": [],
        "recommendation_only": True,
        "package_created": False,
        "submitted": False,
    }
    rate = azure_rate()
    prior_hours = float(state.get("elapsed_hours", 0.0)) if args.resume else 0.0
    active_started = time.time()
    state.update({"retail_rate_per_hour": rate, "cost_cap_usd": args.cost_cap})

    def checkpoint(stage: str) -> None:
        elapsed = prior_hours + (time.time() - active_started) / 3600
        state.update({"elapsed_hours": elapsed, "estimated_retail_compute_cost_usd": elapsed * rate})
        if stage not in state["stages"]:
            state["stages"].append(stage)
        write_json(state_path, state)
        if elapsed * rate >= args.cost_cap:
            raise RuntimeError(f"Azure compute cap reached: ${elapsed * rate:.2f} >= ${args.cost_cap:.2f}")

    command(["az", "vm", "start", "-g", args.resource_group, "-n", args.vm])
    ip = command([
        "az", "vm", "show", "-d", "-g", args.resource_group, "-n", args.vm,
        "--query", "publicIps", "-o", "tsv",
    ], capture=True).stdout.strip()
    vm_details = json.loads(command([
        "az", "vm", "show", "-g", args.resource_group, "-n", args.vm,
        "--query", "{location:location,size:hardwareProfile.vmSize,image:storageProfile.imageReference}", "-o", "json",
    ], capture=True).stdout)
    state.update({"public_ip": ip, "status": "running", "vm": vm_details})
    checkpoint("vm_started")

    def run_remote(script: str) -> None:
        elapsed = prior_hours + (time.time() - active_started) / 3600
        remaining = remaining_budget_seconds(args.cost_cap, rate, elapsed)
        if remaining <= 0:
            raise RuntimeError("Azure compute cap reached before remote stage")
        remote_shell = f"cd {shlex.quote(str(REMOTE_ROOT))} && {script}"
        command([
            "ssh", f"azureuser@{ip}",
            f"timeout --signal=TERM {remaining}s bash -lc {shlex.quote(remote_shell)}",
        ])
    synchronized = False
    try:
        required_files = [
            "artifacts/lucario_bc/lucario_raw.jsonl.gz",
            "artifacts/lucario_bc/lucario_bc.npz",
            str(repository_relative(args.bc_shard)),
            *DEFAULT_DECKS,
            "freshstart/decklists/grimmsnarl_marnie.deck.csv",
            "training/meta_league.json",
            "training/external_alakazam_benchmark.json",
            "data/processed/elite-2026-07-30-31-v2ctl.jsonl.gz",
            "artifacts/5k_replay_refresh_20260802/full/split_manifest.json",
            *DEFAULT_GRIM_MODELS,
        ]
        if args.unseen_grim:
            required_files.append(str(repository_relative(args.unseen_grim)))
        if not args.skip_sync:
            command([
                "rsync", "-azR", "--exclude", "__pycache__", "--exclude", "*.pyc",
                "training", "ptcg_ai", "vendor", "freshstart/submission_template", "freshstart/elite_submissions",
                *required_files,
                f"azureuser@{ip}:{REMOTE_ROOT}/",
            ])
            state["stages"].append("inputs_synchronized")
            checkpoint("inputs_synchronized")

        remote_output = REMOTE_ROOT / output_rel
        curriculum = [
            "/opt/ptcg-venv/bin/python", "-m", "training.run_lucario_curriculum",
            "--output-dir", str(remote_output),
            "--bc-shard", str(REMOTE_ROOT / repository_relative(args.bc_shard)),
            "--stage-games", str(args.stage_games),
            "--max-games", str(args.max_games),
            "--games-per-eval", str(args.games_per_eval),
            "--workers", str(args.workers),
            "--seed", str(args.seed),
        ]
        if args.resume:
            curriculum.append("--resume")
        if args.unseen_grim:
            curriculum.extend(["--unseen-grim", str(REMOTE_ROOT / repository_relative(args.unseen_grim))])
        environment = "export PTCG_AZURE_RUN=1 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2; "
        if not args.skip_smoke and "azure_smoke" not in state["stages"]:
            smoke = list(curriculum)
            replacements = {
                str(remote_output): str(remote_output.parent / "smoke"),
                str(args.stage_games): "200", str(args.max_games): "200", str(args.games_per_eval): "100",
            }
            smoke_script = " ".join(map(shlex.quote, smoke))
            for old, new in replacements.items():
                smoke_script = smoke_script.replace(shlex.quote(old), shlex.quote(new))
            smoke_script += " --bc-max-records 512 --allow-local-smoke"
            run_remote(environment + smoke_script)
            checkpoint("azure_smoke")
        remote_script = environment + " ".join(map(shlex.quote, curriculum))
        run_remote(remote_script)
        checkpoint("curriculum_complete")

        remote_final = remote_output / "final_report.json"
        status = command([
            "ssh", f"azureuser@{ip}",
            f"python3 -c \"import json; print(json.load(open('{remote_final}'))['status'])\"",
        ], capture=True).stdout.strip()
        state["lucario_status"] = status
        if status == "qualified":
            grim_output = remote_output.parent / "grim"
            grim_command = [
                "/opt/ptcg-venv/bin/python", "-m", "training.run_grim_lucario_recovery",
                "--lucario-report", str(remote_final), "--output-dir", str(grim_output),
                "--workers", str(args.workers), "--seed", str(args.seed + 27),
            ]
            if args.resume:
                grim_command.append("--resume")
            run_remote(environment + " ".join(map(shlex.quote, grim_command)))
            checkpoint("grim_recovery_complete")

        command([
            "rsync", "-az", f"azureuser@{ip}:{remote_output.parent}/",
            str(output_dir.parent) + "/",
        ])
        synchronized = True
        checkpoint("artifacts_synchronized")
    except Exception as error:
        state.update({"status": "failed", "error": repr(error)})
        write_json(state_path, state)
        raise
    finally:
        command(["az", "vm", "deallocate", "-g", args.resource_group, "-n", args.vm])
        state["deallocated_unix"] = time.time()
        state["elapsed_hours"] = prior_hours + (state["deallocated_unix"] - active_started) / 3600
        state["estimated_retail_compute_cost_usd"] = state["elapsed_hours"] * rate
        write_json(state_path, state)

    if synchronized:
        verification = verify_synced_artifacts(output_dir)
        state.update({"status": "complete", "sync_verification": verification})
        state["stages"].append("post_deallocation_verification")
        write_json(state_path, state)
        write_program_report(output_dir, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
