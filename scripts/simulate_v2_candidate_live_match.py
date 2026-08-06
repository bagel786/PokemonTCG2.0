#!/usr/bin/env python3
"""Run exact candidate package code with debug logging on Episode 90486266."""

import json
import tarfile
import tempfile
import sys
from pathlib import Path

# Extract candidate tar into a temp directory to simulate exact Kaggle environment
temp_dir = tempfile.TemporaryDirectory()
extract_path = Path(temp_dir.name)

with tarfile.open("artifacts/submission_v2_candidate.tar.gz", "r:gz") as tar:
    tar.extractall(extract_path)

sys.path.insert(0, str(extract_path))
sys.path.insert(0, str(Path("vendor").resolve()))

import ptcg_ai.agent as ag_mod
from cg.api import to_observation_class

print("Loaded agent from extracted bundle:", ag_mod.__file__)

agent = ag_mod.CompetitionAgent(
    extract_path / "deck.csv",
    model_path=extract_path / "policy_weights.npz"
)

rp = json.loads(Path("data/replays/55303334/episode-90486266-replay.json").read_text(encoding="utf-8"))
steps = rp["steps"]
p0_deck = steps[1][0].get("action", [])
hero_idx = 0 if p0_deck[:5] == [7, 7, 7, 7, 7] else 1

print(f"\nSimulating Episode 90486266 (Hero Player {hero_idx}) with exact candidate bundle:")
searches_triggered = 0
agreed_with_replay = 0
disagreed_with_replay = 0

for s_idx, s in enumerate(steps):
    raw_obs = s[hero_idx].get("observation")
    if not raw_obs or not raw_obs.get("select"):
        continue
    
    rep_act = s[hero_idx].get("action")
    agent_act = agent(raw_obs)
    
    if agent_act == rep_act:
        agreed_with_replay += 1
    else:
        disagreed_with_replay += 1
        obs = to_observation_class(raw_obs)
        if obs.select.context == 0:
            print(f"Step {s_idx:3d} (Ctx 0) | Replay Act: {rep_act} | Agent Act: {agent_act}")

print(f"\nTotal Decisions: {agreed_with_replay + disagreed_with_replay}")
print(f"Agreed with Replay: {agreed_with_replay} ({agreed_with_replay / (agreed_with_replay + disagreed_with_replay) * 100:.1f}%)")
print(f"Disagreed with Replay: {disagreed_with_replay}")

temp_dir.cleanup()
