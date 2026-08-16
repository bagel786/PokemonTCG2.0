#!/usr/bin/env python3
"""Launch policy-zoo over EXP23 loss/win episodes (real file, spawn-safe)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, "/Users/safiullahbaig/Projects/pokemonTCG2.0-sprint")
from scripts.policy_zoo_loss_states import main as zoo_main

D = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0-overnight/data/replays/55556726")
meta = json.loads((D / "episodes_metadata.json").read_text())
losses, wins = [], []
for m in meta:
    agents = m["agents"]
    ours = next((i for i, a in enumerate(agents) if str(a.get("submissionId")) == "55556726"), None)
    if ours is None:
        continue
    rw = int(agents[ours].get("reward", 0))
    (losses if rw < 0 else wins).append((str(m["id"]), ours))
args = [f"55556726:{ep}:{seat},loss" for ep, seat in losses]
args += [f"55556726:{ep}:{seat},win" for ep, seat in wins[:6]]
sys.argv = ["policy_zoo", "--episodes"] + args + [
    "--output", "artifacts/global_swing_20260816/policy_zoo_exp23.json"
]
if __name__ == "__main__":
    raise SystemExit(zoo_main())
