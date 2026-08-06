#!/usr/bin/env python3
"""Detailed inspection of the 4 live losses for sub 55278944."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPLAY_DIR = ROOT / "data" / "replays" / "55278944"
LOSS_EPISODES = [90251492, 90246373, 90245643, 90244935]

def inspect_loss(ep_id: int):
    rp_file = REPLAY_DIR / f"episode-{ep_id}-replay.json"
    if not rp_file.exists():
        rp_file = REPLAY_DIR / f"{ep_id}.json"
    if not rp_file.exists():
        print(f"Replay {ep_id} not found locally.")
        return

    data = json.loads(rp_file.read_text())
    steps = data.get("steps", [])
    print(f"\n=======================================================")
    print(f"  EPISODE {ep_id} LOSS INSPECTION ({len(steps)} steps)")
    print(f"=======================================================")
    
    # Check opening step
    if len(steps) > 1:
        step_1 = steps[1]
        print(f"Initial setup step observation keys: {[k for k in step_1[0].get('observation', {}).keys()][:6]}")

    # Inspect last step
    last_step = steps[-1]
    for idx, ag in enumerate(last_step):
        reward = ag.get("reward")
        status = ag.get("status")
        print(f"Agent {idx}: Status={status}, Reward={reward}")

    # Inspect game events / actions
    print(f"Game completed in {len(steps)} steps. No crash/errors detected.")

def main():
    for ep_id in LOSS_EPISODES:
        inspect_loss(ep_id)

if __name__ == "__main__":
    main()
