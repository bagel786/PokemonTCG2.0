#!/usr/bin/env python3
"""Print full human-readable logs of Episode 90342558 and 90343300."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Load exact card names from EN_Card_Data.csv
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

card_names[7] = "Basic Darkness Energy"
card_names[3] = "Basic Psychic Energy"
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

for ep_id in [90342558, 90343300]:
    rp_path = ROOT / "data" / "replays" / "55287852" / f"episode-{ep_id}-replay.json"
    print(f"\n=======================================================")
    print(f"EPISODE: {ep_id}")
    print(f"=======================================================")
    if not rp_path.exists():
        print(f"File {rp_path} not found")
        continue
    data = json.loads(rp_path.read_text(encoding="utf-8"))
    steps = data.get("steps", [])

    for s_idx, step in enumerate(steps):
        print(f"\n--- STEP {s_idx} ---")
        for p_idx, p in enumerate(step):
            act = p.get("action")
            obs = p.get("observation", {})
            logs = obs.get("logs", [])
            cur = obs.get("current")
            status = p.get("status")
            reward = p.get("reward")

            if act:
                # If first step, it's deck
                if s_idx == 1:
                    deck_summary = {}
                    for c in act:
                        deck_summary[cname(c)] = deck_summary.get(cname(c), 0) + 1
                    print(f"  P{p_idx} Deck: {deck_summary}")
                else:
                    print(f"  P{p_idx} Action: {act}")

            if logs:
                for l in logs:
                    # Translate any cardId
                    l_str = str(l)
                    if isinstance(l, dict) and "cardId" in l:
                        l_str += f" ({cname(l['cardId'])})"
                    print(f"  P{p_idx} Log: {l_str}")

            if cur and "players" in cur:
                players = cur["players"]
                if len(players) >= 2:
                    p0 = players[0]
                    p1 = players[1]
                    p0_act = [cname(c.get("cardId")) for c in (p0.get("active") or []) if isinstance(c, dict)]
                    p0_bnc = [cname(c.get("cardId")) for c in (p0.get("bench") or []) if isinstance(c, dict)]
                    p1_act = [cname(c.get("cardId")) for c in (p1.get("active") or []) if isinstance(c, dict)]
                    p1_bnc = [cname(c.get("cardId")) for c in (p1.get("bench") or []) if isinstance(c, dict)]
                    print(f"  Board: P0 Active={p0_act} Bench={p0_bnc} (Prizes: {p0.get('prizes')}) | P1 Active={p1_act} Bench={p1_bnc} (Prizes: {p1.get('prizes')})")

            if status != "ACTIVE":
                print(f"  P{p_idx} Status={status} Reward={reward}")
