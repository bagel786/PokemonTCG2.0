#!/usr/bin/env python3
"""Run immutable independent probe shards on the on-demand Azure recovery farm."""

from __future__ import annotations

import concurrent.futures
import argparse
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
AZURE_CLI = shutil.which("az.cmd") or shutil.which("az") or "az"
KEY = ROOT / ".codex_tmp" / "azure_recovery_ed25519"
OUTPUT = ROOT / "artifacts" / "recovery_azure"
REMOTE = "/mnt/ptcg-recovery"
SOURCE_COMMIT = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
CONSERVATIVE_RATE_USD_PER_WORKER_HOUR = 0.50
SPEND_CAP_USD = 140.0

WORKERS = [
    {"name": "ptcg-train", "rg": "ptcg-train-south-rg", "ip": "20.225.52.72"},
    {"name": "grim-centralus", "rg": "ptcg-recovery-centralus-rg", "ip": "20.9.33.62"},
    {"name": "grim-eastus2", "rg": "ptcg-recovery-eastus2-rg", "ip": "20.97.180.234"},
    {"name": "grim-northcentralus", "rg": "ptcg-recovery-northcentralus-rg", "ip": "130.131.35.196"},
    {"name": "grim-westus2", "rg": "ptcg-recovery-westus2-rg", "ip": "20.69.108.1"},
]

BUNDLE_PATHS = [
    "training/__init__.py",
    "training/evaluate.py",
    "training/evaluation_schema.py",
    "ptcg_ai",
    "vendor/cg",
    "freshstart/submission_template",
    "freshstart/elite_submissions/alakazam_2_4a",
    "freshstart/elite_submissions/alakazam_2_7",
    "freshstart/decklists/grimmsnarl_marnie.deck.csv",
    "artifacts/recovery_probes/extracted/a1",
    "artifacts/recovery_probes/extracted/a2",
    "artifacts/recovery_probes/extracted/control",
    "artifacts/recovery_probes/extracted/a2_base",
    "artifacts/recovery_r0_package/extracted/r0_play_binding",
]


def run(command: list[str], *, timeout: int = 600, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=ROOT, check=True, text=True, timeout=timeout, capture_output=capture)


def ssh(worker: dict, command: str, *, timeout: int = 600) -> None:
    run([
        "ssh", "-i", str(KEY), "-o", "StrictHostKeyChecking=accept-new", "-o", "ServerAliveInterval=30",
        f"azureuser@{worker['ip']}", command,
    ], timeout=timeout)


def scp(source: Path, worker: dict, destination: str, *, from_remote: bool = False) -> None:
    remote = f"azureuser@{worker['ip']}:{destination}"
    arguments = ["scp", "-i", str(KEY), "-o", "StrictHostKeyChecking=accept-new"]
    arguments += [remote, str(source)] if from_remote else [str(source), remote]
    run(arguments, timeout=1200)


def build_bundle() -> tuple[Path, str]:
    bundle = OUTPUT / "source_bundle.tar.gz"
    bundle.parent.mkdir(parents=True, exist_ok=True)
    with bundle.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                files = []
                for relative in BUNDLE_PATHS:
                    path = ROOT / relative
                    files.extend([path] if path.is_file() else [item for item in path.rglob("*") if item.is_file()])
                for path in sorted(set(files)):
                    if "__pycache__" in path.parts or path.suffix == ".pyc":
                        continue
                    info = archive.gettarinfo(str(path), arcname=path.relative_to(ROOT).as_posix())
                    info.mtime = 0
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    with path.open("rb") as handle:
                        archive.addfile(info, handle)
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    return bundle, digest


def prepare_worker(worker: dict, bundle: Path) -> None:
    for attempt in range(30):
        try:
            ssh(worker, "true", timeout=15)
            break
        except Exception:
            if attempt == 29:
                raise
            time.sleep(10)
    bootstrap = (
        f"sudo mkdir -p {REMOTE} && sudo chown azureuser:azureuser {REMOTE} && "
        "if ! command -v python3 >/dev/null; then sudo apt-get update -qq && sudo apt-get install -y python3; fi && "
        "if [ ! -x $HOME/ptcg-venv/bin/python ]; then "
        "sudo apt-get update -qq && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv python3-pip >/dev/null && "
        "python3 -m venv $HOME/ptcg-venv && $HOME/ptcg-venv/bin/pip install -q numpy; fi"
    )
    ssh(worker, bootstrap, timeout=1200)
    scp(bundle, worker, "/tmp/ptcg-recovery-bundle.tar.gz")
    ssh(worker, f"find {REMOTE} -mindepth 1 -maxdepth 1 -exec rm -rf -- {{}} + && tar -xzf /tmp/ptcg-recovery-bundle.tar.gz -C {REMOTE}")


