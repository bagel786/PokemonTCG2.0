#!/usr/bin/env python3
"""Forensic table for current-submission losses (EXP23 55556726, DIP_B 55562629).

For each loss: archetype, order, prize race, first-Grim turn, board composition,
and basic structural flags. Compact JSON for the Pro model.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))

from cg.api import all_card_data

POKEMON_IDS = {int(c.cardId) for c in all_card_data() if int(c.hp) > 0}
GRIM_LINE = {646, 647, 648}
MUNK = 112
FROSLASS = 104
SNORUNT = 860

DECKLIST_DIR = ROOT / "freshstart" / "decklists"
KNOWN = {
    "grimmsnarl": DECKLIST_DIR / "grimmsnarl_marnie.deck.csv",
    "dragapult": DECKLIST_DIR / "dragapult_ex.deck.csv",
    "alakazam": DECKLIST_DIR / "alakazam_dudunsparce.deck.csv",
    "crustle": DECKLIST_DIR / "kangaskhan_crustle.deck.csv",
    "bellibolt": DECKLIST_DIR / "iono_bellibolt_ex.deck.csv",
    "lucario": DECKLIST_DIR / "mega_lucario_ex.deck.csv",
}
KNOWN_DECKS = {k: [int(x) for x in p.read_text().splitlines() if x.strip()] for k, p in KNOWN.items() if p.exists()}


def archetype_of(revealed: set[int]) -> str:
    best, best_n = "other", 0
    for name, deck in KNOWN_DECKS.items():
        kpok = Counter(c for c in deck if c in POKEMON_IDS)
        shared = sum(min(revealed_count, count) for c, count in kpok.items() for revealed_count in [Counter(revealed).get(c, 0)])
        if shared > best_n:
            best, best_n = name, shared
    return best if best_n >= 3 else "other"


def forensic(replay_path: Path, our_seat: int, card_map: dict) -> dict:
    ep = json.loads(replay_path.read_text())
    opp_seat = 1 - our_seat
    first_grim_turn = None
    opp_revealed: set[int] = set()
    our_revealed: set[int] = set()
    max_our_bench = 0
    our_munk = our_fros = our_snorunt = 0
    final_prizes = None
    first_player = None
    for step_list in ep.get("steps", []):
        for entry in step_list:
            obs = entry.get("observation") or {}
            cur = obs.get("current") or {}
            if cur.get("firstPlayer") in (0, 1):
                first_player = int(cur["firstPlayer"])
            players = cur.get("players") or []
            if len(players) < 2:
                continue
            ours = players[our_seat] or {}
            opp = players[opp_seat] or {}
            for zone in ("active", "bench", "discard"):
                for card in ours.get(zone) or []:
                    if card and card.get("id") is not None:
                        cid = int(card["id"])
                        our_revealed.add(cid)
            for zone in ("active", "bench", "discard"):
                for card in opp.get(zone) or []:
                    if card and card.get("id") is not None:
                        opp_revealed.add(int(card["id"]))
            turn = int(cur.get("turn", 0) or 0)
            if first_grim_turn is None and 648 in our_revealed:
                first_grim_turn = turn
            bench = ours.get("bench") or []
            max_our_bench = max(max_our_bench, len(bench))
            our_munk = max(our_munk, sum(1 for s in bench if s and int(s.get("id", 0)) == MUNK))
            our_fros = max(our_fros, sum(1 for s in (bench + (ours.get("active") or [])) if s and int(s.get("id", 0)) == FROSLASS))
            our_snorunt = max(our_snorunt, sum(1 for s in bench if s and int(s.get("id", 0)) == SNORUNT))
            our_prize = len(ours.get("prize") or [])
            opp_prize = len(opp.get("prize") or [])
            final_prizes = {"ours": our_prize, "opp": opp_prize}
    for poke in (None,):
        pass
    return {
        "archetype": archetype_of(opp_revealed),
        "order": ("first" if first_player == our_seat else "second") if first_player is not None else "?",
        "first_grim_turn": first_grim_turn,
        "final_prizes": final_prizes,
        "max_bench": max_our_bench,
        "max_munk_on_board": our_munk,
        "max_froslass_on_board": our_fros,
        "max_snorunt_on_board": our_snorunt,
        "opp_revealed_ids": sorted(opp_revealed),
        "our_revealed_ids": sorted(our_revealed),
    }


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", required=True, help="sub_id:seat_override_optional")
    parser.add_argument("--replay-root", required=True)
    args = parser.parse_args()

    sub = args.submission.split(":")[0]
    seat_override = args.submission.split(":")[1] if ":" in args.submission else None
    d = Path(args.replay_root) / sub
    metadata = json.loads((d / "episodes_metadata.json").read_text())
    rows = []
    for meta in metadata:
        agents = meta["agents"]
        ours = next((i for i, a in enumerate(agents) if str(a.get("submissionId")) == sub), None)
        if ours is None:
            continue
        our_seat = int(seat_override) if seat_override else ours
        reward = int(agents[ours].get("reward", 0))
        if reward >= 0:
            continue
        rp = d / f"episode-{meta['id']}-replay.json"
        if not rp.exists():
            rows.append({"episode": meta["id"], "error": "no replay"})
            continue
        row = {"episode": meta["id"], "opp_submission": agents[1 - our_seat].get("submissionId")}
        row.update(forensic(rp, our_seat, {}))
        rows.append(row)
    print(json.dumps(rows, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
