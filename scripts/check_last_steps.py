#!/usr/bin/env python3
"""Check why the long matches ended and parse exact logs."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
replays_dir = ROOT / "data" / "replays" / "55287852"

for ep_id in [90346282, 90349388, 90350033, 90350768]:
    rp = replays_dir / f"episode-{ep_id}-replay.json"
    data = json.loads(rp.read_text(encoding="utf-8"))
    steps = data.get("steps", [])
    
    print(f"\n================ Episode {ep_id} (Last 10 steps) ================")
    for s_idx in range(max(0, len(steps)-10), len(steps)):
        s = steps[s_idx]
        for p_i, p in enumerate(s):
            logs = p.get("observation", {}).get("logs", [])
            act = p.get("action")
            if logs:
                for l in logs:
                    if l.get("type") in [15, 16, 6, 10]:
                        print(f"  Step {s_idx:03d} P{p_i} Log: {l}")
            if act is not None:
                print(f"  Step {s_idx:03d} P{p_i} Act: {act}")
