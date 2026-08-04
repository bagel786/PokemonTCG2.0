#!/usr/bin/env python3
"""Deep decision-by-decision inspection of every single loss in the active submissions:
55189662 (Games 2, 3, 9) and 55189658 (Games 3, 4, 9, 10).
"""

import csv
import json
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


def inspect_detailed_loss(sub_id: int, ep_id: int, card_map: dict[int, str]):
    sub_dir = ROOT / "data" / "replays" / str(sub_id)
    rp_path = sub_dir / f"episode-{ep_id}-replay.json"
    if not rp_path.exists():
        rp_path = sub_dir / f"{ep_id}.json"
        
    rp_data = json.loads(rp_path.read_text())
    steps = rp_data.get("steps", [])
    info = rp_data.get("info", {})
    team_names = info.get("TeamNames", ["Seat 0", "Seat 1"])
    
    meta_path = sub_dir / "episodes_metadata.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else []
    ep_meta = next((e for e in meta if e.get("id") == ep_id), {})
    agents = ep_meta.get("agents", [])
    our_idx = next((i for i, a in enumerate(agents) if a.get("submissionId") == sub_id), 0)
    opp_idx = 1 - our_idx
    
    us_meta = agents[our_idx]
    opp_meta = agents[opp_idx]
    
    our_name = team_names[our_idx]
    opp_name = team_names[opp_idx]
    
    print(f"\n{'='*95}")
    print(f"DETAILED STEP-BY-STEP LOSS INSPECTION: Sub {sub_id} | Episode {ep_id}")
    print(f"{'='*95}")
    print(f"Us: {our_name} (Seat {our_idx}, ELO {us_meta.get('initialScore'):.1f} -> {us_meta.get('updatedScore'):.1f}, Delta: {(us_meta.get('updatedScore',0)-us_meta.get('initialScore',0)):+5.1f})")
    print(f"Opponent: {opp_name} (Seat {opp_idx}, Sub {opp_meta.get('submissionId')}, ELO {opp_meta.get('initialScore'):.1f})")
    
    # Trace every turn's actions and state
    current_turn = -1
    for s_idx, step in enumerate(steps):
        # check observation
        obs_raw = None
        for s in [our_idx, opp_idx]:
            if step[s].get("observation", {}).get("current"):
                obs_raw = step[s]["observation"]["current"]
                break
                
        if not obs_raw or not isinstance(obs_raw, dict):
            continue
            
        turn = obs_raw.get("turn", 0)
        players = obs_raw.get("players", [])
        if len(players) < 2:
            continue
            
        us_p = players[our_idx]
        opp_p = players[opp_idx]
        
        us_act_list = [x for x in (us_p.get("active") or []) if x]
        opp_act_list = [x for x in (opp_p.get("active") or []) if x]
        us_act = us_act_list[0] if us_act_list else {}
        opp_act = opp_act_list[0] if opp_act_list else {}
        
        us_bench = [x for x in (us_p.get("bench") or []) if x]
        opp_bench = [x for x in (opp_p.get("bench") or []) if x]
        
        # Check actions taken in this step
        our_action = step[our_idx].get("action") if len(step) > our_idx else None
        opp_action = step[opp_idx].get("action") if len(step) > opp_idx else None
        
        # If new turn or notable action
        if turn != current_turn:
            current_turn = turn
            print(f"\n--- Turn {turn} (Step {s_idx}) ---")
            us_bench_str = ", ".join([f"{card_map.get(b.get('id'), '?')}({len(b.get('energies',[]))}E, HP {b.get('hp')}/{b.get('maxHp')})" for b in us_bench]) or "Empty"
            opp_bench_str = ", ".join([f"{card_map.get(b.get('id'), '?')}({len(b.get('energies',[]))}E, HP {b.get('hp')}/{b.get('maxHp')})" for b in opp_bench]) or "Empty"
            
            us_hand = us_p.get("hand", [])
            hand_str = []
            if isinstance(us_hand, list):
                for h in us_hand:
                    cid = h.get("id") if isinstance(h, dict) else h
                    if cid is not None:
                        hand_str.append(card_map.get(cid, str(cid)))
            
            print(f"  US:  Active: {card_map.get(us_act.get('id'), 'None')} (HP {us_act.get('hp')}/{us_act.get('maxHp')}, {len(us_act.get('energies',[]))}E) | Bench: [{us_bench_str}]")
            print(f"       Prizes Remaining: {len(us_p.get('prize',[]))} | Deck: {us_p.get('deckCount')} | Hand ({len(hand_str)}): {hand_str}")
            print(f"  OPP: Active: {card_map.get(opp_act.get('id'), 'None')} (HP {opp_act.get('hp')}/{opp_act.get('maxHp')}, {len(opp_act.get('energies',[]))}E) | Bench: [{opp_bench_str}]")
            print(f"       Prizes Remaining: {len(opp_p.get('prize',[]))} | Deck: {opp_p.get('deckCount')}")

        if our_action is not None and s_idx > 1:
            # Action taken by us
            print(f"    -> US Action (Step {s_idx}): {our_action}")
        if opp_action is not None and s_idx > 1:
            print(f"    -> OPP Action (Step {s_idx}): {opp_action}")


if __name__ == "__main__":
    card_map = load_card_map()
    
    print("\n" + "#"*100)
    print("# SUBMISSION 55189662 (Gen-5 Challenger) - ALL 3 LOSSES")
    print("#"*100)
    for ep in [89546362, 89546456, 89549732]:
        inspect_detailed_loss(55189662, ep, card_map)
        
    print("\n" + "#"*100)
    print("# SUBMISSION 55189658 (5k Reference Proper) - ALL 4 LOSSES")
    print("#"*100)
    for ep in [89546355, 89546945, 89549176, 89549733]:
        inspect_detailed_loss(55189658, ep, card_map)
