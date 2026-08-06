#!/usr/bin/env python3
"""Trace exact runtime exceptions in master_v1 vs v2.2 packages."""

import json
import tarfile
import tempfile
import sys
from pathlib import Path

def trace_tarball(tar_name):
    tar_path = Path("artifacts") / tar_name
    print(f"\n========================================================")
    print(f"TRACING RUNTIME CRASHES IN: {tar_name}")
    print(f"========================================================")
    
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        with tarfile.open(tar_path, "r:gz") as tar:
            tar.extractall(stage)
            
        sys.path.insert(0, str(stage))
        sys.path.insert(0, str(Path("vendor").resolve()))
        
        # Clean import
        for mod in list(sys.modules.keys()):
            if mod.startswith("ptcg_ai"):
                del sys.modules[mod]
                
        import ptcg_ai.agent as ag_mod
        agent = ag_mod.CompetitionAgent(stage / "deck.csv", model_path=stage / "policy_weights.npz")
        
        replays = sorted(Path("data/replays/55303334").glob("*.json"))
        exceptions_caught = 0
        
        for rp in replays:
            data = json.loads(rp.read_text())
            hero_idx = 0 if data["steps"][1][0].get("action", [])[:5] == [7, 7, 7, 7, 7] else 1
            for s_idx, s in enumerate(data["steps"]):
                raw_obs = s[hero_idx].get("observation")
                if not raw_obs:
                    continue
                # Test raw call as Kaggle does
                try:
                    # Let's inspect if policy.choose threw
                    if raw_obs.get("select") is not None:
                        obs = ag_mod.to_observation_class(raw_obs)
                        try:
                            agent.policy.choose(obs)
                        except Exception as e:
                            exceptions_caught += 1
                            print(f"  [CRASH] {rp.stem} Step {s_idx:3d}: policy.choose crashed with: {type(e).__name__}: {e}")
                except Exception as e:
                    exceptions_caught += 1
                    print(f"  [CRASH] {rp.stem} Step {s_idx:3d}: to_observation_class crashed with: {type(e).__name__}: {e}")
                    
        print(f"Total Policy Runtime Crashes in {tar_name}: {exceptions_caught}")

trace_tarball("submission_master_v1.tar.gz")
trace_tarball("submission_v2_2.tar.gz")
