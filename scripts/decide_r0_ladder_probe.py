#!/usr/bin/env python3
"""Fail-closed provisional ladder decision for the R0 PLAY-binding probe."""

from __future__ import annotations

import argparse
import glob
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from training.evaluation_schema import load_evaluation, sha256_path


def wilson(wins: int, games: int, z: float = 1.96) -> tuple[float, float]:
    if games <= 0:
        raise ValueError("Wilson interval requires positive games")
    p = wins / games
    denominator = 1 + z * z / games
    center = (p + z * z / (2 * games)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * games)) / games) / denominator
    return center - margin, center + margin


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shards", default="artifacts/recovery_azure/shards/r0_*.json")
    parser.add_argument("--farm", default="artifacts/recovery_azure/farm_manifest_r0.json")
    parser.add_argument("--package", default="artifacts/recovery_r0_package/package_manifest.json")
    parser.add_argument("--output", default="artifacts/recovery_r0_package/provisional_promotion_manifest.json")
    args = parser.parse_args()

    paths = [Path(path) for path in sorted(glob.glob(args.shards))]
    rows = [load_evaluation(path) for path in paths]
    farm = json.loads(Path(args.farm).read_text(encoding="utf-8"))
    package = json.loads(Path(args.package).read_text(encoding="utf-8"))
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        names = list(row["opponent_results_a"])
        if len(names) != 1:
            raise ValueError("each R0 shard must contain exactly one opponent stratum")
        groups[names[0]].append(row)

    games = sum(row["games"] for row in rows)
    wins = sum(row["wins_a"] for row in rows)
    order = {
        name: {
            "games": sum(row["first_player_results_a"][name]["games"] for row in rows),
            "wins": sum(row["first_player_results_a"][name]["wins"] for row in rows),
        }
        for name in ("first", "second")
    }
    for values in order.values():
        values["win_rate"] = values["wins"] / values["games"]
        values["wilson_95"] = wilson(values["wins"], values["games"])
    opponents = {}
    for name, group in sorted(groups.items()):
        total = sum(row["games"] for row in group)
        group_wins = sum(row["wins_a"] for row in group)
        opponents[name] = {
            "shards": len(group), "games": total, "wins": group_wins,
            "win_rate": group_wins / total, "wilson_95": wilson(group_wins, total),
        }

    artifact_hashes = sorted({row["artifact_provenance"]["artifact_a_sha256"] for row in rows})
    engine_hashes = sorted({row["artifact_provenance"]["engine_sha256"] for row in rows})
    expected_tree = package["extracted_tree_sha256"].lower()
    measured_archive = sha256_path(package["archive"]).lower()
    expected_archive = package["archive_sha256"].lower()
    checks = {
        "farm_complete": farm.get("status") == "complete" and len(farm.get("results", [])) == 10,
        "ten_independent_shards": len(rows) == 10 and len({row["rng_provenance"]["python_numpy_seed_schedule"] for row in rows}) == 10,
        "exact_2000_games": games == 2000,
        "required_opponents": set(groups) == {"r0_a2", "r0_d842"},
        "five_shards_and_1000_games_each": all(
            values["shards"] == 5 and values["games"] == 1000 for values in opponents.values()
        ),
        "overall_point_at_least_52_5": wins / games >= 0.525,
        "overall_wilson_lower_above_50": wilson(wins, games)[0] > 0.50,
        "each_opponent_point_at_least_51_5": all(values["win_rate"] >= 0.515 for values in opponents.values()),
        "each_actual_order_point_at_least_50": all(values["win_rate"] >= 0.50 for values in order.values()),
        "balanced_actual_order": all(values["games"] == 1000 for values in order.values()),
        "zero_policy_errors": sum(row["hero_policy_errors"] + row["opponent_policy_errors"] for row in rows) == 0,
        "single_candidate_artifact": artifact_hashes == [expected_tree],
        "single_engine": len(engine_hashes) == 1,
        "archive_hash_matches": measured_archive == expected_archive,
        "sterile_package_passed": package.get("sterile_validation", {}).get("passed") is True,
        "search_disabled": package.get("search") is False,
    }
    passed = all(checks.values())
    result = {
        "status": "complete", "scope": "provisional_ladder_data_probe_only",
        "promotion_result": "passed" if passed else "failed",
        "checks": checks,
        "overall": {
            "games": games, "wins": wins, "win_rate": wins / games,
            "wilson_95": wilson(wins, games),
        },
        "actual_order": order, "opponents": opponents,
        "candidate_artifact_hashes": artifact_hashes, "engine_hashes": engine_hashes,
        "archive": package["archive"], "archive_sha256": measured_archive.upper(),
        "farm_manifest": str(Path(args.farm).resolve()),
        "evaluation_shards": [str(path.resolve()) for path in paths],
        "limitations": [
            "not a final promotion gate", "no qualified high-tier meta population",
            "no evidence of sustained public score above 1000",
        ],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
