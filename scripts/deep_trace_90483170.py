#!/usr/bin/env python3
"""Deep forensic trace of Alakazam match 90483170."""

import json
from pathlib import Path
from ptcg_ai.search import ArchetypeRegistry
from ptcg_ai.archetypes import COMPETITIVE_ARCHETYPES

rp_path = Path("data/replays/55303334/episode-90483170-replay.json")
data = json.loads(rp_path.read_text(encoding="utf-8"))
steps = data.get("steps", [])

print(f"Total Steps in 90483170: {len(steps)}")
p0_deck = steps[1][0].get("action", [])
hero_idx = 0 if p0_deck[:5] == [7, 7, 7, 7, 7] else 1
opp_deck = steps[1][1 - hero_idx].get("action", [])

print(f"Hero Index: {hero_idx}")
print(f"Opponent Deck: {opp_deck}")

# Check revealed cards at each turn
reg = ArchetypeRegistry()
opp_revealed = set()

for s_idx, s in enumerate(steps):
    hero_step = s[hero_idx]
    opp_step = s[1 - hero_idx]
    
    # Track opp revealed cards
    obs = hero_step.get("observation", {})
    cur = obs.get("current", {})
    if cur:
        opp_p = cur.get("players", [])[1 - cur.get("yourIndex", 0)]
        if opp_p.get("active"):
            for c in opp_p.get("active", []):
                if isinstance(c, dict) and "id" in c:
                    opp_revealed.add(c["id"])
        for b in opp_p.get("bench", []):
            for c in b:
                if isinstance(c, dict) and "id" in c:
                    opp_revealed.add(c["id"])
        for d in opp_p.get("discard", []):
            if isinstance(d, dict) and "id" in d:
                opp_revealed.add(d["id"])
        for e in opp_p.get("energy", []):
            if isinstance(e, dict) and "id" in e:
                opp_revealed.add(e["id"])
                
    m_name, _, j = reg.match(opp_revealed)
    
    act = hero_step.get("action")
    sel = obs.get("select")
    if sel and act != [] and act is not None and sel.get("context") != 2:
        print(f"[Step {s_idx:3d}] Context {sel.get('context'):2d} | Opp Matched: {m_name:12s} (J={j:.3f}) | Act: {act}")

# Check logs
print("\n--- COMBAT & ATTACK EVENTS ---")
all_logs = []
for s in steps:
    for l in s[hero_idx].get("observation", {}).get("logs", []):
        if l not in all_logs:
            all_logs.append(l)
            if l.get("type") in [15, 16, 4, 12, 10]: # Attack, Damage, Knockout, Evolve, Supporter/Item
                print(f"  {l}")
