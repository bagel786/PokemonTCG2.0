#!/usr/bin/env python3
"""Train three schema-4 R1 heads on isolated on-demand Azure workers."""

from __future__ import annotations

import concurrent.futures
import gzip
import hashlib
import json
import shutil
import subprocess
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AZURE = shutil.which("az.cmd") or shutil.which("az") or "az"
KEY = ROOT / ".codex_tmp" / "azure_recovery_ed25519"
OUTPUT = ROOT / "artifacts" / "recovery_r1_azure"
REMOTE = "/mnt/ptcg-schema4"
SPEND_CAP = 140.0
RATE = 0.50
WORKERS = (
    {"name": "ptcg-train", "rg": "ptcg-train-south-rg", "ip": "20.225.52.72"},
    {"name": "grim-centralus", "rg": "ptcg-recovery-centralus-rg", "ip": "20.9.33.62"},
    {"name": "grim-eastus2", "rg": "ptcg-recovery-eastus2-rg", "ip": "20.97.180.234"},
    {"name": "grim-northcentralus", "rg": "ptcg-recovery-northcentralus-rg", "ip": "130.131.35.196"},
    {"name": "grim-westus2", "rg": "ptcg-recovery-westus2-rg", "ip": "20.69.108.1"},
)
BUNDLE_PATHS = (
    "training/__init__.py",
    "training/schema4.py",
    "training/train_bc.py",
    "ptcg_ai",
    "vendor/cg",
    "data/grim_strength_v4/r1_train.jsonl.gz",
    "data/grim_strength_v4/r1_validation.jsonl.gz",
    "data/grim_strength_v4/manifest.json",
    "artifacts/recovery_probes/extracted/a2_base/policy_weights.npz",
)
SEEDS = (20260808, 20260809, 20260810)


def run(command, *, timeout=600, capture=False):
    return subprocess.run(command, cwd=ROOT, check=True, text=True, timeout=timeout, capture_output=capture)


def ssh(worker, command, timeout=600):
    return run([
        "ssh", "-i", str(KEY), "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ServerAliveInterval=30", f"azureuser@{worker['ip']}", command,
    ], timeout=timeout, capture=True)


def scp(worker, source, destination, *, from_remote=False):
    left, right = (
        (f"azureuser@{worker['ip']}:{source}", str(destination)) if from_remote
        else (str(source), f"azureuser@{worker['ip']}:{destination}")
    )
    run(["scp", "-i", str(KEY), "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", left, right], timeout=3600)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bundle() -> tuple[Path, str]:
    missing = [path for path in BUNDLE_PATHS if not (ROOT / path).exists()]
    if missing:
        raise FileNotFoundError(f"schema-4 bundle inputs missing: {missing}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / "training_bundle.tar.gz"
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=6, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for relative in BUNDLE_PATHS:
                    source = ROOT / relative
                    files = [source] if source.is_file() else sorted(item for item in source.rglob("*") if item.is_file())
                    for item in files:
                        info = archive.gettarinfo(str(item), arcname=item.relative_to(ROOT).as_posix())
                        info.mtime = 0
                        info.uid = info.gid = 0
                        info.uname = info.gname = ""
                        with item.open("rb") as handle:
                            archive.addfile(info, handle)
    return path, sha256(path)


def prepare(worker, path, digest):
    run([AZURE, "vm", "start", "-g", worker["rg"], "-n", worker["name"], "--no-wait"], timeout=120)
    error = None
    for _ in range(40):
        try:
            ssh(worker, "true", timeout=15)
            break
        except Exception as exc:
            error = exc
            time.sleep(10)
    else:
        raise RuntimeError(f"worker failed to start: {worker['name']}: {error}")
    remote_bundle = f"/tmp/schema4-{digest}.tar.gz"
    scp(worker, path, remote_bundle)
    ssh(worker, (
        f"sudo mkdir -p {REMOTE} && sudo chown azureuser:azureuser {REMOTE} && "
        f"rm -rf {REMOTE}/training {REMOTE}/ptcg_ai {REMOTE}/vendor {REMOTE}/data {REMOTE}/artifacts && "
        f"tar -xzf {remote_bundle} -C {REMOTE} && "
        f"test \"$(sha256sum {remote_bundle} | cut -d' ' -f1)\" = {digest} && "
        "$HOME/ptcg-venv/bin/python -c 'import torch,numpy'"
    ), timeout=1800)


def train(worker, seed, started):
    projected = (time.time() - started + 4 * 3600) / 3600 * len(WORKERS) * RATE
    if projected >= SPEND_CAP:
        raise RuntimeError(f"projected spend ${projected:.2f} exceeds ${SPEND_CAP:.2f}")
    label = f"seed_{seed}"
    command = (
        f"cd {REMOTE} && export PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=8 MKL_NUM_THREADS=8 && "
        f"timeout 14400s $HOME/ptcg-venv/bin/python -m training.schema4 "
        "data/grim_strength_v4/r1_train.jsonl.gz data/grim_strength_v4/r1_validation.jsonl.gz "
        f"--base artifacts/recovery_probes/extracted/a2_base/policy_weights.npz --mode r1 --seed {seed} "
        f"--epochs 4 --batch-size 64 --learning-rate 0.00015 --output /tmp/{label}.npz "
        f"--manifest /tmp/{label}.json > /tmp/{label}.log 2>&1"
    )
    ssh(worker, command, timeout=15000)
    local = OUTPUT / label
    local.mkdir(parents=True, exist_ok=True)
    scp(worker, f"/tmp/{label}.npz", local / "residual.npz", from_remote=True)
    scp(worker, f"/tmp/{label}.json", local / "training_manifest.json", from_remote=True)
    scp(worker, f"/tmp/{label}.log", local / "training.log", from_remote=True)
    manifest = json.loads((local / "training_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "complete":
        raise RuntimeError(f"incomplete training manifest for {label}")
    return {
        "seed": seed,
        "worker": worker["name"],
        "model": str((local / "residual.npz").resolve()),
        "model_sha256": sha256(local / "residual.npz"),
        "manifest": str((local / "training_manifest.json").resolve()),
    }


def deallocate(worker):
    subprocess.run([AZURE, "vm", "deallocate", "-g", worker["rg"], "-n", worker["name"], "--no-wait"], cwd=ROOT, check=False)


def main() -> int:
    if len(WORKERS) < 4 or not KEY.exists():
        raise SystemExit("at least four workers and the recovery SSH key are required")
    started = time.time()
    path, digest = bundle()
    state = {
        "status": "running", "started_unix": started, "bundle_sha256": digest,
        "spend_cap_usd": SPEND_CAP, "workers": list(WORKERS), "results": [],
    }
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(WORKERS)) as pool:
            list(pool.map(lambda worker: prepare(worker, path, digest), WORKERS))
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(train, WORKERS[index], seed, started) for index, seed in enumerate(SEEDS)]
            state["results"] = [future.result() for future in futures]
        if len(state["results"]) != 3:
            raise RuntimeError("schema-4 training returned an incomplete ensemble")
        state["status"] = "complete"
        return 0
    except Exception as exc:
        state["status"] = "failed"
        state["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        state["ended_unix"] = time.time()
        state["conservative_estimated_spend_usd"] = (
            (state["ended_unix"] - started) / 3600 * len(WORKERS) * RATE
        )
        OUTPUT.mkdir(parents=True, exist_ok=True)
        (OUTPUT / "training_farm_manifest.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
        for worker in WORKERS:
            deallocate(worker)


if __name__ == "__main__":
    raise SystemExit(main())
