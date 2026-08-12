#!/usr/bin/env python3
"""Deep forensic analysis of all 45 live ladder games for Master v1 (Submission #55283588)."""

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUB_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 55283588


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


def classify_deck(card_ids: list[int], card_map: dict[int, str]) -> str:
    names = [card_map.get(cid, str(cid)) for cid in card_ids]
    joined = " ".join(names).lower()

    if "grimmsnarl" in joined or "morgrem" in joined or "impidimp" in joined:
        return "Grimmsnarl Mirror"
    if "lucario" in joined or "riolu" in joined:
        return "Lucario Aggro"
    if "alakazam" in joined or "abra" in joined or "kadabra" in joined:
        return "Alakazam"
    if "raging bolt" in joined or "ogerpon" in joined:
        return "Raging Bolt / Ogerpon"
    if "miraidon" in joined or "iron hands" in joined or "raikou" in joined:
        return "Miraidon / Lightning"
    if "crustle" in joined or "dwebble" in joined:
        return "Crustle Stall"
    if "snorlax" in joined or "pidgeot control" in joined:
        return "Snorlax / Stall"
    if "charizard" in joined or "charmander" in joined:
        return "Charizard ex"
    if "gardevoir" in joined or "ralts" in joined or "kirlia" in joined:
        return "Gardevoir ex"
    if "dragapult" in joined or "drakloak" in joined:
        return "Dragapult ex"
    if "archaludon" in joined or "duraludon" in joined:
        return "Archaludon ex"
    if "regidrago" in joined:
        return "Regidrago VSTAR"
    if "roaring moon" in joined:
        return "Roaring Moon"
    if "mewtwo" in joined:
        return "Mewtwo ex"
    if "gholdengo" in joined:
        return "Gholdengo ex"
    if "chien-pao" in joined or "baxcalibur" in joined:
        return "Chien-Pao / Bax"
    if "garchomp" in joined:
        return "Garchomp ex"

    non_trainers = [
        n
        for n in names
        if not any(
            w in n.lower()
            for w in [
                "energy",
                "ball",
                "professor",
                "boss",
                "iono",
                "marnie",
                "arven",
                "switch",
                "rod",
                "candy",
                "pad",
            ]
        )
    ]
    if non_trainers:
        return f"Other ({non_trainers[0]})"
    return "Unknown Archetype"


def get_card_name(card_obj, card_map: dict[int, str]) -> str:
    if not card_obj:
        return "None"
    if isinstance(card_obj, dict):
        cid = card_obj.get("id") or card_obj.get("cardId")
        return card_map.get(cid, f"Card_{cid}")
    elif isinstance(card_obj, list) and len(card_obj) > 0:
        return get_card_name(card_obj[0], card_map)
    return str(card_obj)


