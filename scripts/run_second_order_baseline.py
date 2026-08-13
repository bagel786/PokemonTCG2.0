#!/usr/bin/env python3
"""Run the current-D1 forced-order baseline against the four strong anchors.

Cells are run sequentially in one process.  Each cell uses a distinct schedule
seed; native deals remain unpaired.  Results land under
artifacts/second_order/baseline/.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "bin" / "python"
EVAL = ROOT / "training" / "evaluate_forced_order.py"
HERO = ROOT / "artifacts" / "dipplin_d1_incumbent"
OUT = ROOT / "artifacts" / "second_order" / "baseline"

OPPONENTS = {
    "a2": ROOT / "artifacts" / "dipplin_opponents" / "a2_exact",
    "d842": ROOT / "artifacts" / "dipplin_opponents" / "d842_exact",
    "az2_4a": ROOT / "freshstart" / "elite_submissions" / "alakazam_2_4a",
    "az2_7": ROOT / "freshstart" / "elite_submissions" / "alakazam_2_7",
}


def run_cell(name: str, opponent: Path, order: str, games: int, seed: int) -> dict:
    output = OUT / f"{name}_{order}_{games}.json"
    if output.exists():
        data = json.loads(output.read_text())
        print(f"[skip] {output.name} win_rate={data.get('win_rate')}", flush=True)
        return data
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(PY), str(EVAL),
        "--hero", str(HERO),
        "--opponent", str(opponent),
        "--actual-order", order,
        "--games", str(games),
        "--workers", "8",
        "--seed", str(seed),
        "--output", str(output),
    ]
    started = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.time() - started
    if proc.returncode != 0:
        print(f"[FAIL] {name} {order}: {proc.stderr[-2000:]}", flush=True)
        return {"name": name, "order": order, "error": proc.stderr[-2000:]}
    data = json.loads(output.read_text())
    print(f"[done] {name} {order} {games}g win={data['win_rate']:.3f} err={data['hero_policy_errors']} t={elapsed:.0f}s", flush=True)
    return data


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    results = {}
    seed = 20260812
    for name, opp in OPPONENTS.items():
        seed += 1
        results[f"{name}_second"] = run_cell(name, opp, "second", 200, seed)
        seed += 1
        results[f"{name}_first"] = run_cell(name, opp, "first", 100, seed)

    second_anchor = [
        results[f"{name}_second"]["win_rate"] for name in OPPONENTS
    ]
    first_anchor = [
        results[f"{name}_first"]["win_rate"] for name in OPPONENTS
    ]
    summary = {
        "second_anchor_macro": sum(second_anchor) / len(second_anchor),
        "first_anchor_macro": sum(first_anchor) / len(first_anchor),
        "cells": results,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "cells"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
