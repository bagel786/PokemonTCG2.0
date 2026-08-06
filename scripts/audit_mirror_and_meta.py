#!/usr/bin/env python3
"""Detailed comparative audit of Grimmsnarl Mirrors, Alakazam, and Seat-1 Defense for Master v1 (#55283588)."""

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUB_ID = 55283588


def load_card_map() -> dict[int, str]:
    card_map = {}
    p = ROOT / "freshstart" / "data" / "EN_Card_Data.csv"
    if p.exists():
        reader = csv.DictReader(p.read_text(encoding="utf-8-sig").splitlines())
        for row in reader:
            cid = int(row.get("Card ID") or -1)
            name = row.get("Card Name") or f"Card_{cid}"
            card_map[cid] = name
    return card_map


def get_card_name(card_obj, card_map: dict[int, str]) -> str:
    if not card_obj:
        return "None"
    if isinstance(card_obj, dict):
        cid = card_obj.get("id") or card_obj.get("cardId")
        return card_map.get(cid, f"Card_{cid}")
    elif isinstance(card_obj, list) and len(card_obj) > 0:
        return get_card_name(card_obj[0], card_map)
    return str(card_obj)


def inspect_mirror_game(ep_id: int, card_map: dict[int, str]):
    out_dir = ROOT / "data" / "replays" / str(SUB_ID)
    rp_file = out_dir / f"episode-{ep_id}-replay.json"
    if not rp_file.exists():
        rp_file = out_dir / f"{ep_id}.json"
    if not rp_file.exists():
        return None

    data = json.loads(rp_file.read_text(encoding="utf-8"))
    steps = data.get("steps", [])
    agents = data.get("info", {}).get("TeamNames", [])

    # Find hero index
    hero_idx = None
    for idx, ag in enumerate(data.get("statuses", [])):
        pass
    for idx, ag in enumerate(steps[0]):
        pass

    # From metadata
    meta = json.loads((out_dir / "episodes_metadata.json").read_text())
    ep_meta = next((e for e in meta if e["id"] == ep_id), None)
    if not ep_meta:
        return None

    for idx, a in enumerate(ep_meta.get("agents", [])):
        if a.get("submissionId") == SUB_ID:
            hero_idx = idx
            break

    opp_idx = 1 - hero_idx
    hero_reward = ep_meta["agents"][hero_idx].get("reward", 0)
    won = hero_reward > 0
    opp_sub = ep_meta["agents"][opp_idx].get("submissionId")
    opp_elo = ep_meta["agents"][opp_idx].get("initialScore")

    # Analyze step by step
    timeline = []
    hero_ex_evolve_turn = None
    opp_ex_evolve_turn = None
    hero_first_attack_turn = None
    opp_first_attack_turn = None
    hero_marnie_turns = []
    opp_marnie_turns = []

    for s_idx, step in enumerate(steps):
        if len(step) <= hero_idx:
            continue
        h_ag = step[hero_idx]
        o_ag = step[opp_idx]

        h_obs = h_ag.get("observation", {})
        cur = h_obs.get("current") if isinstance(h_obs, dict) else None
        if not cur:
            continue

        turn = cur.get("turn", 0)
        players = cur.get("players", [])
        if len(players) < 2:
            continue

        h_p = players[cur.get("yourIndex", hero_idx)]
        o_p = players[1 - cur.get("yourIndex", hero_idx)]

        h_act = get_card_name(h_p.get("active", []), card_map)
        o_act = get_card_name(o_p.get("active", []), card_map)

        h_bench = [get_card_name(b, card_map) for b in h_p.get("bench", []) if b]
        o_bench = [get_card_name(b, card_map) for b in o_p.get("bench", []) if b]

        h_prizes = len(h_p.get("prize", []))
        o_prizes = len(o_p.get("prize", []))

        # Check evolutions
        if "Grimmsnarl" in h_act or any("Grimmsnarl" in b for b in h_bench):
            if hero_ex_evolve_turn is None:
                hero_ex_evolve_turn = turn

        if "Grimmsnarl" in o_act or any("Grimmsnarl" in b for b in o_bench):
            if opp_ex_evolve_turn is None:
                opp_ex_evolve_turn = turn

        # Check action
        h_act_obj = h_ag.get("action")
        if h_act_obj and isinstance(h_act_obj, dict):
            atype = h_act_obj.get("type")
            if atype == "ATTACK" and hero_first_attack_turn is None:
                hero_first_attack_turn = turn
            cid = h_act_obj.get("cardId")
            if cid and "marnie" in card_map.get(cid, "").lower():
                hero_marnie_turns.append(turn)

    return {
        "ep_id": ep_id,
        "won": won,
        "hero_seat": hero_idx,
        "opp_sub": opp_sub,
        "opp_elo": opp_elo,
        "hero_ex_turn": hero_ex_evolve_turn,
        "opp_ex_turn": opp_ex_evolve_turn,
        "hero_attack_turn": hero_first_attack_turn,
        "hero_marnie_turns": hero_marnie_turns,
        "final_prizes_hero_rem": h_prizes,
        "final_prizes_opp_rem": o_prizes,
    }


def main():
    card_map = load_card_map()
    out_dir = ROOT / "data" / "replays" / str(SUB_ID)
    forensic_path = out_dir / "master_v1_forensic_report.json"
    data = json.loads(forensic_path.read_text())

    mirror_matches = [
        m
        for m in (data.get("losses", []) + data.get("wins", []))
        if m.get("opp_arch") == "Grimmsnarl Mirror"
    ]
    mirror_matches.sort(key=lambda x: x["episode_id"])

    print("=" * 100)
    print(f"GRIMMSNARL MIRROR MATCHUP DEEP FORENSICS ({len(mirror_matches)} GAMES: 4 WINS, 8 LOSSES)")
    print("=" * 100)

    for m in mirror_matches:
        ep_id = m["episode_id"]
        res = inspect_mirror_game(ep_id, card_map)
        if not res:
            continue
        outcome = "WIN " if res["won"] else "LOSS"
        elo_str = f"{res['opp_elo']:.1f}" if res['opp_elo'] is not None else "N/A"
        print(
            f"[{outcome}] Ep {ep_id} | Seat {res['hero_seat']} vs Sub {res['opp_sub']} (Elo: {elo_str}) | "
            f"Hero Ex Turn: {res['hero_ex_turn']} vs Opp Ex Turn: {res['opp_ex_turn']} | "
            f"Hero Marnie Turns: {res['hero_marnie_turns']} | Prizes Rem: Hero {res['final_prizes_hero_rem']} vs Opp {res['final_prizes_opp_rem']}"
        )

    # Inspect Alakazam
    alakazam_matches = [
        m for m in (data.get("losses", []) + data.get("wins", [])) if m.get("opp_arch") == "Alakazam"
    ]
    print("\n" + "=" * 100)
    print(
        f"ALAKAZAM MATCHUP FORENSICS ({len(alakazam_matches)} GAMES: 9 WINS, 5 LOSSES, NET ELO: -53.8)"
    )
    print("=" * 100)
    for m in alakazam_matches:
        outcome = "WIN " if m["outcome"] == "WIN" else "LOSS"
        print(
            f"[{outcome}] Ep {m['episode_id']} | Seat {m['hero_seat']} vs Opp Elo {m['opp_init']:.1f} (Sub {m['opp_sub']}) | "
            f"Turns: {m['turns']:>2} | Prizes Taken: Hero {m['hero_prizes']}-Opp {m['opp_prizes']} | Delta: {m['elo_delta']:>+6.1f}"
        )


if __name__ == "__main__":
    main()
