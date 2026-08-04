#!/usr/bin/env python3
"""Download all episode replays for a submission from Kaggle CLI in parallel."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KAGGLE = "/Users/safiullahbaig/Library/Python/3.11/bin/kaggle"


def download_one(ep_id: int, output_dir: Path) -> tuple[int, str]:
    target_file = output_dir / f"episode-{ep_id}-replay.json"
    if target_file.exists() and target_file.stat().st_size > 0:
        return ep_id, "skipped"

    command = [KAGGLE, "competitions", "replay", str(ep_id), "-p", str(output_dir)]
    
    # Retry loop
    for attempt in range(3):
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0 and target_file.exists() and target_file.stat().st_size > 0:
            time.sleep(0.2)  # Minor pacing delay
            return ep_id, "downloaded"
        time.sleep(1.0)
        
    return ep_id, "failed"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", type=int, required=True)
    parser.add_argument("--input", default="artifacts/ladder/episodes.json")
    parser.add_argument("--output-dir", default="data/replays/55114709")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    input_path = ROOT / args.input
    if not input_path.exists():
        print(f"Error: input file {input_path} not found.")
        return 1

    output_dir = ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    episodes = json.loads(input_path.read_text())
    episode_ids = [ep["episode"] for ep in episodes if "episode" in ep]
    total = len(episode_ids)
    print(f"Found {total} episodes in {input_path.name}")

    counts = {"skipped": 0, "downloaded": 0, "failed": 0}
    
    # Download in parallel using ThreadPoolExecutor
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_to_id = {
            executor.submit(download_one, ep_id, output_dir): ep_id
            for ep_id in episode_ids
        }
        
        for index, future in enumerate(concurrent.futures.as_completed(future_to_id), 1):
            ep_id = future_to_id[future]
            try:
                ep_id, status = future.result()
                counts[status] += 1
            except Exception as e:
                print(f"Episode {ep_id} raised exception: {e}")
                counts["failed"] += 1
            
            if index % 5 == 0 or index == total:
                print(f"[{index}/{total}] Completed. downloaded={counts['downloaded']}, skipped={counts['skipped']}, failed={counts['failed']}")

    print(f"Finished. Total counts: {counts}")
    return 1 if counts["failed"] > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
