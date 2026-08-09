"""Fail-closed statistical gates for the controlled dual-order 5k+ policy."""

from __future__ import annotations

import math
from typing import Any


Z_ONE_SIDED_95 = 1.6448536269514722
COMPARISON_EPSILON = 1e-12
FAST_MIN_AGGREGATE_UPLIFT = 0.02


def at_least(value: float, threshold: float) -> bool:
    """Inclusive threshold comparison robust to binary float round-off."""
    return float(value) >= float(threshold) - COMPARISON_EPSILON


def _finite(cell: dict[str, Any]) -> bool:
    return all(math.isfinite(float(cell[key])) for key in ("games", "wins", "win_rate"))


def difference(cell: dict[str, Any], control: dict[str, Any]) -> tuple[float, float]:
    p1 = float(cell["wins"]) / int(cell["games"])
    p0 = float(control["wins"]) / int(control["games"])
    standard_error = math.sqrt(p1 * (1 - p1) / int(cell["games"]) + p0 * (1 - p0) / int(control["games"]))
    return p1 - p0, p1 - p0 - Z_ONE_SIDED_95 * standard_error


def wilson_lower(wins: int, games: int) -> float:
    p = wins / games
    denominator = 1 + Z_ONE_SIDED_95**2 / games
    center = (p + Z_ONE_SIDED_95**2 / (2 * games)) / denominator
    margin = Z_ONE_SIDED_95 * math.sqrt((p * (1 - p) + Z_ONE_SIDED_95**2 / (4 * games)) / games) / denominator
    return center - margin


def pool(cells: list[dict[str, Any]]) -> dict[str, Any]:
    games = sum(int(cell["games"]) for cell in cells)
    wins = sum(int(cell["wins"]) for cell in cells)
    return {"games": games, "wins": wins, "win_rate": wins / games}


def zero_errors(*cells: dict[str, Any]) -> bool:
    return all(
        int(cell.get("hero_policy_errors", 0)) == 0
        and int(cell.get("opponent_policy_errors", 0)) == 0
        for cell in cells
    )


def fast_screen(candidate: dict[str, dict], control: dict[str, dict]) -> dict[str, Any]:
    if set(candidate) != set(control) or not candidate:
        raise ValueError("candidate/control fast-screen opponents are incomplete")
    deltas = {}
    valid = True
    for opponent in sorted(candidate):
        current, baseline = candidate[opponent], control[opponent]
        delta, lower = difference(current, baseline)
        deltas[opponent] = {"uplift": delta, "lower": lower}
        valid &= _finite(current) and _finite(baseline) and zero_errors(current, baseline) and at_least(delta, -0.03)
    aggregate, aggregate_lower = difference(pool(list(candidate.values())), pool(list(control.values())))
    non_regression_passed = bool(valid)
    strength_evidence_passed = (
        at_least(aggregate, FAST_MIN_AGGREGATE_UPLIFT)
        and aggregate_lower > 0.0
    )
    return {
        "passed": non_regression_passed and strength_evidence_passed,
        "non_regression_passed": non_regression_passed,
        "strength_evidence_passed": strength_evidence_passed,
        "opponents": deltas,
        "aggregate_uplift": aggregate, "aggregate_lower": aggregate_lower,
    }


def select_checkpoints(first: dict[str, Any], second: dict[str, dict[str, Any]]) -> dict[str, Any]:
    passing_second = {name: result for name, result in second.items() if result.get("passed")}
    if not passing_second:
        return {"passed": False, "reason": "no_second_checkpoint_passed"}
    selected_second = max(passing_second, key=lambda name: (passing_second[name]["aggregate_uplift"], name))
    trained_first = bool(first.get("passed") and float(first.get("aggregate_uplift", -1)) >= 0.01)
    return {
        "passed": True, "policy_first": "trained" if trained_first else "exact_d842",
        "policy_second": selected_second, "first_screen": first,
        "second_screens": second,
    }


