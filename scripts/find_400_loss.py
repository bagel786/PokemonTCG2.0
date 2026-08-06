#!/usr/bin/env python3
import base64
import json
import ssl
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EPISODE_SERVICE = "https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodes"
import kaggle

kaggle.api.authenticate()
u = kaggle.api.config_values.get("username", "")
k = kaggle.api.config_values.get("key", "")
auth = "Basic " + base64.b64encode(f"{u}:{k}".encode()).decode()

def fetch(sub_id):
    req = urllib.request.Request(
        EPISODE_SERVICE,
        data=json.dumps({"submissionId": sub_id}).encode(),
        headers={"Content-Type": "application/json", "Authorization": auth},
    )
    ctx = ssl._create_unverified_context()
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        return json.loads(resp.read().decode()).get("episodes", [])

subs = [55287852, 55283588, 55280582, 55280578, 55280574, 55278944]
for sub in subs:
    eps = fetch(sub)
    print(f"\n=== Sub {sub} ({len(eps)} episodes) ===")
    for ep in eps:
        ag = ep.get("agents", [])
        if len(ag) < 2:
            continue
        h_idx = 0 if ag[0].get("submissionId") == sub else 1
        h, o = ag[h_idx], ag[1 - h_idx]
        h_init = h.get("initialScore", 0) or 0
        h_upd = h.get("updatedScore", 0) or 0
        o_init = o.get("initialScore", 0) or 0
        o_upd = o.get("updatedScore", 0) or 0
        delta = h_upd - h_init
        if delta < -40 or o_init < 550:
            print(
                f"  Ep {ep['id']} | Delta: {delta:+.1f} | Hero: {h_init:.1f}->{h_upd:.1f} | "
                f"Opp Sub {o.get('submissionId')}: {o_init:.1f}->{o_upd:.1f}"
            )
