#!/usr/bin/env python3
"""Recalculate manuscript toy examples independently of the artifact builder."""

from __future__ import annotations

import json
from pathlib import Path


FINAL = Path(__file__).resolve().parents[1]


def main() -> int:
    profile_hashes = [
        ["a", "a", "a"],
        ["b", "b", "c"],
        ["d", "d", "d"],
        ["e", "f", "e"],
        ["g", "g", "g"],
    ]
    trace_disagreement = sum(len(set(row)) > 1 for row in profile_hashes) / len(profile_hashes)
    differences = [1, 0, -1]
    indices = [0, 0, 1]
    bootstrap_example = sum(differences[index] for index in indices) / len(indices)
    mu_00, mu_10, mu_01, mu_11 = 0.50, 0.52, 0.51, 0.54
    result = {
        "status": "PASS",
        "trace_disagreement": trace_disagreement,
        "paired_difference": 1 - 0,
        "bootstrap_replicate": bootstrap_example,
        "factorial": {
            "total": mu_11 - mu_00,
            "representation": ((mu_10 - mu_00) + (mu_11 - mu_01)) / 2,
            "training": ((mu_01 - mu_00) + (mu_11 - mu_10)) / 2,
            "interaction": mu_11 - mu_10 - mu_01 + mu_00,
        },
    }
    expected = {
        "trace_disagreement": 0.4,
        "paired_difference": 1,
        "bootstrap_replicate": 2 / 3,
        "factorial": {
            "total": 0.040000000000000036,
            "representation": 0.025000000000000022,
            "training": 0.015000000000000013,
            "interaction": 0.010000000000000009,
        },
    }
    for key in ("trace_disagreement", "paired_difference", "bootstrap_replicate"):
        if result[key] != expected[key]:
            raise ValueError(f"equation example failed: {key}")
    if result["factorial"] != expected["factorial"]:
        raise ValueError("factorial equation example failed")
    output = FINAL / "source_data/equation_examples.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
