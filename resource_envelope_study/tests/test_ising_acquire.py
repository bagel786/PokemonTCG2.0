from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

import pytest

from resource_envelope_study.canonical import canonical_json_bytes, hash_json
from resource_envelope_study.canonical import hash_file
from resource_envelope_study.ising_acquire import (
    IsingAcquisitionError,
    IsingAcquisitionLimits,
    IsingBatchFailure,
    _batch_commit,
    _periods,
    _validate_commit,
    _validate_run_authorization,
    acquire_ising_manifest,
)
from resource_envelope_study.ising_experiment import (
    IsingExperimentConfig,
    build_ising_manifest,
)
from resource_envelope_study.period_journal import (
    atomic_write_new,
    build_period_journal,
    period_journal_path,
)


def _manifest(*, phase: str = "smoke") -> dict:
    return build_ising_manifest(
        IsingExperimentConfig(
            master_seed=20260826101,
            phase=phase,
            lattice_size=2,
            burn_in_sweeps=0,
            wall_clock_budget_ns=1_000_000,
            fixed_sweeps=1,
            exact_reference_lattice_size=2,
        )
    )


def _available_cpu() -> int:
    if hasattr(os, "sched_getaffinity"):
        return min(os.sched_getaffinity(0))
    return 0


def _result(row: dict) -> dict:
    sweeps = int(row["requested_sweeps"] or 1)
    result = {
        "schema_version": "ising-case-result-1.0.0",
        "case_id": row["case_id"],
        "manifest_row_hash": hash_json(row),
        "chain_id": row["chain_id"],
        "chain_seed_hash": hash_json({"chain_seed": row["chain_seed"]}),
        "temperature_index": row["temperature_index"],
        "temperature": row["temperature"],
        "lattice_size": row["lattice_size"],
        "coupling_j": row["coupling_j"],
        "burn_in_sweeps": row["burn_in_sweeps"],
        "burn_in_in_measurement": False,
        "budget_mode": row["budget_mode"],
        "requested_budget_ns": row["requested_budget_ns"],
        "requested_sweeps": row["requested_sweeps"],
        "completed_sweeps": sweeps,
        "measurement_attempted_flips": sweeps * row["lattice_size"] ** 2,
        "accepted_flips_total": 0,
        "magnetization_per_spin": 0.0,
        "absolute_magnetization_per_spin": 0.0,
        "energy_per_spin": 0.0,
        "initial_state_hash": "1" * 64,
        "final_state_hash": "2" * 64,
        "load_condition": row["load_condition"],
        "load_batch_id": row["load_batch_id"],
        "load_seed": row["load_seed"],
        "load_period_order": row["load_period_order"],
        "resource_profile_contract_hash": hash_json(row["resource_profile_contract"]),
        "instrumentation_enabled": row["instrumentation_enabled"],
        "worker_pid": 123,
        "search_wall_ns": 1_000,
        "process_cpu_ns": 900,
        "overshoot_ns": 0,
        "cleanup_succeeded": True,
        "terminal_status": "ok",
        "error_type": "",
        "error_message": "",
        "decision_record": {},
        "schedule_row": dict(row),
    }
    result["artifact_sha256"] = hash_json(result)
    return result


def _episode(period_rows: list[dict]) -> dict:
    first = period_rows[0]
    metadata = {
        "schema_version": "resource-episode-1.0.0",
        "load_batch_id": first["load_batch_id"],
        "load_seed": first["load_seed"],
        "profile": {"condition": first["load_condition"]},
        "cleanup_succeeded": True,
    }
    return {
        **metadata,
        "period_case_ids": [row["case_id"] for row in period_rows],
        "metadata_hash": hash_json(metadata),
    }


def test_commit_reconciles_embedded_result_and_episode_hash_lists() -> None:
    manifest = _manifest()
    batch_id = manifest["rows"][0]["load_batch_id"]
    batch_rows = [row for row in manifest["rows"] if row["load_batch_id"] == batch_id]
    results = [_result(row) for row in batch_rows]
    episodes = [_episode(period) for period in _periods(batch_rows)]
    commit = _batch_commit(manifest, batch_id, batch_rows, results, episodes)
    _validate_commit(commit, manifest, batch_id, batch_rows, scientific=False)

    bad_results = copy.deepcopy(commit)
    bad_results["case_result_hashes"][0] = "f" * 64
    bad_results["content_hash"] = hash_json(
        {key: value for key, value in bad_results.items() if key != "content_hash"}
    )
    with pytest.raises(ValueError, match="result-hash list"):
        _validate_commit(bad_results, manifest, batch_id, batch_rows, scientific=False)

    bad_episodes = copy.deepcopy(commit)
    bad_episodes["resource_episode_hashes"][0] = "e" * 64
    bad_episodes["content_hash"] = hash_json(
        {key: value for key, value in bad_episodes.items() if key != "content_hash"}
    )
    with pytest.raises(ValueError, match="episode-hash list"):
        _validate_commit(bad_episodes, manifest, batch_id, batch_rows, scientific=False)


