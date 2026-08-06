#!/usr/bin/env python3
"""Forensic analysis of the two recent losses: 90484716 and 90485483."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
replays_dir = ROOT / "data" / "replays" / "55303334"
replays_dir.mkdir(parents=True, exist_ok=True)
KAGGLE_EXE = sys.executable.replace("python.exe", "kaggle.exe")

losses = [90484716, 90485483]

for ep_id in losses:
    print(f"\n=======================================================")
    print(f"ANALYZING EPISODE {ep_id}")
    print(f"=======================================================")
    
    rp_file = replays_dir / f"episode-{ep_id}-replay.json"
    if not rp_file.exists():
        cmd = [KAGGLE_EXE, "competitions", "replay", str(ep_id), "-p", str(replays_dir)]
        subprocess.run(cmd, capture_output=True, text=True)
        alt = replays_dir / f"{ep_id}.json"
        if alt.exists():
            alt.rename(rp_file)
            
    if not rp_file.exists():
        print(f"Could not download {ep_id}")
        continue
        
    data = json.loads(rp_file.read_text(encoding="utf-8"))
    steps = data.get("steps", [])
    print(f"Total Steps: {len(steps)}")
    
    p0_deck = steps[1][0].get("action", [])
    hero_idx = 0 if p0_deck[:5] == [7, 7, 7, 7, 7] else 1
    opp_deck = steps[1][1 - hero_idx].get("action", [])
    print(f"Hero idx: {hero_idx}")
    print(f"Opponent deck ({len(opp_deck)} cards): {opp_deck}")
    
    from ptcg_ai.search import ArchetypeRegistry
    reg = ArchetypeRegistry()
    m_name, _, j = reg.match(set(opp_deck))
    print(f"Opponent matched archetype: {m_name} (Jaccard: {j:.3f})")
    
    # Check setup benching
    for s_idx, s in enumerate(steps[:10]):
        h_s = s[hero_idx]
        sel = h_s.get("observation", {}).get("select")
        if sel and sel.get("context") == 2:
            print(f"  Step {s_idx} Setup bench action: {h_s.get('action')} (options: {sel.get('option')})")
            
    # Check how game ended
    last_obs = steps[-1][hero_idx].get("observation", {}).get("current", {})
    if last_obs:
        players = last_obs.get("players", [])
        if len(players) >= 2:
            hp = players[last_obs.get("yourIndex", 0)]
            op = players[1 - last_obs.get("yourIndex", 0)]
            h_priz = len(hp.get("prizes", []))
            o_priz = len(op.get("prizes", []))
            print(f"  FINAL SCORE -> Hero Prizes Left: {h_priz} | Opp Prizes Left: {o_priz}")
            print(f"  Hero Active: {hp.get('active')} | Opp Active: {op.get('active')}")
            print(f"  Hero Bench Count: {len(hp.get('bench', []))} | Opp Bench Count: {len(op.get('bench', []))}")
            
    # Print key combat logs
    logs = []
    for s in steps:
        for l in s[hero_idx].get("observation", {}).get("logs", []):
            if l.get("type") in [15, 16]: # Attack, Damage
                logs.append(l)
    print(f"  Total Attacks in game: {len([l for l in logs if l.get('type') == 15])}")
    for l in logs[-15:]:
        print(f"    {l}")
