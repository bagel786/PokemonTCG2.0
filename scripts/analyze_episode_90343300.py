#!/usr/bin/env python3
"""Comprehensive replay analysis of Episode 90343300 (Loss vs 579.4 Elo)."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
rp_path = ROOT / "data" / "replays" / "55287852" / "episode-90343300-replay.json"

if not rp_path.exists():
    print("Replay not found.")
    sys.exit(1)

data = json.loads(rp_path.read_text(encoding="utf-8"))
steps = data.get("steps", [])

# Build card lookup
card_names = {}
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

card_names[1] = "Basic Grass Energy"
card_names[3] = "Basic Psychic Energy"
card_names[7] = "Basic Darkness Energy"
card_names[96] = "Teal Mask Ogerpon ex"
card_names[646] = "Marnie's Impidimp"
card_names[647] = "Marnie's Morgrem"
card_names[648] = "Marnie's Grimmsnarl ex"
card_names[112] = "Marnie"
card_names[104] = "Spikemuth Gym"
card_names[1086] = "Marnie's Morpeko"
card_names[1079] = "Rare Candy"
card_names[1097] = "Professor's Research"
card_names[1219] = "Nest Ball"
card_names[1227] = "Ultra Ball"
card_names[1259] = "Boss's Orders"

def cname(cid):
    return card_names.get(cid, f"Card#{cid}")

print(f"Total steps: {len(steps)}")

# Step 1: Decks
p0_deck = steps[1][0].get("action", [])
p1_deck = steps[1][1].get("action", [])

print("\n--- OPPONENT (P0, Elo 579.4) DECK ---")
p0_counts = {}
for c in p0_deck:
    p0_counts[cname(c)] = p0_counts.get(cname(c), 0) + 1
for nm, count in sorted(p0_counts.items(), key=lambda x: -x[1]):
    print(f"  {count:2d}x {nm}")

print("\n--- OUR AGENT (P1, Elo 674.8) DECK ---")
p1_counts = {}
for c in p1_deck:
    p1_counts[cname(c)] = p1_counts.get(cname(c), 0) + 1
for nm, count in sorted(p1_counts.items(), key=lambda x: -x[1]):
    print(f"  {count:2d}x {nm}")

print("\n--- KEY EVENTS TIMELINE ---")
for s_idx, s in enumerate(steps):
    for p_idx, p in enumerate(s):
        obs = p.get("observation", {})
        logs = obs.get("logs", [])
        cur = obs.get("current") or {}
        act = p.get("action")
        
        # Filter for attacks, knockouts, evolution, supporters, prizes
        for l in logs:
            l_type = l.get("type")
            # 15: Attack, 16: Damage/KO, 12: Evolve, 10: Play Trainer/Item, 11: Attach Energy, 6: Move card
            if l_type == 15:
                print(f"[Step {s_idx:03d} | P{l.get('playerIndex')} ATTACK] Attack {l.get('attackId')} on {cname(l.get('cardId'))}")
            elif l_type == 16 and l.get('value', 0) < 0:
                print(f"[Step {s_idx:03d} | P{l.get('playerIndex')} DAMAGE] {l.get('value')} damage to {cname(l.get('cardId'))}")
            elif l_type == 12:
                print(f"[Step {s_idx:03d} | P{l.get('playerIndex')} EVOLVE] Evolved {cname(l.get('cardIdTarget'))} -> {cname(l.get('cardId'))}")
            elif l_type == 10 and l.get('cardId') in [112, 1097, 1227, 1219, 1259, 1079]:
                print(f"[Step {s_idx:03d} | P{l.get('playerIndex')} PLAY] Played {cname(l.get('cardId'))}")
        
        if p.get("status") != "ACTIVE":
            print(f"[Step {s_idx:03d} | P{p_idx} TERMINAL] Status={p.get('status')}, Reward={p.get('reward')}")
            
    # Every 20 steps, print board state
    if s_idx in [10, 30, 50, 70, 90, 110, 117]:
        obs0 = s[0].get("observation", {})
        cur0 = obs0.get("current") or {}
        players = cur0.get("players", [])
        if len(players) >= 2:
            p0 = players[0]
            p1 = players[1]
            p0_act = [cname(c.get("cardId")) for c in (p0.get("active") or []) if isinstance(c, dict)]
            p1_act = [cname(c.get("cardId")) for c in (p1.get("active") or []) if isinstance(c, dict)]
            p0_bnc = [cname(c.get("cardId")) for c in (p0.get("bench") or []) if isinstance(c, dict)]
            p1_bnc = [cname(c.get("cardId")) for c in (p1.get("bench") or []) if isinstance(c, dict)]
            p0_h = len(p0.get('hand') or [])
            p0_d = len(p0.get('deck') or [])
            p1_h = len(p1.get('hand') or [])
            p1_d = len(p1.get('deck') or [])
            print(f"\n >>> BOARD AT STEP {s_idx} <<<")
            print(f"     P0 (Opp): Active={p0_act}, Bench={p0_bnc}, Hand={p0_h}, Deck={p0_d}, PrizesRemaining={p0.get('prizes')}")
            print(f"     P1 (Hero): Active={p1_act}, Bench={p1_bnc}, Hand={p1_h}, Deck={p1_d}, PrizesRemaining={p1.get('prizes')}")
