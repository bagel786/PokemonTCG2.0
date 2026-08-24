import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from paper.scripts import analyze_pevl as pevl


def test_exact_mcnemar_handles_balanced_and_one_direction_discordance():
    assert pevl.exact_mcnemar(0, 0) == 1.0
    assert pevl.exact_mcnemar(5, 5) == 1.0
    assert pevl.exact_mcnemar(10, 0) == 2 / (2**10)


def test_binary_bootstrap_is_seeded_cluster_based_and_rejects_invalid_input():
    first = pevl.binary_bootstrap([0, 0, 1, 1], seed=17, draws=2_000)
    second = pevl.binary_bootstrap([0, 0, 1, 1], seed=17, draws=2_000)
    assert first == second
    assert first["clusters"] == 4
    assert first["estimate"] == 0.5
    assert first["bootstrap_95_ci"] == [0.0, 1.0]
    with pytest.raises(ValueError, match="binary cluster values"):
        pevl.binary_bootstrap([0, 2], seed=17, draws=10)
    with pytest.raises(ValueError, match="positive draws"):
        pevl.binary_bootstrap([0, 1], seed=17, draws=0)


def test_factorial_bootstrap_preserves_pairs_and_ignores_mapping_insertion_order():
    indicator = (np.arange(200) % 2).astype(np.float64)
    # C1 and C4 are identical within every unit. A column-wise (unpaired)
    # bootstrap would introduce artificial C4-C1 variability.
    matrix = np.column_stack((indicator, 1 - indicator, 1 - indicator, indicator))
    forward = {f"stratum-{index:02d}": matrix.copy() for index in range(10)}
    reverse = dict(reversed(list(forward.items())))
    first = pevl.factorial_bootstrap(forward, draws=500, seed=23)
    second = pevl.factorial_bootstrap(reverse, draws=500, seed=23)
    assert first == second
    assert first["primary_c4_minus_c1"]["bootstrap_95_ci"] == [0.0, 0.0]
    assert first["representation_main"]["bootstrap_95_ci"] == [0.0, 0.0]
    assert first["training_main"]["bootstrap_95_ci"] == [0.0, 0.0]


def test_factorial_bootstrap_enforces_frozen_shape_and_binary_outcomes():
    matrix = np.zeros((200, 4), dtype=np.float64)
    with pytest.raises(ValueError, match="ten frozen strata"):
        pevl.factorial_bootstrap({f"s{index}": matrix for index in range(9)}, draws=1)
    invalid = {f"s{index}": matrix.copy() for index in range(10)}
    invalid["s0"][0, 0] = 0.5
    with pytest.raises(ValueError, match="binary win indicators"):
        pevl.factorial_bootstrap(invalid, draws=1)


def test_preflight_endpoint_mismatches_are_reported_separately():
    reference = {
        "task-a": {
            "public_trace_sha256": "a" * 64,
            "trace_bytes": 10,
            "win": 1,
            "draw": 0,
            "decisions": 3,
            "hero_policy_errors": 0,
            "opponent_policy_errors": 0,
        }
    }
    changed = {"task-a": dict(reference["task-a"])}
    changed["task-a"].update(
        public_trace_sha256="b" * 64,
        win=0,
        decisions=4,
        hero_policy_errors=1,
    )
    result = pevl.proof_endpoint_mismatches(
        {"reference": reference, "changed": changed},
        run_order=("reference", "changed"),
    )
    assert result == {
        "trace": {"task-a"},
        "outcome": {"task-a"},
        "error": {"task-a"},
        "decision_count": {"task-a"},
    }


