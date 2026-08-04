#!/usr/bin/env python3
"""Compare recent pairs of submissions: (55171235 vs 55180261) and (55171237 vs 55180215)."""

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
    name_counts = Counter(names)
    key_mons = []
    for name, _ in name_counts.most_common():
        if any(
            w in name.lower()
            for w in [
                "energy", "ultra ball", "nest ball", "professor", "boss", "ionov",
                "arven", "switch", "super rod", "rare candy", "buddy-buddy", "earthen", "pokégear",
            ]
        ):
            continue
        key_mons.append(name)

    joined = " ".join(names).lower()
    if "grimmsnarl" in joined or "morgrem" in joined:
        return "Grimmsnarl / Froslass"
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
    if "gardevoir" in joined or "ralts" in joined or "kirlia" in joined:
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
    if "archaludon" in joined or "duraludon" in joined:
        return "Archaludon ex"
    if "regidrago" in joined:
        return "Regidrago VSTAR"
    if "pidgeot" in joined:
        return "Pidgeot Control"
    if "mewtwo" in joined:
        return "Team Rocket's Mewtwo"
    if "garchomp" in joined or "gabite" in joined or "gible" in joined:
        return "Cynthia's Garchomp"
    if key_mons:
        return f"Custom ({'/'.join(key_mons[:2])})"
    return "Unknown Archetype"


def analyze_sub(sub_id: int, label: str, card_map: dict[int, str]) -> dict:
    sub_dir = ROOT / "data" / "replays" / str(sub_id)
    meta_path = sub_dir / "episodes_metadata.json"
    if not meta_path.exists():
        return {"error": f"No metadata for {sub_id}"}

    episodes = json.loads(meta_path.read_text())
    
    total_games = len(episodes)
    wins = 0
    losses = 0
    ties = 0
    seat_games = Counter()
    seat_wins = Counter()
    opp_arch_stats = defaultdict(lambda: {"games": 0, "wins": 0, "losses": 0})
    opp_elo_list = []
    elo_progression = []
    loss_reasons = Counter()
    bench_extinctions = 0
    time_losses = 0

    for ep in episodes:
        ep_id = ep.get("id")
        agents = ep.get("agents", [])
        our_idx = None
        for idx, ag in enumerate(agents):
            if ag.get("submissionId") == sub_id:
                our_idx = idx
                break
        if our_idx is None:
            continue

        opp_idx = 1 - our_idx
        our_agent = agents[our_idx]
        opp_agent = agents[opp_idx] if len(agents) > opp_idx else {}

        our_reward = our_agent.get("reward")
        our_init_score = our_agent.get("initialScore")
        our_upd_score = our_agent.get("updatedScore")
        opp_init_score = opp_agent.get("initialScore")

        if our_init_score is not None and our_upd_score is not None:
            elo_progression.append((our_init_score, our_upd_score))
        if opp_init_score is not None:
            opp_elo_list.append(opp_init_score)

        is_win = our_reward == 1
        is_loss = our_reward == -1 or (our_reward is not None and our_reward <= 0)
        is_tie = not is_win and not is_loss

        if is_win:
            wins += 1
            seat_wins[our_idx] += 1
        elif is_loss:
            losses += 1
        else:
            ties += 1

        seat_games[our_idx] += 1

        # Check replay file
        rp_path = sub_dir / f"episode-{ep_id}-replay.json"
        if not rp_path.exists():
            rp_path = sub_dir / f"{ep_id}.json"

        opp_arch = "Unknown"
        if rp_path.exists():
            try:
                rp_data = json.loads(rp_path.read_text())
                steps = rp_data.get("steps", [])
                if len(steps) > 1:
                    opp_deck = steps[1][opp_idx].get("action", [])
                    opp_arch = classify_deck(opp_deck, card_map)

                if is_loss:
                    # Check loss cause
                    last_step = steps[-1] if steps else []
                    our_last = last_step[our_idx] if len(last_step) > our_idx else {}
                    opp_last = last_step[opp_idx] if len(last_step) > opp_idx else {}

                    our_status = our_last.get("status")
                    if our_status == "TIMEOUT":
                        time_losses += 1
                        loss_reasons["TIMEOUT"] += 1
                    elif our_status == "ERROR":
                        loss_reasons["POLICY_ERROR"] += 1
                    else:
                        # Inspect state to see if bench extinction or prize knockout
                        bench_extinct = False
                        for st in reversed(steps):
                            obs = st[our_idx].get("observation", {})
                            cur = obs.get("current")
                            if cur and isinstance(cur, dict):
                                players = cur.get("players", [])
                                if len(players) > our_idx:
                                    our_p = players[our_idx]
                                    active = our_p.get("active", [])
                                    bench = our_p.get("bench", [])
                                    turn = cur.get("turn", 0)
                                    if len(active) == 0 and len(bench) == 0:
                                        bench_extinct = True
                                        if turn <= 3:
                                            loss_reasons[f"EARLY_BENCH_EXTINCTION_T{turn}"] += 1
                                        else:
                                            loss_reasons["MID_LATE_EXTINCTION"] += 1
                                        break
                                    elif len(players) > opp_idx:
                                        opp_p = players[opp_idx]
                                        opp_prizes = len(opp_p.get("prize", []))
                                        if opp_prizes == 0:
                                            loss_reasons["OPPONENT_TOOK_ALL_PRIZES"] += 1
                                            break
                        if not bench_extinct and "OPPONENT_TOOK_ALL_PRIZES" not in loss_reasons:
                            loss_reasons["NORMAL_PRIZE_LOSS"] += 1
            except Exception:
                pass

        opp_arch_stats[opp_arch]["games"] += 1
        if is_win:
            opp_arch_stats[opp_arch]["wins"] += 1
        elif is_loss:
            opp_arch_stats[opp_arch]["losses"] += 1

    return {
        "sub_id": sub_id,
        "label": label,
        "total_games": total_games,
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "win_rate": wins / max(1, total_games),
        "seat_0_games": seat_games[0],
        "seat_0_wins": seat_wins[0],
        "seat_0_win_rate": seat_wins[0] / max(1, seat_games[0]),
        "seat_1_games": seat_games[1],
        "seat_1_wins": seat_wins[1],
        "seat_1_win_rate": seat_wins[1] / max(1, seat_games[1]),
        "avg_opp_elo": sum(opp_elo_list) / max(1, len(opp_elo_list)),
        "min_opp_elo": min(opp_elo_list) if opp_elo_list else 0,
        "max_opp_elo": max(opp_elo_list) if opp_elo_list else 0,
        "final_elo": elo_progression[-1][1] if elo_progression else None,
        "start_elo": elo_progression[0][0] if elo_progression else None,
        "loss_reasons": dict(loss_reasons),
        "opp_arch_stats": dict(opp_arch_stats),
    }


