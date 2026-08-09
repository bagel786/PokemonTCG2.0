#!/usr/bin/env python3
"""Run resumable screen/final B-candidate gates on the on-demand Azure farm."""

from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import threading
import time
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE_COMMIT = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
AZURE = shutil.which("az.cmd") or shutil.which("az") or "az"
KEY = ROOT / ".codex_tmp" / "azure_recovery_ed25519"
OUTPUT = ROOT / "artifacts" / "recovery_final_azure"
REMOTE = "/mnt/ptcg-recovery-final"
RATE = 0.50
SPEND_CAP = 140.0
WORKERS = (
    {"name": "ptcg-train", "rg": "ptcg-train-south-rg", "ip": "20.225.52.72"},
    {"name": "grim-centralus", "rg": "ptcg-recovery-centralus-rg", "ip": "20.9.33.62"},
    {"name": "grim-eastus2", "rg": "ptcg-recovery-eastus2-rg", "ip": "20.97.180.234"},
    {"name": "grim-northcentralus", "rg": "ptcg-recovery-northcentralus-rg", "ip": "130.131.35.196"},
    {"name": "grim-westus2", "rg": "ptcg-recovery-westus2-rg", "ip": "20.69.108.1"},
)
BASE_PATHS = (
    "training/__init__.py",
    "training/evaluate.py",
    "training/evaluation_schema.py",
    "training/promotion.py",
    "ptcg_ai",
    "vendor/cg",
    "freshstart/decklists/grimmsnarl_marnie.deck.csv",
    "artifacts/recovery_probes/extracted/control",
    "artifacts/recovery_final/opponents",
    "freshstart/elite_submissions/alakazam_2_4a",
    "freshstart/elite_submissions/alakazam_2_7",
)


def run(command: list[str], timeout: int = 600, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=ROOT, check=True, text=True, timeout=timeout, capture_output=capture)


def ssh(worker: dict, command: str, timeout: int = 600) -> subprocess.CompletedProcess:
    return run([
        "ssh", "-i", str(KEY), "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ServerAliveInterval=30", f"azureuser@{worker['ip']}", command,
    ], timeout=timeout, capture=True)


def scp(worker: dict, source: str | Path, destination: str | Path, *, from_remote: bool = False) -> None:
    left, right = (f"azureuser@{worker['ip']}:{source}", str(destination)) if from_remote else (
        str(source), f"azureuser@{worker['ip']}:{destination}"
    )
    run(["scp", "-i", str(KEY), "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", left, right], timeout=3600)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def candidate_manifest() -> dict:
    payload = json.loads((ROOT / "artifacts" / "recovery_final" / "candidate_manifest.json").read_text())
    if len(payload.get("candidates", {})) != 6:
        raise RuntimeError("final evaluation requires all six packaged candidates")
    return payload


