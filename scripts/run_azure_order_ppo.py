#!/usr/bin/env python3
"""Run the three strict 5k-game order-PPO generations on five Azure workers."""

from __future__ import annotations

import concurrent.futures
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "order_ppo" / "azure"
REMOTE = "/mnt/ptcg-order-ppo"
KEY = ROOT / ".codex_tmp" / "azure_recovery_ed25519"
AZURE = shutil.which("az.cmd") or shutil.which("az.bat") or shutil.which("az") or "az"
RATE_PER_WORKER_HOUR = 0.50
# The user expanded the experiment authorization on 2026-08-09 after the
# original $30 run had accumulated reusable evaluation evidence. Keep a
# margin against the approximately $130 of credits they reported remaining.
SPEND_CAP_USD = 100.0
GENERATION_GAMES = 5_000
SHARDS_PER_GENERATION = 8

WORKERS = [
    {"name": "ptcg-train", "rg": "ptcg-train-south-rg", "ip": "20.225.52.72"},
    {"name": "grim-centralus", "rg": "ptcg-recovery-centralus-rg", "ip": "20.9.33.62"},
    {"name": "grim-eastus2", "rg": "ptcg-recovery-eastus2-rg", "ip": "20.97.180.234"},
    {"name": "grim-northcentralus", "rg": "ptcg-recovery-northcentralus-rg", "ip": "130.131.35.196"},
    {"name": "grim-westus2", "rg": "ptcg-recovery-westus2-rg", "ip": "20.69.108.1"},
]

BUNDLE_PATHS = [
    "training/__init__.py", "training/azure_guard.py", "training/train_bc.py",
    "training/order_ppo.py", "training/collect_order_ppo.py", "training/order_ppo_opponents.json",
    "ptcg_ai", "vendor/cg", "artifacts/recovery_probes/extracted/control",
    "artifacts/recovery_probes/extracted/a2", "artifacts/recovery_r0_package/extracted/r0_play_binding",
    "artifacts/recovery_final/opponents", "freshstart/elite_submissions/alakazam_2_4a",
]


def run(command: list[str], timeout: int = 600, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(command)}\n{result.stderr[-4000:]}")
    return result


def ssh(worker: dict, command: str, timeout: int = 600) -> subprocess.CompletedProcess:
    return run([
        "ssh", "-i", str(KEY), "-o", "StrictHostKeyChecking=accept-new", "-o", "ServerAliveInterval=30",
        f"azureuser@{worker['ip']}", command,
    ], timeout=timeout)


def scp_to(worker: dict, source: Path, destination: str) -> None:
    run(["scp", "-i", str(KEY), "-o", "StrictHostKeyChecking=accept-new", str(source),
         f"azureuser@{worker['ip']}:{destination}"], timeout=1200)


