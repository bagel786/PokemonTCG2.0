#!/usr/bin/env python3
"""Certified newest-to-oldest Grimmsnarl daily-dataset crawler."""

from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import datetime as dt
import gzip
import hashlib
import json
import shutil
import subprocess
import sys
import time
import zipfile
import zlib
from collections import Counter
from itertools import repeat
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from ptcg_ai.replay import episode_reward, iter_decisions, load_episode
from ptcg_ai.archetypes import COMPETITIVE_ARCHETYPES
from training.lucario_data import canonical_deck, deterministic_gzip_text, load_deck

GRIMMSNARL_EX = 648
DEFAULT_DECK = ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv"
KAGGLE = ["kaggle"] if shutil.which("kaggle") else [sys.executable, "-m", "kaggle"]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def deck_hash(deck: tuple[int, ...]) -> str:
    return hashlib.sha256(",".join(map(str, deck)).encode()).hexdigest()


def load_archetype_catalog(deck_dir: Path) -> dict[str, tuple[int, ...]]:
    """Build signatures from the checked-in current deck data, never card-ID guesses."""
    catalog = {
        path.name.removesuffix(".deck.csv"): load_deck(path)
        for path in sorted(deck_dir.glob("*.deck.csv"))
    }
    for name, signature in COMPETITIVE_ARCHETYPES.items():
        catalog.setdefault(name, tuple(sorted(signature)))
    return catalog


def classify(deck: tuple[int, ...], catalog: dict[str, tuple[int, ...]]) -> str:
    if not deck:
        return "unknown"
    exact = [name for name, signature in catalog.items() if deck == signature]
    if exact:
        return exact[0]
    counts = Counter(deck)
    best_name, best_score = "other", 0.0
    for name, signature in catalog.items():
        other = Counter(signature)
        overlap = sum((counts & other).values())
        union = sum((counts | other).values())
        score = overlap / union if union else 0.0
        if score > best_score:
            best_name, best_score = name, score
    return best_name if best_score >= 0.55 else "other"


