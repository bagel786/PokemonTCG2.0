#!/usr/bin/env python3
"""Fetch all live matches from Kaggle for active submissions and perform in-depth loss analysis."""

import base64
import json
import ssl
import sys
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

def fetch_episode_metadata(sub_id: int) -> list[dict]:
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
        return data.get("episodes", [])
    except Exception as e:
        print(f"Error fetching metadata for sub {sub_id}: {e}")
        return []

# Scan for our submission IDs around 55278000 to 55288000
candidate_ids = [55287852, 55283588, 55278944, 55278940, 55275044, 55259050, 55209876, 55134427]

print("=== CHECKING SUBMISSIONS ===")
for sub_id in candidate_ids:
    eps = fetch_episode_metadata(sub_id)
    if eps:
        # Check latest episode
        latest_ep = sorted(eps, key=lambda x: x['id'])[-1]
        agents = latest_ep.get("agents", [])
        h_idx = 0 if agents[0].get("submissionId") == sub_id else 1
        h_upd = agents[h_idx].get("updatedScore", 0) or 0
        h_init = agents[h_idx].get("initialScore", 0) or 0
        
        # Calculate overall record
        wins, losses, ties = 0, 0, 0
        for ep in eps:
            ag = ep.get("agents", [])
            if len(ag) >= 2:
                idx = 0 if ag[0].get("submissionId") == sub_id else 1
                rew = ag[idx].get("reward")
                if rew == 1:
                    wins += 1
                elif rew == -1:
                    losses += 1
                else:
                    ties += 1
        wr = wins / len(eps) * 100 if eps else 0
        print(f"Sub {sub_id}: {len(eps)} games | Record {wins}W - {losses}L - {ties}T ({wr:.1f}%) | Latest Score: {h_upd:5.1f} | Latest Ep: {latest_ep['id']}")
