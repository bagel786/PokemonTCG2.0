import hashlib
from pathlib import Path

import pytest

from training.evaluate_deterministic_crn import (
    DEFAULT_CONTROL,
    DEFAULT_ENGINE,
    SEED_CONVERSION_RULE,
    UINT32_MODULUS,
    _prepare_tasks,
    _proof_signature,
    _public_observation_sha256,
    _trace_mode,
    assert_converted_seed_uniqueness,
    determinism_proof,
    get_engine,
    load_deck,
    parse_env,
    paired_evaluation,
    paired_summary,
    schedule_fingerprint,
    seed_to_uint32,
)


def row(pair, *, win, seed=None, order="first", seat=0):
    return {
        "pair_index": pair,
        "win": win,
        "draw": 0,
        "seed": pair + 10 if seed is None else seed,
        "actual_order": order,
        "physical_seat": seat,
        "hero_policy_errors": 0,
        "opponent_policy_errors": 0,
        "decisions": 20,
    }


def test_paired_summary_uses_within_seed_differences():
    candidate = [row(0, win=1), row(1, win=0)]
    control = [row(0, win=0), row(1, win=1)]
    summary = paired_summary(candidate, control)
    assert summary["pairs"] == 2
    assert summary["paired_difference"] == 0
    assert summary["discordant_candidate_wins"] == 1
    assert summary["discordant_control_wins"] == 1
    assert summary["concordant"] == 0


def test_paired_summary_rejects_seed_or_schedule_mismatch():
    candidate = [row(0, win=1), row(1, win=0)]
    control = [row(0, win=0, seed=999), row(1, win=1)]
    with pytest.raises(ValueError, match="paired schedules differ"):
        paired_summary(candidate, control)


def test_load_deck_requires_exactly_sixty_cards(tmp_path):
    valid = tmp_path / "valid.csv"
    valid.write_text("7\n" * 60)
    assert load_deck(valid) == [7] * 60

    invalid = tmp_path / "invalid.csv"
    invalid.write_text("7\n" * 59)
    with pytest.raises(ValueError, match="60 cards"):
        load_deck(invalid)


def test_parse_env_requires_key_value_pairs():
    assert parse_env(["NO_SEARCH=1", "DIRECT_POLICY=1"]) == {
        "NO_SEARCH": "1",
        "DIRECT_POLICY": "1",
    }
    with pytest.raises(ValueError, match="KEY=VALUE"):
        parse_env(["NO_SEARCH"])


def test_seed_conversion_is_explicit_uint32_and_collisions_fail_closed():
    assert seed_to_uint32(7) == 7
    assert seed_to_uint32(UINT32_MODULUS + 7) == 7
    assert seed_to_uint32(-1) == UINT32_MODULUS - 1

    paired_tasks = [
        {
            "task_id": "first-00000-candidate",
            "pair_index": 0,
            "arm": "candidate",
            "actual_order": "first",
            "scheduled_seed": 7,
        },
        {
            "task_id": "first-00000-control",
            "pair_index": 0,
            "arm": "control",
            "actual_order": "first",
            "scheduled_seed": 7,
        },
    ]
    assert_converted_seed_uniqueness(paired_tasks)

    with pytest.raises(ValueError, match="uint32 engine-seed collision"):
        assert_converted_seed_uniqueness(
            paired_tasks
            + [
                {
                    "task_id": "first-00001-candidate",
                    "pair_index": 1,
                    "arm": "candidate",
                    "actual_order": "first",
                    "scheduled_seed": UINT32_MODULUS + 7,
                }
            ]
        )

    with pytest.raises(ValueError, match="distinct units"):
        assert_converted_seed_uniqueness(
            paired_tasks
            + [
                {
                    "task_id": "second-00001-candidate",
                    "pair_index": 1,
                    "arm": "candidate",
                    "actual_order": "second",
                    "scheduled_seed": 7,
                }
            ]
        )


def test_prepared_rows_record_exact_seed_and_execution_schedule():
    task = {
        "task_id": "first-00000-candidate",
        "pair_index": 0,
        "arm": "candidate",
        "actual_order": "first",
        "scheduled_seed": UINT32_MODULUS + 9,
        "trace_mode": "digest",
    }
    prepared = _prepare_tasks([task], workers=4)[0]
    assert prepared["seed"] == UINT32_MODULUS + 9
    assert prepared["requested_seed"] == UINT32_MODULUS + 9
    assert prepared["scheduled_seed"] == UINT32_MODULUS + 9
    assert prepared["engine_seed_uint32"] == 9
    assert prepared["seed_conversion_rule"] == SEED_CONVERSION_RULE
    assert prepared["enqueue_position"] == 0
    assert prepared["worker_count"] == 4
    assert prepared["process_start_method"] == "spawn"
    assert prepared["trace_mode"] == "digest"


