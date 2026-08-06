#!/usr/bin/env python3
"""Fetch and diagnose the latest games and the high-penalty loss for v2 (sub 55287852) and v1 (sub 55283588)."""

from __future__ import annotations

import base64
import json
import os
import shutil
import ssl
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EPISODE_SERVICE = "https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodes"
KAGGLE_EXE = sys.executable + " -m kaggle"


def auth_header() -> str:
    kaggle_json = Path.home() / ".kaggle" / "kaggle.json"
    if not kaggle_json.exists():
        return ""
    blob = json.loads(kaggle_json.read_text())
    if "access_token" in blob:
        return "Bearer " + blob["access_token"]
    pair = f"{blob['username']}:{blob['key']}".encode()
    return "Basic " + base64.b64encode(pair).decode()


def fetch_episodes(sub_id: int) -> list[dict]:
    payload = json.dumps({"submissionId": sub_id}).encode()
    headers = {"Content-Type": "application/json", "User-Agent": "PTCG-Live/1.0"}
    auth = auth_header()
    if auth:
        headers["Authorization"] = auth
    req = urllib.request.Request(EPISODE_SERVICE, data=payload, headers=headers)
    ctx = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        return data.get("episodes", []) or data.get("result", {}).get("episodes", [])
    except Exception as e:
        print(f"Error fetching metadata for sub {sub_id}: {e}")
        return []


def download_replay(ep_id: int, out_dir: Path) -> Path | None:
    out_dir.mkdir(parents=True, exist_ok=True)
    rp_path = out_dir / f"episode-{ep_id}-replay.json"
    alt_path = out_dir / f"{ep_id}.json"
    if rp_path.exists() and rp_path.stat().st_size > 0:
        return rp_path
    if alt_path.exists() and alt_path.stat().st_size > 0:
        return alt_path

    cmd = [sys.executable, "-m", "kaggle", "competitions", "replay", str(ep_id), "-p", str(out_dir)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if alt_path.exists() and alt_path.stat().st_size > 0:
        alt_path.rename(rp_path)
        return rp_path
    return None


def main():
    subs = [55287852, 55283588]
    print(f"Checking submissions: {subs}")

    for sub_id in subs:
        print(f"\n=======================================================")
        print(f"Fetching games for Submission {sub_id}...")
        print(f"=======================================================")
        episodes = fetch_episodes(sub_id)
        print(f"Total episodes returned: {len(episodes)}")

        if not episodes:
            continue

        out_dir = ROOT / "data" / "replays" / str(sub_id)
        out_dir.mkdir(parents=True, exist_ok=True)

        for ep in episodes:
            ep_id = ep.get("id")
            agents = ep.get("agents", [])
            if len(agents) < 2:
                continue

            hero_idx = 0 if agents[0].get("submissionId") == sub_id else 1
            opp_idx = 1 - hero_idx
            hero = agents[hero_idx]
            opp = agents[opp_idx]

            hero_init = hero.get("initialScore", 0)
            hero_upd = hero.get("updatedScore", 0)
            opp_init = opp.get("initialScore", 0)
            opp_upd = opp.get("updatedScore", 0)
            hero_delta = (hero_upd - hero_init) if (hero_upd is not None and hero_init is not None) else 0

            # Win/Loss
            reward = hero.get("reward", 0)
            status = hero.get("status", "")
            is_win = reward == 1 or hero_delta > 0
            res_str = "WIN" if is_win else "LOSS"

            print(
                f"Ep {ep_id} | {res_str} | Hero Elo: {hero_init:.1f} -> {hero_upd:.1f} (Delta: {hero_delta:+.1f}) | "
                f"Opp Sub {opp.get('submissionId')} (Elo: {opp_init:.1f} -> {opp_upd:.1f})"
            )

            # Download if loss or if large negative delta
            if not is_win or hero_delta < -50 or opp_init < 600:
                rp_file = download_replay(ep_id, out_dir)
                print(f"  --> Downloaded replay to {rp_file}")


if __name__ == "__main__":
    main()
