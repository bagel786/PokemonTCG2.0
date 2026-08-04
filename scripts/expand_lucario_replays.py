#!/usr/bin/env python3
"""Discover Lucario ladder submissions, fetch their episodes, and build an audited BC shard."""

from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import json
import os
import sys
import tempfile
import time
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

from ptcg_ai.replay import iter_decisions, load_episode  # noqa: E402
from scripts.fetch_active_subs import download_one, fetch_episodes  # noqa: E402
from training.lucario_data import canonical_deck, deterministic_gzip_text, load_deck, sha256_file  # noqa: E402


def replay_paths(root: Path):
    yield from sorted(root.glob("*/episode-*-replay.json"))
    yield from sorted(root.glob("*/[0-9]*.json"))


def metadata_index(root: Path) -> dict[int, dict]:
    result = {}
    for path in root.glob("*/episodes_metadata.json"):
        for row in json.loads(path.read_text()):
            if "id" in row:
                result[int(row["id"])] = row
    return result


def seed_identities(path: Path, metadata: dict[int, dict], signatures: set[tuple[int, ...]]) -> list[dict]:
    """Discover submission IDs cheaply from the already-extracted Lucario shard."""
    unique = {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if canonical_deck(row.get("deck", [])) not in signatures:
                continue
            episode_id, seat = int(row["episode_id"]), int(row["seat"])
            meta = metadata.get(episode_id, {})
            agents = meta.get("agents", [])
            agent = agents[seat] if len(agents) > seat else {}
            unique[(episode_id, seat)] = {
                "episode_id": episode_id, "seat": seat, "team": row.get("team", ""),
                "submission_id": agent.get("submissionId"), "created_at": meta.get("createTime", ""),
            }
    return list(unique.values())


def episode_identity(path: Path, metadata: dict[int, dict], signatures: set[tuple[int, ...]]) -> list[dict]:
    episode = json.loads(path.read_text())
    fallback = path.name.removeprefix("episode-").removesuffix("-replay.json").removesuffix(".json")
    episode_id = int(episode.get("info", {}).get("EpisodeId") or fallback)
    steps = episode.get("steps", [])
    if len(steps) < 2:
        return []
    names = episode.get("info", {}).get("TeamNames", ["seat_0", "seat_1"])
    agents = metadata.get(episode_id, {}).get("agents", [])
    created = metadata.get(episode_id, {}).get("createTime", "")
    found = []
    for seat in (0, 1):
        cards = steps[1][seat].get("action", []) if len(steps[1]) > seat else []
        if canonical_deck(cards) not in signatures:
            continue
        agent = agents[seat] if len(agents) > seat else {}
        found.append({
            "episode_id": episode_id,
            "seat": seat,
            "team": names[seat] if len(names) > seat else f"seat_{seat}",
            "submission_id": agent.get("submissionId"),
            "created_at": created,
            "path": str(path),
        })
    return found


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def extract_submission_shard(
    submission: int, episodes: list[dict], signatures: set[tuple[int, ...]],
    shard: Path, audit: Path, workers: int, request_delay: float = 1.0,
) -> dict:
    if shard.exists() and audit.exists():
        existing = json.loads(audit.read_text())
        if existing.get("output_sha256") == sha256_file(shard) and not existing.get("download_failures"):
            return existing
    shard.parent.mkdir(parents=True, exist_ok=True)
    temporary_shard = shard.with_name(shard.name + ".tmp")
    decisions = downloads = failures = 0
    failed_episode_ids = []
    episode_seats = set()
    seen = set()
    with tempfile.TemporaryDirectory(prefix=f"lucario-{submission}-") as temporary_dir:
        download_dir = Path(temporary_dir)
        with deterministic_gzip_text(temporary_shard) as output:
            for start in range(0, len(episodes), max(1, workers * 2)):
                batch = episodes[start : start + max(1, workers * 2)]
                def paced_download(episode_id: int):
                    result = download_one(episode_id, download_dir)
                    time.sleep(max(0.0, request_delay))
                    return result
                with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = {pool.submit(paced_download, int(row["id"])): row for row in batch if "id" in row}
                    for future in concurrent.futures.as_completed(futures):
                        metadata = futures[future]
                        episode_id, status = future.result()
                        if status == "failed" or str(status).startswith("failed"):
                            failures += 1
                            failed_episode_ids.append(int(episode_id))
                            continue
                        downloads += int(status == "downloaded")
                        path = download_dir / f"episode-{episode_id}-replay.json"
                        if not path.exists():
                            path = download_dir / f"{episode_id}.json"
                        identities = episode_identity(path, {int(episode_id): metadata}, signatures)
                        for identity in identities:
                            for record in iter_decisions(load_episode(path), {identity["team"]}, feature_version=2):
                                row = record.to_json()
                                if int(row.get("seat", -1)) != identity["seat"] or canonical_deck(row.get("deck", [])) not in signatures:
                                    continue
                                key = (str(row["episode_id"]), int(row["seat"]), int(row["step"]))
                                if key in seen:
                                    continue
                                seen.add(key)
                                row.update({key: identity[key] for key in ("submission_id", "created_at")})
                                output.write(json.dumps(row, separators=(",", ":")) + "\n")
                                decisions += 1
                                episode_seats.add((episode_id, identity["seat"]))
                        path.unlink(missing_ok=True)
    os.replace(temporary_shard, shard)
    result = {
        "submission_id": submission, "episodes_listed": len(episodes), "downloads": downloads,
        "download_failures": failures, "episode_seats": len(episode_seats), "decisions": decisions,
        "failed_episode_ids": failed_episode_ids,
        "output": str(shard), "output_sha256": sha256_file(shard),
    }
    write_json(audit, result)
    return result


def fetch_with_retry(submission: int, attempts: int = 7) -> list[dict]:
    for attempt in range(attempts):
        try:
            return fetch_episodes(submission)
        except urllib.error.HTTPError as error:
            if error.code != 429 or attempt + 1 == attempts:
                raise
            time.sleep(min(60, 5 * (2 ** attempt)))
    raise AssertionError("unreachable")


def timeline_sample(episodes: list[dict], maximum: int) -> list[dict]:
    ordered = sorted(episodes, key=lambda row: str(row.get("createTime", "")))
    if maximum <= 0 or len(ordered) <= maximum:
        return ordered
    if maximum == 1:
        return [ordered[-1]]
    indices = {round(index * (len(ordered) - 1) / (maximum - 1)) for index in range(maximum)}
    return [ordered[index] for index in sorted(indices)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-root", default="data/replays")
    parser.add_argument("--deck", action="append", required=True)
    parser.add_argument("--output", default="artifacts/lucario_gap_20260803/data/lucario_expanded_raw.jsonl.gz")
    parser.add_argument("--manifest", default="artifacts/lucario_gap_20260803/data/acquisition.json")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seed-shard", default="artifacts/lucario_bc/lucario_raw.jsonl.gz")
    parser.add_argument("--skip-fetch", action="store_true")
    parser.add_argument("--discover-only", action="store_true")
    parser.add_argument("--max-episodes-per-submission", type=int, default=12)
    parser.add_argument("--request-delay", type=float, default=1.0)
    args = parser.parse_args()

    replay_root = (ROOT / args.replay_root).resolve()
    signatures = {load_deck((ROOT / value).resolve() if not Path(value).is_absolute() else value) for value in args.deck}
    before_meta = metadata_index(replay_root)
    seed_shard = (ROOT / args.seed_shard).resolve() if not Path(args.seed_shard).is_absolute() else Path(args.seed_shard)
    discovered = seed_identities(seed_shard, before_meta, signatures)
    submissions = sorted({int(row["submission_id"]) for row in discovered if row.get("submission_id")})
    manifest = {
        "version": 1,
        "discovered_submissions": submissions,
        "initial_matching_episodes": len(discovered),
        "expanded_matching_episodes": 0,
        "deck_signatures": [list(value) for value in sorted(signatures)],
        "fetch_skipped": args.skip_fetch or args.discover_only,
    }
    if args.discover_only:
        write_json(Path(args.manifest), manifest)
        print(json.dumps(manifest, indent=2))
        return 0

    if not args.skip_fetch:
        shard_root = (ROOT / args.manifest).resolve().parent / "submission_shards"
        shard_reports = []
        for submission in submissions:
            episodes = timeline_sample(fetch_with_retry(submission), args.max_episodes_per_submission)
            shard_reports.append(extract_submission_shard(
                submission, episodes, signatures, shard_root / f"{submission}.jsonl.gz",
                shard_root / f"{submission}.json", args.workers, args.request_delay,
            ))
        source_shards = [Path(row["output"]) for row in shard_reports] + [seed_shard]
    else:
        shard_root = (ROOT / args.manifest).resolve().parent / "submission_shards"
        shard_reports = [json.loads(path.read_text()) for path in sorted(shard_root.glob("*.json"))]
        source_shards = [Path(row["output"]) for row in shard_reports] + [seed_shard]

    output = (ROOT / args.output).resolve() if not Path(args.output).is_absolute() else Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    seen = set()
    decisions = duplicates = 0
    processed_episodes = set()
    with deterministic_gzip_text(temporary) as handle:
        for shard in source_shards:
            with gzip.open(shard, "rt", encoding="utf-8") as source_handle:
                for line in source_handle:
                    row = json.loads(line)
                    key = (str(row["episode_id"]), int(row["seat"]), int(row["step"]))
                    if key in seen:
                        duplicates += 1
                        continue
                    seen.add(key)
                    handle.write(json.dumps(row, separators=(",", ":")) + "\n")
                    decisions += 1
                    processed_episodes.add((str(row["episode_id"]), int(row["seat"])))
    os.replace(temporary, output)
    manifest.update({
        "output": str(output), "output_sha256": sha256_file(output), "decisions": decisions,
        "episode_seats": len(processed_episodes), "expanded_matching_episodes": len(processed_episodes),
        "duplicate_records_removed": duplicates,
        "submissions_with_decisions": sorted(row["submission_id"] for row in shard_reports if row["decisions"]),
        "submission_shards": shard_reports,
    })
    write_json((ROOT / args.manifest).resolve() if not Path(args.manifest).is_absolute() else Path(args.manifest), manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