def process_episode(
    path: Path,
    date: str,
    exact_signature: tuple[int, ...],
    catalog: dict[str, tuple[int, ...]],
    feature_version: int,
    include_behavior: bool = True,
) -> dict:
    try:
        fingerprint = sha256_file(path)
        episode = load_episode(path)
        steps = episode.get("steps") or []
        if len(steps) < 2 or len(steps[1]) < 2:
            raise ValueError("episode does not contain two deck handshake rows")
        decks = [canonical_deck(steps[1][seat].get("action") or []) for seat in (0, 1)]
        if any(len(deck) != 60 for deck in decks):
            raise ValueError("deck handshake is not exactly 60 cards")
        info = episode.get("info") or {}
        episode_id = str(info.get("EpisodeId") or path.stem)
        teams = info.get("TeamNames") or ["seat-0", "seat-1"]
        family_seats = [seat for seat, deck in enumerate(decks) if GRIMMSNARL_EX in deck]
        exact_seats = [seat for seat, deck in enumerate(decks) if deck == exact_signature]
        units = []
        for seat in family_seats:
            outcome = episode_reward(episode, seat)
            units.append({
                "episode_id": episode_id,
                "seat": seat,
                "team": teams[seat],
                "opponent_team": teams[1 - seat],
                "outcome": outcome,
                "exact_current_deck": seat in exact_seats,
                "hero_deck_sha256": deck_hash(decks[seat]),
                "opponent_deck_sha256": deck_hash(decks[1 - seat]),
                "opponent_archetype": classify(decks[1 - seat], catalog),
            })
        rows = []
        behavior_rows = []
        behavior_seats = {}
        for seat, deck in enumerate(decks):
            if not include_behavior:
                continue
            if deck == exact_signature:
                continue
            archetype = classify(deck, catalog)
            if archetype != "unknown":
                behavior_seats[seat] = archetype
        allowed_exact_teams = None if include_behavior else {teams[seat] for seat in exact_seats}
        for decision in iter_decisions(
            episode,
            allowed_exact_teams,
            feature_version=feature_version,
            include_observation=False,
        ):
            row = decision.to_json()
            row.update({
                "source": "kaggle_daily_complete",
                "source_date": date,
                "source_fingerprint": fingerprint,
                "outcome": "win" if decision.reward > 0 else "loss",
                "opponent_team": teams[1 - decision.seat],
                "hero_deck_sha256": deck_hash(decks[decision.seat]),
                "opponent_deck_sha256": deck_hash(decks[1 - decision.seat]),
                "opponent_archetype": classify(decks[1 - decision.seat], catalog),
            })
            if decision.seat in exact_seats:
                rows.append(row)
            if decision.seat in behavior_seats:
                behavior_row = dict(row)
                behavior_row["behavior_archetype"] = behavior_seats[decision.seat]
                behavior_rows.append(behavior_row)
        return {
            "status": "processed", "episode_id": episode_id, "units": units,
            "rows": rows, "behavior_rows": behavior_rows,
        }
    except Exception as exc:
        return {
            "status": "failed", "error": f"{type(exc).__name__}: {exc}",
            "units": [], "rows": [], "behavior_rows": [],
        }


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def process_day(
    date: str,
    raw_root: Path,
    output_root: Path,
    exact_signature: tuple[int, ...],
    catalog: dict[str, tuple[int, ...]],
    feature_version: int,
    workers: int,
    include_behavior: bool = True,
) -> dict:
    manifest_path = output_root / "manifests" / f"{date}.json"
    shard_path = output_root / "shards" / f"{date}.jsonl.gz"
    behavior_path = output_root / "behavior_shards" / f"{date}.jsonl.gz"
    if manifest_path.exists():
        cached = json.loads(manifest_path.read_text())
        behavior_required = "behavior_output" in cached or "behavior_decision_count" in cached
        if (
            cached.get("status") in {"complete", "zero_certified"}
            and shard_path.exists()
            and (behavior_path.exists() or not behavior_required)
        ):
            return cached

    day_dir = (raw_root / date).resolve()
    if raw_root.resolve() not in day_dir.parents:
        raise RuntimeError("resolved raw day path escaped raw root")
    day_dir.mkdir(parents=True, exist_ok=True)
    dataset = f"kaggle/pokemon-tcg-ai-battle-episodes-{date}"
    started = time.time()
    archives = list(day_dir.glob("*.zip"))
    reused_local_archive = len(archives) == 1
    if not reused_local_archive:
        result = subprocess.run([*KAGGLE, "datasets", "download", dataset, "-p", str(day_dir), "-q"], text=True, capture_output=True)
        if result.returncode:
            status = "unavailable" if "404" in result.stderr or "not found" in result.stderr.lower() else "failed"
            manifest = {"date": date, "dataset": dataset, "status": status, "error": result.stderr[-2000:]}
            atomic_json(manifest_path, manifest)
            shutil.rmtree(day_dir)
            return manifest
        archives = list(day_dir.glob("*.zip"))
    if len(archives) != 1:
        manifest = {"date": date, "dataset": dataset, "status": "failed", "error": "expected exactly one bulk archive"}
        atomic_json(manifest_path, manifest)
        shutil.rmtree(day_dir)
        return manifest
    archive = archives[0]
    archive_hash = sha256_file(archive)
    try:
        with zipfile.ZipFile(archive) as zipped:
            bad_member = zipped.testzip()
            members = [name for name in zipped.namelist() if name.endswith((".json", ".json.gz"))]
            if bad_member or not members:
                raise ValueError(f"invalid archive; bad member={bad_member!r}, JSON members={len(members)}")
            extract_dir = day_dir / "expanded"
            existing = sorted([*extract_dir.rglob("*.json"), *extract_dir.rglob("*.json.gz")]) if extract_dir.exists() else []
            if len(existing) != len(members):
                zipped.extractall(extract_dir)
        files = sorted([*extract_dir.rglob("*.json"), *extract_dir.rglob("*.json.gz")])
        if len(files) != len(members):
            raise ValueError(f"archive/extracted count mismatch: {len(members)} != {len(files)}")

        shard_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = shard_path.with_name(shard_path.name + ".tmp")
        behavior_path.parent.mkdir(parents=True, exist_ok=True)
        behavior_temporary = behavior_path.with_name(behavior_path.name + ".tmp")
        processed_count = failed_count = decision_count = behavior_decision_count = 0
        family_unit_count = exact_unit_count = 0
        first_failure = None
        unit_counts = Counter()
        seen_rows: set[tuple[str, int, int]] = set()
        seen_behavior: set[tuple[str, int, int]] = set()
        with (
            deterministic_gzip_text(temporary) as handle,
            deterministic_gzip_text(behavior_temporary) as behavior_handle,
            concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool,
        ):
            # map() yields in sorted file order. This keeps hashes deterministic while
            # limiting the parent to one completed episode instead of the whole day.
            window = max(workers, workers * 4)
            for chunk_start in range(0, len(files), window):
                chunk = files[chunk_start:chunk_start + window]
                results = pool.map(
                    process_episode,
                    chunk,
                    repeat(date),
                    repeat(exact_signature),
                    repeat(catalog),
                    repeat(feature_version),
                    repeat(include_behavior),
                    chunksize=1,
                )
                for offset, result_row in enumerate(results, 1):
                    index = chunk_start + offset
                    if result_row["status"] != "processed":
                        failed_count += 1
                        first_failure = first_failure or result_row.get("error", "unknown failure")
                    else:
                        processed_count += 1
                        for unit in result_row["units"]:
                            family_unit_count += 1
                            exact_unit_count += bool(unit["exact_current_deck"])
                            outcome = "win" if unit["outcome"] == 1 else "loss" if unit["outcome"] == 0 else "unknown"
                            unit_counts[f"seat_{unit['seat']}_{outcome}"] += 1
                        for row in result_row["rows"]:
                            key = (str(row["episode_id"]), int(row["seat"]), int(row["step"]))
                            if key in seen_rows:
                                raise ValueError(f"duplicate exact decision: {key}")
                            seen_rows.add(key)
                            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
                            decision_count += 1
                        for row in result_row.get("behavior_rows", []):
                            key = (str(row["episode_id"]), int(row["seat"]), int(row["step"]))
                            if key in seen_behavior:
                                raise ValueError(f"duplicate behavior decision: {key}")
                            seen_behavior.add(key)
                            behavior_handle.write(json.dumps(row, separators=(",", ":")) + "\n")
                            behavior_decision_count += 1
                    if index % 250 == 0:
                        print(f"[{date}] processed {index}/{len(files)} episodes", flush=True)
        if failed_count:
            temporary.unlink(missing_ok=True)
            behavior_temporary.unlink(missing_ok=True)
            raise ValueError(f"{failed_count} episodes failed; first={first_failure}")
        temporary.replace(shard_path)
        behavior_temporary.replace(behavior_path)

        status = "zero_certified" if not family_unit_count else "complete"
        manifest = {
            "date": date,
            "dataset": dataset,
            "status": status,
            "download_complete": True,
            "reused_local_archive": reused_local_archive,
            "archive_sha256": archive_hash,
            "archive_members": len(members),
            "processed_episodes": processed_count,
            "failed_episodes": 0,
            "grim_family_units": family_unit_count,
            "exact_current_units": exact_unit_count,
            "grim_units_by_outcome_and_seat": dict(sorted(unit_counts.items())),
            "decision_count": decision_count,
            "behavior_decision_count": behavior_decision_count,
            "feature_version": feature_version,
            "output": str(shard_path),
            "output_sha256": sha256_file(shard_path),
            "behavior_output": str(behavior_path),
            "behavior_output_sha256": sha256_file(behavior_path),
            "cleanup_status": "pending",
            "elapsed_seconds": time.time() - started,
        }
        shutil.rmtree(day_dir)
        manifest["cleanup_status"] = "raw_removed"
        atomic_json(manifest_path, manifest)
        return manifest
    except Exception as exc:
        for candidate in (locals().get("temporary"), locals().get("behavior_temporary")):
            if isinstance(candidate, Path):
                candidate.unlink(missing_ok=True)
        manifest = {
            "date": date,
            "dataset": dataset,
            "status": "failed",
            "download_complete": True,
            "archive_sha256": archive_hash,
            "error": f"{type(exc).__name__}: {exc}",
            "cleanup_status": "raw_preserved_for_diagnosis",
        }
        atomic_json(manifest_path, manifest)
        return manifest


