#!/usr/bin/env python3
"""Real-time monitor for new v2.1 submission on Kaggle."""

import base64
import json
import ssl
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EPISODE_SERVICE = "https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodes"

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
            return json.loads(resp.read().decode()).get("episodes", [])
    except Exception as e:
        print(f"Error fetching metadata for sub {sub_id}: {e}")
        return []

def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/monitor_v2_1_live.py <NEW_SUBMISSION_ID>")
        return
    
    sub_id = int(sys.argv[1])
    print(f"Monitoring new submission #{sub_id} in real time...")
    
    seen_eps = set()
    while True:
        eps = fetch_episodes(sub_id)
        for ep in sorted(eps, key=lambda x: x['id']):
            ep_id = ep['id']
            if ep_id not in seen_eps:
                seen_eps.add(ep_id)
                ag = ep.get("agents", [])
                if len(ag) >= 2:
                    h_idx = 0 if ag[0].get("submissionId") == sub_id else 1
                    h, o = ag[h_idx], ag[1 - h_idx]
                    h_init = h.get("initialScore", 0) or 0
                    h_upd = h.get("updatedScore", 0) or 0
                    o_init = o.get("initialScore", 0) or 0
                    rew = h.get("reward")
                    res = "WIN " if rew == 1 else ("LOSS" if rew == -1 else "TIE ")
                    delta = h_upd - h_init
                    print(f"🔥 NEW MATCH -> Ep {ep_id} | {res} | Delta: {delta:+6.1f} | Hero: {h_init:5.1f} -> {h_upd:5.1f} | Opp Sub {o.get('submissionId')} (Elo {o_init:5.1f})")
        time.sleep(30)

if __name__ == "__main__":
    main()
