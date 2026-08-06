#!/usr/bin/env python3
"""Test the Anti-Pass Attack Guard across all live loss replays."""

import json
from pathlib import Path
from cg.api import to_observation_class, OptionType
from ptcg_ai.model import NumpyPolicyModel
from ptcg_ai.features import encode_observation
from ptcg_ai.safety import sanitize_selection

model = NumpyPolicyModel("artifacts/v2_model/policy_weights.npz")
replays = sorted(Path("data/replays/55303334").glob("*.json"))

prevented_blunders = 0

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
            logits, count_logits, _ = model.predict(feat)
            ranked = logits.argsort()[::-1].tolist()
            desired = 1
            action = sanitize_selection(obs.select, ranked, desired)
            
            chosen_opt_idx = action[0] if action else -1
            if 0 <= chosen_opt_idx < len(obs.select.option):
                chosen_opt = obs.select.option[chosen_opt_idx]
                # Check if chosen option is END while ATTACK was legally available
                if chosen_opt.type == OptionType.END or chosen_opt.type == 9:
                    atk_indices = [i for i, opt in enumerate(obs.select.option) if opt.type == OptionType.ATTACK or opt.type == 8]
                    if atk_indices:
                        prevented_blunders += 1
                        print(f"Replay {rp.stem} Step {s_idx:3d}: Anti-Pass Guard triggers! Model chose END ({chosen_opt_idx}), Guard forces ATTACK ({atk_indices[0]})")

print(f"\nTotal Anti-Pass Guard Interventions on Loss Replays: {prevented_blunders}")
