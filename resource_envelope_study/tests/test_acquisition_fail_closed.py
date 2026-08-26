from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from resource_envelope_study.acquire import (
    _assert_unit_scientifically_usable,
    _infrastructure_result,
    assert_scientific_resume_allowed,
    validate_batch_resume_state,
    validate_final_authorization,
    validate_schedule_for_acquisition,
    validate_terminal_accounting,
)
from resource_envelope_study.canonical import hash_json
from resource_envelope_study.canonical import canonical_json_bytes, hash_file
from resource_envelope_study.cli import _load_scientific_run_config, command_acquire
from resource_envelope_study.scheduler import ScheduleConfig, build_schedule


AGENTS = ("one_ply_value_v1", "flat_rollout_v1", "puct_tree_v1")


def _manifest() -> dict:
    return build_schedule(
        ScheduleConfig(
            phase="smoke",
            master_seed=411,
            agents=AGENTS,
            block_count=1,
            paired_load_batches=1,
            minimum_persistent_sessions=1,
            persistent_sequence_length=2,
            wall_clock_budget_ns=1_000,
            fixed_work_by_agent={agent: 1 for agent in AGENTS},
        )
    )


def test_schedule_and_embedded_terminal_rows_are_cryptographically_exact() -> None:
    manifest = _manifest()
    validate_schedule_for_acquisition(manifest)
    changed = deepcopy(manifest)
    changed["rows"][0]["agent_seed"] += 1
    with pytest.raises(ValueError, match="content hash mismatch"):
        validate_schedule_for_acquisition(changed)


def test_any_worker_infrastructure_result_invalidates_the_load_pair() -> None:
    row = _manifest()["rows"][0]
    with pytest.raises(RuntimeError, match="fatal scientific result"):
        _assert_unit_scientifically_usable([_infrastructure_result(row, "timeout")])


@pytest.mark.parametrize("status", ["engine_error", "protocol_invalid"])
def test_engine_or_protocol_failure_kills_the_load_pair(status: str) -> None:
    row = _manifest()["rows"][0]
    result = _infrastructure_result(row, "placeholder")
    result["game"]["terminal_status"] = status
    with pytest.raises(RuntimeError, match=rf"game:{status}"):
        _assert_unit_scientifically_usable([result])


def test_cleanup_failure_kills_the_load_pair() -> None:
    row = _manifest()["rows"][0]
    result = _infrastructure_result(row, "placeholder")
    result["game"]["terminal_status"] = "completed"
    result["decisions"] = [
        {"decision_index": 3, "terminal_status": "cleanup_error"}
    ]
    with pytest.raises(RuntimeError, match="decision:3:cleanup_error"):
        _assert_unit_scientifically_usable([result])


def test_terminal_accounting_recomputes_game_decision_totals() -> None:
    manifest = _manifest()
    row = manifest["rows"][0]
    result = _infrastructure_result(row, "accounted failure")
    result["game"]["completed_work_units"] = 1
    unhashed = dict(result)
    unhashed.pop("artifact_sha256")
    result["artifact_sha256"] = hash_json(unhashed)
    with pytest.raises(ValueError, match="game/decision totals differ"):
        validate_terminal_accounting(
            {**manifest, "rows": [row]}, [result], require_complete=True
        )


def test_terminal_accounting_rejects_nonarray_decision_payload() -> None:
    manifest = _manifest()
    row = manifest["rows"][0]
    result = _infrastructure_result(row, "accounted failure")
    result["decisions"] = {"not": "an array"}
    unhashed = dict(result)
    unhashed.pop("artifact_sha256")
    result["artifact_sha256"] = hash_json(unhashed)
    with pytest.raises(ValueError, match="decisions must be an array"):
        validate_terminal_accounting(
            {**manifest, "rows": [row]}, [result], require_complete=True
        )


def test_resume_rejects_a_partially_materialized_paired_load_batch() -> None:
    manifest = _manifest()
    one_result = [_infrastructure_result(manifest["rows"][0], "interrupted")]
    with pytest.raises(RuntimeError, match="partially materialized"):
        validate_batch_resume_state(manifest, one_result, [], [])


def test_complete_batch_requires_both_periods_and_a_matching_commit() -> None:
    manifest = _manifest()
    batch_id = manifest["rows"][0]["load_batch_id"]
    results = [_infrastructure_result(row, "terminally accounted") for row in manifest["rows"]]
    episodes = []
    for condition in ("idle", "loaded"):
        period_rows = [row for row in manifest["rows"] if row["load_condition"] == condition]
        metadata = {
            "load_batch_id": batch_id,
            "profile": {"condition": condition},
        }
        episodes.append(
            {
                **metadata,
                "period_case_ids": [row["case_id"] for row in period_rows],
                "metadata_hash": hash_json(metadata),
            }
        )
    commit = {
        "schema_version": "load-batch-commit-1.0.0",
        "load_batch_id": batch_id,
        "batch_status": "infrastructure_invalid",
        "case_ids": [row["case_id"] for row in manifest["rows"]],
        "result_hashes": [result["artifact_sha256"] for result in results],
        "episode_hashes": [episode["metadata_hash"] for episode in episodes],
    }
    commit["content_hash"] = hash_json(commit)
    assert validate_batch_resume_state(manifest, results, episodes, [commit]) == {batch_id}


