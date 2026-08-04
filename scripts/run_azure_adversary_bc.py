#!/usr/bin/env python3
"""Train bounded Bellibolt prior/value seeds on Azure and stop.

This runner cannot train Grimmsnarl, qualify a gameplay opponent, package an
archive, or submit to Kaggle.  It always deallocates the configured VM.
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
    parser.add_argument("--shard", default="artifacts/bellibolt_bootstrap_20260803/data/bellibolt_audited.jsonl.gz")
    parser.add_argument("--initial-model", default="artifacts/grimmsnarl_5k_reference.npz")
    parser.add_argument("--output-dir", default="artifacts/bellibolt_bootstrap_20260803/bc")
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--cost-cap", type=float, default=2.0)
    parser.add_argument("--seed", type=int, default=20260803)
    args = parser.parse_args()

    for value in (args.shard, args.initial_model):
        path = (ROOT / value).resolve()
        try:
            path.relative_to(ROOT)
        except ValueError as error:
            parser.error(f"input must live under repository: {path}")
        if not path.exists():
            parser.error(f"missing input: {path}")

    output = ROOT / args.output_dir
    state_path = output / "azure_run.json"
    rate = azure_rate()
    started = time.time()
    state = {
        "version": 1,
        "scope": "bellibolt_prior_value_training_only",
        "started_unix": started,
        "retail_rate_per_hour": rate,
        "cost_cap_usd": args.cost_cap,
        "stages": [],
        "grim_training_started": False,
        "gameplay_qualified": False,
        "package_created": False,
        "submitted": False,
    }

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

    def remote(script: str):
        elapsed = (time.time() - started) / 3600.0
        remaining = max(1, int((args.cost_cap / rate - elapsed) * 3600))
        shell = f"cd {shlex.quote(str(REMOTE_ROOT))} && {script}"
        return command([
            "ssh", f"azureuser@{ip}",
            f"timeout --signal=TERM {remaining}s bash -lc {shlex.quote(shell)}",
        ])

    synchronized = False
    try:
        command([
            "rsync", "-azR", "--exclude", "__pycache__", "--exclude", "*.pyc",
            "training", "ptcg_ai", "vendor", "tests", "freshstart/submission_template",
            args.shard, args.initial_model,
            f"azureuser@{ip}:{REMOTE_ROOT}/",
        ])
        checkpoint("inputs_synchronized")
        environment = "export PTCG_AZURE_RUN=1 PYTHONUNBUFFERED=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1; "
        remote(environment + "/opt/ptcg-venv/bin/python -m pytest -q "
               "tests/test_adversary_bc.py tests/test_mcts_teacher.py tests/test_search_teacher.py")
        checkpoint("remote_tests_passed")
        remote_output = REMOTE_ROOT / args.output_dir
        train = [
            "/opt/ptcg-venv/bin/python", "-m", "training.train_adversary_bc",
            "--shard", str(REMOTE_ROOT / args.shard),
            "--required-card", "269",
            "--initial-model", str(REMOTE_ROOT / args.initial_model),
            "--output-dir", str(remote_output),
            "--epochs", str(args.epochs),
            "--seed", str(args.seed),
        ]
        remote(environment + " ".join(map(shlex.quote, train)))
        checkpoint("candidate_training_complete")
        command(["rsync", "-az", f"azureuser@{ip}:{remote_output}/", str(output) + "/"])
        manifest = json.loads((output / "candidate_manifest.json").read_text())
        if manifest.get("grim_training_started") or manifest.get("package_created") or manifest.get("submitted"):
            raise RuntimeError("adversary BC scope invariant failed")
        synchronized = True
        checkpoint("artifacts_synchronized")
    except Exception as exc:
        state.update({"status": "failed", "error": repr(exc)})
        write_json(state_path, state)
        raise
    finally:
        command(["az", "vm", "deallocate", "-g", args.resource_group, "-n", args.vm])
        finished = time.time()
        state.update({
            "deallocated": True,
            "deallocated_unix": finished,
            "elapsed_hours": (finished - started) / 3600.0,
            "estimated_retail_compute_cost_usd": (finished - started) / 3600.0 * rate,
        })
        write_json(state_path, state)
    if synchronized:
        state["status"] = "complete"
        write_json(state_path, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
