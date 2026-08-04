#!/usr/bin/env python3
"""Compare a challenger to an independent identical-policy structural control."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from training.evaluate import wilson


def newcombe_difference(wins_a: int, games_a: int, wins_b: int, games_b: int, z: float = 1.96):
    """Newcombe score interval for independent proportions p_a - p_b."""
    if not games_a or not games_b:
        return -1.0, 1.0
    pa, pb = wins_a / games_a, wins_b / games_b
    la, ua = wilson(wins_a, games_a, z)
    lb, ub = wilson(wins_b, games_b, z)
    lower = pa - pb - math.sqrt((pa - la) ** 2 + (ub - pb) ** 2)
    upper = pa - pb + math.sqrt((ua - pa) ** 2 + (pb - lb) ** 2)
    return lower, upper


def structural_lift(control: dict, challenger: dict, noninferiority: float = -0.005) -> dict:
    strata = {}
    reasons = []
    mappings = (
        ("seat_0", "seat_results_a", "0"),
        ("seat_1", "seat_results_a", "1"),
        ("went_first", "first_player_results_a", "first"),
        ("went_second", "first_player_results_a", "second"),
    )
    for label, field, key in mappings:
        baseline = control[field][key]
        current = challenger[field][key]
        lift = current["win_rate"] - baseline["win_rate"]
        interval = newcombe_difference(
            current["wins"], current["games"], baseline["wins"], baseline["games"]
        )
        passed = lift > 0.0 and interval[0] >= noninferiority
        strata[label] = {
            "control": baseline,
            "challenger": current,
            "lift": lift,
            "newcombe_95": list(interval),
            "passed": passed,
        }
        if not passed:
            reasons.append(f"{label}: lift={lift:.6f}, lower95={interval[0]:.6f}")
    overall_passed = challenger["wilson_95"][0] > 0.50
    if not overall_passed:
        reasons.append(f"overall lower95={challenger['wilson_95'][0]:.6f}")
    errors = challenger.get("hero_policy_errors", 0) + challenger.get("opponent_policy_errors", 0)
    if errors:
        reasons.append(f"policy_errors={errors}")
    return {
        "passed": not reasons,
        "overall_superiority_passed": overall_passed,
        "noninferiority_margin": noninferiority,
        "strata": strata,
        "policy_errors": errors,
        "reasons": reasons,
        "rng_provenance": {
            "paired_deals": False,
            "reason": "official BattleStart seeds its native engine with std::random_device",
            "comparison": "independent_proportions",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--control", required=True)
    parser.add_argument("--challenger", required=True)
    parser.add_argument("--noninferiority", type=float, default=-0.005)
    parser.add_argument("--output")
    args = parser.parse_args()
    result = structural_lift(
        json.loads(Path(args.control).read_text()),
        json.loads(Path(args.challenger).read_text()),
        args.noninferiority,
    )
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
