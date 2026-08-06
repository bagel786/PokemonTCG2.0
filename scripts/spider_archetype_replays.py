#!/usr/bin/env python3
"""Recursive Archetype Replay Spider: Discover & mine Grimmsnarl vs Meta Matchups.

Algorithm:
1. Take seed opponent submission IDs from specific meta archetypes (Ogerpon, Kangaskhan, Lucario, Stall, etc.).
2. Query Kaggle EpisodeService for their entire match history.
3. Download and inspect each match.
4. If the match is vs Grimmsnarl, extract all decision records using ptcg_ai.features.
5. If Grimmsnarl won against the archetype, upweight the winning decisions (3.0x - 4.0x) as positive examples.
"""

import base64
import concurrent.futures
import csv
import gzip
import json
import os
import shutil
import ssl
import subprocess
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if (ROOT / "vendor").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

from ptcg_ai.replay import iter_decisions, load_episode

def canonical_deck(deck) -> tuple[int, ...]:
    return tuple(sorted(deck))

EPISODE_SERVICE = "https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodes"
KAGGLE_EXE = shutil.which("kaggle") or "kaggle"
GRIM_DECK_PATH = ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv"

OUT_DIR = ROOT / "artifacts" / "spider_mined_data"
RAW_CACHE_DIR = OUT_DIR / "raw_replays"
OUT_SHARD = OUT_DIR / "spider_grim_matchups.jsonl.gz"
LOG_FILE = OUT_DIR / "spider.log"

SEED_OPPONENT_SUBS = [
    55215839,  # Teal Mask Ogerpon ex (942.1 rating)
    55269566,  # Mega Kangaskhan ex (891.6 rating)
    55279179,  # Lucario / Solrock / Makuhita (847.6 rating)
    53837899,  # Bellibolt / Wattrel Stall (747.0 rating)
    55265370,  # Spiritomb Disruption (843.7 rating)
    55197246,  # Duraludon Control (831.5 rating)
    54454637,  # Staryu / Multi-bench (785.9 rating)
    53808571,  # Lucario Aggro (627.1 rating)
    55274653,  # Comfey / Lost Zone (866.0 rating)
    54464885,  # Top-tier 893.2 Opponent
]

def log(msg: str):
    ts = time.strftime("[%Y-%m-%d %H:%M:%S]")
    line = f"{ts} {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def auth_header() -> str:
    kaggle_json = Path.home() / ".kaggle" / "kaggle.json"
    if not kaggle_json.exists():
        return ""
    blob = json.loads(kaggle_json.read_text())
    if "access_token" in blob:
        return "Bearer " + blob["access_token"]
    pair = f"{blob['username']}:{blob['key']}".encode()
    return "Basic " + base64.b64encode(pair).decode()

def fetch_sub_episodes(sub_id: int) -> list[dict]:
    payload = json.dumps({"submissionId": sub_id}).encode()
    headers = {"Content-Type": "application/json", "User-Agent": "PTCG-Spider/1.0", "Authorization": auth_header()}
    req = urllib.request.Request(EPISODE_SERVICE, data=payload, headers=headers)
    ctx = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        return data.get("episodes", [])
    except Exception as e:
        log(f"Failed to fetch episodes for sub {sub_id}: {e}")
        return []

def download_replay(ep_id: int) -> Path | None:
    p = RAW_CACHE_DIR / f"episode-{ep_id}-replay.json"
    alt = RAW_CACHE_DIR / f"{ep_id}.json"
    if p.exists():
        return p
    if alt.exists():
        return alt
    cmd = [KAGGLE_EXE, "competitions", "replay", str(ep_id), "-p", str(RAW_CACHE_DIR)]
    subprocess.run(cmd, capture_output=True)
    if alt.exists() and not p.exists():
        alt.rename(p)
    return p if p.exists() else None

def process_episode(ep_path: Path, grim_sig: tuple[int, ...]) -> list[dict]:
    try:
        data = json.loads(ep_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    steps = data.get("steps") or []
    if len(steps) < 2 or len(steps[1]) < 2:
        return []

    decks = [canonical_deck(steps[1][seat].get("action", [])) for seat in (0, 1)]
    if any(len(deck) != 60 for deck in decks):
        return []

    # Check if Grimmsnarl is in this game
    grim_seats = [seat for seat in (0, 1) if decks[seat] == grim_sig]
    if not grim_seats:
        return []

    extracted_records = []
    for seat in grim_seats:
        last_step = steps[-1] if steps else None
        if not last_step:
            continue
        reward = last_step[seat].get("reward", 0)
        opp_deck = decks[1 - seat]
        opp_is_grim = opp_deck == grim_sig

        # Upweight winning Grimmsnarl play vs non-mirror archetypes
        weight = 1.0
        if reward == 1:
            weight = 3.5 if not opp_is_grim else 2.0
        elif reward == -1:
            weight = 0.5  # Soft weight for losses or omit

        # Extract features for all decisions made by this Grimmsnarl player
        for decision in iter_decisions(data, None, feature_version=2):
            if decision.seat != seat:
                continue
            row = decision.to_json()
            row["sample_weight"] = weight
            row["opponent_exact_grim"] = opp_is_grim
            row["reward"] = reward
            row["spider_source"] = True
            extracted_records.append(row)

    return extracted_records

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RAW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text("")
    log("=== STARTING RECURSIVE ARCHETYPE REPLAY SPIDER ===")

    grim_cards = [int(line.strip()) for line in GRIM_DECK_PATH.read_text().splitlines() if line.strip()]
    grim_sig = canonical_deck(grim_cards)
    log(f"Targeting matchups involving Grimmsnarl ({len(grim_sig)} cards).")

    all_episode_ids = set()
    log(f"Crawling match histories for {len(SEED_OPPONENT_SUBS)} target meta seed submissions...")

    for sub_id in SEED_OPPONENT_SUBS:
        eps = fetch_sub_episodes(sub_id)
        ep_ids = [e.get("id") for e in eps if e.get("id")]
        log(f"  Sub #{sub_id}: Found {len(ep_ids)} matches.")
        for eid in ep_ids:
            all_episode_ids.add(eid)

    log(f"\nTotal unique target matches discovered: {len(all_episode_ids)}")
    log("Downloading and parsing discovered match replays...")

    total_grim_decisions = []
    grim_games_count = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        future_to_id = {pool.submit(download_replay, ep_id): ep_id for ep_id in all_episode_ids}
        for future in concurrent.futures.as_completed(future_to_id):
            ep_id = future_to_id[future]
            try:
                path = future.result()
                if path:
                    records = process_episode(path, grim_sig)
                    if records:
                        grim_games_count += 1
                        total_grim_decisions.extend(records)
            except Exception as e:
                log(f"Error processing episode {ep_id}: {e}")

    log(f"\nSpider crawl complete!")
    log(f"Found {grim_games_count} Grimmsnarl matches with {len(total_grim_decisions):,} high-quality decision states.")

    log(f"Saving to {OUT_SHARD}...")
    with gzip.open(OUT_SHARD, "wt", encoding="utf-8") as f:
        for r in total_grim_decisions:
            f.write(json.dumps(r) + "\n")

    size_mb = OUT_SHARD.stat().st_size / (1024 * 1024)
    log(f"Spider dataset written: {OUT_SHARD.name} ({size_mb:.2f} MB)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
