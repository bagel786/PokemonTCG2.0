#!/usr/bin/env python3
"""Train relational D1 teacher seeds and relational opponent clones on Azure."""

from __future__ import annotations

import argparse
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
OUTPUT = ROOT / "artifacts" / "d1_relational_azure"
REMOTE = "/mnt/ptcg-d1"
SPEND_CAP = 140.0
PRIOR_ESTIMATED_SPEND = 15.48
RATE_PER_WORKER_HOUR = .50
WORKERS = (
    {"name": "ptcg-train", "rg": "ptcg-train-south-rg", "ip": "20.225.52.72"},
    {"name": "grim-centralus", "rg": "ptcg-recovery-centralus-rg", "ip": "20.9.33.62"},
    {"name": "grim-eastus2", "rg": "ptcg-recovery-eastus2-rg", "ip": "20.97.180.234"},
    {"name": "grim-northcentralus", "rg": "ptcg-recovery-northcentralus-rg", "ip": "130.131.35.196"},
    {"name": "grim-westus2", "rg": "ptcg-recovery-westus2-rg", "ip": "20.69.108.1"},
)
CANDIDATE_INITIAL = "artifacts/schema5_azure/candidate/source_balanced_mix/seed_2026080805/direct.npz"
CLONE_INITIALS = {
    55308008: "artifacts/schema5_azure/clone/55308008/seed_2026080822/direct.npz",
    55316998: "artifacts/schema5_azure/clone/55316998/seed_2026080822/direct.npz",
    55321109: "artifacts/schema5_azure/clone/55321109/seed_2026080822/direct.npz",
    55325981: "artifacts/schema5_azure/clone/55325981/seed_2026080821/direct.npz",
}
BUNDLE_PATHS = (
    "training/__init__.py", "training/schema5.py", "training/schema5_relational.py",
    "training/train_bc.py", "training/lucario_data.py", "ptcg_ai", "vendor/cg",
    "data/grim_breakthrough_v5", CANDIDATE_INITIAL, *CLONE_INITIALS.values(),
)


def run(command, *, timeout=600, capture=False):
    return subprocess.run(command, cwd=ROOT, check=True, text=True, timeout=timeout, capture_output=capture)


def ssh(worker, command, timeout=600):
    return run(["ssh", "-i", str(KEY), "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
                "-o", "ServerAliveInterval=30", f"azureuser@{worker['ip']}", command], timeout=timeout, capture=True)


def scp(worker, source, destination, *, from_remote=False):
    left, right = ((f"azureuser@{worker['ip']}:{source}", str(destination)) if from_remote
                   else (str(source), f"azureuser@{worker['ip']}:{destination}"))
    run(["scp", "-i", str(KEY), "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", left, right], timeout=3600)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def bundle():
    missing = [path for path in BUNDLE_PATHS if not (ROOT / path).exists()]
    if missing:
        raise FileNotFoundError(missing)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    destination = OUTPUT / "bundle.tar.gz"
    with destination.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for relative in BUNDLE_PATHS:
                    source = ROOT / relative
                    files = [source] if source.is_file() else sorted(
                        path for path in source.rglob("*") if path.is_file()
                        and "__pycache__" not in path.parts and path.suffix != ".pyc"
                    )
                    for path in files:
                        info = archive.gettarinfo(str(path), arcname=path.relative_to(ROOT).as_posix())
                        info.mtime = info.uid = info.gid = 0; info.uname = info.gname = ""
                        with path.open("rb") as handle:
                            archive.addfile(info, handle)
    return destination, sha256(destination)


def jobs():
    result = []
    for seed in range(2026080901, 2026080907):
        result.append({"kind": "candidate", "name": "source_balanced", "seed": seed,
                       "initial": CANDIDATE_INITIAL,
                       "train": "data/grim_breakthrough_v5/families/source_balanced_mix/train.jsonl.gz",
                       "validation": "data/grim_breakthrough_v5/families/source_balanced_mix/validation.jsonl.gz"})
    for submission, initial in CLONE_INITIALS.items():
        for seed in range(2026080921, 2026080924):
            result.append({"kind": "clone", "name": str(submission), "seed": seed, "initial": initial,
                           "train": f"data/grim_breakthrough_v5/clones/{submission}/train.jsonl.gz",
                           "validation": f"data/grim_breakthrough_v5/clones/{submission}/qualification.jsonl.gz"})
    return result


