#!/usr/bin/env python3
"""Recalculate manuscript toy examples independently of the artifact builder."""

from __future__ import annotations

import json
from pathlib import Path


FINAL = Path(__file__).resolve().parents[1]
REQUIRED_PROFILES = ("serial_forward", "serial_reverse", "parallel_forward")


def cluster_disagrees(
    projections: dict[str, tuple[str, int]],
    required_profiles: tuple[str, ...] = REQUIRED_PROFILES,
) -> bool:
    """Compare complete (digest, byte-count) records and fail closed."""
    if set(projections) != set(required_profiles):
        raise ValueError("required trace-projection profile is missing or unexpected")
    return len({projections[profile] for profile in required_profiles}) > 1


def main() -> int:
    profile_records = [
        dict.fromkeys(REQUIRED_PROFILES, ("a", 10)),
        {
            "serial_forward": ("b", 20),
            "serial_reverse": ("b", 20),
            "parallel_forward": ("c", 20),
        },
        dict.fromkeys(REQUIRED_PROFILES, ("d", 30)),
        {
            "serial_forward": ("e", 40),
            "serial_reverse": ("e", 41),
            "parallel_forward": ("e", 40),
        },
        dict.fromkeys(REQUIRED_PROFILES, ("g", 50)),
    ]
    trace_disagreement = sum(cluster_disagrees(row) for row in profile_records) / len(
        profile_records
    )
    byte_count_only_disagreement = cluster_disagrees(profile_records[3])
    try:
        cluster_disagrees(
            {
                "serial_forward": ("z", 60),
                "serial_reverse": ("z", 60),
            }
        )
    except ValueError:
        missing_profile_fail_closed = True
    else:
        missing_profile_fail_closed = False
    differences = [1, 0, -1]
    indices = [0, 0, 1]
    reweighting_example = sum(differences[index] for index in indices) / len(indices)
    mu_00, mu_10, mu_01, mu_11 = 0.50, 0.52, 0.51, 0.54
    result = {
        "status": "PASS",
        "trace_disagreement": trace_disagreement,
        "byte_count_only_disagreement": byte_count_only_disagreement,
        "missing_profile_fail_closed": missing_profile_fail_closed,
        "paired_difference": 1 - 0,
        "reweighting_replicate": reweighting_example,
        "factorial": {
            "total": mu_11 - mu_00,
            "representation": ((mu_10 - mu_00) + (mu_11 - mu_01)) / 2,
            "training": ((mu_01 - mu_00) + (mu_11 - mu_10)) / 2,
            "interaction": mu_11 - mu_10 - mu_01 + mu_00,
        },
    }
    expected = {
        "trace_disagreement": 0.4,
        "byte_count_only_disagreement": True,
        "missing_profile_fail_closed": True,
        "paired_difference": 1,
        "reweighting_replicate": 2 / 3,
        "factorial": {
            "total": 0.040000000000000036,
            "representation": 0.025000000000000022,
            "training": 0.015000000000000013,
            "interaction": 0.010000000000000009,
        },
    }
    for key in (
        "trace_disagreement",
        "byte_count_only_disagreement",
        "missing_profile_fail_closed",
        "paired_difference",
        "reweighting_replicate",
    ):
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
