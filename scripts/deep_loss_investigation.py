#!/usr/bin/env python3
"""Deep investigation into all loss games for 55180261 (5k ref) and 55180215 (Gen4 sparred)."""

import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def load_cards() -> dict[int, str]:
    card_map = {}
    csv_path = ROOT / "freshstart" / "data" / "EN_Card_Data.csv"
    if csv_path.exists():
        reader = csv.DictReader(csv_path.read_text(encoding="utf-8-sig").splitlines())
        for row in reader:
            cid = int(row.get("card_id") or row.get("id") or row.get("Card ID") or -1)
            name = row.get("name") or row.get("Name") or row.get("card_name") or f"Card_{cid}"
            card_map[cid] = name
    return card_map

def classify_deck(card_ids: list[int], card_map: dict[int, str]) -> str:
    names = [card_map.get(cid, str(cid)) for cid in card_ids]
    name_counts = Counter(names)
    key_mons = []
    for name, cnt in name_counts.most_common():
        # filter energies and common trainers
        if any(w in name.lower() for w in ["energy", "ultra ball", "nest ball", "professor", "boss", "ionov", "arven", "switch", "super rod", "rare candy", "buddy-buddy"]):
            continue
        key_mons.append(f"{name} (x{cnt})")
    
    # Archetype detection
    joined = " ".join(names).lower()
    if "grimmsnarl" in joined or "morgrem" in joined:
        return f"Grimmsnarl / Froslass (Mirror) [{', '.join(key_mons[:3])}]"
    if "alakazam" in joined or "abra" in joined:
        return f"Alakazam [{', '.join(key_mons[:3])}]"
    if "miraidon" in joined or "iron hands" in joined or "raikou" in joined:
        return f"Miraidon / Lightning Aggro [{', '.join(key_mons[:3])}]"
    if "roaring moon" in joined:
        return f"Roaring Moon [{', '.join(key_mons[:3])}]"
    if "raging bolt" in joined or "ogerpon" in joined:
        return f"Raging Bolt / Ogerpon [{', '.join(key_mons[:3])}]"
    if "charizard" in joined or "charmander" in joined:
        return f"Charizard ex [{', '.join(key_mons[:3])}]"
    if "gardevoir" in joined or "ralts" in joined or "kirlia" in joined:
        return f"Gardevoir ex [{', '.join(key_mons[:3])}]"
    if "dragapult" in joined or "drakloak" in joined:
        return f"Dragapult ex [{', '.join(key_mons[:3])}]"
    if "lugia" in joined or "archeops" in joined:
        return f"Lugia / Archeops [{', '.join(key_mons[:3])}]"
    if "crustle" in joined or "dwebble" in joined:
        return f"Crustle Stall/Wall [{', '.join(key_mons[:3])}]"
    if "snorlax" in joined:
        return f"Snorlax Stall [{', '.join(key_mons[:3])}]"
    if "gholdengo" in joined:
        return f"Gholdengo ex [{', '.join(key_mons[:3])}]"
    if "archaludon" in joined or "duraludon" in joined:
        return f"Archaludon ex [{', '.join(key_mons[:3])}]"
    if "regidrago" in joined:
        return f"Regidrago VSTAR [{', '.join(key_mons[:3])}]"
    if "pidgeot" in joined:
        return f"Pidgeot Control/Box [{', '.join(key_mons[:3])}]"
        
    return f"Custom/Other [{', '.join(key_mons[:4])}]"

