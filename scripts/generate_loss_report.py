#!/usr/bin/env python3
"""Generate a thorough, clean diagnostic report for all recent match losses."""

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
            try:
                cid = int(row.get("Card ID", -1))
                name = row.get("Card Name", f"Card_{cid}")
                card_map[cid] = name
            except ValueError:
                continue
    return card_map

def classify_deck(card_ids: list[int], card_map: dict[int, str]) -> tuple[str, list[str]]:
    names = [card_map.get(cid, f"Card_{cid}") for cid in card_ids]
    name_counts = Counter(names)
    key_mons = []
    for name, cnt in name_counts.most_common():
        if any(w in name.lower() for w in ["energy", "ultra ball", "nest ball", "professor", "boss", "ionov", "arven", "switch", "super rod", "rare candy", "buddy-buddy", "earthen", "night stretcher", "counter catcher", "prime catcher", "rescue board", "town store", "artazon"]):
            continue
        key_mons.append(f"{name} x{cnt}")
    
    joined = " ".join(names).lower()
    arch = "Custom / Off-Meta"
    if "grimmsnarl" in joined or "morgrem" in joined:
        arch = "Grimmsnarl / Froslass (Mirror)"
    elif "lucario" in joined:
        arch = "Mega Lucario ex"
    elif "alakazam" in joined or "abra" in joined:
        arch = "Alakazam ex (Mewtwo/Dudunsparce)"
    elif "miraidon" in joined or "iron hands" in joined or "raikou" in joined:
        arch = "Miraidon ex / Iron Hands ex (Turbo Lightning)"
    elif "roaring moon" in joined:
        arch = "Roaring Moon ex (Dark Aggro)"
    elif "raging bolt" in joined or "teal mask ogerpon" in joined:
        arch = "Raging Bolt ex / Ogerpon"
    elif "charizard" in joined:
        arch = "Charizard ex / Pidgeot ex"
    elif "gardevoir" in joined:
        arch = "Gardevoir ex"
    elif "dragapult" in joined:
        arch = "Dragapult ex"
    elif "lugia" in joined or "archeops" in joined:
        arch = "Lugia VSTAR / Archeops"
    elif "crustle" in joined or "dwebble" in joined:
        arch = "Crustle / Stall Wall"
    elif "snorlax" in joined:
        arch = "Snorlax Stall / Block"
    elif "gholdengo" in joined:
        arch = "Gholdengo ex"
    elif "archaludon" in joined or "duraludon" in joined:
        arch = "Archaludon ex"
    elif "froslass" in joined and "munkidori" in joined:
        arch = "Froslass / Munkidori Spread"
    elif "regidrago" in joined:
        arch = "Regidrago VSTAR"
        
    return arch, key_mons[:5]

