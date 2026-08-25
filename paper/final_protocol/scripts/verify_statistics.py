#!/usr/bin/env python3
"""Independently reaggregate released PEVL rows and recompute statistics."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np


SCRIPT = Path(__file__).resolve()
ROOT = SCRIPT.parents[3]
PAPER = ROOT / "paper"
FINAL = SCRIPT.parents[1]
PROTOCOL_COMMIT = "803257f102232763fc88d28c14b668f9b62eb277"
CANONICAL_HASHES = {
    "preflight": "c6295f9f3981d346d0cbcb38327e575b560aaf0950bd52f52594cfb8f9cc56b3",
    "stress": "40b9f5e17a424742ad8a05739646fe56843b8f3a432b124bfc33f9aed1ab5a4b",
    "factorial": "c7df75c7ae0f76a007d866947ad5262242d86c0c90cb0c8631d201dedd023e59",
    "factorial_units": "62fe1fc3657ccd783e4f068042f201ceae0d7fc02d694a8ee5943d3f5c52e3eb",
    "historical_units": "eca841487814c50acccb7f885207e679b906179bb77e6818dfaa430af47e6fcc",
    "seed_audit": "50344ba5a8b3ab21d037c0d37115562ea0c2c1da8fabdfe0b717d292a52f7a5e",
    "stochastic_audit": "995ab30d0f2166963b5bc7dd73d2784ed95cde2f93315e1e06bece935a875c60",
}

HISTORICAL_FIELDS = {
    "opponent", "actual_order", "seed", "physical_seat",
    "c1_c2_run_win", "c1_c2_run_draw", "c1_c2_run_decisions",
    "c1_c3_run_win", "c1_c3_run_draw", "c1_c3_run_decisions",
    "c1_c4_run_win", "c1_c4_run_draw", "c1_c4_run_decisions",
    "c1_outcome_records_identical", "c1_serialized_records_identical",
}
FACTORIAL_FIELDS = {
    "opponent", "actual_order", "pair_index", "scheduled_seed",
    "engine_seed_uint32", "physical_seat",
    *(f"c{cell}_{field}" for cell in range(1, 5) for field in ("win", "draw", "decisions")),
}


class VerificationError(ValueError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_path(path: Path) -> str:
    """Match the frozen evaluator's canonical file/tree hash contract."""
    if path.is_file():
        return sha256(path)
    if not path.is_dir():
        raise VerificationError(f"hash target is missing: {path}")
    digest = hashlib.sha256()
    children = sorted(
        child for child in path.rglob("*")
        if child.is_file() and "__pycache__" not in child.parts and child.suffix != ".pyc"
    )
    for child in children:
        relative = child.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256(child)))
    return digest.hexdigest()


def verify_declared_sources(summary: dict[str, Any], source_root: Path, label: str) -> int:
    sources = summary.get("sources")
    if not isinstance(sources, list) or not sources:
        raise VerificationError(f"{label} declared sources missing")
    for index, record in enumerate(sources):
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise VerificationError(f"{label} source {index} malformed")
        path = source_root / record["path"]
        require_equal(sha256(path), record.get("sha256"), f"{label} source {index}")
    return len(sources)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise VerificationError(f"JSON object required: {path}")
    return value


def require_equal(observed: Any, expected: Any, label: str) -> None:
    if observed != expected:
        raise VerificationError(f"{label}: expected {expected!r}, found {observed!r}")


def percentile(values: np.ndarray) -> list[float]:
    return [float(value) for value in np.quantile(values, [0.025, 0.975])]


def binary_bootstrap(values: Iterable[int], seed: int) -> dict[str, Any]:
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
        "bootstrap_95_ci": percentile(samples),
        "bootstrap_draws": 100_000,
        "bootstrap_seed": seed,
    }


def exact_mcnemar(first_only: int, second_only: int) -> float:
    discordant = first_only + second_only
    if not discordant:
        return 1.0
    lower = min(first_only, second_only)
    tail = sum(math.comb(discordant, index) for index in range(lower + 1)) / (2**discordant)
    return min(1.0, 2 * tail)


