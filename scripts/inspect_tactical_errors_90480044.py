#!/usr/bin/env python3
"""Deep tactical analysis of hero decisions in Episode 90480044."""

import json
from pathlib import Path
from cg.api import to_observation_class

rp_path = Path("data/replays/55303334/episode-90480044-replay.json")
data = json.loads(rp_path.read_text(encoding="utf-8"))
steps = data.get("steps", [])

p0_deck = steps[1][0].get("action", [])
hero_idx = 0 if p0_deck[:5] == [7, 7, 7, 7, 7] else 1
opp_deck = steps[1][1 - hero_idx].get("action", [])

print(f"=== TACTICAL DECISION LOG FOR EPISODE 90480044 ===")
print(f"Hero Index: {hero_idx}")

for s_idx, s in enumerate(steps):
    hero_step = s[hero_idx]
    act = hero_step.get("action")
    obs_raw = hero_step.get("observation", {})
    sel = obs_raw.get("select")
    cur = obs_raw.get("current")
    
    if not sel or not cur:
        continue
        
    ctx = sel.get("context")
    options = sel.get("option", [])
    
    # We only care about branching decision points (more than 1 option or non-empty action)
    if len(options) > 1 and act is not None:
        players = cur.get("players", [])
        me = players[cur.get("yourIndex", 0)]
        opp = players[1 - cur.get("yourIndex", 0)]
        
        h_hand = len(me.get('hand') or [])
        h_priz = len(me.get('prizes') or [])
        o_hand = len(opp.get('hand') or [])
        o_priz = len(opp.get('prizes') or [])
        print(f"   My Board : Active={me.get('active')} | Bench={len(me.get('bench') or [])} | Hand={h_hand} | Prizes={h_priz}")
        print(f"   Opp Board: Active={opp.get('active')} | Bench={len(opp.get('bench') or [])} | Hand={o_hand} | Prizes={o_priz}")
        
        # Detail options
        if len(options) <= 8:
            for opt_i, opt in enumerate(options):
                is_chosen = opt_i in act if isinstance(act, list) else opt_i == act
                mark = "--> [CHOSEN]" if is_chosen else "    "
                print(f"   {mark} Option {opt_i}: {opt}")
        else:
            print(f"   Options summary: {len(options)} choices available")