def parse_detailed_game(replay_file: Path, hero_seat: int, card_map: dict[int, str]) -> dict:
    info = {
        "turns": 0,
        "hero_first": False,
        "hero_opening_active": None,
        "hero_opening_bench": [],
        "opp_opening_active": None,
        "opp_opening_bench": [],
        "opp_deck_cards": [],
        "opp_archetype": "Unknown",
        "hero_final_prizes_remaining": 6,
        "opp_final_prizes_remaining": 6,
        "hero_prizes_taken": 0,
        "opp_prizes_taken": 0,
        "hero_cards_played": Counter(),
        "hero_evolutions": Counter(),
        "opp_evolutions": Counter(),
        "prize_progression": [],
        "game_over_reason": "",
        "detailed_diagnosis": "",
        "turn_snapshots": {},
    }

    try:
        data = json.loads(replay_file.read_text(encoding="utf-8"))
    except Exception as e:
        info["game_over_reason"] = f"JSON Parse Error: {e}"
        return info

    steps = data.get("steps", [])
    if not steps:
        info["game_over_reason"] = "Empty Steps"
        return info

    opp_seat = 1 - hero_seat

    # Opponent deck from step 1
    if len(steps) > 1 and len(steps[1]) > opp_seat:
        act = steps[1][opp_seat].get("action", [])
        if isinstance(act, list) and len(act) == 60:
            info["opp_deck_cards"] = act
            info["opp_archetype"] = classify_deck(act, card_map)

    # Check terminal statuses
    last_step = steps[-1]
    for idx, ag_step in enumerate(last_step):
        status = ag_step.get("status")
        if status not in ("DONE", "ACTIVE"):
            info["game_over_reason"] = f"Seat_{idx}_{status}"

    max_turn = 0
    hero_p_rem = 6
    opp_p_rem = 6

    for s_idx, step in enumerate(steps):
        if len(step) <= hero_seat:
            continue
        hero_agent = step[hero_seat]
        opp_agent = step[opp_seat]

        hero_obs = hero_agent.get("observation", {})
        cur = hero_obs.get("current") if isinstance(hero_obs, dict) else None

        if cur and isinstance(cur, dict):
            players = cur.get("players", [])
            your_idx = cur.get("yourIndex", hero_seat)
            turn = cur.get("turn", 0)

            if turn > max_turn:
                max_turn = turn

            if info["turns"] == 0:
                info["hero_first"] = cur.get("firstPlayer") == your_idx

            if len(players) >= 2:
                h_p = players[your_idx]
                o_p = players[1 - your_idx]

                h_prize_list = h_p.get("prize", [])
                o_prize_list = o_p.get("prize", [])

                h_rem = len(h_prize_list) if isinstance(h_prize_list, list) else int(h_prize_list)
                o_rem = len(o_prize_list) if isinstance(o_prize_list, list) else int(o_prize_list)

                if (h_rem != hero_p_rem or o_rem != opp_p_rem) and (h_rem <= 6 and o_rem <= 6):
                    info["prize_progression"].append(
                        {
                            "turn": turn,
                            "hero_prizes_taken": 6 - h_rem,
                            "opp_prizes_taken": 6 - o_rem,
                            "hero_rem": h_rem,
                            "opp_rem": o_rem,
                        }
                    )
                hero_p_rem = h_rem
                opp_p_rem = o_rem

                # Record turn 1 board
                if turn == 1 and info["hero_opening_active"] is None:
                    h_act = h_p.get("active", [])
                    o_act = o_p.get("active", [])
                    info["hero_opening_active"] = get_card_name(h_act, card_map)
                    info["opp_opening_active"] = get_card_name(o_act, card_map)

                    h_bench = h_p.get("bench", [])
                    o_bench = o_p.get("bench", [])
                    info["hero_opening_bench"] = [
                        get_card_name(b, card_map) for b in h_bench if b and (isinstance(b, list) or isinstance(b, dict))
                    ]
                    info["opp_opening_bench"] = [
                        get_card_name(b, card_map) for b in o_bench if b and (isinstance(b, list) or isinstance(b, dict))
                    ]

                # Sample snapshot every turn
                if turn not in info["turn_snapshots"]:
                    h_act_name = get_card_name(h_p.get("active", []), card_map)
                    h_bench_names = [
                        get_card_name(b, card_map)
                        for b in h_p.get("bench", [])
                        if b and (isinstance(b, list) or isinstance(b, dict))
                    ]
                    o_act_name = get_card_name(o_p.get("active", []), card_map)
                    o_bench_names = [
                        get_card_name(b, card_map)
                        for b in o_p.get("bench", [])
                        if b and (isinstance(b, list) or isinstance(b, dict))
                    ]
                    h_hand = h_p.get("hand") or []
                    o_hand = o_p.get("hand") or []
                    info["turn_snapshots"][turn] = {
                        "hero_active": h_act_name,
                        "hero_bench": h_bench_names,
                        "opp_active": o_act_name,
                        "opp_bench": o_bench_names,
                        "hero_hand_count": h_p.get("handCount", len(h_hand)),
                        "opp_hand_count": o_p.get("handCount", len(o_hand)),
                        "hero_prizes_rem": hero_p_rem,
                        "opp_prizes_rem": opp_p_rem,
                    }

        # Track actions
        hero_action = hero_agent.get("action")
        if hero_action and isinstance(hero_action, dict):
            atype = hero_action.get("type") or hero_action.get("actionType")
            cid = hero_action.get("cardId")
            cname = card_map.get(cid, f"Card_{cid}") if cid else str(atype)
            info["hero_cards_played"][cname] += 1

            if atype == "EVOLVE":
                info["hero_evolutions"][cname] += 1

        # Check logs for evolutions and plays
        logs = hero_obs.get("logs", []) if isinstance(hero_obs, dict) else []
        for l in logs:
            if isinstance(l, dict):
                ltype = l.get("type")
                pidx = l.get("playerIndex")
                cid = l.get("cardId")
                cname = card_map.get(cid, f"Card_{cid}") if cid else "Unknown"
                # Evolve log type
                if ltype == 12:  # Evolve in engine
                    if pidx == your_idx:
                        info["hero_evolutions"][cname] += 1
                    else:
                        info["opp_evolutions"][cname] += 1

    info["turns"] = max_turn
    info["hero_final_prizes_remaining"] = hero_p_rem
    info["opp_final_prizes_remaining"] = opp_p_rem
    info["hero_prizes_taken"] = 6 - hero_p_rem
    info["opp_prizes_taken"] = 6 - opp_p_rem

    # Deep diagnosis of game
    h_win = info["hero_prizes_taken"] >= 6 or (info["opp_prizes_taken"] < 6 and hero_agent.get("reward", 0) > 0)
    h_loss = (
        info["opp_prizes_taken"] >= 6
        or (hero_agent.get("reward", 0) < 0)
        or (info["game_over_reason"].startswith("Seat_0") and hero_seat == 0)
        or (info["game_over_reason"].startswith("Seat_1") and hero_seat == 1)
    )

    if h_loss:
        if info["game_over_reason"]:
            info["detailed_diagnosis"] = f"CRASH / TIMEOUT / DISQUALIFICATION ({info['game_over_reason']})"
        elif info["turns"] <= 3 and len(info["hero_opening_bench"]) == 0 and info["hero_prizes_taken"] == 0:
            info["detailed_diagnosis"] = (
                f"EARLY DONK: Lone {info['hero_opening_active']} knocked out on Turn {info['turns']} with 0 bench."
            )
        elif info["opp_archetype"] == "Grimmsnarl Mirror":
            if info["hero_prizes_taken"] >= 4:
                info["detailed_diagnosis"] = (
                    f"CLOSE MIRROR RACE: Lost {info['hero_prizes_taken']}-6 on Turn {info['turns']}. Opponent had faster tempo/KO."
                )
            elif info["hero_evolutions"].get("Grimmsnarl", 0) == 0 and info["hero_evolutions"].get("Morgrem", 0) == 0:
                info["detailed_diagnosis"] = (
                    f"MIRROR EVOLUTION STALL: Never reached Grimmsnarl. Evolved: {dict(info['hero_evolutions'])}."
                )
            else:
                info["detailed_diagnosis"] = (
                    f"MIRROR TEMPO COLLAPSE: Evolved Grimmsnarl but lost prize race {info['hero_prizes_taken']}-6 (Turn {info['turns']})."
                )
        elif info["opp_archetype"] == "Alakazam":
            if info["hero_prizes_taken"] >= 4:
                info["detailed_diagnosis"] = (
                    f"ALAKAZAM CLOSE RACE: Lost {info['hero_prizes_taken']}-6 on Turn {info['turns']}."
                )
            else:
                info["detailed_diagnosis"] = (
                    f"ALAKAZAM BENCH SNIPE: Alakazam Dimensional Hand sniped bench to 6 prizes (Hero took {info['hero_prizes_taken']})."
                )
        elif "Crustle" in info["opp_archetype"] or "Stall" in info["opp_archetype"]:
            info["detailed_diagnosis"] = (
                f"CRUSTLE ATTRITION / LOCK: Opponent Crustle walled attacks and traded down prizes ({info['hero_prizes_taken']}-{info['opp_prizes_taken']})."
            )
        elif info["opp_archetype"] == "Lucario Aggro":
            info["detailed_diagnosis"] = (
                f"LUCARIO TEMPO BLITZ: Mega Lucario dealt rapid KOs (Prizes: {info['hero_prizes_taken']}-6)."
            )
        else:
            info["detailed_diagnosis"] = (
                f"GENERAL DEFEAT vs {info['opp_archetype']} (Prizes: {info['hero_prizes_taken']}-{info['opp_prizes_taken']} on Turn {info['turns']})."
            )
    else:
        info["detailed_diagnosis"] = (
            f"VICTORY vs {info['opp_archetype']} ({info['hero_prizes_taken']}-{info['opp_prizes_taken']} on Turn {info['turns']})."
        )

    return info


