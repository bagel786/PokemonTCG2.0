#!/usr/bin/env python3
"""Deep dive into the tactical reasons for the losses."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
replays_dir = ROOT / "data" / "replays" / "55287852"

for ep_id in [90346282, 90349388, 90350033, 90350768]:
    rp = replays_dir / f"episode-{ep_id}-replay.json"
    data = json.loads(rp.read_text(encoding="utf-8"))
    steps = data.get("steps", [])
    
    # Determine seats
    p0_deck = steps[1][0].get("action", [])
    hero_idx = 0 if p0_deck[:5] == [7, 7, 7, 7, 7] else 1
    opp_idx = 1 - hero_idx
    
    # Check end game reason
    last_step = steps[-1]
    statuses = [last_step[0].get("status"), last_step[1].get("status")]
    rewards = [last_step[0].get("reward"), last_step[1].get("reward")]
    
    # Count knockouts / prizes
    hero_kos = 0
    opp_kos = 0
    for s in steps:
        for p in s:
            for log in p.get("observation", {}).get("logs", []):
                if log.get("type") == 16 and log.get("value", 0) < 0:
                    pass
    
    # Terminal observation
    obs0 = steps[-2][hero_idx].get("observation", {})
    cur0 = obs0.get("current") or {}
    players = cur0.get("players", [{}, {}])
    hero_p = players[hero_idx] if len(players) > hero_idx else {}
    opp_p = players[opp_idx] if len(players) > opp_idx else {}
    
    print(f"\n================ Episode {ep_id} ================")
    print(f"Hero Seat: P{hero_idx} | Total Steps: {len(steps)}")
    print(f"Final Statuses: {statuses}, Rewards: {rewards}")
    print(f"Terminal State -> Hero Prizes Left: {hero_p.get('prizes')}, Deck Left: {len(hero_p.get('deck') or [])}, Bench: {len(hero_p.get('bench') or [])}")
    print(f"Terminal State -> Opp  Prizes Left: {opp_p.get('prizes')}, Deck Left: {len(opp_p.get('deck') or [])}, Bench: {len(opp_p.get('bench') or [])}")
