#!/usr/bin/env python3
"""Compare 5k Reference (55171235) vs Gen4 Sparred (55180215) in identical Elo bands and matchups."""

import csv
import json
from collections import Counter, defaultdict
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


def classify_deck(card_ids: list[int], card_map: dict[int, str]) -> str:
    names = [card_map.get(cid, str(cid)) for cid in card_ids]
    joined = " ".join(names).lower()
    if "grimmsnarl" in joined or "morgrem" in joined:
        return "Grimmsnarl / Froslass (Mirror)"
    if "alakazam" in joined or "abra" in joined:
        return "Alakazam / Dudunsparce"
    if "miraidon" in joined or "iron hands" in joined or "raikou" in joined:
        return "Miraidon / Lightning"
    if "roaring moon" in joined:
        return "Roaring Moon"
    if "raging bolt" in joined or "ogerpon" in joined:
        return "Raging Bolt / Ogerpon"
    if "charizard" in joined or "charmander" in joined:
        return "Charizard ex"
    if "gardevoir" in joined:
        return "Gardevoir ex"
    if "dragapult" in joined or "drakloak" in joined:
        return "Dragapult ex"
    if "lugia" in joined or "archeops" in joined:
        return "Lugia / Archeops"
    if "crustle" in joined or "dwebble" in joined:
        return "Crustle Stall"
    if "snorlax" in joined:
        return "Snorlax Stall"
    if "gholdengo" in joined:
        return "Gholdengo ex"
    if "archaludon" in joined:
        return "Archaludon ex"
    if "regidrago" in joined:
        return "Regidrago VSTAR"
    if "mewtwo" in joined:
        return "Team Rocket's Mewtwo"
    if "garchomp" in joined or "gabite" in joined:
        return "Cynthia's Garchomp"
    if "abomasnow" in joined:
        return "Mega Abomasnow"
    if "lucario" in joined or "riolu" in joined:
        return "Mega Lucario / Fighting"
    return "Custom / Other"


def analyze_ladder_performance(sub_id: int, label: str, card_map: dict[int, str]):
    sub_dir = ROOT / "data" / "replays" / str(sub_id)
    meta = json.loads((sub_dir / "episodes_metadata.json").read_text())

    elo_bands = {
        "< 700": {"wins": 0, "losses": 0, "games": 0},
        "700 - 799": {"wins": 0, "losses": 0, "games": 0},
        "800 - 899": {"wins": 0, "losses": 0, "games": 0},
        "900+": {"wins": 0, "losses": 0, "games": 0},
    }

    arch_stats = defaultdict(lambda: {"wins": 0, "losses": 0, "games": 0})
    seat_stats = {0: {"wins": 0, "games": 0}, 1: {"wins": 0, "games": 0}}
    total_wins, total_losses, total_games = 0, 0, len(meta)

    for ep in meta:
        agents = ep.get("agents", [])
        if len(agents) < 2:
            continue
        if agents[0].get("submissionId") == sub_id:
            us, opp, our_seat, opp_seat = agents[0], agents[1], 0, 1
        elif agents[1].get("submissionId") == sub_id:
            us, opp, our_seat, opp_seat = agents[1], agents[0], 1, 0
        else:
            continue

        opp_elo = opp.get("initialScore") or 600.0
        is_win = us.get("reward") == 1
        is_loss = us.get("reward") == -1 or (us.get("reward") is not None and us.get("reward") <= 0)

        if is_win:
            total_wins += 1
            seat_stats[our_seat]["wins"] += 1
        elif is_loss:
            total_losses += 1

        seat_stats[our_seat]["games"] += 1

        if opp_elo < 700:
            band = "< 700"
        elif opp_elo < 800:
            band = "700 - 799"
        elif opp_elo < 900:
            band = "800 - 899"
        else:
            band = "900+"

        elo_bands[band]["games"] += 1
        if is_win:
            elo_bands[band]["wins"] += 1
        elif is_loss:
            elo_bands[band]["losses"] += 1

        # Replay archetype
        ep_id = ep.get("id")
        rp_path = sub_dir / f"episode-{ep_id}-replay.json"
        if not rp_path.exists():
            rp_path = sub_dir / f"{ep_id}.json"
        if rp_path.exists():
            try:
                rp_data = json.loads(rp_path.read_text())
                steps = rp_data.get("steps", [])
                if len(steps) > 1:
                    opp_deck = steps[1][opp_seat].get("action", [])
                    arch = classify_deck(opp_deck, card_map)
                    arch_stats[arch]["games"] += 1
                    if is_win:
                        arch_stats[arch]["wins"] += 1
                    elif is_loss:
                        arch_stats[arch]["losses"] += 1
            except Exception:
                pass

    return {
        "sub_id": sub_id,
        "label": label,
        "total_games": total_games,
        "wins": total_wins,
        "losses": total_losses,
        "win_rate": total_wins / max(1, total_games),
        "seat_0_wr": seat_stats[0]["wins"] / max(1, seat_stats[0]["games"]),
        "seat_1_wr": seat_stats[1]["wins"] / max(1, seat_stats[1]["games"]),
        "seat_0_games": seat_stats[0]["games"],
        "seat_1_games": seat_stats[1]["games"],
        "elo_bands": elo_bands,
        "arch_stats": dict(arch_stats),
    }


def main():
    card_map = load_cards()
    res_5k = analyze_ladder_performance(55171235, "5k Ref + Prior (55171235)", card_map)
    res_gen4 = analyze_ladder_performance(55180215, "Gen4 Sparred + Prior (55180215)", card_map)

    print("=" * 90)
    print("DIRECT ELO BAND & ARCHETYPE COMPARISON: 5k+Prior vs Gen4+Prior")
    print("=" * 90)

    for r in [res_5k, res_gen4]:
        print(f"\n### {r['label']} (Games: {r['total_games']} | Overall WR: {r['win_rate']*100:.1f}%)")
        print(f"Seat 0 (Going 1st): {r['seat_0_wr']*100:.1f}% ({r['seat_0_games']} games)")
        print(f"Seat 1 (Going 2nd): {r['seat_1_wr']*100:.1f}% ({r['seat_1_games']} games)")
        print("Performance by Opponent Elo Band:")
        for band, d in r["elo_bands"].items():
            wr = (d["wins"] / d["games"] * 100) if d["games"] else 0.0
            print(f"  - {band:<12}: {d['wins']:2d}W / {d['games']:2d}G ({wr:5.1f}%) [Losses: {d['losses']}]")

        print("Performance by Opponent Archetype:")
        for arch, d in sorted(r["arch_stats"].items(), key=lambda x: x[1]["games"], reverse=True):
            wr = (d["wins"] / d["games"] * 100) if d["games"] else 0.0
            print(f"  - {arch:<32}: {d['wins']:2d}W / {d['games']:2d}G ({wr:5.1f}%)")


if __name__ == "__main__":
    main()
