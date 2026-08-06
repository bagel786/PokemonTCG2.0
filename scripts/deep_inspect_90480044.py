#!/usr/bin/env python3
"""Deep forensic inspection of match 90480044."""

import json
from pathlib import Path

rp_path = Path("data/replays/55303334/episode-90480044-replay.json")
data = json.loads(rp_path.read_text(encoding="utf-8"))
steps = data.get("steps", [])

print(f"Total Steps: {len(steps)}")
p0_deck = steps[1][0].get("action", [])
hero_idx = 0 if p0_deck[:5] == [7, 7, 7, 7, 7] else 1
opp_deck = steps[1][1 - hero_idx].get("action", [])
print(f"Hero Index: {hero_idx}")
print(f"Opponent Deck: {opp_deck}")

# Check what deck opponent is playing
from ptcg_ai.search import ArchetypeRegistry
reg = ArchetypeRegistry()
m_name, _, j = reg.match(set(opp_deck))
print(f"Opponent Matched Archetype: {m_name} (Jaccard: {j:.3f})")

print("\n--- STEP BY STEP EXECUTION ---")
for s_idx, s in enumerate(steps):
    h_s = s[hero_idx]
    o_s = s[1 - hero_idx]
    h_act = h_s.get("action")
    h_obs = h_s.get("observation", {})
    sel = h_obs.get("select")
    logs = h_obs.get("logs", [])
    
    if sel:
        ctx = sel.get("context")
        opt_len = len(sel.get("option", []))
        if ctx == 2:
            print(f"[Step {s_idx:3d}] SETUP_BENCH -> Options: {opt_len} | Action Taken: {h_act}")
        elif h_act != [] and h_act is not None:
            print(f"[Step {s_idx:3d}] Context {ctx:2d} | Options: {opt_len:2d} | Action Taken: {h_act}")

# Check final state
last_obs = steps[-1][hero_idx].get("observation", {}).get("current", {})
if last_obs:
    players = last_obs.get("players", [])
    if len(players) >= 2:
        hp = players[last_obs.get("yourIndex", 0)]
        op = players[1 - last_obs.get("yourIndex", 0)]
        print("\n--- FINAL BOARD STATE ---")
        print(f"Hero: Prizes Left {len(hp.get('prizes', []))} | Active: {hp.get('active', {}).get('cardId')} (HP {hp.get('active', {}).get('hp')}, Energy {hp.get('active', {}).get('energy')}) | Bench: {len(hp.get('bench', []))}")
        print(f"Opp:  Prizes Left {len(op.get('prizes', []))} | Active: {op.get('active', {}).get('cardId')} (HP {op.get('active', {}).get('hp')}, Energy {op.get('active', {}).get('energy')}) | Bench: {len(op.get('bench', []))}")
        print(f"Hero Discard: {hp.get('discard', [])}")
        print(f"Opp Discard:  {op.get('discard', [])}")

# Print game logs
all_logs = []
for s in steps:
    logs = s[hero_idx].get("observation", {}).get("logs", [])
    if logs:
        for l in logs:
            if l not in all_logs:
                all_logs.append(l)

print(f"\n--- GAME LOGS ({len(all_logs)} events) ---")
for l in all_logs[-30:]:
    print(f"  {l}")
