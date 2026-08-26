"""Fail-closed APS scope gate for the open Ising companion experiment.

An ``APS_GO`` result means only that the Ising companion met its frozen
correctness and resource-intervention gates.  This evaluator has no input or
output capable of changing, rescuing, or promoting the Pokemon experiment.
"""

from __future__ import annotations

import math
import statistics
import time
from collections import defaultdict
from typing import Any, Mapping, Sequence

import numpy as np
from training.azure_guard import is_azure_host

from .adapters.ising import (
    ISING_TC,
    IsingConfig,
    effective_sample_size,
    exact_expectations,
    sample_independent_chains,
    split_r_hat,
)
from .canonical import hash_json
from .ising_experiment import (
    ISING_REPLAY_SCHEMA_VERSION,
    ISING_TEMPERATURES,
    IsingGateThresholds,
    fixed_work_replay_fingerprint,
    validate_ising_case_result,
    validate_ising_case_result_against_row,
    validate_ising_manifest,
)


ISING_DIAGNOSTIC_SCHEMA_VERSION = "ising-chain-diagnostic-1.0.0"
ISING_GATE_SCHEMA_VERSION = "ising-aps-gate-1.0.0"
ISING_RESOURCE_VALIDATION_SCHEMA_VERSION = "ising-resource-profile-validation-1.0.0"
OBSERVABLES = ("absolute_magnetization_per_spin", "energy_per_spin")


def _artifact_without_hash(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: item
        for key, item in value.items()
        if key not in {"artifact_sha256", "content_hash", "report_hash"}
    }


def _mcse(values: np.ndarray, ess: float) -> float:
    flattened = np.asarray(values, dtype=np.float64).reshape(-1)
    if flattened.size < 2 or ess <= 0:
        raise ValueError("MCSE requires at least two values and positive ESS")
    return float(np.std(flattened, ddof=1)) / math.sqrt(float(ess))


def summarize_chain_diagnostics(
    config: IsingConfig,
    seeds: Sequence[int],
    measured_sweeps: int,
    *,
    panel_kind: str,
    diagnostic_plan_row_hash: str | None = None,
) -> list[dict[str, Any]]:
    """Run independent chains and summarize existing R-hat/ESS diagnostics.

    ``exact_reference`` is restricted to an enumerable ``L<=4`` torus.  The
    main-lattice convergence panel uses the same code but has no claimed exact
    finite-size reference.
    """

    if panel_kind not in {"main_convergence", "exact_reference"}:
        raise ValueError("panel_kind must be main_convergence or exact_reference")
    if panel_kind == "exact_reference" and config.lattice_size > 4:
        raise ValueError("exact-reference diagnostics require L<=4")
    if len(set(map(int, seeds))) != len(seeds):
        raise ValueError("diagnostic chains require distinct seeds")
    samples = sample_independent_chains(config, list(map(int, seeds)), measured_sweeps)
    exact = (
        exact_expectations(
            config.lattice_size, config.temperature, config.coupling_j
        )
        if panel_kind == "exact_reference"
        else None
    )
    sample_by_name = {
        "absolute_magnetization_per_spin": samples["absolute_magnetization"],
        "energy_per_spin": samples["energy_per_spin"],
    }
    exact_key = {
        "absolute_magnetization_per_spin": "mean_absolute_magnetization",
        "energy_per_spin": "mean_energy_per_spin",
    }
    records: list[dict[str, Any]] = []
    for observable, values in sample_by_name.items():
        ess = effective_sample_size(values)
        reference_value = float(exact[exact_key[observable]]) if exact is not None else None
        sample_mean = float(np.mean(values))
        record = {
            "schema_version": ISING_DIAGNOSTIC_SCHEMA_VERSION,
            "panel_kind": panel_kind,
            "lattice_size": config.lattice_size,
            "temperature": config.temperature,
            "coupling_j": config.coupling_j,
            "burn_in_sweeps": config.burn_in_sweeps,
            "observable": observable,
            "chain_count": len(seeds),
            "draws_per_chain": measured_sweeps,
            "seed_set_hash": hash_json({"seeds": list(map(int, seeds))}),
            "diagnostic_plan_row_hash": diagnostic_plan_row_hash,
            "sample_mean": sample_mean,
            "sample_standard_deviation": float(np.std(values, ddof=1)),
            "split_r_hat": split_r_hat(values),
            "effective_sample_size": ess,
            "mcse": _mcse(values, ess),
            "exact_reference": reference_value,
            "reference_absolute_error": (
                abs(sample_mean - reference_value)
                if reference_value is not None
                else None
            ),
        }
        record["record_hash"] = hash_json(record)
        records.append(record)
    return records


