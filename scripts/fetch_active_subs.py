#!/usr/bin/env python3
"""Fetch all episodes and replays for active submissions (55189658 and 55189662), and analyze every game."""

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
    kaggle_json = Path.home() / ".kaggle" / "kaggle.json"
    if kaggle_json.exists():
        blob = json.loads(kaggle_json.read_text())
        if "access_token" in blob:
            return "Bearer " + blob["access_token"]
        u = blob["username"]
        k = blob["key"]
        return "Basic " + base64.b64encode(f"{u}:{k}".encode()).decode()
    import kaggle
    token = kaggle.api.config_values.get("token")
    if token:
        return "Bearer " + token
    u = kaggle.api.config_values.get("username", "")
    k = kaggle.api.config_values.get("key", "")
    return "Basic " + base64.b64encode(f"{u}:{k}".encode()).decode()


def fetch_episodes(submission_id: int) -> list[dict]:
    ctx = ssl._create_unverified_context()
    req = urllib.request.Request(
        EPISODE_SERVICE,
        data=json.dumps({"submissionId": submission_id}).encode(),
        headers={"Content-Type": "application/json", "Authorization": auth_header()},
    )
    with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
        data = json.load(resp)
        return data.get("result", {}).get("episodes", []) or data.get("episodes", [])


def download_one(ep_id: int, output_dir: Path) -> tuple[int, str]:
    target_file = output_dir / f"episode-{ep_id}-replay.json"
    alt_file = output_dir / f"{ep_id}.json"
    if (target_file.exists() and target_file.stat().st_size > 0) or (alt_file.exists() and alt_file.stat().st_size > 0):
        return ep_id, "skipped"

    command = [KAGGLE, "competitions", "replay", str(ep_id), "-p", str(output_dir)]
    for attempt in range(3):
        res = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if alt_file.exists() and alt_file.stat().st_size > 0:
            alt_file.rename(target_file)
            return ep_id, "downloaded"
        if target_file.exists() and target_file.stat().st_size > 0:
            return ep_id, "downloaded"
        time.sleep(1.0 * (attempt + 1))
    return ep_id, f"failed: {res.stderr.strip()}"


def sync_submission(submission_id: int, workers: int = 8):
    out_dir = ROOT / "data" / "replays" / str(submission_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Fetching episodes for {submission_id}...")
    episodes = fetch_episodes(submission_id)
    (out_dir / "episodes_metadata.json").write_text(json.dumps(episodes, indent=2))
    print(f"Found {len(episodes)} episodes.")

    ep_ids = [ep["id"] for ep in episodes if "id" in ep]
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        future_map = {pool.submit(download_one, ep_id, out_dir): ep_id for ep_id in ep_ids}
        for fut in concurrent.futures.as_completed(future_map):
            pass
    print(f"Finished downloading replays for {submission_id}.")
    return episodes


if __name__ == "__main__":
    for s in [55189658, 55189662]:
        sync_submission(s)
