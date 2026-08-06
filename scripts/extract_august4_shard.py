#!/usr/bin/env python3
"""Extract decision records from raw 2026-08-04 replays into daily_extracted shard."""

import datetime
import gzip
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if (ROOT / "vendor").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

from scripts.stream_mine_and_cleanup import load_deck, stream_download_and_extract

def main():
    raw_root = ROOT / "data" / "raw_episodes"
    extracted_root = ROOT / "data" / "daily_extracted"
    extracted_root.mkdir(parents=True, exist_ok=True)
    deck_path = ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv"
    grim_sig = load_deck(deck_path)
    ref_date = datetime.date(2026, 8, 4)

    print("Extracting 2026-08-04 raw replays...", flush=True)
    stream_download_and_extract("2026-08-04", grim_sig, ref_date, raw_root, extracted_root, workers=10)
    print("Finished extracting 2026-08-04 decisions shard!", flush=True)

if __name__ == "__main__":
    main()
