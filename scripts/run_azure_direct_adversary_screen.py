#!/usr/bin/env python3
"""Directly screen all Bellibolt BC priors against pure-5k Grim on Azure.

This is gameplay evaluation only. It never trains Grim, packages, or submits,
and always deallocates the VM.
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resource-group", default="ptcg-train-south-rg")
    parser.add_argument("--vm", default="ptcg-train")
    parser.add_argument("--manifest", default="artifacts/bellibolt_bootstrap_20260803/bc/candidate_manifest.json")
    parser.add_argument("--output-dir", default="artifacts/bellibolt_bootstrap_20260803/direct_screen")
    parser.add_argument("--games", type=int, default=100)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--cost-cap", type=float, default=2.0)
    parser.add_argument("--seed", type=int, default=20260803)
    args = parser.parse_args()

    manifest = json.loads((ROOT / args.manifest).read_text())
    candidates = []
    for row in manifest["candidates"]:
        if not row["fidelity_gate"]["passed"]:
            continue
        remote_path = Path(row["model"])
        local_path = ROOT / remote_path.relative_to(REMOTE_ROOT)
        if not local_path.exists():
            parser.error(f"missing candidate checkpoint: {local_path}")
        candidates.append({"name": row["name"], "local": local_path, "remote": remote_path})
    if not candidates:
        parser.error("candidate manifest has no fidelity-eligible models")

    output = ROOT / args.output_dir
    state_path = output / "azure_run.json"
    rate = 0.484
    started = time.time()
    state = {
        "version": 1, "scope": "direct_adversary_screen_only", "started_unix": started,
        "retail_rate_per_hour": rate, "cost_cap_usd": args.cost_cap, "stages": [],
        "grim_training_started": False, "package_created": False, "submitted": False,
    }

    def checkpoint(stage: str) -> None:
        elapsed = (time.time() - started) / 3600.0
        state.update({"elapsed_hours": elapsed, "estimated_retail_compute_cost_usd": elapsed * rate})
        if stage not in state["stages"]:
            state["stages"].append(stage)
        write_json(state_path, state)
        if elapsed * rate >= args.cost_cap:
            raise RuntimeError("Azure cost cap reached")

    command(["az", "vm", "start", "-g", args.resource_group, "-n", args.vm])
    ip = command(["az", "vm", "show", "-d", "-g", args.resource_group, "-n", args.vm,
                  "--query", "publicIps", "-o", "tsv"], capture=True).stdout.strip()
    state.update({"public_ip": ip, "status": "running"})
    checkpoint("vm_started")

    def remote(script: str):
        elapsed = (time.time() - started) / 3600.0
        remaining = max(1, int((args.cost_cap / rate - elapsed) * 3600))
        shell = f"cd {shlex.quote(str(REMOTE_ROOT))} && {script}"
        command(["ssh", f"azureuser@{ip}",
                 f"timeout --signal=TERM {remaining}s bash -lc {shlex.quote(shell)}"])

    synchronized = False
    try:
        command([
            "rsync", "-azR", "--exclude", "__pycache__", "--exclude", "*.pyc",
            "training", "ptcg_ai", "vendor", "freshstart/submission_template",
            "freshstart/decklists/iono_bellibolt_ex.deck.csv",
            "freshstart/decklists/grimmsnarl_marnie.deck.csv",
            "artifacts/grimmsnarl_5k_reference.npz",
            *[str(item["local"].relative_to(ROOT)) for item in candidates],
            f"azureuser@{ip}:{REMOTE_ROOT}/",
        ])
        checkpoint("inputs_synchronized")
        environment = "export PTCG_AZURE_RUN=1 PYTHONUNBUFFERED=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1; "
        remote_output = REMOTE_ROOT / args.output_dir
        reports = []
        for index, candidate in enumerate(candidates):
            report_path = remote_output / f"{candidate['name']}.json"
            evaluate = [
                "/opt/ptcg-venv/bin/python", "-m", "training.evaluate",
                "--deck-a", str(REMOTE_ROOT / "freshstart/decklists/iono_bellibolt_ex.deck.csv"),
                "--model-a", str(candidate["remote"]),
                "--deck-b", str(REMOTE_ROOT / "freshstart/decklists/grimmsnarl_marnie.deck.csv"),
                "--model-b", str(REMOTE_ROOT / "artifacts/grimmsnarl_5k_reference.npz"),
                "--games", str(args.games), "--workers", str(args.workers),
                "--seed", str(args.seed + index * 100_000), "--output", str(report_path),
            ]
            remote(environment + " ".join(map(shlex.quote, evaluate)))
            checkpoint(f"screened_{candidate['name']}")
        command(["rsync", "-az", f"azureuser@{ip}:{remote_output}/", str(output) + "/"])
        for candidate in candidates:
            report = json.loads((output / f"{candidate['name']}.json").read_text())
            reports.append({"name": candidate["name"], "model": str(candidate["local"]), "report": report})
        reports.sort(key=lambda row: row["report"]["win_rate_a"], reverse=True)
        summary = {
            "version": 1, "screens": reports,
            "advanced": [row["name"] for row in reports if row["report"]["win_rate_a"] >= 0.15],
            "selection_rule": "gameplay_strength_only",
            "grim_training_started": False, "package_created": False, "submitted": False,
        }
        write_json(output / "final_report.json", summary)
        synchronized = True
        checkpoint("artifacts_synchronized")
    except Exception as exc:
        state.update({"status": "failed", "error": repr(exc)})
        write_json(state_path, state)
        raise
    finally:
        command(["az", "vm", "deallocate", "-g", args.resource_group, "-n", args.vm])
        finished = time.time()
        state.update({"deallocated": True, "deallocated_unix": finished,
                      "elapsed_hours": (finished - started) / 3600.0,
                      "estimated_retail_compute_cost_usd": (finished - started) / 3600.0 * rate})
        write_json(state_path, state)
    if synchronized:
        state["status"] = "complete"
        write_json(state_path, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
