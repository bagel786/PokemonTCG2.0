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
print(f"Total episodes for 55287852: {len(eps)}")
for ep in eps:
    print("\n--------------------------------------------------")
    print(f"Episode {ep.get('id')} | State: {ep.get('state')} | Type: {ep.get('type')}")
    for idx, ag in enumerate(ep.get("agents", [])):
        print(f"  Agent {idx}: SubID {ag.get('submissionId')}, InitScore {ag.get('initialScore')}, UpdatedScore {ag.get('updatedScore')}, Reward {ag.get('reward')}, Status {ag.get('status')}")
