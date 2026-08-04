#!/usr/bin/env python3
"""Full match breakdown for the active submissions (55189662 and 55189658)."""

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
        if any(w in name.lower() for w in ["energy", "ultra ball", "nest ball", "professor", "boss", "ionov", "arven", "switch", "super rod", "rare candy", "buddy-buddy", "earthen", "night stretcher", "technical machine", "supercharged"]):
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


def analyze_sub_full(sub_id: int, label: str):
    card_map = load_card_map()
    sub_dir = ROOT / "data" / "replays" / str(sub_id)
    meta_path = sub_dir / "episodes_metadata.json"
    episodes = json.loads(meta_path.read_text())
    episodes_chronological = list(reversed(episodes))
    
    print(f"\n{'='*100}")
    print(f"SUBMISSION {sub_id}: {label}")
    print(f"{'='*100}")
    print(f"Total Games Played: {len(episodes_chronological)}")
    
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
        
        # Step analysis
        first_player = None
        turn_snaps = []
        action_log = []
        
        for s_idx, step in enumerate(steps):
            # Record action
            if len(step) > our_idx and step[our_idx].get("action") is not None:
                act = step[our_idx]["action"]
                # action_log.append((s_idx, "US", act))
            if len(step) > opp_idx and step[opp_idx].get("action") is not None:
                act = step[opp_idx]["action"]
                # action_log.append((s_idx, "OPP", act))
                
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
                        
                        if not turn_snaps or turn_snaps[-1]["turn"] != t or (seat == our_idx and not turn_snaps[-1].get("us_hand_names")):
                            snap = {
                                "turn": t,
                                "step": s_idx,
                                "us_active": card_map.get(us_active.get("id"), "None") if us_active else "None",
                                "us_active_hp": f"{us_active.get('hp', 0)}/{us_active.get('maxHp', 0)}" if us_active else "0/0",
                                "us_active_energy": [card_map.get(e.get("id"), "E") for e in us_active.get("energies", [])] if us_active else [],
                                "us_bench": [(card_map.get(b.get("id"), str(b.get("id"))), [card_map.get(e.get("id"), "E") for e in b.get("energies", [])]) for b in us_bench],
                                "us_prizes_left": len(us_p.get("prize", [])),
                                "us_deck_left": us_p.get("deckCount", 0),
                                "us_hand_names": hand_names,
                                "opp_active": card_map.get(opp_active.get("id"), "None") if opp_active else "None",
                                "opp_active_hp": f"{opp_active.get('hp', 0)}/{opp_active.get('maxHp', 0)}" if opp_active else "0/0",
                                "opp_active_energy": [card_map.get(e.get("id"), "E") for e in opp_active.get("energies", [])] if opp_active else [],
                                "opp_bench": [(card_map.get(b.get("id"), str(b.get("id"))), [card_map.get(e.get("id"), "E") for e in b.get("energies", [])]) for b in opp_bench],
                                "opp_prizes_left": len(opp_p.get("prize", [])),
                                "opp_deck_left": opp_p.get("deckCount", 0),
                            }
                            if turn_snaps and turn_snaps[-1]["turn"] == t:
                                turn_snaps[-1] = snap
                            else:
                                turn_snaps.append(snap)

        res_str = "WIN " if won else "LOSS"
        our_elo_s = f"{our_upd:.1f}" if our_upd is not None else "N/A"
        opp_elo_s = f"{opp_init:.1f}" if opp_init is not None else "N/A"
        went_first_s = "Went 1st" if first_player == our_idx else "Went 2nd"
        
        final_snap = turn_snaps[-1] if turn_snaps else {}
        our_prizes_taken = 6 - final_snap.get("us_prizes_left", 6)
        opp_prizes_taken = 6 - final_snap.get("opp_prizes_left", 6)
        total_turns = final_snap.get("turn", 0)
        
        print(f"\n--------------------------------------------------------------------------------")
        print(f"Game #{idx:02d} | Episode {ep_id} | {res_str} | ELO: {our_init:.1f} -> {our_elo_s} ({delta:+5.1f})")
        print(f"Opponent: {opp_name} (Sub {opp_sub}, ELO {opp_elo_s}) | Archetype: {opp_arch}")
        print(f"Seat: Seat {our_idx} ({went_first_s}) | Turns: {total_turns} | Final Prizes: Us {our_prizes_taken}/6 - Opp {opp_prizes_taken}/6")
        
        print(f"\nStep-by-Step Turn Log:")
        for snap in turn_snaps:
            bench_str = ", ".join([f"{b[0]}({len(b[1])}E)" for b in snap['us_bench']]) or "None"
            opp_bench_str = ", ".join([f"{b[0]}({len(b[1])}E)" for b in snap['opp_bench']]) or "None"
            hand_str = ", ".join(snap['us_hand_names']) if snap['us_hand_names'] else "Unknown/Hidden"
            print(f"  [T{snap['turn']:02d}] US:  Active: {snap['us_active']} (HP {snap['us_active_hp']}, {len(snap['us_active_energy'])}E) | Bench: [{bench_str}] | Prizes: {6-snap['us_prizes_left']}/6 | Deck: {snap['us_deck_left']}")
            print(f"         Hand: [{hand_str}]")
            print(f"         OPP: Active: {snap['opp_active']} (HP {snap['opp_active_hp']}, {len(snap['opp_active_energy'])}E) | Bench: [{opp_bench_str}] | Prizes: {6-snap['opp_prizes_left']}/6 | Deck: {snap['opp_deck_left']}")


if __name__ == "__main__":
    analyze_sub_full(55189662, "Grimmsnarl Gen-5 Challenger (Active Sub 1)")
    analyze_sub_full(55189658, "Grimmsnarl 5k Reference Proper (Active Sub 2)")
