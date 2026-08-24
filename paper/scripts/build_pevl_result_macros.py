#!/usr/bin/env python3
"""Build fail-closed LaTeX macros from terminal prospective PEVL analyses."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "paper/data/pevl"
DEFAULT_PREFLIGHT = DATA / "trace_preflight_summary.json"
DEFAULT_STRESS = DATA / "timed_search_stress_summary.json"
DEFAULT_FACTORIAL = DATA / "factorial_summary.json"
DEFAULT_COMBINED = DATA / "summary.json"
DEFAULT_OUTPUT = ROOT / "paper/pevl_results_macros.tex"

PREFLIGHT_ARMS = ("C1", "C2", "C3", "C4")
DETERMINISTIC_OPPONENTS = (
    "b0",
    "d842",
    "master",
    "replay",
    "alakazam_no_search",
)
TIMED_OPPONENTS = ("starmie", "dipplin")
ORDERS = ("first", "second")
STRESS_RUNS = (
    "serial_forward",
    "serial_reverse",
    "parallel_forward",
    "parallel_reverse",
)
STRESS_STRATA = tuple(
    f"{opponent}/{order}" for opponent in TIMED_OPPONENTS for order in ORDERS
)
CONTRASTS = (
    "primary_c4_minus_c1",
    "representation_main",
    "training_main",
    "interaction",
)
SIMPLE_EFFECTS = (
    "c2_minus_c1",
    "c3_minus_c1",
    "c4_minus_c1",
    "c4_minus_c2",
    "c4_minus_c3",
)
TERMINAL_FACTORIAL_STATUSES = {
    "ADMITTED_SEED_MATCHED",
    "SUPPRESSED_BY_PREFLIGHT",
    "SUPPRESSED_CONTROL_PARITY_FAILURE",
}
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
MACRO_NAME_RE = re.compile(r"[A-Za-z]+\Z")


class MacroInputError(ValueError):
    """Raised when analysis artifacts cannot support publication macros."""


def load_artifact(path: Path, label: str) -> tuple[dict[str, Any], str]:
    if not path.is_file():
        raise MacroInputError(f"missing {label}: {path}")
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MacroInputError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise MacroInputError(f"{label} must be a JSON object")
    return payload, hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_header(payload: Mapping[str, Any], analysis_id: str) -> None:
    if payload.get("schema_version") != 1 or payload.get("analysis_id") != analysis_id:
        raise MacroInputError(
            f"expected schema_version=1 analysis_id={analysis_id}, got "
            f"{payload.get('schema_version')!r}/{payload.get('analysis_id')!r}"
        )


def require_object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise MacroInputError(f"{label} must be an object")
    return value


def require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise MacroInputError(f"{label} must be an array")
    return value


def require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MacroInputError(f"{label} must be a nonempty string")
    return value


def require_bool(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise MacroInputError(f"{label} must be boolean")
    return value


def require_int(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise MacroInputError(f"{label} must be an integer >= {minimum}")
    return value


def require_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MacroInputError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise MacroInputError(f"{label} must be finite")
    return result


def require_probability(value: Any, label: str) -> float:
    result = require_number(value, label)
    if not 0.0 <= result <= 1.0:
        raise MacroInputError(f"{label} must be in [0, 1]")
    return result


def require_effect(value: Any, label: str) -> float:
    result = require_number(value, label)
    if not -1.0 <= result <= 1.0:
        raise MacroInputError(f"{label} must be in [-1, 1]")
    return result


def require_interval(value: Any, label: str, *, effect: bool = False) -> tuple[float, float]:
    interval = require_list(value, label)
    if len(interval) != 2:
        raise MacroInputError(f"{label} must contain exactly two endpoints")
    converter = require_effect if effect else require_probability
    low = converter(interval[0], f"{label} lower")
    high = converter(interval[1], f"{label} upper")
    if low > high:
        raise MacroInputError(f"{label} endpoints are reversed")
    return low, high


def require_sha256(value: Any, label: str) -> str:
    text = require_string(value, label)
    if SHA256_RE.fullmatch(text) is None:
        raise MacroInputError(f"{label} must be a lowercase SHA-256 digest")
    return text


def require_exact(value: Any, expected: Any, label: str) -> None:
    if value != expected:
        raise MacroInputError(f"{label} must be {expected!r}, got {value!r}")


def validate_rate_summary(
    value: Any,
    label: str,
    *,
    clusters: int,
    disagreements: int,
) -> dict[str, Any]:
    summary = require_object(value, label)
    require_exact(summary.get("clusters"), clusters, f"{label} clusters")
    require_exact(summary.get("bootstrap_draws"), 100_000, f"{label} bootstrap draws")
    require_exact(summary.get("bootstrap_seed"), 2026083118, f"{label} bootstrap seed")
    estimate = require_probability(summary.get("estimate"), f"{label} estimate")
    low, high = require_interval(summary.get("bootstrap_95_ci"), f"{label} interval")
    expected = disagreements / clusters
    if not math.isclose(estimate, expected, rel_tol=0.0, abs_tol=1e-12):
        raise MacroInputError(f"{label} estimate does not reproduce its disagreement count")
    if not low <= estimate <= high:
        raise MacroInputError(f"{label} estimate falls outside its interval")
    return {
        "clusters": clusters,
        "disagreements": disagreements,
        "estimate": estimate,
        "interval": (low, high),
    }


def validate_preflight(payload: dict[str, Any]) -> dict[str, Any]:
    require_header(payload, "trace_preflight")
    status = payload.get("status")
    if status not in {"PASS", "FAIL"}:
        raise MacroInputError(f"trace preflight is not terminal: {status!r}")
    require_exact(payload.get("arms"), 4, "preflight arms")
    require_exact(payload.get("opponents"), 5, "preflight opponents")
    require_exact(payload.get("trajectory_units"), 1_000, "preflight trajectory units")
    require_exact(payload.get("executions"), 3_000, "preflight executions")
    mismatches = require_int(payload.get("mismatch_units"), "preflight mismatches")
    commit = require_string(payload.get("protocol_commit"), "preflight protocol commit")
    rows = require_list(payload.get("rows"), "preflight rows")
    if len(rows) != 20:
        raise MacroInputError("preflight must contain 20 arm/opponent rows")
    seen: set[tuple[str, str]] = set()
    row_mismatches = 0
    endpoint_fields = {
        "trace": "trace_mismatch_units",
        "outcome": "outcome_mismatch_units",
        "error": "error_mismatch_units",
        "decision": "decision_count_mismatch_units",
    }
    endpoint_totals = Counter()
    any_failure = False
    for index, raw_row in enumerate(rows):
        row = require_object(raw_row, f"preflight row {index}")
        arm = require_string(row.get("arm"), f"preflight row {index} arm")
        opponent = require_string(row.get("opponent"), f"preflight row {index} opponent")
        if arm not in PREFLIGHT_ARMS or opponent not in DETERMINISTIC_OPPONENTS:
            raise MacroInputError(f"preflight row {index} has an unexpected arm/opponent")
        key = (arm, opponent)
        if key in seen:
            raise MacroInputError(f"duplicate preflight row {key}")
        seen.add(key)
        require_exact(row.get("trajectory_units"), 50, f"preflight {key} units")
        require_exact(row.get("executions"), 150, f"preflight {key} executions")
        row_mismatch = require_int(row.get("mismatch_units"), f"preflight {key} mismatches")
        row_endpoint_counts = {
            endpoint: require_int(
                row.get(field), f"preflight {key} {field}"
            )
            for endpoint, field in endpoint_fields.items()
        }
        if any(value > row_mismatch for value in row_endpoint_counts.values()):
            raise MacroInputError(
                f"preflight {key} endpoint mismatches exceed aggregate mismatches"
            )
        passed = require_bool(row.get("passed"), f"preflight {key} passed")
        require_sha256(row.get("source_sha256"), f"preflight {key} source digest")
        require_string(row.get("source"), f"preflight {key} source")
        row_mismatches += row_mismatch
        endpoint_totals.update(row_endpoint_counts)
        any_failure = any_failure or not passed or row_mismatch > 0
    expected_rows = {
        (arm, opponent) for arm in PREFLIGHT_ARMS for opponent in DETERMINISTIC_OPPONENTS
    }
    if seen != expected_rows or row_mismatches != mismatches:
        raise MacroInputError("preflight rows do not reproduce the frozen inventory/totals")
    for endpoint, field in endpoint_fields.items():
        require_exact(
            payload.get(field),
            endpoint_totals[endpoint],
            f"preflight aggregate {field}",
        )
    expected_decision = "admit_factorial_acquisition" if status == "PASS" else "suppress_factorial"
    require_exact(payload.get("admission_decision"), expected_decision, "preflight admission")
    if status == "PASS" and (any_failure or mismatches):
        raise MacroInputError("PASS preflight contains a failed or mismatched row")
    if status == "FAIL" and not any_failure:
        raise MacroInputError("FAIL preflight contains no failed row")
    return {
        "status": status,
        "protocol_commit": commit,
        "mismatches": mismatches,
        "endpoint_mismatches": dict(endpoint_totals),
    }


def validate_stress(payload: dict[str, Any]) -> dict[str, Any]:
    require_header(payload, "timed_search_stress")
    status = payload.get("status")
    if status not in {"TRACE_PARITY", "TRACE_DIVERGENCE"}:
        raise MacroInputError(f"timed-search stress analysis is not terminal: {status!r}")
    require_exact(payload.get("clusters"), 200, "stress clusters")
    require_exact(payload.get("executions"), 800, "stress executions")
    commit = require_string(payload.get("protocol_commit"), "stress protocol commit")
    aggregate_fields = {
        "trace": "trace_disagreement_clusters",
        "outcome": "outcome_disagreement_clusters",
        "decision": "decision_count_disagreement_clusters",
        "error": "error_disagreement_clusters",
        "policy": "policy_error_present_clusters",
    }
    aggregates = {
        name: require_int(payload.get(field), f"stress {field}")
        for name, field in aggregate_fields.items()
    }
    if any(value > 200 for value in aggregates.values()):
        raise MacroInputError("a stress disagreement count exceeds 200 clusters")

    cluster_rows = require_list(payload.get("cluster_rows"), "stress cluster rows")
    if len(cluster_rows) != 200:
        raise MacroInputError("stress must contain 200 cluster rows")
    seen: set[tuple[str, str]] = set()
    derived = Counter()
    derived_by_stratum: dict[str, Counter[str]] = {
        stratum: Counter() for stratum in STRESS_STRATA
    }
    divergence_actors: Counter[str] = Counter()
    divergence_lines: list[int] = []
    for index, raw_row in enumerate(cluster_rows):
        row = require_object(raw_row, f"stress cluster row {index}")
        opponent = require_string(row.get("opponent"), f"stress row {index} opponent")
        order = require_string(row.get("actual_order"), f"stress row {index} order")
        task_id = require_string(row.get("task_id"), f"stress row {index} task")
        if opponent not in TIMED_OPPONENTS or order not in ORDERS:
            raise MacroInputError(f"stress row {index} has an unexpected opponent/order")
        key = (opponent, task_id)
        if key in seen:
            raise MacroInputError(f"duplicate stress cluster {key}")
        seen.add(key)
        flags = {
            "trace": require_bool(row.get("trace_disagreement"), f"stress row {index} trace"),
            "outcome": require_bool(row.get("outcome_disagreement"), f"stress row {index} outcome"),
            "decision": require_bool(
                row.get("decision_count_disagreement"), f"stress row {index} decision"
            ),
            "error": require_bool(row.get("error_disagreement"), f"stress row {index} error"),
            "policy": require_bool(row.get("policy_error_present"), f"stress row {index} policy"),
        }
        require_exact(
            row.get("all_four_trace_agree"),
            not flags["trace"],
            f"stress row {index} trace agreement",
        )
        stratum = f"{opponent}/{order}"
        derived_by_stratum[stratum]["clusters"] += 1
        for name, flag in flags.items():
            derived[name] += int(flag)
            derived_by_stratum[stratum][name] += int(flag)
        divergence = row.get("first_divergence")
        if flags["trace"]:
            detail = require_object(divergence, f"stress row {index} first divergence")
            divergence_lines.append(
                require_int(detail.get("trace_line"), f"stress row {index} divergence line")
            )
            actors = require_list(detail.get("actors"), f"stress row {index} divergence actors")
            for actor in actors:
                divergence_actors[require_string(actor, f"stress row {index} actor")] += 1
        elif divergence is not None:
            raise MacroInputError(f"stress row {index} localizes a nonexistent trace mismatch")
    expected_tasks = {
        (opponent, f"{order}-{seed:03d}")
        for opponent in TIMED_OPPONENTS
        for order in ORDERS
        for seed in range(50)
    }
    if seen != expected_tasks:
        raise MacroInputError("stress cluster rows do not match the frozen task inventory")
    if any(derived[name] != aggregates[name] for name in aggregate_fields):
        raise MacroInputError("stress cluster rows do not reproduce aggregate counts")
    if (status == "TRACE_DIVERGENCE") != (aggregates["trace"] > 0):
        raise MacroInputError("stress status contradicts the trace-disagreement count")

    overall_rate = validate_rate_summary(
        payload.get("trace_disagreement"),
        "overall stress trace disagreement",
        clusters=200,
        disagreements=aggregates["trace"],
    )
    strata = require_object(payload.get("strata"), "stress strata")
    if set(strata) != set(STRESS_STRATA):
        raise MacroInputError("stress strata do not match the four frozen strata")
    validated_strata: dict[str, dict[str, Any]] = {}
    stratum_field_map = {
        "outcome": "outcome_disagreement_count",
        "decision": "decision_count_disagreement_count",
        "error": "error_disagreement_count",
        "policy": "policy_error_present_count",
    }
    for stratum in STRESS_STRATA:
        row = require_object(strata[stratum], f"stress stratum {stratum}")
        counts = derived_by_stratum[stratum]
        if counts["clusters"] != 50:
            raise MacroInputError(f"stress stratum {stratum} does not contain 50 clusters")
        rate = validate_rate_summary(
            row.get("trace_disagreement"),
            f"stress stratum {stratum}",
            clusters=50,
            disagreements=counts["trace"],
        )
        for name, field in stratum_field_map.items():
            require_exact(row.get(field), counts[name], f"stress stratum {stratum} {field}")
        validated_strata[stratum] = {
            "rate": rate,
            "clusters": counts["clusters"],
            "trace": counts["trace"],
            "outcome": counts["outcome"],
            "decision": counts["decision"],
            "error": counts["error"],
            "policy": counts["policy"],
        }

    reported_actors = require_object(
        payload.get("first_divergence_actor_counts"), "stress divergence actors"
    )
    normalized_actors = {
        require_string(actor, "stress divergence actor"): require_int(
            count, f"stress divergence actor {actor} count"
        )
        for actor, count in reported_actors.items()
    }
    if normalized_actors != dict(divergence_actors):
        raise MacroInputError("stress first-divergence actor counts do not reproduce cluster rows")

    timing = require_object(payload.get("timing"), "stress timing")
    if set(timing) != set(TIMED_OPPONENTS):
        raise MacroInputError("stress timing does not cover both timed opponents")
    for opponent in TIMED_OPPONENTS:
        opponent_timing = require_object(timing[opponent], f"stress timing {opponent}")
        if set(opponent_timing) != set(STRESS_RUNS):
            raise MacroInputError(f"stress timing {opponent} has the wrong run inventory")
        for run in STRESS_RUNS:
            row = require_object(opponent_timing[run], f"stress timing {opponent}/{run}")
            require_exact(row.get("games"), 100, f"stress timing {opponent}/{run} games")
            mean = require_number(row.get("mean_seconds"), f"stress timing {opponent}/{run} mean")
            median = require_number(
                row.get("median_seconds"), f"stress timing {opponent}/{run} median"
            )
            if mean < 0.0 or median < 0.0:
                raise MacroInputError(f"stress timing {opponent}/{run} is negative")
            iqr = require_list(
                row.get("interquartile_range_seconds"), f"stress timing {opponent}/{run} IQR"
            )
            if len(iqr) != 2:
                raise MacroInputError(f"stress timing {opponent}/{run} IQR needs two endpoints")
            low = require_number(iqr[0], f"stress timing {opponent}/{run} IQR lower")
            high = require_number(iqr[1], f"stress timing {opponent}/{run} IQR upper")
            if low < 0.0 or high < low:
                raise MacroInputError(f"stress timing {opponent}/{run} IQR is invalid")

    sources = require_list(payload.get("sources"), "stress sources")
    if len(sources) != 2:
        raise MacroInputError("stress must contain two source records")
    source_opponents = set()
    for index, raw_source in enumerate(sources):
        source = require_object(raw_source, f"stress source {index}")
        source_opponents.add(require_string(source.get("opponent"), f"stress source {index} opponent"))
        require_sha256(source.get("sha256"), f"stress source {index} digest")
        require_string(source.get("path"), f"stress source {index} path")
    if source_opponents != set(TIMED_OPPONENTS):
        raise MacroInputError("stress source records do not cover both opponents")

    return {
        "status": status,
        "protocol_commit": commit,
        "aggregates": aggregates,
        "rate": overall_rate,
        "strata": validated_strata,
        "actors": normalized_actors,
        "divergence_lines": divergence_lines,
    }


def validate_factorial(payload: dict[str, Any], preflight_status: str) -> dict[str, Any]:
    require_header(payload, "factorial")
    status = payload.get("status")
    if status not in TERMINAL_FACTORIAL_STATUSES:
        raise MacroInputError(f"factorial analysis is not terminal: {status!r}")
    commit = require_string(payload.get("protocol_commit"), "factorial protocol commit")
    if status == "SUPPRESSED_BY_PREFLIGHT":
        require_exact(preflight_status, "FAIL", "suppressed factorial preflight status")
        require_exact(payload.get("admission_decision"), "suppress", "factorial admission")
        reason = require_string(payload.get("reason"), "factorial suppression reason")
        forbidden = {"contrasts", "cell_win_rates", "units", "games"} & set(payload)
        if forbidden:
            raise MacroInputError(f"suppressed factorial contains effect fields: {sorted(forbidden)}")
        return {"status": status, "reason": reason, "protocol_commit": commit}
    if status == "SUPPRESSED_CONTROL_PARITY_FAILURE":
        require_exact(preflight_status, "PASS", "factorial preflight status")
        require_exact(
            payload.get("admission_decision"),
            "suppress_all_factorial_contrasts",
            "factorial admission",
        )
        mismatch_units = require_int(
            payload.get("control_mismatch_units"), "factorial control mismatches", minimum=1
        )
        mismatches = require_list(
            payload.get("first_control_mismatches"), "factorial first control mismatches"
        )
        if len(mismatches) != min(20, mismatch_units):
            raise MacroInputError("factorial control-mismatch examples are incomplete or excessive")
        seen_mismatches = set()
        for index, raw_mismatch in enumerate(mismatches):
            mismatch = require_object(raw_mismatch, f"factorial control mismatch {index}")
            opponent = require_string(
                mismatch.get("opponent"), f"factorial control mismatch {index} opponent"
            )
            order = require_string(
                mismatch.get("actual_order"), f"factorial control mismatch {index} order"
            )
            pair_index = require_int(
                mismatch.get("pair_index"), f"factorial control mismatch {index} pair index"
            )
            key = (opponent, order, pair_index)
            if (
                opponent not in DETERMINISTIC_OPPONENTS
                or order not in ORDERS
                or pair_index >= 200
                or key in seen_mismatches
            ):
                raise MacroInputError(f"invalid or duplicate factorial control mismatch {key}")
            seen_mismatches.add(key)
        validate_factorial_sources(payload)
        forbidden = {"contrasts", "cell_win_rates"} & set(payload)
        if forbidden:
            raise MacroInputError(f"suppressed factorial contains effect fields: {sorted(forbidden)}")
        return {
            "status": status,
            "control_mismatch_units": mismatch_units,
            "protocol_commit": commit,
        }

    require_exact(preflight_status, "PASS", "admitted factorial preflight status")
    require_exact(payload.get("admission_decision"), "admit_with_bounded_wording", "factorial admission")
    require_exact(payload.get("units"), 2_000, "factorial units")
    require_exact(payload.get("games"), 12_000, "factorial games")
    require_exact(payload.get("control_mismatch_units"), 0, "factorial control mismatches")
    rates = require_object(payload.get("cell_win_rates"), "factorial cell win rates")
    if set(rates) != set(PREFLIGHT_ARMS):
        raise MacroInputError("factorial cell win rates must contain C1--C4")
    validated_rates = {
        cell: require_probability(rates[cell], f"factorial {cell} win rate")
        for cell in PREFLIGHT_ARMS
    }

    contrasts = require_object(payload.get("contrasts"), "factorial contrasts")
    if set(contrasts) != set(CONTRASTS):
        raise MacroInputError("factorial contrast set is incomplete")
    validated_contrasts: dict[str, dict[str, Any]] = {}
    bootstrap_settings: set[tuple[int, int, str]] = set()
    for name in CONTRASTS:
        row = require_object(contrasts[name], f"factorial contrast {name}")
        estimate = require_effect(row.get("estimate"), f"factorial contrast {name} estimate")
        low, high = require_interval(
            row.get("bootstrap_95_ci"), f"factorial contrast {name} interval", effect=True
        )
        if not low <= estimate <= high:
            raise MacroInputError(f"factorial contrast {name} estimate falls outside its interval")
        draws = require_int(row.get("bootstrap_draws"), f"factorial contrast {name} draws", minimum=1)
        seed = require_int(row.get("bootstrap_seed"), f"factorial contrast {name} seed")
        resampling = require_string(row.get("resampling"), f"factorial contrast {name} resampling")
        bootstrap_settings.add((draws, seed, resampling))
        validated_contrasts[name] = {"estimate": estimate, "interval": (low, high)}
    expected_contrasts = {
        "primary_c4_minus_c1": validated_rates["C4"] - validated_rates["C1"],
        "representation_main": 0.5
        * (
            (validated_rates["C2"] - validated_rates["C1"])
            + (validated_rates["C4"] - validated_rates["C3"])
        ),
        "training_main": 0.5
        * (
            (validated_rates["C3"] - validated_rates["C1"])
            + (validated_rates["C4"] - validated_rates["C2"])
        ),
        "interaction": validated_rates["C4"]
        - validated_rates["C3"]
        - validated_rates["C2"]
        + validated_rates["C1"],
    }
    for name, expected in expected_contrasts.items():
        if not math.isclose(
            validated_contrasts[name]["estimate"], expected, rel_tol=0.0, abs_tol=1e-12
        ):
            raise MacroInputError(f"factorial contrast {name} does not reproduce cell means")
    if len(bootstrap_settings) != 1:
        raise MacroInputError("factorial contrasts use inconsistent bootstrap settings")
    draws, seed, resampling = next(iter(bootstrap_settings))
    require_exact(draws, 100_000, "factorial bootstrap draws")
    require_exact(seed, 2026083117, "factorial bootstrap seed")
    if "paired units" not in resampling or "ten" not in resampling:
        raise MacroInputError("factorial resampling description is not the frozen paired design")

    simple = require_object(payload.get("simple_effects_descriptive"), "factorial simple effects")
    if set(simple) != set(SIMPLE_EFFECTS):
        raise MacroInputError("factorial descriptive simple-effect set is incomplete")
    validated_simple = {
        name: require_effect(simple[name], f"factorial simple effect {name}")
        for name in SIMPLE_EFFECTS
    }
    expected_simple = {
        "c2_minus_c1": validated_rates["C2"] - validated_rates["C1"],
        "c3_minus_c1": validated_rates["C3"] - validated_rates["C1"],
        "c4_minus_c1": validated_rates["C4"] - validated_rates["C1"],
        "c4_minus_c2": validated_rates["C4"] - validated_rates["C2"],
        "c4_minus_c3": validated_rates["C4"] - validated_rates["C3"],
    }
    for name, expected in expected_simple.items():
        if not math.isclose(validated_simple[name], expected, rel_tol=0.0, abs_tol=1e-12):
            raise MacroInputError(f"factorial simple effect {name} does not reproduce cell means")

    mcnemar = require_object(payload.get("primary_mcnemar"), "factorial McNemar result")
    c4_only = require_int(mcnemar.get("c4_only_wins"), "factorial C4-only wins")
    c1_only = require_int(mcnemar.get("c1_only_wins"), "factorial C1-only wins")
    if c4_only + c1_only > 2_000:
        raise MacroInputError("factorial McNemar discordances exceed the unit count")
    p_value = require_probability(mcnemar.get("exact_two_sided_p"), "factorial McNemar p")
    require_exact(mcnemar.get("role"), "secondary", "factorial McNemar role")
    levels = require_object(payload.get("pevl_levels"), "factorial PEVL levels")
    require_string(levels.get("level_6"), "factorial Level-6 boundary")
    require_string(levels.get("level_7"), "factorial Level-7 boundary")
    require_string(levels.get("level_8"), "factorial Level-8 boundary")
    if "does not prove" not in str(levels.get("level_6")):
        raise MacroInputError("factorial Level-6 wording lacks its causal boundary")

    validate_factorial_sources(payload)

    return {
        "status": status,
        "protocol_commit": commit,
        "rates": validated_rates,
        "contrasts": validated_contrasts,
        "simple": validated_simple,
        "mcnemar": {"c4_only": c4_only, "c1_only": c1_only, "p": p_value},
        "bootstrap_draws": draws,
        "bootstrap_seed": seed,
    }


def validate_factorial_sources(payload: Mapping[str, Any]) -> None:
    sources = require_list(payload.get("sources"), "factorial sources")
    if len(sources) != 15:
        raise MacroInputError("factorial must contain 15 source records")
    source_keys = set()
    for index, raw_source in enumerate(sources):
        source = require_object(raw_source, f"factorial source {index}")
        cell = require_string(source.get("cell"), f"factorial source {index} cell")
        opponent = require_string(source.get("opponent"), f"factorial source {index} opponent")
        require_sha256(source.get("sha256"), f"factorial source {index} digest")
        require_string(source.get("path"), f"factorial source {index} path")
        source_keys.add((cell, opponent))
    expected_sources = {
        (cell, opponent)
        for cell in ("C2", "C3", "C4")
        for opponent in DETERMINISTIC_OPPONENTS
    }
    if source_keys != expected_sources:
        raise MacroInputError("factorial source inventory is incomplete")


def validate_combined(
    payload: dict[str, Any],
    preflight: dict[str, Any],
    stress: dict[str, Any],
    factorial: dict[str, Any],
) -> None:
    require_exact(payload.get("schema_version"), 1, "combined schema version")
    require_exact(payload.get("framework"), "Paired Evaluation Validity Ladder", "combined framework")
    require_exact(
        payload.get("protocol"),
        "paper/protocol/PEVL_PROSPECTIVE_PROTOCOL.md",
        "combined protocol",
    )
    nested = {
        "prospective_trace_preflight": preflight,
        "timed_search_stress": stress,
        "gated_factorial": factorial,
    }
    for key, standalone in nested.items():
        if payload.get(key) != standalone:
            raise MacroInputError(f"combined {key} does not exactly match its standalone analysis")
    require_string(payload.get("claim_boundary"), "combined claim boundary")


def tex_escape(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "$": r"\$",
        "&": r"\&",
        "#": r"\#",
        "_": r"\_",
        "%": r"\%",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(
        " " if character in "\r\n\t" else replacements.get(character, character)
        for character in value
    )


def format_int(value: int) -> str:
    return f"{value:,}"


def format_pct(value: float) -> str:
    return f"{100.0 * value:.2f}"


def format_signed_pp(value: float) -> str:
    scaled = 100.0 * value
    if math.isclose(scaled, 0.0, rel_tol=0.0, abs_tol=0.0005):
        scaled = 0.0
    return f"{scaled:+.2f}" if scaled else "0.00"


def format_p_value(value: float) -> str:
    if value < 0.000001:
        return r"\ensuremath{<}0.000001"
    return f"{value:.6f}".rstrip("0").rstrip(".")


class MacroBuilder:
    def __init__(self) -> None:
        self._names: set[str] = set()
        self._definitions: list[str] = []

    def add(self, name: str, value: str = "") -> None:
        if MACRO_NAME_RE.fullmatch(name) is None:
            raise ValueError(f"invalid TeX macro name {name!r}")
        if name in self._names:
            raise ValueError(f"duplicate TeX macro {name}")
        self._names.add(name)
        if "\n" in value:
            self._definitions.append(f"\\newcommand{{\\{name}}}{{%\n{value}\n}}")
        else:
            self._definitions.append(f"\\newcommand{{\\{name}}}{{{value}}}")

    def render(self, header: list[str]) -> str:
        return "\n".join([*header, "", *self._definitions, ""])


def add_preflight_macros(builder: MacroBuilder, preflight: Mapping[str, Any]) -> None:
    endpoint = preflight["endpoint_mismatches"]
    builder.add("PEVLPreflightReady")
    builder.add(
        "PEVLPreflightStatus",
        "Pass" if preflight["status"] == "PASS" else "Fail",
    )
    values = {
        "PEVLPreflightJobs": "20",
        "PEVLPreflightArms": "4",
        "PEVLPreflightOpponents": "5",
        "PEVLPreflightTrajectoryUnits": format_int(1_000),
        "PEVLPreflightExecutions": format_int(3_000),
        "PEVLPreflightMismatches": format_int(preflight["mismatches"]),
        "PEVLPreflightTraceMismatches": format_int(endpoint["trace"]),
        "PEVLPreflightOutcomeMismatches": format_int(endpoint["outcome"]),
        "PEVLPreflightErrorMismatches": format_int(endpoint["error"]),
        "PEVLPreflightDecisionMismatches": format_int(endpoint["decision"]),
        "PEVLPreflightUnitsPerArm": format_int(250),
        "PEVLPreflightExecutionsPerArm": format_int(750),
    }
    for name, value in values.items():
        builder.add(name, value)


def stress_actor_sentence(stress: Mapping[str, Any]) -> str:
    actors = stress["actors"]
    if not actors:
        return "No first divergence was available because all four traces agreed in every cluster."
    actor_text = ", ".join(
        f"{tex_escape(actor)} ({format_int(count)})" for actor, count in sorted(actors.items())
    )
    lines = stress["divergence_lines"]
    return (
        f"First-divergence actor counts were {actor_text}; localized trace-line indices "
        f"ranged from {format_int(min(lines))} to {format_int(max(lines))}."
    )


def add_stress_macros(builder: MacroBuilder, stress: Mapping[str, Any]) -> None:
    aggregates = stress["aggregates"]
    rate = stress["rate"]
    builder.add("PEVLTimedStressReady")
    builder.add(
        "PEVLTimedStressStatus",
        "Trace parity" if stress["status"] == "TRACE_PARITY" else "Trace divergence",
    )
    scalar_values = {
        "PEVLTimedStressClusters": format_int(200),
        "PEVLTimedStressExecutions": format_int(800),
        "PEVLTimedStressTraceMismatches": format_int(aggregates["trace"]),
        "PEVLTimedStressTraceMismatchPct": format_pct(rate["estimate"]),
        "PEVLTimedStressTraceCILowPct": format_pct(rate["interval"][0]),
        "PEVLTimedStressTraceCIHighPct": format_pct(rate["interval"][1]),
        "PEVLTimedStressOutcomeMismatches": format_int(aggregates["outcome"]),
        "PEVLTimedStressDecisionMismatches": format_int(aggregates["decision"]),
        "PEVLTimedStressErrorMismatches": format_int(aggregates["error"]),
        "PEVLTimedStressPolicyErrorClusters": format_int(aggregates["policy"]),
        "PEVLTimedStressBootstrapDraws": format_int(100_000),
        "PEVLTimedStressBootstrapSeed": format_int(2026083118),
    }
    for name, value in scalar_values.items():
        builder.add(name, value)

    name_parts = {
        "starmie": "Starmie",
        "dipplin": "Dipplin",
        "first": "First",
        "second": "Second",
    }
    for stratum in STRESS_STRATA:
        opponent, order = stratum.split("/")
        prefix = f"PEVLTimedStress{name_parts[opponent]}{name_parts[order]}"
        row = stress["strata"][stratum]
        values = {
            "Clusters": format_int(row["clusters"]),
            "TraceMismatches": format_int(row["trace"]),
            "TraceMismatchPct": format_pct(row["rate"]["estimate"]),
            "TraceCILowPct": format_pct(row["rate"]["interval"][0]),
            "TraceCIHighPct": format_pct(row["rate"]["interval"][1]),
            "OutcomeMismatches": format_int(row["outcome"]),
            "DecisionMismatches": format_int(row["decision"]),
            "ErrorMismatches": format_int(row["error"]),
            "PolicyErrorClusters": format_int(row["policy"]),
        }
        for suffix, value in values.items():
            builder.add(prefix + suffix, value)

    builder.add(
        "PEVLTimedStressAbstractSentence",
        "The timed-search stress test found "
        r"\PEVLTimedStressTraceMismatches{}/\PEVLTimedStressClusters{} complete-trace "
        r"disagreements (\PEVLTimedStressTraceMismatchPct\%; empirical 95\% "
        r"cluster-resampling interval [\PEVLTimedStressTraceCILowPct\%, "
        r"\PEVLTimedStressTraceCIHighPct\%]).",
    )
    reproducibility = (
        "supported exact repeatability only for the exercised four-profile schedule"
        if stress["status"] == "TRACE_PARITY"
        else "rejected exact repeatability for at least one exercised seed condition"
    )
    actor_sentence = stress_actor_sentence(stress)
    builder.add(
        "PEVLTimedStressResultsParagraph",
        r"The four-profile timed-search stress test contained "
        r"\PEVLTimedStressClusters{} seed-condition clusters and "
        r"\PEVLTimedStressExecutions{} executions. Complete public-trace digests "
        r"disagreed in \PEVLTimedStressTraceMismatches{} clusters "
        r"(\PEVLTimedStressTraceMismatchPct\%; empirical 95\% cluster-resampling interval "
        r"[\PEVLTimedStressTraceCILowPct\%, \PEVLTimedStressTraceCIHighPct\%]). "
        r"Terminal outcomes disagreed in \PEVLTimedStressOutcomeMismatches{} clusters, "
        r"decision counts in \PEVLTimedStressDecisionMismatches{}, and error records in "
        r"\PEVLTimedStressErrorMismatches{}; policy errors were present in "
        r"\PEVLTimedStressPolicyErrorClusters{} clusters. "
        + actor_sentence
        + " The result "
        + reproducibility
        + "; it localizes plausible timing or process mechanisms but does not prove a unique "
        "causal source or Level-7 cross-arm event alignment.",
    )

    table_rows = []
    for opponent, label in (("starmie", "Starmie"), ("dipplin", "Dipplin")):
        first = stress["strata"][f"{opponent}/first"]
        second = stress["strata"][f"{opponent}/second"]
        trace = first["trace"] + second["trace"]
        outcome = first["outcome"] + second["outcome"]
        decision = first["decision"] + second["decision"]
        error = first["error"] + second["error"]
        admission = "trace parity" if trace == 0 else "trace divergence"
        table_rows.append(
            f"Timed stress {label} & 100 & 400 & {trace} & {outcome} & "
            f"{decision}/{error} & {admission} \\\\"
        )
    builder.add("PEVLTimedStressTableRows", "\n".join(table_rows))


def add_admitted_factorial_macros(builder: MacroBuilder, factorial: Mapping[str, Any]) -> None:
    builder.add("PEVLFactorialReady")
    builder.add("PEVLFactorialAdmitted")
    builder.add("PEVLFactorialStatus", "Admitted seed-matched factorial")
    builder.add("PEVLFactorialUnits", format_int(2_000))
    builder.add("PEVLFactorialGames", format_int(12_000))
    builder.add("PEVLFactorialControlMismatches", "0")
    builder.add("PEVLFactorialBootstrapDraws", format_int(factorial["bootstrap_draws"]))
    builder.add("PEVLFactorialBootstrapSeed", format_int(factorial["bootstrap_seed"]))
    cell_names = {"C1": "COne", "C2": "CTwo", "C3": "CThree", "C4": "CFour"}
    for cell, suffix in cell_names.items():
        builder.add(f"PEVLFactorial{suffix}WinRatePct", format_pct(factorial["rates"][cell]))
    contrast_names = {
        "primary_c4_minus_c1": "Primary",
        "representation_main": "Representation",
        "training_main": "Training",
        "interaction": "Interaction",
    }
    for contrast, suffix in contrast_names.items():
        row = factorial["contrasts"][contrast]
        builder.add(f"PEVLFactorial{suffix}EstimatePP", format_signed_pp(row["estimate"]))
        builder.add(f"PEVLFactorial{suffix}CILowPP", format_signed_pp(row["interval"][0]))
        builder.add(f"PEVLFactorial{suffix}CIHighPP", format_signed_pp(row["interval"][1]))
    simple_names = {
        "c2_minus_c1": "CTwoMinusCOne",
        "c3_minus_c1": "CThreeMinusCOne",
        "c4_minus_c1": "CFourMinusCOne",
        "c4_minus_c2": "CFourMinusCTwo",
        "c4_minus_c3": "CFourMinusCThree",
    }
    for effect, suffix in simple_names.items():
        builder.add(f"PEVLFactorial{suffix}PP", format_signed_pp(factorial["simple"][effect]))
    builder.add("PEVLFactorialCFourOnlyWins", format_int(factorial["mcnemar"]["c4_only"]))
    builder.add("PEVLFactorialCOneOnlyWins", format_int(factorial["mcnemar"]["c1_only"]))
    builder.add("PEVLFactorialMcNemarP", format_p_value(factorial["mcnemar"]["p"]))
    builder.add(
        "PEVLFactorialAbstractSentence",
        r"The admitted seed-matched factorial covered \PEVLFactorialUnits{} units "
        r"(\PEVLFactorialGames{} games); the total \CFour--\COne{} contrast was "
        r"\PEVLFactorialPrimaryEstimatePP{} percentage points (empirical 95\% "
        r"paired-resampling interval [\PEVLFactorialPrimaryCILowPP{}, "
        r"\PEVLFactorialPrimaryCIHighPP{}]).",
    )
    builder.add(
        "PEVLFactorialResultsParagraph",
        r"The complete repeated-\COne{} audit had \PEVLFactorialControlMismatches{} "
        r"mismatches, admitting the frozen seed-matched analysis of "
        r"\PEVLFactorialUnits{} units and \PEVLFactorialGames{} games. The total "
        r"\CFour--\COne{} contrast was \PEVLFactorialPrimaryEstimatePP{} percentage "
        r"points (empirical 95\% paired-resampling interval "
        r"[\PEVLFactorialPrimaryCILowPP{}, \PEVLFactorialPrimaryCIHighPP{}]); the "
        r"fixed-package representation and training contrasts were "
        r"\PEVLFactorialRepresentationEstimatePP{} and "
        r"\PEVLFactorialTrainingEstimatePP{} percentage points, and the interaction "
        r"was \PEVLFactorialInteractionEstimatePP{} percentage points. These are exact "
        r"observed contrasts on the frozen schedule; the intervals describe empirical "
        r"stability under the prespecified paired-unit resampling scheme and do not "
        r"represent uncertainty over new opponents, training realizations, or executions. "
        r"They do not establish a causally coupled counterfactual or identify a unique "
        r"mechanism, because Level-7 event alignment is unavailable.",
    )
    builder.add(
        "PEVLFactorialResultsTable",
        r"\begin{table}[t]" "\n"
        r"\caption{Frozen seed-matched factorial contrasts. Empirical stability "
        r"intervals use 100,000 paired resamples within each opponent-by-order stratum.}" "\n"
        r"\label{tab:pevl-factorial}" "\n"
        r"\begin{ruledtabular}" "\n"
        r"\begin{tabular}{lrrr}" "\n"
        r"Contrast & Estimate (pp) & 95\% stability low & 95\% stability high \\" "\n"
        r"\hline" "\n"
        r"Total intervention (\CFour--\COne) & \PEVLFactorialPrimaryEstimatePP & "
        r"\PEVLFactorialPrimaryCILowPP & \PEVLFactorialPrimaryCIHighPP \\" "\n"
        r"Fixed-package representation contrast & \PEVLFactorialRepresentationEstimatePP & "
        r"\PEVLFactorialRepresentationCILowPP & \PEVLFactorialRepresentationCIHighPP \\" "\n"
        r"Fixed-package training contrast & \PEVLFactorialTrainingEstimatePP & "
        r"\PEVLFactorialTrainingCILowPP & \PEVLFactorialTrainingCIHighPP \\" "\n"
        r"Interaction & \PEVLFactorialInteractionEstimatePP & "
        r"\PEVLFactorialInteractionCILowPP & \PEVLFactorialInteractionCIHighPP \\" "\n"
        r"\end{tabular}" "\n"
        r"\end{ruledtabular}" "\n"
        r"\end{table}",
    )


def add_suppressed_factorial_macros(
    builder: MacroBuilder,
    factorial: Mapping[str, Any],
    preflight: Mapping[str, Any],
) -> None:
    # The manuscript consumes one complete terminal family. The extra marker
    # distinguishes suppression for validators without requiring a main-text
    # conditional or allowing an effect table to leak into this branch.
    builder.add("PEVLFactorialReady")
    builder.add("PEVLFactorialSuppressedReady")
    status = factorial["status"]
    if status == "SUPPRESSED_BY_PREFLIGHT":
        builder.add("PEVLFactorialSuppressedStatus", "Suppressed by trace preflight")
        builder.add("PEVLFactorialSuppressedMismatchUnits", format_int(preflight["mismatches"]))
        builder.add(
            "PEVLFactorialAbstractSentence",
            r"The prospective factorial was suppressed because the frozen trace preflight "
            r"did not pass; no prospective factorial effects were estimated.",
        )
        builder.add(
            "PEVLFactorialResultsParagraph",
            r"The frozen preflight reported \PEVLFactorialSuppressedMismatchUnits{} "
            r"mismatch units and therefore activated the prespecified suppression rule. "
            r"Factorial acquisition or analysis was not admitted, and no treatment, main-"
            r"effect, interaction, interval, or mechanistic estimate is reported.",
        )
    else:
        mismatches = factorial["control_mismatch_units"]
        builder.add("PEVLFactorialSuppressedStatus", "Suppressed by repeated-control parity")
        builder.add("PEVLFactorialSuppressedMismatchUnits", format_int(mismatches))
        builder.add(
            "PEVLFactorialAbstractSentence",
            r"The prospective factorial was suppressed after "
            r"\PEVLFactorialSuppressedMismatchUnits{} repeated-\COne{} control units "
            r"disagreed; no factorial effects were reported.",
        )
        builder.add(
            "PEVLFactorialResultsParagraph",
            r"The repeated-\COne{} audit disagreed in "
            r"\PEVLFactorialSuppressedMismatchUnits{} units across the three factorial "
            r"acquisitions. Under the frozen fail-closed rule, this suppresses every total, "
            r"main-effect, interaction, interval, and mechanistic contrast; no effect table "
            r"is generated.",
        )
    builder.add("PEVLFactorialResultsTable")


def render_macros(
    preflight: Mapping[str, Any],
    stress: Mapping[str, Any],
    factorial: Mapping[str, Any],
    *,
    source_hashes: Mapping[str, str],
) -> str:
    builder = MacroBuilder()
    add_preflight_macros(builder, preflight)
    add_stress_macros(builder, stress)
    if factorial["status"] == "ADMITTED_SEED_MATCHED":
        add_admitted_factorial_macros(builder, factorial)
    else:
        add_suppressed_factorial_macros(builder, factorial, preflight)
    header = [
        "% Generated by paper/scripts/build_pevl_result_macros.py; do not edit.",
        "% Terminal prospective analysis input SHA-256 digests:",
        *[f"%   {label}: {source_hashes[label]}" for label in sorted(source_hashes)],
    ]
    return builder.render(header)


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise RuntimeError(f"refusing to replace non-regular macro target: {path}")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def build_result_macros(
    *,
    preflight_path: Path = DEFAULT_PREFLIGHT,
    stress_path: Path = DEFAULT_STRESS,
    factorial_path: Path = DEFAULT_FACTORIAL,
    combined_path: Path = DEFAULT_COMBINED,
    output_path: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    paths = {
        "preflight": preflight_path,
        "stress": stress_path,
        "factorial": factorial_path,
        "combined": combined_path,
    }
    loaded = {label: load_artifact(path, label) for label, path in paths.items()}
    payloads = {label: item[0] for label, item in loaded.items()}
    source_hashes = {label: item[1] for label, item in loaded.items()}
    preflight = validate_preflight(payloads["preflight"])
    stress = validate_stress(payloads["stress"])
    factorial = validate_factorial(payloads["factorial"], preflight["status"])
    validate_combined(
        payloads["combined"],
        payloads["preflight"],
        payloads["stress"],
        payloads["factorial"],
    )
    commits = {preflight["protocol_commit"], stress["protocol_commit"]}
    if "protocol_commit" in factorial:
        commits.add(factorial["protocol_commit"])
    if len(commits) != 1:
        raise MacroInputError(f"prospective analyses mix protocol commits: {sorted(commits)}")
    text = render_macros(preflight, stress, factorial, source_hashes=source_hashes)
    atomic_write(output_path, text)
    return {
        "schema_version": 1,
        "stress_status": stress["status"],
        "factorial_status": factorial["status"],
        "protocol_commit": next(iter(commits)),
        "output": str(output_path),
        "output_sha256": sha256_file(output_path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", type=Path, default=DEFAULT_PREFLIGHT)
    parser.add_argument("--stress", type=Path, default=DEFAULT_STRESS)
    parser.add_argument("--factorial", type=Path, default=DEFAULT_FACTORIAL)
    parser.add_argument("--combined", type=Path, default=DEFAULT_COMBINED)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = build_result_macros(
        preflight_path=args.preflight,
        stress_path=args.stress,
        factorial_path=args.factorial,
        combined_path=args.combined,
        output_path=args.output,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
