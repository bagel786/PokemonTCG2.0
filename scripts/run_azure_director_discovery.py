#!/usr/bin/env python3
"""Run the 12-policy Director successive-halving tournament on five Azure VMs."""

from __future__ import annotations

import concurrent.futures
import gzip
import hashlib
import json
import shlex
import shutil
import subprocess
import tarfile
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AZ = shutil.which("az.cmd") or shutil.which("az") or "az"
KEY = ROOT / ".codex_tmp" / "azure_recovery_ed25519"
OUTPUT = ROOT / "artifacts" / "turn_director" / "discovery"
REMOTE = "/mnt/ptcg-director-discovery"
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
POLICIES = [
    {"fallback": fallback, "horizon": horizon, "trigger": trigger,
     "name": f"{fallback}__{horizon}__{trigger}"}
    for fallback in ("a2", "d842")
    for horizon in ("turn", "turn_reply")
    for trigger in ("first_high_impact", "first_robust_disagreement", "third_turn")
]
BUNDLE = [
    "training/__init__.py", "training/evaluate.py", "training/evaluation_schema.py",
    "ptcg_ai", "vendor/cg", "artifacts/turn_director/grim_turn_director.tar.gz",
    *OPPONENTS.values(),
]


def run(arguments, timeout=600, check=True):
    return subprocess.run(arguments, cwd=ROOT, text=True, check=check, timeout=timeout, capture_output=True)


def ssh(worker, command, timeout=600):
    return run(["ssh", "-i", str(KEY), "-o", "StrictHostKeyChecking=accept-new", "-o", "ServerAliveInterval=30", f"azureuser@{worker['ip']}", command], timeout)


def scp(source, worker, destination, reverse=False):
    remote = f"azureuser@{worker['ip']}:{destination}"
    run(["scp", "-i", str(KEY), "-o", "StrictHostKeyChecking=accept-new", remote if reverse else str(source), str(source) if reverse else remote], 1200)


def bundle() -> tuple[Path, str]:
    path = OUTPUT / "bundle.tar.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    files = []
    for relative in BUNDLE:
        target = ROOT / relative
        files.extend([target] if target.is_file() else [item for item in target.rglob("*") if item.is_file()])
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode="w") as archive:
                for item in sorted(set(files)):
                    if "__pycache__" in item.parts or item.suffix == ".pyc":
                        continue
                    info = archive.gettarinfo(str(item), arcname=item.relative_to(ROOT).as_posix())
                    info.mtime = info.uid = info.gid = 0; info.uname = info.gname = ""
                    with item.open("rb") as handle:
                        archive.addfile(info, handle)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(worker, archive):
    for attempt in range(30):
        try:
            ssh(worker, "true", 20); break
        except Exception:
            if attempt == 29: raise
            time.sleep(10)
    scp(archive, worker, "/tmp/ptcg-director-discovery.tar.gz")
    command = (
        f"sudo rm -rf {REMOTE} && sudo mkdir -p {REMOTE}/candidate && sudo chown -R azureuser:azureuser {REMOTE} && "
        f"tar -xzf /tmp/ptcg-director-discovery.tar.gz -C {REMOTE} && "
        f"tar -xzf {REMOTE}/artifacts/turn_director/grim_turn_director.tar.gz -C {REMOTE}/candidate && "
        "test -x /home/azureuser/ptcg-venv/bin/python"
    )
    ssh(worker, command, 1200)


def split_games(total):
    base, remainder = divmod(total, len(OPPONENTS))
    return [base + (index < remainder) for index in range(len(OPPONENTS))]


def jobs(policies, games, stage):
    result = []
    seed = 2026080800 + stage * 100_000
    allocations = split_games(games)
    for policy in policies:
        for index, (lineage, opponent) in enumerate(OPPONENTS.items()):
            seed += 1
            result.append({**policy, "stage": stage, "lineage": lineage, "opponent": opponent, "games": allocations[index], "seed": seed})
    return result


