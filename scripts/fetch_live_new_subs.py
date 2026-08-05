#!/usr/bin/env python3
"""Fetch and diagnose live episodes for newly deployed submissions 55189658 and 55189662."""

import json
import os
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KAGGLE = "/Users/safiullahbaig/Library/Python/3.11/bin/kaggle"
EPISODE_SERVICE = "https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodes"


def auth_header() -> str:
    blob = json.loads((Path.home() / ".kaggle" / "kaggle.json").read_text())
    return blob["key"]


import ssl

def fetch_sub_episodes(sub_id: int):
    out_dir = ROOT / "data" / "replays" / str(sub_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"submissionId": sub_id}).encode()
    req = urllib.request.Request(
        EPISODE_SERVICE,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "PTCG-Live/1.0"},
    )
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, context=ctx) as resp:
        data = json.loads(resp.read().decode())
    
    episodes = data.get("result", {}).get("episodes", [])
    (out_dir / "episodes_metadata.json").write_text(json.dumps(episodes, indent=2))
    print(f"\nSub {sub_id}: Found {len(episodes)} total episodes on Kaggle.")

    for ep in episodes:
        ep_id = ep["id"]
        rp_path = out_dir / f"episode-{ep_id}-replay.json"
        if not rp_path.exists():
            print(f"Downloading replay for Episode {ep_id}...")
            cmd = [KAGGLE, "competitions", "replay", str(ep_id), "-p", str(out_dir)]
            res = subprocess.run(cmd, capture_output=True, text=True)
            # rename if needed
            downloaded = out_dir / f"{ep_id}.json"
            if downloaded.exists() and not rp_path.exists():
                downloaded.rename(rp_path)

    return episodes


if __name__ == "__main__":
    fetch_sub_episodes(55189658)
    fetch_sub_episodes(55189662)