def test_schedule_and_proof_hashes_exclude_runtime_noise():
    static = {
        "task_id": "first-000",
        "scheduled_seed": 123,
        "actual_order": "first",
        "physical_seat": 0,
        "max_decisions": 2_000,
    }
    noisy_a = {**static, "elapsed_wall_seconds": 1.0, "worker_pid": 100, "run_uuid": "a"}
    noisy_b = {**static, "elapsed_wall_seconds": 9.0, "worker_pid": 999, "run_uuid": "b"}
    assert schedule_fingerprint([noisy_a]) == schedule_fingerprint([noisy_b])

    common_row = {
        **static,
        "seed": 123,
        "requested_seed": 123,
        "engine_seed_uint32": 123,
        "pair_index": -1,
        "arm": None,
        "win": 1,
        "draw": 0,
        "decisions": 20,
        "hero_policy_errors": 0,
        "opponent_policy_errors": 0,
        "trace_sha256": "a" * 64,
        "public_trace_sha256": "a" * 64,
        "trace_bytes": 100,
    }
    signature_a = _proof_signature([{**common_row, **noisy_a}])
    signature_b = _proof_signature([{**common_row, **noisy_b}])
    assert signature_a == signature_b
    changed = _proof_signature([{**common_row, "trace_sha256": "b" * 64}])
    assert changed != signature_a


def test_trace_mode_supports_digest_only_without_changing_legacy_flag():
    assert _trace_mode({"trace_mode": "digest"}) == "digest"
    assert _trace_mode({"capture_trace": True}) == "full"
    assert _trace_mode({"capture_trace": False}) == "none"
    with pytest.raises(ValueError, match="trace_mode"):
        _trace_mode({"trace_mode": "payload-and-timing"})


def test_determinism_audit_writes_expected_failure_without_raising(tmp_path, monkeypatch):
    calls = 0
    submitted_runs = []

    def fake_hash(_path):
        return "f" * 64

    def fake_run_tasks(tasks, workers):
        nonlocal calls
        calls += 1
        submitted_runs.append((workers, list(tasks)))
        rows = []
        for task in tasks:
            trace = b'{"event":"terminal"}\n'
            digest = "b" * 64 if calls == 3 and task["task_id"] == "first-000" else "a" * 64
            rows.append(
                {
                    "task_id": task["task_id"],
                    "pair_index": -1,
                    "arm": None,
                    "seed": task["scheduled_seed"],
                    "requested_seed": task["scheduled_seed"],
                    "scheduled_seed": task["scheduled_seed"],
                    "engine_seed_uint32": seed_to_uint32(task["scheduled_seed"]),
                    "actual_order": task["actual_order"],
                    "physical_seat": task["physical_seat"],
                    "win": 1,
                    "draw": 0,
                    "decisions": 20,
                    "hero_policy_errors": 0,
                    "opponent_policy_errors": 0,
                    "trace_sha256": digest,
                    "public_trace_sha256": digest,
                    "trace_bytes": len(trace),
                    "trace": trace,
                    "elapsed_wall_seconds": float(calls),
                    "worker_pid": calls,
                    "worker_count": workers,
                }
            )
        return rows

    monkeypatch.setattr("training.evaluate_deterministic_crn.sha256_file", fake_hash)
    monkeypatch.setattr("training.evaluate_deterministic_crn.sha256_path", fake_hash)
    monkeypatch.setattr("training.evaluate_deterministic_crn.run_tasks", fake_run_tasks)

    output = tmp_path / "audit.json"
    result = determinism_proof(
        engine=tmp_path / "engine.dll",
        hero=tmp_path / "hero",
        opponent=tmp_path / "opponent",
        output=output,
        base_seed=100,
        seeds_per_order=1,
        parallel_workers=4,
        max_decisions=100,
        protocol_commit="1" * 40,
        run_uuid="00000000-0000-0000-0000-000000000001",
        audit=True,
        hero_env={"DIRECT_POLICY": "1"},
        opponent_env={"NO_SEARCH": "1"},
    )
    assert result["passed"] is False
    assert result["audit_mode"] is True
    assert result["admission_decision"] == "suppress"
    assert list(result["runs"]) == ["single_a", "single_b", "workers_4"]
    assert result["execution_plan"]["profile"] == "legacy_three_run"
    assert result["trace_mode"] == "full"
    assert result["trace_payload_files_written"] is True
    assert result["trace_files"]["single_a"]
    assert result["mismatches"]["workers_4"] == ["first-000"]
    assert result["order_seed_offset"] == 1_000_000
    assert result["hero_env"] == {"DIRECT_POLICY": "1"}
    assert result["opponent_env"] == {"NO_SEARCH": "1"}
    assert submitted_runs[0][1][1]["scheduled_seed"] == 1_000_100
    assert all(
        task["opponent_env"] == {"NO_SEARCH": "1"}
        for _workers, tasks in submitted_runs
        for task in tasks
    )
    assert output.exists()