def prepare(worker, bundle_path, digest):
    run([AZURE, "vm", "start", "-g", worker["rg"], "-n", worker["name"], "--no-wait"], timeout=180)
    for _ in range(45):
        try:
            ssh(worker, "true", timeout=15); break
        except Exception:
            time.sleep(10)
    else:
        raise RuntimeError(f"worker unavailable: {worker['name']}")
    remote_bundle = f"/tmp/d1-{digest}.tar.gz"
    scp(worker, bundle_path, remote_bundle)
    ssh(worker, f"sudo mkdir -p {REMOTE} && sudo chown azureuser:azureuser {REMOTE} && "
                f"rm -rf {REMOTE}/* && tar -xzf {remote_bundle} -C {REMOTE} && "
                f"test \"$(sha256sum {remote_bundle} | cut -d' ' -f1)\" = {digest} && "
                "$HOME/ptcg-venv/bin/python -c 'import torch,numpy'", timeout=1800)


def train(worker, job, started):
    projected = PRIOR_ESTIMATED_SPEND + (time.time() - started + 4 * 3600) / 3600 * len(WORKERS) * RATE_PER_WORKER_HOUR
    if projected >= SPEND_CAP:
        raise RuntimeError(f"projected spend ${projected:.2f} exceeds ${SPEND_CAP:.2f}")
    label = f"{job['kind']}_{job['name']}_{job['seed']}"
    command = (f"cd {REMOTE} && export OMP_NUM_THREADS=8 MKL_NUM_THREADS=8 PYTHONDONTWRITEBYTECODE=1 && "
               f"timeout 21600s $HOME/ptcg-venv/bin/python -m training.schema5_relational {job['train']} "
               f"--validation {job['validation']} --initial-model {job['initial']} --seed {job['seed']} "
               f"--epochs 12 --batch-size 64 --learning-rate 0.0001 --output /tmp/{label}.npz "
               f"--manifest /tmp/{label}.json > /tmp/{label}.log 2>&1")
    ssh(worker, command, timeout=22200)
    local = OUTPUT / job["kind"] / job["name"] / f"seed_{job['seed']}"
    local.mkdir(parents=True, exist_ok=True)
    for remote, name in ((f"/tmp/{label}.npz", "direct.npz"),
                         (f"/tmp/{label}.json", "training_manifest.json"),
                         (f"/tmp/{label}.log", "training.log")):
        scp(worker, remote, local / name, from_remote=True)
    manifest = json.loads((local / "training_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "complete" or manifest.get("direct_model_version") != 2:
        raise RuntimeError(f"invalid D1 result {label}")
    return {**job, "worker": worker["name"], "model": str((local / "direct.npz").resolve()),
            "model_sha256": sha256(local / "direct.npz"),
            "agreement": manifest["selected_complete_agreement"]}


def deallocate(worker):
    subprocess.run([AZURE, "vm", "deallocate", "-g", worker["rg"], "-n", worker["name"], "--no-wait"], cwd=ROOT, check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--describe", action="store_true", help="print the immutable job matrix without starting VMs")
    args = parser.parse_args()
    matrix = jobs()
    if args.describe:
        print(json.dumps({"workers": WORKERS, "jobs": matrix}, indent=2)); return 0
    if len(WORKERS) < 4 or not KEY.exists():
        raise SystemExit("at least four workers and the SSH key are required")
    started = time.time(); bundle_path, digest = bundle()
    state = {"status": "running", "started_unix": started, "bundle_sha256": digest,
             "job_count": len(matrix), "results": [], "spend_cap_usd": SPEND_CAP}
    queues = [[] for _ in WORKERS]
    for index, job in enumerate(matrix): queues[index % len(WORKERS)].append(job)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(WORKERS)) as pool:
            list(pool.map(lambda worker: prepare(worker, bundle_path, digest), WORKERS))
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(WORKERS)) as pool:
            futures = [pool.submit(lambda w, q: [train(w, job, started) for job in q], worker, queue)
                       for worker, queue in zip(WORKERS, queues)]
            state["results"] = [row for future in futures for row in future.result()]
        if len(state["results"]) != len(matrix): raise RuntimeError("incomplete D1 matrix")
        state["status"] = "complete"; return 0
    except Exception as exc:
        state["status"] = "failed"; state["error"] = f"{type(exc).__name__}: {exc}"; raise
    finally:
        state["ended_unix"] = time.time()
        state["new_estimated_spend_usd"] = (state["ended_unix"] - started) / 3600 * len(WORKERS) * RATE_PER_WORKER_HOUR
        state["cumulative_estimated_spend_usd"] = PRIOR_ESTIMATED_SPEND + state["new_estimated_spend_usd"]
        OUTPUT.mkdir(parents=True, exist_ok=True)
        (OUTPUT / "training_farm_manifest.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        for worker in WORKERS: deallocate(worker)


if __name__ == "__main__":
    raise SystemExit(main())
