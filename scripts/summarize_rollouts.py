#!/usr/bin/env python3
"""Audit rollout integrity and summarize games by opponent."""

from __future__ import annotations

import argparse
import gzip
import json
import math
from collections import Counter, defaultdict
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("rollouts")
    parser.add_argument("--output")
    args = parser.parse_args()

    decisions = trainable = 0
    trajectories: dict[str, tuple[str, float]] = {}
    policy_versions = Counter()
    schema_versions = Counter()
    invalid_logprobs = order_mismatches = index_errors = 0
    next_index: dict[str, int] = defaultdict(int)

    with gzip.open(args.rollouts, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            row = json.loads(line)
            decisions += 1
            trajectory_id = str(row["trajectory_id"])
            decision_index = int(row["decision_index"])
            if decision_index != next_index[trajectory_id]:
                index_errors += 1
            next_index[trajectory_id] = decision_index + 1
            action = [int(value) for value in row["action"]]
            if action != [int(value) for value in row["selection_order"]]:
                order_mismatches += 1
            if not math.isfinite(float(row["old_logprob"])):
                invalid_logprobs += 1
            if row.get("trainable"):
                trainable += 1
            opponent = str(row["opponent"])
            reward = float(row["return"])
            existing = trajectories.get(trajectory_id)
            if existing is not None and existing != (opponent, reward):
                raise ValueError(f"inconsistent trajectory metadata at line {line_number}")
            trajectories[trajectory_id] = (opponent, reward)
            policy_versions[str(row["policy_version"])] += 1
            schema_versions[str(row.get("model_schema_version", row.get("policy_version")))] += 1

    opponents: dict[str, dict[str, float | int]] = {}
    for opponent, reward in trajectories.values():
        bucket = opponents.setdefault(opponent, {"games": 0, "wins": 0, "win_rate": 0.0})
        bucket["games"] += 1
        bucket["wins"] += int(reward > 0.5)
    for bucket in opponents.values():
        bucket["win_rate"] = bucket["wins"] / bucket["games"]
    games = len(trajectories)
    wins = sum(int(reward > 0.5) for _, reward in trajectories.values())
    result = {
        "games": games,
        "wins": wins,
        "win_rate": wins / games if games else 0.0,
        "decisions": decisions,
        "trainable_decisions": trainable,
        "invalid_logprobs": invalid_logprobs,
        "selection_order_mismatches": order_mismatches,
        "decision_index_errors": index_errors,
        "policy_versions": dict(policy_versions),
        "schema_versions": dict(schema_versions),
        "opponents": dict(sorted(opponents.items())),
    }
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered)
    print(rendered, end="")
    if invalid_logprobs or order_mismatches or index_errors:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