def test_first_invalid_batch_persists_all_partial_evidence_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest()
    first_batch = manifest["rows"][0]["load_batch_id"]
    partial_results = [{"period": "idle", "result": "retained"}]
    partial_episodes = [{"period": "idle", "episode": "retained"}]

    def fail_after_idle(*args, **kwargs):
        raise IsingBatchFailure(
            "loaded period failed",
            attempted_results=partial_results,
            attempted_episodes=partial_episodes,
            evidence_errors=["loaded co-runner lost CPU-time evidence"],
        )

    monkeypatch.setattr(
        "resource_envelope_study.ising_acquire._acquire_batch", fail_after_idle
    )
    with pytest.raises(IsingAcquisitionError, match="stopped at invalid paired batch"):
        acquire_ising_manifest(
            manifest,
            output_dir=tmp_path,
            target_cpus=(_available_cpu(),),
            limits=IsingAcquisitionLimits(maximum_batches=1),
        )
    invalid_path = tmp_path / "invalid_attempts" / f"{first_batch}.json"
    invalid = json.loads(invalid_path.read_text(encoding="utf-8"))
    assert invalid["attempted_results"] == partial_results
    assert invalid["attempted_resource_episodes"] == partial_episodes
    assert invalid["evidence_validation_errors"] == [
        "loaded co-runner lost CPU-time evidence"
    ]
    assert invalid["terminal_status"] == "invalid_stopped"
    assert not (tmp_path / "paired_batches" / f"{first_batch}.json").exists()


def test_completed_first_period_without_batch_commit_kills_resume(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    batch_id = manifest["rows"][0]["load_batch_id"]
    batch_rows = [row for row in manifest["rows"] if row["load_batch_id"] == batch_id]
    first_period = _periods(batch_rows)[0]
    results = [_result(row) for row in first_period]
    episode = _episode(first_period)
    journal = build_period_journal(
        experiment="ising",
        manifest_content_hash=manifest["content_hash"],
        phase="smoke",
        load_batch_id=batch_id,
        load_condition=first_period[0]["load_condition"],
        period_rows=first_period,
        case_results=results,
        resource_episode=episode,
    )
    atomic_write_new(
        period_journal_path(
            tmp_path, batch_id, str(first_period[0]["load_condition"])
        ),
        journal,
    )
    with pytest.raises(IsingAcquisitionError, match="no atomic batch commit"):
        acquire_ising_manifest(
            manifest,
            output_dir=tmp_path,
            target_cpus=(_available_cpu(),),
            limits=IsingAcquisitionLimits(maximum_batches=1),
        )


@pytest.mark.parametrize(
    "target_cpus",
    [
        (True,),
        (_available_cpu(), _available_cpu()),
        (os.cpu_count() if os.cpu_count() is not None else 10**9,),
    ],
)
def test_acquisition_rejects_boolean_duplicate_and_unavailable_cpus(
    tmp_path: Path, target_cpus: tuple
) -> None:
    with pytest.raises(ValueError, match="target_cpus"):
        acquire_ising_manifest(
            _manifest(),
            output_dir=tmp_path,
            target_cpus=target_cpus,
            limits=IsingAcquisitionLimits(maximum_batches=1),
        )


def test_scientific_acquisition_rejects_an_in_memory_manifest_without_file_hashes(
    tmp_path: Path,
) -> None:
    with pytest.raises(RuntimeError, match="canonical manifest"):
        acquire_ising_manifest(
            _manifest(phase="pilot"),
            output_dir=tmp_path,
            target_cpus=(_available_cpu(),),
        )


def test_scientific_acquisition_rejects_noncanonical_manifest_file(
    tmp_path: Path,
) -> None:
    manifest = _manifest(phase="pilot")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    authorization_path = tmp_path / "authorization.json"
    authorization_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="not canonical JSON"):
        acquire_ising_manifest(
            manifest,
            output_dir=tmp_path / "run",
            manifest_path=manifest_path,
            expected_manifest_sha256=hash_file(manifest_path),
            authorization_path=authorization_path,
            expected_authorization_sha256=hash_file(authorization_path),
            target_cpus=(_available_cpu(),),
        )


