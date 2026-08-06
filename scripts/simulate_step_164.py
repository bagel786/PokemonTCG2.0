#!/usr/bin/env python3
"""Simulate Step 164 of 90485483 to see model logits and search evaluation."""

import json
from pathlib import Path
from cg.api import to_observation_class
from ptcg_ai.model import NumpyPolicyModel
from ptcg_ai.features import encode_observation
from ptcg_ai.search import OnePlySearchPolicy, ArchetypeRegistry

rp = json.loads(Path("data/replays/55303334/episode-90485483-replay.json").read_text(encoding="utf-8"))
step_164 = rp["steps"][164]
hero_step = step_164[0]
raw_obs = hero_step["observation"]

# Load model
model = NumpyPolicyModel("artifacts/v2_model/policy_weights.npz")
obs = to_observation_class(raw_obs)
feat = encode_observation(obs, model.feature_version)
logits, count_logits, val = model.predict(feat)

print("Step 164 Raw Options:")
for i, opt in enumerate(obs.select.option):
    print(f"  Opt {i}: {opt} | Logit: {logits[i]:.4f}")

# Check candidates
cand_indices = [int(i) for i in logits.argsort()[::-1][:3]]
candidates = [[idx] for idx in cand_indices]
print(f"\nTop 3 Candidates: {candidates}")

reg = ArchetypeRegistry()
opp_deck = rp["steps"][1][1]["action"]
search_policy = OnePlySearchPolicy(model, rp["steps"][1][0]["action"], reg)

print("\nRunning evaluate_candidates on Step 164:")
best_act = search_policy.evaluate_candidates(obs, candidates, opp_deck)
print(f"Best Action Chosen by Search: {best_act}")
