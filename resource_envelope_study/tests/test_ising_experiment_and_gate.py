from __future__ import annotations

import copy
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import pytest

from resource_envelope_study.adapters.ising import ISING_TC, exact_expectations
from resource_envelope_study.canonical import canonical_json_bytes, hash_json
from resource_envelope_study.ising_experiment import (
    ISING_REPLAY_SCHEMA_VERSION,
    ISING_TEMPERATURES,
    IsingExperimentConfig,
    build_ising_manifest,
    build_resource_profile_request,
    execute_ising_case,
    execute_with_resource_profile,
    fixed_work_replay_fingerprint,
    run_clean_process_replay,
    validate_ising_manifest,
)
from resource_envelope_study.ising_gate import (
    ISING_DIAGNOSTIC_SCHEMA_VERSION,
    evaluate_ising_gate,
)


def _config() -> IsingExperimentConfig:
    return IsingExperimentConfig(
        master_seed=20260826077,
        phase="pilot",
        lattice_size=4,
        burn_in_sweeps=2,
        wall_clock_budget_ns=5_000_000,
        fixed_sweeps=5,
        load_batch_count=20,
        chains_per_temperature_batch=1,
        exact_reference_lattice_size=2,
    )


def test_manifest_is_byte_deterministic_exact_temperature_and_ab_ba_balanced() -> None:
    first = build_ising_manifest(_config())
    second = build_ising_manifest(_config())
    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert tuple(first["config"]["temperatures"]) == (1.5, ISING_TC, 3.5)
    assert tuple(first["config"]["temperatures"]) == ISING_TEMPERATURES
    assert len(first["rows"]) == 20 * 3 * 4

    order_by_batch: dict[str, str] = {}
    rows_by_chain: dict[str, list[dict]] = defaultdict(list)
    seed_by_chain: dict[str, int] = {}
    for row in first["rows"]:
        order_by_batch.setdefault(row["load_batch_id"], row["load_period_order"])
        assert order_by_batch[row["load_batch_id"]] == row["load_period_order"]
        rows_by_chain[row["chain_id"]].append(row)
        seed_by_chain.setdefault(row["chain_id"], row["chain_seed"])
        assert seed_by_chain[row["chain_id"]] == row["chain_seed"]
        assert row["burn_in_in_measurement"] is False
        assert row["work_unit"] == "one_random_scan_sweep_L_squared_attempts"
    assert Counter(order_by_batch.values()) == {
        "idle_then_loaded": 10,
        "loaded_then_idle": 10,
    }
    assert len(set(seed_by_chain.values())) == len(seed_by_chain)
    assert all(len(rows) == 4 for rows in rows_by_chain.values())

    corrupted = copy.deepcopy(first)
    corrupted["rows"][0]["temperature"] = 2.9
    with pytest.raises(ValueError, match="content hash"):
        validate_ising_manifest(corrupted)


def test_fixed_sweeps_are_exact_burn_in_is_outside_budget_and_observables_normalized() -> None:
    manifest = build_ising_manifest(_config())
    row = next(row for row in manifest["rows"] if row["budget_mode"] == "fixed_sweeps")
    result = execute_ising_case(row)
    assert result["terminal_status"] == "ok"
    assert result["completed_sweeps"] == row["requested_sweeps"] == 5
    assert result["measurement_attempted_flips"] == 5 * 4 * 4
    assert result["decision_record"]["completed_sweeps"] == 5
    assert result["decision_record"]["forward_model_calls"] == 5 * 4 * 4
    assert result["burn_in_sweeps"] == 2
    assert result["burn_in_in_measurement"] is False
    assert -1.0 <= result["magnetization_per_spin"] <= 1.0
    assert result["absolute_magnetization_per_spin"] == abs(
        result["magnetization_per_spin"]
    )
    assert -2.0 <= result["energy_per_spin"] <= 2.0


def test_fixed_sweep_control_flow_is_invariant_to_adversarial_telemetry_clocks() -> None:
    manifest = build_ising_manifest(_config())
    row = next(row for row in manifest["rows"] if row["budget_mode"] == "fixed_sweeps")

    class Clock:
        def __init__(self, increments: list[int]):
            self.value = 0
            self.increments = increments
            self.index = 0

        def __call__(self) -> int:
            self.value += self.increments[self.index % len(self.increments)]
            self.index += 1
            return self.value

    first = execute_ising_case(
        row,
        monotonic_ns=Clock([1, 1, 1]),
        process_time_ns=Clock([2, 2]),
    )
    second = execute_ising_case(
        row,
        monotonic_ns=Clock([10_000_000, 7, 99_999]),
        process_time_ns=Clock([1_000_000, 3]),
    )
    assert first["completed_sweeps"] == second["completed_sweeps"] == 5
    assert fixed_work_replay_fingerprint(first) == fixed_work_replay_fingerprint(second)


