#!/usr/bin/env python3
"""Diagnose why the agent chose Pass over Attack when Tormenting Toss was available."""

import json
from pathlib import Path
from cg.api import to_observation_class
from ptcg_ai.model import NumpyPolicyModel
from ptcg_ai.features import encode_observation

model = NumpyPolicyModel("artifacts/v2_model/policy_weights.npz")

cases = [
    (90480044, 65, 1),
    (90484716, 37, 1),
    (90484716, 84, 1),
    (90486266, 110, 1),
    (90486266, 209, 1),
]

for ep_id, s_idx, hero_idx in cases:
    rp_file = Path(f"data/replays/55303334/episode-{ep_id}-replay.json")
    if not rp_file.exists():
        continue
    data = json.loads(rp_file.read_text(encoding="utf-8"))
    s = data["steps"][s_idx]
    raw_obs = s[hero_idx]["observation"]
    obs = to_observation_class(raw_obs)
    feat = encode_observation(obs, model.feature_version)
    logits, count_logits, val = model.predict(feat)
    
    print(f"\n=======================================================")
    print(f"DIAGNOSING Ep {ep_id} Step {s_idx}")
    print(f"Replay Action Taken: {s[hero_idx].get('action')}")
    print(f"Value Head Estimate: {val:+.4f}")
    print("Options & Logits:")
    for oi, opt in enumerate(obs.select.option):
        print(f"  Opt {oi}: Type={opt.type} (AttackId={opt.attackId}) -> Logit: {logits[oi]:+.4f}")