def task_queue(phase: str) -> list[dict]:
    tasks = []
    if phase == "r0":
        seed = 2026080720
        opponents = {
            "a2": "artifacts/recovery_probes/extracted/a2_base",
            "d842": "artifacts/recovery_probes/extracted/control",
        }
        for opponent, submission_b in opponents.items():
            for shard in range(1, 6):
                seed += 1
                tasks.append({
                    "label": f"r0_{opponent}", "shard": shard, "seed": seed,
                    "a": "artifacts/recovery_r0_package/extracted/r0_play_binding",
                    "b": submission_b, "deck_b": f"{submission_b}/deck.csv", "games": 200,
                })
        return tasks
    if phase == "authentic":
        seed = 2026080700
        agents = {
            "a1": "artifacts/recovery_probes/extracted/a1",
            "a2": "artifacts/recovery_probes/extracted/a2",
            "control": "artifacts/recovery_probes/extracted/control",
        }
        opponents = {
            "alakazam_2_4a": "freshstart/elite_submissions/alakazam_2_4a",
            "alakazam_2_7": "freshstart/elite_submissions/alakazam_2_7",
        }
        for agent, submission_a in agents.items():
            for opponent, submission_b in opponents.items():
                for shard in range(1, 5):
                    seed += 1
                    tasks.append({
                        "label": f"auth_{agent}_{opponent}", "shard": shard, "seed": seed,
                        "a": submission_a, "b": submission_b,
                        "deck_b": f"{submission_b}/deck.csv", "games": 500,
                    })
        return tasks
    configurations = {
        "a1": ("artifacts/recovery_probes/extracted/a1", "artifacts/recovery_probes/extracted/control"),
        "a2": ("artifacts/recovery_probes/extracted/a2", "artifacts/recovery_probes/extracted/control"),
        "structural": ("artifacts/recovery_probes/extracted/control", "artifacts/recovery_probes/extracted/control"),
    }
    seed = 2026080610
    for label, (submission_a, submission_b) in configurations.items():
        for shard in range(1, 4):
            seed += 1
            tasks.append({
                "label": label, "shard": shard, "seed": seed, "a": submission_a, "b": submission_b,
                "deck_b": "freshstart/decklists/grimmsnarl_marnie.deck.csv", "games": 10000,
            })
    return tasks


def run_task(worker: dict, task: dict, bundle_hash: str, started: float) -> dict:
    projected = (time.time() - started + 7200) / 3600 * len(WORKERS) * CONSERVATIVE_RATE_USD_PER_WORKER_HOUR
    if projected >= SPEND_CAP_USD:
        raise RuntimeError(f"projected spend ${projected:.2f} would exceed ${SPEND_CAP_USD}")
    filename = f"{task['label']}_shard_{task['shard']}.json"
    command = (
        f"cd {REMOTE} && export PTCG_SOURCE_COMMIT={SOURCE_COMMIT} "
        f"PTCG_SOURCE_BUNDLE_SHA256={bundle_hash} PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 && "
        f"timeout 7200s $HOME/ptcg-venv/bin/python -m training.evaluate "
        "--deck-a freshstart/decklists/grimmsnarl_marnie.deck.csv "
        f"--submission-a {task['a']} "
        f"--deck-b {task['deck_b']} "
        f"--submission-b {task['b']} --games {task['games']} --workers 8 --seed {task['seed']} "
        f"--opponent-name {task['label']} --max-decisions 2000 "
        f"--output {filename} >/tmp/{filename}.log"
    )
    ssh(worker, command, timeout=7500)
    local = OUTPUT / "shards" / filename
    local.parent.mkdir(parents=True, exist_ok=True)
    scp(local, worker, f"{REMOTE}/{filename}", from_remote=True)
    result = json.loads(local.read_text())
    return {"worker": worker["name"], "task": task, "output": str(local), "games": result["games"]}


def deallocate(worker: dict) -> None:
    subprocess.run([AZURE_CLI, "vm", "deallocate", "-g", worker["rg"], "-n", worker["name"], "--no-wait"], cwd=ROOT)


def start(worker: dict) -> None:
    run([AZURE_CLI, "vm", "start", "-g", worker["rg"], "-n", worker["name"], "--no-wait"], timeout=120)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("probes", "authentic", "r0"), default="probes")
    args = parser.parse_args()
    if len(WORKERS) < 4:
        raise SystemExit("at least four on-demand workers are required")
    started = time.time()
    bundle, bundle_hash = build_bundle()
    state = {
        "started": started,
        "source_commit": SOURCE_COMMIT,
        "source_bundle_sha256": bundle_hash,
        "spend_cap_usd": SPEND_CAP_USD,
        "conservative_worker_rate_usd_per_hour": CONSERVATIVE_RATE_USD_PER_WORKER_HOUR,
        "workers": WORKERS,
        "results": [],
    }
    state_path = OUTPUT / "farm_manifest.json"
    try:
        for worker in WORKERS:
            start(worker)
        time.sleep(20)
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(WORKERS)) as pool:
            list(pool.map(lambda worker: prepare_worker(worker, bundle), WORKERS))
        tasks = iter(task_queue(args.phase))
        lock = __import__("threading").Lock()

        def worker_loop(worker: dict) -> list[dict]:
            completed = []
            while True:
                with lock:
                    try:
                        task = next(tasks)
                    except StopIteration:
                        break
                completed.append(run_task(worker, task, bundle_hash, started))
            return completed

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(WORKERS)) as pool:
            for rows in pool.map(worker_loop, WORKERS):
                state["results"].extend(rows)
        state["status"] = "complete"
        return 0
    except Exception as exc:
        state["status"] = "failed"
        state["error"] = repr(exc)
        raise
    finally:
        state["ended"] = time.time()
        hours = (state["ended"] - started) / 3600 * len(WORKERS)
        state["conservative_estimated_spend_usd"] = hours * CONSERVATIVE_RATE_USD_PER_WORKER_HOUR
        state_path = OUTPUT / f"farm_manifest_{args.phase}.json"
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        for worker in WORKERS:
            deallocate(worker)


if __name__ == "__main__":
    raise SystemExit(main())
