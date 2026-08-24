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


def analyze_preflight() -> dict[str, Any]:
    expected = {
        (arm, opponent): PREFLIGHT_RAW / f"{arm}_{opponent}.json"
        for arm in ARMS
        for opponent in DETERMINISTIC_OPPONENTS
    }
    missing = [str(path.relative_to(ROOT)) for path in expected.values() if not path.exists()]
    if missing:
        return {
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
        if payload.get("trace_mode") != "digest":
            raise ValueError(f"{path}: preflight did not use digest traces")
        if set(payload.get("runs", {})) != {"single_a", "single_b", "workers_8"}:
            raise ValueError(f"{path}: unexpected execution variants")
        expected_env = {"NO_SEARCH": "1"} if opponent == "alakazam_no_search" else {}
        if payload.get("opponent_env") != expected_env:
            raise ValueError(f"{path}: opponent environment drift")
        mismatch_units = sorted({
            task_id
            for task_ids in payload.get("mismatches", {}).values()
            for task_id in task_ids
        })
        rows.append({
            "arm": arm.upper(),
            "opponent": opponent,
            "passed": bool(payload.get("passed")),
            "mismatch_units": len(mismatch_units),
            "trajectory_units": 50,
            "executions": 150,
            "source": str(path.relative_to(ROOT)),
            "source_sha256": sha256_file(path),
        })

    if len(protocol_commits) != 1:
        raise ValueError(f"preflight mixes protocol commits: {sorted(protocol_commits)}")
    passed = all(row["passed"] and row["mismatch_units"] == 0 for row in rows)
    return {
        "status": "PASS" if passed else "FAIL",
        "admission_decision": "admit_factorial_acquisition" if passed else "suppress_factorial",
        "protocol_commit": next(iter(protocol_commits)),
        "arms": len(ARMS),
        "opponents": len(DETERMINISTIC_OPPONENTS),
        "trajectory_units": sum(row["trajectory_units"] for row in rows),
        "executions": sum(row["executions"] for row in rows),
        "mismatch_units": sum(row["mismatch_units"] for row in rows),
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
        traces[run] = path.read_bytes().splitlines()
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
        if payload.get("seeds_per_order") != 50 or payload.get("tasks") != 100:
            raise ValueError(f"{path}: incomplete stress schedule")
        if payload.get("trace_mode") != "full" or not payload.get("trace_payload_files_written"):
            raise ValueError(f"{path}: stress run lacks retained full traces")
        if set(payload.get("runs", {})) != set(RUNS):
            raise ValueError(f"{path}: unexpected stress execution variants")
        by_run = {
            run: {str(row["task_id"]): row for row in payload["runs"][run]}
            for run in RUNS
        }
        task_ids = set(by_run[RUNS[0]])
        if any(set(rows) != task_ids for rows in by_run.values()):
            raise ValueError(f"{path}: stress run schedules differ")
        for run in RUNS:
            expected_trace_files = payload.get("trace_files", {}).get(run, {})
            if set(expected_trace_files) != task_ids:
                raise ValueError(f"{path}: incomplete retained trace inventory for {run}")
            for task_id, expected_hash in expected_trace_files.items():
                trace_path = path.parent / "determinism_traces" / run / f"{task_id}.jsonl"
                if not trace_path.exists() or sha256_file(trace_path) != expected_hash:
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
                "decision_count_disagreement": len(decision_values) != 1,
                "first_divergence": divergence,
            })
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
            }

    mismatch_count = sum(row["trace_disagreement"] for row in clusters)
    divergence_actors = Counter(
        actor
        for row in clusters
        if row["first_divergence"] is not None
        for actor in row["first_divergence"]["actors"]
    )
    return {
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
        "first_divergence_actor_counts": dict(sorted(divergence_actors.items())),
        "strata": strata,
        "timing": timing,
        "cluster_rows": clusters,
        "sources": sources,
        "bootstrap_note": (
            "Each seed/order condition is one resampling cluster containing all four "
            "serial/parallel and forward/reverse executions."
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
            "status": "SUPPRESSED_BY_PREFLIGHT",
            "admission_decision": "suppress",
            "reason": "the frozen four-arm trace preflight did not pass in full",
        }
    missing = [str(path.relative_to(ROOT)) for path in expected.values() if not path.exists()]
    if missing:
        return {
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
        checks = {
            "engine": payload.get("engine_sha256") == EXPECTED_HASHES["engine"],
            "production_before": payload.get("production_engine_sha256_before") == EXPECTED_HASHES["production"],
            "production_after": payload.get("production_engine_sha256_after") == EXPECTED_HASHES["production"],
            "production_preserved": payload.get("production_engine_preserved") is True,
            "candidate": payload.get("candidate_sha256") == EXPECTED_HASHES[cell],
            "control": payload.get("control_sha256") == EXPECTED_HASHES["c1"],
            "opponent": payload.get("opponent_sha256") == EXPECTED_HASHES[opponent],
            "base_seed": payload.get("base_seed") == FACTORIAL_BASES[opponent],
            "pairs_per_order": payload.get("pairs_per_order") == 200,
            "orders": payload.get("actual_orders") == ["first", "second"],
            "games": payload.get("games") == 800,
            "workers": payload.get("workers") == 8,
            "max_decisions": payload.get("max_decisions") == 2_000,
            "environment": payload.get("opponent_env") == (
                {"NO_SEARCH": "1"} if opponent == "alakazam_no_search" else {}
            ),
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
            "status": "SUPPRESSED_CONTROL_PARITY_FAILURE",
            "admission_decision": "suppress_all_factorial_contrasts",
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
            "levels_1_to_6": "supported within the frozen artifacts, schedules, audits, and execution contexts",
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
    dump(DATA / "preflight/analysis_summary.json", preflight)
    dump(DATA / "stress/summary.json", stress)
    dump(DATA / "factorial/summary.json", factorial)
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
    dump(DATA / "summary.json", combined)
    print(json.dumps({
        "preflight": preflight["status"],
        "stress": stress["status"],
        "factorial": factorial["status"],
        "output": str((DATA / "summary.json").relative_to(ROOT)),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
