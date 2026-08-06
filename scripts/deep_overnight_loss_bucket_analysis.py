#!/usr/bin/env python3
"""Deep loss-bucket analysis across all 58 live ladder games of Sub 55287852."""

import base64
import json
import ssl
import subprocess
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
replays_dir = ROOT / "data" / "replays" / "55287852"
replays_dir.mkdir(parents=True, exist_ok=True)

EPISODE_SERVICE = "https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodes"

def auth_header() -> str:
    kaggle_json = Path.home() / ".kaggle" / "kaggle.json"
    if not kaggle_json.exists():
        return ""
    blob = json.loads(kaggle_json.read_text())
    if "access_token" in blob:
        return "Bearer " + blob["access_token"]
    pair = f"{blob['username']}:{blob['key']}".encode()
    return "Basic " + base64.b64encode(pair).decode()

def fetch_episode_metadata(sub_id: int) -> list[dict]:
    payload = json.dumps({"submissionId": sub_id}).encode()
    headers = {"Content-Type": "application/json", "User-Agent": "PTCG-Live/1.0"}
    auth = auth_header()
    if auth:
        headers["Authorization"] = auth
    req = urllib.request.Request(EPISODE_SERVICE, data=payload, headers=headers)
    ctx = ssl._create_unverified_context()
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        return json.loads(resp.read().decode()).get("episodes", [])

# Initialize v2.1 agent to evaluate divergence on all losses
from ptcg_ai.agent import CompetitionAgent
v2_1_agent = CompetitionAgent(
    deck_path=ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv",
    model_path=ROOT / "artifacts" / "v2_model" / "policy_weights.npz"
)

eps = fetch_episode_metadata(55287852)
print(f"Total live episodes for Sub 55287852: {len(eps)}")

# Download all replay files
needed_ep_ids = [ep['id'] for ep in eps]
for ep_id in needed_ep_ids:
    rp_path = replays_dir / f"episode-{ep_id}-replay.json"
    if not rp_path.exists():
        cmd = [sys.executable, "-m", "kaggle", "competitions", "replay", str(ep_id), "-p", str(replays_dir)]
        subprocess.run(cmd, capture_output=True, text=True)
        alt = replays_dir / f"{ep_id}.json"
        if alt.exists():
            alt.rename(rp_path)

# Analyze all matches
bucket_counts = defaultdict(int)
bucket_losses = defaultdict(int)
archetype_records = defaultdict(lambda: {"W": 0, "L": 0, "T": 0})
rating_tier_records = defaultdict(lambda: {"W": 0, "L": 0, "T": 0})

loss_details = []

for ep in sorted(eps, key=lambda x: x['id']):
    ep_id = ep['id']
    ag = ep.get("agents", [])
    if len(ag) < 2:
        continue
    h_idx = 0 if ag[0].get("submissionId") == 55287852 else 1
    o_idx = 1 - h_idx
    h, o = ag[h_idx], ag[o_idx]
    h_init = h.get("initialScore", 0) or 0
    h_upd = h.get("updatedScore", 0) or 0
    o_init = o.get("initialScore", 0) or 0
    rew = h.get("reward")
    
    # Rating tier
    if o_init >= 850:
        tier = "Elite (850+)"
    elif o_init >= 750:
        tier = "High (750-849)"
    elif o_init >= 650:
        tier = "Mid (650-749)"
    else:
        tier = "Low (<650)"
        
    if rew == 1:
        rating_tier_records[tier]["W"] += 1
    elif rew == -1:
        rating_tier_records[tier]["L"] += 1
    else:
        rating_tier_records[tier]["T"] += 1
        
    rp_path = replays_dir / f"episode-{ep_id}-replay.json"
    if not rp_path.exists():
        continue
    
    data = json.loads(rp_path.read_text(encoding="utf-8"))
    steps = data.get("steps", [])
    if len(steps) < 2:
        continue
        
    opp_deck = steps[1][o_idx].get("action", [])
    opp_visible_ids = set(opp_deck)
    match_name, _, match_j = v2_1_agent.policy.search_policy.registry.match(opp_visible_ids)
    arch_label = match_name if match_name and match_j >= 0.25 else "Rogue/Other"
    
    if rew == 1:
        archetype_records[arch_label]["W"] += 1
    elif rew == -1:
        archetype_records[arch_label]["L"] += 1
    else:
        archetype_records[arch_label]["T"] += 1
        
    if rew == -1:
        # Categorize loss bucket
        is_setup_blunder = False
        for s in steps[:15]:
            select_dict = s[h_idx].get("observation", {}).get("select")
            if select_dict and select_dict.get("context") == 2 and select_dict.get("maxCount", 0) > 0 and s[h_idx].get("action") == []:
                is_setup_blunder = True
                break
                
        if len(steps) <= 30:
            bucket = "Turn 1-2 Quick Knockout / Donk"
        elif is_setup_blunder:
            bucket = "Setup Bench Blunder (Passed with 0 Bench)"
        elif "ogerpon" in arch_label or 96 in opp_visible_ids or 1 in opp_visible_ids:
            bucket = "Grass Weakness / Ogerpon ex Matchup"
        elif "lucario" in arch_label or 678 in opp_visible_ids:
            bucket = "Mega Lucario Heavy Strike Race"
        elif "grimmsnarl" in arch_label and match_j > 0.80:
            bucket = "Grimmsnarl Mirror Endgame Race"
        elif len(steps) >= 150:
            bucket = "Deep Endgame War (150+ steps)"
        else:
            bucket = "Midgame Tactical Attrition"
            
        bucket_losses[bucket] += 1
        loss_details.append({
            "ep_id": ep_id,
            "opp_elo": o_init,
            "opp_sub": o.get("submissionId"),
            "steps": len(steps),
            "delta": h_upd - h_init,
            "archetype": arch_label,
            "bucket": bucket,
            "setup_blunder": is_setup_blunder,
        })

print("\n=======================================================")
print(f"SUBMISSION 55287852 OVERNIGHT RECORD: {len(eps)} games")
print(f"Record: {sum(r['W'] for r in rating_tier_records.values())}W - {sum(r['L'] for r in rating_tier_records.values())}L (Win Rate: {sum(r['W'] for r in rating_tier_records.values())/len(eps)*100:.1f}%)")
print("=======================================================")

print("\n--- PERFORMANCE BY OPPONENT ELO TIER ---")
for tier, rec in sorted(rating_tier_records.items()):
    tot = rec['W'] + rec['L'] + rec['T']
    wr = rec['W'] / max(1, tot) * 100
    print(f"  {tier:16s}: {rec['W']:2d}W - {rec['L']:2d}L - {rec['T']:1d}T ({wr:5.1f}%) [Total: {tot:2d}]")

print("\n--- PERFORMANCE BY OPPONENT ARCHETYPE ---")
for arch, rec in sorted(archetype_records.items(), key=lambda x: -(x[1]['W']+x[1]['L'])):
    tot = rec['W'] + rec['L'] + rec['T']
    wr = rec['W'] / max(1, tot) * 100
    print(f"  {arch:16s}: {rec['W']:2d}W - {rec['L']:2d}L - {rec['T']:1d}T ({wr:5.1f}%) [Total: {tot:2d}]")

print("\n--- LOSS BUCKET BREAKDOWN (21 Total Losses) ---")
for bucket, count in sorted(bucket_losses.items(), key=lambda x: -x[1]):
    print(f"  {count:2d} losses ({count/21*100:4.1f}%): {bucket}")
