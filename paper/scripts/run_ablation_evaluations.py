#!/usr/bin/env python3
"""Run frozen C2 or C3 representation-ablation gameplay cells."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "artifacts/deterministic_engine/bin/libcg_seeded.dylib"
CONTROL = ROOT / "artifacts/grim_damage_conversion/winner/extracted"
PRODUCTION_ENGINE = ROOT / "vendor/cg/libcg.dylib"
RUNNER = ROOT / "training/evaluate_deterministic_crn.py"
CANDIDATES = {
    "c2_identity_a2": ROOT / "artifacts/grim_play_identity/candidates/p0",
    "c3_blind_trained": ROOT / "artifacts/paper_ablation/blind_trained_package",
}
OPPONENTS = {
    "grim_b0": {
        "path": ROOT / "artifacts/grim_variance_floor/candidates/B0",
        "seed": 202608230000, "workers": 8, "env": None,
    },
    "grim_d842_runtime": {
        "path": ROOT / "artifacts/overnight_20260816/d842_runtime",
        "seed": 202608231000, "workers": 8, "env": None,
    },
    "grim_master_v1": {
        "path": ROOT / "artifacts/grim_damage_conversion/opponents/master_v1",
        "seed": 202608232000, "workers": 8, "env": None,
    },
    "grim_replay_refresh": {
        "path": ROOT / "artifacts/grim_damage_conversion/opponents/replay_refresh",
        "seed": 202608233000, "workers": 8, "env": None,
    },
    "starmie": {
        "path": ROOT / "artifacts/sprint_870/opponents/starmie_v2_boss_atk",
        "seed": 202608234000, "workers": 4, "env": None,
    },
    "dipplin": {
        "path": ROOT / "artifacts/sprint_870/opponents/dipplin_d1",
        "seed": 202608235000, "workers": 4, "env": None,
    },
    "alakazam_no_search": {
        "path": ROOT / "artifacts/sprint_870/opponents/alakazam_2_4a",
        "seed": 202608236000, "workers": 8, "env": {"NO_SEARCH": "1"},
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cell", choices=sorted(CANDIDATES), required=True)
    parser.add_argument(
        "--opponents", nargs="+", choices=sorted(OPPONENTS),
        default=list(OPPONENTS),
    )
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "paper/data/ablation/raw",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    candidate = CANDIDATES[args.cell]
    if not candidate.is_dir():
        raise FileNotFoundError(candidate)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name in args.opponents:
        spec = OPPONENTS[name]
        output = args.output_dir / f"{args.cell}_{name}.json"
        command = [
            sys.executable, str(RUNNER), "paired",
            "--engine", str(ENGINE),
            "--candidate", str(candidate),
            "--control", str(CONTROL),
            "--opponent", str(spec["path"]),
            "--production-engine", str(PRODUCTION_ENGINE),
            "--output", str(output),
            "--base-seed", str(spec["seed"]),
            "--pairs-per-order", "200",
            "--actual-order", "both",
            "--workers", str(spec["workers"]),
            "--max-decisions", "2000",
        ]
        if spec["env"] is not None:
            command.extend(["--opponent-env", json.dumps(spec["env"], separators=(",", ":"))])
        print(json.dumps({"cell": args.cell, "opponent": name, "output": str(output)}), flush=True)
        completed = subprocess.run(command, cwd=ROOT, check=False)
        if completed.returncode:
            print(json.dumps({
                "status": "invalidated", "cell": args.cell,
                "opponent": name, "returncode": completed.returncode,
            }), file=sys.stderr, flush=True)
            return completed.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
