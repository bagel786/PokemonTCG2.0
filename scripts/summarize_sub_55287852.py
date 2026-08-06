#!/usr/bin/env python3
import base64
import json
import ssl
import sys
import urllib.request
from pathlib import Path
import kaggle

kaggle.api.authenticate()
u = kaggle.api.config_values.get("username", "")
k = kaggle.api.config_values.get("key", "")
auth = "Basic " + base64.b64encode(f"{u}:{k}".encode()).decode()

EPISODE_SERVICE = "https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodes"
req = urllib.request.Request(
    EPISODE_SERVICE,
    data=json.dumps({"submissionId": 55287852}).encode(),
    headers={"Content-Type": "application/json", "Authorization": auth},
)
ctx = ssl._create_unverified_context()
with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
    data = json.loads(resp.read().decode())

eps = data.get("episodes", [])
print(f"=== SUBMISSION 55287852 RECORD ({len(eps)} games) ===")
for ep in sorted(eps, key=lambda x: x['id']):
    ag = ep.get("agents", [])
    if len(ag) < 2:
        continue
    h_idx = 0 if ag[0].get("submissionId") == 55287852 else 1
    h, o = ag[h_idx], ag[1 - h_idx]
    h_init = h.get("initialScore", 0) or 0
    h_upd = h.get("updatedScore", 0) or 0
    o_init = o.get("initialScore", 0) or 0
    o_upd = o.get("updatedScore", 0) or 0
    delta = h_upd - h_init
    outcome = "WIN " if h.get("reward") == 1 else "LOSS" if h.get("reward") == -1 else "TIE "
    print(f"Ep {ep['id']} | {outcome} | Delta: {delta:+6.1f} | Hero: {h_init:5.1f} -> {h_upd:5.1f} | Opp Sub {o.get('submissionId')}: {o_init:5.1f}")
