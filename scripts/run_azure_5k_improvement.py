#!/usr/bin/env python3
"""Azure-only controller for the staged 5k improvement program.

This controller can train and evaluate candidates, but intentionally contains no
packaging or submission operation.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCAL_ARTIFACTS = ROOT / "artifacts" / "5k_improvement_20260802"
REMOTE_ROOT = "/mnt/ptcg/repo"
REMOTE_ARTIFACTS = f"{REMOTE_ROOT}/artifacts/5k_improvement_20260802"


def command(args, *, capture=False):
    return subprocess.run(args, cwd=ROOT, check=True, text=True, capture_output=capture)


def command_retry(args, *, capture=False, attempts=5, delay_seconds=3):
    last_error = None
    for attempt in range(attempts):
        try:
            return command(args, capture=capture)
        except subprocess.CalledProcessError as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(delay_seconds)
    raise last_error


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


def remote(ip: str, script: str):
    command(["ssh", f"azureuser@{ip}", f"cd {shlex.quote(REMOTE_ROOT)} && {script}"])


def remote_exists(ip: str, path: str) -> bool:
    return subprocess.run(
        ["ssh", f"azureuser@{ip}", f"test -f {shlex.quote(path)}"],
        cwd=ROOT,
    ).returncode == 0


def write_state(path: Path, state: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resource-group", default="ptcg-train-south-rg")
    parser.add_argument("--vm", default="ptcg-train")
    parser.add_argument("--cost-cap", type=float, default=30.0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--skip-sync", action="store_true")
    args = parser.parse_args()
    state_path = LOCAL_ARTIFACTS / "azure_run.json"
    state = json.loads(state_path.read_text()) if args.resume and state_path.exists() else {
        "version": 1, "started_unix": time.time(), "stages": [], "recommendation_only": True,
        "package_created": False, "submitted": False,
    }
    if args.resume and "elapsed_hours" in state:
        # Continue accounting only billable VM-active time; exclude time spent safely deallocated.
        prior_compute_seconds = float(state["elapsed_hours"]) * 3600
        state["started_unix"] = time.time() - prior_compute_seconds
        for stale_key in ("deallocated_unix", "error", "status"):
            state.pop(stale_key, None)
    rate = azure_rate()
    state.update({"retail_rate_per_hour": rate, "cost_cap": args.cost_cap})

    def checkpoint(stage: str):
        elapsed = (time.time() - state["started_unix"]) / 3600
        cost = elapsed * rate
        state["elapsed_hours"] = elapsed
        state["estimated_compute_cost"] = cost
        if stage not in state["stages"]:
            state["stages"].append(stage)
        write_state(state_path, state)
        if cost >= args.cost_cap:
            raise RuntimeError(f"Azure compute cap reached: ${cost:.2f} >= ${args.cost_cap:.2f}")

    command(["az", "vm", "start", "-g", args.resource_group, "-n", args.vm])
    ip = command([
        "az", "vm", "show", "-d", "-g", args.resource_group, "-n", args.vm,
        "--query", "publicIps", "-o", "tsv",
    ], capture=True).stdout.strip()
    state["public_ip"] = ip
    checkpoint("vm_started")
    try:
        if not args.skip_sync:
            command([
                "rsync", "-az", "--exclude", "__pycache__", "--exclude", "*.pyc",
                "training", "ptcg_ai", "tests", "scripts", "docs", "freshstart/submission_template",
                "freshstart/decklists", "freshstart/elite_submissions", f"azureuser@{ip}:{REMOTE_ROOT}/",
            ])
            checkpoint("code_synced")

        env = "export PTCG_AZURE_RUN=1 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2;"
        hard_audit = f"{REMOTE_ARTIFACTS}/hard/audit.json"
        if not remote_exists(ip, hard_audit):
            remote(ip, env + " /opt/ptcg-venv/bin/python -m training.build_hard_examples "
                   "--fresh data/processed/elite-2026-07-30-31-v2ctl.jsonl.gz "
                   "--split-manifest artifacts/5k_improvement_20260802/split_manifest.json "
                   "--baseline-model artifacts/grimmsnarl_5k_reference.npz "
                   "--finalist-model artifacts/5k_replay_refresh_20260802/full/candidates/lr1e-04_seed20260803/policy_weights.npz "
                   "--output artifacts/5k_improvement_20260802/hard/hard.jsonl.gz "
                   "--audit-output artifacts/5k_improvement_20260802/hard/audit.json --device cpu")
        checkpoint("hard_examples")

        seat_report = f"{REMOTE_ARTIFACTS}/seat_audit/final_report.json"
        if not remote_exists(ip, seat_report):
            remote(ip, env + " /opt/ptcg-venv/bin/python -m training.run_seat_audit "
                   "--challenger-model artifacts/5k_replay_refresh_20260802/full/candidates/lr1e-04_seed20260803/policy_weights.npz "
                   "--output-dir artifacts/5k_improvement_20260802/seat_audit --workers 8 --resume")
        checkpoint("seat_audit")

        candidate_commands = []
        anchors = (
            ("5k", "artifacts/grimmsnarl_5k_reference.npz"),
            ("refresh", "artifacts/5k_replay_refresh_20260802/full/candidates/lr1e-04_seed20260803/policy_weights.npz"),
        )
        for anchor_name, anchor_path in anchors:
            for seed in (20260802, 20260803, 20260804):
                candidate_commands.append(
                    f"/opt/ptcg-venv/bin/python -m training.targeted_refresh --anchor-model {anchor_path} "
                    f"--anchor-name {anchor_name} --hard artifacts/5k_improvement_20260802/hard/hard.jsonl.gz "
                    "--split-manifest artifacts/5k_improvement_20260802/split_manifest.json "
                    f"--output-dir artifacts/5k_improvement_20260802/candidates/{anchor_name}_seed{seed} "
                    f"--seed {seed} --device cpu --resume"
                )
        # Three candidates per wave, two BLAS/OpenMP threads each.
        for wave in (candidate_commands[:3], candidate_commands[3:]):
            remote(ip, env + " " + " & ".join(f"({value})" for value in wave) + " & wait")
            checkpoint("candidate_wave")
        checkpoint("six_candidates")

        candidates = " ".join(
            f"--candidate artifacts/5k_improvement_20260802/candidates/{name}_seed{seed}/candidate.json"
            for name in ("5k", "refresh") for seed in (20260802, 20260803, 20260804)
        )
        remote(ip, env + " /opt/ptcg-venv/bin/python -m training.targeted_selection " + candidates +
               " --structural-control artifacts/5k_improvement_20260802/seat_audit/expanded/control_mirror.json "
               "--fallback-candidate artifacts/5k_replay_refresh_20260802/full/candidates/lr1e-04_seed20260803/decision_evaluation.json "
               "--fallback-model artifacts/5k_replay_refresh_20260802/full/candidates/lr1e-04_seed20260803/policy_weights.npz "
               "--fallback-seat-audit artifacts/5k_improvement_20260802/seat_audit/final_report.json "
               "--output-dir artifacts/5k_improvement_20260802/selection --workers 8 --resume")
        checkpoint("bc_selection")

        status = command_retry([
            "ssh", f"azureuser@{ip}",
            f"python3 -c \"import json; print(json.load(open('{REMOTE_ARTIFACTS}/selection/final_report.json'))['status'])\"",
        ], capture=True).stdout.strip()
        state["bc_status"] = status
        if status == "rl_required":
            best = command_retry([
                "ssh", f"azureuser@{ip}",
                f"python3 -c \"import json; r=json.load(open('{REMOTE_ARTIFACTS}/selection/final_report.json')); print(r['finalist'] or r['screen'][0]['name'])\"",
            ], capture=True).stdout.strip()
            candidate_json = f"artifacts/5k_improvement_20260802/candidates/{best}/candidate.json"
            remote(ip, env + " /opt/ptcg-venv/bin/python -m training.run_conditional_rl "
                   f"--initial-candidate {candidate_json} "
                   "--split-manifest artifacts/5k_improvement_20260802/split_manifest.json "
                   "--structural-control artifacts/5k_improvement_20260802/seat_audit/expanded/control_mirror.json "
                   "--output-dir artifacts/5k_improvement_20260802/conditional_rl --workers 8")
            checkpoint("conditional_rl")

        command_retry(["rsync", "-az", f"azureuser@{ip}:{REMOTE_ARTIFACTS}/", str(LOCAL_ARTIFACTS) + "/"])
        checkpoint("artifacts_synchronized")
        state["status"] = "complete"
        write_state(state_path, state)
        return 0
    except Exception as error:
        state["status"] = "failed"
        state["error"] = repr(error)
        write_state(state_path, state)
        raise
    finally:
        command(["az", "vm", "deallocate", "-g", args.resource_group, "-n", args.vm])
        state["deallocated_unix"] = time.time()
        state["elapsed_hours"] = (state["deallocated_unix"] - state["started_unix"]) / 3600
        state["active_compute_seconds"] = state["elapsed_hours"] * 3600
        state["estimated_compute_cost"] = state["elapsed_hours"] * rate
        write_state(state_path, state)


if __name__ == "__main__":
    raise SystemExit(main())