def test_resource_profile_execution_is_an_external_spawn_safe_hook() -> None:
    manifest = build_ising_manifest(_config())
    row = next(row for row in manifest["rows"] if row["budget_mode"] == "fixed_sweeps")
    request = build_resource_profile_request(row)
    assert request["profile"] == row["resource_profile_contract"]
    assert request["entrypoint"].endswith(":execute_ising_case")

    observed: list[dict] = []

    def fake_existing_controller(payload: dict) -> dict:
        observed.append(payload)
        return execute_ising_case(payload["payload"])

    result = execute_with_resource_profile(row, fake_existing_controller)
    assert result["completed_sweeps"] == 5
    assert observed == [request]


def test_fixed_work_replays_in_two_clean_interpreters() -> None:
    manifest = build_ising_manifest(_config())
    row = next(row for row in manifest["rows"] if row["budget_mode"] == "fixed_sweeps")
    report = run_clean_process_replay(row, repeats=2)
    assert report["schema_version"] == ISING_REPLAY_SCHEMA_VERSION
    assert report["passed"] is True
    assert report["python_hash_seeds"] == [1, 2]
    assert len(set(report["scientific_fingerprints"])) == 1
    # Raw rows retain clocks/PIDs, so the scientific fingerprint is the replay contract.
    assert len(report["raw_output_hashes"]) == 2


def _synthetic_case_results(manifest: dict, *, loaded_wall_sweeps: int = 70) -> list[dict]:
    results: list[dict] = []
    for row in manifest["rows"]:
        if row["budget_mode"] == "fixed_sweeps":
            sweeps = int(row["requested_sweeps"])
        else:
            sweeps = 100 if row["load_condition"] == "idle" else loaded_wall_sweeps
        magnetization = 0.25
        energy = -1.0
        scientific_state = {
            "chain_id": row["chain_id"],
            "budget_mode": row["budget_mode"],
            "sweeps": sweeps,
        }
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
            "accepted_flips_total": sweeps,
            "magnetization_per_spin": magnetization,
            "absolute_magnetization_per_spin": abs(magnetization),
            "energy_per_spin": energy,
            "initial_state_hash": hash_json({"initial": row["chain_id"]}),
            "final_state_hash": hash_json(scientific_state),
            "load_condition": row["load_condition"],
            "load_batch_id": row["load_batch_id"],
            "load_seed": row["load_seed"],
            "load_period_order": row["load_period_order"],
            "resource_profile_contract_hash": hash_json(row["resource_profile_contract"]),
            "instrumentation_enabled": True,
            "worker_pid": 1000,
            "search_wall_ns": 1_000_000,
            "process_cpu_ns": 900_000,
            "overshoot_ns": 10_000 if row["budget_mode"] == "wall_clock" else 0,
            "cleanup_succeeded": True,
            "terminal_status": "ok",
            "error_type": "",
            "error_message": "",
            "decision_record": {},
        }
        result["artifact_sha256"] = hash_json(result)
        results.append(result)
    return results


def _synthetic_diagnostics(manifest: dict) -> list[dict]:
    records: list[dict] = []
    for plan in manifest["design"]["diagnostic_plan"]["panels"]:
        exact = (
            exact_expectations(plan["lattice_size"], plan["temperature"], plan["coupling_j"])
            if plan["panel_kind"] == "exact_reference"
            else None
        )
        for observable, exact_key in (
            ("absolute_magnetization_per_spin", "mean_absolute_magnetization"),
            ("energy_per_spin", "mean_energy_per_spin"),
        ):
            reference = exact[exact_key] if exact is not None else None
            sample_mean = reference if reference is not None else (
                0.5 if observable == "absolute_magnetization_per_spin" else -1.0
            )
            record = {
                "schema_version": ISING_DIAGNOSTIC_SCHEMA_VERSION,
                "panel_kind": plan["panel_kind"],
                "lattice_size": plan["lattice_size"],
                "temperature": plan["temperature"],
                "coupling_j": plan["coupling_j"],
                "burn_in_sweeps": plan["burn_in_sweeps"],
                "observable": observable,
                "chain_count": len(plan["chain_seeds"]),
                "draws_per_chain": plan["draws_per_chain"],
                "seed_set_hash": plan["seed_set_hash"],
                "diagnostic_plan_row_hash": plan["plan_row_hash"],
                "sample_mean": sample_mean,
                "sample_standard_deviation": 0.1,
                "split_r_hat": 1.001,
                "effective_sample_size": 500.0,
                "mcse": 0.005,
                "exact_reference": reference,
                "reference_absolute_error": 0.0 if reference is not None else None,
            }
            record["record_hash"] = hash_json(record)
            records.append(record)
    return records