def factorial_bootstrap(arrays: dict[str, np.ndarray]) -> dict[str, Any]:
    if len(arrays) != 10 or any(value.shape != (200, 4) for value in arrays.values()):
        raise VerificationError("factorial requires ten 200-by-4 strata")
    names = ("primary_c4_minus_c1", "representation_main", "training_main", "interaction")
    samples = {name: np.empty(100_000, dtype=np.float64) for name in names}
    rng = np.random.default_rng(2026083117)
    cursor = 0
    while cursor < 100_000:
        batch = min(1_000, 100_000 - cursor)
        totals = {name: np.zeros(batch, dtype=np.float64) for name in names}
        for key in sorted(arrays):
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
            "bootstrap_95_ci": percentile(samples[name]),
            "bootstrap_draws": 100_000,
            "bootstrap_seed": 2026083117,
            "resampling": "paired units within each of ten opponent-by-order strata",
        }
        for name in names
    }


def verify_historical(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not HISTORICAL_FIELDS.issubset(reader.fieldnames):
            raise VerificationError("historical unit schema is missing required control fields")
        rows = list(reader)
    require_equal(len(rows), 2_800, "historical row count")
    outcome_mismatch = 0
    available_record_mismatch = 0
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    seen: set[tuple[str, str, int]] = set()
    for row in rows:
        key = (row["opponent"], row["actual_order"], int(row["seed"]))
        if key in seen:
            raise VerificationError(f"duplicate historical unit: {key}")
        seen.add(key)
        grouped[f"{row['opponent']}/{row['actual_order']}"] .append(row)
        outcomes = {
            (int(row[f"c1_c{cell}_run_win"]), int(row[f"c1_c{cell}_run_draw"]))
            for cell in (2, 3, 4)
        }
        available_records = {
            (
                int(row[f"c1_c{cell}_run_win"]),
                int(row[f"c1_c{cell}_run_draw"]),
                int(row[f"c1_c{cell}_run_decisions"]),
            )
            for cell in (2, 3, 4)
        }
        outcome_identical = int(len(outcomes) == 1)
        available_identical = int(len(available_records) == 1)
        require_equal(
            int(row["c1_outcome_records_identical"]), outcome_identical,
            f"historical derived outcome flag {key}",
        )
        require_equal(
            int(row["c1_serialized_records_identical"]), available_identical,
            f"historical derived available-record flag {key}",
        )
        outcome_mismatch += 1 - outcome_identical
        available_record_mismatch += 1 - available_identical
    require_equal(len(grouped), 14, "historical opponent/order strata")
    require_equal({row["actual_order"] for row in rows}, {"first", "second"}, "historical orders")
    require_equal(len({row["opponent"] for row in rows}), 7, "historical contexts")
    for key, subset in grouped.items():
        subset.sort(key=lambda row: int(row["seed"]))
        require_equal(len(subset), 200, f"historical {key} units")
        seeds = [int(row["seed"]) for row in subset]
        require_equal(seeds, list(range(seeds[0], seeds[0] + 200)), f"historical {key} seed schedule")
        require_equal([int(row["physical_seat"]) for row in subset], [index % 2 for index in range(200)], f"historical {key} seat schedule")
    require_equal(outcome_mismatch, 210, "historical outcome/error mismatch")
    require_equal(available_record_mismatch, 458, "historical available-record mismatch")
    by_context: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        by_context[row["opponent"]]["units"] += 1
        by_context[row["opponent"]]["outcome_mismatch"] += int(row["c1_outcome_records_identical"]) == 0
        by_context[row["opponent"]]["available_record_mismatch"] += int(row["c1_serialized_records_identical"]) == 0
    require_equal(sum(row["units"] for row in by_context.values()), 2_800, "historical context total")
    return {
        "units": len(rows),
        "outcome_error_mismatch": outcome_mismatch,
        "available_record_mismatch": available_record_mismatch,
        "contexts": len(by_context),
        "strata": len(grouped),
        "derived_flags_verified": len(rows) * 2,
    }


def verify_preflight(summary: dict[str, Any], source_root: Path | None) -> dict[str, Any]:
    require_equal(summary.get("protocol_commit"), PROTOCOL_COMMIT, "preflight protocol commit")
    require_equal(summary.get("status"), "PASS", "preflight status")
    rows = summary.get("rows")
    if not isinstance(rows, list):
        raise VerificationError("preflight rows missing")
    require_equal(len(rows), 20, "preflight arm/context jobs")
    totals = Counter()
    identities: set[tuple[str, str]] = set()
    for row in rows:
        context = row.get("opponent", row.get("context"))
        if not isinstance(context, str):
            raise VerificationError("preflight row context is missing")
        identities.add((str(row["arm"]), context))
        for key in (
            "trajectory_units", "executions", "mismatch_units",
            "trace_mismatch_units", "outcome_mismatch_units",
            "error_mismatch_units", "decision_count_mismatch_units",
        ):
            totals[key] += int(row[key])
        if source_root is not None:
            path = source_root / str(row["source"])
            require_equal(sha256(path), row["source_sha256"], f"preflight source {path}")
    require_equal(len(identities), 20, "preflight identity coverage")
    for key, value in totals.items():
        require_equal(value, int(summary[key]), f"preflight total {key}")
    require_equal(totals["trajectory_units"], 1_000, "preflight units")
    require_equal(totals["executions"], 3_000, "preflight executions")
    require_equal(totals["mismatch_units"], 0, "preflight mismatches")
    return dict(totals)


def verify_seed_audit(audit: dict[str, Any], source_root: Path) -> dict[str, Any]:
    require_equal(audit.get("conversion_rule"), "scheduled_seed & 0xffffffff", "seed conversion rule")
    require_equal(audit.get("uint32_max"), 4_294_967_295, "seed uint32 maximum")
    require_equal(audit.get("prospective_passed"), True, "prospective seed audit status")
    provenance = audit.get("provenance", {})
    require_equal(provenance.get("git_commit"), PROTOCOL_COMMIT, "seed audit protocol commit")
    require_equal(provenance.get("provenance_role"), "protocol_commit", "seed audit provenance role")
    script_path = source_root / str(provenance.get("script"))
    require_equal(sha256(script_path), provenance.get("script_sha256"), "seed audit script hash")
    source_count = verify_declared_sources(audit, source_root, "seed audit")

    historical = audit.get("historical_fresh_confirmation", {})
    for key, expected in {
        "scheduled_count": 2_800,
        "scheduled_unique": 2_800,
        "scheduled_outside_uint32": 2_800,
        "conversion_changed": 2_800,
        "engine_seed_unique": 2_800,
        "passed_no_collision": True,
        "collision_groups": {},
    }.items():
        require_equal(historical.get(key), expected, f"historical seed audit {key}")
    require_equal(audit.get("historical_prospective_engine_seed_overlap"), [], "historical/prospective boundary overlap")

    schedule = audit.get("prospective_by_schedule")
    if not isinstance(schedule, dict):
        raise VerificationError("prospective seed schedules missing")
    expected_shape = {"factorial": (5, 400), "timed_search_stress": (2, 100), "trace_preflight": (5, 50)}
    total = 0
    for study, (context_count, unit_count) in expected_shape.items():
        contexts = schedule.get(study)
        if not isinstance(contexts, dict):
            raise VerificationError(f"seed schedule missing: {study}")
        require_equal(len(contexts), context_count, f"seed schedule {study} contexts")
        for context, row in contexts.items():
            for key, expected in {
                "scheduled_count": unit_count,
                "scheduled_unique": unit_count,
                "engine_seed_unique": unit_count,
                "scheduled_outside_uint32": 0,
                "conversion_changed": 0,
                "passed_no_collision": True,
                "collision_groups": {},
            }.items():
                require_equal(row.get(key), expected, f"seed schedule {study}/{context} {key}")
            total += unit_count
    require_equal(total, 2_450, "prospective seed schedule total")
    all_seeds = audit.get("prospective_all", {})
    for key, expected in {
        "scheduled_count": 2_450,
        "scheduled_unique": 2_450,
        "engine_seed_unique": 2_450,
        "scheduled_outside_uint32": 0,
        "conversion_changed": 0,
        "passed_no_collision": True,
        "collision_groups": {},
    }.items():
        require_equal(all_seeds.get(key), expected, f"prospective seed audit {key}")
    return {
        "historical_scheduled_values": 2_800,
        "prospective_scheduled_values": 2_450,
        "prospective_contexts": 12,
        "historical_prospective_overlap": 0,
        "declared_sources_verified": source_count,
    }


def verify_stochastic_audit(audit: dict[str, Any], source_root: Path) -> dict[str, Any]:
    require_equal(audit.get("schema_version"), "pevl-stochastic-source-audit-v1", "stochastic audit schema")
    require_equal(audit.get("audit_levels"), [1, 6], "stochastic audit levels")
    provenance = audit.get("provenance", {})
    require_equal(provenance.get("git_commit"), PROTOCOL_COMMIT, "stochastic audit protocol commit")
    require_equal(provenance.get("provenance_role"), "protocol_commit", "stochastic audit provenance role")
    script_path = source_root / str(provenance.get("script"))
    require_equal(sha256(script_path), provenance.get("script_sha256"), "stochastic audit script hash")
    protocol_path = source_root / str(provenance.get("frozen_protocol"))
    require_equal(sha256(protocol_path), provenance.get("frozen_protocol_sha256"), "stochastic audit protocol hash")

    inventory = audit.get("inventory")
    if not isinstance(inventory, list):
        raise VerificationError("stochastic audit inventory missing")
    require_equal(len(inventory), 13, "stochastic audit artifact count")
    identifiers: set[str] = set()
    category_hits: Counter[str] = Counter()
    artifacts_with_hits: Counter[str] = Counter()
    source_assessed = 0
    for record in inventory:
        artifact_id = str(record.get("artifact_id"))
        if artifact_id in identifiers:
            raise VerificationError(f"duplicate stochastic-audit artifact: {artifact_id}")
        identifiers.add(artifact_id)
        require_equal(record.get("exists"), True, f"stochastic audit {artifact_id} exists")
        require_equal(record.get("expected_digest_present_in_frozen_protocol"), True, f"stochastic audit {artifact_id} protocol digest")
        require_equal(record.get("hash_match"), True, f"stochastic audit {artifact_id} recorded hash match")
        require_equal(record.get("observed_sha256"), record.get("expected_sha256"), f"stochastic audit {artifact_id} digest fields")
        artifact_path = source_root / str(record.get("local_path"))
        require_equal(sha256_path(artifact_path), record.get("expected_sha256"), f"stochastic audit {artifact_id} current digest")
        source_audit = record.get("source_audit", {})
        if source_audit.get("status") == "completed_static_python_ast_scan":
            source_assessed += 1
        categories = source_audit.get("categories", {})
        for name in sorted(audit.get("category_definitions", {})):
            result = categories.get(name, {})
            hits = result.get("hit_count")
            if hits is not None:
                category_hits[name] += int(hits)
                if int(hits) > 0:
                    artifacts_with_hits[name] += 1
    level_results = audit.get("level_results", {})
    level_1 = level_results.get("level_1_artifact_identity", {})
    require_equal(level_1.get("status"), "pass", "stochastic audit Level 1")
    require_equal(level_1.get("artifact_count"), 13, "stochastic audit Level 1 count")
    require_equal(level_1.get("verified_artifact_count"), 13, "stochastic audit verified artifacts")
    level_6 = level_results.get("level_6_stochastic_source_audit", {})
    require_equal(level_6.get("status"), "bounded_audit_recorded", "stochastic audit Level 6")
    require_equal(level_6.get("verified_package_tree_count"), source_assessed, "stochastic audit assessed trees")
    require_equal(level_6.get("aggregate_hits_by_category"), dict(category_hits), "stochastic audit aggregate hits")
    require_equal(level_6.get("artifacts_with_hits_by_category"), {name: artifacts_with_hits[name] for name in sorted(audit.get("category_definitions", {}))}, "stochastic audit artifact-hit counts")
    require_equal(source_assessed, 11, "stochastic audit source-assessed package trees")
    return {
        "artifacts_verified": len(inventory),
        "source_assessed_package_trees": source_assessed,
        "binary_source_assessments": 0,
        "aggregate_hits_by_category": dict(category_hits),
    }


def verify_stress(summary: dict[str, Any], source_root: Path | None) -> dict[str, Any]:
    require_equal(summary.get("protocol_commit"), PROTOCOL_COMMIT, "stress protocol commit")
    rows = summary.get("cluster_rows")
    if not isinstance(rows, list):
        raise VerificationError("stress cluster rows missing")
    require_equal(len(rows), 200, "stress clusters")
    recomputed = {
        "trace_disagreement_clusters": sum(bool(row["trace_disagreement"]) for row in rows),
        "outcome_disagreement_clusters": sum(bool(row["outcome_disagreement"]) for row in rows),
        "decision_count_disagreement_clusters": sum(bool(row["decision_count_disagreement"]) for row in rows),
        "error_disagreement_clusters": sum(bool(row["error_disagreement"]) for row in rows),
        "policy_error_present_clusters": sum(bool(row["policy_error_present"]) for row in rows),
    }
    for key, value in recomputed.items():
        require_equal(value, summary[key], f"stress {key}")
    actor_counts = summary.get("first_divergence_actor_counts")
    require_equal(actor_counts, {"opponent": 99}, "stress earliest-divergence actor counts")
    require_equal(sum(int(value) for value in actor_counts.values()), recomputed["trace_disagreement_clusters"], "stress localized divergence total")
    source_count = verify_declared_sources(summary, source_root, "stress") if source_root is not None else 0
    require_equal(binary_bootstrap((int(row["trace_disagreement"]) for row in rows), 2026083118), summary["trace_disagreement"], "stress overall bootstrap")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        context = row.get("opponent", row.get("context"))
        if not isinstance(context, str):
            raise VerificationError("stress row context is missing")
        grouped[f"{context}/{row['actual_order']}"] .append(row)
    require_equal(set(grouped), set(summary["strata"]), "stress strata")
    for key, subset in grouped.items():
        require_equal(len(subset), 50, f"stress {key} clusters")
        expected = summary["strata"][key]
        require_equal(binary_bootstrap((int(row["trace_disagreement"]) for row in subset), 2026083118), expected["trace_disagreement"], f"stress {key} bootstrap")
        for field, source in (
            ("outcome_disagreement_count", "outcome_disagreement"),
            ("decision_count_disagreement_count", "decision_count_disagreement"),
            ("error_disagreement_count", "error_disagreement"),
            ("policy_error_present_count", "policy_error_present"),
        ):
            require_equal(sum(bool(row[source]) for row in subset), expected[field], f"stress {key} {field}")
    return recomputed | {
        "bootstrap": summary["trace_disagreement"],
        "first_divergence_actor_counts": actor_counts,
        "declared_sources_verified": source_count,
    }


def verify_factorial(summary: dict[str, Any], units_path: Path, source_root: Path | None) -> dict[str, Any]:
    require_equal(summary.get("protocol_commit"), PROTOCOL_COMMIT, "factorial protocol commit")
    require_equal(summary.get("status"), "ADMITTED_SEED_MATCHED", "factorial status")
    require_equal(summary.get("admission_decision"), "admit_with_bounded_wording", "factorial admission decision")
    require_equal(summary.get("units"), 2_000, "factorial summary units")
    require_equal(summary.get("games"), 12_000, "factorial summary games")
    require_equal(summary.get("control_mismatch_units"), 0, "factorial control mismatch gate")
    source_count = verify_declared_sources(summary, source_root, "factorial") if source_root is not None else 0
    with units_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or set(reader.fieldnames) != FACTORIAL_FIELDS:
            raise VerificationError("factorial unit schema does not match the frozen 18-field schema")
        rows = list(reader)
    require_equal(len(rows), 2_000, "factorial unit count")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, str, int]] = set()
    for row in rows:
        key = (row["opponent"], row["actual_order"], int(row["pair_index"]))
        if key in seen:
            raise VerificationError(f"duplicate factorial unit: {key}")
        seen.add(key)
        grouped[f"{row['opponent']}/{row['actual_order']}"] .append(row)
    require_equal(len(grouped), 10, "factorial stratum count")
    arrays: dict[str, np.ndarray] = {}
    ordered_rows: list[dict[str, Any]] = []
    for key, subset in grouped.items():
        subset.sort(key=lambda row: int(row["pair_index"]))
        require_equal([int(row["pair_index"]) for row in subset], list(range(200)), f"factorial {key} indices")
        seeds = [int(row["scheduled_seed"]) for row in subset]
        require_equal(seeds, list(range(seeds[0], seeds[0] + 200)), f"factorial {key} seed schedule")
        require_equal([int(row["engine_seed_uint32"]) for row in subset], seeds, f"factorial {key} boundary seeds")
        require_equal([int(row["physical_seat"]) for row in subset], [index % 2 for index in range(200)], f"factorial {key} seat schedule")
        matrix = np.asarray([[int(row[f"c{cell}_win"]) for cell in range(1, 5)] for row in subset], dtype=np.float64)
        if not np.all(np.isin(matrix, [0.0, 1.0])):
            raise VerificationError(f"nonbinary factorial outcome: {key}")
        draw_matrix = np.asarray([[int(row[f"c{cell}_draw"]) for cell in range(1, 5)] for row in subset], dtype=np.float64)
        if not np.all(np.isin(draw_matrix, [0.0, 1.0])) or np.any(matrix + draw_matrix > 1):
            raise VerificationError(f"invalid factorial win/draw coding: {key}")
        if any(int(row[f"c{cell}_decisions"]) < 0 for row in subset for cell in range(1, 5)):
            raise VerificationError(f"negative factorial decision count: {key}")
        arrays[key] = matrix
        ordered_rows.extend(subset)
    contexts = sorted({row["opponent"] for row in rows})
    require_equal(len(contexts), 5, "factorial contexts")
    for context in contexts:
        first = sorted(
            int(row["scheduled_seed"]) for row in rows
            if row["opponent"] == context and row["actual_order"] == "first"
        )
        second = sorted(
            int(row["scheduled_seed"]) for row in rows
            if row["opponent"] == context and row["actual_order"] == "second"
        )
        require_equal(len(first), 200, f"factorial {context} first-order units")
        require_equal(len(second), 200, f"factorial {context} second-order units")
        require_equal([value - first[index] for index, value in enumerate(second)], [1_000_000] * 200, f"factorial {context} order namespace")
    all_matrix = np.asarray([[int(row[f"c{cell}_win"]) for cell in range(1, 5)] for row in ordered_rows], dtype=np.float64)
    c1, c2, c3, c4 = (all_matrix[:, index] for index in range(4))
    cell_rates = {"C1": float(c1.mean()), "C2": float(c2.mean()), "C3": float(c3.mean()), "C4": float(c4.mean())}
    require_equal(cell_rates, summary["cell_win_rates"], "factorial cell rates")
    estimates = {
        "primary_c4_minus_c1": float(np.mean(c4 - c1)),
        "representation_main": float(np.mean(0.5 * ((c2 - c1) + (c4 - c3)))),
        "training_main": float(np.mean(0.5 * ((c3 - c1) + (c4 - c2)))),
        "interaction": float(np.mean(c4 - c3 - c2 + c1)),
    }
    bootstrap = factorial_bootstrap(arrays)
    for name, estimate in estimates.items():
        require_equal(estimate, summary["contrasts"][name]["estimate"], f"factorial {name} estimate")
        require_equal(bootstrap[name], {key: summary["contrasts"][name][key] for key in bootstrap[name]}, f"factorial {name} bootstrap")
    c4_only = int(np.sum((c4 == 1) & (c1 == 0)))
    c1_only = int(np.sum((c4 == 0) & (c1 == 1)))
    require_equal(c4_only, summary["primary_mcnemar"]["c4_only_wins"], "factorial C4-only wins")
    require_equal(c1_only, summary["primary_mcnemar"]["c1_only_wins"], "factorial C1-only wins")
    require_equal(exact_mcnemar(c4_only, c1_only), summary["primary_mcnemar"]["exact_two_sided_p"], "factorial McNemar")
    return {
        "units": len(rows),
        "games": summary["games"],
        "strata": len(grouped),
        "declared_sources_verified": source_count,
        "cell_win_rates": cell_rates,
        "contrasts": estimates,
        "mcnemar": summary["primary_mcnemar"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", type=Path, default=PAPER / "data/pevl/trace_preflight_summary.json")
    parser.add_argument("--stress", type=Path, default=PAPER / "data/pevl/timed_search_stress_summary.json")
    parser.add_argument("--factorial", type=Path, default=PAPER / "data/pevl/factorial_summary.json")
    parser.add_argument("--factorial-units", type=Path, default=PAPER / "data/pevl/factorial/units.csv")
    parser.add_argument("--historical-units", type=Path, default=PAPER / "data/ablation/canonical_ablation.csv")
    parser.add_argument("--seed-audit", type=Path, default=PAPER / "data/seed_namespace_audit.json")
    parser.add_argument("--stochastic-audit", type=Path, default=PAPER / "data/stochastic_source_audit.json")
    parser.add_argument("--source-root", type=Path, default=ROOT, help="Root used to verify canonical raw-source and artifact hashes; use 'none' only with the processed-release profile")
    parser.add_argument("--profile", choices=("canonical", "release"), default="canonical")
    parser.add_argument("--output", type=Path, default=FINAL / "source_data/statistics_verification.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = {
        "preflight": args.preflight,
        "stress": args.stress,
        "factorial": args.factorial,
        "factorial_units": args.factorial_units,
        "historical_units": args.historical_units,
    }
    if args.profile == "canonical":
        paths["seed_audit"] = args.seed_audit
        paths["stochastic_audit"] = args.stochastic_audit
        for label, path in paths.items():
            require_equal(sha256(path), CANONICAL_HASHES[label], f"canonical {label} hash")
    source_root = None if str(args.source_root).lower() == "none" else args.source_root
    if args.profile == "canonical" and source_root is None:
        raise VerificationError("canonical profile requires --source-root")
    if args.profile == "release" and source_root is not None:
        raise VerificationError("processed release profile requires --source-root none")
    preflight = load_json(args.preflight)
    stress = load_json(args.stress)
    factorial = load_json(args.factorial)
    report = {
        "status": "PASS",
        "protocol_commit": PROTOCOL_COMMIT,
        "profile": args.profile,
        "inputs": {label: {"role": label, "sha256": sha256(path)} for label, path in paths.items()},
        "historical": verify_historical(args.historical_units),
        "preflight": verify_preflight(preflight, source_root),
        "stress": verify_stress(stress, source_root),
        "factorial": verify_factorial(factorial, args.factorial_units, source_root),
    }
    if args.profile == "canonical":
        assert source_root is not None
        report["seed_namespace_audit"] = verify_seed_audit(load_json(args.seed_audit), source_root)
        report["stochastic_source_audit"] = verify_stochastic_audit(load_json(args.stochastic_audit), source_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