def run_frozen_diagnostic_plan(
    manifest: Mapping[str, Any],
    *,
    authorization: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Execute the manifest-bound diagnostic matrix on an authorized host."""

    validate_ising_manifest(manifest)
    if manifest["config"]["phase"] in {"pilot", "final"}:
        approval = dict(authorization or {})
        if not is_azure_host():
            raise RuntimeError("scientific Ising diagnostics are Azure-only")
        if (
            approval.get("schema_version") != "ising-run-authorization-1.0.0"
            or approval.get("human_approved") is not True
            or approval.get("cloud_cost_authorized") is not True
            or approval.get("diagnostic_execution_authorized") is not True
            or approval.get("phase") != manifest["config"]["phase"]
            or approval.get("manifest_content_hash") != manifest["content_hash"]
            or float(approval.get("authorized_until_unix", 0.0)) <= time.time()
        ):
            raise RuntimeError(
                "scientific Ising diagnostics require the matching non-expired human authorization"
            )
    records: list[dict[str, Any]] = []
    for plan in manifest["design"]["diagnostic_plan"]["panels"]:
        config = IsingConfig(
            lattice_size=int(plan["lattice_size"]),
            temperature=float(plan["temperature"]),
            coupling_j=float(plan["coupling_j"]),
            burn_in_sweeps=int(plan["burn_in_sweeps"]),
        )
        records.extend(
            summarize_chain_diagnostics(
                config,
                list(map(int, plan["chain_seeds"])),
                int(plan["draws_per_chain"]),
                panel_kind=str(plan["panel_kind"]),
                diagnostic_plan_row_hash=str(plan["plan_row_hash"]),
            )
        )
    return records


def _instrumentation_summary(
    rows: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
    threshold: IsingGateThresholds,
) -> tuple[bool, dict[str, Any], str]:
    planned_rows = manifest["design"]["instrumentation_plan"]["pairs"]
    planned = {str(row["pair_id"]): row for row in planned_rows}
    by_pair: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_pair[str(row.get("pair_id", ""))].append(row)
    effects: list[float] = []
    invalid: list[str] = []
    for pair_id, pair_rows in sorted(by_pair.items()):
        plan = planned.get(pair_id)
        if not pair_id or plan is None or len(pair_rows) != 2:
            invalid.append(pair_id or "<missing>")
            continue
        by_mode = {bool(row.get("instrumentation_enabled")): row for row in pair_rows}
        if set(by_mode) != {False, True}:
            invalid.append(pair_id)
            continue
        off = by_mode[False]
        on = by_mode[True]
        try:
            expected_order = [False, True] if plan["execution_order"] == "off_then_on" else [True, False]
            observed_order = [
                bool(row["instrumentation_enabled"])
                for row in sorted(pair_rows, key=lambda item: int(item["execution_position"]))
            ]
            if observed_order != expected_order:
                raise ValueError
            for row in pair_rows:
                unhashed_row = {
                    key: value for key, value in row.items() if key != "record_hash"
                }
                if (
                    row.get("schema_version") != "ising-instrumentation-result-1.0.0"
                    or row.get("record_hash") != hash_json(unhashed_row)
                    or row.get("pair_plan_hash") != plan["plan_row_hash"]
                    or row.get("budget_mode") != "fixed_sweeps"
                    or int(row.get("requested_sweeps", 0)) != int(plan["requested_sweeps"])
                    or int(row.get("temperature_index", -1)) != int(plan["temperature_index"])
                    or float(row.get("temperature", math.nan)).hex()
                    != float(plan["temperature"]).hex()
                    or int(row.get("lattice_size", 0)) != int(plan["lattice_size"])
                    or float(row.get("coupling_j", math.nan)).hex()
                    != float(plan["coupling_j"]).hex()
                    or int(row.get("burn_in_sweeps", -1)) != int(plan["burn_in_sweeps"])
                    or row.get("chain_seed_hash")
                    != hash_json({"chain_seed": int(plan["chain_seed"])})
                    or not isinstance(row.get("source_result_artifact_sha256"), str)
                    or len(row["source_result_artifact_sha256"]) != 64
                ):
                    raise ValueError
            off_sweeps = int(off["completed_sweeps"])
            on_sweeps = int(on["completed_sweeps"])
            off_ns = int(off["search_wall_ns"])
            on_ns = int(on["search_wall_ns"])
            if min(off_sweeps, on_sweeps, off_ns, on_ns) <= 0:
                raise ValueError
            if off_sweeps != on_sweeps:
                raise ValueError
            off_rate = off_sweeps * 1_000_000_000.0 / off_ns
            on_rate = on_sweeps * 1_000_000_000.0 / on_ns
            effects.append(abs(on_rate / off_rate - 1.0))
            off_fingerprint = off.get("scientific_fingerprint")
            on_fingerprint = on.get("scientific_fingerprint")
            if (
                not isinstance(off_fingerprint, str)
                or not off_fingerprint
                or not isinstance(on_fingerprint, str)
                or not on_fingerprint
                or off_fingerprint != on_fingerprint
            ):
                invalid.append(pair_id)
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            invalid.append(pair_id)
    median_effect = statistics.median(effects) if effects else math.inf
    maximum_effect = max(effects) if effects else math.inf
    passed = (
        set(by_pair) == set(planned)
        and len(effects) >= threshold.minimum_instrumentation_pairs
        and not invalid
        and maximum_effect <= threshold.maximum_instrumentation_relative_effect
    )
    evidence = {
        "valid_pair_count": len(effects),
        "required_pair_count": threshold.minimum_instrumentation_pairs,
        "invalid_pair_ids": invalid,
        "missing_planned_pair_ids": sorted(set(planned) - set(by_pair)),
        "unexpected_pair_ids": sorted(set(by_pair) - set(planned)),
        "median_absolute_relative_throughput_effect": median_effect,
        "maximum_absolute_relative_throughput_effect": maximum_effect,
        "maximum_allowed_effect": threshold.maximum_instrumentation_relative_effect,
    }
    reason = (
        "instrumentation panel is incomplete, changes fixed-work state, or exceeds "
        "the frozen throughput tolerance"
    )
    return passed, evidence, reason


def _diagnostic_summary(
    records: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
    threshold: IsingGateThresholds,
) -> tuple[bool, dict[str, Any], list[str]]:
    config = manifest["config"]
    main_size = int(config["lattice_size"])
    coupling = float(config["coupling_j"])
    planned_panels = manifest["design"]["diagnostic_plan"]["panels"]
    plan_by_key = {
        (str(panel["panel_kind"]), float(panel["temperature"]).hex()): panel
        for panel in planned_panels
    }
    by_key: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    reasons: list[str] = []
    row_failures: list[dict[str, Any]] = []
    exact_cache: dict[tuple[int, str, str], dict[str, float]] = {}
    temperature_hexes = {temperature.hex() for temperature in ISING_TEMPERATURES}
    for record in records:
        panel = str(record.get("panel_kind", ""))
        observable = str(record.get("observable", ""))
        try:
            temperature = float(record["temperature"])
        except (KeyError, TypeError, ValueError):
            temperature = math.nan
        key = (panel, temperature.hex(), observable)
        by_key[key].append(record)

    expected_keys = {
        (panel, temperature.hex(), observable)
        for panel in ("main_convergence", "exact_reference")
        for temperature in ISING_TEMPERATURES
        for observable in OBSERVABLES
    }
    missing_or_duplicate = [
        key for key in sorted(expected_keys) if len(by_key.get(key, ())) != 1
    ]
    extra = [key for key in sorted(by_key) if key not in expected_keys]
    if missing_or_duplicate:
        reasons.append("diagnostic matrix is missing or duplicates required cells")
    if extra:
        reasons.append("diagnostic matrix contains unfrozen cells")

    for key in sorted(expected_keys):
        rows = by_key.get(key, ())
        if len(rows) != 1:
            continue
        record = rows[0]
        panel, temperature_hex, observable = key
        plan = plan_by_key.get((panel, temperature_hex))
        failures: list[str] = []
        if record.get("schema_version") != ISING_DIAGNOSTIC_SCHEMA_VERSION:
            failures.append("schema")
        supplied_record_hash = record.get("record_hash")
        unhashed_record = {key: value for key, value in record.items() if key != "record_hash"}
        if supplied_record_hash != hash_json(unhashed_record):
            failures.append("record_hash")
        if plan is None or record.get("diagnostic_plan_row_hash") != plan.get(
            "plan_row_hash"
        ):
            failures.append("diagnostic_plan_row_hash")
        temperature = float.fromhex(temperature_hex)
        if temperature_hex not in temperature_hexes:
            failures.append("temperature")
        size = int(record.get("lattice_size", 0))
        if plan is not None and size != int(plan["lattice_size"]):
            failures.append("planned_lattice_size")
        if panel == "main_convergence" and size != main_size:
            failures.append("main_lattice_size")
        if panel == "exact_reference" and not 2 <= size <= 4:
            failures.append("exact_reference_lattice_size")
        if (
            int(record.get("chain_count", 0)) < threshold.minimum_diagnostic_chains
            or plan is None
            or int(record.get("chain_count", 0)) != len(plan["chain_seeds"])
        ):
            failures.append("chain_count")
        if (
            int(record.get("draws_per_chain", 0))
            < threshold.minimum_diagnostic_draws_per_chain
            or plan is None
            or int(record.get("draws_per_chain", 0)) != int(plan["draws_per_chain"])
        ):
            failures.append("draws_per_chain")
        if plan is not None and (
            record.get("seed_set_hash") != plan.get("seed_set_hash")
            or int(record.get("burn_in_sweeps", -1)) != int(plan["burn_in_sweeps"])
            or float(record.get("coupling_j", math.nan)).hex()
            != float(plan["coupling_j"]).hex()
        ):
            failures.append("frozen_diagnostic_assignment")
        r_hat = float(record.get("split_r_hat", math.inf))
        ess = float(record.get("effective_sample_size", 0.0))
        mcse = float(record.get("mcse", math.inf))
        sample_mean = float(record.get("sample_mean", math.nan))
        if not math.isfinite(r_hat) or r_hat > threshold.maximum_split_r_hat:
            failures.append("split_r_hat")
        if not math.isfinite(ess) or ess < threshold.minimum_effective_sample_size:
            failures.append("effective_sample_size")
        mcse_limit = (
            threshold.maximum_mcse_absolute_magnetization
            if observable == "absolute_magnetization_per_spin"
            else threshold.maximum_mcse_energy_per_spin
        )
        if not math.isfinite(mcse) or mcse < 0 or mcse > mcse_limit:
            failures.append("mcse")
        if observable == "absolute_magnetization_per_spin":
            if not 0.0 <= sample_mean <= 1.0:
                failures.append("observable_bounds")
        elif not -2.0 * coupling <= sample_mean <= 2.0 * coupling:
            failures.append("observable_bounds")
        if panel == "exact_reference" and 2 <= size <= 4:
            cache_key = (size, temperature_hex, float(record.get("coupling_j", coupling)).hex())
            if cache_key not in exact_cache:
                exact_cache[cache_key] = exact_expectations(
                    size, temperature, float(record.get("coupling_j", coupling))
                )
            exact_key = (
                "mean_absolute_magnetization"
                if observable == "absolute_magnetization_per_spin"
                else "mean_energy_per_spin"
            )
            reference = exact_cache[cache_key][exact_key]
            recorded_reference = record.get("exact_reference")
            if recorded_reference is None or not math.isclose(
                float(recorded_reference), reference, rel_tol=0.0, abs_tol=1e-12
            ):
                failures.append("exact_reference_value")
            allowance = max(
                threshold.reference_absolute_tolerance,
                threshold.reference_mcse_multiplier * mcse,
            )
            if not math.isfinite(sample_mean) or abs(sample_mean - reference) > allowance:
                failures.append("long_run_reference_agreement")
            recorded_error = record.get("reference_absolute_error")
            if recorded_error is None or not math.isclose(
                float(recorded_error),
                abs(sample_mean - reference),
                rel_tol=0.0,
                abs_tol=1e-12,
            ):
                failures.append("reference_error_reconciliation")
        elif (
            record.get("exact_reference") is not None
            or record.get("reference_absolute_error") is not None
        ):
            failures.append("unexpected_main_reference")
        if failures:
            row_failures.append(
                {
                    "panel_kind": panel,
                    "temperature": temperature,
                    "observable": observable,
                    "failures": failures,
                }
            )
    if row_failures:
        reasons.append("one or more convergence/reference diagnostics failed")
    passed = not missing_or_duplicate and not extra and not row_failures
    evidence = {
        "required_cell_count": len(expected_keys),
        "observed_cell_count": len(records),
        "missing_or_duplicate_cells": [list(key) for key in missing_or_duplicate],
        "extra_cells": [list(key) for key in extra],
        "row_failures": row_failures,
        "maximum_split_r_hat": threshold.maximum_split_r_hat,
        "minimum_effective_sample_size": threshold.minimum_effective_sample_size,
        "maximum_mcse": {
            "absolute_magnetization_per_spin": threshold.maximum_mcse_absolute_magnetization,
            "energy_per_spin": threshold.maximum_mcse_energy_per_spin,
        },
    }
    return passed, evidence, reasons


def _case_summary(
    manifest: Mapping[str, Any], results: Sequence[Mapping[str, Any]], threshold: IsingGateThresholds
) -> tuple[list[tuple[str, bool, dict[str, Any], str]], dict[str, Mapping[str, Any]]]:
    checks: list[tuple[str, bool, dict[str, Any], str]] = []
    manifest_ids = [str(row["case_id"]) for row in manifest["rows"]]
    manifest_by_id = {str(row["case_id"]): row for row in manifest["rows"]}
    result_ids = [str(row.get("case_id", "")) for row in results]
    duplicate_ids = sorted(
        {case_id for case_id in result_ids if result_ids.count(case_id) > 1}
    )
    result_by_id = {str(row.get("case_id", "")): row for row in results}
    complete = (
        not duplicate_ids
        and set(result_ids) == set(manifest_ids)
        and len(result_ids) == len(manifest_ids)
    )
    checks.append(
        (
            "case_accounting",
            complete,
            {
                "scheduled": len(manifest_ids),
                "observed": len(result_ids),
                "duplicate_case_ids": duplicate_ids,
                "missing_case_ids": sorted(set(manifest_ids) - set(result_ids)),
                "unexpected_case_ids": sorted(set(result_ids) - set(manifest_ids)),
            },
            "every scheduled Ising case must have exactly one result",
        )
    )
    validation_errors: list[dict[str, str]] = []
    for result in results:
        try:
            case_id = str(result.get("case_id", ""))
            if case_id not in manifest_by_id:
                validate_ising_case_result(result)
                raise ValueError("result case ID is absent from the manifest")
            validate_ising_case_result_against_row(result, manifest_by_id[case_id])
            if result.get("artifact_sha256") != hash_json(_artifact_without_hash(result)):
                raise ValueError("acquired Ising result artifact hash mismatch")
        except Exception as exc:
            validation_errors.append(
                {"case_id": str(result.get("case_id", "")), "error": str(exc)}
            )
    checks.append(
        (
            "case_schema_and_observable_bounds",
            not validation_errors,
            {"validation_errors": validation_errors},
            "case schemas, L^2 attempt accounting, and normalized observable bounds must hold",
        )
    )
    non_ok = [
        str(row.get("case_id", ""))
        for row in results
        if row.get("terminal_status") != "ok" or row.get("cleanup_succeeded") is not True
    ]
    checks.append(
        (
            "terminal_status_and_cleanup",
            not non_ok,
            {"failed_case_ids": non_ok},
            "all Ising cases must terminate successfully with cleanup",
        )
    )
    fixed_errors: list[str] = []
    fixed_by_chain: dict[str, dict[str, Mapping[str, Any]]] = defaultdict(dict)
    for row in results:
        if row.get("budget_mode") != "fixed_sweeps":
            continue
        try:
            if int(row["completed_sweeps"]) != int(row["requested_sweeps"]):
                fixed_errors.append(str(row.get("case_id", "")))
            fixed_by_chain[str(row["chain_id"])][str(row["load_condition"])] = row
        except (KeyError, TypeError, ValueError):
            fixed_errors.append(str(row.get("case_id", "")))
    fixed_mismatches: list[str] = []
    for chain_id, cells in fixed_by_chain.items():
        if set(cells) != {"idle", "loaded"}:
            fixed_mismatches.append(chain_id)
            continue
        try:
            if fixed_work_replay_fingerprint(cells["idle"]) != fixed_work_replay_fingerprint(
                cells["loaded"]
            ):
                fixed_mismatches.append(chain_id)
        except Exception:
            fixed_mismatches.append(chain_id)
    fixed_passed = not fixed_errors and not fixed_mismatches and bool(fixed_by_chain)
    checks.append(
        (
            "exact_fixed_sweeps_and_load_invariance",
            fixed_passed,
            {
                "fixed_case_count": sum(len(cells) for cells in fixed_by_chain.values()),
                "nonexact_case_ids": fixed_errors,
                "load_mismatched_chain_ids": fixed_mismatches,
            },
            "fixed work must execute exactly N sweeps and replay identically under load",
        )
    )

    wall_by_batch: dict[str, dict[str, list[Mapping[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in results:
        if row.get("budget_mode") == "wall_clock" and row.get("terminal_status") == "ok":
            wall_by_batch[str(row["load_batch_id"])][str(row["load_condition"])].append(row)
    reductions: list[float] = []
    invalid_batches: list[str] = []
    for batch_id, conditions in sorted(wall_by_batch.items()):
        idle = conditions.get("idle", ())
        loaded = conditions.get("loaded", ())
        if not idle or len(idle) != len(loaded):
            invalid_batches.append(batch_id)
            continue
        idle_total = sum(int(row["completed_sweeps"]) for row in idle)
        loaded_total = sum(int(row["completed_sweeps"]) for row in loaded)
        if idle_total <= 0:
            invalid_batches.append(batch_id)
            continue
        reductions.append(1.0 - loaded_total / idle_total)
    median_reduction = statistics.median(reductions) if reductions else -math.inf
    load_passed = (
        len(reductions) >= threshold.minimum_load_batches
        and not invalid_batches
        and median_reduction >= threshold.minimum_loaded_sweep_reduction
    )
    checks.append(
        (
            "loaded_wall_clock_sweep_reduction",
            load_passed,
            {
                "valid_load_batch_count": len(reductions),
                "required_load_batch_count": threshold.minimum_load_batches,
                "invalid_load_batches": invalid_batches,
                "paired_batch_reductions": reductions,
                "median_paired_batch_reduction": median_reduction,
                "minimum_required_reduction": threshold.minimum_loaded_sweep_reduction,
            },
            "loaded wall-clock execution must reduce completed sweeps by at least 20%",
        )
    )
    return checks, result_by_id


def _finalize_report(
    threshold: IsingGateThresholds,
    checks: Sequence[tuple[str, bool, Mapping[str, Any], str]],
) -> dict[str, Any]:
    failures = [reason for _, passed, _, reason in checks if not passed]
    decision = "APS_GO" if not failures else "APS_NO_GO"
    report: dict[str, Any] = {
        "schema_version": ISING_GATE_SCHEMA_VERSION,
        "decision": decision,
        "scientific_scope": "open_ising_companion_only",
        "pokemon_scope_effect": "none",
        "pokemon_rescue_allowed": False,
        "thresholds": {
            name: getattr(threshold, name)
            for name in threshold.__dataclass_fields__
        },
        "checks": [
            {"name": name, "passed": bool(passed), "evidence": dict(evidence)}
            for name, passed, evidence, _ in checks
        ],
        "reasons": failures or ["all frozen Ising companion gates passed"],
        "interpretation": (
            "APS_GO establishes only that the Ising companion arm is eligible for "
            "APS scope; it cannot alter any Pokemon gate or study disposition."
        ),
    }
    report["report_hash"] = hash_json(report)
    return report


def evaluate_ising_gate(
    manifest: Mapping[str, Any],
    case_results: Sequence[Mapping[str, Any]],
    diagnostics: Sequence[Mapping[str, Any]],
    clean_process_replay: Mapping[str, Any],
    instrumentation_rows: Sequence[Mapping[str, Any]],
    resource_profile_validation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return ``APS_GO`` only when every frozen Ising gate passes."""

    checks: list[tuple[str, bool, Mapping[str, Any], str]] = []
    try:
        validate_ising_manifest(manifest)
        threshold = IsingGateThresholds.from_mapping(
            manifest["config"]["gate_thresholds"]
        )
        manifest_passed = True
        manifest_error = ""
    except Exception as exc:
        threshold = IsingGateThresholds()
        manifest_passed = False
        manifest_error = f"{type(exc).__name__}: {exc}"
    checks.append(
        (
            "frozen_manifest",
            manifest_passed,
            {"error": manifest_error},
            "the deterministic Ising manifest or its frozen thresholds are invalid",
        )
    )
    if not manifest_passed:
        return _finalize_report(threshold, checks)

    resource_validation = dict(resource_profile_validation or {})
    unhashed_resource_validation = {
        key: value
        for key, value in resource_validation.items()
        if key != "report_hash"
    }
    episode_hashes = list(resource_validation.get("resource_episode_hashes", ()))
    batch_commit_hashes = list(resource_validation.get("batch_commit_hashes", ()))
    validated_case_hashes = list(resource_validation.get("case_result_hashes", ()))
    observed_case_hashes = [row.get("artifact_sha256") for row in case_results]
    configured_batches = int(manifest["config"]["load_batch_count"])
    configured_instrumentation_pairs = int(
        manifest["config"]["instrumentation_pair_count"]
    )
    instrumentation_commit_hashes = list(
        resource_validation.get("instrumentation_pair_commit_hashes", ())
    )
    instrumentation_result_hashes = list(
        resource_validation.get("instrumentation_result_hashes", ())
    )
    instrumentation_episode_hashes = list(
        resource_validation.get("instrumentation_resource_episode_hashes", ())
    )
    observed_instrumentation_result_hashes = [
        row.get("source_result_artifact_sha256") for row in instrumentation_rows
    ]
    def valid_hashes(values: Sequence[Any], expected_count: int) -> bool:
        return (
            len(values) == expected_count
            and len(set(map(str, values))) == len(values)
            and all(
                isinstance(value, str)
                and len(value) == 64
                and all(character in "0123456789abcdef" for character in value)
                for value in values
            )
        )

    resource_passed = (
        resource_validation.get("schema_version")
        == ISING_RESOURCE_VALIDATION_SCHEMA_VERSION
        and resource_validation.get("report_hash")
        == hash_json(unhashed_resource_validation)
        and resource_validation.get("manifest_content_hash")
        == manifest.get("content_hash")
        and resource_validation.get("scientific_validation") is True
        and resource_validation.get("passed") is True
        and int(resource_validation.get("validated_load_batch_count", 0))
        == configured_batches
        and configured_batches >= threshold.minimum_load_batches
        and int(resource_validation.get("validated_resource_episode_count", 0))
        == 2 * configured_batches
        and int(resource_validation.get("validated_case_result_count", 0))
        == len(manifest["rows"])
        and valid_hashes(episode_hashes, 2 * configured_batches)
        and valid_hashes(batch_commit_hashes, configured_batches)
        and valid_hashes(validated_case_hashes, len(manifest["rows"]))
        and valid_hashes(observed_case_hashes, len(manifest["rows"]))
        and set(validated_case_hashes) == set(observed_case_hashes)
        and int(
            resource_validation.get("validated_instrumentation_pair_count", 0)
        )
        == configured_instrumentation_pairs
        and valid_hashes(
            instrumentation_commit_hashes, configured_instrumentation_pairs
        )
        and valid_hashes(
            instrumentation_result_hashes, 2 * configured_instrumentation_pairs
        )
        and valid_hashes(
            observed_instrumentation_result_hashes,
            2 * configured_instrumentation_pairs,
        )
        and set(instrumentation_result_hashes)
        == set(observed_instrumentation_result_hashes)
        and valid_hashes(
            instrumentation_episode_hashes, configured_instrumentation_pairs
        )
        and resource_validation.get("validator_contract")
        == (
            "resource_envelope_study.acquire._validate_episode+"
            "_validate_scientific_episode"
        )
    )
    checks.append(
        (
            "resource_profile_manipulation",
            resource_passed,
            {
                "scientific_validation": resource_validation.get(
                    "scientific_validation"
                ),
                "validated_load_batch_count": resource_validation.get(
                    "validated_load_batch_count"
                ),
                "validated_resource_episode_count": resource_validation.get(
                    "validated_resource_episode_count"
                ),
                "required_load_batch_count": configured_batches,
                "resource_episode_hash_count": len(episode_hashes),
                "batch_commit_hash_count": len(batch_commit_hashes),
                "validated_case_result_hash_count": len(validated_case_hashes),
                "observed_case_result_hash_count": len(observed_case_hashes),
                "case_result_hash_sets_match": set(validated_case_hashes)
                == set(observed_case_hashes),
                "validated_instrumentation_pair_count": resource_validation.get(
                    "validated_instrumentation_pair_count"
                ),
                "instrumentation_commit_hash_count": len(
                    instrumentation_commit_hashes
                ),
                "instrumentation_result_hash_sets_match": set(
                    instrumentation_result_hashes
                )
                == set(observed_instrumentation_result_hashes),
                "instrumentation_resource_episode_hash_count": len(
                    instrumentation_episode_hashes
                ),
            },
            "paired idle/loaded periods lack complete affinity, co-runner, CPU-time, or cleanup evidence",
        )
    )

    case_checks, result_by_id = _case_summary(manifest, case_results, threshold)
    checks.extend(case_checks)
    diagnostic_passed, diagnostic_evidence, diagnostic_reasons = _diagnostic_summary(
        diagnostics, manifest, threshold
    )
    checks.append(
        (
            "convergence_and_exact_reference",
            diagnostic_passed,
            diagnostic_evidence,
            "; ".join(diagnostic_reasons)
            or "convergence/reference diagnostic matrix failed",
        )
    )

    replay_fingerprints = list(clean_process_replay.get("scientific_fingerprints", ()))
    replay_hash_seeds = list(clean_process_replay.get("python_hash_seeds", ()))
    replay_unhashed = {
        key: value
        for key, value in clean_process_replay.items()
        if key != "report_hash"
    }
    replay_designation = manifest["design"]["clean_process_replay"]
    designated_case_id = str(replay_designation["case_id"])
    acquired_designated = result_by_id.get(designated_case_id)
    try:
        acquired_fingerprint = (
            fixed_work_replay_fingerprint(acquired_designated)
            if acquired_designated is not None
            else None
        )
    except Exception:
        acquired_fingerprint = None
    replay_passed = (
        clean_process_replay.get("schema_version") == ISING_REPLAY_SCHEMA_VERSION
        and clean_process_replay.get("report_hash") == hash_json(replay_unhashed)
        and clean_process_replay.get("case_id") == designated_case_id
        and clean_process_replay.get("manifest_row_hash")
        == replay_designation["manifest_row_hash"]
        and clean_process_replay.get("passed") is True
        and int(clean_process_replay.get("repeats", 0))
        >= threshold.minimum_clean_process_replays
        and len(replay_fingerprints) >= threshold.minimum_clean_process_replays
        and len(set(map(str, replay_fingerprints))) == 1
        and len(replay_hash_seeds) == int(clean_process_replay.get("repeats", 0))
        and len(set(map(str, replay_hash_seeds))) == len(replay_hash_seeds)
        and acquired_fingerprint is not None
        and replay_fingerprints[0] == acquired_fingerprint
    )
    checks.append(
        (
            "clean_process_replay",
            replay_passed,
            {
                "repeats": clean_process_replay.get("repeats"),
                "unique_scientific_fingerprints": len(
                    set(map(str, replay_fingerprints))
                ),
                "designated_case_id": designated_case_id,
                "reported_case_id": clean_process_replay.get("case_id"),
                "matches_acquired_fingerprint": (
                    bool(replay_fingerprints)
                    and acquired_fingerprint is not None
                    and replay_fingerprints[0] == acquired_fingerprint
                ),
            },
            "designated fixed-work artifacts do not replay across clean processes",
        )
    )

    instrumentation_passed, instrumentation_evidence, instrumentation_reason = (
        _instrumentation_summary(instrumentation_rows, manifest, threshold)
    )
    checks.append(
        (
            "instrumentation_throughput",
            instrumentation_passed,
            instrumentation_evidence,
            instrumentation_reason,
        )
    )
    return _finalize_report(threshold, checks)
