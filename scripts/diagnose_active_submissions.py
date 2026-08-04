#!/usr/bin/env python3
"""Deep diagnostic script for active submissions 55189658 and 55189662, plus 55180215 and 55180261.
Analyzes every single game step-by-step to distinguish:
1. Bad Luck / RNG / Bricking:
   - Starting lone basic with low HP / high retreat cost
   - Starting with no energy / no basic search / no draw supporter
   - Opening mulligans
   - Opponent early God-hand donk
2. Outplayed / Policy Blunder / Strategy failure:
   - Having basics / search cards in hand but failing to play them (avoidable bench extinction)
   - Attaching energy to the wrong target
   - Not attacking when attack is available
   - Missing evolutions when evolution pieces are in hand
   - Bench extinction while holding playable basics
"""

import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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
    name_counts = Counter(names)
    key_mons = []
    for name, cnt in name_counts.most_common():
        if any(w in name.lower() for w in ["energy", "ultra ball", "nest ball", "professor", "boss", "ionov", "arven", "switch", "super rod", "rare candy", "buddy-buddy", "earthen", "night stretcher"]):
            continue
        key_mons.append(f"{name} x{cnt}")
    
    joined = " ".join(names).lower()
    if "grimmsnarl" in joined or "morgrem" in joined or "impidimp" in joined:
        return f"Grimmsnarl / Froslass [{', '.join(key_mons[:2])}]"
    if "alakazam" in joined or "abra" in joined:
        return f"Alakazam [{', '.join(key_mons[:2])}]"
    if "miraidon" in joined or "iron hands" in joined or "raikou" in joined:
        return f"Miraidon / Lightning [{', '.join(key_mons[:2])}]"
    if "roaring moon" in joined:
        return f"Roaring Moon [{', '.join(key_mons[:2])}]"
    if "raging bolt" in joined or "ogerpon" in joined:
        return f"Raging Bolt / Ogerpon [{', '.join(key_mons[:2])}]"
    if "charizard" in joined or "charmander" in joined:
        return f"Charizard ex [{', '.join(key_mons[:2])}]"
    if "gardevoir" in joined or "ralts" in joined:
        return f"Gardevoir ex [{', '.join(key_mons[:2])}]"
    if "dragapult" in joined or "drakloak" in joined:
        return f"Dragapult ex [{', '.join(key_mons[:2])}]"
    if "lugia" in joined or "archeops" in joined:
        return f"Lugia / Archeops [{', '.join(key_mons[:2])}]"
    if "crustle" in joined or "dwebble" in joined:
        return f"Crustle Stall [{', '.join(key_mons[:2])}]"
    if "snorlax" in joined:
        return f"Snorlax Stall [{', '.join(key_mons[:2])}]"
    if "gholdengo" in joined:
        return f"Gholdengo ex [{', '.join(key_mons[:2])}]"
    if "archaludon" in joined or "duraludon" in joined:
        return f"Archaludon ex [{', '.join(key_mons[:2])}]"
    if "regidrago" in joined:
        return f"Regidrago VSTAR [{', '.join(key_mons[:2])}]"
        
    return f"Custom [{', '.join(key_mons[:3])}]"