def scp_from(worker: dict, source: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    run(["scp", "-i", str(KEY), "-o", "StrictHostKeyChecking=accept-new",
         f"azureuser@{worker['ip']}:{source}", str(destination)], timeout=1200)


def check_budget(started: float, allowance_hours: float = 0.0) -> None:
    projected = ((time.time() - started) / 3600 + allowance_hours) * len(WORKERS) * RATE_PER_WORKER_HOUR
    if projected >= SPEND_CAP_USD:
        raise RuntimeError(f"projected additional spend ${projected:.2f} reaches ${SPEND_CAP_USD:.2f} cap")


def build_bundle() -> tuple[Path, str]:
    path = OUTPUT / "source_bundle.tar.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    for relative in BUNDLE_PATHS:
        source = ROOT / relative
        if not source.exists():
            raise FileNotFoundError(source)
        files.extend([source] if source.is_file() else [item for item in source.rglob("*") if item.is_file()])
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for item in sorted(set(files)):
                    if "__pycache__" in item.parts or item.suffix == ".pyc":
                        continue
                    info = archive.gettarinfo(str(item), arcname=item.relative_to(ROOT).as_posix())
                    info.mtime = 0; info.uid = 0; info.gid = 0; info.uname = ""; info.gname = ""
                    with item.open("rb") as handle:
                        archive.addfile(info, handle)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def start(worker: dict) -> None:
    run([AZURE, "vm", "start", "-g", worker["rg"], "-n", worker["name"], "--no-wait"], timeout=180)


def deallocate(worker: dict) -> None:
    subprocess.run([AZURE, "vm", "deallocate", "-g", worker["rg"], "-n", worker["name"], "--no-wait"],
                   cwd=ROOT, capture_output=True, text=True)


def prepare(worker: dict, bundle: Path, digest: str) -> None:
    last_error: Exception | None = None
    for _ in range(45):
        try:
            ssh(worker, "true", timeout=15)
            break
        except Exception as exc:
            last_error = exc
            time.sleep(10)
    else:
        raise RuntimeError(f"worker did not become ready: {worker['name']}: {last_error}")
    remote_bundle = f"/tmp/order-ppo-{digest}.tar.gz"
    scp_to(worker, bundle, remote_bundle)
    ssh(worker, (
        f"sudo mkdir -p {REMOTE} && sudo chown azureuser:azureuser {REMOTE} && "
        f"find {REMOTE} -mindepth 1 -maxdepth 1 -exec rm -rf -- {{}} + && "
        f"tar -xzf {remote_bundle} -C {REMOTE} && "
        f"test \"$(sha256sum {remote_bundle} | cut -d' ' -f1)\" = {digest} && "
        "$HOME/ptcg-venv/bin/python -c 'import torch,numpy'"
    ), timeout=1800)


def rollout_jobs() -> list[dict]:
    generations = [
        {"name": "first", "order": "first", "seed": 2026080811},
        {"name": "second_a", "order": "second", "seed": 2026080821},
        {"name": "second_b", "order": "second", "seed": 2026080831},
    ]
    jobs = []
    for generation in generations:
        for shard in range(SHARDS_PER_GENERATION):
            jobs.append({**generation, "shard": shard})
    return jobs


def collect(worker: dict, job: dict, started: float) -> dict:
    check_budget(started, allowance_hours=4.0)
    label = f"{job['name']}_shard_{job['shard']}"
    output = f"/tmp/{label}.jsonl.gz"
    command = (
        f"cd {REMOTE} && export PTCG_AZURE_RUN=1 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 && "
        f"timeout 16200s $HOME/ptcg-venv/bin/python -m training.collect_order_ppo "
        "--actor artifacts/recovery_probes/extracted/control/policy_weights.npz "
        "--deck artifacts/recovery_probes/extracted/control/deck.csv "
        "--opponent-spec training/order_ppo_opponents.json "
        f"--actual-order {job['order']} --games {GENERATION_GAMES} "
        f"--shard-count {SHARDS_PER_GENERATION} --shard-index {job['shard']} "
        f"--temperature 0.70 --seed {job['seed']} --output {output} > /tmp/{label}.log 2>&1"
    )
    ssh(worker, command, timeout=16800)
    local = OUTPUT / "rollouts" / job["name"] / f"shard_{job['shard']}.jsonl.gz"
    scp_from(worker, output, local)
    scp_from(worker, output + ".json", local.with_suffix(local.suffix + ".json"))
    scp_from(worker, f"/tmp/{label}.log", local.with_suffix(".log"))
    return {"job": job, "worker": worker["name"], "output": str(local)}


def train(worker: dict, name: str, order: str, seed: int, started: float) -> dict:
    check_budget(started, allowance_hours=0.5)
    for shard in range(SHARDS_PER_GENERATION):
        source = OUTPUT / "rollouts" / name / f"shard_{shard}.jsonl.gz"
        scp_to(worker, source, f"/tmp/{name}_shard_{shard}.jsonl.gz")
    rollout_args = " ".join(
        f"--rollouts /tmp/{name}_shard_{shard}.jsonl.gz" for shard in range(SHARDS_PER_GENERATION)
    )
    command = (
        f"cd {REMOTE} && export PTCG_AZURE_RUN=1 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=8 MKL_NUM_THREADS=8 && "
        f"timeout 3600s $HOME/ptcg-venv/bin/python -m training.order_ppo "
        "--initial-model artifacts/recovery_probes/extracted/control/policy_weights.npz "
        f"{rollout_args} --actual-order {order} --games {GENERATION_GAMES} "
        f"--output /tmp/{name}.npz --manifest /tmp/{name}.json --seed {seed} > /tmp/{name}_train.log 2>&1"
    )
    local = OUTPUT / "checkpoints" / name
    try:
        ssh(worker, command, timeout=3900)
    except Exception:
        # Preserve the remote traceback before fail-safe VM deallocation.  A
        # training failure otherwise leaves only the SSH exit code locally.
        try:
            scp_from(worker, f"/tmp/{name}_train.log", local / "training.log")
        except Exception:
            pass
        raise
    scp_from(worker, f"/tmp/{name}.npz", local / "policy_weights.npz")
    scp_from(worker, f"/tmp/{name}.json", local / "training_manifest.json")
    scp_from(worker, f"/tmp/{name}_train.log", local / "training.log")
    return {"name": name, "worker": worker["name"], "path": str(local / "policy_weights.npz")}


def main() -> int:
    if len(WORKERS) != 5 or not KEY.exists():
        raise RuntimeError("five workers and the recovery SSH key are required")
    started = time.time()
    bundle, digest = build_bundle()
    state = {
        "status": "starting", "started_unix": started, "bundle_sha256": digest,
        "workers": WORKERS, "spend_cap_usd": SPEND_CAP_USD,
        "rate_per_worker_hour": RATE_PER_WORKER_HOUR, "rollouts": [], "checkpoints": [],
    }
    state_path = OUTPUT / "run_manifest.json"
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            list(pool.map(start, WORKERS))
        time.sleep(20)
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            list(pool.map(lambda worker: prepare(worker, bundle, digest), WORKERS))
        jobs = rollout_jobs()
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            futures = [pool.submit(collect, WORKERS[index % 5], job, started) for index, job in enumerate(jobs)]
            for future in concurrent.futures.as_completed(futures):
                state["rollouts"].append(future.result())
                state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        training_jobs = [("first", "first", 2026080812), ("second_a", "second", 2026080822), ("second_b", "second", 2026080832)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(train, WORKERS[index], *job, started) for index, job in enumerate(training_jobs)]
            for future in concurrent.futures.as_completed(futures):
                state["checkpoints"].append(future.result())
        state["status"] = "complete"
        return 0
    except Exception as exc:
        state["status"] = "failed"
        state["error"] = repr(exc)
        raise
    finally:
        state["ended_unix"] = time.time()
        state["conservative_estimated_spend_usd"] = (
            (state["ended_unix"] - started) / 3600 * len(WORKERS) * RATE_PER_WORKER_HOUR
        )
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            list(pool.map(deallocate, WORKERS))


if __name__ == "__main__":
    raise SystemExit(main())
