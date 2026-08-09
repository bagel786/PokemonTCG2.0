#!/usr/bin/env python3
"""Apply the B-family population gate and package only qualified finalists."""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_recovery_probes import build
from training.promotion import aggregate_shards, evaluate_final_gate


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def aggregate(pattern: str) -> dict:
    paths = sorted(glob.glob(pattern))
    if not paths:
        raise ValueError(f"no evaluation shards matched {pattern}")
    return aggregate_shards(paths)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="JSON candidate/model/matchup mapping")
    parser.add_argument("--output", default="artifacts/recovery_final/promotion_manifest.json")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    opponent_smoke = json.loads(
        (ROOT / "artifacts" / "recovery_final" / "opponents" / "smoke_manifest.json").read_text()
    )
    decisions, packages = {}, {}
    package_dir = ROOT / "artifacts" / "recovery_final" / "packages"
    for name, candidate in config["candidates"].items():
        matchups = {
            opponent: (aggregate(paths["candidate"]), aggregate(paths["control"]))
            for opponent, paths in candidate["matchups"].items()
        }
        decision = evaluate_final_gate(
            matchups, d842_name=candidate.get("d842_name", "d842"),
            grim_opponents=candidate.get("grim_opponents", []),
        )
        decisions[name] = decision
        decision["checks"]["opponent_population_smoke"] = opponent_smoke.get("passed") is True
        decision["passed"] = decision["passed"] and decision["checks"]["opponent_population_smoke"]
        if decision["passed"]:
            package = build(name, Path(candidate["model"]), package_dir)
            decision["checks"]["sterile_package_validation"] = package["sterile_validation"]["passed"]
            decision["passed"] = decision["passed"] and decision["checks"]["sterile_package_validation"]
            packages[name] = package
    qualified = sorted(
        (name for name, decision in decisions.items() if decision["passed"]),
        key=lambda name: decisions[name]["aggregate"]["one_sided_95_lower"],
        reverse=True,
    )
    manifest = {
        "created_unix": time.time(),
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "config": str(Path(args.config).resolve()),
        "config_sha256": sha256(Path(args.config)),
        "promotion_result": "passed" if qualified else "failed",
        "selected": qualified[0] if qualified else None,
        "contingency": qualified[1] if len(qualified) > 1 else None,
        "exact_upload_archive": packages[qualified[0]]["archive"] if qualified else None,
        "decisions": decisions,
        "packages": packages,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({key: manifest[key] for key in ("promotion_result", "selected", "contingency")}))
    return 0 if qualified else 2


if __name__ == "__main__":
    raise SystemExit(main())
