"""Fail-closed aggregation and promotion decisions for independent game shards."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Iterable

from .evaluation_schema import EvaluationSchemaError, load_evaluation


ONE_SIDED_Z_95 = 1.6448536269514722


def wilson_interval(wins: int, games: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if games <= 0:
        raise EvaluationSchemaError("cannot compute confidence interval with zero games")
    p = wins / games
    denom = 1 + z * z / games
    center = (p + z * z / (2 * games)) / denom
    radius = z * math.sqrt(p * (1 - p) / games + z * z / (4 * games * games)) / denom
    return center - radius, center + radius


def difference_lower_bound(a_wins: int, a_games: int, b_wins: int, b_games: int) -> float:
    """One-sided 95% lower bound for two independent binomial proportions."""
    if min(a_games, b_games) <= 0:
        raise EvaluationSchemaError("difference confidence bound requires nonzero samples")
    a = a_wins / a_games
    b = b_wins / b_games
    standard_error = math.sqrt(a * (1 - a) / a_games + b * (1 - b) / b_games)
    return (a - b) - ONE_SIDED_Z_95 * standard_error


def aggregate_shards(paths: Iterable[str | Path]) -> dict[str, Any]:
    rows = [load_evaluation(path) for path in paths]
    if not rows:
        raise EvaluationSchemaError("at least one evaluation shard is required")

    identity_keys = ("deck_a_sha256", "artifact_a_sha256", "deck_b_sha256", "artifact_b_sha256", "engine_sha256")
    identity = {key: rows[0]["artifact_provenance"].get(key) for key in identity_keys}
    provenance = {
        "source_bundle_sha256": rows[0]["artifact_provenance"]["source_bundle_sha256"],
        "source_commit": rows[0]["artifact_provenance"]["source_commit"],
    }
    for row in rows[1:]:
        observed = {key: row["artifact_provenance"].get(key) for key in identity_keys}
        if observed != identity:
            raise EvaluationSchemaError("artifact hash mismatch across evaluation shards")
        observed_provenance = {
            "source_bundle_sha256": row["artifact_provenance"]["source_bundle_sha256"],
            "source_commit": row["artifact_provenance"]["source_commit"],
        }
        if observed_provenance != provenance:
            raise EvaluationSchemaError("source provenance mismatch across evaluation shards")

    seeds = [row["artifact_provenance"]["seed"] for row in rows]
    if len(seeds) != len(set(seeds)):
        raise EvaluationSchemaError("evaluation shards contain duplicate seeds")

    games = sum(row["games"] for row in rows)
    wins = sum(row["wins_a"] for row in rows)
    seats = {}
    for seat in ("0", "1"):
        seat_games = sum(row["seat_results_a"][seat]["games"] for row in rows)
        seat_wins = sum(row["seat_results_a"][seat]["wins"] for row in rows)
        seats[seat] = {
            "games": seat_games,
            "wins": seat_wins,
            "win_rate": seat_wins / seat_games,
            "wilson_95": list(wilson_interval(seat_wins, seat_games)),
        }
    return {
        "shard_count": len(rows),
        "games": games,
        "wins": wins,
        "win_rate": wins / games,
        "wilson_95": list(wilson_interval(wins, games)),
        "seat_results": seats,
        "hero_policy_errors": sum(row["hero_policy_errors"] for row in rows),
        "opponent_policy_errors": sum(row["opponent_policy_errors"] for row in rows),
        "artifact_hashes": identity,
        "source_provenance": provenance,
        "source_commits": [provenance["source_commit"]],
        "workers": sorted({row["artifact_provenance"]["worker"] for row in rows}),
        "seeds": seeds,
    }


def _difference(candidate: dict[str, Any], control: dict[str, Any], seat: str | None = None) -> dict[str, float]:
    if seat is None:
        cw, cn = candidate["wins"], candidate["games"]
        bw, bn = control["wins"], control["games"]
    else:
        cw, cn = candidate["seat_results"][seat]["wins"], candidate["seat_results"][seat]["games"]
        bw, bn = control["seat_results"][seat]["wins"], control["seat_results"][seat]["games"]
    return {
        "difference": cw / cn - bw / bn,
        "one_sided_95_lower": difference_lower_bound(cw, cn, bw, bn),
    }


def _stratified_difference(
    matchups: dict[str, tuple[dict[str, Any], dict[str, Any]]],
    seat: str | None = None,
) -> dict[str, float | str]:
    """Independent-binomial difference with fixed opponent-stratum weights."""
    strata = []
    for name, (candidate, control) in matchups.items():
        if seat is None:
            cw, cn, bw, bn = candidate["wins"], candidate["games"], control["wins"], control["games"]
        else:
            cw = candidate["seat_results"][seat]["wins"]
            cn = candidate["seat_results"][seat]["games"]
            bw = control["seat_results"][seat]["wins"]
            bn = control["seat_results"][seat]["games"]
        if cn <= 0 or bn <= 0 or cn != bn:
            raise EvaluationSchemaError(f"candidate/control stratum size mismatch: {name}/seat={seat}")
        strata.append((cw, cn, bw, bn))
    total = sum(cn for _, cn, _, _ in strata)
    difference = 0.0
    variance = 0.0
    for cw, cn, bw, bn in strata:
        weight = cn / total
        candidate_rate, control_rate = cw / cn, bw / bn
        difference += weight * (candidate_rate - control_rate)
        variance += weight * weight * (
            candidate_rate * (1 - candidate_rate) / cn
            + control_rate * (1 - control_rate) / bn
        )
    return {
        "difference": difference,
        "one_sided_95_lower": difference - ONE_SIDED_Z_95 * math.sqrt(variance),
        "method": "opponent_stratified_independent_binomial",
    }


def evaluate_probe_gate(
    candidate: dict[str, Any],
    structural_control: dict[str, Any],
    authentic: dict[str, tuple[dict[str, Any], dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Evaluate the approved A1/A2 thresholds and return an explicit decision."""
    authentic = authentic or {}
    if (
        candidate["artifact_hashes"]["deck_b_sha256"] != structural_control["artifact_hashes"]["deck_b_sha256"]
        or candidate["artifact_hashes"]["artifact_b_sha256"] != structural_control["artifact_hashes"]["artifact_b_sha256"]
    ):
        raise EvaluationSchemaError("candidate and structural results do not use the same d842 opponent")
    comparisons = {
        "overall_vs_structural": _difference(candidate, structural_control),
        "seat_0_vs_structural": _difference(candidate, structural_control, "0"),
        "seat_1_vs_structural": _difference(candidate, structural_control, "1"),
    }
    authentic_results = {}
    for name, (candidate_result, control_result) in authentic.items():
        if (
            candidate_result["artifact_hashes"]["deck_b_sha256"] != control_result["artifact_hashes"]["deck_b_sha256"]
            or candidate_result["artifact_hashes"]["artifact_b_sha256"] != control_result["artifact_hashes"]["artifact_b_sha256"]
            or candidate_result["games"] != control_result["games"]
        ):
            raise EvaluationSchemaError(f"authentic matchup population mismatch: {name}")
        authentic_results[name] = _difference(candidate_result, control_result)

    checks = {
        "three_independent_10k_shards": candidate["shard_count"] == 3
        and candidate["games"] >= 30_000
        and len(set(candidate["seeds"])) == 3,
        "complete_structural_control": structural_control["shard_count"] == 3
        and structural_control["games"] >= 30_000
        and structural_control["hero_policy_errors"] == 0
        and structural_control["opponent_policy_errors"] == 0,
        "aggregate_win_rate_at_least_50_5": candidate["win_rate"] >= 0.505,
        "aggregate_wilson_lower_at_least_50": candidate["wilson_95"][0] >= 0.5,
        "seat_0_no_more_than_1_point_below_control": comparisons["seat_0_vs_structural"]["difference"] >= -0.01,
        "seat_1_at_least_1_point_above_control": comparisons["seat_1_vs_structural"]["difference"] >= 0.01,
        "seat_1_improvement_lower_bound_nonnegative": comparisons["seat_1_vs_structural"]["one_sided_95_lower"] >= 0,
        "zero_policy_errors": candidate["hero_policy_errors"] == 0 and candidate["opponent_policy_errors"] == 0,
        "authentic_regression_no_worse_than_2_points": bool(authentic_results)
        and all(row["difference"] >= -0.02 for row in authentic_results.values()),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "candidate": candidate,
        "structural_control": structural_control,
        "comparisons": comparisons,
        "authentic_opponents": authentic_results,
    }


