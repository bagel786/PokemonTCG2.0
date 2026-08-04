#!/usr/bin/env python3
"""Inspect exact sequence of events in loss replays."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def inspect_sub_losses(sub_id: int, num_samples: int = 4):
    sub_dir = ROOT / "data" / "replays" / str(sub_id)
    meta = json.loads((sub_dir / "episodes_metadata.json").read_text())

    losses = []
    for ep in meta:
        agents = ep.get("agents", [])
        for idx, ag in enumerate(agents):
            if ag.get("submissionId") == sub_id and ag.get("reward") in (-1, 0):
                losses.append((ep.get("id"), idx, 1 - idx))

    print(f"\nSub {sub_id}: Found {len(losses)} losses. Inspecting {min(num_samples, len(losses))} sample replays:")

    for ep_id, our_idx, opp_idx in losses[:num_samples]:
        rp_file = sub_dir / f"episode-{ep_id}-replay.json"
        if not rp_file.exists():
            rp_file = sub_dir / f"{ep_id}.json"
        if not rp_file.exists():
            continue

        rp = json.loads(rp_file.read_text())
        steps = rp.get("steps", [])
        print(f"\n--- Episode {ep_id} (Our Seat: {our_idx}) | Total Steps: {len(steps)} ---")

        for s_idx in range(min(12, len(steps))):
            st = steps[s_idx]
            our_act = st[our_idx].get("action")
            opp_act = st[opp_idx].get("action")
            our_obs = st[our_idx].get("observation", {}).get("current", {})
            turn = our_obs.get("turn", -1) if isinstance(our_obs, dict) else -1
            players = our_obs.get("players", []) if isinstance(our_obs, dict) else []

            our_b_count = 0
            our_act_name = "None"
            opp_act_name = "None"
            if len(players) > our_idx and isinstance(players[our_idx], dict):
                our_p = players[our_idx]
                our_b_count = len(our_p.get("bench", []))
                active_list = our_p.get("active", [])
                our_act_name = str(active_list[0].get("id")) if (active_list and isinstance(active_list[0], dict)) else "EMPTY"
            if len(players) > opp_idx and isinstance(players[opp_idx], dict):
                opp_p = players[opp_idx]
                opp_active_list = opp_p.get("active", [])
                opp_act_name = str(opp_active_list[0].get("id")) if (opp_active_list and isinstance(opp_active_list[0], dict)) else "EMPTY"

            print(f"Step {s_idx:02d} [Turn {turn}]: OurAction={our_act} | OppAction={opp_act} | Us Active={our_act_name}, Bench={our_b_count} | Opp Active={opp_act_name}")

        # Check last step
        last_st = steps[-1]
        print(f"Last Step {len(steps)-1}: Us status={last_st[our_idx].get('status')}, reward={last_st[our_idx].get('reward')}")


if __name__ == "__main__":
    inspect_sub_losses(55180261, num_samples=3)
    inspect_sub_losses(55180215, num_samples=3)
