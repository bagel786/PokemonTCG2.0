#!/usr/bin/env python3
"""Audit search policy overrides across all 13 live matches."""

import json
from pathlib import Path
from cg.api import to_observation_class
from ptcg_ai.model import NumpyPolicyModel
from ptcg_ai.search import OnePlySearchPolicy, ArchetypeRegistry
from ptcg_ai.safety import sanitize_selection
from ptcg_ai.features import encode_observation

model = NumpyPolicyModel("artifacts/v2_model/policy_weights.npz")
deck = [int(x) for x in Path("artifacts/submission_staging_master/deck.csv").read_text().splitlines() if x.strip()]
search = OnePlySearchPolicy(model, deck, ArchetypeRegistry(), ambiguity_margin=0.35)

replays_dir = Path("data/replays/55303334")
for rp_path in sorted(replays_dir.glob("*.json")):
    data = json.loads(rp_path.read_text(encoding="utf-8"))
    steps = data["steps"]
    p0_deck = steps[1][0].get("action", [])
    hero_idx = 0 if p0_deck[:5] == [7, 7, 7, 7, 7] else 1
    
    ep_id = rp_path.stem.split("-")[1] if "-" in rp_path.stem else rp_path.stem
    
    total_searches = 0
    overrides = 0
    
    for s_idx, s in enumerate(steps):
        raw_obs = s[hero_idx].get("observation")
        if not raw_obs or not raw_obs.get("select"):
            continue
        obs = to_observation_class(raw_obs)
        if obs.select.context == 0 or obs.select.context == 7: # Main or Gust
            feat = encode_observation(obs, model.feature_version)
            logits, count_logits, val = model.predict(feat)
            
            if len(logits) > 1 and search.should_search(logits, count_logits, obs.select):
                total_searches += 1
                ranked = logits.argsort()[::-1].tolist()
                desired = 1
                greedy = sanitize_selection(obs.select, ranked, desired)
                
                # Check opponent match
                from ptcg_ai.agent import _public_card_ids
                opp_ids = _public_card_ids(obs)
                _name, opp_deck, j = search.registry.match(opp_ids)
                if opp_deck and j >= search.jaccard_threshold:
                    candidates = [greedy]
                    if len(ranked) >= 2:
                        c2 = sanitize_selection(obs.select, [ranked[1]] + [r for r in ranked if r != ranked[1]], desired)
                        if c2 != greedy: candidates.append(c2)
                    
                    search_act = search.evaluate_candidates(obs, candidates, opp_deck)
                    if search_act is not None and search_act != greedy:
                        overrides += 1
                        print(f"Ep {ep_id} Step {s_idx} | SEARCH OVERRODE GREEDY: Greedy was {greedy}, Search chose {search_act} (Opp: {_name})")
                        
    print(f"Episode {ep_id}: Total Searches Triggered = {total_searches}, Overrides = {overrides}")
