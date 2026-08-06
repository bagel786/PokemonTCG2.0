#!/usr/bin/env python3
"""Detailed turn-by-turn breakdown of Episode 90342558."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RP_PATH = ROOT / "data" / "replays" / "55287852" / "episode-90342558-replay.json"

data = json.loads(RP_PATH.read_text(encoding="utf-8"))
steps = data.get("steps", [])

# Let's inspect step 1 for deck submission
step1 = steps[1]
hero_action = step1[0].get("action", [])
opp_action = step1[1].get("action", [])
print(f"Hero (Seat 0) Deck size: {len(hero_action)}, Opponent (Seat 1) Deck size: {len(opp_action)}")

# Card DB
# Card DB from decklists
card_lookup = {}
for txt_file in (ROOT / "freshstart" / "decklists").glob("*.txt"):
    csv_file = txt_file.with_suffix(".deck.csv")
    if csv_file.exists():
        names = [line.strip() for line in txt_file.read_text().strip().splitlines() if line.strip()]
        raw_ids = csv_file.read_text().replace("\n", ",").split(",")
        ids = [int(x.strip()) for x in raw_ids if x.strip()]
        for cid, nm in zip(ids, names):
            card_lookup[cid] = nm

def name(cid):
    return card_lookup.get(cid, str(cid))

print("\nHero deck cards:")
hero_card_counts = {}
for c in hero_action:
    nm = name(c)
    hero_card_counts[nm] = hero_card_counts.get(nm, 0) + 1
for nm, count in sorted(hero_card_counts.items()):
    print(f"  {count}x {nm}")

print("\nOpponent deck cards:")
opp_card_counts = {}
for c in opp_action:
    nm = name(c)
    opp_card_counts[nm] = opp_card_counts.get(nm, 0) + 1
for nm, count in sorted(opp_card_counts.items()):
    print(f"  {count}x {nm}")

print("\n--- TURN BY TURN PLAYBACK ---")
for s_idx, step in enumerate(steps):
    for p_idx, p_data in enumerate(step):
        obs = p_data.get("observation", {})
        logs = obs.get("logs", [])
        if logs:
            for line in logs:
                print(f"[Step {s_idx:02d} | P{p_idx} Log] {line}")
        action = p_data.get("action")
        reward = p_data.get("reward")
        status = p_data.get("status")
        if action:
            print(f"[Step {s_idx:02d} | P{p_idx} Action] {action}")
        if reward != 0 or status != "ACTIVE":
            print(f"[Step {s_idx:02d} | P{p_idx} Outcome] Status: {status}, Reward: {reward}")

# Final step state
final_step = steps[-1]
final_obs = final_step[0].get("observation", {}).get("current", {}) or {}
players = final_obs.get("players", [])
if len(players) >= 2:
    p0 = players[0]
    p1 = players[1]
    print(f"\nFinal State:")
    print(f"  P0 Active: {[name(c.get('cardId')) for c in p0.get('active', [])]}")
    print(f"  P0 Bench: {[name(c.get('cardId')) for c in p0.get('bench', [])]}")
    print(f"  P0 Prizes: {p0.get('prizes', 0)} / {p0.get('prizeCount', 0)}")
    print(f"  P0 Hand count: {len(p0.get('hand', []))}")
    print(f"  P0 Deck count: {len(p0.get('deck', []))}")
    print(f"  P1 Active: {[name(c.get('cardId')) for c in p1.get('active', [])]}")
    print(f"  P1 Bench: {[name(c.get('cardId')) for c in p1.get('bench', [])]}")
    print(f"  P1 Prizes: {p1.get('prizes', 0)} / {p1.get('prizeCount', 0)}")
