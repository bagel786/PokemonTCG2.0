#!/usr/bin/env python3
"""Verify v2.1 execution on all 21 loss replays."""

import json
from pathlib import Path
from cg.api import to_observation_class
from ptcg_ai.agent import CompetitionAgent

ROOT = Path(__file__).resolve().parents[1]
replays_dir = ROOT / "data" / "replays" / "55287852"

# Initialize v2.1 agent
v2_1_agent = CompetitionAgent(
    deck_path=ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv",
    model_path=ROOT / "artifacts" / "v2_model" / "policy_weights.npz"
)

# Load metadata
from scripts.deep_overnight_loss_bucket_analysis import loss_details

print(f"Analyzing all {len(loss_details)} loss episodes...")

fixed_setup_count = 0
tactical_divergences_total = 0

for item in loss_details:
    ep_id = item["ep_id"]
    rp_path = replays_dir / f"episode-{ep_id}-replay.json"
    if not rp_path.exists():
        continue
    data = json.loads(rp_path.read_text(encoding="utf-8"))
    steps = data.get("steps", [])
    if len(steps) < 2:
        continue
    
    # Identify hero index
    p0_deck = steps[1][0].get("action", [])
    hero_idx = 0 if p0_deck[:5] == [7, 7, 7, 7, 7] else 1
    
    setup_fixed_in_ep = False
    ep_divergences = 0
    
    for s_idx, s in enumerate(steps):
        hero_step = s[hero_idx]
        act_taken = hero_step.get("action")
        obs_raw = hero_step.get("observation", {})
        select_dict = obs_raw.get("select")
        
        if select_dict is not None:
            if select_dict.get("context") == 2 and select_dict.get("maxCount", 0) > 0 and act_taken == []:
                # Test v2.1
                obs_obj = to_observation_class(obs_raw)
                v2_1_act = v2_1_agent.policy.choose(obs_obj)
                if len(v2_1_act) > 0:
                    setup_fixed_in_ep = True
                    
            try:
                obs_obj = to_observation_class(obs_raw)
                v2_1_act = v2_1_agent.policy.choose(obs_obj)
                if v2_1_act != act_taken:
                    ep_divergences += 1
            except Exception:
                pass
                
    if setup_fixed_in_ep:
        fixed_setup_count += 1
    tactical_divergences_total += ep_divergences
    
    print(f"Ep {ep_id:8d} | Opp {item['opp_elo']:5.1f} ({item['archetype']:12s}) | Bucket: {item['bucket']:42s} | Fixed Setup: {str(setup_fixed_in_ep):5s} | Divergences: {ep_divergences:3d}")

print(f"\n=======================================================")
print(f"Total Loss Episodes with Setup Bench Blunders Fixed by v2.1: {fixed_setup_count} / 11")
print(f"Total Tactical Divergences across all 21 losses: {tactical_divergences_total}")
print(f"=======================================================")