def analyze_episode(ep_id: int, sub_id: int, label: str, card_map: dict[int, str]):
    out_dir = ROOT / "data" / "replays" / str(sub_id)
    rp_path = out_dir / f"episode-{ep_id}-replay.json"
    if not rp_path.exists():
        rp_path = out_dir / f"{ep_id}.json"
    if not rp_path.exists():
        return f"Replay file for {ep_id} not found."

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
    
    our_arch, our_key = classify_deck(our_deck_ids, card_map)
    opp_arch, opp_key = classify_deck(opp_deck_ids, card_map)
    
    our_init_s = f"{our_init:.1f}" if our_init is not None else "Unrated/Init"
    our_upd_s = f"{our_upd:.1f}" if our_upd is not None else "N/A"
    opp_init_s = f"{opp_init:.1f}" if opp_init is not None else "N/A"
    delta_s = f"{(our_upd - our_init):+.1f}" if (our_upd is not None and our_init is not None) else "+0.0"
    
    first_player = None
    turns_history = []
    
    # Track actions taken by players
    our_attacks_used = []
    opp_attacks_used = []
    
    for s_idx, step in enumerate(steps):
        for seat in [0, 1]:
            obs = step[seat].get("observation", {})
            raw = obs.get("current")
            if raw and isinstance(raw, dict):
                if first_player is None:
                    first_player = raw.get("firstPlayer")
                
                turn = raw.get("turn", 0)
                players = raw.get("players", [])
                if len(players) >= 2:
                    us_p = players[our_seat]
                    opp_p = players[opp_seat]
                    
                    us_active = us_p.get("active", [{}])[0] if us_p.get("active") else {}
                    opp_active = opp_p.get("active", [{}])[0] if opp_p.get("active") else {}
                    
                    us_active_name = card_map.get(us_active.get("id"), str(us_active.get("id"))) if us_active else "Empty"
                    opp_active_name = card_map.get(opp_active.get("id"), str(opp_active.get("id"))) if opp_active else "Empty"
                    
                    us_bench = [card_map.get(b.get("id"), str(b.get("id"))) for b in us_p.get("bench", [])]
                    opp_bench = [card_map.get(b.get("id"), str(b.get("id"))) for b in opp_p.get("bench", [])]
                    
                    us_prizes_left = len(us_p.get("prize", []))
                    opp_prizes_left = len(opp_p.get("prize", []))
                    
                    us_deck_left = us_p.get("deckCount", 0)
                    opp_deck_left = opp_p.get("deckCount", 0)
                    
                    if not turns_history or turns_history[-1]["turn"] != turn:
                        turns_history.append({
                            "turn": turn,
                            "step": s_idx,
                            "us_active": us_active_name,
                            "us_active_hp": f"{us_active.get('hp')}/{us_active.get('maxHp')}" if us_active else "0/0",
                            "us_active_e": len(us_active.get("energies", [])) if us_active else 0,
                            "us_bench": us_bench,
                            "us_prizes": us_prizes_left,
                            "us_deck": us_deck_left,
                            "opp_active": opp_active_name,
                            "opp_active_hp": f"{opp_active.get('hp')}/{opp_active.get('maxHp')}" if opp_active else "0/0",
                            "opp_active_e": len(opp_active.get("energies", [])) if opp_active else 0,
                            "opp_bench": opp_bench,
                            "opp_prizes": opp_prizes_left,
                            "opp_deck": opp_deck_left,
                        })

    first_turn_str = "Us (Going First)" if first_player == our_seat else "Opponent (Going First)"
    
    last_turn = turns_history[-1] if turns_history else {}
    t1 = turns_history[0] if turns_history else {}
    t2 = turns_history[1] if len(turns_history) > 1 else {}
    t4 = turns_history[3] if len(turns_history) > 3 else {}
    
    us_prizes_taken = 6 - last_turn.get("us_prizes", 6)
    opp_prizes_taken = 6 - last_turn.get("opp_prizes", 6)
    
    loss_mode = "Unknown"
    if last_turn.get("opp_prizes") == 0:
        loss_mode = "Opponent took all 6 prizes (Full KO Race)"
    elif last_turn.get("us_deck") == 0:
        loss_mode = "Deckout (0 cards remaining in deck)"
    elif last_turn.get("us_active") == "Empty" and not last_turn.get("us_bench"):
        loss_mode = "Benchout (All Pokemon Knocked Out)"
    else:
        loss_mode = "Engine Resolution / Turn Limit reached"

    # Tactical summary
    findings = []
    if t1:
        findings.append(f"Opening Active: {t1['us_active']} vs Opponent's {t1['opp_active']}")
    
    # Check if we built Grimmsnarl
    grimmsnarl_seen = any("Grimmsnarl" in th["us_active"] or any("Grimmsnarl" in b for b in th["us_bench"]) for th in turns_history)
    morgrem_seen = any("Morgrem" in th["us_active"] or any("Morgrem" in b for b in th["us_bench"]) for th in turns_history)
    froslass_seen = any("Froslass" in th["us_active"] or any("Froslass" in b for b in th["us_bench"]) for th in turns_history)
    
    setup_status = []
    if grimmsnarl_seen:
        setup_status.append("Grimmsnarl evolved")
    elif morgrem_seen:
        setup_status.append("Stuck on Morgrem (Grimmsnarl not reached)")
    else:
        setup_status.append("Failed to evolve beyond Impidimp (Severe Brick/Stall)")
        
    if froslass_seen:
        setup_status.append("Froslass on board")
    else:
        setup_status.append("No Froslass evolved")
        
    findings.append(f"Setup Quality: {', '.join(setup_status)}")
    findings.append(f"Prize Trade: We took {us_prizes_taken}/6 prizes, Opponent took {opp_prizes_taken}/6 prizes")
    
    # Bench development
    final_us_board = [last_turn.get("us_active", "")] + last_turn.get("us_bench", [])
    final_opp_board = [last_turn.get("opp_active", "")] + last_turn.get("opp_bench", [])
    
    return {
        "ep_id": ep_id,
        "sub_id": sub_id,
        "label": label,
        "opp_name": opp_name,
        "opp_sub": opp_sub,
        "opp_init": opp_init_s,
        "our_init": our_init_s,
        "our_upd": our_upd_s,
        "delta": delta_s,
        "first_turn": first_turn_str,
        "total_turns": last_turn.get("turn", 0),
        "total_steps": len(steps),
        "opp_arch": opp_arch,
        "opp_key": opp_key,
        "loss_mode": loss_mode,
        "findings": findings,
        "final_us_board": final_us_board,
        "final_opp_board": final_opp_board,
        "turns_sample": turns_history[::max(1, len(turns_history)//6)] + [last_turn]
    }

def main():
    card_map = load_cards()
    
    # List of loss episodes to report
    all_losses = [
        (89476888, 55180261, "Grimmsnarl 5k Reference"),
        (89476983, 55180261, "Grimmsnarl 5k Reference"),
        (89478632, 55180261, "Grimmsnarl 5k Reference"),
        (89479194, 55180261, "Grimmsnarl 5k Reference"),
        (89476878, 55180215, "Grimmsnarl Gen4 Sparred"),
        (89478080, 55180215, "Grimmsnarl Gen4 Sparred"),
        (89478636, 55180215, "Grimmsnarl Gen4 Sparred"),
        (89479193, 55180215, "Grimmsnarl Gen4 Sparred"),
    ]
    
    reports = [analyze_episode(ep, sub, lbl, card_map) for ep, sub, lbl in all_losses]
    
    for r in reports:
        if isinstance(r, str):
            print(r)
            continue
        print(f"\n{'='*85}")
        print(f"EPISODE {r['ep_id']} | {r['label']} (Sub {r['sub_id']}) vs {r['opp_name']} (Opp ELO: {r['opp_init']})")
        print(f"{'='*85}")
        print(f"ELO Impact: {r['our_init']} -> {r['our_upd']} ({r['delta']}) | {r['first_turn']} | Total Turns: {r['total_turns']} (Steps: {r['total_steps']})")
        print(f"Opponent Archetype: {r['opp_arch']}")
        print(f"Opponent Key Cards: {', '.join(r['opp_key'])}")
        print(f"Loss Mode: {r['loss_mode']}")
        for f in r['findings']:
            print(f"  • {f}")
        print("Final Boards:")
        print(f"  • Our Final Board: {', '.join(filter(None, r['final_us_board']))}")
        print(f"  • Opp Final Board: {', '.join(filter(None, r['final_opp_board']))}")
        print("\nTurn Progression Highlights:")
        for t in r['turns_sample']:
            print(f"  Turn {t.get('turn', 0):2d}: Us Active={t.get('us_active')} (Prizes: {t.get('us_prizes')}/6 left) vs Opp Active={t.get('opp_active')} (Prizes: {t.get('opp_prizes')}/6 left)")

if __name__ == "__main__":
    main()
