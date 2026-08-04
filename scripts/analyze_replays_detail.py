#!/usr/bin/env python3
"""Deep replay analyzer for recent loss episodes of 55180261 and 55180215."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Card ID mapping if available
def load_card_names():
    # Attempt to load cards
    card_map = {}
    csv_path = ROOT / "data" / "cards.csv"
    if csv_path.exists():
        import csv
        for row in csv.DictReader(csv_path.read_text().splitlines()):
            card_map[int(row.get("id", -1))] = row.get("name", "Unknown")
    return card_map

def inspect_episode(ep_id: int, sub_id: int):
    out_dir = ROOT / "data" / "replays" / str(sub_id)
    rp_path = out_dir / f"episode-{ep_id}-replay.json"
    if not rp_path.exists():
        rp_path = out_dir / f"{ep_id}.json"
    if not rp_path.exists():
        print(f"Replay {ep_id} not found!")
        return

    data = json.loads(rp_path.read_text())
    steps = data.get("steps", [])
    info = data.get("info", {})
    team_names = info.get("TeamNames", ["Player 0", "Player 1"])
    
    meta_path = out_dir / "episodes_metadata.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else []
    ep_meta = next((e for e in meta if e.get("id") == ep_id), {})
    
    meta_agents = ep_meta.get("agents", [])
    our_seat = 0
    for idx, ag in enumerate(meta_agents):
        if ag.get("submissionId") == sub_id:
            our_seat = idx
            break
            
    opp_seat = 1 - our_seat
    our_name = team_names[our_seat] if len(team_names) > our_seat else f"Seat {our_seat}"
    opp_name = team_names[opp_seat] if len(team_names) > opp_seat else f"Seat {opp_seat}"
    
    print(f"\n================================================================================")
    print(f"EPISODE {ep_id} | SUBMISSION {sub_id} (Seat {our_seat}: {our_name}) vs Opponent (Seat {opp_seat}: {opp_name})")
    print(f"================================================================================")
    print(f"Total Steps: {len(steps)}")
    
    # Step 1: deck submission
    our_deck = steps[1][our_seat].get("action") if len(steps) > 1 else []
    opp_deck = steps[1][opp_seat].get("action") if len(steps) > 1 else []
    
    # Final step
    last_step = steps[-1]
    our_final = last_step[our_seat]
    opp_final = last_step[opp_seat]
    
    print(f"Final Status: Us={our_final.get('status')}, Reward={our_final.get('reward')} | Opp={opp_final.get('status')}, Reward={opp_final.get('reward')}")
    
    # Trace step-by-step game evolution
    # Let's see prizes, active pokemon, bench, energy, deck sizes across turns
    turn_snapshots = []
    
    for s_idx, step in enumerate(steps):
        # Check observations
        for seat in [0, 1]:
            ag = step[seat]
            obs = ag.get("observation", {})
            raw = obs.get("raw")
            if raw and isinstance(raw, dict):
                # We found game state
                # Check turn number
                turn = raw.get("turn", 0)
                active_player = raw.get("activePlayerIndex", 0)
                # Check if we should log snapshot
                players = raw.get("players", [])
                if len(players) >= 2:
                    p0 = players[0]
                    p1 = players[1]
                    us_p = players[our_seat]
                    opp_p = players[opp_seat]
                    
                    snapshot = {
                        "step": s_idx,
                        "turn": turn,
                        "active_player": active_player,
                        "us_prizes": len(us_p.get("prizes", [])),
                        "opp_prizes": len(opp_p.get("prizes", [])),
                        "us_deck": len(us_p.get("deck", [])),
                        "opp_deck": len(opp_p.get("deck", [])),
                        "us_hand": len(us_p.get("hand", [])),
                        "opp_hand": len(opp_p.get("hand", [])),
                        "us_active": (us_p.get("active") or {}).get("name", (us_p.get("active") or {}).get("cardId")),
                        "opp_active": (opp_p.get("active") or {}).get("name", (opp_p.get("active") or {}).get("cardId")),
                        "us_bench_count": len(us_p.get("bench", [])),
                        "opp_bench_count": len(opp_p.get("bench", [])),
                        "winner": raw.get("winner"),
                    }
                    if not turn_snapshots or turn_snapshots[-1]["turn"] != turn or s_idx == len(steps) - 1:
                        turn_snapshots.append(snapshot)
    
    # Print key game progression
    print("\nGame Progression (Turn Samples):")
    for sn in turn_snapshots[::max(1, len(turn_snapshots)//10)] + ([turn_snapshots[-1]] if turn_snapshots else []):
        print(f"  Turn {sn['turn']:2d} (Step {sn['step']:3d}): Us Prizes Left={sn['us_prizes']}, Deck={sn['us_deck']:2d}, Active={sn['us_active']} | Opp Prizes Left={sn['opp_prizes']}, Deck={sn['opp_deck']:2d}, Active={sn['opp_active']}")
    
    if turn_snapshots:
        final_sn = turn_snapshots[-1]
        print(f"\nFinal State: Winner={final_sn['winner']} (Our Seat={our_seat})")
        print(f"Prizes Remaining: Us={final_sn['us_prizes']} (took {6-final_sn['us_prizes']}/6) vs Opp={final_sn['opp_prizes']} (took {6-final_sn['opp_prizes']}/6)")
        print(f"Decks Remaining: Us={final_sn['us_deck']} vs Opp={final_sn['opp_deck']}")
        if final_sn['opp_prizes'] == 0:
            print("Loss Reason: Opponent took all 6 prize cards (Prize Out)")
        elif final_sn['us_deck'] == 0:
            print("Loss Reason: We ran out of cards in deck (Deck Out)")
        elif final_sn['us_active'] is None and final_sn['us_bench_count'] == 0:
            print("Loss Reason: All our Pokemon were knocked out (Bench Out)")
        else:
            print(f"Loss Reason: Other / Game Engine Resolution (Winner={final_sn['winner']})")

def main():
    print("================================================================================")
    print("SUBMISSION 55180261 (Grimmsnarl 5k Reference) LOSSES")
    print("================================================================================")
    for ep in [89476888, 89476983, 89478632, 89479194]:
        inspect_episode(ep, 55180261)
        
    print("\n\n================================================================================")
    print("SUBMISSION 55180215 (Grimmsnarl Gen4 Sparred) LOSSES")
    print("================================================================================")
    for ep in [89476878, 89478080, 89478636, 89479193]:
        inspect_episode(ep, 55180215)

if __name__ == "__main__":
    main()
