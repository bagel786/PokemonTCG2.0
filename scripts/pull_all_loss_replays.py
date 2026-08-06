#!/usr/bin/env python3
"""Pull and analyze all losses for submission 55287852 and simulate v2.1 search decisions."""

import base64
import json
import ssl
import subprocess
import sys
import urllib.request
from pathlib import Path
import kaggle

ROOT = Path(__file__).resolve().parents[1]
replays_dir = ROOT / "data" / "replays" / "55287852"
replays_dir.mkdir(parents=True, exist_ok=True)

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

# Filter for losses
losses = []
for ep in sorted(eps, key=lambda x: x['id']):
    ag = ep.get("agents", [])
    if len(ag) < 2:
        continue
    h_idx = 0 if ag[0].get("submissionId") == 55287852 else 1
    h, o = ag[h_idx], ag[1 - h_idx]
    if h.get("reward") == -1:
        losses.append({
            "id": ep["id"],
            "hero_seat": h_idx,
            "hero_init": h.get("initialScore", 0),
            "hero_upd": h.get("updatedScore", 0),
            "opp_sub": o.get("submissionId"),
            "opp_init": o.get("initialScore", 0),
        })

print(f"Found {len(losses)} losses out of {len(eps)} total games (Win Rate: {(len(eps)-len(losses))/len(eps)*100:.1f}%)")

# Download replay files if not present
for loss in losses:
    ep_id = loss["id"]
    rp_path = replays_dir / f"episode-{ep_id}-replay.json"
    if not rp_path.exists():
        cmd = [sys.executable, "-m", "kaggle", "competitions", "replay", str(ep_id), "-p", str(replays_dir)]
        subprocess.run(cmd, capture_output=True, text=True)
        alt = replays_dir / f"{ep_id}.json"
        if alt.exists():
            alt.rename(rp_path)

print(f"All {len(losses)} loss replays are ready.")