def test_proof_stress_matrix_runs_forward_reverse_with_digest_only(tmp_path, monkeypatch):
    invocations = []

    def fake_hash(_path):
        return "f" * 64

    def fake_run_tasks(tasks, workers):
        invocations.append((workers, [task["task_id"] for task in tasks], list(tasks)))
        rows = []
        for task in tasks:
            digest = hashlib.sha256(task["task_id"].encode()).hexdigest()
            rows.append(
                {
                    "task_id": task["task_id"],
                    "pair_index": -1,
                    "arm": None,
                    "seed": task["scheduled_seed"],
                    "requested_seed": task["scheduled_seed"],
                    "scheduled_seed": task["scheduled_seed"],
                    "engine_seed_uint32": seed_to_uint32(task["scheduled_seed"]),
                    "actual_order": task["actual_order"],
                    "physical_seat": task["physical_seat"],
                    "win": 1,
                    "draw": 0,
                    "decisions": 20,
                    "hero_policy_errors": 0,
                    "opponent_policy_errors": 0,
                    "trace_sha256": digest,
                    "public_trace_sha256": digest,
                    "trace_bytes": 100,
                    "trace": None,
                    "trace_mode": task["trace_mode"],
                    "hero_env": task["hero_env"],
                    "opponent_env": task["opponent_env"],
                    "execution_variant": task["execution_variant"],
                    "schedule_direction": task["schedule_direction"],
                }
            )
        return rows

    monkeypatch.setattr("training.evaluate_deterministic_crn.sha256_file", fake_hash)
    monkeypatch.setattr("training.evaluate_deterministic_crn.sha256_path", fake_hash)
    monkeypatch.setattr("training.evaluate_deterministic_crn.run_tasks", fake_run_tasks)

    output = tmp_path / "stress-audit.json"
    result = determinism_proof(
        engine=tmp_path / "engine.dll",
        hero=tmp_path / "hero",
        opponent=tmp_path / "opponent",
        output=output,
        base_seed=500,
        seeds_per_order=2,
        parallel_workers=4,
        max_decisions=100,
        protocol_commit="1" * 40,
        run_uuid="00000000-0000-0000-0000-000000000003",
        hero_env={"DIRECT_POLICY": "1"},
        opponent_env={"NO_SEARCH": "1"},
        trace_mode="digest",
        execution_variants=(
            "serial-forward",
            "serial-reverse",
            "parallel-forward",
            "parallel-reverse",
        ),
    )

    assert result["passed"] is True
    assert result["trace_mode"] == "digest"
    assert result["trace_payload_files_written"] is False
    assert result["trace_files"] == {}
    assert not (tmp_path / "determinism_traces").exists()
    assert list(result["runs"]) == [
        "serial_forward",
        "serial_reverse",
        "parallel_forward",
        "parallel_reverse",
    ]
    assert [workers for workers, _task_ids, _tasks in invocations] == [1, 1, 4, 4]
    assert invocations[0][1] == ["first-000", "first-001", "second-000", "second-001"]
    assert invocations[1][1] == list(reversed(invocations[0][1]))
    assert invocations[2][1] == invocations[0][1]
    assert invocations[3][1] == invocations[1][1]
    assert invocations[0][2][2]["scheduled_seed"] == 1_000_500
    assert invocations[0][2][0]["execution_variant"] == "serial_forward"
    assert invocations[1][2][0]["schedule_direction"] == "reverse"
    assert result["runs"]["parallel_reverse"][0]["execution_variant"] == "parallel_reverse"
    assert all(
        task["opponent_env"] == {"NO_SEARCH": "1"}
        for _workers, _task_ids, tasks in invocations
        for task in tasks
    )


