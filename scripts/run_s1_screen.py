#!/usr/bin/env python3
"""Run the S1 SECOND_OPENING_V2 gross/forced-order screens.

The S1 candidate is the current D1 package extracted with
PTCG_DIPPLIN_SECOND_OPENING_V2=1 supplied via --hero-env.  Cells are sequential.
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
HERO = ROOT / "artifacts" / "dipplin_s1" / "extracted"
HERO_ENV = {"PTCG_DIPPLIN_SECOND_OPENING_V2": "1"}
OUT = ROOT / "artifacts" / "second_order" / "s1"

OPPONENTS = {
    "a2": ROOT / "artifacts" / "dipplin_opponents" / "a2_exact",
    "d842": ROOT / "artifacts" / "dipplin_opponents" / "d842_exact",
    "az2_4a": ROOT / "freshstart" / "elite_submissions" / "alakazam_2_4a",
    "az2_7": ROOT / "freshstart" / "elite_submissions" / "alakazam_2_7",
}


def run_cell(name, opponent, order, games, seed):
    output = OUT / f"{name}_{order}_{games}.json"
    if output.exists():
        data = json.loads(output.read_text())
        print(f"[skip] {output.name} win={data.get('win_rate'):.3f}", flush=True)
        return data
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(PY), str(EVAL),
        "--hero", str(HERO), "--opponent", str(opponent),
        "--actual-order", order, "--games", str(games), "--workers", "8",
        "--seed", str(seed), "--hero-env", json.dumps(HERO_ENV),
        "--output", str(output),
    ]
    started = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.time() - started
    if proc.returncode != 0:
        print(f"[FAIL] {name} {order}: {proc.stderr[-1500:]}", flush=True)
        return {"name": name, "order": order, "error": proc.stderr[-1500:]}
    data = json.loads(output.read_text())
    print(f"[done] {name} {order} {games}g win={data['win_rate']:.3f} err={data['hero_policy_errors']} t={elapsed:.0f}s", flush=True)
    return data


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    results = {}
    seed = 20260910
    for name, opp in OPPONENTS.items():
        seed += 1
        results[f"{name}_second"] = run_cell(name, opp, "second", 100, seed)
    second = [results[f"{name}_second"].get("win_rate", 0.0) for name in OPPONENTS]
    summary = {
        "second_anchor_macro": sum(second) / len(second),
        "cells": results,
    }
    (OUT / "gross_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "cells"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
