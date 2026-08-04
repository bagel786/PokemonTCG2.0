#!/usr/bin/env python3
"""Inspect final 10 steps of loss games to understand end-game losses."""

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_cards() -> dict[int, str]:
    card_map = {}
    csv_path = ROOT / "freshstart" / "data" / "EN_Card_Data.csv"
    if csv_path.exists():
        reader = csv.DictReader(csv_path.read_text(encoding="utf-8-sig").splitlines())
        for row in reader:
            cid = int(row.get("Card ID") or row.get("card_id") or row.get("id") or -1)
            name = row.get("Card Name") or row.get("name") or row.get("Name") or row.get("card_name") or f"Card_{cid}"
            card_map[cid] = name
    return card_map


def inspect_endings(sub_id: int, num_samples: int = 5):
    card_map = load_cards()
    sub_dir = ROOT / "data" / "replays" / str(sub_id)
    meta = json.loads((sub_dir / "episodes_metadata.json").read_text())

    losses = []
    for ep in meta:
        agents = ep.get("agents", [])
        for idx, ag in enumerate(agents):
            if ag.get("submissionId") == sub_id and ag.get("reward") in (-1, 0):
                losses.append((ep.get("id"), idx, 1 - idx))

    print(f"\n=======================================================")
    print(f"SUBMISSION {sub_id} LOSS ENDING INSPECTION ({len(losses)} total losses)")
    print(f"=======================================================")

    for ep_id, our_idx, opp_idx in losses[:num_samples]:
        rp_file = sub_dir / f"episode-{ep_id}-replay.json"
        if not rp_file.exists():
            rp_file = sub_dir / f"{ep_id}.json"
        if not rp_file.exists():
            continue

        rp = json.loads(rp_file.read_text())
        steps = rp.get("steps", [])
        print(f"\n--- Episode {ep_id} (Seat: {our_idx}) | Total Steps: {len(steps)} ---")

        # Trace final 6 state observations
        for s_idx in range(max(0, len(steps) - 6), len(steps)):
            st = steps[s_idx]
            obs = st[our_idx].get("observation", {}).get("current", {})
            if not isinstance(obs, dict):
                print(f"Step {s_idx:03d}: [Non-dict obs]")
                continue

            turn = obs.get("turn", -1)
            players = obs.get("players", [])
            if len(players) <= max(our_idx, opp_idx):
                print(f"Step {s_idx:03d}: Turn {turn} | Players missing")
                continue

            our_p = players[our_idx]
            opp_p = players[opp_idx]

            our_act_cards = [card_map.get(c.get("id"), str(c.get("id"))) for c in our_p.get("active", []) if isinstance(c, dict)]
            opp_act_cards = [card_map.get(c.get("id"), str(c.get("id"))) for c in opp_p.get("active", []) if isinstance(c, dict)]

            our_b_cards = [card_map.get(c.get("id"), str(c.get("id"))) for c in our_p.get("bench", []) if isinstance(c, dict)]
            opp_b_cards = [card_map.get(c.get("id"), str(c.get("id"))) for c in opp_p.get("bench", []) if isinstance(c, dict)]

            our_prizes = len(our_p.get("prize", []))
            opp_prizes = len(opp_p.get("prize", []))
            our_deck = our_p.get("deckCount", -1)
            opp_deck = opp_p.get("deckCount", -1)

            our_hp = our_p.get("active", [{}])[0].get("hp") if our_p.get("active") else 0
            opp_hp = opp_p.get("active", [{}])[0].get("hp") if opp_p.get("active") else 0

            print(f"Step {s_idx:03d} [Turn {turn}]: Us Prizes={our_prizes}/6, Active={our_act_cards}(HP:{our_hp}), Bench={our_b_cards}, Deck={our_deck} | Opp Prizes={opp_prizes}/6, Active={opp_act_cards}(HP:{opp_hp}), Bench={opp_b_cards}, Deck={opp_deck}")


if __name__ == "__main__":
    inspect_endings(55180261, num_samples=3)
    inspect_endings(55180215, num_samples=3)
