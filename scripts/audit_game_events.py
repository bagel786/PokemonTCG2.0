#!/usr/bin/env python3
import json
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def load_cards() -> dict[int, str]:
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

def inspect_game_events(ep_id, sub_id, card_map):
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
    
    print(f"\n====================================================================")
    print(f"GAME EVENT AUDIT: Episode {ep_id} (Our Seat: {our_seat})")
    print(f"====================================================================")
    
    for s_idx in range(len(steps)):
        step = steps[s_idx]
        for seat in [0, 1]:
            obs = step[seat].get("observation") or {}
            logs = obs.get("logs") or []
            curr = obs.get("current") or {}
            for l in logs:
                ltype = l.get("type")
                # Types in PTCG sim:
                # 0: Game start
                # 1: Draw
                # 2: Play basic
                # 3: Evolve
                # 4: Energy attach
                # 5: Play trainer/supporter
                # 6: Attack
                # 7: Damage
                # 8: Knockout / discard
                # 9: Prize taken
                # 10: Special ability
                # 11: Energy attach / effect
                p_idx = l.get("playerIndex")
                p_str = "US" if p_idx == our_seat else "OPP"
                cid = l.get("cardId")
                cname = card_map.get(cid, str(cid)) if cid else ""
                target_cid = l.get("cardIdTarget")
                target_name = card_map.get(target_cid, str(target_cid)) if target_cid else ""
                dmg = l.get("damage")
                
                # Filter noise (like simple draws), focus on attacks, damage, KOs, prizes, abilities, trainers
                if ltype in [3, 5, 6, 7, 8, 9, 10, 11] or "damage" in l or "attack" in str(l).lower():
                    # print meaningful events
                    desc = f"Type {ltype}: {cname}"
                    if target_name:
                        desc += f" -> {target_name}"
                    if dmg:
                        desc += f" (Dmg: {dmg})"
                    if l.get("prize"):
                        desc += f" [Prize: {l.get('prize')}]"
                    print(f"Step {s_idx:3d} (Turn {curr.get('turn', '?')}): [{p_str}] {desc} | full: {l}")

def main():
    card_map = load_cards()
    print("--- 55180261 (5k ref) episode 89479194 & 89478632 ---")
    inspect_game_events(89479194, 55180261, card_map)

if __name__ == "__main__":
    main()
