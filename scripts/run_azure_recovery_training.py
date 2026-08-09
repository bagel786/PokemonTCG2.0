#!/usr/bin/env python3
"""Train the six schema-3 B candidates on the on-demand Azure worker pool."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import shutil
import subprocess
import tarfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AZURE = shutil.which("az.cmd") or shutil.which("az") or "az"
KEY = ROOT / ".codex_tmp" / "azure_recovery_ed25519"
OUTPUT = ROOT / "artifacts" / "recovery_training_azure"
REMOTE = "/mnt/ptcg-recovery-training"
SPEND_CAP_USD = 140.0
RATE_USD_PER_WORKER_HOUR = 0.50
WORKERS = (
    {"name": "ptcg-train", "rg": "ptcg-train-south-rg", "ip": "20.225.52.72"},
    {"name": "grim-centralus", "rg": "ptcg-recovery-centralus-rg", "ip": "20.9.33.62"},
    {"name": "grim-eastus2", "rg": "ptcg-recovery-eastus2-rg", "ip": "20.97.180.234"},
    {"name": "grim-northcentralus", "rg": "ptcg-recovery-northcentralus-rg", "ip": "130.131.35.196"},
    {"name": "grim-westus2", "rg": "ptcg-recovery-westus2-rg", "ip": "20.69.108.1"},
)
BUNDLE_PATHS = (
    "training/__init__.py",
    "training/train_recovery_candidates.py",
    "training/train_bc.py",
    "training/lucario_data.py",
    "ptcg_ai",
    "vendor/cg",
    "artifacts/recovery_training/datasets/b1_train.jsonl.gz",
    "artifacts/recovery_training/datasets/b2_train.jsonl.gz",
    "artifacts/recovery_training/datasets/assembly_manifest.json",
    "artifacts/recovery_schema3/d842_schema3_zero_init.npz",
    "data/grim_daily_v3/splits/validation.jsonl.gz",
)


def run(command: list[str], timeout: int = 600, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        command, cwd=ROOT, check=True, text=True, timeout=timeout,
        capture_output=capture,
    )


def ssh(worker: dict, command: str, timeout: int = 600) -> subprocess.CompletedProcess:
    return run([
        "ssh", "-i", str(KEY), "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new", "-o", "ServerAliveInterval=30",
        f"azureuser@{worker['ip']}", command,
    ], timeout=timeout, capture=True)


def scp(worker: dict, source: Path | str, destination: Path | str, *, from_remote: bool = False) -> None:
    if from_remote:
        left, right = f"azureuser@{worker['ip']}:{source}", str(destination)
    else:
        left, right = str(source), f"azureuser@{worker['ip']}:{destination}"
    run([
        "scp", "-i", str(KEY), "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new", left, right,
    ], timeout=3600)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_bundle() -> tuple[Path, str]:
    missing = [name for name in BUNDLE_PATHS if not (ROOT / name).exists()]
    if missing:
        raise FileNotFoundError(f"recovery-training bundle inputs are missing: {missing}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    bundle = OUTPUT / "training_bundle.tar.gz"
    with tarfile.open(bundle, "w:gz", compresslevel=6) as archive:
        for name in BUNDLE_PATHS:
            path = ROOT / name
            archive.add(path, arcname=name, recursive=True)
    return bundle, sha256(bundle)


def start_and_prepare(worker: dict, bundle: Path, bundle_hash: str) -> None:
    run([AZURE, "vm", "start", "-g", worker["rg"], "-n", worker["name"], "--no-wait"], timeout=120)
    last_error = None
    for _ in range(40):
        try:
            ssh(worker, "true", timeout=15)
            break
        except Exception as exc:  # VM boot/SSH readiness is transient.
            last_error = exc
            time.sleep(10)
    else:
        raise RuntimeError(f"worker did not become SSH-ready: {worker['name']}: {last_error}")
    remote_bundle = f"/tmp/recovery-training-{bundle_hash}.tar.gz"
    scp(worker, bundle, remote_bundle)
    command = (
        f"sudo mkdir -p {REMOTE} && sudo chown azureuser:azureuser {REMOTE} && "
        f"rm -rf {REMOTE}/training {REMOTE}/ptcg_ai {REMOTE}/vendor "
        f"{REMOTE}/artifacts {REMOTE}/data && "
        f"tar -xzf {remote_bundle} -C {REMOTE} && "
        "$HOME/ptcg-venv/bin/pip install -q --index-url "
        "https://download.pytorch.org/whl/cpu torch && "
        f"cd {REMOTE} && test \"$(sha256sum {remote_bundle} | cut -d' ' -f1)\" = {bundle_hash}"
    )
    ssh(worker, command, timeout=3600)


def task_queue() -> list[dict]:
    return [
        {"family": family, "seed": seed}
        for family in ("b1", "b2")
        for seed in (20260807, 20260808, 20260809)
    ]


def run_task(worker: dict, task: dict, started: float) -> dict:
    projected = (time.time() - started + 6 * 3600) / 3600 * len(WORKERS) * RATE_USD_PER_WORKER_HOUR
    if projected >= SPEND_CAP_USD:
        raise RuntimeError(f"projected spend ${projected:.2f} exceeds ${SPEND_CAP_USD:.2f}")
    label = f"{task['family']}_seed_{task['seed']}"
    command = (
        f"cd {REMOTE} && export PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=8 MKL_NUM_THREADS=8 && "
        f"timeout 21600s $HOME/ptcg-venv/bin/python training/train_recovery_candidates.py "
        "--skip-assembly --output-dir artifacts/recovery_training "
        "--validation data/grim_daily_v3/splits/validation.jsonl.gz "
        "--anchor artifacts/recovery_schema3/d842_schema3_zero_init.npz "
        f"--families {task['family']} --seeds {task['seed']} --epochs 3 --batch-size 256 "
        f">/tmp/{label}.log 2>&1"
    )
    ssh(worker, command, timeout=22000)
    local_dir = OUTPUT / label
    local_dir.mkdir(parents=True, exist_ok=True)
    remote_model = f"{REMOTE}/artifacts/recovery_training/{task['family']}/seed_{task['seed']}/policy_weights.npz"
    scp(worker, remote_model, local_dir / "policy_weights.npz", from_remote=True)
    scp(worker, f"{REMOTE}/artifacts/recovery_training/training_manifest.json", local_dir / "training_manifest.json", from_remote=True)
    scp(worker, f"/tmp/{label}.log", local_dir / "training.log", from_remote=True)
    report = json.loads((local_dir / "training_manifest.json").read_text())["runs"][0]
    if report["sha256"] != sha256(local_dir / "policy_weights.npz"):
        raise RuntimeError(f"model hash mismatch after Azure transfer: {label}")
    return {
        "label": label,
        "worker": worker["name"],
        "model": str((local_dir / "policy_weights.npz").resolve()),
        "model_sha256": report["sha256"],
        "report": report,
    }


def deallocate(worker: dict) -> None:
    subprocess.run(
        [AZURE, "vm", "deallocate", "-g", worker["rg"], "-n", worker["name"], "--no-wait"],
        cwd=ROOT, check=False,
    )


def main() -> int:
    if len(WORKERS) < 4 or not KEY.exists():
        raise SystemExit("at least four workers and the recovery SSH key are required")
    started = time.time()
    bundle, bundle_hash = build_bundle()
    state = {
        "started_unix": started,
        "source_commit": run(["git", "rev-parse", "HEAD"], capture=True).stdout.strip(),
        "bundle_sha256": bundle_hash,
        "workers": list(WORKERS),
        "spend_cap_usd": SPEND_CAP_USD,
        "results": [],
    }
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(WORKERS)) as pool:
            list(pool.map(lambda worker: start_and_prepare(worker, bundle, bundle_hash), WORKERS))
        tasks = iter(task_queue())
        lock = threading.Lock()

        def worker_loop(worker: dict) -> list[dict]:
            completed = []
            while True:
                with lock:
                    try:
                        task = next(tasks)
                    except StopIteration:
                        return completed
                completed.append(run_task(worker, task, started))

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(WORKERS)) as pool:
            for results in pool.map(worker_loop, WORKERS):
                state["results"].extend(results)
        if len(state["results"]) != 6:
            raise RuntimeError("training farm returned an incomplete candidate set")
        state["status"] = "complete"
        return 0
    except Exception as exc:
        state["status"] = "failed"
        state["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        state["ended_unix"] = time.time()
        state["conservative_estimated_spend_usd"] = (
            (state["ended_unix"] - started) / 3600 * len(WORKERS) * RATE_USD_PER_WORKER_HOUR
        )
        OUTPUT.mkdir(parents=True, exist_ok=True)
        (OUTPUT / "training_farm_manifest.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
        for worker in WORKERS:
            deallocate(worker)


if __name__ == "__main__":
    raise SystemExit(main())
