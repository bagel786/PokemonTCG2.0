#!/usr/bin/env python3
"""Exhaustive forensic audit of all loss replays for 55303334."""

import json
import ssl
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUB_ID = 55303334
replays_dir = ROOT / "data" / "replays" / str(SUB_ID)
replays_dir.mkdir(parents=True, exist_ok=True)
KAGGLE_EXE = sys.executable.replace("python.exe", "kaggle.exe")

req = urllib.request.Request(
    "https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodes",
    data=json.dumps({"submissionId": SUB_ID}).encode(),
    headers={"Content-Type": "application/json", "User-Agent": "PTCG/1.0"}
)
ctx = ssl._create_unverified_context()
with urllib.request.urlopen(req, context=ctx) as resp:
    eps = json.loads(resp.read().decode()).get("episodes", [])

print(f"Total episodes: {len(eps)}")
losses = []
for ep in sorted(eps, key=lambda x: x['id']):
    ag = ep['agents']
    h_idx = 0 if ag[0]['submissionId'] == SUB_ID else 1
    h, o = ag[h_idx], ag[1 - h_idx]
    rew = h.get('reward')
    res = "WIN " if rew == 1 else ("LOSS" if rew == -1 else "TIE ")
    h_init = h.get('initialScore') or 0
    h_upd = h.get('updatedScore') or 0
    o_init = o.get('initialScore') or 0
    print(f"Ep {ep['id']} | {res} | {h_init:5.1f} -> {h_upd:5.1f} vs Sub {o.get('submissionId')} (Elo {o_init:5.1f})")
    if rew == -1:
        losses.append(ep['id'])

print(f"\nAudit of {len(losses)} losses: {losses}")

for ep_id in losses:
    rp_file = replays_dir / f"episode-{ep_id}-replay.json"
    if not rp_file.exists():
        subprocess.run([KAGGLE_EXE, "competitions", "replay", str(ep_id), "-p", str(replays_dir)], capture_output=True, text=True)
        alt = replays_dir / f"{ep_id}.json"
        if alt.exists(): alt.rename(rp_file)
    if not rp_file.exists():
        continue
    data = json.loads(rp_file.read_text(encoding="utf-8"))
    steps = data["steps"]
    p0_deck = steps[1][0].get("action", [])
    hero_idx = 0 if p0_deck[:5] == [7, 7, 7, 7, 7] else 1
    opp_deck = steps[1][1 - hero_idx].get("action", [])
    
    print(f"\n=======================================================")
    print(f"EPISODE {ep_id} (Hero is Player {hero_idx})")
    print(f"Total Steps: {len(steps)} | Opponent Deck Length: {len(opp_deck)}")
    
    # Check turns, attacks, passes, energy attachments, evolutions
    hero_attacks = 0
    opp_attacks = 0
    hero_passes = 0
    hero_items = 0
    hero_supporters = 0
    hero_abilities = 0
    
    for s_idx, s in enumerate(steps):
        h_s = s[hero_idx]
        o_s = s[1 - hero_idx]
        
        # Check hero actions
        sel = h_s.get("observation", {}).get("select")
        act = h_s.get("action")
        if sel and act != [] and act is not None:
            ctx = sel.get("context")
            opts = sel.get("option", [])
            if ctx == 0:
                for a_idx in act:
                    if a_idx < len(opts):
                        opt = opts[a_idx]
                        t = opt.get("type")
                        if t == 13: hero_attacks += 1
                        elif t == 14: hero_passes += 1
                        elif t == 7: hero_items += 1
                        elif t == 10: hero_abilities += 1
                        
        for l in h_s.get("observation", {}).get("logs", []):
            if l.get("type") == 15 and l.get("playerIndex") == 1 - hero_idx:
                opp_attacks += 1
                
    print(f"Stats: Hero Attacks={hero_attacks}, Opp Attacks={opp_attacks}, Hero Passes={hero_passes}, Hero Items={hero_items}, Hero Abilities={hero_abilities}")