def _trace_bytes(actor: str = "hero") -> bytes:
    return json.dumps(
        {"actor": actor, "decision": 0, "event": "action"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"


def _write_stress_proof(root: Path, *, mismatch_task: str | None = None) -> Path:
    opponent = "starmie"
    proof_path = root / opponent / "proof.json"
    base_seed = pevl.STRESS_BASES[opponent]
    expected = pevl.expected_proof_tasks(50, base_seed)
    variants = {
        "serial_forward": (1, "forward"),
        "serial_reverse": (1, "reverse"),
        "parallel_forward": (4, "forward"),
        "parallel_reverse": (4, "reverse"),
    }
    runs = {}
    trace_files = {}
    total = len(expected)
    # Deliberately reverse both object insertion order and row order. Neither is
    # part of the frozen statistical schedule.
    for run, (workers, direction) in reversed(list(variants.items())):
        rows = []
        trace_files[run] = {}
        for task_id, scheduled in reversed(list(expected.items())):
            actor = "opponent" if run == "serial_reverse" and task_id == mismatch_task else "hero"
            trace = _trace_bytes(actor)
            digest = hashlib.sha256(trace).hexdigest()
            trace_dir = proof_path.parent / "determinism_traces" / run
            trace_dir.mkdir(parents=True, exist_ok=True)
            (trace_dir / f"{task_id}.jsonl").write_bytes(trace)
            trace_files[run][task_id] = digest
            base_enqueue = int(scheduled["base_enqueue_position"])
            enqueue = base_enqueue if direction == "forward" else total - 1 - base_enqueue
            seed = int(scheduled["scheduled_seed"])
            rows.append(
                {
                    "task_id": task_id,
                    "pair_index": -1,
                    "arm": None,
                    "seed": seed,
                    "requested_seed": seed,
                    "scheduled_seed": seed,
                    "engine_seed_uint32": seed,
                    "seed_conversion_rule": pevl.SEED_CONVERSION_RULE,
                    "actual_order": scheduled["actual_order"],
                    "physical_seat": scheduled["physical_seat"],
                    "win": 1,
                    "draw": 0,
                    "decisions": 1,
                    "hero_policy_errors": 0,
                    "opponent_policy_errors": 0,
                    "trace_mode": "full",
                    "trace_sha256": digest,
                    "public_trace_sha256": digest,
                    "trace_bytes": len(trace),
                    "hero_env": {},
                    "opponent_env": {},
                    "max_decisions": pevl.MAX_DECISIONS,
                    "process_start_method": pevl.PROCESS_START_METHOD,
                    "enqueue_position": enqueue,
                    "worker_count": workers,
                    "worker_pid": 1000 + enqueue,
                    "worker_process_name": f"worker-{workers}",
                    "elapsed_wall_seconds": 0.01,
                    "execution_variant": run,
                    "schedule_direction": direction,
                    "protocol_id": pevl.PROTOCOL_ID,
                    "protocol_commit": "protocol-commit",
                    "run_uuid": "00000000-0000-4000-8000-000000000001",
                    "schedule_fingerprint_sha256": "a" * 64,
                    "run_fingerprint_sha256": "b" * 64,
                }
            )
        runs[run] = rows

    mismatches = {
        "serial_reverse": [mismatch_task] if mismatch_task else [],
        "parallel_forward": [],
        "parallel_reverse": [],
    }
    payload = {
        "passed": mismatch_task is None,
        "protocol_id": pevl.PROTOCOL_ID,
        "protocol_commit": "protocol-commit",
        "run_uuid": "00000000-0000-4000-8000-000000000001",
        "schedule_fingerprint_sha256": "a" * 64,
        "run_fingerprint_sha256": "b" * 64,
        "engine_sha256": pevl.EXPECTED_HASHES["engine"],
        "hero_sha256": pevl.EXPECTED_HASHES["c1"],
        "opponent_sha256": pevl.EXPECTED_HASHES[opponent],
        "tasks": 100,
        "seeds_per_order": 50,
        "base_seed": base_seed,
        "order_seed_offset": pevl.ORDER_SEED_OFFSET,
        "seed_conversion": {
            "requested_field": "scheduled_seed",
            "engine_field": "engine_seed_uint32",
            "rule": pevl.SEED_CONVERSION_RULE,
            "modulus": pevl.UINT32_MODULUS,
            "schedule_wide_distinct_seed_collision_check": "passed",
        },
        "max_decisions": pevl.MAX_DECISIONS,
        "trace_mode": "full",
        "trace_payload_files_written": True,
        "hero_env": {},
        "opponent_env": {},
        "execution_plan": {
            "profile": "explicit_variants",
            "process_start_method": pevl.PROCESS_START_METHOD,
            "variants": [
                {"name": run, "workers": workers, "schedule_direction": direction}
                for run, (workers, direction) in reversed(list(variants.items()))
            ],
        },
        "execution_environment": {
            "process_start_method": pevl.PROCESS_START_METHOD,
            "python_hash_seed": "0",
        },
        "runs": runs,
        "mismatches": mismatches,
        "trace_files": trace_files,
    }
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    proof_path.write_text(json.dumps(payload), encoding="utf-8")
    return proof_path


def _cheap_binary_bootstrap(values, *, seed, draws=100_000):
    vector = [int(value) for value in values]
    return {
        "clusters": len(vector),
        "estimate": sum(vector) / len(vector),
        "bootstrap_95_ci": [0.0, 1.0],
        "bootstrap_draws": draws,
        "bootstrap_seed": seed,
    }


def test_stress_analysis_is_order_independent_reports_failures_and_verifies_trace_hashes(
    tmp_path, monkeypatch
):
    proof_path = _write_stress_proof(tmp_path, mismatch_task="first-000")
    monkeypatch.setattr(pevl, "TIMED_OPPONENTS", ("starmie",))
    monkeypatch.setattr(pevl, "binary_bootstrap", _cheap_binary_bootstrap)

    result = pevl.analyze_stress(tmp_path)
    assert result["schema_version"] == 1
    assert result["analysis_id"] == "timed_search_stress"
    assert result["status"] == "TRACE_DIVERGENCE"
    assert result["clusters"] == 100
    assert result["executions"] == 400
    assert result["trace_disagreement_clusters"] == 1
    divergent = next(row for row in result["cluster_rows"] if row["trace_disagreement"])
    assert divergent["task_id"] == "first-000"
    assert divergent["first_divergence"]["actors"] == ["hero", "opponent"]
    assert "do not prove a unique causal source" in result["pevl_level_6_boundary"]

    retained = proof_path.parent / "determinism_traces/parallel_forward/first-000.jsonl"
    retained.write_bytes(retained.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="retained trace hash mismatch"):
        pevl.analyze_stress(tmp_path)


def _paired_row(cell: str, order: str, index: int, arm: str) -> dict:
    base_seed = pevl.FACTORIAL_BASES["b0"]
    seed = base_seed + (pevl.ORDER_SEED_OFFSET if order == "second" else 0) + index
    enqueue = (0 if order == "first" else 400) + index * 2 + (arm == "control")
    win = int(cell == "c4" and arm == "candidate")
    return {
        "task_id": f"{order}-{index:05d}-{arm}",
        "pair_index": index,
        "arm": arm,
        "seed": seed,
        "requested_seed": seed,
        "scheduled_seed": seed,
        "engine_seed_uint32": seed,
        "seed_conversion_rule": pevl.SEED_CONVERSION_RULE,
        "actual_order": order,
        "physical_seat": index % 2,
        "win": win,
        "draw": 0,
        "decisions": 10,
        "hero_policy_errors": 0,
        "opponent_policy_errors": 0,
        "trace_mode": "none",
        "trace_sha256": None,
        "public_trace_sha256": None,
        "trace_bytes": 0,
        "hero_env": {},
        "opponent_env": {},
        "max_decisions": pevl.MAX_DECISIONS,
        "process_start_method": pevl.PROCESS_START_METHOD,
        "enqueue_position": int(enqueue),
        "worker_count": 8,
        # Process/timing fields intentionally differ across cell acquisitions;
        # repeated-C1 parity must exclude them.
        "worker_pid": 1000 + {"c2": 2, "c3": 3, "c4": 4}[cell],
        "worker_process_name": f"{cell}-worker",
        "elapsed_wall_seconds": {"c2": 0.02, "c3": 0.03, "c4": 0.04}[cell],
        "execution_variant": None,
        "schedule_direction": None,
        "protocol_id": pevl.PROTOCOL_ID,
        "protocol_commit": "protocol-commit",
        "run_uuid": f"00000000-0000-4000-8000-00000000000{cell[-1]}",
        "schedule_fingerprint_sha256": "a" * 64,
        "run_fingerprint_sha256": cell[-1] * 64,
    }


def _write_factorial_payload(raw: Path, cell: str) -> Path:
    rows = [
        _paired_row(cell, order, index, arm)
        for order in pevl.ORDERS
        for index in range(200)
        for arm in ("candidate", "control")
    ]
    rows.reverse()
    payload = {
        "protocol_id": pevl.PROTOCOL_ID,
        "protocol_commit": "protocol-commit",
        "run_uuid": f"00000000-0000-4000-8000-00000000000{cell[-1]}",
        "schedule_fingerprint_sha256": "a" * 64,
        "run_fingerprint_sha256": cell[-1] * 64,
        "engine_sha256": pevl.EXPECTED_HASHES["engine"],
        "production_engine_sha256_before": pevl.EXPECTED_HASHES["production"],
        "production_engine_sha256_after": pevl.EXPECTED_HASHES["production"],
        "production_engine_preserved": True,
        "candidate_sha256": pevl.EXPECTED_HASHES[cell],
        "control_sha256": pevl.EXPECTED_HASHES["c1"],
        "opponent_sha256": pevl.EXPECTED_HASHES["b0"],
        "base_seed": pevl.FACTORIAL_BASES["b0"],
        "order_seed_offset": pevl.ORDER_SEED_OFFSET,
        "pairs_per_order": 200,
        "actual_orders": ["first", "second"],
        "games": 800,
        "workers": 8,
        "max_decisions": pevl.MAX_DECISIONS,
        "hero_env": {},
        "opponent_env": {},
        "capture_trace_digest": False,
        "seed_conversion": {
            "requested_field": "scheduled_seed",
            "engine_field": "engine_seed_uint32",
            "rule": pevl.SEED_CONVERSION_RULE,
            "modulus": pevl.UINT32_MODULUS,
            "schedule_wide_distinct_seed_collision_check": "passed",
        },
        "execution_plan": {
            "workers": 8,
            "process_start_method": pevl.PROCESS_START_METHOD,
            "actual_orders": ["first", "second"],
            "pairs_per_order": 200,
            "capture_trace_digest": False,
        },
        "execution_environment": {
            "process_start_method": pevl.PROCESS_START_METHOD,
            "python_hash_seed": "0",
        },
        "orders": {"first": {"pairs": 200}, "second": {"pairs": 200}},
        "overall": {"pairs": 400},
        "rows": rows,
    }
    path = raw / f"{cell}_b0.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_factorial_analysis_accepts_real_schema_without_row_order_assumptions(
    tmp_path, monkeypatch
):
    raw = tmp_path / "paper/data/pevl/factorial/raw"
    paths = [_write_factorial_payload(raw, cell) for cell in pevl.CELLS]
    captured = {}

    def cheap_factorial_bootstrap(arrays, *, draws=100_000, seed=2026083117):
        captured["arrays"] = arrays
        return {
            name: {
                "bootstrap_95_ci": [0.0, 1.0],
                "bootstrap_draws": draws,
                "bootstrap_seed": seed,
                "resampling": "test",
            }
            for name in (
                "primary_c4_minus_c1",
                "representation_main",
                "training_main",
                "interaction",
            )
        }

    monkeypatch.setattr(pevl, "ROOT", tmp_path)
    monkeypatch.setattr(pevl, "FACTORIAL_RAW", raw)
    monkeypatch.setattr(pevl, "DETERMINISTIC_OPPONENTS", ("b0",))
    monkeypatch.setattr(pevl, "factorial_bootstrap", cheap_factorial_bootstrap)
    monkeypatch.setattr(pevl, "write_factorial_units", lambda rows: captured.setdefault("rows", rows))

    result = pevl.analyze_factorial({"status": "PASS", "protocol_commit": "protocol-commit"})
    assert result["schema_version"] == 1
    assert result["analysis_id"] == "factorial"
    assert result["status"] == "ADMITTED_SEED_MATCHED"
    assert result["units"] == 400
    assert result["games"] == 2_400
    assert result["control_mismatch_units"] == 0
    assert result["contrasts"]["primary_c4_minus_c1"]["estimate"] == 1.0
    assert set(captured["arrays"]) == {"b0/first", "b0/second"}
    assert all(matrix.shape == (200, 4) for matrix in captured["arrays"].values())
    assert "levels_1_to_6" not in result["pevl_levels"]
    assert "does not prove a unique causal source" in result["pevl_levels"]["level_6"]

    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    payload["rows"][0]["requested_seed"] += 1
    paths[0].write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="incompatible paired row"):
        pevl.analyze_factorial({"status": "PASS", "protocol_commit": "protocol-commit"})


def test_analysis_output_names_are_distinct_from_acquisition_summaries():
    assert pevl.TRACE_PREFLIGHT_OUTPUT == pevl.DATA / "trace_preflight_summary.json"
    assert pevl.TIMED_STRESS_OUTPUT == pevl.DATA / "timed_search_stress_summary.json"
    assert pevl.FACTORIAL_OUTPUT == pevl.DATA / "factorial_summary.json"
    assert pevl.COMBINED_OUTPUT == pevl.DATA / "summary.json"
    assert {
        pevl.TRACE_PREFLIGHT_OUTPUT,
        pevl.TIMED_STRESS_OUTPUT,
        pevl.FACTORIAL_OUTPUT,
    }.isdisjoint(
        {
            pevl.DATA / "preflight/summary.json",
            pevl.DATA / "stress/acquisition_summary.json",
            pevl.DATA / "factorial/acquisition_summary.json",
        }
    )
