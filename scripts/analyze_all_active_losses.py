#!/usr/bin/env python3
"""Comprehensive analyzer for active submissions (55189658 and 55189662) and previous submissions.
Performs deep-dive game and loss diagnosis: Bad luck / bricking vs Outplayed / policy blunders.
"""

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_card_map() -> dict[int, str]:
    card_map = {}
    for p in [
        ROOT / "freshstart" / "data" / "EN_Card_Data.csv",
        ROOT / "data" / "EN_Card_Data.csv",
    ]:
        if p.exists():
            reader = csv.DictReader(p.read_text(encoding="utf-8-sig").splitlines())
            for row in reader:
                cid = int(row.get("Card ID") or row.get("card_id") or row.get("id") or -1)
                name = row.get("Card Name") or row.get("name") or row.get("Name") or row.get("card_name") or f"Card_{cid}"
                card_map[cid] = name
            break
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
    if "grimmsnarl" in joined or "morgrem" in joined:
        return f"Grimmsnarl/Froslass ({', '.join(key_mons[:2])})"
    if "alakazam" in joined or "abra" in joined:
        return f"Alakazam/Dudunsparce ({', '.join(key_mons[:2])})"
    if "miraidon" in joined or "iron hands" in joined or "raikou" in joined:
        return f"Miraidon/Lightning ({', '.join(key_mons[:2])})"
    if "roaring moon" in joined:
        return f"Roaring Moon ({', '.join(key_mons[:2])})"
    if "raging bolt" in joined or "ogerpon" in joined:
        return f"Raging Bolt/Ogerpon ({', '.join(key_mons[:2])})"
    if "charizard" in joined or "charmander" in joined:
        return f"Charizard ex ({', '.join(key_mons[:2])})"
    if "gardevoir" in joined or "ralts" in joined:
        return f"Gardevoir ex ({', '.join(key_mons[:2])})"
    if "dragapult" in joined or "drakloak" in joined:
        return f"Dragapult ex ({', '.join(key_mons[:2])})"
    if "lugia" in joined or "archeops" in joined:
        return f"Lugia/Archeops ({', '.join(key_mons[:2])})"
    if "crustle" in joined or "dwebble" in joined:
        return f"Crustle Stall ({', '.join(key_mons[:2])})"
    if "snorlax" in joined:
        return f"Snorlax Stall ({', '.join(key_mons[:2])})"
    if "gholdengo" in joined:
        return f"Gholdengo ex ({', '.join(key_mons[:2])})"
    if "archaludon" in joined or "duraludon" in joined:
        return f"Archaludon ex ({', '.join(key_mons[:2])})"
    if "regidrago" in joined:
        return f"Regidrago VSTAR ({', '.join(key_mons[:2])})"
        
    return f"Custom/Other ({', '.join(key_mons[:3])})"


