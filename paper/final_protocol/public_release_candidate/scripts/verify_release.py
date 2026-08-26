#!/usr/bin/env python3
"""Fail-closed verification of the processed, engine-independent review package."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

import numpy as np


SCRIPT = Path(__file__).resolve()
RELEASE = SCRIPT.parents[1]
sys.path.insert(0, str(RELEASE))
PROTOCOL_COMMIT = "803257f102232763fc88d28c14b668f9b62eb277"
MANIFEST_LINE = re.compile(r"([0-9a-f]{64})  ([^\r\n]+)")


class VerificationError(ValueError):
    """Raised when released evidence or package structure is inconsistent."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(observed: Any, expected: Any, label: str) -> None:
    if observed != expected:
        raise VerificationError(f"{label}: expected {expected!r}, found {observed!r}")


def safe_relative(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        bool(value)
        and not path.is_absolute()
        and "\\" not in value
        and value == path.as_posix()
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def verify_manifest(expected_manifest_sha256: str | None = None) -> dict[str, Any]:
    path = RELEASE / "MANIFEST.sha256"
    if not path.is_file() or path.is_symlink() or path.stat().st_nlink != 1:
        raise VerificationError(
            "MANIFEST.sha256 must be a regular, single-link, non-symlink file"
        )
    manifest_sha256 = sha256(path)
    if expected_manifest_sha256 is not None:
        if re.fullmatch(r"[0-9a-f]{64}", expected_manifest_sha256) is None:
            raise VerificationError("external manifest pin must be one lowercase SHA-256")
        require(manifest_sha256, expected_manifest_sha256, "external manifest pin")
    entries: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        match = MANIFEST_LINE.fullmatch(line)
        if not match:
            raise VerificationError(f"malformed manifest line {number}")
        digest, relative = match.groups()
        if not safe_relative(relative) or relative == "MANIFEST.sha256":
            raise VerificationError(f"unsafe manifest path on line {number}: {relative!r}")
        if relative in entries:
            raise VerificationError(f"duplicate manifest path: {relative}")
        entries[relative] = digest
    actual: set[str] = set()
    actual_directories: set[str] = set()
    for item in RELEASE.rglob("*"):
        relative = item.relative_to(RELEASE).as_posix()
        if item.is_symlink():
            raise VerificationError(f"symlink prohibited: {relative}")
        if item.is_file():
            if item.stat().st_nlink != 1:
                raise VerificationError(f"hard-linked file prohibited: {relative}")
            if relative != "MANIFEST.sha256":
                actual.add(relative)
        elif item.is_dir():
            actual_directories.add(relative)
        else:
            raise VerificationError(f"special filesystem object prohibited: {relative}")
    require(actual, set(entries), "manifest entry set")
    expected_directories = {
        parent.as_posix()
        for relative in entries
        for parent in PurePosixPath(relative).parents
        if parent.as_posix() != "."
    }
    require(actual_directories, expected_directories, "manifest directory set")
    for relative, digest in entries.items():
        file_path = RELEASE / relative
        if not file_path.is_file() or file_path.is_symlink():
            raise VerificationError(f"manifest entry is not a regular file: {relative}")
        require(sha256(file_path), digest, f"manifest digest {relative}")
    return {
        "entries": len(entries),
        "manifest_sha256": manifest_sha256,
        "trust_anchor": (
            "caller_supplied_manifest_pin"
            if expected_manifest_sha256 is not None
            else "internal_consistency_only"
        ),
        "integrity_scope": (
            "manifest bytes matched the caller-supplied SHA-256; external provenance remains the caller's responsibility"
            if expected_manifest_sha256 is not None
            else "internal consistency only; no external manifest pin supplied"
        ),
    }


def load_json(relative: str) -> dict[str, Any]:
    value = json.loads((RELEASE / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise VerificationError(f"JSON object required: {relative}")
    return value


def load_csv(relative: str, expected_fields: tuple[str, ...]) -> list[dict[str, str]]:
    with (RELEASE / relative).open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        require(tuple(reader.fieldnames or ()), expected_fields, f"CSV schema {relative}")
        return list(reader)


def percentile(values: np.ndarray) -> list[float]:
    return [float(value) for value in np.quantile(values, [0.025, 0.975])]


def binary_reweighting(values: Iterable[int], seed: int) -> dict[str, Any]:
    vector = np.asarray(list(values), dtype=np.float64)
    if not len(vector) or not np.all(np.isin(vector, [0.0, 1.0])):
        raise VerificationError("binary cluster vector is empty or nonbinary")
    rng = np.random.default_rng(seed)
    samples = np.empty(100_000, dtype=np.float64)
    cursor = 0
    while cursor < len(samples):
        batch = min(2_000, len(samples) - cursor)
        indices = rng.integers(0, len(vector), size=(batch, len(vector)))
        samples[cursor : cursor + batch] = vector[indices].mean(axis=1)
        cursor += batch
    return {
        "clusters": int(len(vector)),
        "estimate": float(vector.mean()),
        "quantiles_2_5_97_5": percentile(samples),
        "reweighting_draws": 100_000,
        "reweighting_seed": seed,
    }


def stratified_binary_reweighting(
    strata: dict[str, list[int]], seed: int
) -> dict[str, Any]:
    if not strata:
        raise VerificationError("stratified reweighting requires at least one stratum")
    vectors = {key: np.asarray(strata[key], dtype=np.float64) for key in sorted(strata)}
    if any(not len(vector) or not np.all(np.isin(vector, [0.0, 1.0])) for vector in vectors.values()):
        raise VerificationError("stratified cluster vectors must be nonempty and binary")
    rng = np.random.default_rng(seed)
    samples = np.zeros(100_000, dtype=np.float64)
    for key in sorted(vectors):
        vector = vectors[key]
        indices = rng.integers(0, len(vector), size=(100_000, len(vector)))
        samples += vector[indices].mean(axis=1) / len(vectors)
    return {
        "estimate": float(np.mean([vector.mean() for vector in vectors.values()])),
        "quantiles_2_5_97_5": percentile(samples),
        "reweighting_draws": 100_000,
        "reweighting_seed": seed,
        "stratum_disagreement_counts": {
            key: int(vectors[key].sum()) for key in sorted(vectors)
        },
    }


def factorial_reweighting(arrays: dict[str, np.ndarray]) -> dict[str, dict[str, Any]]:
    if len(arrays) != 10 or any(value.shape != (200, 4) for value in arrays.values()):
        raise VerificationError("factorial requires ten 200-by-4 strata")
    names = ("primary_c4_minus_c1", "representation_main", "training_main", "interaction")
    samples = {name: np.empty(100_000, dtype=np.float64) for name in names}
    rng = np.random.default_rng(2026083117)
    cursor = 0
    while cursor < 100_000:
        batch = min(1_000, 100_000 - cursor)
        totals = {name: np.zeros(batch, dtype=np.float64) for name in names}
        # Preserve the frozen analyzer's stratum accumulation order after
        # neutralization.  The order is immaterial to the estimand but avoids
        # platform-visible last-bit changes from floating-point addition.
        context_order = {
            "deterministic-5": 0,
            "deterministic-1": 1,
            "deterministic-2": 2,
            "deterministic-3": 3,
            "deterministic-4": 4,
        }
        ordered_keys = sorted(
            arrays,
            key=lambda key: (
                context_order[key.rsplit("/", 1)[0]],
                0 if key.endswith("/first") else 1,
            ),
        )
        for key in ordered_keys:
            matrix = arrays[key]
            indices = rng.integers(0, 200, size=(batch, 200))
            means = matrix[indices].mean(axis=1)
            c1, c2, c3, c4 = (means[:, index] for index in range(4))
            totals["primary_c4_minus_c1"] += c4 - c1
            totals["representation_main"] += 0.5 * ((c2 - c1) + (c4 - c3))
            totals["training_main"] += 0.5 * ((c3 - c1) + (c4 - c2))
            totals["interaction"] += c4 - c3 - c2 + c1
        for name in names:
            samples[name][cursor : cursor + batch] = totals[name] / 10
        cursor += batch
    return {
        name: {
            "quantiles_2_5_97_5": percentile(samples[name]),
            "reweighting_draws": 100_000,
            "reweighting_seed": 2026083117,
            "reweighting": "stratified paired-unit empirical reweighting within each of ten fixed opponent-by-order strata",
        }
        for name in names
    }


HISTORICAL_FIELDS = (
    "context", "actual_order", "unit_index", "scheduled_seed", "physical_seat",
    "control_repeat_1_win", "control_repeat_1_draw", "control_repeat_1_decisions",
    "control_repeat_2_win", "control_repeat_2_draw", "control_repeat_2_decisions",
    "control_repeat_3_win", "control_repeat_3_draw", "control_repeat_3_decisions",
    "outcome_record_identical", "available_record_identical",
)


def verify_historical() -> dict[str, Any]:
    rows = load_csv("data/processed/historical_control_repetition.csv", HISTORICAL_FIELDS)
    require(len(rows), 2_800, "historical units")
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    outcome_mismatch = 0
    available_mismatch = 0
    for row in rows:
        groups[(row["context"], row["actual_order"])].append(row)
        outcomes = {
            (row[f"control_repeat_{index}_win"], row[f"control_repeat_{index}_draw"])
            for index in range(1, 4)
        }
        available = {
            (
                row[f"control_repeat_{index}_win"],
                row[f"control_repeat_{index}_draw"],
                row[f"control_repeat_{index}_decisions"],
            )
            for index in range(1, 4)
        }
        outcome_identical = int(len(outcomes) == 1)
        available_identical = int(len(available) == 1)
        require(int(row["outcome_record_identical"]), outcome_identical, "historical outcome flag")
        require(int(row["available_record_identical"]), available_identical, "historical available-record flag")
        outcome_mismatch += 1 - outcome_identical
        available_mismatch += 1 - available_identical
    require(len(groups), 14, "historical strata")
    for key, subset in groups.items():
        subset.sort(key=lambda row: int(row["unit_index"]))
        require([int(row["unit_index"]) for row in subset], list(range(200)), f"historical indices {key}")
        seeds = [int(row["scheduled_seed"]) for row in subset]
        require(seeds, list(range(seeds[0], seeds[0] + 200)), f"historical seed schedule {key}")
        require([int(row["physical_seat"]) for row in subset], [index % 2 for index in range(200)], f"historical seats {key}")
    require(outcome_mismatch, 210, "historical outcome-record mismatches")
    require(available_mismatch, 458, "historical available-record mismatches")
    summary = load_json("data/processed/historical_summary.json")
    require(summary["outcome_record_mismatches"], outcome_mismatch, "historical summary outcome count")
    require(summary["available_record_mismatches"], available_mismatch, "historical summary available count")
    return {"units": len(rows), "strata": len(groups), "outcome_record_mismatches": outcome_mismatch, "available_record_mismatches": available_mismatch}


PREFLIGHT_FIELDS = (
    "arm", "context", "actual_order", "unit_index", "scheduled_seed", "engine_seed_uint32", "physical_seat",
    "repeat_1_trace_sha256", "repeat_1_trace_bytes", "repeat_1_win", "repeat_1_draw", "repeat_1_decisions", "repeat_1_policy_errors",
    "repeat_2_trace_sha256", "repeat_2_trace_bytes", "repeat_2_win", "repeat_2_draw", "repeat_2_decisions", "repeat_2_policy_errors",
    "worker_profile_trace_sha256", "worker_profile_trace_bytes", "worker_profile_win", "worker_profile_draw", "worker_profile_decisions", "worker_profile_policy_errors",
    "trace_digest_identical", "trace_bytes_identical", "outcome_identical", "error_identical", "decision_count_identical", "unit_identical",
)


def verify_preflight() -> dict[str, Any]:
    rows = load_csv("data/processed/preflight_units.csv", PREFLIGHT_FIELDS)
    require(len(rows), 1_000, "preflight trajectory units")
    identities = Counter((row["arm"], row["context"]) for row in rows)
    require(len(identities), 20, "preflight arm/context jobs")
    require(set(identities.values()), {50}, "preflight units per job")
    counts = Counter()
    for row in rows:
        require(int(row["engine_seed_uint32"]), int(row["scheduled_seed"]), "preflight boundary seed")
        digests = [row[f"{profile}_trace_sha256"] for profile in ("repeat_1", "repeat_2", "worker_profile")]
        byte_counts = [int(row[f"{profile}_trace_bytes"]) for profile in ("repeat_1", "repeat_2", "worker_profile")]
        outcomes = [(row[f"{profile}_win"], row[f"{profile}_draw"]) for profile in ("repeat_1", "repeat_2", "worker_profile")]
        errors = [int(row[f"{profile}_policy_errors"]) for profile in ("repeat_1", "repeat_2", "worker_profile")]
        decisions = [int(row[f"{profile}_decisions"]) for profile in ("repeat_1", "repeat_2", "worker_profile")]
        flags = {
            "trace_digest_identical": int(len(set(digests)) == 1),
            "trace_bytes_identical": int(len(set(byte_counts)) == 1),
            "outcome_identical": int(len(set(outcomes)) == 1),
            "error_identical": int(len(set(errors)) == 1),
            "decision_count_identical": int(len(set(decisions)) == 1),
        }
        flags["unit_identical"] = int(all(flags.values()))
        for key, value in flags.items():
            require(int(row[key]), value, f"preflight {key}")
            counts[f"{key}_failures"] += 1 - value
    require(set(counts.values()), {0}, "preflight mismatch counts")
    summary = load_json("data/processed/preflight_summary.json")
    require(summary["protocol_commit"], PROTOCOL_COMMIT, "preflight protocol commit")
    require(summary["status"], "PASS", "preflight status")
    require(summary["trajectory_units"], 1_000, "preflight summary units")
    require(summary["executions"], 3_000, "preflight summary executions")
    require(summary["mismatch_units"], 0, "preflight summary mismatch units")
    return {"trajectory_units": len(rows), "executions": len(rows) * 3, "jobs": len(identities), **dict(counts)}


def verify_stress() -> dict[str, Any]:
    summary = load_json("data/processed/timed_search_stress.json")
    require(summary["protocol_commit"], PROTOCOL_COMMIT, "stress protocol commit")
    rows = summary.get("cluster_rows")
    if not isinstance(rows, list):
        raise VerificationError("stress cluster rows missing")
    require(len(rows), 200, "stress clusters")
    counts = {
        "trace_disagreement_clusters": sum(bool(row["trace_disagreement"]) for row in rows),
        "outcome_disagreement_clusters": sum(bool(row["outcome_disagreement"]) for row in rows),
        "decision_count_disagreement_clusters": sum(bool(row["decision_count_disagreement"]) for row in rows),
        "error_disagreement_clusters": sum(bool(row["error_disagreement"]) for row in rows),
        "policy_error_present_clusters": sum(bool(row["policy_error_present"]) for row in rows),
    }
    for key, value in counts.items():
        require(summary[key], value, f"stress {key}")
    require(counts, {
        "trace_disagreement_clusters": 99,
        "outcome_disagreement_clusters": 47,
        "decision_count_disagreement_clusters": 93,
        "error_disagreement_clusters": 0,
        "policy_error_present_clusters": 0,
    }, "stress frozen counts")
    observed_overall = binary_reweighting(
        (int(row["trace_disagreement"]) for row in rows), 2026083118
    )
    for field, value in observed_overall.items():
        require(value, summary["trace_disagreement"][field], f"stress reweighting {field}")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[f"{row['context']}/{row['actual_order']}"].append(row)
    require(set(grouped), set(summary["strata"]), "stress strata")
    for key, subset in grouped.items():
        require(len(subset), 50, f"stress stratum units {key}")
        observed = binary_reweighting(
            (int(row["trace_disagreement"]) for row in subset), 2026083118
        )
        for field, value in observed.items():
            require(
                value,
                summary["strata"][key]["trace_disagreement"][field],
                f"stress stratum reweighting {key} {field}",
            )
    sensitivity = stratified_binary_reweighting(
        {
            key: [int(row["trace_disagreement"]) for row in subset]
            for key, subset in grouped.items()
        },
        2026083118,
    )
    for field, value in sensitivity.items():
        require(
            value,
            summary["fixed_composition_reweighting_sensitivity"][field],
            f"stress fixed-composition sensitivity {field}",
        )
    require(summary["first_divergence_actor_counts_included"], True, "stress actor counts recovered")
    require(
        summary["first_divergence_actor_counts"],
        {"opponent": counts["trace_disagreement_clusters"]},
        "stress actor counts match disagreement clusters",
    )
    require(summary["first_divergence_position_included"], False, "stress position omission")
    require(summary["timing_summaries_included"], True, "stress timing summaries recovered")
    timing = summary["timing_summaries"]
    require(set(timing), {"timed-search-A", "timed-search-B"}, "stress timing opponents")
    for opponent, profiles in timing.items():
        require(
            set(profiles),
            {"serial_forward", "serial_reverse", "parallel_forward", "parallel_reverse"},
            f"stress timing profiles {opponent}",
        )
        for profile, values in profiles.items():
            require(values["games"], 100, f"stress timing games {opponent}/{profile}")
            require(bool(values["median_seconds"] > 0.0), True, f"stress timing median {opponent}/{profile}")
    provenance = summary["recovered_secondary_outputs_provenance"]
    require(len(provenance["source_sha256"]), 64, "recovered output source hash present")
    require(
        summary["protocol_deviation_status"],
        "PENDING_HUMAN_SIGNOFF_UNSIGNED_POSITIONS_UNRECOVERED",
        "stress protocol deviation status",
    )
    return {
        "clusters": len(rows),
        **counts,
        "trace_disagreement": summary["trace_disagreement"],
        "fixed_composition_reweighting_sensitivity": summary["fixed_composition_reweighting_sensitivity"],
    }


FACTORIAL_FIELDS = (
    "context", "actual_order", "pair_index", "scheduled_seed", "engine_seed_uint32", "physical_seat",
    "c1_win", "c2_win", "c3_win", "c4_win", "c1_draw", "c2_draw", "c3_draw", "c4_draw",
    "c1_decisions", "c2_decisions", "c3_decisions", "c4_decisions",
)


def verify_factorial() -> dict[str, Any]:
    rows = load_csv("data/processed/factorial_units.csv", FACTORIAL_FIELDS)
    require(len(rows), 2_000, "factorial units")
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[f"{row['context']}/{row['actual_order']}"].append(row)
    require(len(grouped), 10, "factorial strata")
    arrays: dict[str, np.ndarray] = {}
    ordered: list[dict[str, str]] = []
    for key, subset in grouped.items():
        subset.sort(key=lambda row: int(row["pair_index"]))
        require([int(row["pair_index"]) for row in subset], list(range(200)), f"factorial indices {key}")
        seeds = [int(row["scheduled_seed"]) for row in subset]
        require(seeds, list(range(seeds[0], seeds[0] + 200)), f"factorial seeds {key}")
        require([int(row["engine_seed_uint32"]) for row in subset], seeds, f"factorial boundary seeds {key}")
        require([int(row["physical_seat"]) for row in subset], [index % 2 for index in range(200)], f"factorial seats {key}")
        matrix = np.asarray([[int(row[f"c{cell}_win"]) for cell in range(1, 5)] for row in subset], dtype=np.float64)
        draws = np.asarray([[int(row[f"c{cell}_draw"]) for cell in range(1, 5)] for row in subset], dtype=np.float64)
        if not np.all(np.isin(matrix, [0.0, 1.0])) or not np.all(np.isin(draws, [0.0, 1.0])) or np.any(matrix + draws > 1):
            raise VerificationError(f"invalid factorial outcome coding: {key}")
        arrays[key] = matrix
        ordered.extend(subset)
    contexts = sorted({row["context"] for row in rows})
    require(len(contexts), 5, "factorial contexts")
    for context in contexts:
        first = sorted(int(row["scheduled_seed"]) for row in rows if row["context"] == context and row["actual_order"] == "first")
        second = sorted(int(row["scheduled_seed"]) for row in rows if row["context"] == context and row["actual_order"] == "second")
        require([second[index] - first[index] for index in range(200)], [1_000_000] * 200, f"factorial order namespace {context}")
    matrix = np.asarray([[int(row[f"c{cell}_win"]) for cell in range(1, 5)] for row in ordered], dtype=np.float64)
    c1, c2, c3, c4 = (matrix[:, index] for index in range(4))
    rates = {"C1": float(c1.mean()), "C2": float(c2.mean()), "C3": float(c3.mean()), "C4": float(c4.mean())}
    estimates = {
        "primary_c4_minus_c1": float(np.mean(c4 - c1)),
        "representation_main": float(np.mean(0.5 * ((c2 - c1) + (c4 - c3)))),
        "training_main": float(np.mean(0.5 * ((c3 - c1) + (c4 - c2)))),
        "interaction": float(np.mean(c4 - c3 - c2 + c1)),
    }
    summary = load_json("data/processed/factorial_summary.json")
    require(summary["protocol_commit"], PROTOCOL_COMMIT, "factorial protocol commit")
    require(summary["status"], "ADMITTED_SEED_MATCHED", "factorial status")
    require(summary["legacy_acquisition_status"], "ADMITTED_SEED_MATCHED", "factorial legacy acquisition status retained verbatim")
    require(summary["final_reporting_status"], "ADMITTED_FIXED_BATTERY_DESCRIPTIVE", "factorial final reporting status")
    require(summary["units"], 2_000, "factorial summary units")
    require(summary["games"], 12_000, "factorial summary games")
    require(summary["control_mismatch_units"], 0, "factorial control gate")
    require(rates, summary["cell_win_rates"], "factorial cell rates")
    reweighting = factorial_reweighting(arrays)
    for name, estimate in estimates.items():
        require(estimate, summary["contrasts"][name]["estimate"], f"factorial estimate {name}")
        for field, value in reweighting[name].items():
            require(value, summary["contrasts"][name][field], f"factorial {name} {field}")
    require("primary_mcnemar" in summary, False, "factorial inferential McNemar field omitted")
    require(summary["mcnemar_recalculation_included"], False, "factorial McNemar omission marker")
    return {"units": len(rows), "games": 12_000, "strata": len(grouped), "cell_win_rates": rates, "contrasts": estimates}


def verify_synthetic() -> dict[str, Any]:
    from pevl_bench import synthetic
    from pevl_bench.admission import load_json_document
    from pevl_bench.schema_subset import CheckedSchemaError, validate_instance

    failures = synthetic.verify_outputs(RELEASE / "pevl_bench/results")
    if failures:
        raise VerificationError("synthetic fixtures failed: " + "; ".join(failures))
    report = load_json_document(RELEASE / "pevl_bench/results/pevl_results.json")
    schema = load_json_document(RELEASE / "pevl_bench/results/pevl_results.schema.json")
    try:
        validate_instance(report, schema, label="synthetic results")
    except CheckedSchemaError as exc:
        raise VerificationError(f"synthetic JSON Schema validation failed: {exc}") from exc
    require(len(report["modes"]), 5, "synthetic mode count")
    require(len(report["levels"]), 8, "synthetic level count")
    return {
        "modes": 5,
        "levels": 8,
        "status": "verified",
        "json_schema": "checked_subset_validated",
    }


def verify_admission() -> dict[str, Any]:
    from pevl_bench import synthetic_admission
    from pevl_bench.admission import AdmissionProtocol, load_json_document
    from pevl_bench.evidence import verify_and_admit

    protocol = AdmissionProtocol.load(RELEASE / "protocol")
    retained_table = (RELEASE / "docs/ADMISSION_DECISION_TABLE.md").read_text(
        encoding="utf-8"
    )
    require(retained_table, protocol.render_decision_table(), "admission decision table")
    example = verify_and_admit(
        load_json_document(RELEASE / "examples/example_evidence.json"),
        protocol,
        evidence_root=RELEASE / "examples",
    )
    require(example["input_valid"], True, "worked admission example validity")
    require(example["evidence_verified"], True, "worked admission evidence verification")
    failures = synthetic_admission.verify_outputs(
        RELEASE / "pevl_bench/admission_results", protocol
    )
    if failures:
        raise VerificationError(
            "synthetic admission decisions failed: " + "; ".join(failures)
        )
    return {
        "status": "verified",
        "protocol_bundle_sha256": protocol.bundle_sha256,
        "worked_example_claim_class": example["permitted_claim_class"],
        "worked_example_external_scientific_provenance_verified": example[
            "external_scientific_provenance_verified"
        ],
        "worked_example_trust_anchor": example["evidence_trust_anchor"],
        "synthetic_modes_routed": 5,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify the exact release tree and independently reaggregate retained evidence."
    )
    parser.add_argument(
        "--expected-manifest-sha256",
        help=(
            "optional external trust anchor; without it verification establishes "
            "internal consistency only"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = {
        "status": "PASS",
        "scope": "engine-independent processed review package",
        "protocol_commit": PROTOCOL_COMMIT,
        "manifest": verify_manifest(args.expected_manifest_sha256),
        "synthetic": verify_synthetic(),
        "admission": verify_admission(),
        "historical": verify_historical(),
        "preflight": verify_preflight(),
        "stress": verify_stress(),
        "factorial": verify_factorial(),
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