def test_paired_evaluation_serializes_manifest_and_digest_only_rows(tmp_path, monkeypatch):
    submitted_tasks = []
    emitted_rows = []

    def fake_hash(_path):
        return "f" * 64

    def fake_run_tasks(tasks, workers):
        submitted_tasks.extend(tasks)
        rows = []
        for enqueue_position, task in enumerate(tasks):
            digest = "d" * 64
            rows.append(
                {
                    "task_id": task["task_id"],
                    "pair_index": task["pair_index"],
                    "arm": task["arm"],
                    "seed": task["scheduled_seed"],
                    "requested_seed": task["scheduled_seed"],
                    "scheduled_seed": task["scheduled_seed"],
                    "engine_seed_uint32": seed_to_uint32(task["scheduled_seed"]),
                    "seed_conversion_rule": SEED_CONVERSION_RULE,
                    "actual_order": task["actual_order"],
                    "physical_seat": task["physical_seat"],
                    "win": int(task["arm"] == "candidate"),
                    "draw": 0,
                    "decisions": 20,
                    "hero_policy_errors": 0,
                    "opponent_policy_errors": 0,
                    "trace_mode": task["trace_mode"],
                    "trace_sha256": digest,
                    "public_trace_sha256": digest,
                    "trace_bytes": 100,
                    "trace": None,
                    "hero_env": task["hero_env"],
                    "opponent_env": task["opponent_env"],
                    "max_decisions": task["max_decisions"],
                    "process_start_method": "spawn",
                    "enqueue_position": enqueue_position,
                    "worker_count": workers,
                    "worker_pid": 100 + enqueue_position,
                    "worker_process_name": "fake-worker",
                    "protocol_id": task["protocol_id"],
                    "protocol_commit": task["protocol_commit"],
                    "run_uuid": task["run_uuid"],
                    "schedule_fingerprint_sha256": task["schedule_fingerprint_sha256"],
                    "run_fingerprint_sha256": task["run_fingerprint_sha256"],
                    "elapsed_wall_seconds": 0.1,
                }
            )
        emitted_rows.extend(rows)
        return rows

    monkeypatch.setattr("training.evaluate_deterministic_crn.sha256_file", fake_hash)
    monkeypatch.setattr("training.evaluate_deterministic_crn.sha256_path", fake_hash)
    monkeypatch.setattr("training.evaluate_deterministic_crn.run_tasks", fake_run_tasks)

    output = tmp_path / "paired.json"
    result = paired_evaluation(
        engine=tmp_path / "engine.dll",
        candidate=tmp_path / "candidate",
        control=tmp_path / "control",
        opponent=tmp_path / "opponent",
        production_engine=tmp_path / "production.dll",
        output=output,
        base_seed=UINT32_MODULUS + 100,
        pairs_per_order=2,
        workers=4,
        max_decisions=500,
        actual_orders=("first",),
        hero_env={"DIRECT_POLICY": "1"},
        opponent_env={"NO_SEARCH": "1"},
        capture_trace_digest=True,
        protocol_id="test-protocol",
        protocol_commit="1" * 40,
        run_uuid="00000000-0000-0000-0000-000000000002",
    )
    assert output.exists()
    assert result["capture_trace_digest"] is True
    assert result["protocol_id"] == "test-protocol"
    assert result["protocol_commit"] == "1" * 40
    assert result["run_uuid"] == "00000000-0000-0000-0000-000000000002"
    assert len(result["schedule_fingerprint_sha256"]) == 64
    assert len(result["run_fingerprint_sha256"]) == 64
    assert result["seed_conversion"]["rule"] == SEED_CONVERSION_RULE
    assert result["order_seed_offset"] == 1_000_000
    assert all(task["trace_mode"] == "digest" for task in submitted_tasks)
    assert all(row["trace"] is None for row in emitted_rows)
    assert all("trace" not in row for row in result["rows"])
    assert all(row["public_trace_sha256"] == "d" * 64 for row in result["rows"])


@pytest.mark.skipif(not DEFAULT_ENGINE.exists(), reason="isolated deterministic DLL has not been built")
def test_seeded_engine_repeats_public_state_and_treats_zero_as_literal_seed():
    engine = get_engine(DEFAULT_ENGINE)
    deck = [int(line) for line in (DEFAULT_CONTROL / "deck.csv").read_text().splitlines() if line.strip()]

    def state_after_order(seed):
        pointer, _ = engine.start(deck, deck, seed)
        try:
            return _public_observation_sha256(engine.select(pointer, [0]))
        finally:
            engine.finish(pointer)

    assert state_after_order(123) == state_after_order(123)
    assert state_after_order(0) == state_after_order(0)
    assert state_after_order(123) != state_after_order(124)


@pytest.mark.skipif(not DEFAULT_ENGINE.exists(), reason="isolated deterministic DLL has not been built")
def test_local_source_engine_matches_production_card_metadata():
    from cg.sim import lib as production

    engine = get_engine(DEFAULT_ENGINE)
    local_cards = engine.lib.AllCard()
    local_attacks = engine.lib.AllAttack()
    assert hashlib.sha256(local_cards).digest() == hashlib.sha256(production.AllCard()).digest()
    assert hashlib.sha256(local_attacks).digest() == hashlib.sha256(production.AllAttack()).digest()