def analyze_loss_details(replay_data: dict, our_seat: int, opp_seat: int, card_map: dict[int, str]):
    steps = replay_data.get("steps", [])
    if not steps:
        return {"loss_type": "NO_STEPS", "details": "Empty replay"}
        
    # Track opening state
    mulligans_us = 0
    mulligans_opp = 0
    
    # We can inspect step 0 / step 1 observations
    first_obs = None
    step_turn_history = []
    
    our_bench_counts = []
    opp_bench_counts = []
    
    our_energy_attachments = 0
    opp_energy_attachments = 0
    
    our_evolutions = []
    opp_evolutions = []
    
    first_player = None
    last_state = None
    
    for s_idx, step in enumerate(steps):
        # check observations
        for seat in [0, 1]:
            raw = step[seat].get("observation", {}).get("current")
            if raw and isinstance(raw, dict):
                last_state = raw
                if first_player is None:
                    first_player = raw.get("firstPlayer")
                
                turn = raw.get("turn", 0)
                players = raw.get("players", [])
                if len(players) >= 2:
                    us_p = players[our_seat]
                    opp_p = players[opp_seat]
                    
                    us_act_list = [x for x in (us_p.get("active") or []) if x]
                    opp_act_list = [x for x in (opp_p.get("active") or []) if x]
                    us_active = us_act_list[0] if us_act_list else {}
                    opp_active = opp_act_list[0] if opp_act_list else {}
                    
                    us_bench = [x for x in (us_p.get("bench") or []) if x]
                    opp_bench = [x for x in (opp_p.get("bench") or []) if x]
                    
                    our_bench_counts.append(len(us_bench))
                    opp_bench_counts.append(len(opp_bench))
                    
                    us_prizes = len(us_p.get("prize", []))
                    opp_prizes = len(opp_p.get("prize", []))
                    
                    us_deck = us_p.get("deckCount", 0)
                    opp_deck = opp_p.get("deckCount", 0)
                    
                    us_hand = us_p.get("hand", [])
                    
                    if not step_turn_history or step_turn_history[-1]["turn"] != turn:
                        step_turn_history.append({
                            "turn": turn,
                            "step": s_idx,
                            "us_active_id": us_active.get("id"),
                            "us_active_name": card_map.get(us_active.get("id"), str(us_active.get("id")) if us_active else "None"),
                            "us_active_hp": us_active.get("hp", 0),
                            "us_active_max_hp": us_active.get("maxHp", 0),
                            "us_active_energies": len(us_active.get("energies", [])),
                            "us_bench": [card_map.get(b.get("id"), str(b.get("id"))) for b in us_bench],
                            "us_prizes_left": us_prizes,
                            "us_deck_left": us_deck,
                            "us_hand_size": len(us_hand) if isinstance(us_hand, list) else us_hand,
                            "opp_active_id": opp_active.get("id"),
                            "opp_active_name": card_map.get(opp_active.get("id"), str(opp_active.get("id")) if opp_active else "None"),
                            "opp_active_hp": opp_active.get("hp", 0),
                            "opp_active_max_hp": opp_active.get("maxHp", 0),
                            "opp_active_energies": len(opp_active.get("energies", [])),
                            "opp_bench": [card_map.get(b.get("id"), str(b.get("id"))) for b in opp_bench],
                            "opp_prizes_left": opp_prizes,
                            "opp_deck_left": opp_deck,
                        })

    # Classify loss reason
    if not step_turn_history:
        return {"loss_type": "UNKNOWN", "prizes_taken": 0, "opp_prizes_taken": 0, "total_turns": 0, "first_player": first_player}

    initial_t = step_turn_history[0]
    final_t = step_turn_history[-1]
    
    total_turns = final_t["turn"]
    our_prizes_taken = 6 - final_t["us_prizes_left"]
    opp_prizes_taken = 6 - final_t["opp_prizes_left"]
    
    loss_category = "OUTPLAYED"
    loss_subcategory = "Standard Prize Race Loss"
    luck_vs_skill = "Skill / Strategy"
    
    # Check for Donk / Turn 1-2 bench extinction
    if total_turns <= 3:
        # Check if our bench was 0 throughout
        if max(our_bench_counts[:10] if len(our_bench_counts) >= 10 else our_bench_counts, default=0) == 0:
            loss_category = "EARLY_BENCH_EXTINCTION_DONK"
            luck_vs_skill = "RNG / Bad Opening (Bricked 1-mon start)"
            loss_subcategory = f"Single Mon KO on Turn {total_turns} (Opened {initial_t['us_active_name']} alone)"
        else:
            loss_category = "EARLY_BENCH_EXTINCTION"
            luck_vs_skill = "Rapid Loss / Fast Wipeout"
            loss_subcategory = f"Wiped out on Turn {total_turns}"
    elif opp_prizes_taken == 6 and our_prizes_taken == 0:
        loss_category = "TOTAL_SHUTOUT_0_6"
        if total_turns <= 6:
            luck_vs_skill = "Major Setup Failure / Severe Brick"
            loss_subcategory = f"Setup Stalled / 0 Prizes by Turn {total_turns}"
        else:
            luck_vs_skill = "Tactical Lock / Ineffective Offense"
            loss_subcategory = f"Complete Lockout (0-6) over {total_turns} turns"
    elif opp_prizes_taken == 6 and our_prizes_taken <= 2:
        loss_category = "HEAVY_PRIZE_LOSS"
        loss_subcategory = f"Losing Prize Race {our_prizes_taken}-6 in {total_turns} turns"
        luck_vs_skill = "Pacing / Momentum Loss"
    elif our_prizes_taken >= 4:
        loss_category = "CLOSE_MATCH_PRIZE_RACE"
        loss_subcategory = f"Narrow Finish {our_prizes_taken}-6 in {total_turns} turns"
        luck_vs_skill = "Endgame Sequencing / Micro-play"
    elif final_t["us_deck_left"] == 0:
        loss_category = "DECKOUT"
        loss_subcategory = f"Decked out on Turn {total_turns}"
        luck_vs_skill = "Resource Management / Stall"
    else:
        loss_category = "EXTINCTION_MIDGAME"
        loss_subcategory = f"Board wiped with empty bench on Turn {total_turns} ({our_prizes_taken}-{opp_prizes_taken} prizes)"
        luck_vs_skill = "Bench Management / Energy Tempo"

    return {
        "loss_category": loss_category,
        "loss_subcategory": loss_subcategory,
        "luck_vs_skill": luck_vs_skill,
        "total_turns": total_turns,
        "our_prizes_taken": our_prizes_taken,
        "opp_prizes_taken": opp_prizes_taken,
        "first_player": "Us (1st)" if first_player == our_seat else "Opponent (1st)",
        "opening_mon": initial_t["us_active_name"],
        "opening_bench": initial_t["us_bench"],
        "max_bench": max(our_bench_counts, default=0),
        "history": step_turn_history,
    }


