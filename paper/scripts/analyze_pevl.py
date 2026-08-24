#!/usr/bin/env python3
"""Analyze the frozen PEVL preflight, timed-search stress test, and factorial."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "paper/data/pevl"
PREFLIGHT_RAW = DATA / "preflight/raw"
FACTORIAL_RAW = DATA / "factorial/raw"
DEFAULT_STRESS_ROOT = ROOT / "artifacts/pevl_20260824/stress"
TRACE_PREFLIGHT_OUTPUT = DATA / "trace_preflight_summary.json"
TIMED_STRESS_OUTPUT = DATA / "timed_search_stress_summary.json"
FACTORIAL_OUTPUT = DATA / "factorial_summary.json"
COMBINED_OUTPUT = DATA / "summary.json"
PROTOCOL_ID = "PEVL_PROSPECTIVE_PROTOCOL_20260824"
ORDER_SEED_OFFSET = 1_000_000
MAX_DECISIONS = 2_000
UINT32_MODULUS = 1 << 32
SEED_CONVERSION_RULE = "engine_seed_uint32 = scheduled_seed & 0xffffffff"
PROCESS_START_METHOD = "spawn"

ARMS = ("c1", "c2", "c3", "c4")
CELLS = ("c2", "c3", "c4")
DETERMINISTIC_OPPONENTS = (
    "b0",
    "d842",
    "master",
    "replay",
    "alakazam_no_search",
)
TIMED_OPPONENTS = ("starmie", "dipplin")
RUNS = (
    "serial_forward",
    "serial_reverse",
    "parallel_forward",
    "parallel_reverse",
)
ORDERS = ("first", "second")

PROOF_SIGNATURE_FIELDS = (
    "public_trace_sha256",
    "trace_bytes",
    "win",
    "draw",
    "decisions",
    "hero_policy_errors",
    "opponent_policy_errors",
)

PREFLIGHT_ENDPOINT_FIELDS = {
    "trace": ("public_trace_sha256", "trace_bytes"),
    "outcome": ("win", "draw"),
    "error": ("hero_policy_errors", "opponent_policy_errors"),
    "decision_count": ("decisions",),
}

EXPECTED_HASHES = {
    "engine": "867e3f9bb87e0b48889a44b5d4b04f5d2d434b2a0788d1b2bcfe0caebcb5ab78",
    "production": "7a157f045d333f99d1996d49c12bdbdd148072a619af246385c7295518776e30",
    "c1": "13426288358d597ead809e45c364c7f7b9274a6eebf55ddd942142e3326535c3",
    "c2": "36e804ae6c593db57b595bfca9fd48592da10957f0e5f840a7e390edbeb39b63",
    "c3": "236afa20b4ced63169736fea616849fa564281c05e9435e4dd77ecfb4ae5fd54",
    "c4": "83489e0c80c631763c65375d2a7a34d28d6aa9fbb1d11e89d130c83b1e27f1c0",
    "b0": "0c15b56adf3b09c654505a152309fdc9f8401579a495da714347d98ae735003c",
    "d842": "7db753d6610930d8bd9694b4b9bece5ac48733b825422a3e399c18077b55e64e",
    "master": "8a06ebab47cc60ed981dfada85972eb8a62e732e349f01c2a3085262079f06e8",
    "replay": "30e45955b67893514c8ee077cac15d46fc207efe781cbce1b94242defda4cbdc",
    "alakazam_no_search": "5d44338891094988ca15f0c26d5187316549facd64a7bfbac04aa0048424e8c7",
    "starmie": "1b73779da7dcc93c8f121090bb0f1ae2d9b10b798ca4c70447b0ce1d6d01c0db",
    "dipplin": "076ae8de12d2d6c4a170b47b2d2f9cf538c1d318a05bb2e81f13da9be2cd2026",
}

TRACE_BASES = {
    "b0": 2026072700,
    "d842": 2026073700,
    "master": 2026074700,
    "replay": 2026075700,
    "alakazam_no_search": 2026078700,
}
FACTORIAL_BASES = {
    "b0": 2026082700,
    "d842": 2026083700,
    "master": 2026084700,
    "replay": 2026085700,
    "alakazam_no_search": 2026086700,
}
STRESS_BASES = {"starmie": 2026092700, "dipplin": 2026093700}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def dump(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def percentile_interval(values: np.ndarray) -> list[float]:
    return [float(value) for value in np.quantile(values, [0.025, 0.975])]


def binary_bootstrap(values: Iterable[int], *, seed: int, draws: int = 100_000) -> dict[str, Any]:
    vector = np.asarray(list(values), dtype=np.float64)
    if not len(vector):
        raise ValueError("binary bootstrap requires at least one cluster")
    if draws < 1 or not np.all(np.isin(vector, [0.0, 1.0])):
        raise ValueError("binary bootstrap requires positive draws and binary cluster values")
    rng = np.random.default_rng(seed)
    estimates = np.empty(draws, dtype=np.float64)
    cursor = 0
    while cursor < draws:
        size = min(2_000, draws - cursor)
        indices = rng.integers(0, len(vector), size=(size, len(vector)))
        estimates[cursor : cursor + size] = vector[indices].mean(axis=1)
        cursor += size
    return {
        "clusters": int(len(vector)),
        "estimate": float(vector.mean()),
        "bootstrap_95_ci": percentile_interval(estimates),
        "bootstrap_draws": draws,
        "bootstrap_seed": seed,
    }


def row_map(rows: list[dict[str, Any]]) -> dict[tuple[str, int], dict[str, Any]]:
    mapped: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        key = (str(row["actual_order"]), int(row["pair_index"]))
        if key in mapped:
            raise ValueError(f"duplicate row key {key}")
        mapped[key] = row
    return mapped


def is_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def expected_proof_tasks(count: int, base_seed: int) -> dict[str, dict[str, int | str]]:
    return {
        f"{order}-{index:03d}": {
            "actual_order": order,
            "pair_index": index,
            "scheduled_seed": base_seed + (ORDER_SEED_OFFSET if order == "second" else 0) + index,
            "physical_seat": index % 2,
            "base_enqueue_position": order_index * count + index,
        }
        for order_index, order in enumerate(ORDERS)
        for index in range(count)
    }


def proof_rows_by_task(
    payload: dict[str, Any],
    *,
    path: Path,
    count: int,
    base_seed: int,
    variants: dict[str, tuple[int, str]],
) -> dict[str, dict[str, dict[str, Any]]]:
    expected = expected_proof_tasks(count, base_seed)
    if set(payload.get("runs", {})) != set(variants):
        raise ValueError(f"{path}: unexpected execution variants")
    seed_conversion = payload.get("seed_conversion", {})
    environment = payload.get("execution_environment", {})
    plan = payload.get("execution_plan", {})
    plan_variants = plan.get("variants", [])
    if not isinstance(plan_variants, list):
        raise ValueError(f"{path}: invalid execution plan variants")
    plan_by_name = {
        str(item.get("name")): item
        for item in plan_variants
        if isinstance(item, dict)
    }
    expected_profile = (
        "legacy_three_run"
        if set(variants) == {"single_a", "single_b", "workers_8"}
        else "explicit_variants"
    )
    top_checks = {
        "conversion_requested_field": seed_conversion.get("requested_field") == "scheduled_seed",
        "conversion_engine_field": seed_conversion.get("engine_field") == "engine_seed_uint32",
        "conversion_rule": seed_conversion.get("rule") == SEED_CONVERSION_RULE,
        "conversion_modulus": seed_conversion.get("modulus") == UINT32_MODULUS,
        "collision_check": seed_conversion.get("schedule_wide_distinct_seed_collision_check")
        == "passed",
        "environment_start_method": environment.get("process_start_method")
        == PROCESS_START_METHOD,
        "python_hash_seed": environment.get("python_hash_seed") == "0",
        "plan_profile": plan.get("profile") == expected_profile,
        "plan_start_method": plan.get("process_start_method") == PROCESS_START_METHOD,
        "plan_variant_count": len(plan_variants) == len(variants),
        "plan_variant_names": set(plan_by_name) == set(variants),
        "run_uuid": bool(payload.get("run_uuid")),
        "schedule_fingerprint": is_sha256(payload.get("schedule_fingerprint_sha256")),
        "run_fingerprint": is_sha256(payload.get("run_fingerprint_sha256")),
    }
    for run, (workers, direction) in variants.items():
        planned = plan_by_name.get(run, {})
        top_checks[f"plan_{run}"] = (
            planned.get("workers") == workers
            and planned.get("schedule_direction") == direction
        )
    if not all(top_checks.values()):
        raise ValueError(f"{path}: invalid proof execution metadata: {top_checks}")
    mapped: dict[str, dict[str, dict[str, Any]]] = {}
    total = len(expected)
    for run, (workers, direction) in variants.items():
        rows = payload["runs"][run]
        by_task: dict[str, dict[str, Any]] = {}
        for row in rows:
            task_id = str(row["task_id"])
            if task_id in by_task:
                raise ValueError(f"{path}: duplicate {run} task {task_id}")
            by_task[task_id] = row
        if len(rows) != total or set(by_task) != set(expected):
            raise ValueError(f"{path}: incomplete {run} proof schedule")
        for task_id, scheduled in expected.items():
            row = by_task[task_id]
            base_enqueue = int(scheduled["base_enqueue_position"])
            expected_enqueue = base_enqueue if direction == "forward" else total - 1 - base_enqueue
            elapsed = float(row.get("elapsed_wall_seconds", -1))
            decisions = int(row.get("decisions", -1))
            win = int(row.get("win", -1))
            draw = int(row.get("draw", -1))
            checks = {
                "actual_order": row.get("actual_order") == scheduled["actual_order"],
                "pair_index": int(row.get("pair_index", -1)) == -1,
                "arm": row.get("arm") is None,
                "legacy_seed": int(row.get("seed", -1)) == scheduled["scheduled_seed"],
                "scheduled_seed": int(row.get("scheduled_seed", -1)) == scheduled["scheduled_seed"],
                "requested_seed": int(row.get("requested_seed", -1)) == scheduled["scheduled_seed"],
                "engine_seed": int(row.get("engine_seed_uint32", -1))
                == (int(scheduled["scheduled_seed"]) & 0xFFFFFFFF),
                "seed_conversion_rule": row.get("seed_conversion_rule") == SEED_CONVERSION_RULE,
                "physical_seat": int(row.get("physical_seat", -1)) == scheduled["physical_seat"],
                "workers": int(row.get("worker_count", -1)) == workers,
                "direction": row.get("schedule_direction") == direction,
                "variant": row.get("execution_variant") == run,
                "enqueue_position": int(row.get("enqueue_position", -1)) == expected_enqueue,
                "max_decisions": int(row.get("max_decisions", -1)) == MAX_DECISIONS,
                "process_start_method": row.get("process_start_method") == PROCESS_START_METHOD,
                "worker_pid": int(row.get("worker_pid", -1)) > 0,
                "worker_process_name": bool(row.get("worker_process_name")),
                "elapsed_wall_seconds": math.isfinite(elapsed) and elapsed >= 0.0,
                "outcome": win in {0, 1} and draw in {0, 1} and win + draw <= 1,
                "decisions": 0 <= decisions <= MAX_DECISIONS,
                "policy_errors": int(row.get("hero_policy_errors", -1)) >= 0
                and int(row.get("opponent_policy_errors", -1)) >= 0,
                "trace_mode": row.get("trace_mode") == payload.get("trace_mode"),
                "trace_sha": row.get("trace_sha256") == row.get("public_trace_sha256"),
                "trace_bytes": int(row.get("trace_bytes", 0)) > 0,
                "hero_env": row.get("hero_env") == payload.get("hero_env"),
                "opponent_env": row.get("opponent_env") == payload.get("opponent_env"),
                "protocol_id": row.get("protocol_id") == payload.get("protocol_id"),
                "protocol_commit": row.get("protocol_commit") == payload.get("protocol_commit"),
                "run_uuid": row.get("run_uuid") == payload.get("run_uuid"),
                "schedule_fingerprint": row.get("schedule_fingerprint_sha256")
                == payload.get("schedule_fingerprint_sha256"),
                "run_fingerprint": row.get("run_fingerprint_sha256")
                == payload.get("run_fingerprint_sha256"),
            }
            checks["trace_digest"] = is_sha256(row.get("public_trace_sha256"))
            if not all(checks.values()):
                raise ValueError(f"{path}: invalid {run}/{task_id} metadata: {checks}")
        mapped[run] = by_task
    return mapped


def validate_proof_mismatches(
    payload: dict[str, Any],
    by_run: dict[str, dict[str, dict[str, Any]]],
    *,
    path: Path,
    run_order: tuple[str, ...],
) -> set[str]:
    reference = by_run[run_order[0]]
    computed_by_run = {
        run: {
            task_id
            for task_id, row in by_run[run].items()
            if tuple(row[field] for field in PROOF_SIGNATURE_FIELDS)
            != tuple(reference[task_id][field] for field in PROOF_SIGNATURE_FIELDS)
        }
        for run in run_order[1:]
    }
    reported = payload.get("mismatches", {})
    if not isinstance(reported, dict) or set(reported) != set(computed_by_run):
        raise ValueError(f"{path}: invalid proof mismatch inventory")
    reported_by_run = {run: {str(task_id) for task_id in reported[run]} for run in reported}
    if reported_by_run != computed_by_run:
        raise ValueError(f"{path}: reported and computed proof mismatches differ")
    computed = set().union(*computed_by_run.values()) if computed_by_run else set()
    if bool(payload.get("passed")) != (not computed):
        raise ValueError(f"{path}: proof admission flag contradicts trace records")
    return computed


def proof_endpoint_mismatches(
    by_run: dict[str, dict[str, dict[str, Any]]],
    *,
    run_order: tuple[str, ...],
) -> dict[str, set[str]]:
    """Return task IDs that disagree with the reference run by endpoint.

    These endpoint-specific inventories are deliberately derived from the same
    validated proof rows as the aggregate admission signature.  Reporting them
    separately prevents a zero aggregate from being silently reused for four
    conceptually different checks in the manuscript.
    """

    reference = by_run[run_order[0]]
    return {
        endpoint: {
            task_id
            for run in run_order[1:]
            for task_id, row in by_run[run].items()
            if tuple(row[field] for field in fields)
            != tuple(reference[task_id][field] for field in fields)
        }
        for endpoint, fields in PREFLIGHT_ENDPOINT_FIELDS.items()
    }


def analyze_preflight() -> dict[str, Any]:
    expected = {
        (arm, opponent): PREFLIGHT_RAW / f"{arm}_{opponent}.json"
        for arm in ARMS
        for opponent in DETERMINISTIC_OPPONENTS
    }
    missing = [str(path.relative_to(ROOT)) for path in expected.values() if not path.exists()]
    if missing:
        return {
            "schema_version": 1,
            "analysis_id": "trace_preflight",
            "status": "NOT_RUN" if len(missing) == len(expected) else "INCOMPLETE",
            "admission_decision": "suppress",
            "expected_files": len(expected),
            "missing_files": missing,
        }

    rows: list[dict[str, Any]] = []
    protocol_commits: set[str] = set()
    for (arm, opponent), path in expected.items():
        payload = load(path)
        protocol_commits.add(str(payload["protocol_commit"]))
        if payload["engine_sha256"] != EXPECTED_HASHES["engine"]:
            raise ValueError(f"{path}: engine hash drift")
        if payload["hero_sha256"] != EXPECTED_HASHES[arm]:
            raise ValueError(f"{path}: {arm} hash drift")
        if payload["opponent_sha256"] != EXPECTED_HASHES[opponent]:
            raise ValueError(f"{path}: opponent hash drift")
        if payload.get("base_seed") != TRACE_BASES[opponent]:
            raise ValueError(f"{path}: base seed drift")
        if payload.get("order_seed_offset") != 1_000_000:
            raise ValueError(f"{path}: second-order seed offset drift")
        if payload.get("seeds_per_order") != 25 or payload.get("tasks") != 50:
            raise ValueError(f"{path}: incomplete preflight schedule")
        if (
            payload.get("protocol_id") != PROTOCOL_ID
            or payload.get("max_decisions") != MAX_DECISIONS
            or payload.get("hero_env") != {}
        ):
            raise ValueError(f"{path}: preflight execution configuration drift")
        if (
            payload.get("trace_mode") != "digest"
            or payload.get("trace_payload_files_written") is not False
            or payload.get("trace_files") != {}
        ):
            raise ValueError(f"{path}: preflight did not use digest traces")
        expected_env = {"NO_SEARCH": "1"} if opponent == "alakazam_no_search" else {}
        if payload.get("opponent_env") != expected_env:
            raise ValueError(f"{path}: opponent environment drift")
        by_run = proof_rows_by_task(
            payload,
            path=path,
            count=25,
            base_seed=TRACE_BASES[opponent],
            variants={
                "single_a": (1, "forward"),
                "single_b": (1, "forward"),
                "workers_8": (8, "forward"),
            },
        )
        computed_mismatches = validate_proof_mismatches(
            payload,
            by_run,
            path=path,
            run_order=("single_a", "single_b", "workers_8"),
        )
        endpoint_mismatches = proof_endpoint_mismatches(
            by_run,
            run_order=("single_a", "single_b", "workers_8"),
        )
        if set().union(*endpoint_mismatches.values()) != computed_mismatches:
            raise ValueError(
                f"{path}: endpoint mismatch inventories do not reproduce the "
                "aggregate proof signature"
            )
        if any(
            int(row["hero_policy_errors"]) or int(row["opponent_policy_errors"])
            for run in by_run.values()
            for row in run.values()
        ):
            raise ValueError(f"{path}: preflight contains policy errors")
        rows.append({
            "arm": arm.upper(),
            "opponent": opponent,
            "passed": bool(payload.get("passed")),
            "mismatch_units": len(computed_mismatches),
            "trace_mismatch_units": len(endpoint_mismatches["trace"]),
            "outcome_mismatch_units": len(endpoint_mismatches["outcome"]),
            "error_mismatch_units": len(endpoint_mismatches["error"]),
            "decision_count_mismatch_units": len(
                endpoint_mismatches["decision_count"]
            ),
            "trajectory_units": 50,
            "executions": 150,
            "source": str(path.relative_to(ROOT)),
            "source_sha256": sha256_file(path),
        })

    if len(protocol_commits) != 1:
        raise ValueError(f"preflight mixes protocol commits: {sorted(protocol_commits)}")
    passed = all(row["passed"] and row["mismatch_units"] == 0 for row in rows)
    return {
        "schema_version": 1,
        "analysis_id": "trace_preflight",
        "status": "PASS" if passed else "FAIL",
        "admission_decision": "admit_factorial_acquisition" if passed else "suppress_factorial",
        "protocol_commit": next(iter(protocol_commits)),
        "arms": len(ARMS),
        "opponents": len(DETERMINISTIC_OPPONENTS),
        "trajectory_units": sum(row["trajectory_units"] for row in rows),
        "executions": sum(row["executions"] for row in rows),
        "mismatch_units": sum(row["mismatch_units"] for row in rows),
        "trace_mismatch_units": sum(row["trace_mismatch_units"] for row in rows),
        "outcome_mismatch_units": sum(
            row["outcome_mismatch_units"] for row in rows
        ),
        "error_mismatch_units": sum(row["error_mismatch_units"] for row in rows),
        "decision_count_mismatch_units": sum(
            row["decision_count_mismatch_units"] for row in rows
        ),
        "rows": rows,
        "claim_boundary": (
            "Passing establishes within-arm public-state/action trace reproducibility "
            "for the frozen subset and execution contexts; it does not establish "
            "cross-arm event alignment."
        ),
    }


def first_trace_divergence(proof_path: Path, task_id: str) -> dict[str, Any] | None:
    traces: dict[str, list[bytes]] = {}
    for run in RUNS:
        path = proof_path.parent / "determinism_traces" / run / f"{task_id}.jsonl"
        if not path.exists():
            raise FileNotFoundError(path)
        # Preserve line endings so a digest difference caused only by a missing
        # terminal newline is still localized instead of being silently erased.
        traces[run] = path.read_bytes().splitlines(keepends=True)
    limit = max(len(lines) for lines in traces.values())
    for index in range(limit):
        observed = {
            run: lines[index] if index < len(lines) else None
            for run, lines in traces.items()
        }
        if len(set(observed.values())) == 1:
            continue
        decoded = []
        for run, line in observed.items():
            if line is None:
                decoded.append({"run": run, "event": "missing", "actor": None, "decision": None})
                continue
            event = json.loads(line)
            decoded.append({
                "run": run,
                "event": event.get("event"),
                "actor": event.get("actor"),
                "decision": event.get("decision"),
            })
        return {
            "trace_line": index,
            "event_types": sorted({str(item["event"]) for item in decoded}),
            "actors": sorted({str(item["actor"]) for item in decoded if item["actor"] is not None}),
            "decisions": sorted({int(item["decision"]) for item in decoded if item["decision"] is not None}),
            "run_metadata": decoded,
        }
    return None


def analyze_stress(stress_root: Path) -> dict[str, Any]:
    paths = {opponent: stress_root / opponent / "proof.json" for opponent in TIMED_OPPONENTS}
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        return {
            "schema_version": 1,
            "analysis_id": "timed_search_stress",
            "status": "NOT_RUN" if len(missing) == len(paths) else "INCOMPLETE",
            "expected_files": len(paths),
            "missing_files": missing,
        }

    clusters: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    protocol_commits: set[str] = set()
    timing: dict[str, dict[str, Any]] = {}
    for opponent, path in paths.items():
        payload = load(path)
        protocol_commits.add(str(payload["protocol_commit"]))
        if payload["engine_sha256"] != EXPECTED_HASHES["engine"]:
            raise ValueError(f"{path}: engine hash drift")
        if payload["hero_sha256"] != EXPECTED_HASHES["c1"]:
            raise ValueError(f"{path}: C1 hash drift")
        if payload["opponent_sha256"] != EXPECTED_HASHES[opponent]:
            raise ValueError(f"{path}: opponent hash drift")
        if payload.get("base_seed") != STRESS_BASES[opponent]:
            raise ValueError(f"{path}: base seed drift")
        if payload.get("order_seed_offset") != ORDER_SEED_OFFSET:
            raise ValueError(f"{path}: second-order seed offset drift")
        if payload.get("seeds_per_order") != 50 or payload.get("tasks") != 100:
            raise ValueError(f"{path}: incomplete stress schedule")
        if (
            payload.get("protocol_id") != PROTOCOL_ID
            or payload.get("max_decisions") != MAX_DECISIONS
            or payload.get("hero_env") != {}
            or payload.get("opponent_env") != {}
        ):
            raise ValueError(f"{path}: stress execution configuration drift")
        if payload.get("trace_mode") != "full" or not payload.get("trace_payload_files_written"):
            raise ValueError(f"{path}: stress run lacks retained full traces")
        by_run = proof_rows_by_task(
            payload,
            path=path,
            count=50,
            base_seed=STRESS_BASES[opponent],
            variants={
                "serial_forward": (1, "forward"),
                "serial_reverse": (1, "reverse"),
                "parallel_forward": (4, "forward"),
                "parallel_reverse": (4, "reverse"),
            },
        )
        task_ids = set(expected_proof_tasks(50, STRESS_BASES[opponent]))
        if set(payload.get("trace_files", {})) != set(RUNS):
            raise ValueError(f"{path}: invalid retained trace run inventory")
        for run in RUNS:
            expected_trace_files = payload.get("trace_files", {}).get(run, {})
            if set(expected_trace_files) != task_ids:
                raise ValueError(f"{path}: incomplete retained trace inventory for {run}")
            trace_dir = path.parent / "determinism_traces" / run
            observed_trace_files = {
                trace_path.stem for trace_path in trace_dir.glob("*.jsonl")
            }
            if observed_trace_files != task_ids:
                raise ValueError(f"{trace_dir}: retained trace directory inventory mismatch")
            for task_id, expected_hash in expected_trace_files.items():
                trace_path = trace_dir / f"{task_id}.jsonl"
                if not is_sha256(expected_hash) or sha256_file(trace_path) != expected_hash:
                    raise ValueError(f"{trace_path}: retained trace hash mismatch")
                if by_run[run][task_id]["public_trace_sha256"] != expected_hash:
                    raise ValueError(f"{trace_path}: row and retained trace digests differ")

        timing[opponent] = {}
        for run in RUNS:
            values = np.asarray(
                [float(row["elapsed_wall_seconds"]) for row in by_run[run].values()],
                dtype=np.float64,
            )
            timing[opponent][run] = {
                "games": int(len(values)),
                "mean_seconds": float(values.mean()),
                "median_seconds": float(np.median(values)),
                "interquartile_range_seconds": [
                    float(value) for value in np.quantile(values, [0.25, 0.75])
                ],
            }

        for task_id in sorted(task_ids):
            rows = [by_run[run][task_id] for run in RUNS]
            trace_values = {str(row["public_trace_sha256"]) for row in rows}
            outcome_values = {(int(row["win"]), int(row["draw"])) for row in rows}
            error_values = {
                (int(row["hero_policy_errors"]), int(row["opponent_policy_errors"]))
                for row in rows
            }
            decision_values = {int(row["decisions"]) for row in rows}
            trace_agree = len(trace_values) == 1
            divergence = None if trace_agree else first_trace_divergence(path, task_id)
            if not trace_agree and divergence is None:
                raise ValueError(f"{path}: digest mismatch without a localized divergence for {task_id}")
            first_row = rows[0]
            clusters.append({
                "opponent": opponent,
                "task_id": task_id,
                "actual_order": str(first_row["actual_order"]),
                "scheduled_seed": int(first_row["scheduled_seed"]),
                "engine_seed_uint32": int(first_row["engine_seed_uint32"]),
                "physical_seat": int(first_row["physical_seat"]),
                "all_four_trace_agree": trace_agree,
                "trace_disagreement": not trace_agree,
                "outcome_disagreement": len(outcome_values) != 1,
                "error_disagreement": len(error_values) != 1,
                "policy_error_present": any(any(value) for value in error_values),
                "decision_count_disagreement": len(decision_values) != 1,
                "first_divergence": divergence,
            })
        validate_proof_mismatches(
            payload,
            by_run,
            path=path,
            run_order=RUNS,
        )
        sources.append({
            "opponent": opponent,
            "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
            "sha256": sha256_file(path),
        })

    if len(protocol_commits) != 1:
        raise ValueError(f"stress runs mix protocol commits: {sorted(protocol_commits)}")
    strata: dict[str, Any] = {}
    for opponent in TIMED_OPPONENTS:
        for order in ORDERS:
            subset = [
                row for row in clusters
                if row["opponent"] == opponent and row["actual_order"] == order
            ]
            if len(subset) != 50:
                raise ValueError(f"{opponent}/{order}: expected 50 stress clusters")
            key = f"{opponent}/{order}"
            strata[key] = {
                "trace_disagreement": binary_bootstrap(
                    (row["trace_disagreement"] for row in subset), seed=2026083118
                ),
                "outcome_disagreement_count": sum(row["outcome_disagreement"] for row in subset),
                "decision_count_disagreement_count": sum(
                    row["decision_count_disagreement"] for row in subset
                ),
                "error_disagreement_count": sum(row["error_disagreement"] for row in subset),
                "policy_error_present_count": sum(row["policy_error_present"] for row in subset),
            }

    mismatch_count = sum(row["trace_disagreement"] for row in clusters)
    divergence_actors = Counter(
        actor
        for row in clusters
        if row["first_divergence"] is not None
        for actor in row["first_divergence"]["actors"]
    )
    return {
        "schema_version": 1,
        "analysis_id": "timed_search_stress",
        "status": "TRACE_DIVERGENCE" if mismatch_count else "TRACE_PARITY",
        "protocol_commit": next(iter(protocol_commits)),
        "clusters": len(clusters),
        "executions": len(clusters) * len(RUNS),
        "trace_disagreement_clusters": int(mismatch_count),
        "trace_disagreement": binary_bootstrap(
            (row["trace_disagreement"] for row in clusters), seed=2026083118
        ),
        "outcome_disagreement_clusters": sum(row["outcome_disagreement"] for row in clusters),
        "decision_count_disagreement_clusters": sum(
            row["decision_count_disagreement"] for row in clusters
        ),
        "error_disagreement_clusters": sum(row["error_disagreement"] for row in clusters),
        "policy_error_present_clusters": sum(row["policy_error_present"] for row in clusters),
        "first_divergence_actor_counts": dict(sorted(divergence_actors.items())),
        "strata": strata,
        "timing": timing,
        "cluster_rows": clusters,
        "sources": sources,
        "bootstrap_note": (
            "Each seed/order condition is one resampling cluster containing all four "
            "serial/parallel and forward/reverse executions."
        ),
        "pevl_level_6_boundary": (
            "Trace localization and source inspection identify plausible nondeterminism "
            "mechanisms in the exercised executions; they do not prove a unique causal source."
        ),
    }


def exact_mcnemar(first_wins: int, second_wins: int) -> float:
    discordant = first_wins + second_wins
    if discordant == 0:
        return 1.0
    lower = min(first_wins, second_wins)
    tail = sum(math.comb(discordant, index) for index in range(lower + 1)) / (2**discordant)
    return min(1.0, 2.0 * tail)


def factorial_bootstrap(
    arrays: dict[str, np.ndarray], *, draws: int = 100_000, seed: int = 2026083117
) -> dict[str, Any]:
    if len(arrays) != 10:
        raise ValueError(f"factorial bootstrap requires ten frozen strata, got {len(arrays)}")
    if draws < 1:
        raise ValueError("factorial bootstrap requires at least one draw")
    rng = np.random.default_rng(seed)
    names = ("primary_c4_minus_c1", "representation_main", "training_main", "interaction")
    samples = {name: np.empty(draws, dtype=np.float64) for name in names}
    cursor = 0
    while cursor < draws:
        batch = min(1_000, draws - cursor)
        totals = {name: np.zeros(batch, dtype=np.float64) for name in names}
        for key in sorted(arrays):
            matrix = arrays[key]
            if matrix.shape != (200, 4):
                raise ValueError(f"{key}: expected a 200 by 4 cell matrix")
            if not np.all(np.isin(matrix, [0.0, 1.0])):
                raise ValueError(f"{key}: cell outcomes must be binary win indicators")
            indices = rng.integers(0, 200, size=(batch, 200))
            means = matrix[indices].mean(axis=1)
            c1, c2, c3, c4 = (means[:, index] for index in range(4))
            totals["primary_c4_minus_c1"] += c4 - c1
            totals["representation_main"] += 0.5 * ((c2 - c1) + (c4 - c3))
            totals["training_main"] += 0.5 * ((c3 - c1) + (c4 - c2))
            totals["interaction"] += c4 - c3 - c2 + c1
        for name in names:
            samples[name][cursor : cursor + batch] = totals[name] / len(arrays)
        cursor += batch
    return {
        name: {
            "bootstrap_95_ci": percentile_interval(samples[name]),
            "bootstrap_draws": draws,
            "bootstrap_seed": seed,
            "resampling": "paired units within each of ten opponent-by-order strata",
        }
        for name in names
    }


def write_factorial_units(rows: list[dict[str, Any]]) -> None:
    path = DATA / "factorial/units.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "opponent", "actual_order", "pair_index", "scheduled_seed", "engine_seed_uint32",
        "physical_seat", "c1_win", "c2_win", "c3_win", "c4_win", "c1_draw", "c2_draw",
        "c3_draw", "c4_draw", "c1_decisions", "c2_decisions", "c3_decisions", "c4_decisions",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: row[key] for key in fields} for row in rows)


def analyze_factorial(preflight: dict[str, Any]) -> dict[str, Any]:
    expected = {
        (cell, opponent): FACTORIAL_RAW / f"{cell}_{opponent}.json"
        for cell in CELLS
        for opponent in DETERMINISTIC_OPPONENTS
    }
    existing = [path for path in expected.values() if path.exists()]
    if preflight.get("status") != "PASS":
        if existing:
            raise ValueError("factorial files exist even though the frozen preflight did not pass")
        return {
            "schema_version": 1,
            "analysis_id": "factorial",
            "status": "SUPPRESSED_BY_PREFLIGHT",
            "admission_decision": "suppress",
            "protocol_commit": preflight.get("protocol_commit"),
            "reason": "the frozen four-arm trace preflight did not pass in full",
        }
    missing = [str(path.relative_to(ROOT)) for path in expected.values() if not path.exists()]
    if missing:
        return {
            "schema_version": 1,
            "analysis_id": "factorial",
            "status": "NOT_RUN" if not existing else "INCOMPLETE",
            "admission_decision": "suppress",
            "expected_files": len(expected),
            "missing_files": missing,
        }

    candidates: dict[tuple[str, str], dict[tuple[str, int], dict[str, Any]]] = {}
    controls: dict[tuple[str, str], dict[tuple[str, int], dict[str, Any]]] = {}
    sources: list[dict[str, Any]] = []
    protocol_commits: set[str] = set()
    for (cell, opponent), path in expected.items():
        payload = load(path)
        protocol_commits.add(str(payload["protocol_commit"]))
        seed_conversion = payload.get("seed_conversion", {})
        execution_plan = payload.get("execution_plan", {})
        execution_environment = payload.get("execution_environment", {})
        checks = {
            "engine": payload.get("engine_sha256") == EXPECTED_HASHES["engine"],
            "production_before": payload.get("production_engine_sha256_before") == EXPECTED_HASHES["production"],
            "production_after": payload.get("production_engine_sha256_after") == EXPECTED_HASHES["production"],
            "production_preserved": payload.get("production_engine_preserved") is True,
            "candidate": payload.get("candidate_sha256") == EXPECTED_HASHES[cell],
            "control": payload.get("control_sha256") == EXPECTED_HASHES["c1"],
            "opponent": payload.get("opponent_sha256") == EXPECTED_HASHES[opponent],
            "protocol_id": payload.get("protocol_id") == PROTOCOL_ID,
            "base_seed": payload.get("base_seed") == FACTORIAL_BASES[opponent],
            "order_seed_offset": payload.get("order_seed_offset") == ORDER_SEED_OFFSET,
            "pairs_per_order": payload.get("pairs_per_order") == 200,
            "orders": payload.get("actual_orders") == ["first", "second"],
            "games": payload.get("games") == 800,
            "workers": payload.get("workers") == 8,
            "max_decisions": payload.get("max_decisions") == MAX_DECISIONS,
            "hero_environment": payload.get("hero_env") == {},
            "environment": payload.get("opponent_env") == (
                {"NO_SEARCH": "1"} if opponent == "alakazam_no_search" else {}
            ),
            "no_trace_capture": payload.get("capture_trace_digest") is False,
            "conversion_requested_field": seed_conversion.get("requested_field")
            == "scheduled_seed",
            "conversion_engine_field": seed_conversion.get("engine_field")
            == "engine_seed_uint32",
            "conversion_rule": seed_conversion.get("rule") == SEED_CONVERSION_RULE,
            "conversion_modulus": seed_conversion.get("modulus") == UINT32_MODULUS,
            "collision_check": seed_conversion.get("schedule_wide_distinct_seed_collision_check")
            == "passed",
            "execution_plan_workers": execution_plan.get("workers") == 8,
            "execution_plan_start_method": execution_plan.get("process_start_method")
            == PROCESS_START_METHOD,
            "execution_plan_orders": execution_plan.get("actual_orders") == ["first", "second"],
            "execution_plan_pairs": execution_plan.get("pairs_per_order") == 200,
            "execution_plan_trace": execution_plan.get("capture_trace_digest") is False,
            "environment_start_method": execution_environment.get("process_start_method")
            == PROCESS_START_METHOD,
            "python_hash_seed": execution_environment.get("python_hash_seed") == "0",
            "run_uuid": bool(payload.get("run_uuid")),
            "schedule_fingerprint": is_sha256(payload.get("schedule_fingerprint_sha256")),
            "run_fingerprint": is_sha256(payload.get("run_fingerprint_sha256")),
            "overall_pairs": payload.get("overall", {}).get("pairs") == 400,
            "first_pairs": payload.get("orders", {}).get("first", {}).get("pairs") == 200,
            "second_pairs": payload.get("orders", {}).get("second", {}).get("pairs") == 200,
            "row_count": len(payload.get("rows", [])) == 800,
        }
        if not all(checks.values()):
            raise ValueError(f"{path}: frozen acquisition validation failed: {checks}")
        candidate_rows = [row for row in payload["rows"] if row["arm"] == "candidate"]
        control_rows = [row for row in payload["rows"] if row["arm"] == "control"]
        candidates[(cell, opponent)] = row_map(candidate_rows)
        controls[(cell, opponent)] = row_map(control_rows)
        expected_keys = {(order, index) for order in ORDERS for index in range(200)}
        if set(candidates[(cell, opponent)]) != expected_keys or set(controls[(cell, opponent)]) != expected_keys:
            raise ValueError(f"{path}: incomplete row schedule")
        expected_env = {"NO_SEARCH": "1"} if opponent == "alakazam_no_search" else {}
        for arm, arm_rows in (
            ("candidate", candidates[(cell, opponent)]),
            ("control", controls[(cell, opponent)]),
        ):
            for (order, index), row in arm_rows.items():
                expected_seed = (
                    FACTORIAL_BASES[opponent]
                    + (ORDER_SEED_OFFSET if order == "second" else 0)
                    + index
                )
                expected_enqueue = (
                    (0 if order == "first" else 400)
                    + index * 2
                    + (0 if arm == "candidate" else 1)
                )
                elapsed = float(row.get("elapsed_wall_seconds", -1))
                decisions = int(row.get("decisions", -1))
                win = int(row.get("win", -1))
                draw = int(row.get("draw", -1))
                row_checks = {
                    "task_id": row.get("task_id") == f"{order}-{index:05d}-{arm}",
                    "arm": row.get("arm") == arm,
                    "legacy_seed": int(row.get("seed", -1)) == expected_seed,
                    "requested_seed": int(row.get("requested_seed", -1)) == expected_seed,
                    "scheduled_seed": int(row.get("scheduled_seed", -1)) == expected_seed,
                    "engine_seed": int(row.get("engine_seed_uint32", -1))
                    == (expected_seed & 0xFFFFFFFF),
                    "seed_conversion_rule": row.get("seed_conversion_rule")
                    == SEED_CONVERSION_RULE,
                    "physical_seat": int(row.get("physical_seat", -1)) == index % 2,
                    "max_decisions": int(row.get("max_decisions", -1)) == MAX_DECISIONS,
                    "worker_count": int(row.get("worker_count", -1)) == 8,
                    "process_start_method": row.get("process_start_method")
                    == PROCESS_START_METHOD,
                    "enqueue_position": int(row.get("enqueue_position", -1))
                    == expected_enqueue,
                    "worker_pid": int(row.get("worker_pid", -1)) > 0,
                    "worker_process_name": bool(row.get("worker_process_name")),
                    "elapsed_wall_seconds": math.isfinite(elapsed) and elapsed >= 0.0,
                    "hero_env": row.get("hero_env") == {},
                    "opponent_env": row.get("opponent_env") == expected_env,
                    "protocol_id": row.get("protocol_id") == PROTOCOL_ID,
                    "protocol_commit": row.get("protocol_commit") == payload.get("protocol_commit"),
                    "run_uuid": row.get("run_uuid") == payload.get("run_uuid"),
                    "schedule_fingerprint": row.get("schedule_fingerprint_sha256")
                    == payload.get("schedule_fingerprint_sha256"),
                    "run_fingerprint": row.get("run_fingerprint_sha256")
                    == payload.get("run_fingerprint_sha256"),
                    "trace_mode": row.get("trace_mode") == "none",
                    "trace_digest": row.get("trace_sha256") is None
                    and row.get("public_trace_sha256") is None
                    and int(row.get("trace_bytes", -1)) == 0,
                    "outcome": win in {0, 1} and draw in {0, 1} and win + draw <= 1,
                    "decisions": 0 <= decisions <= MAX_DECISIONS,
                }
                if not all(row_checks.values()):
                    raise ValueError(
                        f"{path}: incompatible paired row {order}/{index}: {row_checks}"
                    )
        sources.append({
            "cell": cell.upper(),
            "opponent": opponent,
            "path": str(path.relative_to(ROOT)),
            "sha256": sha256_file(path),
        })

    if len(protocol_commits) != 1 or next(iter(protocol_commits)) != preflight["protocol_commit"]:
        raise ValueError("preflight and factorial protocol commits differ")

    comparison_fields = (
        "scheduled_seed", "engine_seed_uint32", "actual_order", "physical_seat",
        "win", "draw", "hero_policy_errors", "opponent_policy_errors", "decisions",
    )
    control_mismatches: list[dict[str, Any]] = []
    unit_rows: list[dict[str, Any]] = []
    arrays: dict[str, np.ndarray] = {}
    for opponent in DETERMINISTIC_OPPONENTS:
        for order in ORDERS:
            matrix = np.empty((200, 4), dtype=np.float64)
            for index in range(200):
                key = (order, index)
                c1_rows = [controls[(cell, opponent)][key] for cell in CELLS]
                signatures = [tuple(row[field] for field in comparison_fields) for row in c1_rows]
                if len(set(signatures)) != 1:
                    control_mismatches.append({
                        "opponent": opponent,
                        "actual_order": order,
                        "pair_index": index,
                    })
                c1 = c1_rows[0]
                cell_rows = {cell: candidates[(cell, opponent)][key] for cell in CELLS}
                all_rows = [c1, *cell_rows.values()]
                if any(
                    int(row["hero_policy_errors"]) or int(row["opponent_policy_errors"])
                    for row in all_rows
                ):
                    raise ValueError(f"policy error at {opponent}/{order}/{index}")
                expected_seed = FACTORIAL_BASES[opponent] + (1_000_000 if order == "second" else 0) + index
                if any(
                    int(row["scheduled_seed"]) != expected_seed
                    or int(row["engine_seed_uint32"]) != expected_seed
                    or int(row["physical_seat"]) != index % 2
                    for row in all_rows
                ):
                    raise ValueError(f"schedule mismatch at {opponent}/{order}/{index}")
                matrix[index] = [
                    int(c1["win"]), int(cell_rows["c2"]["win"]),
                    int(cell_rows["c3"]["win"]), int(cell_rows["c4"]["win"]),
                ]
                unit_rows.append({
                    "opponent": opponent,
                    "actual_order": order,
                    "pair_index": index,
                    "scheduled_seed": expected_seed,
                    "engine_seed_uint32": expected_seed,
                    "physical_seat": index % 2,
                    "c1_win": int(c1["win"]),
                    "c2_win": int(cell_rows["c2"]["win"]),
                    "c3_win": int(cell_rows["c3"]["win"]),
                    "c4_win": int(cell_rows["c4"]["win"]),
                    "c1_draw": int(c1["draw"]),
                    "c2_draw": int(cell_rows["c2"]["draw"]),
                    "c3_draw": int(cell_rows["c3"]["draw"]),
                    "c4_draw": int(cell_rows["c4"]["draw"]),
                    "c1_decisions": int(c1["decisions"]),
                    "c2_decisions": int(cell_rows["c2"]["decisions"]),
                    "c3_decisions": int(cell_rows["c3"]["decisions"]),
                    "c4_decisions": int(cell_rows["c4"]["decisions"]),
                })
            arrays[f"{opponent}/{order}"] = matrix

    if control_mismatches:
        return {
            "schema_version": 1,
            "analysis_id": "factorial",
            "status": "SUPPRESSED_CONTROL_PARITY_FAILURE",
            "admission_decision": "suppress_all_factorial_contrasts",
            "protocol_commit": next(iter(protocol_commits)),
            "control_mismatch_units": len(control_mismatches),
            "first_control_mismatches": control_mismatches[:20],
            "sources": sources,
        }

    write_factorial_units(unit_rows)
    c1 = np.asarray([row["c1_win"] for row in unit_rows], dtype=np.float64)
    c2 = np.asarray([row["c2_win"] for row in unit_rows], dtype=np.float64)
    c3 = np.asarray([row["c3_win"] for row in unit_rows], dtype=np.float64)
    c4 = np.asarray([row["c4_win"] for row in unit_rows], dtype=np.float64)
    estimates = {
        "primary_c4_minus_c1": float(np.mean(c4 - c1)),
        "representation_main": float(np.mean(0.5 * ((c2 - c1) + (c4 - c3)))),
        "training_main": float(np.mean(0.5 * ((c3 - c1) + (c4 - c2)))),
        "interaction": float(np.mean(c4 - c3 - c2 + c1)),
    }
    bootstrap = factorial_bootstrap(arrays)
    contrasts = {
        name: {"estimate": estimate, **bootstrap[name]}
        for name, estimate in estimates.items()
    }
    simple_effects = {
        "c2_minus_c1": float(np.mean(c2 - c1)),
        "c3_minus_c1": float(np.mean(c3 - c1)),
        "c4_minus_c1": float(np.mean(c4 - c1)),
        "c4_minus_c2": float(np.mean(c4 - c2)),
        "c4_minus_c3": float(np.mean(c4 - c3)),
    }
    c4_only = int(np.sum((c4 == 1) & (c1 == 0)))
    c1_only = int(np.sum((c4 == 0) & (c1 == 1)))
    return {
        "schema_version": 1,
        "analysis_id": "factorial",
        "status": "ADMITTED_SEED_MATCHED",
        "admission_decision": "admit_with_bounded_wording",
        "protocol_commit": next(iter(protocol_commits)),
        "target_population": "five prospectively frozen determinism-eligible opponent packages by two actual orders",
        "units": len(unit_rows),
        "games": len(unit_rows) * 6,
        "control_mismatch_units": 0,
        "cell_win_rates": {
            "C1": float(c1.mean()), "C2": float(c2.mean()),
            "C3": float(c3.mean()), "C4": float(c4.mean()),
        },
        "contrasts": contrasts,
        "simple_effects_descriptive": simple_effects,
        "primary_mcnemar": {
            "c4_only_wins": c4_only,
            "c1_only_wins": c1_only,
            "exact_two_sided_p": exact_mcnemar(c4_only, c1_only),
            "role": "secondary",
        },
        "pevl_levels": {
            "levels_1_to_5": (
                "supported only for the frozen artifacts, schedules, and exercised "
                "serial/parallel execution contexts"
            ),
            "level_6": (
                "stochastic sources were inspected and trace divergence can localize "
                "plausible mechanisms; the audit does not prove a unique causal source"
            ),
            "level_7": "not established because the restricted engine exposes no event identifiers or event-keyed streams",
            "level_8": "seed-matched finite-population contrasts admitted; counterfactual and full-CRN wording prohibited",
        },
        "sources": sources,
    }


def historical_summary() -> dict[str, Any]:
    path = ROOT / "paper/data/ablation/summary.json"
    payload = load(path)
    audit = payload["control_parity_audit"]
    return {
        "status": payload["status"],
        "units": int(audit["pairs"]),
        "outcome_record_mismatch_units": int(audit["outcome_record_mismatch_units"]),
        "outcome_record_mismatch_rate": audit["outcome_record_mismatch_units"] / audit["pairs"],
        "serialized_record_mismatch_units": int(audit["serialized_record_mismatch_units"]),
        "serialized_record_mismatch_rate": audit["serialized_record_mismatch_units"] / audit["pairs"],
        "by_opponent": audit["by_opponent"],
        "cause_audit": payload["cause_audit"],
        "source": str(path.relative_to(ROOT)),
        "source_sha256": sha256_file(path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stress-root", type=Path, default=DEFAULT_STRESS_ROOT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    preflight = analyze_preflight()
    stress = analyze_stress(args.stress_root)
    factorial = analyze_factorial(preflight)
    historical = historical_summary()
    dump(TRACE_PREFLIGHT_OUTPUT, preflight)
    dump(TIMED_STRESS_OUTPUT, stress)
    dump(FACTORIAL_OUTPUT, factorial)
    combined = {
        "schema_version": 1,
        "framework": "Paired Evaluation Validity Ladder",
        "protocol": "paper/protocol/PEVL_PROSPECTIVE_PROTOCOL.md",
        "historical_control_parity": historical,
        "prospective_trace_preflight": preflight,
        "timed_search_stress": stress,
        "gated_factorial": factorial,
        "claim_boundary": (
            "Same schedule, reproducible execution, and event-aligned stochastic coupling "
            "are distinct. Game-engine results cannot establish Level 7."
        ),
    }
    dump(COMBINED_OUTPUT, combined)
    print(json.dumps({
        "preflight": preflight["status"],
        "stress": stress["status"],
        "factorial": factorial["status"],
        "output": str(COMBINED_OUTPUT.relative_to(ROOT)),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