def direct_gate(direct: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "direct_at_least_52_percent": at_least(float(direct["win_rate"]), 0.52),
        "direct_lower_above_50_percent": wilson_lower(int(direct["wins"]), int(direct["games"])) > 0.50,
        "zero_policy_errors": zero_errors(direct),
        "actual_order_accounting_complete": bool(direct.get("actual_order_accounting_complete", False)),
    }
    return {"passed": all(checks.values()), "checks": checks}


def confirmation_gate(payload: dict[str, Any]) -> dict[str, Any]:
    heldout = payload["heldout"]
    direct = payload["direct"]
    safety = payload["safety"]
    trained_first = bool(payload.get("trained_first"))
    heldout_pairs = []
    per_cell = {}
    for opponent in ("replay_refresh", "v2_2", "alakazam_2_7"):
        for order in ("first", "second"):
            candidate = heldout[opponent][order]["candidate"]
            control = heldout[opponent][order]["control"]
            delta, lower = difference(candidate, control)
            per_cell[f"{opponent}:{order}"] = {"uplift": delta, "lower": lower}
            heldout_pairs.append((opponent, order, candidate, control))
    represented_candidate = pool([row[2] for row in heldout_pairs])
    represented_control = pool([row[3] for row in heldout_pairs])
    represented_uplift, represented_lower = difference(represented_candidate, represented_control)
    second_pairs = [row for row in heldout_pairs if row[1] == "second"]
    second_uplift, second_lower = difference(pool([row[2] for row in second_pairs]), pool([row[3] for row in second_pairs]))
    first_pairs = [row for row in heldout_pairs if row[1] == "first"]
    first_uplift, first_lower = difference(pool([row[2] for row in first_pairs]), pool([row[3] for row in first_pairs]))
    safety_deltas = {name: difference(values["candidate"], values["control"])[0] for name, values in safety.items()}
    all_cells = [direct] + [row[2] for row in heldout_pairs] + [row[3] for row in heldout_pairs]
    all_cells += [cell for values in safety.values() for cell in values.values()]
    checks = {
        **direct_gate(direct)["checks"],
        "represented_meta_uplift_at_least_2_points": at_least(represented_uplift, 0.02),
        "represented_meta_lower_positive": represented_lower > 0.0,
        "actual_second_uplift_at_least_3_points": at_least(second_uplift, 0.03),
        "actual_second_lower_positive": second_lower > 0.0,
        "first_policy_gate": (at_least(first_uplift, 0.01) and at_least(first_lower, -0.005)) if trained_first else True,
        "no_heldout_cell_regresses_over_3_points": all(at_least(value["uplift"], -0.03) for value in per_cell.values()),
        "authentic_alakazam_no_regression_over_3_points": all(
            at_least(per_cell[f"alakazam_2_7:{order}"]["uplift"], -0.03) for order in ("first", "second")
        ),
        "no_safety_archetype_regresses_over_5_points": all(at_least(value, -0.05) for value in safety_deltas.values()),
        "zero_policy_errors": zero_errors(*all_cells),
        "actual_order_accounting_complete": all(bool(cell.get("actual_order_accounting_complete", False)) for cell in all_cells),
        "sterile_ubuntu": bool(payload.get("sterile_ubuntu")),
        "deterministic_replay": bool(payload.get("deterministic_replay")),
        "archive_hash_verified": bool(payload.get("archive_hash_verified")),
        "latency_passed": bool(payload.get("latency_passed")),
        "kaggle_self_play_passed": bool(payload.get("kaggle_self_play_passed")),
    }
    return {
        "passed": all(checks.values()), "label": "CONTROLLED_LADDER_PROBE",
        "checks": checks, "heldout_cells": per_cell,
        "represented_meta": {"uplift": represented_uplift, "lower": represented_lower},
        "actual_second": {"uplift": second_uplift, "lower": second_lower},
        "actual_first": {"uplift": first_uplift, "lower": first_lower, "trained": trained_first},
        "safety_uplift": safety_deltas,
    }
