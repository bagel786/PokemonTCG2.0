#!/usr/bin/env python3
"""Forensic deep dive into Episode 90342558 and 90343300."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Download 90343300 replay as well
ep_ids = [90342558, 90343300]
out_dir = ROOT / "data" / "replays" / "55287852"

for ep_id in ep_ids:
    cmd = [sys.executable, "-m", "kaggle", "competitions", "replay", str(ep_id), "-p", str(out_dir)]
    subprocess.run(cmd, capture_output=True, text=True)
    alt = out_dir / f"{ep_id}.json"
    target = out_dir / f"episode-{ep_id}-replay.json"
    if alt.exists():
        alt.rename(target)

# Load card names
card_lookup = {}
for txt_file in (ROOT / "freshstart" / "decklists").glob("*.txt"):
    csv_file = txt_file.with_suffix(".deck.csv")
    if csv_file.exists():
        names = [line.strip() for line in txt_file.read_text().strip().splitlines() if line.strip()]
        raw_ids = csv_file.read_text().replace("\n", ",").split(",")
        ids = [int(x.strip()) for x in raw_ids if x.strip()]
        for cid, nm in zip(ids, names):
            card_lookup[cid] = nm

# Additional manual IDs if known
card_lookup[7] = "Darkness Energy"
card_lookup[3] = "Psychic Energy"
card_lookup[646] = "Alakazam"
card_lookup[721] = "Impidimp"
card_lookup[722] = "Morgrem"
card_lookup[723] = "Grimmsnarl"
card_lookup[1145] = "Marnie"
card_lookup[1227] = "Professor's Research"
card_lookup[1205] = "Ultra Ball"
card_lookup[1235] = "Rare Candy"
card_lookup[1122] = "Arven"
card_lookup[1219] = "Nest Ball"
card_lookup[1158] = "Boss's Orders"
card_lookup[1086] = "Kangaskhan"
card_lookup[1097] = "Dudunsparce"
card_lookup[1081] = "Dunsparce"
card_lookup[741] = "Mega Lucario ex"
card_lookup[742] = "Riolu"
card_lookup[743] = "Lucario"
card_lookup[140] = "Abra"
card_lookup[305] = "Kadabra"

def name(cid):
    return card_lookup.get(cid, f"Card#{cid}")

for ep_id in ep_ids:
    print(f"\n=======================================================")
    print(f"EPISODE FORENSICS: {ep_id}")
    print(f"=======================================================")
    rp_file = out_dir / f"episode-{ep_id}-replay.json"
    if not rp_file.exists():
        print(f"Replay file {rp_file} not found.")
        continue
    data = json.loads(rp_file.read_text(encoding="utf-8"))
    steps = data.get("steps", [])
    print(f"Total steps: {len(steps)}")
    
    # Step 1: Decks
    step1 = steps[1]
    p0_deck = step1[0].get("action", [])
    p1_deck = step1[1].get("action", [])
    print(f"P0 (Opponent) Deck ({len(p0_deck)} cards):")
    p0_counts = {}
    for c in p0_deck:
        nm = name(c)
        p0_counts[nm] = p0_counts.get(nm, 0) + 1
    for nm, count in sorted(p0_counts.items()):
        print(f"  {count}x {nm}")

    print(f"\nP1 (Our v2 Agent) Deck ({len(p1_deck)} cards):")
    p1_counts = {}
    for c in p1_deck:
        nm = name(c)
        p1_counts[nm] = p1_counts.get(nm, 0) + 1
    for nm, count in sorted(p1_counts.items()):
        print(f"  {count}x {nm}")

    print(f"\n--- STEP-BY-STEP REPLAY AUDIT ---")
    for s_idx, step in enumerate(steps):
        p0_info = step[0]
        p1_info = step[1]
        
        # Check observations / actions
        obs0 = p0_info.get("observation", {})
        obs1 = p1_info.get("observation", {})
        
        cur0 = obs0.get("current") or {}
        cur1 = obs1.get("current") or {}
        
        act0 = p0_info.get("action")
        act1 = p1_info.get("action")
        
        logs0 = obs0.get("logs", [])
        
        if s_idx in [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22]:
            print(f"\n[Step {s_idx}]")
            if act0:
                print(f"  P0 Action: {act0}")
            if act1:
                print(f"  P1 Action: {act1}")
            if logs0:
                for l in logs0:
                    print(f"  Log: {l}")
            
            # Print board state
            players = cur0.get("players", []) or cur1.get("players", [])
            if len(players) >= 2:
                p0_act = [name(c.get('cardId')) for c in players[0].get('active', [])]
                p0_bnc = [name(c.get('cardId')) for c in players[0].get('bench', [])]
                p1_act = [name(c.get('cardId')) for c in players[1].get('active', [])]
                p1_bnc = [name(c.get('cardId')) for c in players[1].get('bench', [])]
                print(f"  P0 Active: {p0_act}, Bench: {p0_bnc}, Hand: {len(players[0].get('hand', []))}, Deck: {len(players[0].get('deck', []))}")
                print(f"  P1 Active: {p1_act}, Bench: {p1_bnc}, Hand: {len(players[1].get('hand', []))}, Deck: {len(players[1].get('deck', []))}")
        
        if p0_info.get("status") != "ACTIVE" or p1_info.get("status") != "ACTIVE":
            print(f"  [TERMINAL] P0 Status: {p0_info.get('status')}, Reward: {p0_info.get('reward')}")
            print(f"  [TERMINAL] P1 Status: {p1_info.get('status')}, Reward: {p1_info.get('reward')}")
