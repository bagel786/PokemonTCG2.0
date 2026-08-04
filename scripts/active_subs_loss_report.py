#!/usr/bin/env python3
"""Targeted loss analysis for the two active submissions:
- 55189662: Grimmsnarl Gen-5 Challenger
- 55189658: Grimmsnarl 5k Reference Proper
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
        if any(w in name.lower() for w in ["energy", "ultra ball", "nest ball", "professor", "boss", "ionov", "arven", "switch", "super rod", "rare candy", "buddy-buddy", "earthen", "night stretcher", "technical machine", "supercharged", "poké pad", "dusk ball"]):
            continue
        key_mons.append(f"{name} x{cnt}")
    
    joined = " ".join(names).lower()
    if "grimmsnarl" in joined or "morgrem" in joined or "impidimp" in joined:
        return f"Grimmsnarl / Froslass [{', '.join(key_mons[:2])}]"
    if "lucario" in joined:
        return f"Lucario Aggro [{', '.join(key_mons[:2])}]"
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
    if "crustle" in joined or "dwebble" in joined:
        return f"Crustle Stall [{', '.join(key_mons[:2])}]"
    if "snorlax" in joined or "phantump" in joined:
        return f"Stall / Control [{', '.join(key_mons[:2])}]"
    if "gholdengo" in joined:
        return f"Gholdengo ex [{', '.join(key_mons[:2])}]"
    if "archaludon" in joined or "duraludon" in joined:
        return f"Archaludon ex [{', '.join(key_mons[:2])}]"
    if "regidrago" in joined:
        return f"Regidrago VSTAR [{', '.join(key_mons[:2])}]"
        
    return f"Custom [{', '.join(key_mons[:2])}]"


def analyze_active_sub(sub_id: int, label: str):
    card_map = load_card_map()
    sub_dir = ROOT / "data" / "replays" / str(sub_id)
    meta_path = sub_dir / "episodes_metadata.json"
    episodes = json.loads(meta_path.read_text())
    episodes_chronological = list(reversed(episodes))
    
    print(f"\n{'='*100}")
    print(f"SUBMISSION {sub_id}: {label}")
    print(f"{'='*100}")
    print(f"Total Matches: {len(episodes_chronological)}")
    
    wins = 0
    losses = 0
    ties = 0
    
    seat0_w, seat0_l = 0, 0
    seat1_w, seat1_l = 0, 0
    
    loss_list = []
    win_list = []
    
    for idx, ep in enumerate(episodes_chronological, 1):
        ep_id = ep["id"]
        agents = ep.get("agents", [])
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
        
        if won:
            wins += 1
            if our_idx == 0:
                seat0_w += 1
            else:
                seat1_w += 1
        elif lost:
            losses += 1
            if our_idx == 0:
                seat0_l += 1
            else:
                seat1_l += 1
        else:
            ties += 1
            
        rp_path = sub_dir / f"episode-{ep_id}-replay.json"
        if not rp_path.exists():
            rp_path = sub_dir / f"{ep_id}.json"
            
        rp_data = json.loads(rp_path.read_text()) if rp_path.exists() else {}
        steps = rp_data.get("steps", [])
        info = rp_data.get("info", {})
        team_names = info.get("TeamNames", ["Seat 0", "Seat 1"])
        opp_name = team_names[opp_idx] if len(team_names) > opp_idx else f"Sub {opp_sub}"
        
        opp_deck = steps[1][opp_idx].get("action", []) if len(steps) > 1 and len(steps[1]) > opp_idx else []
        opp_arch = classify_deck(opp_deck, card_map)
        
        # Trace turns
        first_player = None
        turn_snaps = []
        
        # Track active evolutions and energies
        for s_idx, step in enumerate(steps):
            for seat in [0, 1]:
                raw = step[seat].get("observation", {}).get("current")
                if raw and isinstance(raw, dict):
                    if first_player is None:
                        first_player = raw.get("firstPlayer")
                    t = raw.get("turn", 0)
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
                        hand_names = []
                        if seat == our_idx and isinstance(us_hand, list):
                            for h in us_hand:
                                cid = h.get("id") if isinstance(h, dict) else h
                                if cid is not None:
                                    hand_names.append(card_map.get(cid, str(cid)))
                        
                        # Energy counts
                        us_act_e = len(us_active.get("energies", [])) if us_active else 0
                        opp_act_e = len(opp_active.get("energies", [])) if opp_active else 0
                        
                        snap = {
                            "turn": t,
                            "step": s_idx,
                            "us_active": card_map.get(us_active.get("id"), "None") if us_active else "None",
                            "us_active_hp": f"{us_active.get('hp', 0)}/{us_active.get('maxHp', 0)}" if us_active else "0/0",
                            "us_active_energy": us_act_e,
                            "us_bench": [(card_map.get(b.get("id"), str(b.get("id"))), len(b.get("energies", []))) for b in us_bench],
                            "us_prizes_left": len(us_p.get("prize", [])),
                            "us_deck_left": us_p.get("deckCount", 0),
                            "us_hand_names": hand_names,
                            "opp_active": card_map.get(opp_active.get("id"), "None") if opp_active else "None",
                            "opp_active_hp": f"{opp_active.get('hp', 0)}/{opp_active.get('maxHp', 0)}" if opp_active else "0/0",
                            "opp_active_energy": opp_act_e,
                            "opp_bench": [(card_map.get(b.get("id"), str(b.get("id"))), len(b.get("energies", []))) for b in opp_bench],
                            "opp_prizes_left": len(opp_p.get("prize", [])),
                            "opp_deck_left": opp_p.get("deckCount", 0),
                        }
                        if not turn_snaps or turn_snaps[-1]["turn"] != t:
                            turn_snaps.append(snap)
                        elif seat == our_idx and hand_names:
                            turn_snaps[-1]["us_hand_names"] = hand_names
        
        went_first_s = "1st" if first_player == our_idx else "2nd"
        final_snap = turn_snaps[-1] if turn_snaps else {}
        our_prizes = 6 - final_snap.get("us_prizes_left", 6)
        opp_prizes = 6 - final_snap.get("opp_prizes_left", 6)
        total_turns = final_snap.get("turn", 0)
        
        # Analyze opening & loss root cause
        t1_snap = next((s for s in turn_snaps if s["turn"] == 1), turn_snaps[0] if turn_snaps else {})
        t1_hand = t1_snap.get("us_hand_names", [])
        
        # Check evolutions reached
        all_us_mons = set()
        for s in turn_snaps:
            if s["us_active"] != "None":
                all_us_mons.add(s["us_active"])
            for b in s["us_bench"]:
                all_us_mons.add(b[0])
                
        evolved_morgrem = "Marnie's Morgrem" in all_us_mons
        evolved_grimmsnarl = "Marnie's Grimmsnarl ex" in all_us_mons
        evolved_froslass = "Froslass" in all_us_mons
        
        match_info = {
            "index": idx,
            "ep_id": ep_id,
            "won": won,
            "lost": lost,
            "our_init": our_init,
            "our_upd": our_upd,
            "delta": delta,
            "opp_name": opp_name,
            "opp_sub": opp_sub,
            "opp_elo": opp_init,
            "opp_arch": opp_arch,
            "seat": f"Seat {our_idx} ({went_first_s})",
            "total_turns": total_turns,
            "our_prizes": our_prizes,
            "opp_prizes": opp_prizes,
            "opening_active": t1_snap.get("us_active", "None"),
            "opening_bench": [b[0] for b in t1_snap.get("us_bench", [])],
            "opening_hand": t1_hand,
            "evolved_morgrem": evolved_morgrem,
            "evolved_grimmsnarl": evolved_grimmsnarl,
            "evolved_froslass": evolved_froslass,
            "turn_snaps": turn_snaps,
        }
        
        if won:
            win_list.append(match_info)
        elif lost:
            # Diagnose loss
            # 1. Donk (<= 3 turns, wiped out)
            if total_turns <= 3 and final_snap.get("us_active") == "None" and len(final_snap.get("us_bench", [])) == 0:
                match_info["loss_type"] = "BAD_LUCK_DONK"
                match_info["verdict"] = "Bad Luck (Turn 1-2 Wipeout / Lone Mon Knockout)"
                match_info["explanation"] = f"Opened lone {t1_snap.get('us_active')} with 0 benched Pokemon. KO'd on Turn {total_turns} before setup could start."
            # 2. Deckout
            elif final_snap.get("us_deck_left") == 0:
                match_info["loss_type"] = "DECKOUT"
                match_info["verdict"] = "Outplayed / Resource Exhaustion (Deckout)"
                match_info["explanation"] = f"Ran out of cards against {opp_arch} on Turn {total_turns}."
            # 3. Severe Brick / Lockout (0 prizes, no evolutions)
            elif our_prizes == 0 and not (evolved_morgrem or evolved_grimmsnarl or evolved_froslass):
                match_info["loss_type"] = "BAD_LUCK_SETUP_BRICK"
                match_info["verdict"] = "Bad Luck (Severe Setup Stall / Zero Evolutions Drawn)"
                match_info["explanation"] = f"Never drew/evolved Morgrem, Grimmsnarl ex, or Froslass across {total_turns} turns. 0 prizes taken."
            # 4. Outplayed in Prize Race
            elif opp_prizes >= 5 and our_prizes <= 2:
                match_info["loss_type"] = "OUTPLAYED_TEMPO_LOSS"
                match_info["verdict"] = "Outplayed / Tempo Collapse (Lost Prize Race Heavily)"
                match_info["explanation"] = f"Opponent took prizes much faster ({our_prizes}-6) over {total_turns} turns. Evolutions reached: Grimm={evolved_grimmsnarl}, Froslass={evolved_froslass}."
            # 5. Close Game
            elif our_prizes >= 4:
                match_info["loss_type"] = "CLOSE_RACE_ENDGAME"
                match_info["verdict"] = "Close Game (Endgame Micro-play / Prize Exchange)"
                match_info["explanation"] = f"Very close {our_prizes}-6 prize exchange over {total_turns} turns against {opp_arch}."
            else:
                match_info["loss_type"] = "TACTICAL_EXTINCTION"
                match_info["verdict"] = "Outplayed / Midgame Bench Extinction"
                match_info["explanation"] = f"Board wiped on Turn {total_turns} with score {our_prizes}-{opp_prizes}."
                
            loss_list.append(match_info)

    print(f"\nOVERALL RECORD: {wins}W - {losses}L (Winrate: {wins/max(1, len(episodes_chronological)):.1%})")
    print(f"Seat 0 (Going 1st/2nd): {seat0_w}W - {seat0_l}L ({seat0_w/max(1, seat0_w+seat0_l):.1%})")
    print(f"Seat 1 (Going 1st/2nd): {seat1_w}W - {seat1_l}L ({seat1_w/max(1, seat1_w+seat1_l):.1%})")
    
    print(f"\n{'='*90}")
    print(f"ALL LOSSES ({len(loss_list)} Total Losses):")
    print(f"{'='*90}")
    
    for l in loss_list:
        print(f"\n[Game #{l['index']}] Episode {l['ep_id']} | ELO: {l['our_init']:.1f} -> {l['our_upd']:.1f} (Delta: {l['delta']:+5.1f}) | {l['seat']}")
        print(f"  Opponent: {l['opp_name']} (Sub {l['opp_sub']}, ELO {l['opp_elo']:.1f}) | Deck: {l['opp_arch']}")
        print(f"  Result: Score Us {l['our_prizes']}/6 vs Opp {l['opp_prizes']}/6 ({l['total_turns']} turns)")
        print(f"  Opening Board: Active = {l['opening_active']} | Bench = {l['opening_bench']}")
        print(f"  Opening Hand: {l['opening_hand']}")
        print(f"  Evolutions Reached: Morgrem={l['evolved_morgrem']}, Grimmsnarl ex={l['evolved_grimmsnarl']}, Froslass={l['evolved_froslass']}")
        print(f"  ==> VERDICT: {l['verdict']}")
        print(f"      {l['explanation']}")
        print(f"  Turn Progression Summary:")
        for t in l["turn_snaps"][:8]:
            bench_s = ", ".join([f"{b[0]}({b[1]}E)" for b in t['us_bench']]) or "Empty"
            opp_bench_s = ", ".join([f"{b[0]}({b[1]}E)" for b in t['opp_bench']]) or "Empty"
            print(f"    T{t['turn']:02d}: US [{t['us_active']} ({t['us_active_hp']}, {t['us_active_energy']}E), Bench: {bench_s}] | OPP [{t['opp_active']} ({t['opp_active_hp']}, {t['opp_active_energy']}E), Bench: {opp_bench_s}] (Prizes: {6-t['us_prizes_left']}-{6-t['opp_prizes_left']})")


if __name__ == "__main__":
    analyze_active_sub(55189662, "Grimmsnarl Gen-5 Challenger (Active Sub 1)")
    analyze_active_sub(55189658, "Grimmsnarl 5k Reference Proper (Active Sub 2)")
