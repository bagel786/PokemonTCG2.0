#!/usr/bin/env python3
"""Trace why Step 37 took action [2] in Episode 90484716."""

import json
from pathlib import Path
from cg.api import to_observation_class
from ptcg_ai.model import NumpyPolicyModel, NeuralPolicy
from ptcg_ai.agent import CompetitionAgent
from ptcg_ai.heuristic import GrimmsnarlHeuristic
from ptcg_ai.safety import emergency_selection, sanitize_selection

rp = json.loads(Path("data/replays/55303334/episode-90484716-replay.json").read_text(encoding="utf-8"))
step_37 = rp["steps"][37]
raw_obs = step_37[1]["observation"]
obs = to_observation_class(raw_obs)

print("Step 37 select options:")
for i, o in enumerate(obs.select.option):
    print(f"  {i}: {o}")

# Test Heuristic
heur = GrimmsnarlHeuristic()
heur_act = heur.choose(obs)
print(f"Heuristic choice: {heur_act}")

# Test NeuralPolicy without search
model = NumpyPolicyModel("artifacts/v2_model/policy_weights.npz")
neural_no_search = NeuralPolicy("artifacts/v2_model/policy_weights.npz", heur, search_policy=None)
neural_act = neural_no_search.choose(obs)
print(f"Neural (No Search) choice: {neural_act}")

# Test Full CompetitionAgent
agent = CompetitionAgent("artifacts/submission_staging_master/deck.csv", model_path="artifacts/v2_model/policy_weights.npz")
agent_act = agent(raw_obs)
print(f"Full CompetitionAgent choice: {agent_act}")