def assign_splits(output_root: Path, legacy_root: Path, feature_version: int = 4) -> dict:
    manifests = [json.loads(path.read_text()) for path in sorted((output_root / "manifests").glob("*.json"))]
    nonzero = sorted(row["date"] for row in manifests if row.get("status") == "complete" and row.get("grim_family_units", 0))
    if not nonzero:
        raise RuntimeError("no nonzero certified days are available")
    temporal_date = nonzero[-1]
    shard_paths = sorted((output_root / "shards").glob("*.jsonl.gz"))
    episode_metadata: dict[str, dict[str, set[str]]] = {}
    for path in shard_paths:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                metadata = episode_metadata.setdefault(
                    str(row["episode_id"]), {"dates": set(), "teams": set()}
                )
                metadata["dates"].add(row["source_date"])
                metadata["teams"].update((row.get("team", ""), row.get("opponent_team", "")))
    episode_assignment = {}
    for episode_id, metadata in episode_metadata.items():
        if temporal_date in metadata["dates"]:
            split = "temporal_holdout"
        else:
            teams = "|".join(sorted(metadata["teams"]))
            team_bucket = zlib.crc32(teams.encode()) % 10
            episode_bucket = zlib.crc32(episode_id.encode()) % 10
            split = "team_holdout" if team_bucket == 0 else ("validation" if episode_bucket == 0 else "train")
        episode_assignment[episode_id] = split

    seen_steps = set()
    split_dir = output_root / "splits"
    split_dir.mkdir(parents=True, exist_ok=True)
    split_names = ("train", "validation", "team_holdout", "temporal_holdout")
    counts = Counter()
    temporary_paths = {name: split_dir / f"{name}.jsonl.gz.tmp" for name in split_names}
    with contextlib.ExitStack() as stack:
        handles = {name: stack.enter_context(deterministic_gzip_text(path)) for name, path in temporary_paths.items()}
        for path in shard_paths:
            with gzip.open(path, "rt", encoding="utf-8") as source:
                for line in source:
                    row = json.loads(line)
                    episode_id = str(row["episode_id"])
                    key = (episode_id, int(row["seat"]), int(row["step"]))
                    if key in seen_steps:
                        continue
                    seen_steps.add(key)
                    split = episode_assignment[episode_id]
                    row["split"] = split
                    handles[split].write(json.dumps(row, separators=(",", ":")) + "\n")
                    counts[split] += 1
    hashes = {}
    for split in split_names:
        path = split_dir / f"{split}.jsonl.gz"
        temporary_paths[split].replace(path)
        hashes[split] = {"rows": counts[split], "sha256": sha256_file(path)}

    legacy_rows = 0
    for path in legacy_root.glob("*_decisions.jsonl.gz"):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            legacy_rows += sum(1 for _ in handle)
    manifest = {
        "feature_version": feature_version,
        "temporal_date": temporal_date,
        "episode_count": len(episode_assignment),
        "deduplication_key": ["episode_id", "seat", "step"],
        "split_unit": "whole_episode",
        "splits": hashes,
        "legacy_winner_rehearsal": {"available_rows": legacy_rows, "policy": "capped_external_stream_only"},
    }
    atomic_json(output_root / "dataset_manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", default=dt.date.today().isoformat())
    parser.add_argument("--min-date", default="2026-06-01")
    parser.add_argument("--raw-root", default="data/grim_daily_v4/raw")
    parser.add_argument("--output-root", default="data/grim_daily_v4")
    parser.add_argument("--deck", default=str(DEFAULT_DECK))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--feature-version", type=int, default=5)
    parser.add_argument("--skip-behavior", action="store_true", help="extract exact-Grim rows only")
    parser.add_argument("--no-assemble", action="store_true")
    args = parser.parse_args()
    if args.feature_version not in {4, 5}:
        raise SystemExit("this strength-recovery crawler requires feature schema 4 or 5")
    current = dt.date.fromisoformat(args.start_date)
    minimum = dt.date.fromisoformat(args.min_date)
    output_root = Path(args.output_root).resolve()
    raw_root = Path(args.raw_root).resolve()
    exact = load_deck(Path(args.deck))
    catalog = load_archetype_catalog(ROOT / "freshstart" / "decklists")
    while current >= minimum:
        date = current.isoformat()
        manifest = process_day(
            date, raw_root, output_root, exact, catalog, args.feature_version,
            args.workers, include_behavior=not args.skip_behavior,
        )
        print(json.dumps({key: manifest.get(key) for key in ("date", "status", "grim_family_units", "decision_count")}), flush=True)
        if manifest.get("status") == "zero_certified":
            break
        current -= dt.timedelta(days=1)
    if not args.no_assemble:
        print(json.dumps(assign_splits(
            output_root, ROOT / "data" / "daily_extracted", args.feature_version
        ), indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
