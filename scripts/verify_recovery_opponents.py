#!/usr/bin/env python3
"""Fail closed on the smoke results for every final-gate opponent package."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from training.evaluation_schema import load_evaluation


def main() -> int:
    root = ROOT / "artifacts" / "recovery_final"
    opponents = json.loads((root / "opponents" / "manifest.json").read_text())
    expected = {
        **{name: row["artifact_tree_sha256"] for name, row in opponents["grim"].items()},
        **{name: row["artifact_tree_sha256"] for name, row in opponents["behavior_clones"].items()},
    }
    results, failures = {}, []
    for name, expected_hash in expected.items():
        path = root / f"smoke_{name}.json"
        try:
            row = load_evaluation(path)
            checks = {
                "at_least_two_games": row["games"] >= 2,
                "zero_policy_errors": row["hero_policy_errors"] == 0 and row["opponent_policy_errors"] == 0,
                "opponent_hash_matches": row["artifact_provenance"]["artifact_b_sha256"] == expected_hash.lower(),
            }
            results[name] = {"checks": checks, "result": str(path.resolve())}
            if not all(checks.values()):
                failures.append(name)
        except Exception as exc:
            failures.append(name)
            results[name] = {"error": f"{type(exc).__name__}: {exc}"}
    manifest = {"passed": not failures and set(results) == set(expected), "failures": failures, "results": results}
    output = root / "opponents" / "smoke_manifest.json"
    output.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"passed": manifest["passed"], "opponents": len(results), "failures": failures}))
    return 0 if manifest["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