def build_bundle(phase: str, candidates: list[str]) -> tuple[Path, str]:
    paths = list(BASE_PATHS) + [f"artifacts/recovery_final/candidates/{name}" for name in candidates]
    missing = [name for name in paths if not (ROOT / name).exists()]
    if missing:
        raise FileNotFoundError(f"final-evaluation bundle inputs are missing: {missing}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    bundle = OUTPUT / f"{phase}_bundle.tar.gz"
    with bundle.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=6, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for name in paths:
                    source = ROOT / name
                    files = [source] if source.is_file() else sorted(path for path in source.rglob("*") if path.is_file())
                    for path in files:
                        info = archive.gettarinfo(str(path), arcname=path.relative_to(ROOT).as_posix())
                        info.mtime = 0
                        info.uid = info.gid = 0
                        info.uname = info.gname = ""
                        with path.open("rb") as handle:
                            archive.addfile(info, handle)
    return bundle, sha256(bundle)


def start_and_prepare(worker: dict, bundle: Path, bundle_hash: str) -> None:
    run([AZURE, "vm", "start", "-g", worker["rg"], "-n", worker["name"], "--no-wait"], timeout=120)
    last_error = None
    for _ in range(40):
        try:
            ssh(worker, "true", timeout=15)
            break
        except Exception as exc:
            last_error = exc
            time.sleep(10)
    else:
        raise RuntimeError(f"worker did not become ready: {worker['name']}: {last_error}")
    remote_bundle = f"/tmp/recovery-final-{bundle_hash}.tar.gz"
    scp(worker, bundle, remote_bundle)
    ssh(worker, (
        f"sudo mkdir -p {REMOTE} && sudo chown azureuser:azureuser {REMOTE} && "
        f"tar -xzf {remote_bundle} -C {REMOTE} && "
        f"test \"$(sha256sum {remote_bundle} | cut -d' ' -f1)\" = {bundle_hash}"
    ), timeout=1800)


def screen_tasks(names: list[str]) -> list[dict]:
    tasks, seed = [], 2026080900
    for name in names:
        for shard in range(1, 5):
            seed += 1
            tasks.append({
                "phase": "screen", "arm": name, "opponent": "d842", "shard": shard,
                "games": 500, "seed": seed,
                "agent": f"artifacts/recovery_final/candidates/{name}",
                "opponent_agent": "artifacts/recovery_final/opponents/d842",
                "opponent_deck": "artifacts/recovery_final/opponents/d842/deck.csv",
            })
    return tasks


def select_finalists(names: list[str]) -> dict:
    from training.promotion import aggregate_shards

    selected, scores = {}, {}
    for name in names:
        paths = sorted((OUTPUT / "shards").glob(f"screen__{name}__vs__d842__shard_*.json"))
        if len(paths) != 4:
            raise RuntimeError(f"screen is incomplete for {name}")
        result = aggregate_shards(paths)
        if result["games"] != 2000 or result["hero_policy_errors"] or result["opponent_policy_errors"]:
            raise RuntimeError(f"screen failed closed for {name}")
        scores[name] = result
    for family in ("b1", "b2"):
        family_names = [name for name in names if name.startswith(f"{family}_")]
        selected[family] = max(
            family_names,
            key=lambda name: (scores[name]["win_rate"], scores[name]["seat_results"]["1"]["win_rate"]),
        )
    manifest = {"selected": selected, "screens": scores}
    (OUTPUT / "screen_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def full_matchups() -> dict[str, tuple[str, str, int]]:
    opponents = ROOT / "artifacts" / "recovery_final" / "opponents"
    matchups = {
        "d842": ("artifacts/recovery_final/opponents/d842", "artifacts/recovery_final/opponents/d842/deck.csv", 20_000),
        "master_v1": ("artifacts/recovery_final/opponents/master_v1", "artifacts/recovery_final/opponents/master_v1/deck.csv", 10_000),
        "replay_refresh": ("artifacts/recovery_final/opponents/replay_refresh", "artifacts/recovery_final/opponents/replay_refresh/deck.csv", 10_000),
        "v2_2": ("artifacts/recovery_final/opponents/v2_2", "artifacts/recovery_final/opponents/v2_2/deck.csv", 10_000),
        "alakazam_2_4a": ("freshstart/elite_submissions/alakazam_2_4a", "freshstart/elite_submissions/alakazam_2_4a/deck.csv", 2_000),
        "alakazam_2_7": ("freshstart/elite_submissions/alakazam_2_7", "freshstart/elite_submissions/alakazam_2_7/deck.csv", 2_000),
        **{
            name: (f"artifacts/recovery_final/opponents/{name}", f"artifacts/recovery_final/opponents/{name}/deck.csv", 2_000)
            for name in ("lucario", "crustle", "ogerpon", "bellibolt", "starmie_froslass")
            if (opponents / name).exists()
        },
    }
    if len(matchups) != 11:
        raise RuntimeError(f"final population is incomplete: expected 11 matchups, found {len(matchups)}")
    return matchups


def final_tasks(finalists: list[str]) -> list[dict]:
    tasks, seed = [], 2026081000
    arms = {name: f"artifacts/recovery_final/candidates/{name}" for name in finalists}
    arms["control"] = "artifacts/recovery_probes/extracted/control"
    for arm, agent in arms.items():
        for opponent, (opponent_agent, opponent_deck, games) in full_matchups().items():
            for shard in range(1, games // 500 + 1):
                seed += 1
                tasks.append({
                    "phase": "full", "arm": arm, "opponent": opponent, "shard": shard,
                    "games": 500, "seed": seed, "agent": agent,
                    "opponent_agent": opponent_agent, "opponent_deck": opponent_deck,
                })
    return tasks


def filename(task: dict) -> str:
    return f"{task['phase']}__{task['arm']}__vs__{task['opponent']}__shard_{task['shard']}.json"


def run_task(worker: dict, task: dict, bundle_hash: str, started: float) -> dict:
    local = OUTPUT / "shards" / filename(task)
    if local.exists():
        from training.evaluation_schema import load_evaluation
        try:
            result = load_evaluation(local)
            if (
                result["games"] == task["games"]
                and result["artifact_provenance"]["source_bundle_sha256"] == bundle_hash
                and result["artifact_provenance"]["seed"] == task["seed"]
            ):
                return {"worker": "resumed", "task": task, "output": str(local)}
        except Exception:
            pass
    projected = (time.time() - started + 2 * 3600) / 3600 * len(WORKERS) * RATE
    if projected >= SPEND_CAP:
        raise RuntimeError(f"projected spend ${projected:.2f} exceeds ${SPEND_CAP:.2f}")
    remote_output = filename(task)
    command = (
        f"cd {REMOTE} && export PTCG_SOURCE_COMMIT={SOURCE_COMMIT} "
        f"PTCG_SOURCE_BUNDLE_SHA256={bundle_hash} PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 && "
        f"timeout 7200s $HOME/ptcg-venv/bin/python -m training.evaluate "
        "--deck-a freshstart/decklists/grimmsnarl_marnie.deck.csv "
        f"--submission-a {task['agent']} --deck-b {task['opponent_deck']} "
        f"--submission-b {task['opponent_agent']} --games {task['games']} --workers 8 "
        f"--seed {task['seed']} --opponent-name {task['opponent']} --output {remote_output} "
        f">/tmp/{remote_output}.log 2>&1"
    )
    ssh(worker, command, timeout=7500)
    local.parent.mkdir(parents=True, exist_ok=True)
    scp(worker, f"{REMOTE}/{remote_output}", local, from_remote=True)
    from training.evaluation_schema import load_evaluation
    result = load_evaluation(local)
    if result["games"] != task["games"]:
        raise RuntimeError(f"incomplete evaluation shard: {remote_output}")
    return {"worker": worker["name"], "task": task, "output": str(local)}


def deallocate(worker: dict) -> None:
    subprocess.run([AZURE, "vm", "deallocate", "-g", worker["rg"], "-n", worker["name"], "--no-wait"], cwd=ROOT, check=False)


def execute(phase: str) -> int:
    candidates = sorted(candidate_manifest()["candidates"])
    if phase == "screen":
        bundle_names, tasks = candidates, screen_tasks(candidates)
    else:
        screen = json.loads((OUTPUT / "screen_manifest.json").read_text())
        bundle_names = list(screen["selected"].values())
        tasks = final_tasks(bundle_names)
    bundle, bundle_hash = build_bundle(phase, bundle_names)
    started = time.time()
    state = {"phase": phase, "started_unix": started, "bundle_sha256": bundle_hash, "tasks": len(tasks), "results": []}
    try:
        from training.evaluation_schema import load_evaluation
        cached = []
        for task in tasks:
            local = OUTPUT / "shards" / filename(task)
            if not local.exists():
                break
            result = load_evaluation(local)
            if (
                result["games"] != task["games"]
                or result["artifact_provenance"]["source_bundle_sha256"] != bundle_hash
                or result["artifact_provenance"]["seed"] != task["seed"]
            ):
                break
            cached.append({"worker": "resumed", "task": task, "output": str(local)})
        if len(cached) == len(tasks):
            state["results"] = cached
            state["worker_failures"] = []
            if phase == "screen":
                state["selection"] = select_finalists(candidates)["selected"]
            state["status"] = "complete"
            return 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(WORKERS)) as pool:
            list(pool.map(lambda worker: start_and_prepare(worker, bundle, bundle_hash), WORKERS))
        pending, lock = deque(tasks), threading.Lock()
        state["worker_failures"] = []

        def loop(worker: dict) -> list[dict]:
            rows = []
            while True:
                with lock:
                    if not pending:
                        return rows
                    task = pending.popleft()
                try:
                    rows.append(run_task(worker, task, bundle_hash, started))
                except Exception as exc:
                    with lock:
                        pending.appendleft(task)
                        state["worker_failures"].append({
                            "worker": worker["name"],
                            "task": task,
                            "error": f"{type(exc).__name__}: {exc}",
                        })
                    return rows

        healthy_workers = list(WORKERS)
        while pending:
            before_pending = len(pending)
            before_results = len(state["results"])
            failure_start = len(state["worker_failures"])
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(healthy_workers)) as pool:
                for rows in pool.map(loop, healthy_workers):
                    state["results"].extend(rows)
            failed_names = {
                row["worker"] for row in state["worker_failures"][failure_start:]
            }
            healthy_workers = [worker for worker in healthy_workers if worker["name"] not in failed_names]
            if pending and not healthy_workers:
                raise RuntimeError("all Azure workers failed with evaluation tasks still pending")
            if (
                pending
                and len(pending) >= before_pending
                and len(state["results"]) == before_results
            ):
                raise RuntimeError("evaluation queue made no progress")
        if len(state["results"]) != len(tasks):
            raise RuntimeError("evaluation queue returned incomplete results")
        if phase == "screen":
            state["selection"] = select_finalists(candidates)["selected"]
        state["status"] = "complete"
        return 0
    except Exception as exc:
        state["status"] = "failed"
        state["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        state["ended_unix"] = time.time()
        state["estimated_spend_usd"] = (state["ended_unix"] - started) / 3600 * len(WORKERS) * RATE
        OUTPUT.mkdir(parents=True, exist_ok=True)
        (OUTPUT / f"{phase}_farm_manifest.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
        for worker in WORKERS:
            deallocate(worker)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("screen", "full"), required=True)
    args = parser.parse_args()
    if len(WORKERS) < 4 or not KEY.exists():
        raise SystemExit("at least four on-demand workers and the recovery SSH key are required")
    return execute(args.phase)


if __name__ == "__main__":
    raise SystemExit(main())
