#!/usr/bin/env python3
import json
from pathlib import Path

def inspect_end(ep_id, sub_id):
    p = Path(f"data/replays/{sub_id}/episode-{ep_id}-replay.json")
    if not p.exists():
        p = Path(f"data/replays/{sub_id}/{ep_id}.json")
    if not p.exists():
        print(f"Missing {ep_id}")
        return
        
    data = json.loads(p.read_text())
    steps = data["steps"]
    print(f"\n====================================================================")
    print(f"EPISODE {ep_id} (Submission {sub_id}) - LAST 8 STEPS")
    print(f"====================================================================")
    for s_idx in range(max(0, len(steps)-8), len(steps)):
        step = steps[s_idx]
        print(f"Step {s_idx:3d}:")
        for seat in [0, 1]:
            ag = step[seat]
            st = ag.get('status')
            rw = ag.get('reward')
            act = ag.get('action')
            obs = ag.get('observation') or {}
            ov = obs.get('remainingOverageTime')
            curr = obs.get('current') or {}
            res = curr.get('result')
            print(f"  Seat {seat}: status={st}, reward={rw}, result={res}, overage={ov}, action={act}")

def main():
    print("--- 55180261 (5k ref) losses ---")
    for ep in [89476888, 89476983, 89478632, 89479194]:
        inspect_end(ep, 55180261)
        
    print("\n--- 55180215 (Gen4 sparred) losses ---")
    for ep in [89476878, 89478080, 89478636, 89479193]:
        inspect_end(ep, 55180215)

if __name__ == "__main__":
    main()