def evaluate(worker, job, bundle_hash, started):
    projected = PRIOR_SPEND + ((time.time() - started) / 3600 + 2.0) * len(WORKERS) * RATE
    if projected >= CAP:
        raise RuntimeError(f"projected spend ${projected:.2f} exceeds cap")
    env = {
        "PTCG_DIRECTOR_ARM": "treatment",
        "PTCG_DIRECTOR_HORIZON": job["horizon"],
        "PTCG_DIRECTOR_TRIGGER": job["trigger"],
        "PTCG_DIRECTOR_SWAP_FALLBACK": "1" if job["fallback"] == "d842" else "0",
    }
    filename = f"s{job['stage']}__{job['name']}__{job['lineage']}.json"
    command = (
        f"cd {REMOTE} && export PTCG_SOURCE_COMMIT={shlex.quote(subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip())} "
        f"PTCG_SOURCE_BUNDLE_SHA256={bundle_hash} PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 && "
        "/home/azureuser/ptcg-venv/bin/python -m training.evaluate "
        "--deck-a candidate/deck.csv --submission-a candidate "
        f"--submission-env-a {shlex.quote(json.dumps(env, separators=(',', ':')))} "
        f"--deck-b {job['opponent']}/deck.csv --submission-b {job['opponent']} "
        f"--games {job['games']} --workers 8 --seed {job['seed']} --max-decisions 2000 "
        f"--opponent-name {job['lineage']} --output {filename} >{filename}.log"
    )
    ssh(worker, command, 7200)
    local = OUTPUT / "shards" / filename
    local.parent.mkdir(parents=True, exist_ok=True)
    scp(local, worker, f"{REMOTE}/{filename}", True)
    return json.loads(local.read_text(encoding="utf-8"))


def stage_run(policies, games, stage, bundle_hash, started):
    queue = iter(jobs(policies, games, stage)); lock = threading.Lock(); rows = []
    def loop(worker):
        local = []
        while True:
            with lock:
                try: job = next(queue)
                except StopIteration: break
            local.append((job, evaluate(worker, job, bundle_hash, started)))
        return local
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(WORKERS)) as pool:
        for values in pool.map(loop, WORKERS): rows.extend(values)
    summaries = {}
    for policy in policies:
        selected = [(job, row) for job, row in rows if job["name"] == policy["name"]]
        wins = sum(row["wins_a"] for _, row in selected); total = sum(row["games"] for _, row in selected)
        errors = sum(row["hero_policy_errors"] + row["opponent_policy_errors"] for _, row in selected)
        summaries[policy["name"]] = {"games": total, "wins": wins, "win_rate": wins / total, "errors": errors, "lineages": {job["lineage"]: row["win_rate_a"] for job, row in selected}}
    ranked = sorted(policies, key=lambda policy: (summaries[policy["name"]]["errors"] == 0, summaries[policy["name"]]["win_rate"]), reverse=True)
    return rows, summaries, ranked


def deallocate(worker):
    subprocess.run([AZ, "vm", "deallocate", "-g", worker["rg"], "-n", worker["name"], "--no-wait"], cwd=ROOT)


def main():
    started = time.time(); archive, digest = bundle(); manifest = {"started": started, "bundle_sha256": digest, "prior_spend_usd": PRIOR_SPEND, "cap_usd": CAP, "stages": []}
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool: list(pool.map(lambda worker: prepare(worker, archive), WORKERS))
        active = list(POLICIES)
        for stage, (games, keep) in enumerate(((500, 4), (2000, 2), (5000, 1)), 1):
            rows, summaries, ranked = stage_run(active, games, stage, digest, started)
            manifest["stages"].append({"stage": stage, "games_per_policy": games, "summaries": summaries, "ranking": [item["name"] for item in ranked]})
            active = ranked[:keep]
            (OUTPUT / "manifest.partial.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        winner = active[0]
        manifest.update({
            "status": "frozen", "winner": winner["name"],
            "winner_config": {
                "PTCG_DIRECTOR_HORIZON": winner["horizon"], "PTCG_DIRECTOR_TRIGGER": winner["trigger"],
                "PTCG_DIRECTOR_SWAP_FALLBACK": "1" if winner["fallback"] == "d842" else "0",
            },
            "behavior_clones_used": False, "engine_randomness": "independent_unpaired",
        })
        return 0
    except Exception as exc:
        manifest.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
        raise
    finally:
        manifest["ended"] = time.time(); manifest["estimated_incremental_spend_usd"] = (manifest["ended"] - started) / 3600 * len(WORKERS) * RATE
        OUTPUT.mkdir(parents=True, exist_ok=True)
        (OUTPUT / "discovery_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        for worker in WORKERS: deallocate(worker)


if __name__ == "__main__":
    raise SystemExit(main())
