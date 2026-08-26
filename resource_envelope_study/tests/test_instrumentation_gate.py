from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

import pytest
from jsonschema.validators import validator_for

from resource_envelope_study.canonical import hash_file, hash_json, write_canonical_json
from resource_envelope_study.instrumentation import (
    GATE_REPORT_SCHEMA_VERSION,
    InstrumentationError,
    InstrumentationLimits,
    InstrumentationWorkerError,
    FrozenInstrumentationState,
    SYNTHETIC_ENTRYPOINT,
    _normalize_result,
    _spawn_case,
    _stop_child,
    _student_t_quantile,
    build_instrumentation_manifest,
    build_instrumentation_run_config,
    evaluate_instrumentation_gate,
    execute_instrumentation_manifest,
    synthetic_instrumentation_entrypoint,
    validate_instrumentation_gate_report,
    validate_instrumentation_manifest,
)


SCHEMA_ROOT = Path(__file__).resolve().parents[1] / "schemas" / "v1"


def _available_cpu() -> int:
    if hasattr(os, "sched_getaffinity"):
        return min(os.sched_getaffinity(0))
    return 0


def _study_files(
    root: Path,
    *,
    off_ns: int = 1_000_000,
    on_ns: int = 1_000_000,
) -> tuple[dict[str, Any], Path, str, dict[str, Any], Path, str]:
    root.mkdir(parents=True, exist_ok=True)
    state_path = root / "state.raw"
    state_path.write_bytes(b"exact-frozen-test-state\n")
    state = FrozenInstrumentationState(
        state_id="state-test-1",
        source_game_id="source-test-1",
        state_file=str(state_path),
        state_file_sha256=hash_file(state_path),
    )
    run_config = build_instrumentation_run_config(
        entrypoint=SYNTHETIC_ENTRYPOINT,
        entrypoint_payload={
            "off_search_wall_ns": off_ns,
            "on_search_wall_ns": on_ns,
        },
        target_cpus=(_available_cpu(),),
        worker_timeout_s=1.0,
        thread_env={},
        platform_expectations={},
        test_mode=True,
        require_linux_affinity=False,
    )
    run_config_path = root / "instrumentation-run-config.json"
    run_config_sha256 = write_canonical_json(run_config_path, run_config)
    manifest = build_instrumentation_manifest(
        master_seed=20260826091,
        frozen_states=[state],
        fixed_work_by_agent={
            "one_ply_value_v1": 11,
            "flat_rollout_v1": 12,
            "puct_tree_v1": 13,
        },
        pair_count=20,
        run_config_file=run_config_path,
        run_config_file_sha256=run_config_sha256,
    )
    manifest_path = root / "instrumentation-manifest.json"
    manifest_sha256 = write_canonical_json(manifest_path, manifest)
    return (
        manifest,
        manifest_path,
        manifest_sha256,
        run_config,
        run_config_path,
        run_config_sha256,
    )


def _fake_spawn(row: dict[str, Any], *, run_config: dict[str, Any]) -> dict[str, Any]:
    raw = Path(row["state_file"]).read_bytes()
    callback = synthetic_instrumentation_entrypoint(
        row, raw, run_config["entrypoint_payload"]
    )
    runtime = {
        "observed_process_id": os.getpid(),
        "spawned_process_id": os.getpid(),
        "target_cpus": list(run_config["target_cpus"]),
        "spawn_method": "spawn",
        "fresh_process": True,
        "thread_env": dict(run_config["thread_env"]),
        "affinity_applied": False,
        "observed_affinity": None,
        "process_time_ns_start": 1,
        "process_time_ns_end": 2,
        "process_time_ns_delta": 1,
        "exitcode": 0,
    }
    return {
        "ok": True,
        "callback": callback,
        "state_bytes_sha256": hash_file(row["state_file"]),
        "runtime": runtime,
    }


def _execute_fake_panel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    off_ns: int,
    on_ns: int,
) -> tuple[dict[str, Any], Path, str, Path, dict[str, Any]]:
    manifest, manifest_path, manifest_sha256, run_config, _, _ = _study_files(
        tmp_path / "frozen", off_ns=off_ns, on_ns=on_ns
    )
    monkeypatch.setattr(
        "resource_envelope_study.instrumentation._spawn_case", _fake_spawn
    )
    acquisition = tmp_path / "acquisition"
    summary = execute_instrumentation_manifest(
        manifest_path,
        expected_manifest_sha256=manifest_sha256,
        output_dir=acquisition,
        limits=InstrumentationLimits(
            maximum_pairs=20,
            maximum_total_worker_seconds=40.0,
        ),
        execution_enabled=True,
        allow_test_mode=True,
    )
    return manifest, manifest_path, manifest_sha256, acquisition, summary


def _validate_schema(name: str, value: dict[str, Any]) -> None:
    schema = json.loads((SCHEMA_ROOT / name).read_text(encoding="utf-8"))
    validator = validator_for(schema)
    validator.check_schema(schema)
    validator(schema).validate(value)