def analyze_all_subs(sub_ids: list[tuple[int, str]]):
    card_map = load_card_map()
    
    all_summary = {}
    
    for sub_id, sub_label in sub_ids:
        sub_dir = ROOT / "data" / "replays" / str(sub_id)
        meta_path = sub_dir / "episodes_metadata.json"
        if not meta_path.exists():
            print(f"No metadata found for {sub_id} at {meta_path}")
            continue
            
        episodes = json.loads(meta_path.read_text())
        episodes_chronological = list(reversed(episodes))
        
        print(f"\n{'='*100}")
        print(f"SUBMISSION {sub_id}: {sub_label}")
        print(f"{'='*100}")
        print(f"Total Matches: {len(episodes)}")
        
        wins = 0
        losses = 0
        ties = 0
        
        seat0_record = [0, 0] # [W, L]
        seat1_record = [0, 0] # [W, L]
        
        loss_types = Counter()
        luck_vs_skill_counts = Counter()
        opp_archetype_losses = Counter()
        low_elo_losses = [] # Losses to opp < 1000 ELO
        high_elo_losses = [] # Losses to opp >= 1000 ELO
        
        match_details = []
        
        for idx, ep in enumerate(episodes_chronological, 1):
            ep_id = ep["id"]
            agents = ep.get("agents", [])
            our_idx = next((i for i, a in enumerate(agents) if a.get("submissionId") == sub_id), 0)
            opp_idx = 1 - our_idx
            
            us = agents[our_idx] if len(agents) > our_idx else {}
            them = agents[opp_idx] if len(agents) > opp_idx else {}
            
            reward = us.get("reward")
            our_init = us.get("initialScore")
            our_upd = us.get("updatedScore")
            opp_init = them.get("initialScore")
            opp_upd = them.get("updatedScore")
            opp_sub = them.get("submissionId")
            
            won = (reward is not None and reward > 0)
            lost = (reward is not None and reward < 0) or (us.get("status") == "ERROR")
            
            if won:
                wins += 1
                if our_idx == 0:
                    seat0_record[0] += 1
                else:
                    seat1_record[0] += 1
            elif lost:
                losses += 1
                if our_idx == 0:
                    seat0_record[1] += 1
                else:
                    seat1_record[1] += 1
            else:
                ties += 1
                
            delta = (our_upd - our_init) if (our_upd is not None and our_init is not None) else 0.0
            
            # Load replay
            rp_path = sub_dir / f"episode-{ep_id}-replay.json"
            if not rp_path.exists():
                rp_path = sub_dir / f"{ep_id}.json"
                
            rp_data = {}
            if rp_path.exists():
                try:
                    rp_data = json.loads(rp_path.read_text())
                except:
                    pass
                    
            steps = rp_data.get("steps", [])
            info = rp_data.get("info", {})
            team_names = info.get("TeamNames", ["Seat 0", "Seat 1"])
            
            opp_name = team_names[opp_idx] if len(team_names) > opp_idx else f"Sub {opp_sub}"
            our_name = team_names[our_idx] if len(team_names) > our_idx else f"Sub {sub_id}"
            
            opp_deck = steps[1][opp_idx].get("action", []) if len(steps) > 1 and len(steps[1]) > opp_idx else []
            opp_arch = classify_deck(opp_deck, card_map) if opp_deck else "Unknown Archetype"
            
            res_str = "WIN " if won else ("LOSS" if lost else "TIE ")
            
            loss_diag = None
            if lost and rp_data:
                loss_diag = analyze_loss_details(rp_data, our_idx, opp_idx, card_map)
                loss_types[loss_diag["loss_category"]] += 1
                luck_vs_skill_counts[loss_diag["luck_vs_skill"]] += 1
                opp_archetype_losses[opp_arch] += 1
                
                loss_entry = {
                    "episode_id": ep_id,
                    "index": idx,
                    "opp_name": opp_name,
                    "opp_sub": opp_sub,
                    "opp_elo": opp_init,
                    "our_elo_before": our_init,
                    "our_elo_after": our_upd,
                    "delta": delta,
                    "opp_arch": opp_arch,
                    "seat": f"Seat {our_idx} ({'Going 1st' if loss_diag['first_player'].startswith('Us') else 'Going 2nd'})",
                    "diagnosis": loss_diag,
                }
                if opp_init is not None and opp_init < 1000:
                    low_elo_losses.append(loss_entry)
                else:
                    high_elo_losses.append(loss_entry)
                    
            match_details.append({
                "index": idx,
                "ep_id": ep_id,
                "result": res_str,
                "reward": reward,
                "delta": delta,
                "our_elo": our_upd,
                "opp_elo": opp_init,
                "opp_name": opp_name,
                "opp_arch": opp_arch,
                "seat": our_idx,
                "loss_diag": loss_diag
            })

        # Print detailed report for this submission
        winrate = wins / max(1, len(episodes))
        s0_wr = seat0_record[0] / max(1, sum(seat0_record))
        s1_wr = seat1_record[0] / max(1, sum(seat1_record))
        
        print(f"\n--- PERFORMANCE OVERVIEW ---")
        print(f"Overall Record: {wins}W - {losses}L - {ties}T | Winrate: {winrate:.1%}")
        print(f"Seat 0 (Player 1): {seat0_record[0]}W - {seat0_record[1]}L ({s0_wr:.1%} WR) [N={sum(seat0_record)}]")
        print(f"Seat 1 (Player 2): {seat1_record[0]}W - {seat1_record[1]}L ({s1_wr:.1%} WR) [N={sum(seat1_record)}]")
        
        print(f"\n--- LOSS BREAKDOWN BY CATEGORY ---")
        for cat, cnt in loss_types.most_common():
            print(f"  * {cat:30s}: {cnt:2d} ({cnt/max(1, losses):.1%})")
            
        print(f"\n--- LOSS BREAKDOWN BY NATURE (LUCK VS SKILL/TACTICS) ---")
        for nature, cnt in luck_vs_skill_counts.most_common():
            print(f"  * {nature:40s}: {cnt:2d} ({cnt/max(1, losses):.1%})")
            
        print(f"\n--- LOSSES BY OPPONENT ARCHETYPE ---")
        for arch, cnt in opp_archetype_losses.most_common():
            print(f"  * {arch:50s}: {cnt:2d} losses")

        print(f"\n--- LOSSES TO LOW-RATED AGENTS (ELO < 1000) [Total: {len(low_elo_losses)}] ---")
        for l in low_elo_losses:
            diag = l["diagnosis"]
            print(f"\n  [Match #{l['index']}] Episode {l['episode_id']} | Delta: {l['delta']:+5.1f} | Opp: {l['opp_name']} (Sub {l['opp_sub']}, ELO {l['opp_elo']})")
            print(f"    Archetype: {l['opp_arch']}")
            print(f"    Setup: {l['seat']} | Opening: Active {diag['opening_mon']}, Bench {diag['opening_bench']}")
            print(f"    Outcome: {diag['loss_subcategory']} (Score: Us {diag['our_prizes_taken']}/6 vs Opp {diag['opp_prizes_taken']}/6 in {diag['total_turns']} turns)")
            print(f"    Nature: {diag['luck_vs_skill']} [{diag['loss_category']}]")
            
            # Print turn progression
            print("    Turn trace:")
            for te in diag["history"][:8]:
                print(f"      T{te['turn']:2d}: US [{te['us_active_name']} HP {te['us_active_hp']}/{te['us_active_max_hp']}, {te['us_active_energies']}E, Bench {te['us_bench']}, Hand {te['us_hand_size']}] vs OPP [{te['opp_active_name']} HP {te['opp_active_hp']}/{te['opp_active_max_hp']}, {te['opp_active_energies']}E, Bench {te['opp_bench']}] (Prizes: Us {6-te['us_prizes_left']}-Opp {6-te['opp_prizes_left']})")

        print(f"\n--- LOSSES TO HIGH-RATED AGENTS (ELO >= 1000) [Total: {len(high_elo_losses)}] ---")
        for l in high_elo_losses:
            diag = l["diagnosis"]
            print(f"\n  [Match #{l['index']}] Episode {l['episode_id']} | Delta: {l['delta']:+5.1f} | Opp: {l['opp_name']} (Sub {l['opp_sub']}, ELO {l['opp_elo']})")
            print(f"    Archetype: {l['opp_arch']}")
            print(f"    Setup: {l['seat']} | Opening: Active {diag['opening_mon']}, Bench {diag['opening_bench']}")
            print(f"    Outcome: {diag['loss_subcategory']} (Score: Us {diag['our_prizes_taken']}/6 vs Opp {diag['opp_prizes_taken']}/6 in {diag['total_turns']} turns)")
            print(f"    Nature: {diag['luck_vs_skill']} [{diag['loss_category']}]")


if __name__ == "__main__":
    subs_to_analyze = [
        (55189662, "Grimmsnarl Gen-5 Challenger (Active Sub 1)"),
        (55189658, "Grimmsnarl 5k Reference Proper (Active Sub 2)"),
        (55180215, "Grimmsnarl Gen4 Sparred (Previous Sub 1)"),
        (55180261, "Grimmsnarl 5k Reference (Previous Sub 2)"),
        (55171237, "Grimmsnarl Co-Evolution R2 (High Rating Benchmark)"),
        (55171235, "Grimmsnarl 5k Reference (High Rating Benchmark)"),
    ]
    analyze_all_subs(subs_to_analyze)
