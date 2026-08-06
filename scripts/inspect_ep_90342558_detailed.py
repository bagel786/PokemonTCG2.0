#!/usr/bin/env python3
"""Detailed turn-by-turn breakdown of Episode 90342558."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
rp_path = ROOT / "data" / "replays" / "55287852" / "episode-90342558-replay.json"
data = json.loads(rp_path.read_text(encoding="utf-8"))
steps = data.get("steps", [])

print(f"Total steps in 90342558: {len(steps)}")
for s_idx, step in enumerate(steps):
    p0, p1 = step[0], step[1]
    act0, act1 = p0.get("action"), p1.get("action")
    obs0, obs1 = p0.get("observation", {}), p1.get("observation", {})
    logs0 = obs0.get("logs", [])
    logs1 = obs1.get("logs", [])
    
    # We want to see what decisions were made
    print(f"\n=================== STEP {s_idx} ===================")
    if act0 is not None:
        print(f"P0 (Opponent 464 Elo) Action: {act0}")
    if act1 is not None:
        print(f"P1 (Hero v2 Agent) Action: {act1}")
    if logs0:
        print(f"P0 Logs ({len(logs0)}):")
        for l in logs0:
            print(f"   {l}")
    if logs1 and logs1 != logs0:
        print(f"P1 Logs ({len(logs1)}):")
        for l in logs1:
            print(f"   {l}")
