#!/usr/bin/env python3
"""Run the low-band Grim exposure curriculum on the Azure VM.

Single-candidate: sync inputs, remote smoke, remote run of
training.run_lowband_exposure, sync artifacts back, deallocate. Contains no
packaging or submission step. Modeled on scripts/run_azure_lucario.py.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from training.replay_refresh import sha256_file  # noqa: E402

REMOTE_ROOT = Path("/mnt/ptcg/repo")

REQUIRED_FILES = [
    "data/processed/elite-2026-07-30-31-v2ctl.jsonl.gz",
    "artifacts/5k_replay_refresh_20260802/full/split_manifest.json",
    "artifacts/5k_replay_refresh_20260802/full/candidates/lr1e-04_seed20260803/policy_weights.npz",
    "artifacts/grimmsnarl_5k_reference.npz",
    "artifacts/lucario_pilot/lucario_ppo2.npz",
    "artifacts/bellibolt_bootstrap_20260803/bc/initialized_seed20260804/policy_weights.npz",
    "freshstart/decklists/grimmsnarl_marnie.deck.csv",
    "freshstart/decklists/mega_lucario_ex.deck.csv",
    "freshstart/decklists/iono_bellibolt_ex.deck.csv",
    "freshstart/decklists/dragapult_ex.deck.csv",
    "freshstart/decklists/team_rockets_mewtwo_ex.deck.csv",
    "freshstart/decklists/kangaskhan_crustle.deck.csv",
    "freshstart/decklists/cynthias_garchomp_ex.deck.csv",
    "freshstart/decklists/mega_starmie_froslass.deck.csv",
]
SYNC_DIRS = ["training", "ptcg_ai", "vendor", "freshstart/submission_template", "freshstart/elite_submissions"]


def command(args, *, capture=False):
    return subprocess.run(args, cwd=ROOT, check=True, text=True, capture_output=capture)


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


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def wait_for_ssh(ip: str, attempts: int = 20, delay: int = 20) -> None:
    """Block until sshd accepts; a cold VM is not reachable the instant az returns."""
    for _ in range(attempts):
        if subprocess.run(["ssh", "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=accept-new",
                           f"azureuser@{ip}", "true"], cwd=ROOT).returncode == 0:
            return
        time.sleep(delay)
    raise RuntimeError(f"SSH to {ip} not ready after {attempts * delay}s")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resource-group", default="ptcg-train-south-rg")
    parser.add_argument("--vm", default="ptcg-train")
    parser.add_argument("--output-dir", default="artifacts/lowband_exposure_20260803")
    parser.add_argument("--collect-games", type=int, default=5000)
    parser.add_argument("--mirror-games", type=int, default=2000)
    parser.add_argument("--adversary-games", type=int, default=1000)
    parser.add_argument("--authentic-games", type=int, default=500)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20260803)
    parser.add_argument("--cost-cap", type=float, default=8.0)
    parser.add_argument("--skip-smoke", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--skip-sync", action="store_true")
    args = parser.parse_args()

    for rel in REQUIRED_FILES:
        if not (ROOT / rel).exists():
            parser.error(f"missing required input: {rel}")

    output_rel = Path(args.output_dir)
    output_dir = ROOT / output_rel
    state_path = output_dir / "azure_run.json"
    state = json.loads(state_path.read_text()) if args.resume and state_path.exists() else {
        "version": 1, "started_unix": time.time(), "stages": [],
        "recommendation_only": True, "package_created": False, "submitted": False,
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
    state.update({"public_ip": ip, "status": "running"})
    checkpoint("vm_started")
    wait_for_ssh(ip)
    checkpoint("ssh_ready")

    def run_remote(script: str) -> None:
        elapsed = prior_hours + (time.time() - active_started) / 3600
        remaining = max(0, int((args.cost_cap / rate - elapsed) * 3600))
        if remaining <= 0:
            raise RuntimeError("Azure compute cap reached before remote stage")
        remote_shell = f"cd {shlex.quote(str(REMOTE_ROOT))} && {script}"
        command(["ssh", f"azureuser@{ip}",
                 f"timeout --signal=TERM {remaining}s bash -lc {shlex.quote(remote_shell)}"])

    synchronized = False
    try:
        if not args.skip_sync:
            command(["rsync", "-azR", "--exclude", "__pycache__", "--exclude", "*.pyc",
                     *SYNC_DIRS, *REQUIRED_FILES, f"azureuser@{ip}:{REMOTE_ROOT}/"])
            checkpoint("inputs_synchronized")

        remote_output = REMOTE_ROOT / output_rel
        base = [
            "/opt/ptcg-venv/bin/python", "-m", "training.run_lowband_exposure",
            "--anchor", "artifacts/5k_replay_refresh_20260802/full/candidates/lr1e-04_seed20260803/policy_weights.npz",
            "--league", "training/lowband_grim_league.json",
            "--workers", str(args.workers), "--seed", str(args.seed),
        ]
        env = "export PTCG_AZURE_RUN=1 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2; "

        if not args.skip_smoke and "azure_smoke" not in state["stages"]:
            smoke = base + [
                "--output-dir", str(remote_output.parent / "lowband_exposure_smoke"),
                "--collect-games", "20", "--shard-size", "10",
                "--mirror-games", "20", "--adversary-games", "20", "--authentic-games", "10",
                "--allow-local-smoke",
            ]
            run_remote(env + " ".join(map(shlex.quote, smoke)))
            checkpoint("azure_smoke")

        full = base + [
            "--output-dir", str(remote_output),
            "--collect-games", str(args.collect_games), "--shard-size", "500",
            "--mirror-games", str(args.mirror_games),
            "--adversary-games", str(args.adversary_games),
            "--authentic-games", str(args.authentic_games),
        ]
        if args.resume:
            full.append("--resume")
        run_remote(env + " ".join(map(shlex.quote, full)))
        checkpoint("exposure_complete")

        command(["rsync", "-az", f"azureuser@{ip}:{remote_output}/", str(output_dir) + "/"])
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
        final = json.loads((output_dir / "final_report.json").read_text())
        challenger = output_dir / "policy_weights.npz"
        verified = challenger.exists() and sha256_file(challenger) == final["sha256"]
        state.update({"status": "complete", "run_status": final["status"],
                      "success": final["success"], "challenger_verified": verified})
        write_json(state_path, state)
        print(json.dumps({"run_status": final["status"], "success": final["success"],
                          "challenger_verified": verified, "cost_usd": state["estimated_retail_compute_cost_usd"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