def analyze_loss_replay(ep_id: int, sub_id: int, label: str, card_map: dict[int, str]):
    out_dir = ROOT / "data" / "replays" / str(sub_id)
    rp_path = out_dir / f"episode-{ep_id}-replay.json"
    if not rp_path.exists():
        rp_path = out_dir / f"{ep_id}.json"
    if not rp_path.exists():
        print(f"Error: {ep_id} replay not found!")
        return

    data = json.loads(rp_path.read_text())
    steps = data.get("steps", [])
    info = data.get("info", {})
    team_names = info.get("TeamNames", ["Player 0", "Player 1"])
    
    meta_path = out_dir / "episodes_metadata.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else []
    ep_meta = next((e for e in meta if e.get("id") == ep_id), {})
    
    meta_agents = ep_meta.get("agents", [])
    our_agent_idx = None
    for idx, ag in enumerate(meta_agents):
        if ag.get("submissionId") == sub_id:
            our_agent_idx = idx
            break
            
    our_seat = our_agent_idx if our_agent_idx is not None else 0
    opp_seat = 1 - our_seat
    
    our_name = team_names[our_seat] if len(team_names) > our_seat else f"Seat {our_seat}"
    opp_name = team_names[opp_seat] if len(team_names) > opp_seat else f"Seat {opp_seat}"
    
    our_agent_meta = meta_agents[our_seat] if len(meta_agents) > our_seat else {}
    opp_agent_meta = meta_agents[opp_seat] if len(meta_agents) > opp_seat else {}
    
    our_init = our_agent_meta.get("initialScore")
    our_upd = our_agent_meta.get("updatedScore")
    opp_init = opp_agent_meta.get("initialScore")
    opp_upd = opp_agent_meta.get("updatedScore")
    opp_sub = opp_agent_meta.get("submissionId")
    
    # Decks
    our_deck_ids = steps[1][our_seat].get("action", []) if len(steps) > 1 else []
    opp_deck_ids = steps[1][opp_seat].get("action", []) if len(steps) > 1 else []
    
    our_arch = classify_deck(our_deck_ids, card_map)
    opp_arch = classify_deck(opp_deck_ids, card_map)
    
    our_init_s = f"{our_init:.1f}" if our_init is not None else "Init"
    our_upd_s = f"{our_upd:.1f}" if our_upd is not None else "N/A"
    opp_init_s = f"{opp_init:.1f}" if opp_init is not None else "N/A"
    delta_s = f"{(our_upd - our_init):+.1f}" if (our_upd is not None and our_init is not None) else "+0.0"
    
    print(f"\n{'='*90}")
    print(f"LOSS ANALYSIS: Episode {ep_id} | Agent: {label} (Sub {sub_id})")
    print(f"{'='*90}")
    print(f"Matchup: Us ({our_name}, ELO {our_init_s} -> {our_upd_s}, Delta: {delta_s})")
    print(f"         vs Opponent ({opp_name}, Sub {opp_sub}, ELO {opp_init_s})")
    print(f"Opponent Archetype: {opp_arch}")
    print(f"Total Steps: {len(steps)}")
    
    # Step-by-step game trace
    first_player = None
    turn_events = []
    
    # Track states
    last_valid_state = None
    
    for s_idx, step in enumerate(steps):
        for seat in [0, 1]:
            obs = step[seat].get("observation", {})
            raw = obs.get("current")
            if raw and isinstance(raw, dict):
                last_valid_state = raw
                if first_player is None:
                    first_player = raw.get("firstPlayer")
                
                turn = raw.get("turn", 0)
                players = raw.get("players", [])
                if len(players) >= 2:
                    us_p = players[our_seat]
                    opp_p = players[opp_seat]
                    
                    us_active = us_p.get("active", [{}])[0] if us_p.get("active") else {}
                    opp_active = opp_p.get("active", [{}])[0] if opp_p.get("active") else {}
                    
                    us_active_name = card_map.get(us_active.get("id"), str(us_active.get("id"))) if us_active else "None"
                    opp_active_name = card_map.get(opp_active.get("id"), str(opp_active.get("id"))) if opp_active else "None"
                    
                    us_bench = [card_map.get(b.get("id"), str(b.get("id"))) for b in us_p.get("bench", [])]
                    opp_bench = [card_map.get(b.get("id"), str(b.get("id"))) for b in opp_p.get("bench", [])]
                    
                    us_prizes_left = len(us_p.get("prize", []))
                    opp_prizes_left = len(opp_p.get("prize", []))
                    
                    us_deck_left = us_p.get("deckCount", 0)
                    opp_deck_left = opp_p.get("deckCount", 0)
                    
                    # Record turn milestone
                    if not turn_events or turn_events[-1]["turn"] != turn:
                        turn_events.append({
                            "turn": turn,
                            "step": s_idx,
                            "us_active": us_active_name,
                            "us_active_hp": f"{us_active.get('hp')}/{us_active.get('maxHp')}" if us_active else "0/0",
                            "us_active_energies": len(us_active.get("energies", [])) if us_active else 0,
                            "us_bench": us_bench,
                            "us_prizes_left": us_prizes_left,
                            "us_deck_left": us_deck_left,
                            "opp_active": opp_active_name,
                            "opp_active_hp": f"{opp_active.get('hp')}/{opp_active.get('maxHp')}" if opp_active else "0/0",
                            "opp_active_energies": len(opp_active.get("energies", [])) if opp_active else 0,
                            "opp_bench": opp_bench,
                            "opp_prizes_left": opp_prizes_left,
                            "opp_deck_left": opp_deck_left,
                        })

    print(f"\nFirst Turn Player: {'Us (Seat ' + str(our_seat) + ')' if first_player == our_seat else 'Opponent (Seat ' + str(opp_seat) + ')'}")
    
    print("\n--- TURN PROGRESSION ---")
    for te in turn_events:
        print(f"Turn {te['turn']:2d} (Step {te['step']:3d}):")
        print(f"  US:  Active: {te['us_active']} (HP {te['us_active_hp']}, {te['us_active_energies']} E) | Bench: {te['us_bench']} | Prizes Left: {te['us_prizes_left']} | Deck: {te['us_deck_left']}")
        print(f"  OPP: Active: {te['opp_active']} (HP {te['opp_active_hp']}, {te['opp_active_energies']} E) | Bench: {te['opp_bench']} | Prizes Left: {te['opp_prizes_left']} | Deck: {te['opp_deck_left']}")

    # Determine end game condition
    if turn_events:
        last_te = turn_events[-1]
        print("\n--- FINAL OUTCOME ANALYSIS ---")
        print(f"Final Score in Prizes: We took {6 - last_te['us_prizes_left']}/6 prizes | Opponent took {6 - last_te['opp_prizes_left']}/6 prizes")
        print(f"Final Deck Counts: Us = {last_te['us_deck_left']} | Opponent = {last_te['opp_deck_left']}")
        
        # Diagnosis
        reasons = []
        if last_te['opp_prizes_left'] == 0:
            reasons.append("Opponent took all 6 prize cards (Prize Out)")
        if last_te['us_deck_left'] == 0:
            reasons.append("We ran out of cards in deck (Deck Out)")
        if last_te['us_active'] == "None" and not last_te['us_bench']:
            reasons.append("All our Pokemon were knocked out with empty bench (Bench Out)")
        if not reasons:
            reasons.append("Game reached turn/action limit or conceded by rule")
            
        print(f"Primary Defeat Mode: {', '.join(reasons)}")
        
        t1 = turn_events[0] if len(turn_events) > 0 else None
        print("\nKey Tactical Observation:")
        if t1:
            print(f"- Start: We opened with {t1['us_active']} in active.")
        if last_te['us_prizes_left'] == 6:
            print(f"- Prize Lock: We took 0 prizes the entire game (complete stall/lockout or fast blowout).")
        elif last_te['us_prizes_left'] >= 4:
            print(f"- Low Prize Conversion: We only took {6 - last_te['us_prizes_left']} prizes.")
        else:
            print(f"- Close Game: We took {6 - last_te['us_prizes_left']} prizes (went down to wire).")

def main():
    card_map = load_cards()
    print(f"Loaded {len(card_map)} cards from EN_Card_Data.csv.")
    
    print("\n" + "#"*90)
    print("# INVESTIGATING 55180261 (Grimmsnarl 5k Reference)")
    print("#"*90)
    for ep_id in [89476888, 89476983, 89478632, 89479194]:
        analyze_loss_replay(ep_id, 55180261, "Grimmsnarl 5k Reference", card_map)
        
    print("\n\n" + "#"*90)
    print("# INVESTIGATING 55180215 (Grimmsnarl Gen4 Sparred)")
    print("#"*90)
    for ep_id in [89476878, 89478080, 89478636, 89479193]:
        analyze_loss_replay(ep_id, 55180215, "Grimmsnarl Gen4 Sparred", card_map)

if __name__ == "__main__":
    main()
