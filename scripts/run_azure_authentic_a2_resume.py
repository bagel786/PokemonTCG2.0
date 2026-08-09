#!/usr/bin/env python3
"""Resume the qualified A2 authentic gate in timeout-safe 500-game shards."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import subprocess
import threading
import time
from pathlib import Path

from scripts.run_azure_recovery_farm import (
    CONSERVATIVE_RATE_USD_PER_WORKER_HOUR,
    KEY,
    OUTPUT,
    SOURCE_COMMIT,
    SPEND_CAP_USD,
    WORKERS,
    deallocate,
    prepare_worker,
    run_task,
    scp,
    start,
)
from training.evaluation_schema import load_evaluation

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = OUTPUT / "source_bundle.tar.gz"
WEST = "grim-westus2"
RESERVED = "auth_control_alakazam_2_4a_shard_1.json"


def tasks() -> list[dict]:
    agents = {
        "a2": "artifacts/recovery_probes/extracted/a2",
        "control": "artifacts/recovery_probes/extracted/control",
    }
    opponents = {
        "alakazam_2_4a": "freshstart/elite_submissions/alakazam_2_4a",
        "alakazam_2_7": "freshstart/elite_submissions/alakazam_2_7",
    }
    seed = 2026080708  # A2 starts at 09 in the canonical 4x500 schedule.
    rows = []
    for agent, submission_a in agents.items():
        for opponent, submission_b in opponents.items():
            for shard in range(1, 5):
                seed += 1
                rows.append({
                    "label": f"auth_{agent}_{opponent}",
                    "shard": shard,
                    "seed": seed,
                    "a": submission_a,
                    "b": submission_b,
                    "deck_b": f"{submission_b}/deck.csv",
                    "games": 500,
                })
    return rows


def filename(task: dict) -> str:
    return f"{task['label']}_shard_{task['shard']}.json"


def valid_local(task: dict) -> bool:
    path = OUTPUT / "shards" / filename(task)
    if not path.exists():
        return False
    try:
        row = load_evaluation(path)
    except Exception:
        return False
    return row["games"] == task["games"] and row["artifact_provenance"]["seed"] == task["seed"]


def remote_state(worker: dict, target: str) -> str:
    command = (
        f"if test -s /mnt/ptcg-recovery/{target}; then echo complete; "
        "elif pgrep -f 'python -m training.evaluate' >/dev/null; then echo running; else echo failed; fi"
    )
    result = subprocess.run([
        "ssh", "-i", str(KEY), "-o", "StrictHostKeyChecking=accept-new",
        f"azureuser@{worker['ip']}", command,
    ], cwd=ROOT, check=True, capture_output=True, text=True, timeout=30)
    return result.stdout.strip()


def recover_reserved(worker: dict, task: dict) -> dict:
    deadline = time.time() + 7200
    while time.time() < deadline:
        state = remote_state(worker, filename(task))
        if state == "complete":
            local = OUTPUT / "shards" / filename(task)
            local.parent.mkdir(parents=True, exist_ok=True)
            scp(local, worker, f"/mnt/ptcg-recovery/{filename(task)}", from_remote=True)
            if not valid_local(task):
                raise RuntimeError(f"recovered shard failed validation: {filename(task)}")
            return {"worker": worker["name"], "task": task, "output": str(local), "games": task["games"], "recovered": True}
        if state == "failed":
            return run_task(worker, task, bundle_hash(), time.time())
        time.sleep(15)
    raise TimeoutError(f"reserved shard did not finish: {filename(task)}")


def bundle_hash() -> str:
    return hashlib.sha256(BUNDLE.read_bytes()).hexdigest()


def main() -> int:
    started = time.time()
    expected_bundle = "ce98f756159fbd47c66b9f52c9cf78bd2f02502574d0ecaa1fc829465cec4283"
    observed_bundle = bundle_hash()
    if observed_bundle != expected_bundle:
        raise SystemExit(f"frozen source bundle changed: {observed_bundle}")
    if len(WORKERS) != 5:
        raise SystemExit("the timeout-safe authentic queue requires exactly five approved workers")

    west = next(worker for worker in WORKERS if worker["name"] == WEST)
    originals = [worker for worker in WORKERS if worker["name"] != WEST]
    for worker in originals:
        start(worker)
    time.sleep(20)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda worker: prepare_worker(worker, BUNDLE), originals))

    all_tasks = tasks()
    reserved_task = next(task for task in all_tasks if filename(task) == RESERVED)
    pending = [task for task in all_tasks if task is not reserved_task and not valid_local(task)]
    lock = threading.Lock()
    results: list[dict] = []

    def worker_loop(worker: dict) -> list[dict]:
        completed = []
        if worker["name"] == WEST and not valid_local(reserved_task):
            completed.append(recover_reserved(worker, reserved_task))
        while True:
            with lock:
                if not pending:
                    break
                task = pending.pop(0)
            if valid_local(task):
                continue
            completed.append(run_task(worker, task, observed_bundle, started))
        return completed

    status = "failed"
    error = None
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            for rows in pool.map(worker_loop, WORKERS):
                results.extend(rows)
        missing = [filename(task) for task in all_tasks if not valid_local(task)]
        if missing:
            raise RuntimeError(f"missing or invalid authentic shards: {missing}")
        status = "complete"
        return 0
    except Exception as exc:
        error = repr(exc)
        raise
    finally:
        ended = time.time()
        estimated = (ended - started) / 3600 * len(WORKERS) * CONSERVATIVE_RATE_USD_PER_WORKER_HOUR
        if estimated > SPEND_CAP_USD:
            status = "failed"
            error = f"conservative estimated spend exceeded cap: ${estimated:.2f}"
        manifest = {
            "status": status,
            "error": error,
            "started": started,
            "ended": ended,
            "source_commit": SOURCE_COMMIT,
            "source_bundle_sha256": observed_bundle,
            "workers": WORKERS,
            "results": results,
            "conservative_estimated_spend_usd": estimated,
            "spend_cap_usd": SPEND_CAP_USD,
        }
        (OUTPUT / "farm_manifest_authentic_a2_resume.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        for worker in WORKERS:
            deallocate(worker)


if __name__ == "__main__":
    raise SystemExit(main())