def main():
    card_map = load_card_map()
    out_dir = ROOT / "data" / "replays" / str(SUB_ID)
    meta_path = out_dir / "episodes_metadata.json"
    episodes = json.loads(meta_path.read_text())
    episodes_sorted = sorted(episodes, key=lambda x: x.get("id", 0))

    matches = []
    wins = 0
    losses = 0
    ties = 0

    seat0_w, seat0_l = 0, 0
    seat1_w, seat1_l = 0, 0

    archetype_stats = defaultdict(
        lambda: {
            "wins": 0,
            "losses": 0,
            "ties": 0,
            "games": 0,
            "elo_delta": 0.0,
            "seat0_w": 0,
            "seat0_l": 0,
            "seat1_w": 0,
            "seat1_l": 0,
        }
    )

    losses_detail = []
    wins_detail = []

    initial_rating = episodes_sorted[0]["agents"][0].get("initialScore") or 600.0
    latest_rating = None

    for ep in episodes_sorted:
        ep_id = ep["id"]
        agents = ep.get("agents", [])

        hero_seat = next((i for i, a in enumerate(agents) if a.get("submissionId") == SUB_ID), 0)
        opp_seat = 1 - hero_seat

        hero_ag = agents[hero_seat]
        opp_ag = agents[opp_seat]

        hero_reward = hero_ag.get("reward")
        opp_reward = opp_ag.get("reward")

        hero_init = hero_ag.get("initialScore") or 0.0
        hero_upd = hero_ag.get("updatedScore") or hero_init
        opp_init = opp_ag.get("initialScore") or 0.0
        opp_upd = opp_ag.get("updatedScore") or opp_init
        opp_sub = opp_ag.get("submissionId")

        latest_rating = hero_upd
        elo_delta = hero_upd - hero_init

        won = (hero_reward is not None and hero_reward > 0)
        lost = (hero_reward is not None and hero_reward < 0) or (hero_ag.get("status") == "ERROR")
        tied = not won and not lost
        outcome = "WIN" if won else ("LOSS" if lost else "TIE")

        rp_file = out_dir / f"episode-{ep_id}-replay.json"
        if not rp_file.exists():
            rp_file = out_dir / f"{ep_id}.json"

        deep = parse_detailed_game(rp_file, hero_seat, card_map) if rp_file.exists() else {}
        opp_arch = deep.get("opp_archetype", "Unknown")

        rec = {
            "episode_id": ep_id,
            "hero_seat": hero_seat,
            "hero_first": deep.get("hero_first", False),
            "outcome": outcome,
            "elo_delta": elo_delta,
            "hero_init": hero_init,
            "hero_upd": hero_upd,
            "opp_init": opp_init,
            "opp_upd": opp_upd,
            "opp_sub": opp_sub,
            "opp_arch": opp_arch,
            "turns": deep.get("turns", 0),
            "hero_prizes": deep.get("hero_prizes_taken", 0),
            "opp_prizes": deep.get("opp_prizes_taken", 0),
            "hero_opening_active": deep.get("hero_opening_active"),
            "hero_opening_bench": deep.get("hero_opening_bench", []),
            "opp_opening_active": deep.get("opp_opening_active"),
            "opp_opening_bench": deep.get("opp_opening_bench", []),
            "hero_evolutions": dict(deep.get("hero_evolutions", {})),
            "diagnosis": deep.get("detailed_diagnosis", ""),
            "turn_snapshots": deep.get("turn_snapshots", {}),
            "prizes_rem_hero": deep.get("hero_final_prizes_remaining", 6),
            "prizes_rem_opp": deep.get("opp_final_prizes_remaining", 6),
        }
        matches.append(rec)

        st = archetype_stats[opp_arch]
        st["games"] += 1
        st["elo_delta"] += elo_delta

        if won:
            wins += 1
            st["wins"] += 1
            wins_detail.append(rec)
            if hero_seat == 0:
                seat0_w += 1
                st["seat0_w"] += 1
            else:
                seat1_w += 1
                st["seat1_w"] += 1
        elif lost:
            losses += 1
            st["losses"] += 1
            losses_detail.append(rec)
            if hero_seat == 0:
                seat0_l += 1
                st["seat0_l"] += 1
            else:
                seat1_l += 1
                st["seat1_l"] += 1
        else:
            ties += 1
            st["ties"] += 1

    total_games = len(matches)
    win_rate = (wins / total_games * 100) if total_games > 0 else 0.0
    s0_games = seat0_w + seat0_l
    s1_games = seat1_w + seat1_l
    s0_wr = (seat0_w / s0_games * 100) if s0_games > 0 else 0.0
    s1_wr = (seat1_w / s1_games * 100) if s1_games > 0 else 0.0

    print("=" * 110)
    print(f"MASTER V1 (#55283588) COMPLETE FORENSIC REPORT ({total_games} GAMES)")
    print("=" * 110)
    print(
        f"Total Record: {wins} Wins / {losses} Losses / {ties} Ties ({win_rate:.1f}%) | Elo: {initial_rating:.1f} -> {latest_rating:.1f} (Net: {latest_rating - initial_rating:+.1f})"
    )
    print(
        f"Seat 0 (1st): {seat0_w}/{s0_games} ({s0_wr:.1f}%) | Seat 1 (2nd): {seat1_w}/{s1_games} ({s1_wr:.1f}%) | Structural Gap: {s0_wr - s1_wr:+.1f}%"
    )

    print("\n" + "-" * 110)
    print(
        f"{'Opponent Archetype':<24} | {'Games':<5} | {'Record':<8} | {'Win %':<7} | {'Seat0 (W-L)':<12} | {'Seat1 (W-L)':<12} | {'Net Elo':<8}"
    )
    print("-" * 110)
    for arch, st in sorted(archetype_stats.items(), key=lambda x: x[1]["games"], reverse=True):
        wr = (st["wins"] / st["games"] * 100) if st["games"] > 0 else 0.0
        rec_str = f"{st['wins']}-{st['losses']}"
        s0_str = f"{st['seat0_w']}-{st['seat0_l']}"
        s1_str = f"{st['seat1_w']}-{st['seat1_l']}"
        print(
            f"{arch:<24} | {st['games']:<5} | {rec_str:<8} | {wr:>5.1f}% | {s0_str:<12} | {s1_str:<12} | {st['elo_delta']:>+7.1f}"
        )

    print("\n" + "=" * 110)
    print(f"DEEP DIVE ON ALL 18 LOSSES")
    print("=" * 110)
    for idx, l in enumerate(losses_detail, 1):
        print(
            f"\n[LOSS #{idx:02d}] Episode {l['episode_id']} | Seat {l['hero_seat']} (1st={l['hero_first']}) vs {l['opp_arch']} (Opp Elo: {l['opp_init']:.1f}, Sub: {l['opp_sub']})"
        )
        print(
            f"  Score/Delta: {l['elo_delta']:+.1f} | Duration: {l['turns']} turns | Prizes: Hero {l['hero_prizes']} - Opp {l['opp_prizes']}"
        )
        print(
            f"  Opening Board: Hero Active = {l['hero_opening_active']}, Hero Bench = {l['hero_opening_bench']} vs Opp Active = {l['opp_opening_active']}, Opp Bench = {l['opp_opening_bench']}"
        )
        print(f"  Evolutions Achieved: {l['hero_evolutions']}")
        print(f"  Tactical Diagnosis: {l['diagnosis']}")

        # Print turn 1-5 progression snapshots
        snaps = l["turn_snapshots"]
        if snaps:
            print("  Turn-by-turn trace:")
            for t_num in sorted(snaps.keys())[:6]:
                sn = snaps[t_num]
                print(
                    f"    Turn {t_num:02d}: Active={sn['hero_active']} (Bench={sn['hero_bench']}) | OppActive={sn['opp_active']} | Prizes Rem: Hero {sn['hero_prizes_rem']} vs Opp {sn['opp_prizes_rem']}"
                )

    # Save output
    (out_dir / "master_v1_forensic_report.json").write_text(
        json.dumps(
            {
                "sub_id": SUB_ID,
                "summary": {
                    "total_games": total_games,
                    "wins": wins,
                    "losses": losses,
                    "win_rate": win_rate,
                    "initial_rating": initial_rating,
                    "latest_rating": latest_rating,
                    "net_elo": latest_rating - initial_rating,
                    "seat0_wr": s0_wr,
                    "seat1_wr": s1_wr,
                },
                "archetypes": dict(archetype_stats),
                "losses": losses_detail,
                "wins": wins_detail,
            },
            indent=2,
        )
    )
    print(f"\nSaved complete forensic report to {out_dir / 'master_v1_forensic_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
