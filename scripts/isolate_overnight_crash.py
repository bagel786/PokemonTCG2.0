#!/usr/bin/env python3
"""Run exact overnight package code on Episode 90484716 steps to find the crash."""

import importlib.util
import json
import sys
from pathlib import Path

pkg_dir = Path("artifacts/overnight_pipeline_output/final_submission/kaggle_submission_package").resolve()
sys.path.insert(0, str(pkg_dir))
sys.path.insert(0, str(Path("vendor").resolve()))

import ptcg_ai.agent as ag_mod
from cg.api import to_observation_class

print("Loaded agent from:", ag_mod.__file__)

agent = ag_mod.CompetitionAgent(
    pkg_dir / "deck.csv",
    model_path=pkg_dir / "policy_weights.npz"
)

for ep_id in [90480044, 90484716, 90486266]:
    rp = json.loads(Path(f"data/replays/55303334/episode-{ep_id}-replay.json").read_text(encoding="utf-8"))
    steps = rp["steps"]
    p0_deck = steps[1][0].get("action", [])
    hero_idx = 0 if p0_deck[:5] == [7, 7, 7, 7, 7] else 1
    
    print(f"\n=======================================================")
    print(f"TESTING EPISODE {ep_id} (Hero {hero_idx})")
    print(f"=======================================================")
    
    for s_idx, s in enumerate(steps):
        raw_obs = s[hero_idx].get("observation")
        if not raw_obs or not raw_obs.get("select"):
            continue
        
        rep_act = s[hero_idx].get("action")
        
        # Test direct policy choose
        obs = to_observation_class(raw_obs)
        policy_act = None
        heur_act = None
        policy_err = None
        heur_err = None
        
        try:
            policy_act = agent.policy.choose(obs)
        except Exception as e:
            policy_err = str(e)
            
        try:
            heur_act = agent.fallback.choose(obs)
        except Exception as e:
            heur_err = str(e)
            
        agent_act = agent(raw_obs)
        
        if policy_err or heur_err or agent_act != rep_act:
            if policy_err or heur_err:
                print(f"Step {s_idx:3d} | CRASH: policy_err={policy_err}, heur_err={heur_err}")
            elif obs.select.context == 0:
                print(f"Step {s_idx:3d} | MISMATCH: Replay took {rep_act} | Agent code chose {agent_act} | Policy choice {policy_act} | Heur choice {heur_act}")
