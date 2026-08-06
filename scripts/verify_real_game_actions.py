#!/usr/bin/env python3
"""Verify real game actions using correct cg.api enum mappings."""

import json
from pathlib import Path
from cg.api import OptionType

replays = sorted(Path("data/replays/55303334").glob("*.json"))

print(f"Auditing all {len(replays)} replays with EXACT OptionType Enums:")
print(f"  OptionType.ATTACK = {OptionType.ATTACK.value} ({OptionType.ATTACK.name})")
print(f"  OptionType.END    = {OptionType.END.value} ({OptionType.END.name})")
print(f"  OptionType.ABILITY= {OptionType.ABILITY.value} ({OptionType.ABILITY.name})")
print(f"  OptionType.EVOLVE = {OptionType.EVOLVE.value} ({OptionType.EVOLVE.name})\n")

for rp in replays:
    data = json.loads(rp.read_text())
    hero_idx = 0 if data["steps"][1][0].get("action", [])[:5] == [7, 7, 7, 7, 7] else 1
    
    attacks_executed = 0
    abilities_executed = 0
    evolves_executed = 0
    raw_passes_without_attack = 0
    
    for s_idx, s in enumerate(data["steps"]):
        raw_obs = s[hero_idx].get("observation")
        raw_act = s[hero_idx].get("action")
        if not raw_obs or not raw_obs.get("select") or not raw_act:
            continue
        
        ctx = raw_obs["select"].get("context")
        if ctx == 0: # Main turn decision
            chosen_idx = raw_act[0]
            opts = raw_obs["select"].get("option", [])
            if 0 <= chosen_idx < len(opts):
                chosen_type = opts[chosen_idx].get("type")
                if chosen_type == OptionType.ATTACK.value or chosen_type == OptionType.ATTACK:
                    attacks_executed += 1
                elif chosen_type == OptionType.ABILITY.value or chosen_type == OptionType.ABILITY:
                    abilities_executed += 1
                elif chosen_type == OptionType.EVOLVE.value or chosen_type == OptionType.EVOLVE:
                    evolves_executed += 1
                elif chosen_type == OptionType.END.value or chosen_type == OptionType.END:
                    # Check if an attack was available at the same moment
                    atk_opts = [i for i, o in enumerate(opts) if o.get("type") == OptionType.ATTACK.value]
                    if atk_opts:
                        raw_passes_without_attack += 1
                        print(f"  Replay {rp.stem} Step {s_idx:3d}: Chose END while Attack was in options!")

    print(f"Episode {rp.stem}: Attacks={attacks_executed}, Abilities={abilities_executed}, Evolves={evolves_executed}, Passes-With-Attack={raw_passes_without_attack}")
