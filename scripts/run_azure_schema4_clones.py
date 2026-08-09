#!/usr/bin/env python3
"""Train six source-specific exact-Grim policy clones on Azure."""

from __future__ import annotations

import concurrent.futures
import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import run_azure_schema4_training as farm

SOURCES = (55308008, 55312662, 55316998, 55321109, 55325981, 55327371)
OUTPUT = ROOT / "artifacts" / "grim_source_clones_v4"


def train(worker, submission_id, started):
    projected = (time.time() - started + 4 * 3600) / 3600 * len(farm.WORKERS) * farm.RATE
    if projected >= farm.SPEND_CAP:
        raise RuntimeError(f"projected spend ${projected:.2f} exceeds ${farm.SPEND_CAP:.2f}")
    label = str(submission_id)
    command = (
        f"cd {farm.REMOTE} && export PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=8 MKL_NUM_THREADS=8 && "
        f"timeout 14400s $HOME/ptcg-venv/bin/python -m training.schema4 "
        f"data/grim_source_clones_v4/{submission_id}/decisions.jsonl.gz "
        "--base artifacts/recovery_probes/extracted/a2_base/policy_weights.npz --mode r1 "
        f"--seed {submission_id} --epochs 10 --batch-size 64 --learning-rate 0.0002 "
        "--checkpoint-metric top1 --support-margin 0 "
        f"--output /tmp/clone-{label}.npz --manifest /tmp/clone-{label}.json "
        f"> /tmp/clone-{label}.log 2>&1"
    )
    farm.ssh(worker, command, timeout=15000)
    local = OUTPUT / label
    local.mkdir(parents=True, exist_ok=True)
    farm.scp(worker, f"/tmp/clone-{label}.npz", local / "residual.npz", from_remote=True)
    farm.scp(worker, f"/tmp/clone-{label}.json", local / "training_manifest.json", from_remote=True)
    farm.scp(worker, f"/tmp/clone-{label}.log", local / "training.log", from_remote=True)
    manifest = json.loads((local / "training_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "complete":
        raise RuntimeError(f"incomplete clone training: {submission_id}")
    return {
        "submission_id": submission_id,
        "worker": worker["name"],
        "model": str((local / "residual.npz").resolve()),
        "model_sha256": farm.sha256(local / "residual.npz"),
    }


def main() -> int:
    farm.OUTPUT = OUTPUT
    farm.REMOTE = "/mnt/ptcg-schema4-clones"
    farm.BUNDLE_PATHS = (
        "training/__init__.py", "training/schema4.py", "training/train_bc.py",
        "ptcg_ai", "vendor/cg", "data/grim_source_clones_v4",
        "artifacts/recovery_probes/extracted/a2_base/policy_weights.npz",
    )
    started = time.time()
    bundle, digest = farm.bundle()
    state = {"status": "running", "started_unix": started, "bundle_sha256": digest, "results": []}
    pending = iter(SOURCES)
    lock = threading.Lock()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(farm.WORKERS)) as pool:
            list(pool.map(lambda worker: farm.prepare(worker, bundle, digest), farm.WORKERS))

        def loop(worker):
            completed = []
            while True:
                with lock:
                    try:
                        source = next(pending)
                    except StopIteration:
                        return completed
                completed.append(train(worker, source, started))

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(farm.WORKERS)) as pool:
            for values in pool.map(loop, farm.WORKERS):
                state["results"].extend(values)
        if len(state["results"]) != len(SOURCES):
            raise RuntimeError("source clone farm returned an incomplete policy set")
        state["status"] = "complete"
        return 0
    except Exception as exc:
        state["status"] = "failed"
        state["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        state["ended_unix"] = time.time()
        state["conservative_estimated_spend_usd"] = (
            (state["ended_unix"] - started) / 3600 * len(farm.WORKERS) * farm.RATE
        )
        OUTPUT.mkdir(parents=True, exist_ok=True)
        (OUTPUT / "training_farm_manifest.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
        for worker in farm.WORKERS:
            farm.deallocate(worker)


if __name__ == "__main__":
    raise SystemExit(main())