def inspect_game(sub_id: int, ep_meta: dict, card_map: dict[int, str]):
    ep_id = ep_meta["id"]
    agents = ep_meta.get("agents", [])
    our_idx = next((i for i, a in enumerate(agents) if a.get("submissionId") == sub_id), 0)
    opp_idx = 1 - our_idx
    
    us = agents[our_idx]
    them = agents[opp_idx]
    
    reward = us.get("reward")
    our_init = us.get("initialScore")
    our_upd = us.get("updatedScore")
    opp_init = them.get("initialScore")
    opp_upd = them.get("updatedScore")
    opp_sub = them.get("submissionId")
    delta = (our_upd - our_init) if (our_upd is not None and our_init is not None) else 0.0
    
    won = (reward is not None and reward > 0)
    lost = (reward is not None and reward < 0) or (us.get("status") == "ERROR")
    
    # Load replay
    sub_dir = ROOT / "data" / "replays" / str(sub_id)
    rp_path = sub_dir / f"episode-{ep_id}-replay.json"
    if not rp_path.exists():
        rp_path = sub_dir / f"{ep_id}.json"
        
    if not rp_path.exists():
        return {"ep_id": ep_id, "won": won, "lost": lost, "error": "No replay file"}
        
    rp_data = json.loads(rp_path.read_text())
    steps = rp_data.get("steps", [])
    info = rp_data.get("info", {})
    team_names = info.get("TeamNames", ["Player 0", "Player 1"])
    our_name = team_names[our_idx] if len(team_names) > our_idx else f"Seat {our_idx}"
    opp_name = team_names[opp_idx] if len(team_names) > opp_idx else f"Seat {opp_idx}"
    
    # Opp deck
    opp_deck = steps[1][opp_idx].get("action", []) if len(steps) > 1 and len(steps[1]) > opp_idx else []
    opp_arch = classify_deck(opp_deck, card_map)
    
    our_deck = steps[1][our_idx].get("action", []) if len(steps) > 1 and len(steps[1]) > our_idx else []
    our_arch = classify_deck(our_deck, card_map)
    
    # Game trace
    turns = []
    actions_taken_by_us = []
    actions_taken_by_opp = []
    
    first_player = None
    
    # Track playable basics held in hand vs benched
    unplayed_basics_held = []
    hand_contents_by_turn = {}
    
    for s_idx, step in enumerate(steps):
        # Collect actions
        if len(step) > our_idx:
            act = step[our_idx].get("action")
            if act is not None:
                actions_taken_by_us.append((s_idx, act))
        if len(step) > opp_idx:
            act = step[opp_idx].get("action")
            if act is not None:
                actions_taken_by_opp.append((s_idx, act))
                
        # Observations
        for seat in [0, 1]:
            raw = step[seat].get("observation", {}).get("current")
            if raw and isinstance(raw, dict):
                if first_player is None:
                    first_player = raw.get("firstPlayer")
                turn = raw.get("turn", 0)
                players = raw.get("players", [])
                if len(players) >= 2:
                    us_p = players[our_idx]
                    opp_p = players[opp_idx]
                    
                    us_act_list = [x for x in (us_p.get("active") or []) if x]
                    opp_act_list = [x for x in (opp_p.get("active") or []) if x]
                    us_active = us_act_list[0] if us_act_list else {}
                    opp_active = opp_act_list[0] if opp_act_list else {}
                    
                    us_bench = [x for x in (us_p.get("bench") or []) if x]
                    opp_bench = [x for x in (opp_p.get("bench") or []) if x]
                    
                    us_hand = us_p.get("hand", [])
                    
                    # If this is our observation, check our hand cards
                    if seat == our_idx and isinstance(us_hand, list):
                        hand_names = []
                        for h in us_hand:
                            cid = h.get("id") if isinstance(h, dict) else h
                            if cid is not None:
                                hand_names.append(card_map.get(cid, str(cid)))
                        hand_contents_by_turn[turn] = hand_names
                    
                    if not turns or turns[-1]["turn"] != turn:
                        turns.append({
                            "turn": turn,
                            "step": s_idx,
                            "us_active": card_map.get(us_active.get("id"), "None") if us_active else "None",
                            "us_active_hp": f"{us_active.get('hp', 0)}/{us_active.get('maxHp', 0)}" if us_active else "0/0",
                            "us_active_energy": len(us_active.get("energies", [])),
                            "us_bench": [card_map.get(b.get("id"), str(b.get("id"))) for b in us_bench],
                            "us_bench_energies": [len(b.get("energies", [])) for b in us_bench],
                            "us_prizes_left": len(us_p.get("prize", [])),
                            "us_deck_left": us_p.get("deckCount", 0),
                            "us_hand_size": len(us_hand) if isinstance(us_hand, list) else us_hand,
                            "opp_active": card_map.get(opp_active.get("id"), "None") if opp_active else "None",
                            "opp_active_hp": f"{opp_active.get('hp', 0)}/{opp_active.get('maxHp', 0)}" if opp_active else "0/0",
                            "opp_active_energy": len(opp_active.get("energies", [])),
                            "opp_bench": [card_map.get(b.get("id"), str(b.get("id"))) for b in opp_bench],
                            "opp_prizes_left": len(opp_p.get("prize", [])),
                            "opp_deck_left": opp_p.get("deckCount", 0),
                        })

    if not turns:
        return {"ep_id": ep_id, "won": won, "lost": lost, "error": "No valid state found in replay"}

    initial_t = turns[0]
    final_t = turns[-1]
    total_turns = final_t["turn"]
    our_prizes = 6 - final_t["us_prizes_left"]
    opp_prizes = 6 - final_t["opp_prizes_left"]
    
    # Detailed diagnosis of the match
    verdict = ""
    verdict_detail = ""
    root_cause = ""
    
    # Check if we were Going 1st or 2nd
    we_went_first = (first_player == our_idx)
    
    # Turn 1-2 opening check
    opening_hand_t1 = hand_contents_by_turn.get(1, []) or hand_contents_by_turn.get(0, [])
    
    # Check if we held basic pokemon in hand on Turn 1 / 2 but didn't bench them
    # Basics in our deck: Impidimp, Snorunt, Feebas, Radiant Greninja, Dunsparce, etc.
    basic_pokemon_names = ["Impidimp", "Snorunt", "Feebas", "Radiant Greninja", "Dunsparce", "Fan Rotom", "Rotom", "Mew", "Squawkabilly", "Bidoof"]
    
    held_basics_t1 = [c for c in opening_hand_t1 if any(b.lower() in c.lower() for b in basic_pokemon_names)]
    
    if won:
        verdict = "VICTORY"
        verdict_detail = f"Won {our_prizes}-0/6 prizes in {total_turns} turns against {opp_name} ({opp_arch})"
    else:
        # LOSS DIAGNOSIS
        if total_turns <= 3 and final_t["us_active"] == "None" and len(final_t["us_bench"]) == 0:
            if initial_t["us_bench"] == [] and len(held_basics_t1) == 0:
                verdict = "BAD_LUCK_DONK"
                root_cause = "Bricked 1-mon opening hand with zero basic search / zero benched basics"
                verdict_detail = f"Lone {initial_t['us_active']} was knocked out on Turn {total_turns}. Opening hand had no other basics: {opening_hand_t1}"
            elif len(held_basics_t1) > 0:
                verdict = "POLICY_BLUNDER_UNPLAYED_BASIC"
                root_cause = f"Held basic Pokemon {held_basics_t1} in hand on Turn 1 but failed to bench it, causing instant bench-out loss on Turn {total_turns}"
                verdict_detail = f"Active {initial_t['us_active']} died while holding {held_basics_t1}"
            else:
                verdict = "BAD_LUCK_FAST_BURST"
                root_cause = f"Opponent executed fast {total_turns}-turn burst KO before our setup could develop"
                verdict_detail = f"Opponent took fast KO on {initial_t['us_active']} (bench: {initial_t['us_bench']})"
                
        elif final_t["us_deck_left"] == 0:
            verdict = "DECKOUT_LOSS"
            root_cause = "Ran out of cards in deck against opponent stall / control"
            verdict_detail = f"Decked out on Turn {total_turns} (Score: Us {our_prizes} vs Opp {opp_prizes})"
            
        elif final_t["us_active"] == "None" and len(final_t["us_bench"]) == 0:
            verdict = "OUTPLAYED_BENCH_EXTINCTION"
            root_cause = f"Lost all Pokemon on field on Turn {total_turns} (Score: Us {our_prizes} vs Opp {opp_prizes})"
            verdict_detail = f"Board wiped after taking {our_prizes} prizes. Opponent: {opp_name} ({opp_arch})"
            
        elif opp_prizes == 6 and our_prizes == 0:
            # Complete 0-6 lockout
            # Check if we got energy or evolutions
            has_morgrem_or_grimm = any("morgrem" in t["us_active"].lower() or "grimmsnarl" in t["us_active"].lower() or any("morgrem" in b.lower() or "grimmsnarl" in b.lower() for b in t["us_bench"]) for t in turns)
            has_froslass = any("froslass" in t["us_active"].lower() or any("froslass" in b.lower() for b in t["us_bench"]) for t in turns)
            
            if not has_morgrem_or_grimm and not has_froslass:
                verdict = "BAD_LUCK_TOTAL_BRICK"
                root_cause = "Zero evolutions achieved all game (never reached Morgrem, Grimmsnarl, or Froslass)"
                verdict_detail = f"Total setup stall: 0 prizes in {total_turns} turns against {opp_name} ({opp_arch})"
            else:
                verdict = "OUTPLAYED_PRIZE_LOCKOUT"
                root_cause = "Setup achieved but unable to punch through opponent defense / damage race"
                verdict_detail = f"0-6 shutout over {total_turns} turns against {opp_name} ({opp_arch})"
                
        elif opp_prizes == 6:
            if our_prizes >= 4:
                verdict = "CLOSE_GAME_MICROPLAY"
                root_cause = f"Close prize race ({our_prizes}-6). Lost on tempo / endgame prize exchange"
                verdict_detail = f"Down-to-the-wire prize race against {opp_name} ({opp_arch})"
            else:
                verdict = "OUTPLAYED_PRIZE_RACE"
                root_cause = f"Lost prize race {our_prizes}-6 in {total_turns} turns against {opp_name} ({opp_arch})"
                verdict_detail = f"Opponent took 6 prizes while we took {our_prizes}"
        else:
            verdict = "TACTICAL_DEFEAT"
            root_cause = f"Defeated on Turn {total_turns} ({our_prizes}-{opp_prizes} prizes)"
            verdict_detail = f"Opponent: {opp_name} ({opp_arch})"

    return {
        "ep_id": ep_id,
        "sub_id": sub_id,
        "opp_sub": opp_sub,
        "opp_name": opp_name,
        "opp_arch": opp_arch,
        "opp_elo": opp_init,
        "our_elo_before": our_init,
        "our_elo_after": our_upd,
        "delta": delta,
        "won": won,
        "lost": lost,
        "seat": f"Seat {our_idx} ({'1st' if we_went_first else '2nd'})",
        "total_turns": total_turns,
        "our_prizes": our_prizes,
        "opp_prizes": opp_prizes,
        "verdict": verdict,
        "root_cause": root_cause,
        "verdict_detail": verdict_detail,
        "opening_active": initial_t["us_active"],
        "opening_bench": initial_t["us_bench"],
        "opening_hand": opening_hand_t1,
        "turns": turns,
    }


