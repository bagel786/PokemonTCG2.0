#!/usr/bin/env python3
"""Run the frozen Director randomized kill-screen on the five Azure workers.

This is deliberately separate from discovery: it accepts only a package whose
macro has already been frozen, randomizes treatment/control within every shard,
and aggregates intention-to-treat rows fail-closed.
"""

from __future__ import annotations

import concurrent.futures
import gzip
import hashlib
import json
import shlex
import shutil
import subprocess
import sys
import tarfile
import threading
import time
from dataclasses import asdict
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from training.director_experiment import MacroTrialRow, analyze


AZ = shutil.which("az.cmd") or shutil.which("az") or "az"
KEY = ROOT / ".codex_tmp" / "azure_recovery_ed25519"
OUTPUT = ROOT / "artifacts" / "turn_director" / "confirmation"
REMOTE = "/mnt/ptcg-director-confirmation"
RATE = 0.50
PRIOR_SPEND = 16.59
CAP = 140.0
WORKERS = [
    {"name": "ptcg-train", "rg": "PTCG-TRAIN-SOUTH-RG", "ip": "20.225.52.72"},
    {"name": "grim-centralus", "rg": "PTCG-RECOVERY-CENTRALUS-RG", "ip": "20.9.33.62"},
    {"name": "grim-eastus2", "rg": "PTCG-RECOVERY-EASTUS2-RG", "ip": "20.97.180.234"},
    {"name": "grim-northcentralus", "rg": "PTCG-RECOVERY-NORTHCENTRALUS-RG", "ip": "130.131.35.196"},
    {"name": "grim-westus2", "rg": "PTCG-RECOVERY-WESTUS2-RG", "ip": "20.69.108.1"},
]
OPPONENTS = {
    "master_v1": "artifacts/recovery_final/opponents/master_v1",
    "replay_refresh": "artifacts/recovery_final/opponents/replay_refresh",
    "v2_2": "artifacts/recovery_final/opponents/v2_2",
}


def run(arguments, timeout=600, check=True):
    return subprocess.run(arguments, cwd=ROOT, text=True, check=check, timeout=timeout, capture_output=True)


def ssh(worker, command, timeout=600):
    return run(["ssh", "-i", str(KEY), "-o", "StrictHostKeyChecking=accept-new",
                "-o", "ServerAliveInterval=30", f"azureuser@{worker['ip']}", command], timeout)


def scp(source, worker, destination, reverse=False):
    remote = f"azureuser@{worker['ip']}:{destination}"
    run(["scp", "-i", str(KEY), "-o", "StrictHostKeyChecking=accept-new",
         remote if reverse else str(source), str(source) if reverse else remote], 1200)


def make_bundle(candidate_archive: Path) -> tuple[Path, str]:
    required = [
        ROOT / "training" / "__init__.py",
        ROOT / "training" / "director_experiment.py",
        ROOT / "training" / "evaluate.py",
        ROOT / "training" / "evaluation_schema.py",
        ROOT / "training" / "promotion.py",
        ROOT / "ptcg_ai",
        ROOT / "vendor" / "cg",
        candidate_archive,
        *(ROOT / value for value in OPPONENTS.values()),
    ]
    files = []
    for target in required:
        if not target.exists():
            raise FileNotFoundError(target)
        files.extend([target] if target.is_file() else [item for item in target.rglob("*") if item.is_file()])
    path = OUTPUT / "bundle.tar.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode="w") as archive:
                for item in sorted(set(files)):
                    if "__pycache__" in item.parts or item.suffix == ".pyc":
                        continue
                    arcname = "candidate.tar.gz" if item == candidate_archive else item.relative_to(ROOT).as_posix()
                    info = archive.gettarinfo(str(item), arcname=arcname)
                    info.mtime = info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    with item.open("rb") as handle:
                        archive.addfile(info, handle)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def start_and_prepare(worker, bundle):
    run([AZ, "vm", "start", "-g", worker["rg"], "-n", worker["name"]], 1200)
    for attempt in range(30):
        try:
            ssh(worker, "true", 20)
            break
        except Exception:
            if attempt == 29:
                raise
            time.sleep(10)
    scp(bundle, worker, "/tmp/ptcg-director-confirmation.tar.gz")
    ssh(worker, (
        f"sudo rm -rf {REMOTE} && sudo mkdir -p {REMOTE}/candidate && "
        f"sudo chown -R azureuser:azureuser {REMOTE} && "
        f"tar -xzf /tmp/ptcg-director-confirmation.tar.gz -C {REMOTE} && "
        f"tar -xzf {REMOTE}/candidate.tar.gz -C {REMOTE}/candidate && "
        "test -x /home/azureuser/ptcg-venv/bin/python"
    ), 1200)


