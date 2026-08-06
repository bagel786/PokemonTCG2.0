#!/usr/bin/env python3
"""Fetch and analyze the Alakazam loss for submission 55303334."""

import json
import ssl
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUB_ID = 55303334
KAGGLE_EXE = sys.executable.replace("python.exe", "kaggle.exe")
EPISODE_SERVICE = "https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodes"

def fetch_episodes(sub_id: int):
    payload = json.dumps({"submissionId": sub_id}).encode()
    req = urllib.request.Request(
        EPISODE_SERVICE,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "PTCG-Live/1.0"}
    )
    ctx = ssl._create_unverified_context()
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        return json.loads(resp.read().decode()).get("episodes", [])

def download_replay(ep_id: int, out_dir: Path) -> Path | None:
    rp_path = out_dir / f"episode-{ep_id}-replay.json"
    alt_path = out_dir / f"{ep_id}.json"
    if rp_path.exists() and rp_path.stat().st_size > 0:
        return rp_path
    if alt_path.exists() and alt_path.stat().st_size > 0:
        return alt_path
    
    cmd = [KAGGLE_EXE, "competitions", "replay", str(ep_id), "-p", str(out_dir)]
    for attempt in range(3):
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if alt_path.exists() and alt_path.stat().st_size > 0:
            alt_path.rename(rp_path)
            return rp_path
        if rp_path.exists() and rp_path.stat().st_size > 0:
            return rp_path
        time.sleep(1.0)
    return None

print(f"Fetching all matches for submission {SUB_ID}...")
episodes = fetch_episodes(SUB_ID)
print(f"Total matches found: {len(episodes)}")

replays_dir = ROOT / "data" / "replays" / str(SUB_ID)
replays_dir.mkdir(parents=True, exist_ok=True)

for ep in sorted(episodes, key=lambda x: x['id']):
    ep_id = ep["id"]
    ag = ep.get("agents", [])
    if len(ag) < 2:
        continue
    h_idx = 0 if ag[0].get("submissionId") == SUB_ID else 1
    h, o = ag[h_idx], ag[1 - h_idx]
    rew = h.get("reward")
    res = "WIN " if rew == 1 else ("LOSS" if rew == -1 else "TIE ")
    h_init = h.get("initialScore", 0) or 0
    h_upd = h.get("updatedScore", 0) or 0
    o_init = o.get("initialScore", 0) or 0
    delta = h_upd - h_init if h_upd else 0
    print(f"Ep {ep_id} | {res} | Rating: {h_init:5.1f} -> {h_upd:5.1f} ({delta:+6.1f}) vs Sub {o.get('submissionId')} (Elo {o_init:5.1f})")

# Download and inspect the newest match
latest_ep = sorted(episodes, key=lambda x: x['id'])[-1]
latest_ep_id = latest_ep['id']
print(f"\nDownloading replay for newest Episode {latest_ep_id}...")
rp_file = download_replay(latest_ep_id, replays_dir)

if rp_file and rp_file.exists():
    data = json.loads(rp_file.read_text(encoding="utf-8"))
    steps = data.get("steps", [])
    print(f"Replay loaded: {len(steps)} steps.")
    
    p0_deck = steps[1][0].get("action", [])
    hero_idx = 0 if p0_deck[:5] == [7, 7, 7, 7, 7] else 1
    opp_deck = steps[1][1 - hero_idx].get("action", [])
    print(f"Hero idx: {hero_idx}")
    print(f"Opponent deck: {opp_deck}")
    
    # Check archetype matching
    from ptcg_ai.search import ArchetypeRegistry
    reg = ArchetypeRegistry()
    m_name, _, j = reg.match(set(opp_deck))
    print(f"Opponent matched archetype: {m_name} (Jaccard similarity: {j:.3f})")
