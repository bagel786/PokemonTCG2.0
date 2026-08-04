#!/usr/bin/env python3
import json
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def load_cards():
    card_map = {}
    csv_path = ROOT / "freshstart" / "data" / "EN_Card_Data.csv"
    if csv_path.exists():
        reader = csv.DictReader(csv_path.read_text(encoding="utf-8-sig").splitlines())
        for row in reader:
            try:
                cid = int(row.get("Card ID", -1))
                name = row.get("Card Name", f"Card_{cid}")
                card_map[cid] = name
            except ValueError:
                continue
    return card_map

def inspect_terminal_state(ep_id, sub_id, card_map):
    p = Path(f"data/replays/{sub_id}/episode-{ep_id}-replay.json")
    if not p.exists():
        p = Path(f"data/replays/{sub_id}/{ep_id}.json")
    if not p.exists():
        return
        
    data = json.loads(p.read_text())
    steps = data["steps"]
    
    meta_path = Path(f"data/replays/{sub_id}/episodes_metadata.json")
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else []
    ep_meta = next((e for e in meta if e.get("id") == ep_id), {})
    
    meta_agents = ep_meta.get("agents", [])
    our_seat = 0
    for idx, ag in enumerate(meta_agents):
        if ag.get("submissionId") == sub_id:
            our_seat = idx
            break
    opp_seat = 1 - our_seat
    
    # Get last valid observation
    last_obs_step = None
    last_step_idx = len(steps) - 1
    for s_idx in reversed(range(len(steps))):
        s = steps[s_idx]
        for seat in [0, 1]:
            if s[seat].get("observation", {}).get("current"):
                last_obs_step = (s_idx, s[seat]["observation"]["current"])
                break
        if last_obs_step:
            break
            
    if not last_obs_step:
        print(f"Ep {ep_id}: No valid observation found.")
        return
        
    s_idx, curr = last_obs_step
    players = curr.get("players", [])
    us = players[our_seat]
    opp = players[opp_seat]
    
    us_active = [card_map.get(c.get("id"), str(c.get("id"))) for c in us.get("active", [])]
    opp_active = [card_map.get(c.get("id"), str(c.get("id"))) for c in opp.get("active", [])]
    
    us_bench = [card_map.get(c.get("id"), str(c.get("id"))) for c in us.get("bench", [])]
    opp_bench = [card_map.get(c.get("id"), str(c.get("id"))) for c in opp.get("bench", [])]
    
    us_prizes = len(us.get("prize", []))
    opp_prizes = len(opp.get("prize", []))
    
    us_deck = us.get("deckCount", 0)
    opp_deck = opp.get("deckCount", 0)
    
    us_discard = len(us.get("discard", []))
    opp_discard = len(opp.get("discard", []))
    
    res = curr.get("result")
    final_step = steps[-1]
    our_final_status = final_step[our_seat].get("status")
    opp_final_status = final_step[opp_seat].get("status")
    our_reward = final_step[our_seat].get("reward")
    opp_reward = final_step[opp_seat].get("reward")
    
    print(f"\n{'='*80}")
    print(f"EPISODE {ep_id} (Sub {sub_id}) | Final Turn {curr.get('turn')} / Step {s_idx} of {len(steps)}")
    print(f"{'='*80}")
    print(f"Result: Us={our_final_status} (Reward {our_reward}) | Opp={opp_final_status} (Reward {opp_reward}) | Sim Result={res}")
    print(f"Prizes Remaining: Us={us_prizes} (took {6-us_prizes}/6) | Opp={opp_prizes} (took {6-opp_prizes}/6)")
    print(f"Decks Remaining:  Us={us_deck} cards | Opp={opp_deck} cards")
    print(f"Board State:")
    print(f"  US Active:  {', '.join(us_active) or 'Empty / Knocked Out'}")
    print(f"  US Bench:   {', '.join(us_bench) or 'Empty'}")
    print(f"  OPP Active: {', '.join(opp_active) or 'Empty / Knocked Out'}")
    print(f"  OPP Bench:  {', '.join(opp_bench) or 'Empty'}")
    
    # Specific Loss Mechanism
    mechanism = "UNKNOWN"
    if opp_prizes == 0:
        mechanism = "OPPONENT_TOOK_ALL_PRIZES (Prize Race Loss)"
    elif us_deck == 0:
        mechanism = "HERO_DECKOUT (Drew entire deck)"
    elif not us_active and not us_bench:
        mechanism = "HERO_BENCH_WIPE (All Pokemon Knocked Out)"
    elif our_final_status == "TIMEOUT":
        mechanism = "TIMEOUT"
    elif our_final_status == "ERROR":
        mechanism = "INVALID_ACTION_ERROR"
    else:
        # Check turn limit or sudden win
        mechanism = f"ENGINE_DECISION (Result: {res}, OppPrizesLeft: {opp_prizes}, UsPrizesLeft: {us_prizes})"
    print(f"Defeat Mechanism: {mechanism}")

def main():
    card_map = load_cards()
    print("\n" + "#"*80)
    print("SUBMISSION 55180261 (Grimmsnarl 5k Reference) LOSSES")
    print("#"*80)
    for ep in [89476888, 89476983, 89478632, 89479194]:
        inspect_terminal_state(ep, 55180261, card_map)
        
    print("\n" + "#"*80)
    print("SUBMISSION 55180215 (Grimmsnarl Gen4 Sparred) LOSSES")
    print("#"*80)
    for ep in [89476878, 89478080, 89478636, 89479193]:
        inspect_terminal_state(ep, 55180215, card_map)

if __name__ == "__main__":
    main()
