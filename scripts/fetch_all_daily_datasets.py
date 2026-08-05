#!/usr/bin/env python3
"""Discover and bulk-download all available daily episode datasets from Kaggle.

Downloads the full daily archives directly using `--unzip`, avoiding per-file
API rate limits and ensuring complete local replay coverage.
Resumes automatically from existing complete folders.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KAGGLE = ["kaggle"] if shutil.which("kaggle") else [sys.executable, "-m", "kaggle"]


def list_available_dates() -> list[str]:
    """Query Kaggle datasets API across search queries to get all daily dates."""
    print("Querying Kaggle API for all Pokémon TCG daily datasets...", flush=True)
    all_refs = set()
    for search_term in ["pokemon-tcg-ai-battle-episodes-2026-06", "pokemon-tcg-ai-battle-episodes-2026-07", "pokemon-tcg-ai-battle-episodes-2026-08"]:
        cmd = [*KAGGLE, "datasets", "list", "-s", search_term, "--page-size", "100", "--format", "json"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        try:
            items = json.loads(res.stdout)
            for item in items:
                ref = item.get("ref", "")
                if "pokemon-tcg-ai-battle-episodes-2026-" in ref:
                    all_refs.add(ref)
        except Exception as e:
            print(f"Error querying {search_term}: {e}", flush=True)

    dates = sorted([ref.split("pokemon-tcg-ai-battle-episodes-")[-1] for ref in all_refs])
    print(f"Found {len(dates)} available daily datasets on Kaggle: {dates}", flush=True)
    return dates


def download_day(date_str: str, target_dir: Path, max_retries: int = 5) -> bool:
    """Download and unzip a full daily dataset."""
    dataset = f"kaggle/pokemon-tcg-ai-battle-episodes-{date_str}"
    day_dir = target_dir / date_str
    day_dir.mkdir(parents=True, exist_ok=True)

    json_files = list(day_dir.glob("*.json")) + list(day_dir.glob("*.json.gz"))
    if len(json_files) > 100:
        print(f"[{date_str}] Already downloaded ({len(json_files)} episodes present). Skipping.", flush=True)
        return True

    # Clean up incomplete downloads
    for z in day_dir.glob("*.zip"):
        try:
            z.unlink()
        except Exception:
            pass

    print(f"[{date_str}] Starting bulk download from {dataset}...", flush=True)
    cmd = [*KAGGLE, "datasets", "download", dataset, "-p", str(day_dir), "--unzip"]
    
    for attempt in range(max_retries):
        started = time.time()
        res = subprocess.run(cmd, capture_output=True, text=True)
        elapsed = time.time() - started
        if res.returncode == 0:
            json_files = list(day_dir.glob("*.json")) + list(day_dir.glob("*.json.gz"))
            if len(json_files) > 50:
                print(f"[{date_str}] Successfully downloaded and unpacked {len(json_files)} episodes in {elapsed:.1f}s.", flush=True)
                return True
        print(f"[{date_str}] Attempt {attempt + 1} failed: {res.stderr.strip()[:200]}. Retrying in 10s...", flush=True)
        time.sleep(10)

    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dates", nargs="*", help="Specific dates to download")
    parser.add_argument("--output-dir", default="data/raw_episodes", help="Output directory for raw replays")
    parser.add_argument("--parallel", type=int, default=3, help="Concurrent daily downloads")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.dates:
        target_dates = args.dates
    else:
        target_dates = list_available_dates()

    print(f"\nTargeting {len(target_dates)} daily datasets for download into {output_dir}:", flush=True)
    for d in target_dates:
        print(f" - {d}", flush=True)

    manifest = {"downloaded_dates": [], "failed_dates": []}

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as pool:
        future_to_date = {pool.submit(download_day, d, output_dir): d for d in target_dates}
        for future in concurrent.futures.as_completed(future_to_date):
            d = future_to_date[future]
            try:
                success = future.result()
                if success:
                    manifest["downloaded_dates"].append(d)
                else:
                    manifest["failed_dates"].append(d)
            except Exception as exc:
                print(f"[{d}] Exception during download: {exc}", flush=True)
                manifest["failed_dates"].append(d)

    manifest_path = output_dir / "download_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"\nDownload summary written to {manifest_path}", flush=True)
    print(f"Successfully downloaded {len(manifest['downloaded_dates'])} / {len(target_dates)} dates.", flush=True)


if __name__ == "__main__":
    main()