def test_manifest_is_deterministic_balanced_and_schema_valid(tmp_path: Path) -> None:
    manifest, manifest_path, manifest_sha256, run_config, _, _ = _study_files(tmp_path)
    validate_instrumentation_manifest(manifest)
    rebuilt, *_ = _study_files(tmp_path)
    assert rebuilt == manifest
    assert manifest_sha256 == hash_file(manifest_path)
    assert len(manifest["pairs"]) == 20
    assert sum(
        pair["instrumentation_order"] == "off_then_on"
        for pair in manifest["pairs"]
    ) == 10
    assert {
        row["instrumentation_enabled"]
        for pair in manifest["pairs"]
        for row in pair["rows"]
    } == {False, True}
    counts = {
        agent: sum(pair["rows"][0]["agent_id"] == agent for pair in manifest["pairs"])
        for agent in manifest["config"]["agents"]
    }
    assert max(counts.values()) - min(counts.values()) <= 1
    _validate_schema("pokemon-instrumentation-manifest.schema.json", manifest)
    _validate_schema("pokemon-instrumentation-run-config.schema.json", run_config)


def test_manifest_rejects_changed_frozen_state_bytes(tmp_path: Path) -> None:
    manifest, *_ = _study_files(tmp_path)
    Path(manifest["config"]["frozen_states"][0]["state_file"]).write_bytes(b"tampered\n")
    with pytest.raises(InstrumentationError, match="state"):
        validate_instrumentation_manifest(manifest)


def test_real_spawn_is_fresh_and_consumes_exact_state(tmp_path: Path) -> None:
    manifest, _, manifest_sha256, run_config, _, run_config_sha256 = _study_files(
        tmp_path
    )
    row = manifest["pairs"][0]["rows"][0]
    message = _spawn_case(row, run_config=run_config)
    assert message["ok"] is True
    assert message["state_bytes_sha256"] == row["state_file_sha256"]
    assert message["runtime"]["fresh_process"] is True
    assert message["runtime"]["spawn_method"] == "spawn"
    assert message["runtime"]["observed_process_id"] != os.getpid()
    result = _normalize_result(
        row,
        message,
        manifest=manifest,
        manifest_file_sha256=manifest_sha256,
        run_config=run_config,
        run_config_file_sha256=run_config_sha256,
    )
    _validate_schema("pokemon-instrumentation-result.schema.json", result)


@pytest.mark.parametrize(
    ("on_ns", "expected"),
    [
        (1_000_000, "GO"),
        (1_081_081, "NARROW"),
        (1_250_000, "STOP"),
    ],
)
def test_outcome_blind_gate_applies_frozen_interval_bounds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    on_ns: int,
    expected: str,
) -> None:
    manifest, manifest_path, manifest_sha256, acquisition, summary = _execute_fake_panel(
        tmp_path,
        monkeypatch,
        off_ns=1_000_000,
        on_ns=on_ns,
    )
    report = evaluate_instrumentation_gate(
        manifest_path,
        expected_manifest_sha256=manifest_sha256,
        acquisition_dir=acquisition,
    )
    assert report["schema_version"] == GATE_REPORT_SCHEMA_VERSION
    assert report["decision"] == expected
    assert report["committed_pair_count"] == 20
    assert report["exact_semantic_equality"]["passed"] is True
    assert report["paired_interval_90"]["pair_count"] == 20
    assert summary["committed_pair_count"] == 20
    _validate_schema("pokemon-instrumentation-gate-report.schema.json", report)
    _validate_schema("pokemon-instrumentation-acquisition-summary.schema.json", summary)
    first_pair = manifest["pairs"][0]["pair_id"]
    commit = json.loads(
        (acquisition / "pair_commits" / f"{first_pair}.json").read_text(
            encoding="ascii"
        )
    )
    attempt = json.loads(
        (acquisition / "pair_attempts" / f"{first_pair}.json").read_text(
            encoding="ascii"
        )
    )
    _validate_schema("pokemon-instrumentation-pair-commit.schema.json", commit)
    _validate_schema("pokemon-instrumentation-attempt.schema.json", attempt)
    _validate_schema(
        "pokemon-instrumentation-resource-episode.schema.json",
        commit["resource_episode"],
    )
    for result in commit["case_results"]:
        _validate_schema("pokemon-instrumentation-result.schema.json", result)


