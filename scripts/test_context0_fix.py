#!/usr/bin/env python3
"""Test Context 0 desired count fix across all loss replays."""

import json
from pathlib import Path
from cg.api import to_observation_class
from ptcg_ai.model import NumpyPolicyModel
from ptcg_ai.features import encode_observation
from ptcg_ai.safety import sanitize_selection

m = NumpyPolicyModel("artifacts/v2_model/policy_weights.npz")
losses = [90480044, 90483170, 90484716, 90485483, 90486266]

for ep_id in losses:
    rp = json.loads(Path(f"data/replays/55303334/episode-{ep_id}-replay.json").read_text(encoding="utf-8"))
    steps = rp["steps"]
    p0_deck = steps[1][0].get("action", [])
    hero_idx = 0 if p0_deck[:5] == [7, 7, 7, 7, 7] else 1
    
    empty_actions = 0
    attack_choices = 0
    pass_choices = 0
    item_choices = 0
    
    for s in steps:
        raw_obs = s[hero_idx].get("observation")
        if not raw_obs or not raw_obs.get("select"):
            continue
        obs = to_observation_class(raw_obs)
        if obs.select.context == 0:
            feat = encode_observation(obs, m.feature_version)
            logits, count_logits, _ = m.predict(feat)
            
            # Old count logic
            min_c = int(obs.select.minCount)
            max_c = min(int(obs.select.maxCount), len(count_logits) - 1)
            old_des = min_c + int(count_logits[min_c : max_c + 1].argmax())
            
            # Fixed count logic: context 0 always picks 1 action
            fixed_des = 1
            
            ranked = logits.argsort()[::-1].tolist()
            old_act = sanitize_selection(obs.select, ranked, old_des)
            fixed_act = sanitize_selection(obs.select, ranked, fixed_des)
            
            if len(old_act) == 0:
                empty_actions += 1
                opt = obs.select.option[fixed_act[0]]
                if opt.type == 13: attack_choices += 1
                elif opt.type == 14: pass_choices += 1
                elif opt.type in [7, 9, 10]: item_choices += 1
                
    print(f"Episode {ep_id}: {empty_actions} Context 0 turns were skipped as empty [] by old count logic!")
    print(f"  Fixed logic converted those {empty_actions} empty turns into: {attack_choices} Attacks, {item_choices} Items/Abilities, {pass_choices} Explicit Passes")