def _instrumentation_rows(manifest: dict) -> list[dict]:
    rows: list[dict] = []
    for plan in manifest["design"]["instrumentation_plan"]["pairs"]:
        fingerprint = hash_json({"pair": plan["pair_id"], "fixed_state": True})
        order = [False, True] if plan["execution_order"] == "off_then_on" else [True, False]
        for position, enabled in enumerate(order):
            row = {
                "schema_version": "ising-instrumentation-result-1.0.0",
                "pair_id": plan["pair_id"],
                "pair_plan_hash": plan["plan_row_hash"],
                "case_id": f"instrumentation-case-{plan['pair_id']}-{position}",
                "execution_position": position,
                "instrumentation_enabled": enabled,
                "budget_mode": "fixed_sweeps",
                "requested_sweeps": plan["requested_sweeps"],
                "completed_sweeps": plan["requested_sweeps"],
                "temperature_index": plan["temperature_index"],
                "temperature": plan["temperature"],
                "lattice_size": plan["lattice_size"],
                "coupling_j": plan["coupling_j"],
                "burn_in_sweeps": plan["burn_in_sweeps"],
                "chain_seed_hash": hash_json({"chain_seed": plan["chain_seed"]}),
                "search_wall_ns": 1_020_000_000 if enabled else 1_000_000_000,
                "scientific_fingerprint": fingerprint,
                "source_result_artifact_sha256": hash_json(
                    {"pair": plan["pair_id"], "position": position}
                ),
            }
            row["record_hash"] = hash_json(row)
            rows.append(row)
    return rows


def _resource_profile_validation(manifest: dict, results: list[dict]) -> dict:
    instrumentation = _instrumentation_rows(manifest)
    report = {
        "schema_version": "ising-resource-profile-validation-1.0.0",
        "manifest_content_hash": manifest["content_hash"],
        "scientific_validation": True,
        "passed": True,
        "validated_load_batch_count": 20,
        "validated_resource_episode_count": 40,
        "validated_case_result_count": len(results),
        "batch_commit_hashes": [f"{index:064x}" for index in range(101, 121)],
        "case_result_hashes": [row["artifact_sha256"] for row in results],
        "resource_episode_hashes": [f"{index:064x}" for index in range(1, 41)],
        "validated_instrumentation_pair_count": 20,
        "instrumentation_pair_commit_hashes": [
            f"{index:064x}" for index in range(201, 221)
        ],
        "instrumentation_result_hashes": [
            row["source_result_artifact_sha256"] for row in instrumentation
        ],
        "instrumentation_resource_episode_hashes": [
            f"{index:064x}" for index in range(301, 321)
        ],
        "validator_contract": (
            "resource_envelope_study.acquire._validate_episode+"
            "_validate_scientific_episode"
        ),
    }
    report["report_hash"] = hash_json(report)
    return report


def _sealed_replay(value: dict) -> dict:
    result = dict(value)
    result["python_hash_seeds"] = [1, 2]
    result["report_hash"] = hash_json(result)
    return result


def test_gate_returns_only_aps_go_when_every_frozen_requirement_passes() -> None:
    manifest = build_ising_manifest(_config())
    results = _synthetic_case_results(manifest)
    designated = manifest["design"]["clean_process_replay"]
    one_fixed = next(row for row in results if row["case_id"] == designated["case_id"])
    replay_fingerprint = fixed_work_replay_fingerprint(one_fixed)
    replay = _sealed_replay({
        "schema_version": ISING_REPLAY_SCHEMA_VERSION,
        "case_id": designated["case_id"],
        "manifest_row_hash": designated["manifest_row_hash"],
        "repeats": 2,
        "scientific_fingerprints": [replay_fingerprint, replay_fingerprint],
        "passed": True,
    })
    report = evaluate_ising_gate(
        manifest,
        results,
        _synthetic_diagnostics(manifest),
        replay,
        _instrumentation_rows(manifest),
        _resource_profile_validation(manifest, results),
    )
    assert report["decision"] == "APS_GO"
    assert all(check["passed"] for check in report["checks"])
    assert report["pokemon_scope_effect"] == "none"
    assert report["pokemon_rescue_allowed"] is False
    assert report["reasons"] == ["all frozen Ising companion gates passed"]