def test_repository_placeholder_freeze_cannot_authorize_final(tmp_path: Path) -> None:
    schedule = tmp_path / "schedule.json"
    schedule.write_text("{}", encoding="utf-8")
    freeze = Path(__file__).resolve().parents[1] / "FREEZE_MANIFEST.json"
    with pytest.raises(RuntimeError, match="not FROZEN"):
        validate_final_authorization(
            {"config": {"phase": "final"}},
            schedule_path=schedule,
            freeze_manifest_path=freeze,
            actual_artifact_hashes={},
        )


def test_canonical_run_config_binds_paths_hashes_and_runtime(tmp_path: Path) -> None:
    artifact_names = (
        "engine_binary",
        "engine_source",
        "hero_deck",
        "hero_model",
        "opponent_deck",
        "opponent_model",
    )
    artifact_paths = {}
    for index, name in enumerate(artifact_names):
        artifact_paths[name] = tmp_path / f"{name}.bin"
        artifact_paths[name].write_bytes(f"artifact-{index}".encode("ascii"))
    algorithms = {
        "one_ply_value_v1": "one_ply_value",
        "flat_rollout_v1": "flat_rollout",
        "puct_tree_v1": "puct_tree",
    }
    adapters = {
        agent: {
            "agent_id": agent,
            "algorithm": algorithm,
            "hero_deck_path": artifact_paths["hero_deck"].name,
            "hero_model_path": artifact_paths["hero_model"].name,
            "opponent_deck_path": artifact_paths["opponent_deck"].name,
            "opponent_model_path": artifact_paths["opponent_model"].name,
            "seeded_engine_path": artifact_paths["engine_binary"].name,
            "rollout_depth": 16,
            "initialize_engine": False,
        }
        for agent, algorithm in algorithms.items()
    }
    value = {
        "schema_version": "acquisition-run-config-1.0.0",
        "artifacts": {
            name: {"path": path.name, "sha256": hash_file(path)}
            for name, path in artifact_paths.items()
        },
        "target_cpus": [0],
        "load_workers": 1,
        "max_decisions": 2_000,
        "worker_timeout_s": 3_600.0,
        "thread_env": {
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "PYTHONHASHSEED": "20260826",
            "VECLIB_MAXIMUM_THREADS": "1",
        },
        "platform_expectations": {"system": "Linux", "machine": "x86_64"},
        "adapter_configs": adapters,
    }
    config_path = tmp_path / "run-config.json"
    config_path.write_bytes(canonical_json_bytes(value))
    loaded, paths, hashes, configured = _load_scientific_run_config(
        config_path, set(AGENTS)
    )
    assert loaded == value
    assert paths["engine_binary"] == artifact_paths["engine_binary"]
    assert hashes["run_config"] == hash_file(config_path)
    assert set(configured) == set(AGENTS)

    artifact_paths["engine_binary"].write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash mismatch for engine_binary"):
        _load_scientific_run_config(config_path, set(AGENTS))


def test_local_smoke_override_is_rejected_for_scientific_phase(tmp_path: Path) -> None:
    manifest = build_schedule(
        ScheduleConfig(
            phase="pilot",
            master_seed=412,
            agents=AGENTS,
            block_count=80,
            paired_load_batches=20,
            minimum_persistent_sessions=20,
            persistent_sequence_length=8,
            wall_clock_budget_ns=1_000,
            fixed_work_by_agent={agent: 1 for agent in AGENTS},
            artifact_hashes={
                "engine_binary": "0" * 64,
                "engine_source": "1" * 64,
                "hero_deck": "2" * 64,
                "hero_model": "3" * 64,
                "opponent_deck": "4" * 64,
                "opponent_model": "5" * 64,
                "run_config": "6" * 64,
            },
        )
    )
    schedule = tmp_path / "pilot.json"
    schedule.write_bytes(canonical_json_bytes(manifest))
    with pytest.raises(ValueError, match="forbidden for scientific phases"):
        command_acquire(
            SimpleNamespace(schedule=str(schedule), allow_local_smoke=True)
        )


def test_scientific_resume_stays_killed_after_an_invalid_batch() -> None:
    pilot = {"config": {"phase": "pilot"}}
    invalid_commit = {
        "load_batch_id": "pilot-load-pair-007",
        "batch_status": "infrastructure_invalid",
    }
    with pytest.raises(RuntimeError, match="new frozen reserve IDs"):
        assert_scientific_resume_allowed(pilot, [invalid_commit])
    # Smoke remains a diagnostic mode and may continue to expose more defects.
    assert_scientific_resume_allowed(
        {"config": {"phase": "smoke"}}, [invalid_commit]
    )
