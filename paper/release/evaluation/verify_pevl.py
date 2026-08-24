#!/usr/bin/env python3
"""Fail-closed verification for the released PEVL evidence package.

This verifier uses only the Python standard library.  It verifies processed
PEVL summaries and their cross-file relationships, the conditional factorial
unit release, the two bounded audit records, and the standalone synthetic
testbed.  It does not claim to rerun the restricted game engine or recompute
bootstrap intervals from unavailable raw trajectories.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
SYNTHETIC = ROOT / "synthetic"

PREFLIGHT_FILE = DATA / "pevl_trace_preflight_summary.json"
STRESS_FILE = DATA / "pevl_timed_search_stress_summary.json"
FACTORIAL_FILE = DATA / "pevl_factorial_summary.json"
COMBINED_FILE = DATA / "pevl_summary.json"
FACTORIAL_UNITS_FILE = DATA / "pevl_factorial_units.csv"
SEED_AUDIT_FILE = DATA / "seed_namespace_audit.json"
STOCHASTIC_AUDIT_FILE = DATA / "stochastic_source_audit.json"
HISTORICAL_FILE = DATA / "ablation_summary.json"
PEVL_PROTOCOL_FILE = ROOT / "docs/protocols/PEVL_PROSPECTIVE_PROTOCOL.md"
PEVL_PROTOCOL_RELEASE_SHA256 = (
    "c6087693d5c569aae77945af4a6bf7ea11a428055bfce87e348d8c30a4fd42cc"
)

SHA256_RE = re.compile(r"[0-9a-f]{64}")
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
TERMINAL_SUPPRESSION_STATUSES = {
    "SUPPRESSED_BY_PREFLIGHT",
    "SUPPRESSED_CONTROL_PARITY_FAILURE",
}
FACTORIAL_FIELDS = [
    "opponent",
    "actual_order",
    "pair_index",
    "scheduled_seed",
    "engine_seed_uint32",
    "physical_seat",
    "c1_win",
    "c2_win",
    "c3_win",
    "c4_win",
    "c1_draw",
    "c2_draw",
    "c3_draw",
    "c4_draw",
    "c1_decisions",
    "c2_decisions",
    "c3_decisions",
    "c4_decisions",
]
SYNTHETIC_FILES = {
    "README.md",
    "__init__.py",
    "pevl_synthetic.py",
    "results/MANIFEST.sha256",
    "results/pevl_matrix.csv",
    "results/pevl_results.json",
    "results/pevl_results.schema.json",
}
SYNTHETIC_RESULT_FILES = {
    "pevl_matrix.csv",
    "pevl_results.json",
    "pevl_results.schema.json",
}
SYNTHETIC_MODES = {
    "clean_deterministic",
    "stateful_draw_shift",
    "wall_clock_search",
    "process_global_state",
    "uint32_seed_conversion",
}
STOCHASTIC_CATEGORIES = {
    "clock_or_deadline",
    "explicit_randomness",
    "module_global_state",
    "native_pointer_or_state",
    "process_or_thread_parallelism",
}
FACTORIAL_CELLS = {"C2", "C3", "C4"}
RELEASE_FACTORIAL_OPPONENTS = {
    "Matched1",
    "Matched2",
    "Matched3",
    "Matched4",
    "Broader3",
}


class VerificationError(ValueError):
    """Raised when a released artifact violates its frozen contract."""


def reject_json_constant(value: str) -> None:
    raise VerificationError(f"non-finite JSON constant prohibited: {value}")


def parse_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise VerificationError(f"non-finite JSON number prohibited: {value}")
    return parsed


def reject_duplicate_pairs(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise VerificationError(f"duplicate JSON key prohibited: {key}")
        result[key] = value
    return result


def require_regular(path: Path, *, root: Path = ROOT) -> None:
    if root.is_symlink() or not root.is_dir():
        raise VerificationError(f"trusted root is unavailable or symlinked: {root}")
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise VerificationError(f"path escapes release root: {path}") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise VerificationError(f"symlinked path component prohibited: {current}")
    if not path.is_file() or path.stat().st_nlink != 1:
        raise VerificationError(f"regular single-link file required: {path}")
    if not path.resolve(strict=True).is_relative_to(root.resolve(strict=True)):
        raise VerificationError(f"resolved path escapes release root: {path}")


def load_json(path: Path) -> dict[str, Any]:
    require_regular(path)
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_pairs,
            parse_constant=reject_json_constant,
            parse_float=parse_finite_float,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"invalid JSON in {path.name}: {exc}") from exc
    if not isinstance(payload, dict):
        raise VerificationError(f"top-level JSON object required: {path.name}")
    return payload


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise VerificationError(f"{label} must be an integer >= {minimum}")
    return value


def number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise VerificationError(f"{label} must be finite numeric")
    result = float(value)
    if not math.isfinite(result):
        raise VerificationError(f"{label} must be finite numeric")
    return result


def probability(value: Any, label: str) -> float:
    result = number(value, label)
    if not 0.0 <= result <= 1.0:
        raise VerificationError(f"{label} must lie in [0, 1]")
    return result


def boolean(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise VerificationError(f"{label} must be boolean")
    return value


def nonempty_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VerificationError(f"{label} must be nonempty text")
    return value


def require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise VerificationError(f"{label} must be a lowercase SHA-256")
    return value


def require_header(payload: Mapping[str, Any], analysis_id: str) -> None:
    if payload.get("schema_version") != 1:
        raise VerificationError(f"{analysis_id} must use schema_version 1")
    if payload.get("analysis_id") != analysis_id:
        raise VerificationError(
            f"expected analysis_id {analysis_id!r}, got {payload.get('analysis_id')!r}"
        )


def require_protocol_commit(payload: Mapping[str, Any], label: str) -> str:
    value = payload.get("protocol_commit")
    if not isinstance(value, str) or COMMIT_RE.fullmatch(value) is None:
        raise VerificationError(f"{label} protocol_commit must be a Git SHA-1")
    return value


def validate_interval(
    value: Any,
    label: str,
    *,
    minimum: float,
    maximum: float,
) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise VerificationError(f"{label} must be a two-value list")
    low, high = (number(item, label) for item in value)
    if not minimum <= low <= high <= maximum:
        raise VerificationError(f"{label} is reversed or out of range")
    return low, high


def validate_preflight(payload: Mapping[str, Any]) -> str:
    require_header(payload, "trace_preflight")
    status = payload.get("status")
    if status not in {"PASS", "FAIL"}:
        raise VerificationError(f"trace preflight is not terminal: {status!r}")
    expected_decision = (
        "admit_factorial_acquisition" if status == "PASS" else "suppress_factorial"
    )
    if payload.get("admission_decision") != expected_decision:
        raise VerificationError("trace-preflight status/decision conflict")
    require_protocol_commit(payload, "trace preflight")
    if integer(payload.get("arms"), "preflight arms", minimum=1) != 4:
        raise VerificationError("trace preflight must cover four arms")
    if integer(payload.get("opponents"), "preflight opponents", minimum=1) != 5:
        raise VerificationError("trace preflight must cover five frozen opponents")
    rows = payload.get("rows")
    if not isinstance(rows, list) or len(rows) != 20:
        raise VerificationError("trace preflight must contain 20 arm/opponent rows")
    identities: set[tuple[str, str]] = set()
    mismatch_sum = unit_sum = execution_sum = 0
    opponent_names: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise VerificationError(f"preflight row {index} must be an object")
        arm = row.get("arm")
        opponent = row.get("opponent")
        if arm not in {"C1", "C2", "C3", "C4"}:
            raise VerificationError(f"invalid preflight arm: {arm!r}")
        opponent = nonempty_text(opponent, "preflight opponent")
        identity = (arm, opponent)
        if identity in identities:
            raise VerificationError(f"duplicate preflight identity: {identity}")
        identities.add(identity)
        opponent_names.add(opponent)
        passed = boolean(row.get("passed"), f"preflight {identity} passed")
        mismatches = integer(row.get("mismatch_units"), f"preflight {identity} mismatches")
        units = integer(row.get("trajectory_units"), f"preflight {identity} units", minimum=1)
        executions = integer(row.get("executions"), f"preflight {identity} executions", minimum=1)
        if units != 50 or executions != 150:
            raise VerificationError(f"preflight {identity} does not match frozen schedule")
        if passed != (mismatches == 0):
            raise VerificationError(f"preflight {identity} pass flag conflicts with mismatches")
        require_sha256(row.get("source_sha256"), f"preflight {identity} source digest")
        nonempty_text(row.get("source"), f"preflight {identity} source")
        mismatch_sum += mismatches
        unit_sum += units
        execution_sum += executions
    if len(opponent_names) != 5:
        raise VerificationError("trace preflight does not identify five opponents")
    if identities != {
        (arm, opponent)
        for arm in ("C1", "C2", "C3", "C4")
        for opponent in opponent_names
    }:
        raise VerificationError("trace-preflight arm/opponent grid is incomplete")
    if (
        integer(payload.get("trajectory_units"), "preflight total units") != unit_sum
        or integer(payload.get("executions"), "preflight total executions") != execution_sum
        or integer(payload.get("mismatch_units"), "preflight total mismatches") != mismatch_sum
        or unit_sum != 1_000
        or execution_sum != 3_000
    ):
        raise VerificationError("trace-preflight totals do not reproduce its rows")
    if (status == "PASS") != (mismatch_sum == 0):
        raise VerificationError("trace-preflight terminal status conflicts with row evidence")
    nonempty_text(payload.get("claim_boundary"), "trace-preflight claim boundary")
    return status


def validate_bootstrap_binary(
    payload: Any,
    *,
    label: str,
    expected_clusters: int,
    expected_count: int,
) -> None:
    if not isinstance(payload, dict):
        raise VerificationError(f"{label} must be an object")
    if integer(payload.get("clusters"), f"{label} clusters", minimum=1) != expected_clusters:
        raise VerificationError(f"{label} cluster count mismatch")
    estimate = probability(payload.get("estimate"), f"{label} estimate")
    low, high = validate_interval(
        payload.get("bootstrap_95_ci"), label, minimum=0.0, maximum=1.0
    )
    if abs(estimate - expected_count / expected_clusters) > 1e-12:
        raise VerificationError(f"{label} estimate does not reproduce its count")
    if not low <= estimate <= high:
        raise VerificationError(f"{label} estimate lies outside its interval")
    if integer(payload.get("bootstrap_draws"), f"{label} draws", minimum=1) != 100_000:
        raise VerificationError(f"{label} does not use the frozen draw count")
    integer(payload.get("bootstrap_seed"), f"{label} seed")


def validate_stress(payload: Mapping[str, Any]) -> str:
    require_header(payload, "timed_search_stress")
    status = payload.get("status")
    if status not in {"TRACE_PARITY", "TRACE_DIVERGENCE"}:
        raise VerificationError(f"timed-search stress is not terminal: {status!r}")
    require_protocol_commit(payload, "timed-search stress")
    clusters = integer(payload.get("clusters"), "stress clusters", minimum=1)
    executions = integer(payload.get("executions"), "stress executions", minimum=1)
    if (clusters, executions) != (200, 800):
        raise VerificationError("timed-search stress must contain 200 clusters/800 executions")
    rows = payload.get("cluster_rows")
    if not isinstance(rows, list) or len(rows) != clusters:
        raise VerificationError("stress cluster_rows do not match the cluster total")
    identities: set[tuple[str, str]] = set()
    opponents: set[str] = set()
    counts = Counter()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise VerificationError(f"stress row {index} must be an object")
        opponent = nonempty_text(row.get("opponent"), "stress opponent")
        task_id = nonempty_text(row.get("task_id"), "stress task_id")
        identity = (opponent, task_id)
        if identity in identities:
            raise VerificationError(f"duplicate stress cluster: {identity}")
        identities.add(identity)
        opponents.add(opponent)
        order = row.get("actual_order")
        if order not in {"first", "second"}:
            raise VerificationError(f"invalid stress order: {order!r}")
        counts[(opponent, order)] += 1
        integer(row.get("scheduled_seed"), "stress scheduled seed")
        integer(row.get("engine_seed_uint32"), "stress engine seed", minimum=0)
        seat = integer(row.get("physical_seat"), "stress physical seat")
        if seat not in {0, 1}:
            raise VerificationError("stress physical seat must be zero or one")
        disagreement = boolean(row.get("trace_disagreement"), "stress trace disagreement")
        agree = boolean(row.get("all_four_trace_agree"), "stress four-run agreement")
        if agree == disagreement:
            raise VerificationError("stress trace agreement flags conflict")
        for field in (
            "outcome_disagreement",
            "error_disagreement",
            "policy_error_present",
            "decision_count_disagreement",
        ):
            boolean(row.get(field), f"stress {field}")
        divergence = row.get("first_divergence")
        if disagreement != (divergence is not None):
            raise VerificationError("stress divergence localization conflicts with digest parity")
    if len(opponents) != 2 or set(counts.values()) != {50} or len(counts) != 4:
        raise VerificationError("stress rows must cover two opponents by two orders, 50 each")
    count_fields = {
        "trace_disagreement_clusters": "trace_disagreement",
        "outcome_disagreement_clusters": "outcome_disagreement",
        "decision_count_disagreement_clusters": "decision_count_disagreement",
        "error_disagreement_clusters": "error_disagreement",
        "policy_error_present_clusters": "policy_error_present",
    }
    observed_counts = {
        summary_field: sum(bool(row[row_field]) for row in rows)
        for summary_field, row_field in count_fields.items()
    }
    for field, observed in observed_counts.items():
        if integer(payload.get(field), f"stress {field}") != observed:
            raise VerificationError(f"stress {field} does not reproduce cluster rows")
    disagreements = observed_counts["trace_disagreement_clusters"]
    if (status == "TRACE_DIVERGENCE") != (disagreements > 0):
        raise VerificationError("stress terminal status conflicts with trace rows")
    validate_bootstrap_binary(
        payload.get("trace_disagreement"),
        label="stress overall bootstrap",
        expected_clusters=clusters,
        expected_count=disagreements,
    )
    strata = payload.get("strata")
    if not isinstance(strata, dict) or len(strata) != 4:
        raise VerificationError("stress must contain four strata")
    expected_strata = {f"{opponent}/{order}" for opponent, order in counts}
    if set(strata) != expected_strata:
        raise VerificationError("stress stratum keys do not match cluster rows")
    stratum_field_map = {
        "outcome_disagreement_count": "outcome_disagreement",
        "decision_count_disagreement_count": "decision_count_disagreement",
        "error_disagreement_count": "error_disagreement",
        "policy_error_present_count": "policy_error_present",
    }
    for name, stratum in strata.items():
        if not isinstance(stratum, dict):
            raise VerificationError(f"stress stratum {name} must be an object")
        opponent, order = name.rsplit("/", 1)
        subset = [row for row in rows if row["opponent"] == opponent and row["actual_order"] == order]
        disagreements_in_stratum = sum(bool(row["trace_disagreement"]) for row in subset)
        validate_bootstrap_binary(
            stratum.get("trace_disagreement"),
            label=f"stress {name} bootstrap",
            expected_clusters=50,
            expected_count=disagreements_in_stratum,
        )
        for field, row_field in stratum_field_map.items():
            expected = sum(bool(row[row_field]) for row in subset)
            if integer(stratum.get(field), f"stress {name} {field}") != expected:
                raise VerificationError(f"stress {name} {field} conflicts with rows")
    timing = payload.get("timing")
    if not isinstance(timing, dict) or set(timing) != opponents:
        raise VerificationError("stress timing inventory does not match opponents")
    expected_runs = {"serial_forward", "serial_reverse", "parallel_forward", "parallel_reverse"}
    for opponent, runs in timing.items():
        if not isinstance(runs, dict) or set(runs) != expected_runs:
            raise VerificationError(f"stress timing runs incomplete for {opponent}")
        for run, summary in runs.items():
            if not isinstance(summary, dict) or integer(summary.get("games"), f"{opponent}/{run} games") != 100:
                raise VerificationError(f"stress timing summary malformed for {opponent}/{run}")
            for field in ("mean_seconds", "median_seconds"):
                if number(summary.get(field), f"{opponent}/{run} {field}") < 0:
                    raise VerificationError("stress elapsed time cannot be negative")
            low, high = validate_interval(
                summary.get("interquartile_range_seconds"),
                f"{opponent}/{run} IQR",
                minimum=0.0,
                maximum=float("inf"),
            )
            if low > high:
                raise VerificationError("stress timing IQR is reversed")
    sources = payload.get("sources")
    if not isinstance(sources, list) or len(sources) != 2:
        raise VerificationError("stress must identify two source proofs")
    for source in sources:
        if not isinstance(source, dict):
            raise VerificationError("stress source record must be an object")
        nonempty_text(source.get("path"), "stress source path")
        require_sha256(source.get("sha256"), "stress source digest")
    nonempty_text(payload.get("bootstrap_note"), "stress bootstrap note")
    nonempty_text(payload.get("pevl_level_6_boundary"), "stress Level-6 boundary")
    return status


def exact_mcnemar(first_wins: int, second_wins: int) -> float:
    discordant = first_wins + second_wins
    if discordant == 0:
        return 1.0
    lower = min(first_wins, second_wins)
    tail = sum(math.comb(discordant, index) for index in range(lower + 1)) / (2**discordant)
    return min(1.0, 2.0 * tail)


def validate_factorial_sources(payload: Mapping[str, Any]) -> None:
    sources = payload.get("sources")
    if not isinstance(sources, list) or len(sources) != 15:
        raise VerificationError(
            "factorial must identify 15 C2/C3/C4-by-opponent source records"
        )
    observed: set[tuple[str, str]] = set()
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise VerificationError(f"factorial source {index} must be an object")
        cell = nonempty_text(source.get("cell"), f"factorial source {index} cell")
        opponent = nonempty_text(
            source.get("opponent"), f"factorial source {index} opponent"
        )
        nonempty_text(source.get("path"), f"factorial source {index} path")
        require_sha256(source.get("sha256"), f"factorial source {index} digest")
        key = (cell, opponent)
        if key in observed:
            raise VerificationError(f"duplicate factorial source record: {key}")
        observed.add(key)
    expected = {
        (cell, opponent)
        for cell in FACTORIAL_CELLS
        for opponent in RELEASE_FACTORIAL_OPPONENTS
    }
    if observed != expected:
        raise VerificationError("factorial source inventory does not match the frozen design")


def load_factorial_units() -> list[dict[str, Any]]:
    require_regular(FACTORIAL_UNITS_FILE)
    try:
        with FACTORIAL_UNITS_FILE.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != FACTORIAL_FIELDS:
                raise VerificationError("factorial unit CSV header mismatch")
            raw_rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise VerificationError(f"cannot read factorial units: {exc}") from exc
    if len(raw_rows) != 2_000:
        raise VerificationError("admitted factorial must release exactly 2,000 unit rows")
    rows: list[dict[str, Any]] = []
    identities: set[tuple[str, str, int]] = set()
    opponents: set[str] = set()
    for raw in raw_rows:
        opponent = nonempty_text(raw.get("opponent"), "factorial opponent")
        order = raw.get("actual_order")
        if order not in {"first", "second"}:
            raise VerificationError(f"invalid factorial order: {order!r}")
        try:
            row = {
                key: raw[key] if key in {"opponent", "actual_order"} else int(raw[key])
                for key in FACTORIAL_FIELDS
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise VerificationError("factorial CSV contains a non-integer numeric field") from exc
        index = row["pair_index"]
        identity = (opponent, order, index)
        if identity in identities:
            raise VerificationError(f"duplicate factorial unit: {identity}")
        identities.add(identity)
        opponents.add(opponent)
        if not 0 <= index < 200 or row["physical_seat"] != index % 2:
            raise VerificationError(f"factorial schedule mismatch at {identity}")
        if row["scheduled_seed"] != row["engine_seed_uint32"]:
            raise VerificationError(f"factorial seed conversion mismatch at {identity}")
        for field in ("c1_win", "c2_win", "c3_win", "c4_win", "c1_draw", "c2_draw", "c3_draw", "c4_draw"):
            if row[field] not in {0, 1}:
                raise VerificationError(f"factorial {field} must be binary")
        for cell in ("c1", "c2", "c3", "c4"):
            if row[f"{cell}_win"] + row[f"{cell}_draw"] > 1:
                raise VerificationError(f"factorial win/draw conflict at {identity}/{cell}")
            if row[f"{cell}_decisions"] < 0:
                raise VerificationError(f"factorial decision count is negative at {identity}/{cell}")
        rows.append(row)
    expected = {
        (opponent, order, index)
        for opponent in opponents
        for order in ("first", "second")
        for index in range(200)
    }
    if len(opponents) != 5 or identities != expected:
        raise VerificationError("factorial CSV is not the complete five-opponent schedule")
    return rows


def validate_factorial(payload: Mapping[str, Any], preflight_status: str) -> tuple[str, int]:
    require_header(payload, "factorial")
    status = payload.get("status")
    decision = payload.get("admission_decision")
    require_protocol_commit(payload, "factorial")
    units_path_exists = FACTORIAL_UNITS_FILE.exists() or FACTORIAL_UNITS_FILE.is_symlink()
    if status in TERMINAL_SUPPRESSION_STATUSES:
        if units_path_exists:
            raise VerificationError("suppressed factorial must not release unit rows")
        if status == "SUPPRESSED_BY_PREFLIGHT":
            if preflight_status != "FAIL" or decision != "suppress":
                raise VerificationError("preflight suppression conflicts with preflight evidence")
            nonempty_text(payload.get("reason"), "factorial suppression reason")
        else:
            if preflight_status != "PASS" or decision != "suppress_all_factorial_contrasts":
                raise VerificationError("control-parity suppression conflicts with its gate")
            integer(payload.get("control_mismatch_units"), "factorial control mismatches", minimum=1)
            validate_factorial_sources(payload)
        return str(status), 0
    if status != "ADMITTED_SEED_MATCHED" or decision != "admit_with_bounded_wording":
        raise VerificationError(f"factorial branch is unresolved: {status!r}/{decision!r}")
    if preflight_status != "PASS":
        raise VerificationError("admitted factorial lacks a PASS preflight")
    if integer(payload.get("control_mismatch_units"), "factorial control mismatches") != 0:
        raise VerificationError("admitted factorial contains control mismatches")
    units = integer(payload.get("units"), "factorial units", minimum=1)
    games = integer(payload.get("games"), "factorial games", minimum=1)
    if units != 2_000 or games != 12_000:
        raise VerificationError("admitted factorial schedule must contain 2,000 units/12,000 games")
    rows = load_factorial_units()
    rates = payload.get("cell_win_rates")
    if not isinstance(rates, dict) or set(rates) != {"C1", "C2", "C3", "C4"}:
        raise VerificationError("factorial cell-win-rate inventory is incomplete")
    arrays = {cell: [row[f"{cell.lower()}_win"] for row in rows] for cell in rates}
    for cell, vector in arrays.items():
        expected_rate = sum(vector) / len(vector)
        if abs(probability(rates[cell], f"factorial {cell} rate") - expected_rate) > 1e-12:
            raise VerificationError(f"factorial {cell} rate does not reproduce unit rows")
    c1, c2, c3, c4 = (arrays[cell] for cell in ("C1", "C2", "C3", "C4"))
    expected_contrasts = {
        "primary_c4_minus_c1": sum(d - a for a, d in zip(c1, c4)) / units,
        "representation_main": sum(0.5 * ((b - a) + (d - c)) for a, b, c, d in zip(c1, c2, c3, c4)) / units,
        "training_main": sum(0.5 * ((c - a) + (d - b)) for a, b, c, d in zip(c1, c2, c3, c4)) / units,
        "interaction": sum(d - c - b + a for a, b, c, d in zip(c1, c2, c3, c4)) / units,
    }
    contrasts = payload.get("contrasts")
    if not isinstance(contrasts, dict) or set(contrasts) != set(expected_contrasts):
        raise VerificationError("factorial contrast inventory is incomplete")
    for name, expected in expected_contrasts.items():
        record = contrasts[name]
        if not isinstance(record, dict):
            raise VerificationError(f"factorial contrast {name} must be an object")
        estimate = number(record.get("estimate"), f"factorial {name} estimate")
        if abs(estimate - expected) > 1e-12:
            raise VerificationError(f"factorial {name} does not reproduce unit rows")
        low, high = validate_interval(
            record.get("bootstrap_95_ci"), f"factorial {name} CI", minimum=-1.0, maximum=1.0
        )
        if not low <= estimate <= high:
            raise VerificationError(f"factorial {name} estimate lies outside its interval")
        if integer(record.get("bootstrap_draws"), f"factorial {name} draws", minimum=1) != 100_000:
            raise VerificationError(f"factorial {name} uses an unexpected draw count")
    expected_simple = {
        "c2_minus_c1": sum(b - a for a, b in zip(c1, c2)) / units,
        "c3_minus_c1": sum(c - a for a, c in zip(c1, c3)) / units,
        "c4_minus_c1": sum(d - a for a, d in zip(c1, c4)) / units,
        "c4_minus_c2": sum(d - b for b, d in zip(c2, c4)) / units,
        "c4_minus_c3": sum(d - c for c, d in zip(c3, c4)) / units,
    }
    simple = payload.get("simple_effects_descriptive")
    if not isinstance(simple, dict) or set(simple) != set(expected_simple):
        raise VerificationError("factorial simple-effect inventory is incomplete")
    for name, expected in expected_simple.items():
        if abs(number(simple[name], f"factorial {name}") - expected) > 1e-12:
            raise VerificationError(f"factorial {name} does not reproduce unit rows")
    c4_only = sum(d == 1 and a == 0 for a, d in zip(c1, c4))
    c1_only = sum(d == 0 and a == 1 for a, d in zip(c1, c4))
    mcnemar = payload.get("primary_mcnemar")
    if not isinstance(mcnemar, dict):
        raise VerificationError("factorial McNemar record is missing")
    if (
        integer(mcnemar.get("c4_only_wins"), "factorial C4-only wins") != c4_only
        or integer(mcnemar.get("c1_only_wins"), "factorial C1-only wins") != c1_only
        or abs(probability(mcnemar.get("exact_two_sided_p"), "factorial McNemar p") - exact_mcnemar(c4_only, c1_only)) > 1e-12
        or mcnemar.get("role") != "secondary"
    ):
        raise VerificationError("factorial McNemar record does not reproduce unit rows")
    boundaries = payload.get("pevl_levels")
    if not isinstance(boundaries, dict) or set(boundaries) != {
        "levels_1_to_5", "level_6", "level_7", "level_8"
    }:
        raise VerificationError("factorial PEVL claim boundaries are incomplete")
    for key, value in boundaries.items():
        nonempty_text(value, f"factorial {key} boundary")
    validate_factorial_sources(payload)
    return str(status), len(rows)


def validate_combined(
    payload: Mapping[str, Any],
    *,
    preflight: Mapping[str, Any],
    stress: Mapping[str, Any],
    factorial: Mapping[str, Any],
    historical: Mapping[str, Any],
) -> None:
    if payload.get("schema_version") != 1:
        raise VerificationError("combined PEVL summary must use schema_version 1")
    if payload.get("framework") != "Paired Evaluation Validity Ladder":
        raise VerificationError("combined PEVL framework mismatch")
    if payload.get("protocol") != "paper/protocol/PEVL_PROSPECTIVE_PROTOCOL.md":
        raise VerificationError("combined PEVL protocol path mismatch")
    for key, expected in {
        "prospective_trace_preflight": preflight,
        "timed_search_stress": stress,
        "gated_factorial": factorial,
    }.items():
        if payload.get(key) != expected:
            raise VerificationError(f"combined summary differs from standalone {key}")
    old_audit = historical.get("control_parity_audit")
    combined_historical = payload.get("historical_control_parity")
    if not isinstance(old_audit, dict) or not isinstance(combined_historical, dict):
        raise VerificationError("combined historical parity record is missing")
    expected_historical = {
        "status": historical.get("status"),
        "units": old_audit.get("pairs"),
        "outcome_record_mismatch_units": old_audit.get("outcome_record_mismatch_units"),
        "serialized_record_mismatch_units": old_audit.get("serialized_record_mismatch_units"),
        "by_opponent": old_audit.get("by_opponent"),
        "cause_audit": historical.get("cause_audit"),
    }
    for key, expected in expected_historical.items():
        if combined_historical.get(key) != expected:
            raise VerificationError(f"combined historical field {key} conflicts with released audit")
    nonempty_text(payload.get("claim_boundary"), "combined PEVL claim boundary")


def validate_seed_summary(payload: Any, label: str) -> int:
    if not isinstance(payload, dict):
        raise VerificationError(f"{label} must be an object")
    count = integer(payload.get("scheduled_count"), f"{label} scheduled count", minimum=1)
    if (
        integer(payload.get("scheduled_unique"), f"{label} scheduled unique") != count
        or integer(payload.get("engine_seed_unique"), f"{label} engine unique") != count
        or payload.get("collision_groups") != {}
        or payload.get("passed_no_collision") is not True
    ):
        raise VerificationError(f"{label} does not establish a collision-free namespace")
    low = integer(payload.get("engine_seed_min"), f"{label} engine minimum")
    high = integer(payload.get("engine_seed_max"), f"{label} engine maximum")
    if low > high or high > 0xFFFFFFFF:
        raise VerificationError(f"{label} engine-seed range is invalid")
    integer(payload.get("conversion_changed"), f"{label} converted count")
    integer(payload.get("scheduled_outside_uint32"), f"{label} out-of-range count")
    return count


def validate_seed_audit(payload: Mapping[str, Any]) -> None:
    if payload.get("conversion_rule") != "scheduled_seed & 0xffffffff":
        raise VerificationError("seed audit conversion rule mismatch")
    if payload.get("uint32_max") != 0xFFFFFFFF or payload.get("prospective_passed") is not True:
        raise VerificationError("seed audit did not pass the frozen uint32 namespace")
    historical = payload.get("historical_fresh_confirmation")
    if validate_seed_summary(historical, "historical seed namespace") != 2_800:
        raise VerificationError("historical seed audit must cover 2,800 scheduled games")
    schedules = payload.get("prospective_by_schedule")
    if not isinstance(schedules, dict) or set(schedules) != {
        "trace_preflight", "timed_search_stress", "factorial"
    }:
        raise VerificationError("prospective seed schedule inventory is incomplete")
    expected_shapes = {
        "trace_preflight": (5, 50),
        "timed_search_stress": (2, 100),
        "factorial": (5, 400),
    }
    schedule_total = 0
    for schedule, (groups, per_group) in expected_shapes.items():
        records = schedules[schedule]
        if not isinstance(records, dict) or len(records) != groups:
            raise VerificationError(f"seed audit {schedule} group count mismatch")
        for label, record in records.items():
            observed = validate_seed_summary(record, f"seed audit {schedule}/{label}")
            if observed != per_group:
                raise VerificationError(f"seed audit {schedule}/{label} count mismatch")
            schedule_total += observed
    if validate_seed_summary(payload.get("prospective_all"), "prospective seed namespace") != schedule_total:
        raise VerificationError("prospective seed aggregate does not reproduce schedule counts")
    if payload.get("historical_prospective_engine_seed_overlap") != []:
        raise VerificationError("historical and prospective engine-seed namespaces overlap")
    sources = payload.get("sources")
    if not isinstance(sources, list) or len(sources) != 7:
        raise VerificationError("historical seed audit source inventory is incomplete")
    for source in sources:
        if not isinstance(source, dict):
            raise VerificationError("seed source record must be an object")
        nonempty_text(source.get("path"), "seed source path")
        require_sha256(source.get("sha256"), "seed source digest")


def validate_stochastic_audit(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != "pevl-stochastic-source-audit-v1":
        raise VerificationError("stochastic-source audit schema mismatch")
    if payload.get("audit_levels") != [1, 6]:
        raise VerificationError("stochastic-source audit must cover PEVL Levels 1 and 6")
    nonempty_text(payload.get("audit_claim"), "stochastic audit claim boundary")
    nonempty_text(payload.get("hash_contract"), "stochastic audit hash contract")
    definitions = payload.get("category_definitions")
    if not isinstance(definitions, dict) or set(definitions) != STOCHASTIC_CATEGORIES:
        raise VerificationError("stochastic-source category inventory mismatch")
    disclosure = payload.get("disclosure_policy")
    if not isinstance(disclosure, dict) or disclosure.get("card_and_deck_material_included") is not False:
        raise VerificationError("stochastic-source disclosure policy is unsafe")
    if disclosure.get("source_paths_lines_snippets_included") is not False:
        raise VerificationError("restricted source paths/lines/snippets must remain excluded")
    inventory = payload.get("inventory")
    if not isinstance(inventory, list) or len(inventory) != 13:
        raise VerificationError("stochastic-source inventory must contain 13 frozen artifacts")
    artifact_ids: set[str] = set()
    aggregate_hits = Counter({category: 0 for category in STOCHASTIC_CATEGORIES})
    artifacts_with_hits = Counter({category: 0 for category in STOCHASTIC_CATEGORIES})
    verified_trees = 0
    for item in inventory:
        if not isinstance(item, dict):
            raise VerificationError("stochastic-source inventory row must be an object")
        artifact_id = nonempty_text(item.get("artifact_id"), "stochastic artifact id")
        if artifact_id in artifact_ids:
            raise VerificationError(f"duplicate stochastic artifact id: {artifact_id}")
        artifact_ids.add(artifact_id)
        if any(item.get(field) is not True for field in (
            "exists", "expected_digest_present_in_frozen_protocol", "hash_match"
        )):
            raise VerificationError(f"stochastic artifact identity failed: {artifact_id}")
        expected = require_sha256(item.get("expected_sha256"), f"{artifact_id} expected digest")
        observed = require_sha256(item.get("observed_sha256"), f"{artifact_id} observed digest")
        if expected != observed:
            raise VerificationError(f"stochastic artifact digest mismatch: {artifact_id}")
        source_audit = item.get("source_audit")
        if not isinstance(source_audit, dict):
            raise VerificationError(f"missing source audit for {artifact_id}")
        categories = source_audit.get("categories")
        if not isinstance(categories, dict) or set(categories) != STOCHASTIC_CATEGORIES:
            raise VerificationError(f"source category mismatch for {artifact_id}")
        if source_audit.get("status") == "completed_static_python_ast_scan":
            verified_trees += 1
        elif source_audit.get("status") != "not_assessed":
            raise VerificationError(f"unrecognized source-audit status for {artifact_id}")
        for category, record in categories.items():
            if not isinstance(record, dict):
                raise VerificationError(f"malformed {category} record for {artifact_id}")
            hits = record.get("hit_count")
            if hits is None:
                if source_audit.get("status") != "not_assessed":
                    raise VerificationError(f"assessed artifact lacks {category} hit count")
                continue
            hits = integer(hits, f"{artifact_id}/{category} hits")
            aggregate_hits[category] += hits
            artifacts_with_hits[category] += int(hits > 0)
    levels = payload.get("level_results")
    if not isinstance(levels, dict):
        raise VerificationError("stochastic-source level results are missing")
    level1 = levels.get("level_1_artifact_identity")
    level6 = levels.get("level_6_stochastic_source_audit")
    if not isinstance(level1, dict) or not isinstance(level6, dict):
        raise VerificationError("stochastic-source Level 1/6 records are missing")
    if (
        level1.get("status") != "pass"
        or level1.get("all_frozen_hashes_match") is not True
        or level1.get("all_expected_digests_present_in_frozen_protocol") is not True
        or level1.get("artifact_count") != 13
        or level1.get("verified_artifact_count") != 13
    ):
        raise VerificationError("stochastic-source Level 1 identity gate failed")
    if (
        level6.get("status") != "bounded_audit_recorded"
        or level6.get("verified_package_tree_count") != verified_trees
        or level6.get("aggregate_hits_by_category") != dict(aggregate_hits)
        or level6.get("artifacts_with_hits_by_category") != dict(artifacts_with_hits)
    ):
        raise VerificationError("stochastic-source Level 6 aggregates do not reproduce inventory")
    nonempty_text(level6.get("admission_interpretation"), "stochastic Level-6 interpretation")
    limits = payload.get("scope_limits")
    if not isinstance(limits, list) or len(limits) < 3 or any(not isinstance(row, str) or not row.strip() for row in limits):
        raise VerificationError("stochastic-source scope limits are incomplete")


def validate_synthetic_tree() -> None:
    if SYNTHETIC.is_symlink() or not SYNTHETIC.is_dir():
        raise VerificationError("standalone synthetic testbed is missing or symlinked")
    actual: set[str] = set()
    for path in SYNTHETIC.rglob("*"):
        relative = path.relative_to(SYNTHETIC).as_posix()
        if path.is_symlink():
            raise VerificationError(f"synthetic symlink prohibited: {relative}")
        if path.is_file():
            if path.stat().st_nlink != 1:
                raise VerificationError(f"synthetic hard link prohibited: {relative}")
            actual.add(relative)
        elif not path.is_dir():
            raise VerificationError(f"synthetic special file prohibited: {relative}")
    if actual != SYNTHETIC_FILES:
        raise VerificationError(
            "synthetic exact tree mismatch: "
            f"missing={sorted(SYNTHETIC_FILES - actual)}, extra={sorted(actual - SYNTHETIC_FILES)}"
        )
    manifest = SYNTHETIC / "results" / "MANIFEST.sha256"
    require_regular(manifest)
    entries: dict[str, str] = {}
    for number, line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_.-]+)", line)
        if match is None:
            raise VerificationError(f"malformed synthetic manifest line {number}")
        digest, name = match.groups()
        if name in entries:
            raise VerificationError(f"duplicate synthetic manifest path: {name}")
        entries[name] = digest
    if set(entries) != SYNTHETIC_RESULT_FILES:
        raise VerificationError("synthetic manifest inventory mismatch")
    for name, digest in entries.items():
        path = SYNTHETIC / "results" / name
        require_regular(path)
        if sha256(path) != digest:
            raise VerificationError(f"synthetic result digest mismatch: {name}")
    results = load_json(SYNTHETIC / "results" / "pevl_results.json")
    if (
        results.get("schema_version") != "1.1.0"
        or results.get("framework") != "Paired Evaluation Validity Ladder"
        or results.get("testbed") != "pevl_synthetic_coupling_validation"
    ):
        raise VerificationError("synthetic result header mismatch")
    levels = results.get("levels")
    if not isinstance(levels, list) or [row.get("level") for row in levels if isinstance(row, dict)] != list(range(1, 9)):
        raise VerificationError("synthetic PEVL level inventory mismatch")
    modes = results.get("modes")
    if not isinstance(modes, list) or {row.get("mode") for row in modes if isinstance(row, dict)} != SYNTHETIC_MODES:
        raise VerificationError("synthetic mode inventory mismatch")
    protected = {name: sha256(SYNTHETIC / name) for name in SYNTHETIC_FILES}
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-B", "pevl_synthetic.py", "verify"],
        cwd=SYNTHETIC,
        env=environment,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[-2_000:]
        raise VerificationError(f"synthetic verifier failed: {detail}")
    for name, digest in protected.items():
        path = SYNTHETIC / name
        require_regular(path)
        if sha256(path) != digest:
            raise VerificationError(f"synthetic verifier modified protected file: {name}")


def verify() -> dict[str, Any]:
    require_regular(PEVL_PROTOCOL_FILE)
    if sha256(PEVL_PROTOCOL_FILE) != PEVL_PROTOCOL_RELEASE_SHA256:
        raise VerificationError(
            "released sanitized PEVL protocol differs from the frozen protocol blob"
        )
    preflight = load_json(PREFLIGHT_FILE)
    stress = load_json(STRESS_FILE)
    factorial = load_json(FACTORIAL_FILE)
    combined = load_json(COMBINED_FILE)
    historical = load_json(HISTORICAL_FILE)
    seed_audit = load_json(SEED_AUDIT_FILE)
    stochastic_audit = load_json(STOCHASTIC_AUDIT_FILE)

    preflight_status = validate_preflight(preflight)
    stress_status = validate_stress(stress)
    factorial_status, factorial_units = validate_factorial(factorial, preflight_status)
    preflight_commit = require_protocol_commit(preflight, "trace preflight")
    stress_commit = require_protocol_commit(stress, "timed-search stress")
    if preflight_commit != stress_commit:
        raise VerificationError("preflight and stress protocol commits differ")
    if require_protocol_commit(factorial, "factorial") != preflight_commit:
        raise VerificationError("factorial and preflight protocol commits differ")
    validate_combined(
        combined,
        preflight=preflight,
        stress=stress,
        factorial=factorial,
        historical=historical,
    )
    validate_seed_audit(seed_audit)
    validate_stochastic_audit(stochastic_audit)
    validate_synthetic_tree()
    return {
        "status": "PASS",
        "framework": "Paired Evaluation Validity Ladder",
        "preflight": preflight_status,
        "timed_search_stress": stress_status,
        "factorial": factorial_status,
        "factorial_units_verified": factorial_units,
        "synthetic_modes_verified": 5,
        "scope": (
            "processed and synthetic verification only; restricted engine trajectories "
            "and bootstrap recomputation are outside this package"
        ),
    }


def main() -> int:
    try:
        report = verify()
    except (OSError, subprocess.SubprocessError, VerificationError, ValueError) as exc:
        report = {"status": "FAIL", "error": str(exc)}
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
