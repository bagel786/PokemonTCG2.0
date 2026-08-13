#!/usr/bin/env python3
"""Same-deck mirror baselines: D1 vs D1 and D1 vs D0 across actual orders."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.package_dipplin import safe_extract

PY = ROOT / ".venv" / "bin" / "python"
EVAL = ROOT / "training" / "evaluate_forced_order.py"
D1_ARCHIVE = ROOT / "artifacts" / "dipplin_d1" / "submission.tar.gz"
D1_A = ROOT / "artifacts" / "second_order" / "d1_copy_a"
D1_B = ROOT / "artifacts" / "second_order" / "d1_copy_b"
D0 = ROOT / "artifacts" / "dipplin_d0" / "extracted"
OUT = ROOT / "artifacts" / "second_order" / "mirror"


def ensure_sterile_copies() -> None:
    for dst in (D1_A, D1_B):
        if dst.exists():
            shutil.rmtree(dst)
        safe_extract(D1_ARCHIVE, dst)


def run_cell(name, hero, opponent, order, games, seed):
    output = OUT / f"{name}_{order}_{games}.json"
    if output.exists():
        data = json.loads(output.read_text())
        print(f"[skip] {output.name} win={data.get('win_rate'):.3f}", flush=True)
        return data
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [str(PY), str(EVAL), "--hero", str(hero), "--opponent", str(opponent),
           "--actual-order", order, "--games", str(games), "--workers", "8",
           "--seed", str(seed), "--output", str(output)]
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
    ensure_sterile_copies()
    OUT.mkdir(parents=True, exist_ok=True)
    results = {}
    seed = 20260901
    # D1 vs D1 mirror (intrinsic first-player advantage of this deck/policy).
    for order, games in (("first", 400), ("second", 400)):
        seed += 1
        results[f"d1v_d1_{order}"] = run_cell("d1v_d1", D1_A, D1_B, order, games, seed)
    # D1 vs D0 same-deck (archetype-independent policy strength).
    for order, games in (("first", 300), ("second", 300)):
        seed += 1
        results[f"d1v_d0_{order}"] = run_cell("d1v_d0", D1_A, D0, order, games, seed)
    (OUT / "summary.json").write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: (v.get("win_rate") if isinstance(v, dict) else v) for k, v in results.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