def test_gate_fails_closed_on_weak_load_and_can_never_rescue_pokemon() -> None:
    manifest = build_ising_manifest(_config())
    results = _synthetic_case_results(manifest, loaded_wall_sweeps=90)
    designated = manifest["design"]["clean_process_replay"]
    one_fixed = next(row for row in results if row["case_id"] == designated["case_id"])
    fingerprint = fixed_work_replay_fingerprint(one_fixed)
    report = evaluate_ising_gate(
        manifest,
        results,
        _synthetic_diagnostics(manifest),
        _sealed_replay({
            "schema_version": ISING_REPLAY_SCHEMA_VERSION,
            "case_id": designated["case_id"],
            "manifest_row_hash": designated["manifest_row_hash"],
            "repeats": 2,
            "scientific_fingerprints": [fingerprint, fingerprint],
            "passed": True,
        }),
        _instrumentation_rows(manifest),
        _resource_profile_validation(manifest, results),
    )
    assert report["decision"] == "APS_NO_GO"
    assert any("20%" in reason for reason in report["reasons"])
    assert report["pokemon_scope_effect"] == "none"
    assert report["pokemon_rescue_allowed"] is False


def test_gate_cannot_go_without_validated_resource_manipulation_evidence() -> None:
    manifest = build_ising_manifest(_config())
    results = _synthetic_case_results(manifest)
    designated = manifest["design"]["clean_process_replay"]
    fixed = next(row for row in results if row["case_id"] == designated["case_id"])
    fingerprint = fixed_work_replay_fingerprint(fixed)
    report = evaluate_ising_gate(
        manifest,
        results,
        _synthetic_diagnostics(manifest),
        _sealed_replay({
            "schema_version": ISING_REPLAY_SCHEMA_VERSION,
            "case_id": designated["case_id"],
            "manifest_row_hash": designated["manifest_row_hash"],
            "repeats": 2,
            "scientific_fingerprints": [fingerprint, fingerprint],
            "passed": True,
        }),
        _instrumentation_rows(manifest),
    )
    assert report["decision"] == "APS_NO_GO"
    resource_check = next(
        check for check in report["checks"] if check["name"] == "resource_profile_manipulation"
    )
    assert resource_check["passed"] is False


def test_gate_binds_resource_validation_to_exact_acquired_result_hashes() -> None:
    manifest = build_ising_manifest(_config())
    results = _synthetic_case_results(manifest)
    resource = _resource_profile_validation(manifest, results)
    resource["case_result_hashes"][0] = "f" * 64
    resource["report_hash"] = hash_json(
        {key: value for key, value in resource.items() if key != "report_hash"}
    )
    report = evaluate_ising_gate(
        manifest,
        results,
        _synthetic_diagnostics(manifest),
        _valid_replay(manifest, results),
        _instrumentation_rows(manifest),
        resource,
    )
    resource_check = next(
        check for check in report["checks"] if check["name"] == "resource_profile_manipulation"
    )
    assert report["decision"] == "APS_NO_GO"
    assert resource_check["passed"] is False
    assert resource_check["evidence"]["case_result_hash_sets_match"] is False


def _valid_replay(manifest: dict, results: list[dict]) -> dict:
    designated = manifest["design"]["clean_process_replay"]
    fixed = next(row for row in results if row["case_id"] == designated["case_id"])
    fingerprint = fixed_work_replay_fingerprint(fixed)
    return _sealed_replay({
        "schema_version": ISING_REPLAY_SCHEMA_VERSION,
        "case_id": designated["case_id"],
        "manifest_row_hash": designated["manifest_row_hash"],
        "repeats": 2,
        "scientific_fingerprints": [fingerprint, fingerprint],
        "passed": True,
    })


