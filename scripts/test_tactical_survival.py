#!/usr/bin/env python3
"""Evaluate survival & tanking strategy across all 13 matches."""

import json
from pathlib import Path

replays_dir = Path("data/replays/55303334")
print(f"Auditing all {len(list(replays_dir.glob('*.json')))} replays for Grimmsnarl Active Tanking & Prize Trading:\n")

for rp_path in sorted(replays_dir.glob("*.json")):
    data = json.loads(rp_path.read_text(encoding="utf-8"))
    steps = data["steps"]
    p0_deck = steps[1][0].get("action", [])
    hero_idx = 0 if p0_deck[:5] == [7, 7, 7, 7, 7] else 1
    
    ep_id = rp_path.stem.split("-")[1] if "-" in rp_path.stem else rp_path.stem
    
    # Check Active Pokemon identity throughout game
    active_types = []
    for s in steps:
        raw_obs = s[hero_idx].get("observation")
        if raw_obs and raw_obs.get("current"):
            curr = raw_obs["current"]
            p = curr["players"][curr.get("yourIndex", hero_idx)]
            act = p.get("active", [])
            if act and isinstance(act, list) and act[0] is not None:
                active_types.append(act[0].get("id"))
                
    from collections import Counter
    c = Counter(active_types)
    # 648 = Grimmsnarl ex, 112 = Munkidori, 104 = Morpeko, 646 = Impidimp, 647 = Morgrem
    name_map = {648: "Grimmsnarl ex (320HP)", 112: "Munkidori (110HP)", 104: "Morpeko (70HP)", 646: "Impidimp (70HP)", 647: "Morgrem (90HP)", 860: "Fezandipiti"}
    distribution = {name_map.get(k, f"Card {k}"): v for k, v in c.most_common()}
    print(f"Episode {ep_id} (Outcome: {steps[-1][0].get('reward', 0) if hero_idx==0 else steps[-1][1].get('reward', 0)}):")
    print(f"  Active Spot Time: {distribution}\n")
