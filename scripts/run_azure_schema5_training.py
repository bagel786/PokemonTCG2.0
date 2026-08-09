#!/usr/bin/env python3
"""Train schema-5 M0 families and independent policy clones on Azure."""

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
OUTPUT = ROOT / "artifacts" / "schema5_azure"
REMOTE = "/mnt/ptcg-schema5"
SPEND_CAP = 140.0
PRIOR_ESTIMATED_SPEND = 14.71
RATE_PER_WORKER_HOUR = 0.50
WORKERS = (
    {"name": "ptcg-train", "rg": "ptcg-train-south-rg", "ip": "20.225.52.72"},
    {"name": "grim-centralus", "rg": "ptcg-recovery-centralus-rg", "ip": "20.9.33.62"},
    {"name": "grim-eastus2", "rg": "ptcg-recovery-eastus2-rg", "ip": "20.97.180.234"},
    {"name": "grim-northcentralus", "rg": "ptcg-recovery-northcentralus-rg", "ip": "130.131.35.196"},
    {"name": "grim-westus2", "rg": "ptcg-recovery-westus2-rg", "ip": "20.69.108.1"},
)
FAMILIES = (
    "matsurih_only",
    "sixth_sense_only",
    "yaroslav_only",
    "less_only",
    "oshbocker_only",
    "at_kdcyberdude_only",
    "ar_sekkat_only",
    "primary_first_nishimatsu_second",
    "source_balanced_mix",
    "flg_variant_only",
)
CLONES = (55308008, 55316998, 55321109, 55325981)
CANDIDATE_SEEDS = tuple(range(2026080801, 2026080807))
CLONE_SEEDS = tuple(range(2026080821, 2026080824))
BUNDLE_PATHS = (
    "training/__init__.py",
    "training/schema5.py",
    "training/train_bc.py",
    "training/lucario_data.py",
    "ptcg_ai",
    "vendor/cg",
    "data/grim_breakthrough_v5",
)


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
        raise FileNotFoundError(f"schema-5 bundle inputs missing: {missing}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / "training_bundle.tar.gz"
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=6, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for relative in BUNDLE_PATHS:
                    source = ROOT / relative
                    files = [source] if source.is_file() else sorted(
                        item for item in source.rglob("*")
                        if item.is_file() and "__pycache__" not in item.parts and item.suffix != ".pyc"
                    )
                    for item in files:
                        info = archive.gettarinfo(str(item), arcname=item.relative_to(ROOT).as_posix())
                        info.mtime = 0
                        info.uid = info.gid = 0
                        info.uname = info.gname = ""
                        with item.open("rb") as handle:
                            archive.addfile(info, handle)
    return path, sha256(path)


def prepare(worker, path, digest):
    run([AZURE, "vm", "start", "-g", worker["rg"], "-n", worker["name"], "--no-wait"], timeout=180)
    last_error = None
    for _ in range(45):
        try:
            ssh(worker, "true", timeout=15)
            break
        except Exception as exc:
            last_error = exc
            time.sleep(10)
    else:
        raise RuntimeError(f"worker failed to start: {worker['name']}: {last_error}")
    remote_bundle = f"/tmp/schema5-{digest}.tar.gz"
    scp(worker, path, remote_bundle)
    ssh(worker, (
        f"sudo mkdir -p {REMOTE} && sudo chown azureuser:azureuser {REMOTE} && "
        f"rm -rf {REMOTE}/training {REMOTE}/ptcg_ai {REMOTE}/vendor {REMOTE}/data && "
        f"tar -xzf {remote_bundle} -C {REMOTE} && "
        f"test \"$(sha256sum {remote_bundle} | cut -d' ' -f1)\" = {digest} && "
        "$HOME/ptcg-venv/bin/python -c 'import torch,numpy'"
    ), timeout=1800)


def jobs():
    result = []
    for family in FAMILIES:
        for seed in CANDIDATE_SEEDS:
            result.append({
                "kind": "candidate", "name": family, "seed": seed, "epochs": 8,
                "train": f"data/grim_breakthrough_v5/families/{family}/train.jsonl.gz",
                "validation": f"data/grim_breakthrough_v5/families/{family}/validation.jsonl.gz",
            })
    for submission_id in CLONES:
        for seed in CLONE_SEEDS:
            result.append({
                "kind": "clone", "name": str(submission_id), "seed": seed, "epochs": 10,
                "train": f"data/grim_breakthrough_v5/clones/{submission_id}/train.jsonl.gz",
                "validation": f"data/grim_breakthrough_v5/clones/{submission_id}/qualification.jsonl.gz",
            })
    return result


def train_job(worker, job, started):
    projected = PRIOR_ESTIMATED_SPEND + (time.time() - started + 8 * 3600) / 3600 * len(WORKERS) * RATE_PER_WORKER_HOUR
    if projected >= SPEND_CAP:
        raise RuntimeError(f"projected cumulative spend ${projected:.2f} exceeds ${SPEND_CAP:.2f}")
    label = f"{job['kind']}_{job['name']}_seed_{job['seed']}"
    command = (
        f"cd {REMOTE} && export PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=8 MKL_NUM_THREADS=8 && "
        f"timeout 21600s $HOME/ptcg-venv/bin/python -m training.schema5 {job['train']} "
        f"--validation {job['validation']} --seed {job['seed']} --epochs {job['epochs']} "
        f"--batch-size 96 --learning-rate 0.0002 --checkpoint-metric agreement "
        f"--output /tmp/{label}.npz --manifest /tmp/{label}.json > /tmp/{label}.log 2>&1"
    )
    ssh(worker, command, timeout=22200)
    local = OUTPUT / job["kind"] / job["name"] / f"seed_{job['seed']}"
    local.mkdir(parents=True, exist_ok=True)
    for remote_name, local_name in (
        (f"/tmp/{label}.npz", "direct.npz"),
        (f"/tmp/{label}.json", "training_manifest.json"),
        (f"/tmp/{label}.log", "training.log"),
    ):
        scp(worker, remote_name, local / local_name, from_remote=True)
    manifest = json.loads((local / "training_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "complete" or int(manifest.get("schema_version", -1)) != 5:
        raise RuntimeError(f"incomplete schema-5 manifest for {label}")
    return {
        **job, "worker": worker["name"],
        "model": str((local / "direct.npz").resolve()),
        "model_sha256": sha256(local / "direct.npz"),
        "selected_complete_agreement": manifest["selected_complete_agreement"],
    }


def worker_queue(worker, queue, started):
    completed = []
    for job in queue:
        completed.append(train_job(worker, job, started))
    return completed


def deallocate(worker):
    subprocess.run([AZURE, "vm", "deallocate", "-g", worker["rg"], "-n", worker["name"], "--no-wait"], cwd=ROOT, check=False)


def main() -> int:
    if len(WORKERS) < 4 or not KEY.exists():
        raise SystemExit("at least four workers and the recovery SSH key are required")
    all_jobs = jobs()
    queues = [[] for _ in WORKERS]
    for index, job in enumerate(all_jobs):
        queues[index % len(WORKERS)].append(job)
    started = time.time()
    bundle_path, digest = bundle()
    state = {
        "status": "running", "started_unix": started, "bundle_sha256": digest,
        "spend_cap_usd": SPEND_CAP, "prior_estimated_spend_usd": PRIOR_ESTIMATED_SPEND,
        "workers": list(WORKERS), "job_count": len(all_jobs), "results": [],
    }
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(WORKERS)) as pool:
            list(pool.map(lambda worker: prepare(worker, bundle_path, digest), WORKERS))
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(WORKERS)) as pool:
            futures = [pool.submit(worker_queue, worker, queue, started) for worker, queue in zip(WORKERS, queues)]
            state["results"] = [result for future in futures for result in future.result()]
        if len(state["results"]) != len(all_jobs):
            raise RuntimeError("Azure returned an incomplete schema-5 job matrix")
        state["status"] = "complete"
        return 0
    except Exception as exc:
        state["status"] = "failed"
        state["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        state["ended_unix"] = time.time()
        state["new_estimated_spend_usd"] = (state["ended_unix"] - started) / 3600 * len(WORKERS) * RATE_PER_WORKER_HOUR
        state["cumulative_estimated_spend_usd"] = PRIOR_ESTIMATED_SPEND + state["new_estimated_spend_usd"]
        OUTPUT.mkdir(parents=True, exist_ok=True)
        (OUTPUT / "training_farm_manifest.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
        for worker in WORKERS:
            deallocate(worker)


if __name__ == "__main__":
    raise SystemExit(main())
