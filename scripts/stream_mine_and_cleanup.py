#!/usr/bin/env python3
"""Streaming miner and disk-space optimizer.

Extracts exact-deck decisions and features from downloaded daily datasets,
saves compact compressed daily decision shards to `data/daily_extracted/`,
and immediately deletes the uncompressed raw JSON episode files to keep
local disk usage minimal (< 10 GB total).
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
import shutil
import subprocess
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
KAGGLE = ["kaggle"] if shutil.which("kaggle") else [sys.executable, "-m", "kaggle"]

LUCARIO_CARD_ID = 448
ALAKAZAM_CARD_ID = 65
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

    try:
        ep_date = datetime.date.fromisoformat(date_str)
        age_days = max(0, (reference_date - ep_date).days)
    except Exception:
        age_days = 0
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

    for seat, d_rows in seat_decisions.items():
        if not d_rows:
            continue
        per_step_weight = (recency_weight * 30.0) / float(len(d_rows))
        for r in d_rows:
            r["sample_weight"] = per_step_weight
            rows.append(r)

    return {"status": "extracted", "rows": rows, "units": units}


def mine_date_folder(
    d_dir: Path,
    grim_signature: tuple[int, ...],
    reference_date: datetime.date,
    extracted_root: Path,
    workers: int = 8,
) -> int:
    date_str = d_dir.name
    out_file = extracted_root / f"{date_str}_decisions.jsonl.gz"
    
    if out_file.exists():
        print(f"[{date_str}] Already extracted into {out_file.name}. Cleaning raw folder...", flush=True)
        shutil.rmtree(d_dir, ignore_errors=True)
        return 1

    files = list(d_dir.glob("*.json")) + list(d_dir.glob("*.json.gz"))
    if not files:
        print(f"[{date_str}] No raw files found in {d_dir}. Removing empty dir.", flush=True)
        shutil.rmtree(d_dir, ignore_errors=True)
        return 0

    print(f"[{date_str}] Extracting decisions from {len(files)} raw episode files...", flush=True)
    all_tasks = [(f, grim_signature, date_str, reference_date, True) for f in files]
    
    results = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(process_single_episode, *t) for t in all_tasks]
        for fut in concurrent.futures.as_completed(futures):
            results.append(fut.result())

    rows = []
    seen = set()
    for res in results:
        for r in res.get("rows", []):
            k = (str(r["episode_id"]), int(r["seat"]), int(r["step"]))
            if k not in seen:
                seen.add(k)
                rows.append(r)

    rows.sort(key=lambda r: (str(r["episode_id"]), int(r["seat"]), int(r["step"])))
    print(f"[{date_str}] Extracted {len(rows)} exact Grim decisions. Saving to {out_file.name}...", flush=True)

    extracted_root.mkdir(parents=True, exist_ok=True)
    tmp_out = out_file.with_suffix(".tmp")
    with deterministic_gzip_text(tmp_out) as handle:
        for r in rows:
            handle.write(json.dumps(r, separators=(",", ":")) + "\n")
    tmp_out.replace(out_file)

    shutil.rmtree(d_dir, ignore_errors=True)
    return len(rows)


def stream_download_and_extract(
    date_str: str,
    grim_signature: tuple[int, ...],
    reference_date: datetime.date,
    raw_root: Path,
    extracted_root: Path,
    workers: int = 8,
) -> int:
    out_file = extracted_root / f"{date_str}_decisions.jsonl.gz"
    if out_file.exists():
        print(f"[{date_str}] Already processed and saved. Skipping download.", flush=True)
        return 1

    day_dir = raw_root / date_str
    day_dir.mkdir(parents=True, exist_ok=True)

    dataset = f"kaggle/pokemon-tcg-ai-battle-episodes-{date_str}"
    print(f"[{date_str}] Downloading {dataset}...", flush=True)
    cmd = [*KAGGLE, "datasets", "download", dataset, "-p", str(day_dir), "--unzip"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"[{date_str}] Download failed: {res.stderr.strip()[:200]}", flush=True)
        shutil.rmtree(day_dir, ignore_errors=True)
        return 0

    return mine_date_folder(day_dir, grim_signature, reference_date, extracted_root, workers)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", default="data/raw_episodes", help="Root folder of raw episode JSONs")
    parser.add_argument("--extracted-dir", default="data/daily_extracted", help="Root folder for compressed extracted shards")
    parser.add_argument("--deck", default=str(DEFAULT_DECK), help="Hero deck CSV path")
    parser.add_argument("--workers", type=int, default=8, help="Worker processes")
    args = parser.parse_args()

    raw_root = Path(args.raw_dir).resolve()
    extracted_root = Path(args.extracted_dir).resolve()
    extracted_root.mkdir(parents=True, exist_ok=True)

    deck_path = Path(args.deck).resolve()
    grim_signature = load_deck(deck_path)
    reference_date = datetime.date(2026, 8, 3)

    all_dates = [
        "2026-06-16", "2026-06-17", "2026-06-18", "2026-06-19", "2026-06-20",
        "2026-06-21", "2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25",
        "2026-06-26", "2026-06-27", "2026-06-28", "2026-06-29", "2026-06-30",
        "2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04", "2026-07-05",
        "2026-07-06", "2026-07-07", "2026-07-08", "2026-07-10", "2026-07-11",
        "2026-07-12", "2026-07-14", "2026-07-15", "2026-07-16", "2026-07-20",
        "2026-07-23", "2026-07-24", "2026-07-25", "2026-07-26", "2026-07-29",
        "2026-08-01", "2026-08-02", "2026-08-03"
    ]

    print("Checking daily shards status...", flush=True)
    for date_str in all_dates:
        stream_download_and_extract(date_str, grim_signature, reference_date, raw_root, extracted_root, args.workers)

    # Assemble full multiday splits from extracted daily shards
    print("\nAssembling unified multiday splits from daily shards...", flush=True)
    all_shards = sorted(list(extracted_root.glob("*_decisions.jsonl.gz")))
    print(f"Found {len(all_shards)} extracted daily shards.", flush=True)

    all_rows = []
    seen = set()
    temporal_date = all_dates[-1]

    for shard in all_shards:
        with gzip.open(shard, "rt", encoding="utf-8") as handle:
            for line in handle:
                r = json.loads(line)
                k = (str(r["episode_id"]), int(r["seat"]), int(r["step"]))
                if k not in seen:
                    seen.add(k)
                    if r.get("source_date") == temporal_date:
                        r["split"] = "temporal"
                    elif stable_team_bucket(r.get("team", "")) == 0:
                        r["split"] = "team_holdout"
                    elif (zlib.crc32(str(r.get("episode_id", "")).encode("utf-8")) % 10) == 0:
                        r["split"] = "validation"
                    else:
                        r["split"] = "train"
                    all_rows.append(r)

    all_rows.sort(key=lambda r: (str(r["episode_id"]), int(r["seat"]), int(r["step"])))
    print(f"Total unified decisions: {len(all_rows)}", flush=True)

    out_dir = ROOT / "data" / "multiday_processed"
    out_dir.mkdir(parents=True, exist_ok=True)

    def write_gz(path, row_list):
        tmp = path.with_name(path.name + ".tmp")
        with deterministic_gzip_text(tmp) as h:
            for r in row_list:
                h.write(json.dumps(r, separators=(",", ":")) + "\n")
        tmp.replace(path)
        print(f"Wrote {len(row_list)} rows to {path.name}", flush=True)

    write_gz(out_dir / "multiday_winning_decisions.jsonl.gz", all_rows)
    write_gz(out_dir / "train.jsonl.gz", [r for r in all_rows if r["split"] == "train"])
    write_gz(out_dir / "validation.jsonl.gz", [r for r in all_rows if r["split"] == "validation"])
    write_gz(out_dir / "team_holdout.jsonl.gz", [r for r in all_rows if r["split"] == "team_holdout"])
    write_gz(out_dir / "temporal_holdout.jsonl.gz", [r for r in all_rows if r["split"] == "temporal"])

    split_counts = Counter(r["split"] for r in all_rows)
    arch_counts = Counter(r.get("opponent_archetype", "other") for r in all_rows)

    manifest = {
        "created_at": datetime.datetime.now().isoformat(),
        "total_shards": len(all_shards),
        "total_decisions": len(all_rows),
        "split_counts": dict(split_counts),
        "archetype_counts": dict(arch_counts),
    }
    (out_dir / "multiday_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Manifest written to {out_dir / 'multiday_manifest.json'}", flush=True)

    total, used, free = shutil.disk_usage("C:/")
    print(f"\nDone! Final disk usage - Free: {free / (1024**3):.2f} GB (Used: {used / (1024**3):.2f} GB)", flush=True)


if __name__ == "__main__":
    main()