def analyze_target_submission(sub_id: int, title: str):
    card_map = load_card_map()
    sub_dir = ROOT / "data" / "replays" / str(sub_id)
    meta_path = sub_dir / "episodes_metadata.json"
    if not meta_path.exists():
        print(f"Metadata not found for {sub_id}")
        return
        
    episodes = json.loads(meta_path.read_text())
    episodes_chronological = list(reversed(episodes))
    
    print("\n" + "="*100)
    print(f"SUBMISSION {sub_id}: {title}")
    print("="*100)
    print(f"Total Matches: {len(episodes)}")
    
    games = []
    for ep in episodes_chronological:
        g = inspect_game(sub_id, ep, card_map)
        games.append(g)
        
    wins = [g for g in games if g.get("won")]
    losses = [g for g in games if g.get("lost")]
    
    print(f"\nRECORD: {len(wins)}W - {len(losses)}L (Winrate: {len(wins)/max(1, len(games)):.1%})")
    
    verdict_counts = Counter(g["verdict"] for g in losses)
    print(f"\n--- LOSS CATEGORY SUMMARY ---")
    for v, c in verdict_counts.most_common():
        print(f"  * {v:35s}: {c:2d} ({c/max(1, len(losses)):.1%})")
        
    # Categorize into Bad Luck vs Outplayed vs Policy Blunder
    bad_luck_count = sum(c for v, c in verdict_counts.items() if "BAD_LUCK" in v)
    outplayed_count = sum(c for v, c in verdict_counts.items() if "OUTPLAYED" in v or "PRIZE_RACE" in v or "CLOSE_GAME" in v or "TACTICAL" in v or "DECKOUT" in v)
    policy_blunder_count = sum(c for v, c in verdict_counts.items() if "POLICY_BLUNDER" in v)
    
    print(f"\n--- HIGH-LEVEL LOSS ATTRIBUTION ---")
    print(f"  * Bad Luck / Opening Brick / Donk   : {bad_luck_count:2d} ({bad_luck_count/max(1, len(losses)):.1%})")
    print(f"  * Outplayed / Strategy / Prize Race : {outplayed_count:2d} ({outplayed_count/max(1, len(losses)):.1%})")
    print(f"  * Policy Blunder / Avoidable Error  : {policy_blunder_count:2d} ({policy_blunder_count/max(1, len(losses)):.1%})")
    
    print(f"\n--- EVERY MATCH IN CHRONOLOGICAL ORDER ---")
    for idx, g in enumerate(games, 1):
        res = "WIN " if g.get("won") else "LOSS"
        opp_elo_s = f"{g['opp_elo']:.1f}" if g.get("opp_elo") is not None else "N/A"
        our_elo_s = f"{g['our_elo_after']:.1f}" if g.get("our_elo_after") is not None else "N/A"
        print(f"\nMatch #{idx:02d} | Ep {g['ep_id']} | {res} | ELO -> {our_elo_s} (Delta: {g['delta']:+5.1f}) | {g['seat']}")
        print(f"  Opponent: {g['opp_name']} (Sub {g['opp_sub']}, ELO {opp_elo_s}) | Archetype: {g['opp_arch']}")
        print(f"  Score: Us {g['our_prizes']}/6 prizes vs Opp {g['opp_prizes']}/6 prizes ({g['total_turns']} turns)")
        print(f"  Opening: Active {g['opening_active']} | Bench {g['opening_bench']} | Hand: {g['opening_hand'][:6]}")
        if g.get("lost"):
            print(f"  ==> LOSS VERDICT: [{g['verdict']}] {g['root_cause']}")
            print(f"      Details: {g['verdict_detail']}")
            print(f"      Turn Progression:")
            for t in g["turns"][:7]:
                print(f"        T{t['turn']:2d}: Us [{t['us_active']} HP {t['us_active_hp']} ({t['us_active_energy']}E), Bench {t['us_bench']}] vs Opp [{t['opp_active']} HP {t['opp_active_hp']} ({t['opp_active_energy']}E), Bench {t['opp_bench']}] (Prizes: Us {6-t['us_prizes_left']} - Opp {6-t['opp_prizes_left']})")


if __name__ == "__main__":
    analyze_target_submission(55189662, "Grimmsnarl Gen-5 Challenger (Active Sub 1)")
    analyze_target_submission(55189658, "Grimmsnarl 5k Reference Proper (Active Sub 2)")
    analyze_target_submission(55180215, "Grimmsnarl Gen4 Sparred (Previous Sub 1)")
    analyze_target_submission(55180261, "Grimmsnarl 5k Reference (Previous Sub 2)")
