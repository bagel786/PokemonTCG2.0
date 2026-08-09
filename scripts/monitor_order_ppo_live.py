#!/usr/bin/env python3
"""Persist Kaggle and Azure snapshots for the live 5k/order-PPO run."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from kaggle.api.kaggle_api_extended import KaggleApi

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.monitor_recovery_ladder import episode_games

OUTPUT = ROOT / "artifacts" / "order_ppo" / "live_monitor"
LATEST = OUTPUT / "latest.json"
HISTORY = OUTPUT / "history.jsonl"
STOP_UTC = dt.datetime(2026, 8, 9, 7, 0, tzinfo=dt.timezone.utc)
AZURE_START_UNIX = dt.datetime(2026, 8, 8, 18, 58, 49, tzinfo=dt.timezone.utc).timestamp()
RATE_PER_WORKER_HOUR = 0.50
# Mirrors the latest recorded authorization in
# artifacts/order_ppo/budget_authorization.json.
SPEND_CAP_USD = 100.0
SUBMISSIONS = (55358290, 55358291)
KEY = ROOT / ".codex_tmp" / "azure_recovery_ed25519"
AZURE = shutil.which("az.cmd") or shutil.which("az.bat") or shutil.which("az") or "az"
WORKERS = [
    {"name": "ptcg-train", "rg": "ptcg-train-south-rg", "ip": "20.225.52.72"},
    {"name": "grim-centralus", "rg": "ptcg-recovery-centralus-rg", "ip": "20.9.33.62"},
    {"name": "grim-eastus2", "rg": "ptcg-recovery-eastus2-rg", "ip": "20.97.180.234"},
    {"name": "grim-northcentralus", "rg": "ptcg-recovery-northcentralus-rg", "ip": "130.131.35.196"},
    {"name": "grim-westus2", "rg": "ptcg-recovery-westus2-rg", "ip": "20.69.108.1"},
]


def command(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=timeout)


def pipeline_state() -> dict:
    result = {}
    for name, relative in (
        ("training", "artifacts/order_ppo/azure/run_manifest.json"),
        ("training_recovery", "artifacts/order_ppo/azure/training_recovery_manifest.json"),
        ("evaluation", "artifacts/order_ppo/evaluation/evaluation_manifest.json"),
        ("continuation", "artifacts/order_ppo/continuation_manifest.json"),
        ("promotion", "artifacts/order_ppo/promotion_manifest.json"),
    ):
        path = ROOT / relative
        if path.exists():
            try:
                result[name] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                result[name] = {"status": "unreadable", "error": repr(exc)}
    return result


def kaggle_snapshot(api: KaggleApi) -> dict:
    remote = {int(row.ref): row for row in api.competition_submissions("pokemon-tcg-ai-battle", page_size=100)}
    result = {}
    for submission_id in SUBMISSIONS:
        row = remote.get(submission_id)
        if row is None:
            result[str(submission_id)] = {"missing": True}
            continue
        games, selfplay = episode_games(api, submission_id)
        result[str(submission_id)] = {
            "status": str(row.status),
            "rating": float(row.public_score) if row.public_score not in (None, "") else None,
            "rated_games": len(games),
            "wins": sum(game["outcome"] > 0 for game in games),
            "losses": sum(game["outcome"] < 1 for game in games),
            "crashes": sum(game["crash"] for game in games),
            "seat0": sum(game["seat"] == 0 for game in games),
            "seat1": sum(game["seat"] == 1 for game in games),
            "excluded_selfplay": selfplay,
            "last_episode": games[-1] if games else None,
        }
    return result


def worker_snapshot(worker: dict) -> dict:
    status = command([
        AZURE, "vm", "get-instance-view", "-g", worker["rg"], "-n", worker["name"],
        "--query", "instanceView.statuses[?starts_with(code, 'PowerState/')].displayStatus | [0]", "-o", "tsv",
    ], timeout=45)
    observed = {"power": status.stdout.strip() if status.returncode == 0 else "azure_query_failed"}
    if observed["power"] != "VM running":
        return observed
    remote = command([
        "ssh", "-i", str(KEY), "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=accept-new",
        f"azureuser@{worker['ip']}",
        "for f in /tmp/*_shard_*.log; do b=${f%.log}; p=$(tail -n 1 \"$f\"); "
        "printf '%s|%s|' \"$f\" \"$p\"; stat -c '%s|%Y' \"$b.jsonl.gz\"; done; "
        "ps -eo args | grep '^/home/azureuser/ptcg-venv/bin/python -m training.collect_order_ppo' | wc -l",
    ], timeout=30)
    if remote.returncode:
        observed["ssh_error"] = remote.stderr.strip()
        return observed
    progress = {}
    lines = remote.stdout.splitlines()
    for line in lines[:-1]:
        parts = line.split("|")
        if len(parts) != 4:
            continue
        filename, payload, size, modified = parts
        try:
            progress[Path(filename).stem] = json.loads(payload) if payload else {"games": 0}
        except json.JSONDecodeError:
            progress[Path(filename).stem] = {"unparseable": payload}
        progress[Path(filename).stem]["rollout_bytes"] = int(size)
        progress[Path(filename).stem]["rollout_modified_unix"] = int(modified)
    observed["active_collectors"] = int(lines[-1]) if lines and lines[-1].isdigit() else None
    observed["shards"] = progress
    return observed


def alerts(snapshot: dict) -> list[str]:
    result = []
    if snapshot.get("kaggle_error"):
        result.append(f"kaggle_query_failed:{snapshot['kaggle_error']['type']}")
    for submission_id, values in snapshot.get("kaggle", {}).items():
        if values.get("missing"):
            result.append(f"submission_missing:{submission_id}")
        if values.get("crashes", 0):
            result.append(f"submission_crash:{submission_id}:{values['crashes']}")
        if "COMPLETE" not in values.get("status", ""):
            result.append(f"submission_status:{submission_id}:{values.get('status')}")
    pipeline = snapshot.get("pipeline", {})
    completed_rollouts = set()
    training = pipeline.get("training", {})
    if isinstance(training, dict):
        for rollout in training.get("rollouts", []):
            job = rollout.get("job", {})
            worker = rollout.get("worker")
            name = job.get("name")
            shard = job.get("shard")
            if worker and name is not None and shard is not None:
                completed_rollouts.add((worker, f"{name}_shard_{shard}"))
    phase = next((pipeline[name] for name in ("promotion", "evaluation", "training_recovery", "training")
                  if isinstance(pipeline.get(name), dict)), {})
    terminal = phase.get("status") in {
        "complete",
        "passed",
        "confirmation_failed",
        "direct_gate_failed",
        "no_checkpoint_passed",
        "cancelled_after_promotion_gate_failure",
    }
    if not terminal:
        for worker, values in snapshot.get("azure", {}).items():
            if values.get("power") != "VM running":
                result.append(f"worker_not_running:{worker}:{values.get('power')}")
            if values.get("ssh_error"):
                result.append(f"worker_ssh:{worker}")
            if int(values.get("active_collectors") or 0) > 0:
                for shard, progress in values.get("shards", {}).items():
                    # Completed remote logs remain on a worker while its other
                    # collectors run. Their age is not evidence of a stall.
                    if (worker, shard) in completed_rollouts:
                        continue
                    modified = float(progress.get("rollout_modified_unix", snapshot["observed_unix"]))
                    if snapshot["observed_unix"] - modified > 900:
                        result.append(f"stalled_rollout:{worker}:{shard}")
    recovery_complete = pipeline.get("training_recovery", {}).get("status") == "complete"
    for name, values in pipeline.items():
        if recovery_complete and name in {"training", "continuation"}:
            continue
        if isinstance(values, dict) and values.get("status") in {"failed", "unreadable", "training_failed"}:
            result.append(f"pipeline_failure:{name}:{values.get('status')}")
    if snapshot["estimated_max_running_spend_usd"] >= SPEND_CAP_USD:
        result.append("budget_cap_reached")
    for relative in ("artifacts/order_ppo/azure/orchestrator.stderr.log", "artifacts/order_ppo/continuation.stderr.log"):
        if recovery_complete and relative.endswith("orchestrator.stderr.log"):
            continue
        path = ROOT / relative
        if path.exists() and path.stat().st_size:
            result.append(f"nonempty_error_log:{relative}")
    return result


def write_snapshot(snapshot: dict) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    temporary = LATEST.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(LATEST)
    with HISTORY.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(snapshot, separators=(",", ":")) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    api = KaggleApi(); api.authenticate()
    next_poll = 0.0
    while dt.datetime.now(dt.timezone.utc) < STOP_UTC:
        now = time.time()
        if now >= next_poll:
            previous = {}
            if LATEST.exists():
                try:
                    previous = json.loads(LATEST.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    previous = {}
            kaggle_error = None
            try:
                kaggle = kaggle_snapshot(api)
            except Exception as exc:
                # Kaggle auth/network failures must not terminate Azure and
                # pipeline coverage. Preserve the last good ladder snapshot
                # and retry on the next normal poll.
                kaggle = previous.get("kaggle", {})
                kaggle_error = {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "stale_since_utc": previous.get("observed_utc"),
                }
            snapshot = {
                "observed_unix": now,
                "observed_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "kaggle": kaggle,
                "kaggle_error": kaggle_error,
                "pipeline": pipeline_state(),
                "azure": {worker["name"]: worker_snapshot(worker) for worker in WORKERS},
                "estimated_max_running_spend_usd": max(0.0, now - AZURE_START_UNIX) / 3600 * len(WORKERS) * RATE_PER_WORKER_HOUR,
                "spend_cap_usd": SPEND_CAP_USD,
            }
            snapshot["alerts"] = alerts(snapshot)
            write_snapshot(snapshot)
            if args.once:
                print(json.dumps(snapshot, indent=2))
                return 0
            next_poll = now + 240
        time.sleep(60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
