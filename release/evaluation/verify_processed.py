#!/usr/bin/env python3
"""Verify the sanitized canonical data against the frozen statistical summary."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/processed"
REQUIRED = {
    "experiment", "candidate_hash", "control_hash", "opponent", "opponent_hash",
    "seed", "actual_order", "candidate_outcome", "control_outcome",
    "candidate_error", "control_error", "latency_candidate_ms",
    "latency_control_ms", "source_artifact",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def exact_mcnemar(candidate_only: int, control_only: int) -> float:
    total = candidate_only + control_only
    if not total:
        return 1.0
    lower = min(candidate_only, control_only)
    return min(1.0, 2 * sum(math.comb(total, index) for index in range(lower + 1)) / 2 ** total)


def main() -> int:
    canonical_path = DATA / "canonical_results.csv"
    summary_path = DATA / "statistical_summary.json"
    with canonical_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not REQUIRED.issubset(reader.fieldnames or []):
            raise ValueError(f"canonical schema missing: {sorted(REQUIRED - set(reader.fieldnames or []))}")
        rows = [row for row in reader if row["experiment"] == "fresh_confirmation"]
    if len(rows) != 2_800:
        raise ValueError(f"expected 2800 fresh pairs, found {len(rows)}")
    strata = Counter((row["opponent"], row["actual_order"]) for row in rows)
    if len(strata) != 14 or set(strata.values()) != {200}:
        raise ValueError(f"unbalanced fresh strata: {strata}")
    differences = [int(row["candidate_win"]) - int(row["control_win"]) for row in rows]
    candidate_only = sum(value == 1 for value in differences)
    control_only = sum(value == -1 for value in differences)
    candidate_wins = sum(int(row["candidate_win"]) for row in rows)
    control_wins = sum(int(row["control_win"]) for row in rows)
    errors = sum(
        int(row["candidate_error"]) + int(row["control_error"])
        + int(row["candidate_opponent_error"]) + int(row["control_opponent_error"])
        for row in rows
    )
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    primary = summary["fresh_confirmation"]["primary"]
    checks = {
        "canonical_sha256": sha256(canonical_path) == summary["canonical_sha256"],
        "effect": math.isclose(sum(differences) / len(differences), primary["effect"], abs_tol=1e-15),
        "candidate_wins": candidate_wins == primary["candidate_wins"],
        "control_wins": control_wins == primary["control_wins"],
        "candidate_only": candidate_only == primary["candidate_only_wins"],
        "control_only": control_only == primary["control_only_wins"],
        "mcnemar": math.isclose(
            exact_mcnemar(candidate_only, control_only),
            primary["mcnemar_exact_two_sided_p"], abs_tol=1e-15,
        ),
        "errors_zero": errors == 0,
    }
    if not all(checks.values()):
        raise AssertionError(checks)
    print(json.dumps({
        "status": "verified",
        "fresh_pairs": len(rows),
        "strata": len(strata),
        "effect": primary["effect"],
        "discordant": [candidate_only, control_only],
        "checks": checks,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