def test_gate_rejects_self_consistent_result_swapped_to_another_manifest_row() -> None:
    manifest = build_ising_manifest(_config())
    results = _synthetic_case_results(manifest)
    fixed_rows = [row for row in results if row["budget_mode"] == "fixed_sweeps"]
    target, donor = fixed_rows[2], fixed_rows[3]
    original_case_id = target["case_id"]
    for field in (
        "manifest_row_hash",
        "chain_id",
        "chain_seed_hash",
        "temperature_index",
        "temperature",
        "lattice_size",
        "coupling_j",
        "burn_in_sweeps",
        "budget_mode",
        "requested_budget_ns",
        "requested_sweeps",
        "completed_sweeps",
        "measurement_attempted_flips",
        "load_condition",
        "load_batch_id",
        "load_seed",
        "load_period_order",
        "resource_profile_contract_hash",
        "instrumentation_enabled",
    ):
        target[field] = donor[field]
    target["case_id"] = original_case_id
    report = evaluate_ising_gate(
        manifest,
        results,
        _synthetic_diagnostics(manifest),
        _valid_replay(manifest, results),
        _instrumentation_rows(manifest),
        _resource_profile_validation(manifest, results),
    )
    assert report["decision"] == "APS_NO_GO"
    binding = next(
        check
        for check in report["checks"]
        if check["name"] == "case_schema_and_observable_bounds"
    )
    assert binding["passed"] is False
    assert "exact manifest row" in binding["evidence"]["validation_errors"][0]["error"]


def test_gate_binds_replay_to_designated_acquired_fingerprint() -> None:
    manifest = build_ising_manifest(_config())
    results = _synthetic_case_results(manifest)
    designated = manifest["design"]["clean_process_replay"]
    other = next(
        row
        for row in results
        if row["budget_mode"] == "fixed_sweeps" and row["case_id"] != designated["case_id"]
    )
    wrong = fixed_work_replay_fingerprint(other)
    replay = _sealed_replay({
        "schema_version": ISING_REPLAY_SCHEMA_VERSION,
        "case_id": designated["case_id"],
        "manifest_row_hash": designated["manifest_row_hash"],
        "repeats": 2,
        "scientific_fingerprints": [wrong, wrong],
        "passed": True,
    })
    report = evaluate_ising_gate(
        manifest,
        results,
        _synthetic_diagnostics(manifest),
        replay,
        _instrumentation_rows(manifest),
        _resource_profile_validation(manifest, results),
    )
    replay_check = next(
        check for check in report["checks"] if check["name"] == "clean_process_replay"
    )
    assert report["decision"] == "APS_NO_GO"
    assert replay_check["passed"] is False
    assert replay_check["evidence"]["matches_acquired_fingerprint"] is False


def test_gate_uses_maximum_instrumentation_effect_and_frozen_diagnostic_seeds() -> None:
    manifest = build_ising_manifest(_config())
    results = _synthetic_case_results(manifest)
    instrumentation = _instrumentation_rows(manifest)
    # One outlying pair exceeds 5%; a median-only rule would incorrectly pass.
    first_on = next(row for row in instrumentation if row["instrumentation_enabled"])
    first_on["search_wall_ns"] = 1_250_000_000
    first_on["record_hash"] = hash_json(
        {key: value for key, value in first_on.items() if key != "record_hash"}
    )
    diagnostics = _synthetic_diagnostics(manifest)
    diagnostics[0]["seed_set_hash"] = "f" * 64
    diagnostics[0]["record_hash"] = hash_json(
        {key: value for key, value in diagnostics[0].items() if key != "record_hash"}
    )
    report = evaluate_ising_gate(
        manifest,
        results,
        diagnostics,
        _valid_replay(manifest, results),
        instrumentation,
        _resource_profile_validation(manifest, results),
    )
    instrumentation_check = next(
        check
        for check in report["checks"]
        if check["name"] == "instrumentation_throughput"
    )
    diagnostic_check = next(
        check
        for check in report["checks"]
        if check["name"] == "convergence_and_exact_reference"
    )
    assert report["decision"] == "APS_NO_GO"
    assert instrumentation_check["passed"] is False
    assert instrumentation_check["evidence"][
        "maximum_absolute_relative_throughput_effect"
    ] > 0.05
    assert diagnostic_check["passed"] is False
    assert "frozen_diagnostic_assignment" in diagnostic_check["evidence"]["row_failures"][0][
        "failures"
    ]


def test_ising_json_schemas_are_present_and_parseable() -> None:
    schema_dir = Path(__file__).resolve().parents[1] / "schemas" / "v1"
    required_names = {
        "ising-experiment-manifest.schema.json",
        "ising-case-result.schema.json",
        "ising-chain-diagnostic.schema.json",
        "ising-gate-report.schema.json",
        "ising-clean-process-replay.schema.json",
        "ising-instrumentation-result.schema.json",
        "ising-resource-profile-validation.schema.json",
        "ising-run-authorization.schema.json",
        "ising-paired-batch-commit.schema.json",
    }
    observed_names = {path.name for path in schema_dir.glob("ising-*.schema.json")}
    assert required_names <= observed_names
    for path in schema_dir.glob("ising-*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["type"] == "object"
