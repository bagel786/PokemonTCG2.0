#!/usr/bin/env python3
"""Trace exact decision steps for specific key games."""

import json
from pathlib import Path
import csv

ROOT = Path(__file__).resolve().parents[1]
p = ROOT / "freshstart" / "data" / "EN_Card_Data.csv"
card_map = {}
if p.exists():
    reader = csv.DictReader(p.read_text(encoding="utf-8-sig").splitlines())
    for row in reader:
        cid = int(row.get("Card ID") or -1)
        name = row.get("Card Name") or f"Card_{cid}"
        card_map[cid] = name

def trace_episode(ep_id: int, hero_seat: int):
    f = ROOT / "data" / "replays" / "55283588" / f"episode-{ep_id}-replay.json"
    if not f.exists():
        f = ROOT / "data" / "replays" / "55283588" / f"{ep_id}.json"
    d = json.loads(f.read_text())
    steps = d["steps"]
    print(f"\n=======================================================")
    print(f"TRACING EPISODE {ep_id} (Hero Seat {hero_seat})")
    print(f"=======================================================")
    opp_seat = 1 - hero_seat

    for s_idx, step in enumerate(steps):
        h_ag = step[hero_seat]
        o_ag = step[opp_seat]

        h_act = h_ag.get("action")
        o_act = o_ag.get("action")

        h_obs = h_ag.get("observation", {})
        cur = h_obs.get("current") if isinstance(h_obs, dict) else None
        
        turn = cur.get("turn") if cur else None
        if h_act is not None and h_act != [] and h_act != "":
            print(f"[Step {s_idx:03d} | Turn {turn}] HERO Action: {h_act}")
        if o_act is not None and o_act != [] and o_act != "":
            print(f"[Step {s_idx:03d} | Turn {turn}] OPP Action: {o_act}")

if __name__ == "__main__":
    trace_episode(90303182, 0)
    trace_episode(90326666, 0)
