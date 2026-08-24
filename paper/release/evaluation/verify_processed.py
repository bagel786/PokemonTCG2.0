#!/usr/bin/env python3
"""Fail-closed verification of released canonical rows and primary arithmetic."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/processed"
FIELDS = [
    "experiment",
    "candidate_hash",
    "control_hash",
    "opponent",
    "opponent_family",
    "opponent_role",
    "opponent_hash",
    "seed",
    "pair_index",
    "actual_order",
    "physical_seat",
    "candidate_outcome",
    "control_outcome",
    "candidate_win",
    "control_win",
    "candidate_draw",
    "control_draw",
    "candidate_error",
    "control_error",
    "candidate_opponent_error",
    "control_opponent_error",
    "latency_candidate_ms",
    "latency_control_ms",
    "source_artifact",
    "source_sha256",
]
TOP_LEVEL_FIELDS = {
    "analysis_script",
    "analysis_script_sha256",
    "canonical_sha256",
    "fresh_confirmation",
    "generated_at_commit",
    "historical_exploratory",
    "latency",
    "release_sanitization",
    "schema_version",
    "source_canonical_sha256",
    "source_inventory",
}
FRESH_FIELDS = {
    "by_actual_order",
    "by_opponent",
    "by_opponent_family",
    "cells",
    "execution_provenance_caveat",
    "multiplicity",
    "primary",
    "win_draw_loss_utility_sensitivity",
}
PRIMARY_FIELDS = {
    "bootstrap_iterations",
    "bootstrap_seed",
    "candidate_draws",
    "candidate_errors",
    "candidate_only_wins",
    "candidate_wins",
    "control_draws",
    "control_errors",
    "control_only_wins",
    "control_wins",
    "effect",
    "estimand",
    "mcnemar_exact_two_sided_p",
    "mcnemar_scope",
    "opponent_errors",
    "paired_bootstrap_95_ci",
    "pairs",
    "strata",
}
OPPONENT_METADATA = {
    "Matched1": ("Matched", "baseline"),
    "Matched2": ("Matched", "internal_learned"),
    "Matched3": ("Matched", "internal_learned"),
    "Matched4": ("Matched", "internal_learned"),
    "Broader1": ("Other", "external"),
    "Broader2": ("Other", "external"),
    "Broader3": ("Other", "external"),
}
EXPECTED_CANDIDATE_HASH = "83489e0c80c631763c65375d2a7a34d28d6aa9fbb1d11e89d130c83b1e27f1c0"
EXPECTED_CONTROL_HASH = "13426288358d597ead809e45c364c7f7b9274a6eebf55ddd942142e3326535c3"
EXPECTED_OPPONENT_HASH = {
    "Matched1": "0c15b56adf3b09c654505a152309fdc9f8401579a495da714347d98ae735003c",
    "Matched2": "7db753d6610930d8bd9694b4b9bece5ac48733b825422a3e399c18077b55e64e",
    "Matched3": "8a06ebab47cc60ed981dfada85972eb8a62e732e349f01c2a3085262079f06e8",
    "Matched4": "30e45955b67893514c8ee077cac15d46fc207efe781cbce1b94242defda4cbdc",
    "Broader1": "1b73779da7dcc93c8f121090bb0f1ae2d9b10b798ca4c70447b0ce1d6d01c0db",
    "Broader2": "076ae8de12d2d6c4a170b47b2d2f9cf538c1d318a05bb2e81f13da9be2cd2026",
    "Broader3": "5d44338891094988ca15f0c26d5187316549facd64a7bfbac04aa0048424e8c7",
}
EXPECTED_SOURCE_HASH = {
    "Matched1": "3c161a3d52c0e2ee383cb6b7493ad5ded03ab320097bb6b184a7a71d086407fb",
    "Matched2": "b2d325adbfa752ea2ef05cc0e6c001ca5b2624e70aa5b3230fe61f16f2032370",
    "Matched3": "c52c072d1df4dd6d8dfbbf668d2aeeee553a50b6cb12b0157a523b1d9b2b9734",
    "Matched4": "1c31c89df874ba793112922026db322a2c24c30341b7d71b9562e87982e081ef",
    "Broader1": "a25e535548268f23ec364de322a5b42566da35a4b0ada4eb6b6f3bf375457ab7",
    "Broader2": "3892c62c01a04a8b8c24a2d824827096c72ba7b543a97407e763d53b0dd0bac1",
    "Broader3": "e414b58f370c6457e36dcd145c6dbbad80a2fad178ce3112a01fc533ca25bb65",
}
EXPECTED_SOURCE_ARTIFACT = {
    opponent: f"paper/data/fresh_confirmation/raw/{opponent}.json"
    for opponent in OPPONENT_METADATA
}
EXPECTED_FIRST_SEED_BASE = {
    "Matched1": 202608230000,
    "Matched2": 202608231000,
    "Matched3": 202608232000,
    "Matched4": 202608233000,
    "Broader1": 202608234000,
    "Broader2": 202608235000,
    "Broader3": 202608236000,
}
SECOND_ORDER_SEED_OFFSET = 1_000_000
HEX64 = re.compile(r"[0-9a-f]{64}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def reject_json_constant(value: str):
    raise ValueError(f"non-finite JSON constant prohibited: {value}")


def parse_finite_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"non-finite JSON number prohibited: {value}")
    return parsed


def reject_duplicate_json_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key prohibited: {key}")
        value[key] = item
    return value


def load_json_strict(path: Path):
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicate_json_pairs,
        parse_constant=reject_json_constant,
        parse_float=parse_finite_json_float,
    )


def require_regular_within(root: Path, path: Path) -> None:
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"verification root is missing, not a directory, or a symlink: {root}")
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"verification input is outside release root: {path}") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"symlinked verification path component prohibited: {current}")
    if not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError(f"regular single-link verification input required: {path}")
    if not path.resolve(strict=True).is_relative_to(root.resolve(strict=True)):
        raise ValueError(f"verification input escapes release root: {path}")


def exact_mcnemar(candidate_only: int, control_only: int) -> float:
    total = candidate_only + control_only
    if not total:
        return 1.0
    lower = min(candidate_only, control_only)
    return min(1.0, 2 * sum(math.comb(total, index) for index in range(lower + 1)) / 2**total)


def require_exact_fields(value: dict, expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise ValueError(
            f"{label} schema mismatch: missing={sorted(expected - actual)}, "
            f"unexpected={sorted(actual - expected)}"
        )


def parse_nonnegative_int(value: str, field: str) -> int:
    if not re.fullmatch(r"0|[1-9][0-9]*", value):
        raise ValueError(f"{field} is not a canonical nonnegative integer: {value!r}")
    return int(value)


def safe_relative(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        bool(value)
        and not any(ord(character) < 32 or ord(character) == 127 for character in value)
        and "\\" not in value
        and not path.is_absolute()
        and value == path.as_posix()
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def validate_row(row: dict[str, str], number: int) -> None:
    label = f"canonical row {number}"
    if None in row or set(row) != set(FIELDS):
        raise ValueError(f"{label} does not match the exact CSV schema")
    if row["experiment"] not in {"fresh_confirmation", "historical_exploratory"}:
        raise ValueError(f"{label} has unknown experiment: {row['experiment']!r}")
    for field in ("candidate_hash", "control_hash", "opponent_hash", "source_sha256"):
        if not HEX64.fullmatch(row[field]):
            raise ValueError(f"{label} has invalid {field}")
    if row["candidate_hash"] == row["control_hash"]:
        raise ValueError(f"{label} aliases candidate and control digests")
    if row["actual_order"] not in {"first", "second"}:
        raise ValueError(f"{label} has invalid actual_order")
    pair_index = parse_nonnegative_int(row["pair_index"], f"{label}.pair_index")
    parse_nonnegative_int(row["seed"], f"{label}.seed")
    seat = parse_nonnegative_int(row["physical_seat"], f"{label}.physical_seat")
    if seat not in {0, 1} or seat != pair_index % 2:
        raise ValueError(f"{label} violates the fixed alternating physical-seat schedule")
    for prefix in ("candidate", "control"):
        outcome = row[f"{prefix}_outcome"]
        if outcome not in {"win", "draw", "loss"}:
            raise ValueError(f"{label} has invalid {prefix}_outcome")
        win = parse_nonnegative_int(row[f"{prefix}_win"], f"{label}.{prefix}_win")
        draw = parse_nonnegative_int(row[f"{prefix}_draw"], f"{label}.{prefix}_draw")
        if win not in {0, 1} or draw not in {0, 1}:
            raise ValueError(f"{label} has nonbinary outcome flags")
        if win != int(outcome == "win") or draw != int(outcome == "draw"):
            raise ValueError(f"{label} outcome string/indicator mismatch for {prefix}")
    for field in (
        "candidate_error",
        "control_error",
        "candidate_opponent_error",
        "control_opponent_error",
    ):
        if parse_nonnegative_int(row[field], f"{label}.{field}") != 0:
            raise ValueError(f"{label} contains an evaluation error")
    if row["latency_candidate_ms"] or row["latency_control_ms"]:
        raise ValueError(f"{label} unexpectedly contains latency values")
    if not safe_relative(row["source_artifact"]):
        raise ValueError(f"{label} has unsafe source_artifact")


def require_integer(value, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a nonnegative JSON integer")
    return value


def main() -> int:
    canonical_path = DATA / "canonical_results.csv"
    summary_path = DATA / "statistical_summary.json"
    require_regular_within(ROOT, canonical_path)
    require_regular_within(ROOT, summary_path)
    with canonical_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != FIELDS:
            raise ValueError(f"canonical CSV header mismatch: {reader.fieldnames!r}")
        rows = list(reader)
    for index, row in enumerate(rows, 2):
        validate_row(row, index)

    summary = load_json_strict(summary_path)
    if not isinstance(summary, dict):
        raise ValueError("statistical summary root must be an object")
    require_exact_fields(summary, TOP_LEVEL_FIELDS, "statistical summary")
    fresh_summary = summary["fresh_confirmation"]
    if not isinstance(fresh_summary, dict):
        raise ValueError("fresh_confirmation must be an object")
    require_exact_fields(fresh_summary, FRESH_FIELDS, "fresh_confirmation")
    primary = fresh_summary["primary"]
    if not isinstance(primary, dict):
        raise ValueError("fresh primary summary must be an object")
    require_exact_fields(primary, PRIMARY_FIELDS, "fresh primary")
    primary_integers = {
        field: require_integer(primary[field], f"primary.{field}")
        for field in (
            "bootstrap_iterations",
            "bootstrap_seed",
            "candidate_draws",
            "candidate_errors",
            "candidate_only_wins",
            "candidate_wins",
            "control_draws",
            "control_errors",
            "control_only_wins",
            "control_wins",
            "opponent_errors",
            "pairs",
            "strata",
        )
    }
    for field in ("estimand", "mcnemar_scope"):
        if not isinstance(primary[field], str) or not primary[field].strip():
            raise ValueError(f"primary.{field} must be a nonempty string")
    if summary["release_sanitization"] != {
        "absolute_local_paths_removed": True,
        "opponent_and_team_identifiers": "neutralized",
        "restricted_local_uris_removed": True,
        "schema_version": 1,
    }:
        raise ValueError("missing or altered release-sanitization declaration")
    if summary["schema_version"] != 1:
        raise ValueError(f"unsupported statistical-summary schema: {summary['schema_version']!r}")
    if not HEX64.fullmatch(summary["analysis_script_sha256"]):
        raise ValueError("invalid analysis_script_sha256")
    if not HEX64.fullmatch(summary["source_canonical_sha256"]):
        raise ValueError("invalid source_canonical_sha256")

    fresh = [row for row in rows if row["experiment"] == "fresh_confirmation"]
    historical = [row for row in rows if row["experiment"] == "historical_exploratory"]
    expected_fresh = primary_integers["pairs"]
    expected_historical = sum(
        require_integer(cell["pairs"], f"historical_exploratory.cells[{index}].pairs")
        for index, cell in enumerate(summary["historical_exploratory"]["cells"])
    )
    if len(fresh) != expected_fresh or len(historical) != expected_historical:
        raise ValueError(
            f"canonical experiment counts mismatch: fresh={len(fresh)}/{expected_fresh}, "
            f"historical={len(historical)}/{expected_historical}"
        )
    if expected_fresh != 2_800:
        raise ValueError(f"frozen fresh-pair count changed: {expected_fresh}")

    candidate_hashes = {row["candidate_hash"] for row in fresh}
    control_hashes = {row["control_hash"] for row in fresh}
    if candidate_hashes != {EXPECTED_CANDIDATE_HASH}:
        raise ValueError(f"fresh candidate digest drift: {sorted(candidate_hashes)}")
    if control_hashes != {EXPECTED_CONTROL_HASH}:
        raise ValueError(f"fresh control digest drift: {sorted(control_hashes)}")
    opponent_hashes = {
        opponent: {row["opponent_hash"] for row in fresh if row["opponent"] == opponent}
        for opponent in OPPONENT_METADATA
    }
    if any(len(hashes) != 1 for hashes in opponent_hashes.values()) or len({
        next(iter(hashes)) for hashes in opponent_hashes.values()
    }) != len(OPPONENT_METADATA):
        raise ValueError("fresh neutral opponents do not map one-to-one to distinct package digests")
    if set(fresh_summary["by_opponent"]) != set(OPPONENT_METADATA):
        raise ValueError("fresh summary does not expose exactly seven neutral opponent identifiers")
    for row in fresh:
        expected_metadata = OPPONENT_METADATA.get(row["opponent"])
        if expected_metadata != (row["opponent_family"], row["opponent_role"]):
            raise ValueError(f"invalid neutral opponent metadata: {row['opponent']!r}")
        opponent = row["opponent"]
        if row["opponent_hash"] != EXPECTED_OPPONENT_HASH[opponent]:
            raise ValueError(f"frozen opponent digest drift: {opponent}")
        if row["source_sha256"] != EXPECTED_SOURCE_HASH[opponent]:
            raise ValueError(f"frozen source-artifact digest drift: {opponent}")
        if row["source_artifact"] != EXPECTED_SOURCE_ARTIFACT[opponent]:
            raise ValueError(f"frozen neutral source-artifact path drift: {opponent}")
        expected_seed = EXPECTED_FIRST_SEED_BASE[opponent] + int(row["pair_index"])
        if row["actual_order"] == "second":
            expected_seed += SECOND_ORDER_SEED_OFFSET
        if int(row["seed"]) != expected_seed:
            raise ValueError(
                f"frozen seed schedule drift: {opponent}/{row['actual_order']}/{row['pair_index']}"
            )

    strata = Counter((row["opponent"], row["actual_order"]) for row in fresh)
    if set(strata.values()) != {200} or set(strata) != {
        (opponent, order)
        for opponent in OPPONENT_METADATA
        for order in ("first", "second")
    }:
        raise ValueError(f"unbalanced or incomplete fresh strata: {strata}")
    by_stratum_indices: dict[tuple[str, str], set[int]] = {}
    for row in fresh:
        key = (row["opponent"], row["actual_order"])
        index = int(row["pair_index"])
        indices = by_stratum_indices.setdefault(key, set())
        if index in indices:
            raise ValueError(f"duplicate fresh paired unit: {key + (index,)}")
        indices.add(index)
    if any(indices != set(range(200)) for indices in by_stratum_indices.values()):
        raise ValueError("fresh strata do not each contain pair_index 0..199 exactly once")
    if len({row["seed"] for row in fresh}) != len(fresh):
        raise ValueError("fresh seeds are not globally unique")

    historical_keys = [
        (row["source_artifact"], row["actual_order"], row["pair_index"])
        for row in historical
    ]
    if len(set(historical_keys)) != len(historical_keys):
        raise ValueError("duplicate historical row within source/order/pair_index")

    differences = [int(row["candidate_win"]) - int(row["control_win"]) for row in fresh]
    candidate_only = sum(value == 1 for value in differences)
    control_only = sum(value == -1 for value in differences)
    candidate_wins = sum(int(row["candidate_win"]) for row in fresh)
    control_wins = sum(int(row["control_win"]) for row in fresh)
    candidate_draws = sum(int(row["candidate_draw"]) for row in fresh)
    control_draws = sum(int(row["control_draw"]) for row in fresh)
    ci = primary["paired_bootstrap_95_ci"]
    if (
        not isinstance(ci, list)
        or len(ci) != 2
        or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in ci)
        or not -1 <= ci[0] <= ci[1] <= 1
    ):
        raise ValueError("primary paired bootstrap interval has invalid structure")

    checks = {
        "canonical_sha256": sha256(canonical_path) == summary["canonical_sha256"],
        "effect": math.isclose(
            sum(differences) / len(differences), primary["effect"], rel_tol=0, abs_tol=1e-15
        ),
        "candidate_wins": candidate_wins == primary_integers["candidate_wins"],
        "control_wins": control_wins == primary_integers["control_wins"],
        "candidate_draws": candidate_draws == primary_integers["candidate_draws"],
        "control_draws": control_draws == primary_integers["control_draws"],
        "candidate_only": candidate_only == primary_integers["candidate_only_wins"],
        "control_only": control_only == primary_integers["control_only_wins"],
        "mcnemar": math.isclose(
            exact_mcnemar(candidate_only, control_only),
            primary["mcnemar_exact_two_sided_p"],
            rel_tol=0,
            abs_tol=1e-15,
        ),
        "errors_zero": (
            primary_integers["candidate_errors"] == 0
            and primary_integers["control_errors"] == 0
            and primary_integers["opponent_errors"] == 0
        ),
        "strata": primary_integers["strata"] == len(strata) == 14,
        "frozen_candidate_control_opponent_and_source_hashes": True,
        "frozen_seed_order_pair_and_seat_schedule": True,
        "bootstrap_configuration_recorded": (
            primary_integers["bootstrap_iterations"] > 0
            and primary_integers["bootstrap_seed"] >= 0
        ),
    }
    if not all(checks.values()):
        raise AssertionError(checks)
    print(json.dumps({
        "status": "verified",
        "scope": "schema, row schedule, primary arithmetic, and recorded-summary consistency",
        "not_recomputed": ["paired bootstrap interval", "secondary summaries", "figures"],
        "fresh_pairs": len(fresh),
        "historical_pairs": len(historical),
        "strata": len(strata),
        "effect": primary["effect"],
        "discordant": [candidate_only, control_only],
        "checks": checks,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
