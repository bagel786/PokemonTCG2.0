#!/usr/bin/env python3
"""Inspect what options were available when agent chose END."""

import json
from pathlib import Path
from cg.api import to_observation_class, OptionType
from ptcg_ai.model import NumpyPolicyModel
from ptcg_ai.features import encode_observation
from ptcg_ai.view import option_source_card

model = NumpyPolicyModel("artifacts/v2_model/policy_weights.npz")
replays = sorted(Path("data/replays/55303334").glob("*.json"))

print("Auditing all END choices in live loss games:\n")

for rp in replays:
    data = json.loads(rp.read_text())
    hero_idx = 0 if data["steps"][1][0].get("action", [])[:5] == [7, 7, 7, 7, 7] else 1
    
    for s_idx, s in enumerate(data["steps"]):
        raw_obs = s[hero_idx].get("observation")
        if not raw_obs or not raw_obs.get("select"):
            continue
        obs = to_observation_class(raw_obs)
        if obs.select.context == 0:
            feat = encode_observation(obs, model.feature_version)
            logits, count_logits, val = model.predict(feat)
            
            # Find which option is END
            end_opts = [(i, opt) for i, opt in enumerate(obs.select.option) if opt.type == OptionType.END or opt.type == 9]
            atk_opts = [(i, opt) for i, opt in enumerate(obs.select.option) if opt.type == OptionType.ATTACK or opt.type == 8]
            abil_opts = [(i, opt) for i, opt in enumerate(obs.select.option) if opt.type == OptionType.ABILITY or opt.type == 6]
            play_opts = [(i, opt) for i, opt in enumerate(obs.select.option) if opt.type == OptionType.PLAY or opt.type == 4]
            evolve_opts = [(i, opt) for i, opt in enumerate(obs.select.option) if opt.type == OptionType.EVOLVE or opt.type == 5]
            
            # What was the chosen action in the live replay?
            live_action = s[hero_idx].get("action", [])
            live_opt = live_action[0] if live_action else -1
            
            # Did the live replay choose END when an attack or ability or play was available?
            if end_opts and (atk_opts or abil_opts or play_opts or evolve_opts):
                chosen_is_end = live_opt in [i for i, _ in end_opts]
                if chosen_is_end:
                    ranked = logits.argsort()[::-1].tolist()
                    print(f"Replay {rp.stem} Step {s_idx:3d}: LIVE AGENT CHOSE END ({live_opt})!")
                    print(f"   Available options: {len(obs.select.option)} total | Attacks: {len(atk_opts)} | Abilities: {len(abil_opts)} | Evolves: {len(evolve_opts)} | Plays: {len(play_opts)}")
                    print(f"   Model top 3 logits rank: {ranked[:3]}")
                    if atk_opts:
                        print(f"   ATTACK was option {atk_opts[0][0]} with logit {logits[atk_opts[0][0]]:.3f} vs END logit {logits[end_opts[0][0]]:.3f}")
                    if abil_opts:
                        print(f"   ABILITY was option {abil_opts[0][0]} with logit {logits[abil_opts[0][0]]:.3f} vs END logit {logits[end_opts[0][0]]:.3f}")
                    print()
