#!/usr/bin/env python3
"""Comprehensive analysis of all team submissions and overnight matches."""

import base64
import json
import ssl
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path
import kaggle

ROOT = Path(__file__).resolve().parents[1]
replays_dir = ROOT / "data" / "replays"
replays_dir.mkdir(parents=True, exist_ok=True)

kaggle.api.authenticate()
u = kaggle.api.config_values.get("username", "")
k = kaggle.api.config_values.get("key", "")
auth = "Basic " + base64.b64encode(f"{u}:{k}".encode()).decode()

# 1. Fetch all submissions for competition
subs = kaggle.api.competition_submissions("pokemon-tcg-ai")
print(f"=== FOUND {len(subs)} SUBMISSIONS ===")
for s in sorted(subs, key=lambda x: str(x.ref) if hasattr(x, 'ref') else str(x), reverse=True):
    print(f"Sub ID: {getattr(s, 'ref', s)} | Status: {getattr(s, 'status', 'N/A')} | Score: {getattr(s, 'publicScore', 'N/A')} | Date: {getattr(s, 'date', 'N/A')} | Description: {getattr(s, 'description', '')[:60]}")

# 2. Fetch episodes for recent active submissions (e.g. 55287852 and previous active)
EPISODE_SERVICE = "https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodes"

def get_episodes(sub_id):
    req = urllib.request.Request(
        EPISODE_SERVICE,
        data=json.dumps({"submissionId": sub_id}).encode(),
        headers={"Content-Type": "application/json", "Authorization": auth},
    )
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        return json.loads(resp.read().decode()).get("episodes", [])

for sub in sorted(subs, key=lambda x: x.get("id", 0), reverse=True)[:3]:
    sub_id = sub.get("id")
    eps = get_episodes(sub_id)
    if not eps:
        continue
    print(f"\n=======================================================")
    print(f"Submission {sub_id} ({sub.get('description', '')[:50]}): {len(eps)} games")
    print(f"=======================================================")
    
    wins, losses, ties = 0, 0, 0
    scores = []
    
    for ep in sorted(eps, key=lambda x: x['id']):
        ag = ep.get("agents", [])
        if len(ag) < 2:
            continue
        h_idx = 0 if ag[0].get("submissionId") == sub_id else 1
        h, o = ag[h_idx], ag[1 - h_idx]
        h_init = h.get("initialScore", 0) or 0
        h_upd = h.get("updatedScore", 0) or 0
        o_init = o.get("initialScore", 0) or 0
        delta = h_upd - h_init
        
        rew = h.get("reward")
        if rew == 1:
            wins += 1
            res = "WIN "
        elif rew == -1:
            losses += 1
            res = "LOSS"
        else:
            ties += 1
            res = "TIE "
            
        scores.append(h_upd)
        print(f"  Ep {ep['id']} | {res} | Delta: {delta:+6.1f} | Hero: {h_init:5.1f} -> {h_upd:5.1f} | Opp {o.get('submissionId')} ({o_init:5.1f})")
    
    wr = wins / len(eps) * 100 if eps else 0
    print(f"\nSummary for {sub_id}: Record {wins}W - {losses}L - {ties}T ({wr:.1f}%) | Final Score: {scores[-1] if scores else 'N/A'}")
