#!/usr/bin/env python3
"""Recover checkpoint training from the already validated 24 rollout shards."""

from __future__ import annotations

import concurrent.futures
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_azure_order_ppo import (
    OUTPUT,
    RATE_PER_WORKER_HOUR,
    SPEND_CAP_USD,
    WORKERS,
    build_bundle,
    deallocate,
    prepare,
    start,
    train,
)

STATE_PATH = OUTPUT / "training_recovery_manifest.json"
TRAINERS = WORKERS[:3]
JOBS = [
    ("first", "first", 2026080812),
    ("second_a", "second", 2026080822),
    ("second_b", "second", 2026080832),
]


def validate_rollouts() -> None:
    expected_hash = "D842F85ABFC44AF9F41979F91795E22C92C179B62E04D5A0A2F9C734E70AF1C3"
    for name, order, _seed in JOBS:
        for shard in range(8):
            rollout = OUTPUT / "rollouts" / name / f"shard_{shard}.jsonl.gz"
            metadata = rollout.with_suffix(rollout.suffix + ".json")
            if not rollout.exists() or not metadata.exists():
                raise FileNotFoundError(rollout)
            values = json.loads(metadata.read_text(encoding="utf-8"))
            checks = {
                "status": values.get("status") == "complete",
                "games": values.get("games") == 625,
                "excluded": values.get("excluded_decisions") == 0,
                "actual_order": values.get("actual_order") == order,
                "temperature": values.get("behavior_temperature") == 0.7,
                "terminal_reward_only": values.get("terminal_reward_only") is True,
                "policy_hash": values.get("policy_hash") == expected_hash,
            }
            if not all(checks.values()):
                raise ValueError(f"invalid rollout metadata {metadata}: {checks}")


def write_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    started = time.time()
    state = {
        "status": "starting",
        "started_unix": started,
        "source_failure": "missing vendor path in training.order_ppo",
        "workers": TRAINERS,
        "checkpoints": [],
        "errors": [],
        "spend_cap_usd": SPEND_CAP_USD,
    }
    write_state(state)
    try:
        validate_rollouts()
        projected = 5.0 + 0.5 * len(TRAINERS) * RATE_PER_WORKER_HOUR
        if projected >= SPEND_CAP_USD:
            raise RuntimeError(f"recovery projection ${projected:.2f} reaches budget cap")
        bundle, digest = build_bundle()
        state["bundle_sha256"] = digest
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(start, TRAINERS))
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda worker: prepare(worker, bundle, digest), TRAINERS))
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures = {
                pool.submit(train, worker, *job, started): (worker["name"], job[0])
                for worker, job in zip(TRAINERS, JOBS)
            }
            for future in concurrent.futures.as_completed(futures):
                worker, name = futures[future]
                try:
                    state["checkpoints"].append(future.result())
                except Exception as exc:
                    state["errors"].append({"worker": worker, "name": name, "error": repr(exc)})
                write_state(state)
        if state["errors"]:
            raise RuntimeError(f"{len(state['errors'])} recovered training job(s) failed")
        state["status"] = "complete"
        return 0
    except Exception as exc:
        state["status"] = "failed"
        state["error"] = repr(exc)
        return 2
    finally:
        state["ended_unix"] = time.time()
        state["conservative_estimated_recovery_spend_usd"] = (
            (state["ended_unix"] - started) / 3600 * len(TRAINERS) * RATE_PER_WORKER_HOUR
        )
        write_state(state)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(deallocate, TRAINERS))


if __name__ == "__main__":
    raise SystemExit(main())
