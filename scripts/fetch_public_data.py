#!/usr/bin/env python3
"""Fetch a bounded sample of the official top-episode datasets via Kaggle CLI."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import random
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path


KAGGLE = ["kaggle"] if shutil.which("kaggle") else [sys.executable, "-m", "kaggle"]


def command_page(command: list[str]):
    result = subprocess.run(command, check=True, text=True, capture_output=True)
    # Some paginated Kaggle CLI commands print a next-page token before JSON.
    start = result.stdout.find("[")
    if start < 0:
        start = result.stdout.find("{")
    if start < 0:
        raise RuntimeError(f"Kaggle CLI did not return JSON: {result.stdout[:500]}")
    token_match = re.search(r"Next Page Token = (\S+)", result.stdout[:start])
    return json.loads(result.stdout[start:]), token_match.group(1) if token_match else None


def fetch_one(dataset: str, filename: str, output: Path) -> tuple[str, str]:
    target = output / filename
    if target.exists() and target.stat().st_size > 0:
        return filename, "cached"
    command = [*KAGGLE, "datasets", "download", dataset, "-f", filename, "-p", str(output), "-q"]
    for attempt in range(4):
        result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode == 0 and target.exists() and target.stat().st_size > 0:
            return filename, "downloaded"
        time.sleep(2 ** attempt)
    return filename, "failed"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="YYYY-MM-DD daily episode dataset")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument("--output-root", default="data/replays")
    parser.add_argument("--max-retry-seconds", type=int, default=1800)
    args = parser.parse_args()

    dataset = f"kaggle/pokemon-tcg-ai-battle-episodes-{args.date}"
    output = Path(args.output_root) / args.date
    output.mkdir(parents=True, exist_ok=True)

    # A full daily dataset can contain several thousand files. Downloading each
    # one separately quickly trips Kaggle's API throttling, while the native
    # bulk archive uses one resumable request and unpacks the same public files.
    if args.limit == 0:
        command = [*KAGGLE, "datasets", "download", dataset, "-p", str(output), "--unzip"]
        started = time.monotonic()
        for attempt in range(6):
            result = subprocess.run(command)
            if result.returncode == 0:
                break
            if attempt == 5:
                return result.returncode
            delay = min(600, 60 * (2 ** attempt))
            if time.monotonic() - started + delay > args.max_retry_seconds:
                print({"bulk_aborted": True, "reason": "retry_budget_exhausted", "elapsed_seconds": time.monotonic() - started}, flush=True)
                return result.returncode
            print({"bulk_retry": attempt + 1, "delay_seconds": delay}, flush=True)
            time.sleep(delay)
        files = list(output.glob("*.json")) + list(output.glob("*.json.gz"))
        print({"complete": len(files), "total": len(files), "bulk": True, "output": str(output)})
        return 0

    listing = []
    page_token = None
    while True:
        command = [
            *KAGGLE, "datasets", "files", dataset,
            "--page-size", "200", "--format", "json",
        ]
        if page_token:
            command.extend(["--page-token", page_token])
        page, page_token = command_page(command)
        listing.extend(page)
        if not page_token or (args.limit and len(listing) >= args.limit):
            break
    files = [item["name"] for item in listing if item["name"].endswith(".json")]
    random.Random(args.seed).shuffle(files)
    if args.limit:
        files = files[: min(args.limit, len(files))]
    counts = {"cached": 0, "downloaded": 0, "failed": 0}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(fetch_one, dataset, filename, output) for filename in files]
        for future in concurrent.futures.as_completed(futures):
            _, status = future.result()
            counts[status] += 1
            done = sum(counts.values())
            if done % 25 == 0 or done == len(files):
                print({"complete": done, "total": len(files), **counts})
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
