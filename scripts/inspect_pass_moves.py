#!/usr/bin/env python3
"""Inspect every single pass action (Context 0, Type 14) across all 5 loss games."""

import json
from pathlib import Path

losses = [90480044, 90483170, 90484716, 90485483, 90486266]
replays_dir = Path("data/replays/55303334")

for ep_id in losses:
    rp_file = replays_dir / f"episode-{ep_id}-replay.json"
    if not rp_file.exists():
        continue
    data = json.loads(rp_file.read_text(encoding="utf-8"))
    steps = data["steps"]
    p0_deck = steps[1][0].get("action", [])
    hero_idx = 0 if p0_deck[:5] == [7, 7, 7, 7, 7] else 1
    
    print(f"\n=======================================================")
    print(f"PASS AUDIT FOR EPISODE {ep_id} (Hero Player {hero_idx})")
    print(f"=======================================================")
    
    for s_idx, s in enumerate(steps):
        h_s = s[hero_idx]
        sel = h_s.get("observation", {}).get("select")
        act = h_s.get("action")
        cur = h_s.get("observation", {}).get("current")
        if sel and act != [] and act is not None:
            ctx = sel.get("context")
            opts = sel.get("option", [])
            if ctx == 0:
                # Check if action contains pass (type 14)
                for a_idx in act:
                    if a_idx < len(opts) and opts[a_idx].get("type") == 14:
                        print(f"Step {s_idx:3d} | PASSED TURN! Available options were:")
                        for oi, o in enumerate(opts):
                            print(f"   Option {oi}: {o}")
                        if cur:
                            hp = cur["players"][cur.get("yourIndex", 0)]
                            h_act = hp.get("active", [{}])[0] if hp.get("active") else {}
                            print(f"   Hero Active: ID={h_act.get('id')}, HP={h_act.get('hp')}/{h_act.get('maxHp')}, Energies={h_act.get('energies')}")
                            print(f"   Hero Hand ({len(hp.get('hand', []))} cards): {[c.get('id') for c in hp.get('hand', []) if c]}")
                            print(f"   Hero Bench ({len(hp.get('bench', []))} mons): {[m.get('id') for m in hp.get('bench', []) if m]}")
