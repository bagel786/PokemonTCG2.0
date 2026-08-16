#!/usr/bin/env python3
"""Check DIP_B mirror losses: did the Dipplin route fire? did dip_b fire?"""
import json
import sys
from pathlib import Path

SPRINT = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0-sprint")
sys.path.insert(0, str(SPRINT))
sys.path.insert(0, str(SPRINT / "vendor"))
from cg.api import to_observation_class, SelectContext  # noqa: E402
from ptcg_ai.external import ExternalSubmissionAgent  # noqa: E402

DIPB = "/Users/safiullahbaig/Projects/pokemonTCG2.0-anti-meta/artifacts/anti_meta_20260816/packages/exp23_dip_surgical"
REPLAYS = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0-overnight/data/replays/55562629")

EPISODES = [93749272, 93747403, 93745625, 93742882, 93741971, 93741076, 93740206, 93739304, 93738399, 93738302]

agent = ExternalSubmissionAgent(DIPB, {})
for ep in EPISODES:
    path = REPLAYS / f"episode-{ep}-replay.json"
    if not path.exists():
        continue
    data = json.loads(path.read_text())
    steps = data.get("steps") or []
    meta_list = json.loads((REPLAYS / "episodes_metadata.json").read_text())
    seat = next(
        i for m in meta_list if str(m["id"]) == str(ep)
        for i, a in enumerate(m["agents"]) if str(a.get("submissionId")) == "55562629"
    )
    route_seen = set()
    fires = []
    for step_index in range(len(steps) - 1):
        row = steps[step_index]
        entry = row[seat] if row and seat < len(row) else None
        obs = (entry or {}).get("observation") or {}
        if not obs.get("select") or not obs.get("current"):
            continue
        act = agent(obs)
        ag = agent.module._AGENT
        route_seen.add(ag.route)
        fires.extend(list(ag.surgical.fires))
    print(f"ep{ep}: routes_seen={sorted(str(r) for r in route_seen)} surgical_fires={len(fires)}")
    for f in fires[:3]:
        print("   ", json.dumps(f)[:150])
agent.close()
