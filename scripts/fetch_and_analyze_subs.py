#!/usr/bin/env python3
"""Fetch replays and episode metadata for submissions 55171237 and 55171235."""

import argparse
import base64
import concurrent.futures
import json
import os
import ssl
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KAGGLE = "/Users/safiullahbaig/Library/Python/3.11/bin/kaggle"
EPISODE_SERVICE = "https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodes"


def auth_header() -> str:
    blob = json.loads((Path(os.environ["HOME"]) / ".kaggle" / "kaggle.json").read_text())
    if "access_token" in blob:
        return "Bearer " + blob["access_token"]
    pair = f"{blob['username']}:{blob['key']}".encode()
    return "Basic " + base64.b64encode(pair).decode()


def fetch_episodes(submission_id: int) -> list[dict]:
    ctx = ssl._create_unverified_context()
    req = urllib.request.Request(
        EPISODE_SERVICE,
        data=json.dumps({"submissionId": submission_id}).encode(),
        headers={"Content-Type": "application/json", "Authorization": auth_header()},
    )
    with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
        return json.load(resp).get("episodes", [])


def download_one(ep_id: int, output_dir: Path) -> tuple[int, str]:
    target_file = output_dir / f"episode-{ep_id}-replay.json"
    alt_file = output_dir / f"{ep_id}.json"
    if (target_file.exists() and target_file.stat().st_size > 0) or (alt_file.exists() and alt_file.stat().st_size > 0):
        return ep_id, "skipped"

    command = [KAGGLE, "competitions", "replay", str(ep_id), "-p", str(output_dir)]
    for attempt in range(4):
        res = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if (target_file.exists() and target_file.stat().st_size > 0) or (alt_file.exists() and alt_file.stat().st_size > 0):
            return ep_id, "downloaded"
        time.sleep(1.0 * (attempt + 1))
    return ep_id, f"failed: {res.stderr.strip()}"


def download_submission_replays(submission_id: int, workers: int = 10):
    print(f"Fetching episode list for submission {submission_id}...")
    episodes = fetch_episodes(submission_id)
    print(f"Submission {submission_id}: found {len(episodes)} episodes.")

    out_dir = ROOT / "data" / "replays" / str(submission_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Save episode metadata
    meta_path = out_dir / "episodes_metadata.json"
    meta_path.write_text(json.dumps(episodes, indent=2))

    ep_ids = [ep["id"] for ep in episodes if "id" in ep]
    print(f"Downloading {len(ep_ids)} replays to {out_dir} with {workers} workers...")

    results = {"downloaded": 0, "skipped": 0, "failed": 0}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        future_map = {pool.submit(download_one, ep_id, out_dir): ep_id for ep_id in ep_ids}
        for idx, fut in enumerate(concurrent.futures.as_completed(future_map), 1):
            ep_id = future_map[fut]
            try:
                _, status = fut.result()
                if status in results:
                    results[status] += 1
                else:
                    results["failed"] += 1
                    print(f"Episode {ep_id} failed: {status}")
            except Exception as e:
                print(f"Episode {ep_id} exception: {e}")
                results["failed"] += 1
            if idx % 10 == 0 or idx == len(ep_ids):
                print(f"[{idx}/{len(ep_ids)}] Status: {results}")

    print(f"Submission {submission_id} replay download complete: {results}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--submissions", nargs="+", type=int, default=[55171237, 55171235])
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()

    for sub_id in args.submissions:
        download_submission_replays(sub_id, workers=args.workers)


if __name__ == "__main__":
    main()