def kill_jobs(total_games: int) -> list[dict]:
    if total_games != 4_000:
        raise ValueError("the preregistered kill screen is exactly 4,000 games")
    # Equal-lineage to within two games; every shard has equal treatment/control.
    layout = {
        "master_v1": (668, 666),
        "replay_refresh": (668, 666),
        "v2_2": (666, 666),
    }
    jobs = []
    seed = 2026080900
    for lineage, counts in layout.items():
        for shard, games in enumerate(counts):
            seed += 1
            jobs.append({"lineage": lineage, "games": games, "shard": shard, "seed": seed})
    assert sum(job["games"] for job in jobs) == total_games
    return jobs


def evaluate(worker, job, bundle_hash, started):
    projected = PRIOR_SPEND + ((time.time() - started) / 3600 + 2.0) * len(WORKERS) * RATE
    if projected >= CAP:
        raise RuntimeError(f"projected spend ${projected:.2f} exceeds cap")
    lineage = job["lineage"]
    filename = f"kill__{lineage}__{job['shard']}.json"
    command = (
        f"cd {REMOTE} && export PTCG_SOURCE_BUNDLE_SHA256={bundle_hash} "
        "PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 && "
        "/home/azureuser/ptcg-venv/bin/python -m training.director_experiment "
        "--candidate candidate "
        f"--opponent {shlex.quote(lineage + '=' + OPPONENTS[lineage])} "
        f"--games {job['games']} --workers 8 --seed {job['seed']} --output {filename} "
        f">{filename}.log 2>&1; rc=$?; test $rc -eq 0 -o $rc -eq 2"
    )
    ssh(worker, command, 7200)
    local = OUTPUT / "shards" / filename
    local.parent.mkdir(parents=True, exist_ok=True)
    scp(local, worker, f"{REMOTE}/{filename}", True)
    payload = json.loads(local.read_text(encoding="utf-8"))
    if payload.get("schema") != "macro_trial_v1" or len(payload.get("rows", [])) != job["games"]:
        raise ValueError(f"incomplete shard {filename}")
    return job, payload


def deallocate(worker):
    subprocess.run([AZ, "vm", "deallocate", "-g", worker["rg"], "-n", worker["name"], "--no-wait"], cwd=ROOT)


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=OUTPUT / "kill_screen.json")
    args = parser.parse_args()
    candidate_archive = args.candidate_archive.resolve()
    started = time.time()
    bundle, bundle_hash = make_bundle(candidate_archive)
    manifest = {"status": "running", "bundle_sha256": bundle_hash, "candidate_archive_sha256": hashlib.sha256(candidate_archive.read_bytes()).hexdigest()}
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            list(pool.map(lambda worker: start_and_prepare(worker, bundle), WORKERS))
        queue = iter(kill_jobs(4_000))
        lock = threading.Lock()
        results = []

        def loop(worker):
            local = []
            while True:
                with lock:
                    try:
                        job = next(queue)
                    except StopIteration:
                        break
                local.append(evaluate(worker, job, bundle_hash, started))
            return local

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            for values in pool.map(loop, WORKERS):
                results.extend(values)
        rows = []
        next_id = 0
        for job, payload in sorted(results, key=lambda item: (item[0]["lineage"], item[0]["shard"])):
            for raw in payload["rows"]:
                raw["game_id"] = next_id
                raw["shard"] = job["shard"]
                next_id += 1
                rows.append(MacroTrialRow(**raw))
        decision = analyze(rows)
        manifest.update({"status": "complete", "decision": decision, "rows": [asdict(row) for row in rows]})
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(decision, indent=2))
        return 0 if decision["passed"] else 2
    except Exception as exc:
        manifest.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        raise
    finally:
        manifest["elapsed_seconds"] = time.time() - started
        manifest["estimated_incremental_spend_usd"] = manifest["elapsed_seconds"] / 3600 * len(WORKERS) * RATE
        for worker in WORKERS:
            deallocate(worker)


if __name__ == "__main__":
    raise SystemExit(main())
