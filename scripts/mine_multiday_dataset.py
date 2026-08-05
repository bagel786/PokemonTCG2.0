#!/usr/bin/env python3
"""Multi-day dataset miner for Kaggle Pokémon TCG AI Battle.

Processes full raw episode JSON files across all available dates, extracting
exact-deck decisions, calculating opponent archetypes, applying exponential
recency weighting (w = 2^(-age_days / 3)), normalizing per-episode-seat
contributions, and generating leakage-safe train/val/team-holdout/temporal splits.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import gzip
import hashlib
import json
import math
import os
import random
import shutil
import sys
import time
import zlib
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

from ptcg_ai.replay import episode_reward, iter_decisions, load_episode
from training.lucario_data import canonical_deck, deterministic_gzip_text, load_deck, sha256_file
from training.replay_refresh import stable_team_bucket

DEFAULT_DECK = ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv"
LUCARIO_CARD_ID = 448
ALAKAZAM_CARD_ID = 65
RAGING_BOLT_CARD_ID = 1021  # Or standard lightning/ancient signature
CRUSTLE_CARD_ID = 558


def deck_hash(signature: tuple[int, ...]) -> str:
    payload = ",".join(map(str, signature)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def detect_archetype(deck: tuple[int, ...]) -> str:
    deck_set = set(deck)
    if LUCARIO_CARD_ID in deck_set:
        return "lucario"
    if ALAKAZAM_CARD_ID in deck_set:
        return "alakazam"
    if CRUSTLE_CARD_ID in deck_set:
        return "crustle"
    return "other"


def process_single_episode(
    path: Path,
    grim_signature: tuple[int, ...],
    date_str: str,
    reference_date: datetime.date,
    winner_only: bool = True,
) -> dict:
    """Process a single episode file and return extracted decision rows and metadata."""
    try:
        episode = load_episode(path)
    except Exception as exc:
        return {"status": "corrupt", "rows": [], "units": [], "error": str(exc)}

    steps = episode.get("steps") or []
    if len(steps) < 2 or len(steps[1]) < 2:
        return {"status": "invalid_steps", "rows": [], "units": []}

    decks = [canonical_deck(steps[1][seat].get("action", [])) for seat in (0, 1)]
    if any(len(deck) != 60 for deck in decks):
        return {"status": "invalid_deck_length", "rows": [], "units": []}

    exact_grim_seats = [seat for seat in (0, 1) if decks[seat] == grim_signature]
    if not exact_grim_seats:
        return {"status": "non_grim", "rows": [], "units": []}

    info = episode.get("info") or {}
    episode_id = str(info.get("EpisodeId") or path.stem)
    team_names = info.get("TeamNames") or ["seat_0", "seat_1"]

    # Calculate date age and recency weight
    try:
        ep_date = datetime.date.fromisoformat(date_str)
        age_days = max(0, (reference_date - ep_date).days)
    except Exception:
        age_days = 0
    # Exponential recency decay: 2^(-age_days / 3)
    recency_weight = math.pow(2.0, -float(age_days) / 3.0)

    units = []
    eligible_seats = set()
    for seat in exact_grim_seats:
        reward = episode_reward(episode, seat)
        if reward is None:
            continue
        reward = float(reward)
        team = team_names[seat] if len(team_names) > seat else f"seat_{seat}"
        opp_deck = decks[1 - seat]
        opp_is_grim = opp_deck == grim_signature
        opp_archetype = "grim_mirror" if opp_is_grim else detect_archetype(opp_deck)

        units.append(
            {
                "episode_id": episode_id,
                "seat": seat,
                "team": team,
                "date": date_str,
                "age_days": age_days,
                "recency_weight": recency_weight,
                "reward": reward,
                "opponent_exact_grim": opp_is_grim,
                "opponent_archetype": opp_archetype,
                "opponent_deck_sha256": deck_hash(opp_deck),
            }
        )
        if not winner_only or reward > 0:
            eligible_seats.add(seat)

    if not eligible_seats:
        return {"status": "no_eligible_seats", "rows": [], "units": units}

    # Extract decisions with feature schema v2
    rows = []
    seat_decisions = defaultdict(list)
    for decision in iter_decisions(episode, None, feature_version=2):
        if decision.seat not in eligible_seats:
            continue
        row = decision.to_json()
        opp_deck = decks[1 - decision.seat]
        opp_is_grim = opp_deck == grim_signature
        opp_archetype = "grim_mirror" if opp_is_grim else detect_archetype(opp_deck)

        row.update(
            {
                "source": "daily_kaggle_dataset",
                "source_date": date_str,
                "age_days": age_days,
                "date_recency_weight": recency_weight,
                "opponent_exact_grim": opp_is_grim,
                "opponent_archetype": opp_archetype,
                "opponent_deck_sha256": deck_hash(opp_deck),
            }
        )
        seat_decisions[decision.seat].append(row)

    # Normalize weights per episode-seat so every game contributes equally
    for seat, d_rows in seat_decisions.items():
        if not d_rows:
            continue
        # Per-decision weight = recency_weight / count(decisions in this game)
        # Scaled such that average 30-decision game has weight ~recency_weight
        per_step_weight = (recency_weight * 30.0) / float(len(d_rows))
        for r in d_rows:
            r["sample_weight"] = per_step_weight
            rows.append(r)

    return {"status": "extracted", "rows": rows, "units": units}


def assign_split(row: dict, temporal_date: str) -> str:
    """Assign data split: temporal_holdout, team_holdout, validation, or train."""
    if row.get("source_date") == temporal_date:
        return "temporal"
    team = row.get("team", "")
    if stable_team_bucket(team) == 0:
        return "team_holdout"
    ep_bucket = zlib.crc32(str(row.get("episode_id", "")).encode("utf-8")) % 10
    if ep_bucket == 0:
        return "validation"
    return "train"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", default="data/raw_episodes", help="Root folder of raw episode JSONs")
    parser.add_argument("--deck", default=str(DEFAULT_DECK), help="Hero deck CSV path")
    parser.add_argument("--output-dir", default="data/multiday_processed", help="Output directory for mined datasets")
    parser.add_argument("--workers", type=int, default=8, help="Number of extraction worker threads")
    parser.add_argument("--include-losses", action="store_true", help="Extract loss decisions as well as wins")
    parser.add_argument("--limit-per-day", type=int, default=0, help="Max episodes to parse per day (0 = all)")
    args = parser.parse_args()

    raw_root = Path(args.raw_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    deck_path = Path(args.deck).resolve()
    grim_signature = load_deck(deck_path)

    # Discover date directories
    date_dirs = sorted([d for d in raw_root.iterdir() if d.is_dir() and len(d.name) == 10 and d.name.startswith("2026-")])
    if not date_dirs:
        print(f"No daily subdirectories found in {raw_root}. Please download raw datasets first.")
        return 1

    reference_date = datetime.date.fromisoformat(date_dirs[-1].name)
    temporal_date = date_dirs[-1].name  # Newest date reserved as temporal holdout
    print(f"Processing {len(date_dirs)} daily datasets. Reference (newest) date: {reference_date}")
    print(f"Temporal holdout date: {temporal_date}")

    all_tasks = []
    for d_dir in date_dirs:
        date_str = d_dir.name
        files = list(d_dir.glob("*.json")) + list(d_dir.glob("*.json.gz"))
        if args.limit_per_day > 0:
            files = files[: args.limit_per_day]
        for f in files:
            all_tasks.append((f, grim_signature, date_str, reference_date, not args.include_losses))

    print(f"Total episode files queued: {len(all_tasks)}")
    random.shuffle(all_tasks)

    results = []
    started = time.time()
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(process_single_episode, *t) for t in all_tasks]
        for i, fut in enumerate(concurrent.futures.as_completed(futures), 1):
            results.append(fut.result())
            if i % 1000 == 0 or i == len(all_tasks):
                elapsed = time.time() - started
                print(f"Processed {i}/{len(all_tasks)} episodes ({elapsed:.1f}s, {i/elapsed:.1f} ep/s)...", flush=True)

    # Aggregate extracted rows and units
    seen = set()
    all_rows = []
    all_units = {}
    status_counts = Counter()

    for res in results:
        status_counts[res["status"]] += 1
        for unit in res["units"]:
            all_units[(str(unit["episode_id"]), int(unit["seat"]))] = unit
        for row in res["rows"]:
            key = (str(row["episode_id"]), int(row["seat"]), int(row["step"]))
            if key in seen:
                continue
            seen.add(key)
            row["split"] = assign_split(row, temporal_date)
            all_rows.append(row)

    print(f"\nExtraction complete! Status summary: {dict(status_counts)}")
    print(f"Total unique units: {len(all_units)}, Total decision rows: {len(all_rows)}")

    # Split rows by split
    split_counts = Counter(r["split"] for r in all_rows)
    archetype_counts = Counter(r["opponent_archetype"] for r in all_rows)
    date_counts = Counter(r["source_date"] for r in all_rows)

    print(f"Splits breakdown: {dict(split_counts)}")
    print(f"Opponent archetypes breakdown: {dict(archetype_counts)}")

    # Write combined and split files
    out_all_path = output_dir / "multiday_winning_decisions.jsonl.gz"
    out_train_path = output_dir / "train.jsonl.gz"
    out_val_path = output_dir / "validation.jsonl.gz"
    out_team_holdout_path = output_dir / "team_holdout.jsonl.gz"
    out_temporal_path = output_dir / "temporal_holdout.jsonl.gz"

    all_rows.sort(key=lambda r: (str(r["episode_id"]), int(r["seat"]), int(r["step"])))

    def write_gz(path, row_list):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        with deterministic_gzip_text(tmp) as h:
            for r in row_list:
                h.write(json.dumps(r, separators=(",", ":")) + "\n")
        tmp.replace(path)
        print(f"Wrote {len(row_list)} rows to {path}")

    write_gz(out_all_path, all_rows)
    write_gz(out_train_path, [r for r in all_rows if r["split"] == "train"])
    write_gz(out_val_path, [r for r in all_rows if r["split"] == "validation"])
    write_gz(out_team_holdout_path, [r for r in all_rows if r["split"] == "team_holdout"])
    write_gz(out_temporal_path, [r for r in all_rows if r["split"] == "temporal"])

    # Write manifest
    manifest = {
        "created_at": datetime.datetime.now().isoformat(),
        "reference_date": str(reference_date),
        "temporal_holdout_date": temporal_date,
        "deck": str(deck_path),
        "deck_sha256": sha256_file(deck_path),
        "total_episodes_scanned": len(all_tasks),
        "total_units": len(all_units),
        "total_decisions": len(all_rows),
        "split_counts": dict(split_counts),
        "archetype_counts": dict(archetype_counts),
        "date_counts": dict(sorted(date_counts.items())),
        "files": {
            "all": str(out_all_path),
            "train": str(out_train_path),
            "validation": str(out_val_path),
            "team_holdout": str(out_team_holdout_path),
            "temporal_holdout": str(out_temporal_path),
        },
    }
    manifest_file = output_dir / "multiday_manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2))
    print(f"Manifest written to {manifest_file}")


if __name__ == "__main__":
    main()
