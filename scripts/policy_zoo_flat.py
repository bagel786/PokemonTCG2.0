#!/usr/bin/env python3
"""Policy zoo: c0/d842 consensus vs EXP23 recorded action on loss/win states."""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

OV = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0-overnight")
sys.path.insert(0, str(OV / "scripts" / "overnight_20260816"))
sys.path.insert(0, str(OV))
sys.path.insert(0, str(OV / "vendor"))
from replay_disagreement import _run_worker  # noqa: E402

C0 = "/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/grim_damage_conversion/winner/extracted"
D842 = "/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/overnight_20260816/d842_runtime"

REPLAYS = OV / "data" / "replays" / "55556726"
meta = json.loads((REPLAYS / "episodes_metadata.json").read_text())
units = []
for m in meta:
    agents = m["agents"]
    ours = next((i for i, a in enumerate(agents) if str(a.get("submissionId")) == "55556726"), None)
    if ours is None:
        continue
    rw = int(agents[ours].get("reward", 0))
    units.append({
        "path": str(REPLAYS / f"episode-{m['id']}-replay.json"),
        "seat": ours,
        "label": "loss" if rw < 0 else "win",
    })
units = [u for u in units if Path(u["path"]).exists()]
loss_units = [u for u in units if u["label"] == "loss"]
win_units = [u for u in units if u["label"] == "win"][:6]
chosen_units = loss_units + win_units

rows = []
for u in chosen_units:
    r_c0 = _run_worker({"package": C0, "episode": u["path"], "seat": u["seat"], "team": u["label"]})
    r_d842 = _run_worker({"package": D842, "episode": u["path"], "seat": u["seat"], "team": u["label"]})
    if r_c0.get("fatal") or r_d842.get("fatal"):
        print("fatal", u["path"], r_c0.get("fatal"), r_d842.get("fatal"), file=sys.stderr)
        continue
    c0_by_step = {rec["step"]: rec for rec in r_c0["records"]}
    d842_by_step = {rec["step"]: rec for rec in r_d842["records"]}
    for step, rec in c0_by_step.items():
        other = d842_by_step.get(step)
        if other is None:
            continue
        rows.append({
            "label": u["label"],
            "episode": Path(u["path"]).stem,
            "step": step,
            "context": rec["context"],
            "turn": rec["turn"],
            "forced": rec["forced"],
            "elite": rec["elite_action"],
            "c0": rec["package_action"],
            "d842": other["package_action"],
        })

total = Counter(r["label"] for r in rows)
consensus = Counter()
ctx = Counter()
band = Counter()
eps = defaultdict(set)
examples = []
for r in rows:
    if r["forced"]:
        continue
    if r["c0"] == r["d842"] and r["c0"] != r["elite"]:
        consensus[r["label"]] += 1
        ctx[(r["label"], r["context"])] += 1
        b = "early" if r["turn"] <= 6 else ("mid" if r["turn"] <= 14 else "late")
        band[(r["label"], b)] += 1
        eps[r["label"]].add(r["episode"])
        examples.append(r)

summary = {
    "units": len(chosen_units),
    "loss_units": len(loss_units),
    "win_units": len(win_units),
    "total_decisions": dict(total),
    "consensus_c0d842_vs_exp23": dict(consensus),
    "consensus_rate": {k: round(consensus[k] / max(1, total[k]), 4) for k in consensus},
    "consensus_by_ctx": {str(k): v for k, v in ctx.most_common(25)},
    "consensus_by_band": {str(k): v for k, v in band.most_common(12)},
    "distinct_episodes_with_consensus": {k: len(v) for k, v in eps.items()},
    "examples": examples[:12],
}
out = Path("artifacts/global_swing_20260816/policy_zoo_exp23.json")
out.write_text(json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n")
print(json.dumps({k: v for k, v in summary.items() if k != "examples"}, indent=1, default=str))
