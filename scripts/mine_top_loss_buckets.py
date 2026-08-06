#!/usr/bin/env python3
"""Mine top-team replays across specific high-tier loss buckets.

Buckets targeted:
1. Grass / Teal Mask Ogerpon ex weakness matchups (Card 96, etc.)
2. High-HP Tanks / Mega Kangaskhan ex / Bellibolt ex (Card 756, etc.)
3. Fast Fighting Aggro / Solrock / Lunatone / Makuhita / Lucario
4. Elite Top-Team Grimmsnarl Mirror Matches (from top_teams.txt / high-ELO)
5. Going-Second (Seat 1) Lone-Basic Defensive Recovery states
"""

import gzip
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if (ROOT / "vendor").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

from ptcg_ai.features import MAX_SELECT_COUNT

TOP_TEAMS_PATH = ROOT / "data" / "top_teams.txt"
GRIM_DECK_PATH = ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv"
OUT_DIR = ROOT / "artifacts" / "top_loss_buckets"
OUT_SHARD = OUT_DIR / "elite_loss_buckets_train.jsonl.gz"
LOG_FILE = OUT_DIR / "mining.log"

# Key Card IDs
OGERPON_CARD_ID = 96
KANGASKHAN_CARD_ID = 756
BELLIBOLT_CARD_ID = 741
LUCARIO_CARD_ID = 434
SOLROCK_CARD_ID = 301
MAKUHITA_CARD_ID = 405
MARNIE_IMPIDIMP_ID = 646
MARNIE_GRIMMSNARL_ID = 648
SNORUNT_ID = 860
MUNKIDORI_ID = 650

def log(msg: str):
    ts = time.strftime("[%Y-%m-%d %H:%M:%S]")
    line = f"{ts} {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def canonical_deck(deck) -> tuple[int, ...]:
    return tuple(sorted(deck))

def load_top_teams() -> set[str]:
    teams = set()
    if TOP_TEAMS_PATH.exists():
        for line in TOP_TEAMS_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                teams.add(line.lower())
    return teams

def parse_extracted_shards(extracted_dir: Path, grim_sig: tuple[int, ...], top_teams: set[str]):
    shards = sorted(list(extracted_dir.glob("*_decisions.jsonl.gz")))
    log(f"Found {len(shards)} extracted daily shards in {extracted_dir.name}.")

    bucket_stats = defaultdict(int)
    mined_records = []

    for shard in shards:
        date_str = shard.name.split("_")[0]
        log(f"Scanning shard {shard.name} for elite loss buckets...")
        shard_count = 0

        with gzip.open(shard, "rt", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                row = json.loads(line)
                shard_count += 1

                seat = row.get("seat", 0)
                reward = row.get("reward", 1.0)
                team = str(row.get("team", "")).lower()
                opp_team = str(row.get("opponent_team", "")).lower()
                is_top_team = any(t in team for t in top_teams) or any(t in opp_team for t in top_teams)
                
                opp_deck_str = row.get("opponent_deck_cards", "")
                opp_cards = set(map(int, opp_deck_str.split())) if opp_deck_str else set()
                
                # Check match characteristics
                has_ogerpon = OGERPON_CARD_ID in opp_cards
                has_kanga = KANGASKHAN_CARD_ID in opp_cards
                has_bellibolt = BELLIBOLT_CARD_ID in opp_cards
                has_lucario = LUCARIO_CARD_ID in opp_cards or MAKUHITA_CARD_ID in opp_cards or SOLROCK_CARD_ID in opp_cards
                is_mirror = row.get("opponent_exact_grim", False) or row.get("opponent_archetype") == "grim_mirror"

                turn = row.get("turn", 1)
                bench_count = row.get("bench_count", 0)

                weight = 1.0
                matched_buckets = []

                # Bucket 1: Grass / Ogerpon ex Weakness Matchup
                if has_ogerpon:
                    weight = 4.0
                    matched_buckets.append("grass_ogerpon")
                    bucket_stats["grass_ogerpon"] += 1

                # Bucket 2: 300 HP Tank / Kangaskhan / Bellibolt Matchup
                elif has_kanga or has_bellibolt:
                    weight = 3.0
                    matched_buckets.append("tank_kanga_bellibolt")
                    bucket_stats["tank_kanga_bellibolt"] += 1

                # Bucket 3: Fast Fighting Aggro (Lucario / Solrock / Makuhita)
                elif has_lucario:
                    weight = 3.0
                    matched_buckets.append("fighting_aggro")
                    bucket_stats["fighting_aggro"] += 1

                # Bucket 4: High-ELO / Top-Team Mirror Match
                elif is_mirror and is_top_team:
                    weight = 2.5
                    matched_buckets.append("top_team_mirror")
                    bucket_stats["top_team_mirror"] += 1

                # Bucket 5: Seat 1 (Going Second) Lone-Basic Survival
                elif seat == 1 and turn <= 2 and bench_count <= 1:
                    weight = 3.5
                    matched_buckets.append("seat1_lone_basic")
                    bucket_stats["seat1_lone_basic"] += 1

                # General Elite Top-Team Winning Games
                elif is_top_team and reward > 0:
                    weight = 2.0
                    matched_buckets.append("top_team_general")
                    bucket_stats["top_team_general"] += 1

                # Include standard winning mirror data with base weight
                elif is_mirror and reward > 0:
                    weight = 1.0
                    matched_buckets.append("standard_mirror")
                    bucket_stats["standard_mirror"] += 1

                if matched_buckets:
                    row["sample_weight"] = weight
                    row["loss_buckets"] = matched_buckets
                    mined_records.append(row)

    log(f"\nMining complete! Extracted {len(mined_records)} bucket-targeted decision records.")
    for b_name, count in sorted(bucket_stats.items(), key=lambda x: -x[1]):
        log(f"  - {b_name:25s}: {count:,} records")

    return mined_records

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text("")
    log("=== STARTING TOP-TEAM LOSS-BUCKET REPLAY MINER ===")

    top_teams = load_top_teams()
    log(f"Loaded {len(top_teams)} top leaderboard teams from {TOP_TEAMS_PATH.name}.")

    grim_cards = [int(line.strip()) for line in GRIM_DECK_PATH.read_text().splitlines() if line.strip()]
    grim_sig = canonical_deck(grim_cards)
    log(f"Loaded Hero Grimmsnarl deck signature ({len(grim_sig)} cards).")

    extracted_dir = ROOT / "data" / "daily_extracted"
    if not extracted_dir.exists():
        log(f"Error: {extracted_dir} does not exist.")
        return 1

    records = parse_extracted_shards(extracted_dir, grim_sig, top_teams)

    log(f"\nCompressing and saving to {OUT_SHARD}...")
    with gzip.open(OUT_SHARD, "wt", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    size_mb = OUT_SHARD.stat().st_size / (1024 * 1024)
    log(f"Dataset successfully saved: {OUT_SHARD.name} ({size_mb:.2f} MB, {len(records):,} records)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