def evaluate_final_gate(
    matchups: dict[str, tuple[dict[str, Any], dict[str, Any]]],
    *,
    d842_name: str = "d842",
    grim_opponents: Iterable[str] = (),
) -> dict[str, Any]:
    """Evaluate the approved B-family promotion thresholds."""
    if d842_name not in matchups:
        raise EvaluationSchemaError(f"missing required control matchup: {d842_name}")
    grim_names = set(grim_opponents)
    missing_grim = sorted(grim_names - set(matchups))
    if missing_grim:
        raise EvaluationSchemaError(f"missing retained Grim matchups: {missing_grim}")

    per_matchup = {}
    total_candidate = {"wins": 0, "games": 0, "seat0_wins": 0, "seat0_games": 0, "seat1_wins": 0, "seat1_games": 0}
    total_control = dict(total_candidate)
    zero_errors = True
    sample_checks = {}
    for name, (candidate, control) in matchups.items():
        per_matchup[name] = _difference(candidate, control)
        for prefix, result in (("candidate", candidate), ("control", control)):
            target = total_candidate if prefix == "candidate" else total_control
            target["wins"] += result["wins"]
            target["games"] += result["games"]
            target["seat0_wins"] += result["seat_results"]["0"]["wins"]
            target["seat0_games"] += result["seat_results"]["0"]["games"]
            target["seat1_wins"] += result["seat_results"]["1"]["wins"]
            target["seat1_games"] += result["seat_results"]["1"]["games"]
            zero_errors &= result["hero_policy_errors"] == 0 and result["opponent_policy_errors"] == 0
        minimum = 20_000 if name == d842_name else (10_000 if name in grim_names else 2_000)
        same_population = (
            candidate["artifact_hashes"]["deck_b_sha256"] == control["artifact_hashes"]["deck_b_sha256"]
            and candidate["artifact_hashes"]["artifact_b_sha256"] == control["artifact_hashes"]["artifact_b_sha256"]
            and candidate["artifact_hashes"]["engine_sha256"] == control["artifact_hashes"]["engine_sha256"]
            and candidate["source_provenance"] == control["source_provenance"]
            and candidate["games"] == control["games"]
            and candidate["seat_results"]["0"]["games"] == control["seat_results"]["0"]["games"]
            and candidate["seat_results"]["1"]["games"] == control["seat_results"]["1"]["games"]
        )
        sample_checks[name] = candidate["games"] >= minimum and control["games"] >= minimum and same_population

    overall = _stratified_difference(matchups)
    seat0 = _stratified_difference(matchups, "0")
    seat1 = _stratified_difference(matchups, "1")
    checks = {
        "minimum_games_per_matchup": all(sample_checks.values()),
        "aggregate_improvement_lower_at_least_1_5_points": overall["one_sided_95_lower"] >= 0.015,
        "seat_1_improvement_lower_at_least_2_points": seat1["one_sided_95_lower"] >= 0.02,
        "seat_0_noninferiority_lower_no_worse_than_minus_1_point": seat0["one_sided_95_lower"] >= -0.01,
        "no_matchup_regression_over_3_points": all(row["difference"] >= -0.03 for row in per_matchup.values()),
        "zero_policy_errors": zero_errors,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "sample_checks": sample_checks,
        "aggregate": overall,
        "seat_0": seat0,
        "seat_1": seat1,
        "matchups": per_matchup,
    }
