#!/usr/bin/env python3
"""Test surgical promotion invariant on all replays."""

import json
from pathlib import Path
from cg.api import to_observation_class, SelectContext
from ptcg_ai.view import option_source_card

replays_dir = Path("data/replays/55303334")
promotions_tested = 0
grimmsnarl_promoted = 0

for rp_path in sorted(replays_dir.glob("*.json")):
    data = json.loads(rp_path.read_text(encoding="utf-8"))
    steps = data["steps"]
    p0_deck = steps[1][0].get("action", [])
    hero_idx = 0 if p0_deck[:5] == [7, 7, 7, 7, 7] else 1
    
    for s_idx, s in enumerate(steps):
        raw_obs = s[hero_idx].get("observation")
        if not raw_obs or not raw_obs.get("select"):
            continue
        obs = to_observation_class(raw_obs)
        ctx = obs.select.context
        if ctx == 4 or ctx == SelectContext.TO_ACTIVE or str(ctx).endswith("TO_ACTIVE"):
            promotions_tested += 1
            for opt_idx, opt in enumerate(obs.select.option):
                c = option_source_card(obs, opt)
                if c is not None and getattr(c, "id", None) == 648:
                    grimmsnarl_promoted += 1
                    print(f"Replay {rp_path.name} Step {s_idx:3d} (Context 4): Found Grimmsnarl ex at Option {opt_idx} -> Prioritized!")

print(f"\nTotal Promotions in Matches: {promotions_tested}")
print(f"Grimmsnarl ex Promotions Prioritized: {grimmsnarl_promoted}")
