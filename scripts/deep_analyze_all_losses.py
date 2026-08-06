#!/usr/bin/env python3
"""Detailed forensic breakdown of all 7 losses with v2.1 simulation."""

import json
from pathlib import Path
from cg.api import to_observation_class

ROOT = Path(__file__).resolve().parents[1]
replays_dir = ROOT / "data" / "replays" / "55287852"

# Load card names
card_names = {
    0: "Basic Fire Energy", 1: "Basic Grass Energy", 2: "Basic Water Energy", 3: "Basic Psychic Energy",
    4: "Basic Lightning Energy", 5: "Basic Fighting Energy", 7: "Basic Darkness Energy",
    96: "Teal Mask Ogerpon ex", 104: "Spikemuth Gym", 112: "Marnie",
    646: "Marnie's Impidimp", 647: "Marnie's Morgrem", 648: "Marnie's Grimmsnarl ex",
    649: "Cynthia's Gible", 650: "Cynthia's Gabite", 651: "Cynthia's Garchomp ex",
    677: "Riolu", 678: "Mega Lucario ex", 860: "Snorunt", 1079: "Rare Candy",
    1086: "Marnie's Morpeko", 1097: "Professor's Research", 1122: "Pokégear 3.0",
    1152: "Poké Pad", 1182: "Boss's Orders", 1219: "Nest Ball", 1227: "Ultra Ball",
    1259: "Boss's Orders",
}
csv_path = ROOT / "freshstart" / "data" / "EN_Card_Data.csv"
if csv_path.exists():
    for line in csv_path.read_text(encoding="utf-8").splitlines():
        parts = line.split(",")
        if len(parts) >= 2:
            try:
                cid = int(parts[0])
                cname = parts[1]
                card_names[cid] = cname
            except Exception:
                pass

def cname(cid):
    return card_names.get(cid, f"Card#{cid}")

loss_ep_ids = [90341059, 90342558, 90343300, 90346282, 90349388, 90350033, 90350768]

# Initialize v2.1 agent to evaluate divergence
from ptcg_ai.agent import CompetitionAgent
v2_1_agent = CompetitionAgent(
    deck_path=ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv",
    model_path=ROOT / "artifacts" / "v2_model" / "policy_weights.npz"
)
print("v2.1 Agent initialized with 1-ply search:", v2_1_agent.policy.search_policy is not None)

for ep_id in loss_ep_ids:
    rp_path = replays_dir / f"episode-{ep_id}-replay.json"
    data = json.loads(rp_path.read_text(encoding="utf-8"))
    steps = data.get("steps", [])
    
    # Identify hero index
    # We check step 1 action length 60
    hero_idx = 1
    if len(steps) > 1:
        if steps[1][0].get("action") and steps[1][0]["action"][:10] == [7, 7, 7, 7, 7, 7, 7, 7, 7, 7]:
            hero_idx = 0
        elif steps[1][1].get("action") and steps[1][1]["action"][:10] == [7, 7, 7, 7, 7, 7, 7, 7, 7, 7]:
            hero_idx = 1
    opp_idx = 1 - hero_idx
    
    opp_deck = steps[1][opp_idx].get("action", [])
    opp_counts = {}
    for c in opp_deck:
        opp_counts[cname(c)] = opp_counts.get(cname(c), 0) + 1
    top_opp = ", ".join([f"{count}x {nm}" for nm, count in sorted(opp_counts.items(), key=lambda x: -x[1])[:4]])
    
    # Classify archetype
    opp_visible_ids = set(opp_deck)
    match_name, _, match_j = v2_1_agent.policy.search_policy.registry.match(opp_visible_ids)
    
    # Trace steps
    divergences = 0
    search_triggers = 0
    setup_bench_fixed = False
    
    for s_idx, s in enumerate(steps):
        hero_step = s[hero_idx]
        act_taken = hero_step.get("action")
        obs_raw = hero_step.get("observation", {})
        select_dict = obs_raw.get("select")
        
        if select_dict is not None:
            # Check setup bench fix
            if select_dict.get("context") == 2 and select_dict.get("maxCount", 0) > 0 and act_taken == []:
                setup_bench_fixed = True
                
            try:
                obs_obj = to_observation_class(obs_raw)
                # Test v2.1 decision
                v2_1_act = v2_1_agent.policy.choose(obs_obj)
                if v2_1_act != act_taken:
                    divergences += 1
            except Exception:
                pass
                
    print(f"\n=======================================================")
    print(f"Episode {ep_id} | Total Steps: {len(steps)} | Hero Seat: P{hero_idx}")
    print(f"Opponent Archetype: {match_name} (J={match_j:.2f}) | Key Cards: {top_opp}")
    print(f"Divergent decisions with v2.1: {divergences}")
    if setup_bench_fixed:
        print(f"*** CRITICAL: v2.1 Setup Bench Fix was active in this match! ***")