def test_first_failure_preserves_partial_evidence_stops_and_refuses_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, manifest_path, manifest_sha256, run_config, _, _ = _study_files(
        tmp_path / "frozen"
    )
    calls: list[str] = []

    def fail_second(row: dict[str, Any], *, run_config: dict[str, Any]):
        calls.append(row["case_id"])
        if len(calls) == 2:
            raise InstrumentationWorkerError(
                "worker failed and was killed",
                {"spawned_process_id": 987, "stop_disposition": "killed"},
            )
        return _fake_spawn(row, run_config=run_config)

    monkeypatch.setattr(
        "resource_envelope_study.instrumentation._spawn_case", fail_second
    )
    acquisition = tmp_path / "acquisition"
    limits = InstrumentationLimits(
        maximum_pairs=20,
        maximum_total_worker_seconds=40.0,
    )
    with pytest.raises(InstrumentationError, match="stopped at invalid pair"):
        execute_instrumentation_manifest(
            manifest_path,
            expected_manifest_sha256=manifest_sha256,
            output_dir=acquisition,
            limits=limits,
            execution_enabled=True,
            allow_test_mode=True,
        )
    assert len(calls) == 2
    first_pair = manifest["pairs"][0]["pair_id"]
    attempt = json.loads(
        (acquisition / "pair_attempts" / f"{first_pair}.json").read_text(
            encoding="ascii"
        )
    )
    assert attempt["status"] == "invalid_stopped"
    assert len(attempt["attempted_results"]) == 1
    assert attempt["failed_worker"]["stop_disposition"] == "killed"
    assert not (acquisition / "pair_commits" / f"{first_pair}.json").exists()
    _validate_schema("pokemon-instrumentation-attempt.schema.json", attempt)

    with pytest.raises(InstrumentationError, match="partial instrumentation pair"):
        execute_instrumentation_manifest(
            manifest_path,
            expected_manifest_sha256=manifest_sha256,
            output_dir=acquisition,
            limits=limits,
            execution_enabled=True,
            resume=True,
            allow_test_mode=True,
        )
    assert len(calls) == 2
    report = evaluate_instrumentation_gate(
        manifest_path,
        expected_manifest_sha256=manifest_sha256,
        acquisition_dir=acquisition,
    )
    assert report["decision"] == "STOP"
    assert report["paired_interval_90"] is None
    assert report["invalid_or_interrupted_attempts"][0]["status"] == "invalid_stopped"


def test_semantic_mismatch_invalidates_atomic_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, manifest_path, manifest_sha256, _, _, _ = _study_files(
        tmp_path / "frozen"
    )

    def mismatching_spawn(row: dict[str, Any], *, run_config: dict[str, Any]):
        message = _fake_spawn(row, run_config=run_config)
        if row["instrumentation_enabled"]:
            decision = message["callback"]["decision_record"]
            decision["selected_action"] = [999]
        return message

    monkeypatch.setattr(
        "resource_envelope_study.instrumentation._spawn_case", mismatching_spawn
    )
    acquisition = tmp_path / "acquisition"
    with pytest.raises(InstrumentationError, match="semantic mismatch"):
        execute_instrumentation_manifest(
            manifest_path,
            expected_manifest_sha256=manifest_sha256,
            output_dir=acquisition,
            limits=InstrumentationLimits(20, 40.0),
            execution_enabled=True,
            allow_test_mode=True,
        )
    first_pair = manifest["pairs"][0]["pair_id"]
    assert not (acquisition / "pair_commits" / f"{first_pair}.json").exists()


def test_shared_hard_kill_primitive_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    process = object()
    observed: dict[str, Any] = {}

    def fake_stop(candidate, *, terminate_timeout_s: float, kill_timeout_s: float):
        observed.update(
            candidate=candidate,
            terminate_timeout_s=terminate_timeout_s,
            kill_timeout_s=kill_timeout_s,
        )
        return "killed"

    monkeypatch.setattr(
        "resource_envelope_study.instrumentation.stop_process", fake_stop
    )
    assert _stop_child(process, terminate_timeout_s=0.1, kill_timeout_s=0.2) == "killed"
    assert observed == {
        "candidate": process,
        "terminate_timeout_s": 0.1,
        "kill_timeout_s": 0.2,
    }


def test_student_t_critical_is_not_normal_approximation() -> None:
    assert _student_t_quantile(0.95, 19) == pytest.approx(1.7291328115, rel=1e-9)


def test_recomputed_hash_cannot_weaken_gate_specification(tmp_path: Path) -> None:
    manifest, *_ = _study_files(tmp_path)
    tampered = copy.deepcopy(manifest)
    tampered["config"]["gate_specification"]["go_bounds"] = [0.90, 1.10]
    tampered["content_hash"] = hash_json(
        {key: value for key, value in tampered.items() if key != "content_hash"}
    )
    with pytest.raises(InstrumentationError, match="criterion"):
        validate_instrumentation_manifest(tampered)


def test_recomputed_report_hash_cannot_change_gate_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, manifest_path, manifest_sha256, acquisition, _ = _execute_fake_panel(
        tmp_path,
        monkeypatch,
        off_ns=1_000_000,
        on_ns=1_000_000,
    )
    report = evaluate_instrumentation_gate(
        manifest_path,
        expected_manifest_sha256=manifest_sha256,
        acquisition_dir=acquisition,
    )
    report["decision"] = "STOP"
    report["report_hash"] = hash_json(
        {key: value for key, value in report.items() if key != "report_hash"}
    )
    with pytest.raises(InstrumentationError, match="decision does not reconcile"):
        validate_instrumentation_gate_report(report)