def main():
    card_map = load_cards()
    subs = [
        (55171235, "5k Reference (Run 1 - Converged)"),
        (55180261, "5k Reference (Run 2 - Recent Drop)"),
        (55171237, "Coevo R2 (Run 1 - Converged)"),
        (55180215, "Gen4 Sparred (Run 2 - Recent Drop)"),
    ]

    results = {}
    for sub_id, label in subs:
        res = analyze_sub(sub_id, label, card_map)
        results[sub_id] = res

    print("\n" + "=" * 100)
    print("SUBMISSION COMPARISON REPORT")
    print("=" * 100)

    for sub_id, label in subs:
        r = results[sub_id]
        print(f"\n--- [{sub_id}] {label} ---")
        print(f"Games: {r['total_games']} | Record: {r['wins']}W - {r['losses']}L - {r['ties']}T (Win Rate: {r['win_rate']*100:.1f}%)")
        print(f"Elo: Start {r['start_elo']} -> Final {r['final_elo']:.1f} (Avg Opponent Elo: {r['avg_opp_elo']:.1f}, Min: {r['min_opp_elo']:.1f}, Max: {r['max_opp_elo']:.1f})")
        print(f"Seat 0 (Going 1st): {r['seat_0_wins']}/{r['seat_0_games']} ({r['seat_0_win_rate']*100:.1f}%)")
        print(f"Seat 1 (Going 2nd): {r['seat_1_wins']}/{r['seat_1_games']} ({r['seat_1_win_rate']*100:.1f}%)")
        print(f"Loss Causes: {r['loss_reasons']}")
        print("Matchups vs Archetypes:")
        for arch, st in sorted(r["opp_arch_stats"].items(), key=lambda x: x[1]["games"], reverse=True):
            wr = (st["wins"] / st["games"]) * 100 if st["games"] else 0
            print(f"  - {arch:<30}: {st['wins']}W / {st['games']}G ({wr:.1f}%)")


if __name__ == "__main__":
    main()