def test_final_ising_authorization_is_bound_to_study_wide_freeze(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _manifest(phase="final")
    repository_root = Path(__file__).resolve().parents[2]
    protocol_commit = "a" * 40
    head_commit = "b" * 40
    branch = "paper/resource-envelope-search-20260826"
    with tempfile.TemporaryDirectory(
        dir=Path(__file__).resolve().parent,
        prefix="ising-final-auth-",
    ) as directory:
        work = Path(directory)
        manifest_path = work / "manifest.json"
        manifest_path.write_bytes(canonical_json_bytes(manifest))
        manifest_sha256 = hash_file(manifest_path)
        authorization_path = work / "authorization.json"
        authorization_relative = authorization_path.relative_to(repository_root).as_posix()
        authorization = {
            "schema_version": "ising-run-authorization-1.0.0",
            "human_approved": True,
            "cloud_cost_authorized": True,
            "diagnostic_execution_authorized": True,
            "phase": "final",
            "manifest_content_hash": manifest["content_hash"],
            "manifest_sha256": manifest_sha256,
            "approval_id": "test-human-approval",
            "authorized_until_unix": time.time() + 600.0,
            "maximum_load_batches": manifest["config"]["load_batch_count"],
            "maximum_total_cases": len(manifest["rows"])
            + 2 * manifest["config"]["instrumentation_pair_count"],
            "maximum_worker_seconds_per_period": 10.0,
            "protocol_commit": protocol_commit,
            "branch": branch,
        }
        authorization_path.write_bytes(canonical_json_bytes(authorization))
        authorization_sha256 = hash_file(authorization_path)
        freeze = {
            "protocol_commit": protocol_commit,
            "branch": branch,
            "ising_manifest_sha256": manifest_sha256,
            "human_approval": {
                "approved": True,
                "phase": "final",
                "protocol_commit": protocol_commit,
                "approval_id": "test-human-approval",
                "attestation_path": authorization_relative,
                "attestation_sha256": authorization_sha256,
            },
        }

        def fake_git_text(_root: Path, *arguments: str) -> str:
            if arguments == ("branch", "--show-current"):
                return branch
            if arguments in {
                ("rev-parse", "HEAD"),
                ("rev-parse", "@{upstream}"),
            }:
                return head_commit
            if arguments == ("status", "--porcelain"):
                return ""
            if arguments[:2] == ("ls-files", "--error-unmatch"):
                return arguments[-1]
            if arguments[:2] == ("diff", "--name-only"):
                return "\n".join(
                    (
                        authorization_relative,
                        "resource_envelope_study/FREEZE_MANIFEST.json",
                    )
                )
            raise AssertionError(f"unexpected git arguments: {arguments}")

        def fake_run(arguments, **kwargs):
            del kwargs
            if arguments[1:3] == ["merge-base", "--is-ancestor"]:
                return subprocess.CompletedProcess(arguments, 0, stdout=b"", stderr=b"")
            if arguments[1] == "show":
                return subprocess.CompletedProcess(
                    arguments,
                    0,
                    stdout=canonical_json_bytes(manifest),
                    stderr=b"",
                )
            raise AssertionError(f"unexpected subprocess: {arguments}")

        monkeypatch.setattr(
            "resource_envelope_study.ising_acquire._git_text", fake_git_text
        )
        monkeypatch.setattr(
            "resource_envelope_study.ising_acquire.subprocess.run", fake_run
        )
        monkeypatch.setattr(
            "resource_envelope_study.ising_acquire.load_and_validate_freeze_manifest",
            lambda *args, **kwargs: dict(freeze),
        )
        assert _validate_run_authorization(
            manifest,
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha256,
            authorization_path=authorization_path,
            authorization_sha256=authorization_sha256,
            limits=IsingAcquisitionLimits(worker_timeout_seconds=10.0),
        ) == authorization_sha256

        freeze["ising_manifest_sha256"] = "0" * 64
        with pytest.raises(RuntimeError, match="study-wide freeze"):
            _validate_run_authorization(
                manifest,
                manifest_path=manifest_path,
                manifest_sha256=manifest_sha256,
                authorization_path=authorization_path,
                authorization_sha256=authorization_sha256,
                limits=IsingAcquisitionLimits(worker_timeout_seconds=10.0),
            )
