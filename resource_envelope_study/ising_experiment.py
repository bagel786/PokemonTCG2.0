"""Auditable experiment contract for the open Ising companion arm.

The numerical kernel lives in :mod:`resource_envelope_study.adapters.ising`.
This module deliberately does not implement CPU contention.  Instead it emits a
spawn-safe resource-profile request that the study's existing acquisition layer
can execute under its ``ResourceEnvelope`` contract.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from .adapters.ising import ISING_TC, IsingSearchAdapter
from .canonical import (
    canonical_json_bytes,
    derive_u32,
    derive_u64,
    deterministic_shuffle,
    hash_json,
)
from .runner import CaseContext, run_decision
from .stop_policy import FixedWorkStop, WallClockStop


ISING_TEMPERATURES = (1.5, ISING_TC, 3.5)
ISING_MANIFEST_SCHEMA_VERSION = "ising-experiment-manifest-1.0.0"
ISING_ROW_SCHEMA_VERSION = "ising-case-row-1.0.0"
ISING_RESULT_SCHEMA_VERSION = "ising-case-result-1.0.0"
ISING_REPLAY_SCHEMA_VERSION = "ising-clean-process-replay-1.0.0"
RESOURCE_PROFILE_CONTRACT_VERSION = "resource-envelope-request-1.0.0"
ISING_EXECUTION_ENTRYPOINT = (
    "resource_envelope_study.ising_experiment:execute_ising_case"
)


@dataclass(frozen=True)
class IsingGateThresholds:
    """Thresholds serialized into every manifest before outcomes exist."""

    minimum_load_batches: int = 20
    maximum_split_r_hat: float = 1.01
    minimum_effective_sample_size: float = 400.0
    maximum_mcse_absolute_magnetization: float = 0.02
    maximum_mcse_energy_per_spin: float = 0.02
    reference_absolute_tolerance: float = 0.03
    reference_mcse_multiplier: float = 4.0
    minimum_diagnostic_chains: int = 4
    minimum_diagnostic_draws_per_chain: int = 1_000
    minimum_loaded_sweep_reduction: float = 0.20
    maximum_instrumentation_relative_effect: float = 0.05
    minimum_instrumentation_pairs: int = 20
    minimum_clean_process_replays: int = 2

    def validate(self) -> None:
        if self.minimum_load_batches < 20 or self.minimum_load_batches % 2:
            raise ValueError("minimum_load_batches must be an even integer >=20")
        if not 1.0 <= self.maximum_split_r_hat <= 1.01:
            raise ValueError("maximum_split_r_hat must be in [1, 1.01]")
        if self.minimum_effective_sample_size <= 0:
            raise ValueError("minimum_effective_sample_size must be positive")
        if self.maximum_mcse_absolute_magnetization <= 0:
            raise ValueError("absolute-magnetization MCSE threshold must be positive")
        if self.maximum_mcse_energy_per_spin <= 0:
            raise ValueError("energy MCSE threshold must be positive")
        if self.reference_absolute_tolerance <= 0:
            raise ValueError("reference tolerance must be positive")
        if self.reference_mcse_multiplier <= 0:
            raise ValueError("reference MCSE multiplier must be positive")
        if self.minimum_diagnostic_chains < 4:
            raise ValueError("at least four independent diagnostic chains are required")
        if self.minimum_diagnostic_draws_per_chain < 4:
            raise ValueError("diagnostic chains need at least four retained draws")
        if not 0.20 <= self.minimum_loaded_sweep_reduction < 1.0:
            raise ValueError("loaded sweep-reduction threshold must be in [0.20, 1)")
        if not 0.0 < self.maximum_instrumentation_relative_effect <= 0.05:
            raise ValueError("instrumentation threshold must be in (0, 0.05]")
        if self.minimum_instrumentation_pairs <= 0:
            raise ValueError("minimum_instrumentation_pairs must be positive")
        if self.minimum_clean_process_replays < 2:
            raise ValueError("at least two clean-process replays are required")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "IsingGateThresholds":
        threshold = cls(**{name: value[name] for name in cls.__dataclass_fields__})
        threshold.validate()
        return threshold


@dataclass(frozen=True)
class IsingExperimentConfig:
    """Frozen factors for one pilot or confirmatory Ising schedule."""

    master_seed: int
    phase: str = "pilot"
    lattice_size: int = 16
    temperatures: tuple[float, float, float] = ISING_TEMPERATURES
    coupling_j: float = 1.0
    burn_in_sweeps: int = 1_000
    wall_clock_budget_ns: int = 100_000_000
    fixed_sweeps: int = 100
    fixed_sweeps_source: str = "independent_idle_fresh_pilot_median"
    load_batch_count: int = 20
    chains_per_temperature_batch: int = 1
    instrumentation_enabled: bool = True
    diagnostic_chain_count: int = 4
    diagnostic_draws_per_chain: int = 1_000
    diagnostic_burn_in_sweeps: int = 2_000
    exact_reference_lattice_size: int = 4
    instrumentation_pair_count: int = 20
    gate_thresholds: IsingGateThresholds = field(default_factory=IsingGateThresholds)

    def validate(self) -> None:
        if isinstance(self.master_seed, bool) or not isinstance(self.master_seed, int):
            raise ValueError("master_seed must be an integer")
        if self.phase not in {"smoke", "pilot", "final"}:
            raise ValueError("phase must be smoke, pilot, or final")
        if self.lattice_size < 2:
            raise ValueError("lattice_size must be at least two")
        if tuple(self.temperatures) != ISING_TEMPERATURES:
            raise ValueError(
                "temperatures are frozen at 1.5, exact Onsager Tc, and 3.5"
            )
        if not math.isfinite(self.coupling_j) or self.coupling_j <= 0:
            raise ValueError("coupling_j must be finite and positive")
        if self.burn_in_sweeps < 0:
            raise ValueError("burn_in_sweeps cannot be negative")
        if self.wall_clock_budget_ns <= 0:
            raise ValueError("wall_clock_budget_ns must be positive")
        if self.fixed_sweeps <= 0:
            raise ValueError("fixed_sweeps must be positive")
        if not self.fixed_sweeps_source.strip():
            raise ValueError("fixed_sweeps_source must identify the independent pilot")
        self.gate_thresholds.validate()
        if self.load_batch_count < self.gate_thresholds.minimum_load_batches:
            raise ValueError("load_batch_count is below the frozen gate minimum")
        if self.load_batch_count % 2:
            raise ValueError("load_batch_count must be even for exact AB/BA balance")
        if self.chains_per_temperature_batch <= 0:
            raise ValueError("chains_per_temperature_batch must be positive")
        if not isinstance(self.instrumentation_enabled, bool):
            raise ValueError("instrumentation_enabled must be boolean")
        if self.diagnostic_chain_count < self.gate_thresholds.minimum_diagnostic_chains:
            raise ValueError("diagnostic_chain_count is below the frozen gate minimum")
        if (
            self.diagnostic_draws_per_chain
            < self.gate_thresholds.minimum_diagnostic_draws_per_chain
        ):
            raise ValueError("diagnostic draws are below the frozen gate minimum")
        if self.diagnostic_burn_in_sweeps < 0:
            raise ValueError("diagnostic burn-in cannot be negative")
        if not 2 <= self.exact_reference_lattice_size <= 4:
            raise ValueError("exact reference lattice must satisfy 2 <= L <= 4")
        if self.instrumentation_pair_count < self.gate_thresholds.minimum_instrumentation_pairs:
            raise ValueError("instrumentation pair count is below the frozen minimum")
        if self.instrumentation_pair_count % 2:
            raise ValueError("instrumentation pairs must be even for exact AB/BA balance")

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["temperatures"] = list(self.temperatures)
        return result


def _manifest_without_hash(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in manifest.items() if key != "content_hash"}


def _case_id(case_identity: Mapping[str, Any]) -> str:
    return f"ising-case-{hash_json(case_identity)[:24]}"


def build_ising_manifest(config: IsingExperimentConfig) -> dict[str, Any]:
    """Create a canonical, outcome-blind paired idle/loaded schedule."""

    config.validate()
    batch_indexes = deterministic_shuffle(
        range(config.load_batch_count), config.master_seed, "ising_load_order"
    )
    idle_first = set(batch_indexes[: config.load_batch_count // 2])
    rows: list[dict[str, Any]] = []
    execution_index = 0
    for batch_index in range(config.load_batch_count):
        load_batch_id = f"{config.phase}-ising-load-pair-{batch_index:03d}"
        load_seed = derive_u32(config.master_seed, "ising_load", load_batch_id)
        load_period_order = (
            "idle_then_loaded" if batch_index in idle_first else "loaded_then_idle"
        )
        conditions = (
            ("idle", "loaded")
            if load_period_order == "idle_then_loaded"
            else ("loaded", "idle")
        )
        for condition in conditions:
            within_period: list[dict[str, Any]] = []
            for temperature_index, temperature in enumerate(config.temperatures):
                for replicate in range(config.chains_per_temperature_batch):
                    chain_id = (
                        f"{config.phase}-ising-chain-{batch_index:03d}-"
                        f"t{temperature_index}-r{replicate:03d}"
                    )
                    chain_seed = derive_u64(
                        config.master_seed, "ising_chain", chain_id
                    )
                    for budget_mode in ("wall_clock", "fixed_sweeps"):
                        identity = {
                            "phase": config.phase,
                            "chain_id": chain_id,
                            "budget_mode": budget_mode,
                            "load_condition": condition,
                        }
                        within_period.append(
                            {
                                "schema_version": ISING_ROW_SCHEMA_VERSION,
                                "case_id": _case_id(identity),
                                "phase": config.phase,
                                "chain_id": chain_id,
                                "chain_seed": chain_seed,
                                "temperature_index": temperature_index,
                                "temperature": temperature,
                                "lattice_size": config.lattice_size,
                                "coupling_j": config.coupling_j,
                                "burn_in_sweeps": config.burn_in_sweeps,
                                "burn_in_in_measurement": False,
                                "work_unit": "one_random_scan_sweep_L_squared_attempts",
                                "budget_mode": budget_mode,
                                "requested_budget_ns": (
                                    config.wall_clock_budget_ns
                                    if budget_mode == "wall_clock"
                                    else None
                                ),
                                "requested_sweeps": (
                                    config.fixed_sweeps
                                    if budget_mode == "fixed_sweeps"
                                    else None
                                ),
                                "load_condition": condition,
                                "load_batch_id": load_batch_id,
                                "load_seed": load_seed,
                                "load_period_order": load_period_order,
                                "instrumentation_enabled": config.instrumentation_enabled,
                                "resource_profile_contract": {
                                    "schema_version": RESOURCE_PROFILE_CONTRACT_VERSION,
                                    "condition": condition,
                                    "load_batch_id": load_batch_id,
                                    "load_seed": load_seed,
                                    "requires_external_controller": True,
                                },
                            }
                        )
            period_seed = derive_u64(
                config.master_seed,
                "ising_period_execution_order",
                load_batch_id,
                condition,
            )
            for row in deterministic_shuffle(
                within_period, period_seed, f"{load_batch_id}:{condition}"
            ):
                row["execution_index"] = execution_index
                execution_index += 1
                rows.append(row)

    primary_chain_seeds = {int(row["chain_seed"]) for row in rows}
    diagnostic_panels: list[dict[str, Any]] = []
    diagnostic_seeds: set[int] = set()
    for panel_kind, lattice_size in (
        ("main_convergence", config.lattice_size),
        ("exact_reference", config.exact_reference_lattice_size),
    ):
        for temperature_index, temperature in enumerate(config.temperatures):
            seeds = [
                derive_u64(
                    config.master_seed,
                    "ising_diagnostic_chain",
                    panel_kind,
                    temperature_index,
                    chain_index,
                )
                for chain_index in range(config.diagnostic_chain_count)
            ]
            if diagnostic_seeds.intersection(seeds) or primary_chain_seeds.intersection(seeds):
                raise RuntimeError("domain-separated Ising seed derivation collided")
            diagnostic_seeds.update(seeds)
            panel = {
                "schema_version": "ising-diagnostic-plan-row-1.0.0",
                "panel_kind": panel_kind,
                "lattice_size": lattice_size,
                "temperature_index": temperature_index,
                "temperature": temperature,
                "coupling_j": config.coupling_j,
                "burn_in_sweeps": config.diagnostic_burn_in_sweeps,
                "draws_per_chain": config.diagnostic_draws_per_chain,
                "chain_seeds": seeds,
                "seed_set_hash": hash_json({"seeds": seeds}),
            }
            panel["plan_row_hash"] = hash_json(panel)
            diagnostic_panels.append(panel)
    diagnostic_plan: dict[str, Any] = {
        "schema_version": "ising-diagnostic-plan-1.0.0",
        "panels": diagnostic_panels,
    }
    diagnostic_plan["content_hash"] = hash_json(diagnostic_plan)

    instrumentation_order_indexes = deterministic_shuffle(
        range(config.instrumentation_pair_count),
        config.master_seed,
        "ising_instrumentation_order",
    )
    instrumentation_off_first = set(
        instrumentation_order_indexes[: config.instrumentation_pair_count // 2]
    )
    instrumentation_pairs: list[dict[str, Any]] = []
    instrumentation_seeds: set[int] = set()
    for pair_index in range(config.instrumentation_pair_count):
        pair_id = f"{config.phase}-ising-instrumentation-{pair_index:03d}"
        chain_seed = derive_u64(
            config.master_seed, "ising_instrumentation_chain", pair_id
        )
        if (
            chain_seed in primary_chain_seeds
            or chain_seed in diagnostic_seeds
            or chain_seed in instrumentation_seeds
        ):
            raise RuntimeError("domain-separated instrumentation seed derivation collided")
        instrumentation_seeds.add(chain_seed)
        temperature_index = pair_index % len(config.temperatures)
        pair = {
            "schema_version": "ising-instrumentation-plan-row-1.0.0",
            "pair_id": pair_id,
            "chain_seed": chain_seed,
            "temperature_index": temperature_index,
            "temperature": config.temperatures[temperature_index],
            "lattice_size": config.lattice_size,
            "coupling_j": config.coupling_j,
            "burn_in_sweeps": config.burn_in_sweeps,
            "requested_sweeps": config.fixed_sweeps,
            "execution_order": (
                "off_then_on"
                if pair_index in instrumentation_off_first
                else "on_then_off"
            ),
            "equivalence_metric": "maximum_absolute_paired_relative_throughput_effect",
            "maximum_relative_effect": config.gate_thresholds.maximum_instrumentation_relative_effect,
        }
        pair["plan_row_hash"] = hash_json(pair)
        instrumentation_pairs.append(pair)
    instrumentation_plan: dict[str, Any] = {
        "schema_version": "ising-instrumentation-plan-1.0.0",
        "pairs": instrumentation_pairs,
    }
    instrumentation_plan["content_hash"] = hash_json(instrumentation_plan)

    replay_row = min(
        (
            row
            for row in rows
            if row["budget_mode"] == "fixed_sweeps" and row["load_condition"] == "idle"
        ),
        key=lambda row: str(row["case_id"]),
    )
    manifest: dict[str, Any] = {
        "schema_version": ISING_MANIFEST_SCHEMA_VERSION,
        "config": config.to_dict(),
        "design": {
            "scientific_scope": "open_ising_companion_only",
            "lattice": "square_periodic_2d_ferromagnetic",
            "update": "single_spin_random_scan_metropolis",
            "attempts_per_sweep": "L^2",
            "burn_in_timing": "outside_measurement",
            "observables": [
                "magnetization_per_spin",
                "absolute_magnetization_per_spin",
                "energy_per_spin",
            ],
            "independent_unit": "chain_id",
            "pairing": "same_chain_seed_across_budget_and_load_conditions",
            "load_assignment_unit": "paired_load_batch",
            "load_period_balance": "exact_AB_BA",
            "resource_controller": "external_integration_hook",
            "rng_domains": {
                "primary_chain": "ising_chain",
                "diagnostic_chain": "ising_diagnostic_chain",
                "instrumentation_chain": "ising_instrumentation_chain",
                "external_load": "ising_load",
                "execution_order": "ising_period_execution_order",
            },
            "clean_process_replay": {
                "case_id": replay_row["case_id"],
                "manifest_row_hash": hash_json(replay_row),
                "minimum_repeats": config.gate_thresholds.minimum_clean_process_replays,
            },
            "diagnostic_plan": diagnostic_plan,
            "instrumentation_plan": instrumentation_plan,
            "pokemon_scope_effect": "none",
        },
        "rows": rows,
    }
    manifest["content_hash"] = hash_json(manifest)
    validate_ising_manifest(manifest)
    return manifest


def _temperature_identity(values: Sequence[Any]) -> tuple[str, ...]:
    return tuple(float(value).hex() for value in values)


def validate_ising_manifest(manifest: Mapping[str, Any]) -> None:
    """Fail closed on schedule drift, reuse, imbalance, or factor omission."""

    if manifest.get("schema_version") != ISING_MANIFEST_SCHEMA_VERSION:
        raise ValueError("unexpected Ising manifest schema version")
    if manifest.get("content_hash") != hash_json(_manifest_without_hash(manifest)):
        raise ValueError("Ising manifest content hash mismatch")
    config = dict(manifest.get("config", {}))
    if _temperature_identity(config.get("temperatures", ())) != _temperature_identity(
        ISING_TEMPERATURES
    ):
        raise ValueError("manifest temperature set drifted from the frozen values")
    threshold = IsingGateThresholds.from_mapping(config.get("gate_thresholds", {}))
    batch_count = int(config.get("load_batch_count", 0))
    if batch_count < threshold.minimum_load_batches or batch_count % 2:
        raise ValueError("manifest requires an even number of at least 20 load batches")
    chains_per = int(config.get("chains_per_temperature_batch", 0))
    if chains_per <= 0:
        raise ValueError("manifest has no independent chain replicates")
    diagnostic_chain_count = int(config.get("diagnostic_chain_count", 0))
    diagnostic_draws = int(config.get("diagnostic_draws_per_chain", 0))
    if diagnostic_chain_count < threshold.minimum_diagnostic_chains:
        raise ValueError("manifest diagnostic chain count is below its frozen minimum")
    if diagnostic_draws < threshold.minimum_diagnostic_draws_per_chain:
        raise ValueError("manifest diagnostic draws are below their frozen minimum")
    if int(config.get("diagnostic_burn_in_sweeps", -1)) < 0:
        raise ValueError("manifest diagnostic burn-in is invalid")
    if not 2 <= int(config.get("exact_reference_lattice_size", 0)) <= 4:
        raise ValueError("manifest exact reference lattice must satisfy L<=4")
    instrumentation_pair_count = int(config.get("instrumentation_pair_count", 0))
    if (
        instrumentation_pair_count < threshold.minimum_instrumentation_pairs
        or instrumentation_pair_count % 2
    ):
        raise ValueError("manifest instrumentation plan is too small or unbalanced")
    rows = list(manifest.get("rows", ()))
    expected_rows = batch_count * len(ISING_TEMPERATURES) * chains_per * 4
    if len(rows) != expected_rows:
        raise ValueError(f"manifest has {len(rows)} rows; expected {expected_rows}")
    if [int(row.get("execution_index", -1)) for row in rows] != list(
        range(expected_rows)
    ):
        raise ValueError("execution indexes must be unique and contiguous")
    case_ids = [str(row.get("case_id", "")) for row in rows]
    if not all(case_ids) or len(set(case_ids)) != len(case_ids):
        raise ValueError("case IDs must be nonempty and unique")

    orders_by_batch: dict[str, set[str]] = {}
    conditions_by_batch: dict[str, set[str]] = {}
    rows_by_chain: dict[str, list[Mapping[str, Any]]] = {}
    seed_by_chain: dict[str, set[int]] = {}
    for row in rows:
        if row.get("schema_version") != ISING_ROW_SCHEMA_VERSION:
            raise ValueError("unexpected Ising row schema version")
        if row.get("work_unit") != "one_random_scan_sweep_L_squared_attempts":
            raise ValueError("Ising work-unit definition drifted")
        if row.get("burn_in_in_measurement") is not False:
            raise ValueError("burn-in must remain outside the measurement budget")
        condition = str(row.get("load_condition"))
        if condition not in {"idle", "loaded"}:
            raise ValueError("invalid load condition")
        budget_mode = str(row.get("budget_mode"))
        if budget_mode not in {"wall_clock", "fixed_sweeps"}:
            raise ValueError("invalid Ising budget mode")
        if budget_mode == "wall_clock":
            if int(row.get("requested_budget_ns") or 0) <= 0:
                raise ValueError("wall-clock row lacks a positive deadline")
            if row.get("requested_sweeps") is not None:
                raise ValueError("wall-clock row must not request fixed sweeps")
        else:
            if int(row.get("requested_sweeps") or 0) <= 0:
                raise ValueError("fixed-work row lacks positive sweeps")
            if row.get("requested_budget_ns") is not None:
                raise ValueError("fixed-work row must not request a deadline")
        if int(row.get("lattice_size", 0)) < 2:
            raise ValueError("invalid lattice size")
        temperature_index = int(row.get("temperature_index", -1))
        if not 0 <= temperature_index < len(ISING_TEMPERATURES):
            raise ValueError("invalid temperature index")
        if float(row.get("temperature", math.nan)).hex() != ISING_TEMPERATURES[
            temperature_index
        ].hex():
            raise ValueError("row temperature does not match its frozen stratum")
        batch_id = str(row.get("load_batch_id", ""))
        orders_by_batch.setdefault(batch_id, set()).add(str(row.get("load_period_order")))
        conditions_by_batch.setdefault(batch_id, set()).add(condition)
        chain_id = str(row.get("chain_id", ""))
        rows_by_chain.setdefault(chain_id, []).append(row)
        seed_by_chain.setdefault(chain_id, set()).add(int(row.get("chain_seed", -1)))
        contract = row.get("resource_profile_contract", {})
        if not isinstance(contract, Mapping):
            raise ValueError("resource profile contract must be an object")
        if (
            contract.get("schema_version") != RESOURCE_PROFILE_CONTRACT_VERSION
            or contract.get("condition") != condition
            or contract.get("load_batch_id") != batch_id
            or int(contract.get("load_seed", -1)) != int(row.get("load_seed", -2))
            or contract.get("requires_external_controller") is not True
        ):
            raise ValueError("resource profile contract does not reconcile with its row")

    if len(orders_by_batch) != batch_count:
        raise ValueError("manifest does not represent every configured load batch")
    order_counts = {"idle_then_loaded": 0, "loaded_then_idle": 0}
    for batch_id, orders in orders_by_batch.items():
        if len(orders) != 1:
            raise ValueError(f"load order changes inside batch {batch_id}")
        order = next(iter(orders))
        if order not in order_counts:
            raise ValueError(f"unknown load period order {order}")
        order_counts[order] += 1
        if conditions_by_batch.get(batch_id) != {"idle", "loaded"}:
            raise ValueError(f"load batch {batch_id} lacks a complete idle/loaded pair")
    if len(set(order_counts.values())) != 1:
        raise ValueError("load periods are not exactly AB/BA balanced")

    if len(set(next(iter(seeds)) for seeds in seed_by_chain.values())) != len(
        seed_by_chain
    ):
        raise ValueError("independent chain IDs reuse a chain seed")
    for chain_id, chain_rows in rows_by_chain.items():
        if not chain_id or len(chain_rows) != 4 or len(seed_by_chain[chain_id]) != 1:
            raise ValueError(f"chain {chain_id!r} is not a complete independent block")
        cells = {
            (str(row["load_condition"]), str(row["budget_mode"]))
            for row in chain_rows
        }
        if cells != {
            ("idle", "wall_clock"),
            ("loaded", "wall_clock"),
            ("idle", "fixed_sweeps"),
            ("loaded", "fixed_sweeps"),
        }:
            raise ValueError(f"chain {chain_id} lacks the four matched cells")

    design = manifest.get("design", {})
    if not isinstance(design, Mapping):
        raise ValueError("manifest design must be an object")
    expected_domains = {
        "primary_chain": "ising_chain",
        "diagnostic_chain": "ising_diagnostic_chain",
        "instrumentation_chain": "ising_instrumentation_chain",
        "external_load": "ising_load",
        "execution_order": "ising_period_execution_order",
    }
    if design.get("rng_domains") != expected_domains:
        raise ValueError("manifest RNG domain separation changed")
    replay = design.get("clean_process_replay", {})
    if not isinstance(replay, Mapping):
        raise ValueError("manifest lacks a clean-process replay designation")
    replay_rows = [row for row in rows if row["case_id"] == replay.get("case_id")]
    if (
        len(replay_rows) != 1
        or replay_rows[0]["budget_mode"] != "fixed_sweeps"
        or replay_rows[0]["load_condition"] != "idle"
        or replay.get("manifest_row_hash") != hash_json(replay_rows[0])
        or int(replay.get("minimum_repeats", 0))
        < threshold.minimum_clean_process_replays
    ):
        raise ValueError("clean-process replay designation is invalid")

    diagnostic_plan = design.get("diagnostic_plan", {})
    if not isinstance(diagnostic_plan, Mapping):
        raise ValueError("manifest diagnostic plan must be an object")
    if diagnostic_plan.get("schema_version") != "ising-diagnostic-plan-1.0.0":
        raise ValueError("unexpected diagnostic plan schema")
    if diagnostic_plan.get("content_hash") != hash_json(
        {key: value for key, value in diagnostic_plan.items() if key != "content_hash"}
    ):
        raise ValueError("diagnostic plan content hash mismatch")
    panels = list(diagnostic_plan.get("panels", ()))
    if len(panels) != 2 * len(ISING_TEMPERATURES):
        raise ValueError("diagnostic plan must contain six frozen panels")
    expected_panel_cells = {
        (panel_kind, temperature_index)
        for panel_kind in ("main_convergence", "exact_reference")
        for temperature_index in range(len(ISING_TEMPERATURES))
    }
    observed_panel_cells: set[tuple[str, int]] = set()
    diagnostic_seeds: list[int] = []
    for panel in panels:
        if not isinstance(panel, Mapping):
            raise ValueError("diagnostic panel row must be an object")
        supplied = panel.get("plan_row_hash")
        unhashed = {key: value for key, value in panel.items() if key != "plan_row_hash"}
        if supplied != hash_json(unhashed):
            raise ValueError("diagnostic panel row hash mismatch")
        panel_kind = str(panel.get("panel_kind"))
        temperature_index = int(panel.get("temperature_index", -1))
        observed_panel_cells.add((panel_kind, temperature_index))
        if not 0 <= temperature_index < len(ISING_TEMPERATURES):
            raise ValueError("diagnostic panel temperature index is invalid")
        if float(panel.get("temperature", math.nan)).hex() != ISING_TEMPERATURES[
            temperature_index
        ].hex():
            raise ValueError("diagnostic panel temperature drifted")
        expected_size = (
            int(config["lattice_size"])
            if panel_kind == "main_convergence"
            else int(config["exact_reference_lattice_size"])
        )
        if int(panel.get("lattice_size", 0)) != expected_size:
            raise ValueError("diagnostic panel lattice size drifted")
        if int(panel.get("burn_in_sweeps", -1)) != int(
            config["diagnostic_burn_in_sweeps"]
        ):
            raise ValueError("diagnostic burn-in drifted")
        if int(panel.get("draws_per_chain", 0)) != diagnostic_draws:
            raise ValueError("diagnostic draw count drifted")
        seeds = list(map(int, panel.get("chain_seeds", ())))
        if len(seeds) != diagnostic_chain_count or len(set(seeds)) != len(seeds):
            raise ValueError("diagnostic panel seeds are not independent")
        if panel.get("seed_set_hash") != hash_json({"seeds": seeds}):
            raise ValueError("diagnostic seed-set hash mismatch")
        diagnostic_seeds.extend(seeds)
    if observed_panel_cells != expected_panel_cells:
        raise ValueError("diagnostic panel cells are incomplete or duplicated")
    if len(set(diagnostic_seeds)) != len(diagnostic_seeds):
        raise ValueError("diagnostic chain seeds are reused across panels")

    instrumentation_plan = design.get("instrumentation_plan", {})
    if not isinstance(instrumentation_plan, Mapping):
        raise ValueError("manifest instrumentation plan must be an object")
    if instrumentation_plan.get("schema_version") != "ising-instrumentation-plan-1.0.0":
        raise ValueError("unexpected instrumentation plan schema")
    if instrumentation_plan.get("content_hash") != hash_json(
        {
            key: value
            for key, value in instrumentation_plan.items()
            if key != "content_hash"
        }
    ):
        raise ValueError("instrumentation plan content hash mismatch")
    instrumentation_pairs = list(instrumentation_plan.get("pairs", ()))
    if len(instrumentation_pairs) != instrumentation_pair_count:
        raise ValueError("instrumentation plan pair count drifted")
    pair_ids: set[str] = set()
    instrumentation_seeds: list[int] = []
    order_counts = {"off_then_on": 0, "on_then_off": 0}
    for pair in instrumentation_pairs:
        if not isinstance(pair, Mapping):
            raise ValueError("instrumentation plan row must be an object")
        supplied = pair.get("plan_row_hash")
        unhashed = {key: value for key, value in pair.items() if key != "plan_row_hash"}
        if supplied != hash_json(unhashed):
            raise ValueError("instrumentation plan row hash mismatch")
        pair_id = str(pair.get("pair_id", ""))
        if not pair_id or pair_id in pair_ids:
            raise ValueError("instrumentation pair IDs must be unique")
        pair_ids.add(pair_id)
        chain_seed = int(pair.get("chain_seed", -1))
        instrumentation_seeds.append(chain_seed)
        temperature_index = int(pair.get("temperature_index", -1))
        if not 0 <= temperature_index < len(ISING_TEMPERATURES):
            raise ValueError("instrumentation temperature index is invalid")
        if float(pair.get("temperature", math.nan)).hex() != ISING_TEMPERATURES[
            temperature_index
        ].hex():
            raise ValueError("instrumentation temperature drifted")
        if (
            int(pair.get("lattice_size", 0)) != int(config["lattice_size"])
            or float(pair.get("coupling_j", math.nan)).hex()
            != float(config["coupling_j"]).hex()
            or int(pair.get("burn_in_sweeps", -1)) != int(config["burn_in_sweeps"])
            or int(pair.get("requested_sweeps", 0)) != int(config["fixed_sweeps"])
        ):
            raise ValueError("instrumentation fixed workload drifted")
        order = str(pair.get("execution_order", ""))
        if order not in order_counts:
            raise ValueError("instrumentation execution order is invalid")
        order_counts[order] += 1
        if (
            pair.get("equivalence_metric")
            != "maximum_absolute_paired_relative_throughput_effect"
            or float(pair.get("maximum_relative_effect", math.inf))
            != threshold.maximum_instrumentation_relative_effect
        ):
            raise ValueError("instrumentation equivalence rule drifted")
    if len(set(instrumentation_seeds)) != len(instrumentation_seeds):
        raise ValueError("instrumentation seeds are reused")
    if len(set(order_counts.values())) != 1:
        raise ValueError("instrumentation execution order is not exactly balanced")
    primary_seeds = {next(iter(seeds)) for seeds in seed_by_chain.values()}
    if (
        primary_seeds.intersection(diagnostic_seeds)
        or primary_seeds.intersection(instrumentation_seeds)
        or set(diagnostic_seeds).intersection(instrumentation_seeds)
    ):
        raise ValueError("Ising RNG domains reuse a chain seed")


def _validate_case_row(row: Mapping[str, Any]) -> None:
    if row.get("schema_version") != ISING_ROW_SCHEMA_VERSION:
        raise ValueError("unexpected Ising case row schema")
    if row.get("budget_mode") not in {"wall_clock", "fixed_sweeps"}:
        raise ValueError("invalid Ising case budget mode")
    if row.get("load_condition") not in {"idle", "loaded"}:
        raise ValueError("invalid Ising case load condition")
    if row.get("burn_in_in_measurement") is not False:
        raise ValueError("burn-in cannot be included in the measurement budget")
    if row.get("work_unit") != "one_random_scan_sweep_L_squared_attempts":
        raise ValueError("invalid Ising work unit")


def validate_ising_case_result(result: Mapping[str, Any]) -> None:
    if result.get("schema_version") != ISING_RESULT_SCHEMA_VERSION:
        raise ValueError("unexpected Ising result schema")
    size = int(result["lattice_size"])
    coupling = float(result["coupling_j"])
    sweeps = int(result["completed_sweeps"])
    attempts = int(result["measurement_attempted_flips"])
    if size < 2 or coupling <= 0 or sweeps < 0:
        raise ValueError("invalid Ising result dimensions")
    if attempts != sweeps * size * size:
        raise ValueError("measurement attempts do not equal sweeps * L^2")
    if result.get("terminal_status") == "ok" and result.get("budget_mode") == "fixed_sweeps":
        if sweeps != int(result["requested_sweeps"]):
            raise ValueError("successful fixed-sweep result is not exact")
    magnetization = result.get("magnetization_per_spin")
    absolute = result.get("absolute_magnetization_per_spin")
    energy = result.get("energy_per_spin")
    if result.get("terminal_status") in {"ok", "deadline_no_work"}:
        if magnetization is None or not -1.0 <= float(magnetization) <= 1.0:
            raise ValueError("magnetization per spin is out of bounds")
        if absolute is None or not 0.0 <= float(absolute) <= 1.0:
            raise ValueError("absolute magnetization per spin is out of bounds")
        if not math.isclose(float(absolute), abs(float(magnetization)), abs_tol=1e-15):
            raise ValueError("absolute magnetization does not reconcile")
        if energy is None or not -2.0 * coupling <= float(energy) <= 2.0 * coupling:
            raise ValueError("energy per spin is out of bounds")


def validate_ising_case_result_against_row(
    result: Mapping[str, Any], row: Mapping[str, Any]
) -> None:
    """Bind every scientific factor in a result to its exact manifest row."""

    validate_ising_case_result(result)
    _validate_case_row(row)
    exact_fields = (
        ("case_id", "case_id"),
        ("chain_id", "chain_id"),
        ("temperature_index", "temperature_index"),
        ("lattice_size", "lattice_size"),
        ("burn_in_sweeps", "burn_in_sweeps"),
        ("budget_mode", "budget_mode"),
        ("requested_budget_ns", "requested_budget_ns"),
        ("requested_sweeps", "requested_sweeps"),
        ("load_condition", "load_condition"),
        ("load_batch_id", "load_batch_id"),
        ("load_seed", "load_seed"),
        ("load_period_order", "load_period_order"),
        ("instrumentation_enabled", "instrumentation_enabled"),
    )
    mismatches = [
        result_field
        for result_field, row_field in exact_fields
        if result.get(result_field) != row.get(row_field)
    ]
    for field_name in ("temperature", "coupling_j"):
        try:
            if float(result[field_name]).hex() != float(row[field_name]).hex():
                mismatches.append(field_name)
        except (KeyError, TypeError, ValueError):
            mismatches.append(field_name)
    if result.get("burn_in_in_measurement") is not False:
        mismatches.append("burn_in_in_measurement")
    if result.get("chain_seed_hash") != hash_json(
        {"chain_seed": int(row["chain_seed"])}
    ):
        mismatches.append("chain_seed_hash")
    if result.get("manifest_row_hash") != hash_json(dict(row)):
        mismatches.append("manifest_row_hash")
    if result.get("resource_profile_contract_hash") != hash_json(
        row["resource_profile_contract"]
    ):
        mismatches.append("resource_profile_contract_hash")
    if mismatches:
        raise ValueError(
            "Ising result does not bind to its exact manifest row: "
            f"{sorted(set(mismatches))}"
        )


def execute_ising_case(
    row: Mapping[str, Any],
    *,
    monotonic_ns: Callable[[], int] = time.monotonic_ns,
    process_time_ns: Callable[[], int] = time.process_time_ns,
) -> dict[str, Any]:
    """Execute one already-profiled case using the shared stop-policy runner."""

    _validate_case_row(row)
    adapter = IsingSearchAdapter()
    budget_mode = str(row["budget_mode"])
    if budget_mode == "fixed_sweeps":
        stop = FixedWorkStop(int(row["requested_sweeps"]))
    else:
        stop = WallClockStop(int(row["requested_budget_ns"]), monotonic_ns)
    context = CaseContext(
        case_id=str(row["case_id"]),
        block_id=str(row["chain_id"]),
        decision_index=0,
        load_condition=str(row["load_condition"]),
        lifecycle="fresh",
        lifecycle_id=f"{row['case_id']}:fresh",
        process_instance_id=f"ising-pid-{os.getpid()}",
        sequence_index=0,
        load_batch_id=str(row["load_batch_id"]),
        agent_seed=int(row["chain_seed"]),
        instrumentation_enabled=bool(row["instrumentation_enabled"]),
    )
    state = {
        "lattice_size": int(row["lattice_size"]),
        "temperature": float(row["temperature"]),
        "coupling_j": float(row["coupling_j"]),
        "burn_in_sweeps": int(row["burn_in_sweeps"]),
    }
    decision = run_decision(
        adapter,
        state,
        stop,
        context,
        monotonic_ns=monotonic_ns,
        process_time_ns=process_time_ns,
    )
    lattice = getattr(adapter, "lattice", None)
    measurement_start_attempts = int(
        getattr(adapter, "_measurement_start_attempts", 0)
    )
    measurement_start_sweeps = int(getattr(adapter, "_measurement_start_sweeps", 0))
    actual_sweeps = (
        int(lattice.completed_sweeps) - measurement_start_sweeps
        if lattice is not None
        else decision.completed_work_units
    )
    actual_attempts = (
        int(lattice.attempted_flips) - measurement_start_attempts
        if lattice is not None
        else actual_sweeps * int(row["lattice_size"]) ** 2
    )
    values = list(decision.value_estimates)
    result: dict[str, Any] = {
        "schema_version": ISING_RESULT_SCHEMA_VERSION,
        "case_id": str(row["case_id"]),
        "manifest_row_hash": hash_json(dict(row)),
        "chain_id": str(row["chain_id"]),
        "chain_seed_hash": hash_json({"chain_seed": int(row["chain_seed"])}),
        "temperature_index": int(row["temperature_index"]),
        "temperature": float(row["temperature"]),
        "lattice_size": int(row["lattice_size"]),
        "coupling_j": float(row["coupling_j"]),
        "burn_in_sweeps": int(row["burn_in_sweeps"]),
        "burn_in_in_measurement": False,
        "budget_mode": budget_mode,
        "requested_budget_ns": row.get("requested_budget_ns"),
        "requested_sweeps": row.get("requested_sweeps"),
        "completed_sweeps": actual_sweeps,
        "measurement_attempted_flips": actual_attempts,
        "accepted_flips_total": (
            int(lattice.accepted_flips) if lattice is not None else None
        ),
        "magnetization_per_spin": values[0] if len(values) >= 1 else None,
        "absolute_magnetization_per_spin": values[1] if len(values) >= 2 else None,
        "energy_per_spin": values[2] if len(values) >= 3 else None,
        "initial_state_hash": decision.state_hash,
        "final_state_hash": lattice.state_hash() if lattice is not None else None,
        "load_condition": str(row["load_condition"]),
        "load_batch_id": str(row["load_batch_id"]),
        "load_seed": int(row["load_seed"]),
        "load_period_order": str(row["load_period_order"]),
        "resource_profile_contract_hash": hash_json(
            row["resource_profile_contract"]
        ),
        "instrumentation_enabled": bool(row["instrumentation_enabled"]),
        "worker_pid": decision.worker_pid,
        "search_wall_ns": decision.search_wall_ns,
        "process_cpu_ns": decision.process_cpu_ns,
        "overshoot_ns": decision.overshoot_ns,
        "cleanup_succeeded": decision.cleanup_succeeded,
        "terminal_status": decision.terminal_status,
        "error_type": decision.error_type,
        "error_message": decision.error_message,
        "decision_record": decision.to_dict(),
    }
    validate_ising_case_result(result)
    return result


class ResourceProfileHook(Protocol):
    """Integration point owned by the existing resource controller/acquirer."""

    def __call__(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...


def build_resource_profile_request(row: Mapping[str, Any]) -> dict[str, Any]:
    """Return a spawn-safe request; this function never starts load itself."""

    _validate_case_row(row)
    return {
        "schema_version": RESOURCE_PROFILE_CONTRACT_VERSION,
        "entrypoint": ISING_EXECUTION_ENTRYPOINT,
        "payload": dict(row),
        "profile": dict(row["resource_profile_contract"]),
    }


def execute_with_resource_profile(
    row: Mapping[str, Any], hook: ResourceProfileHook
) -> dict[str, Any]:
    """Delegate load/affinity/process control without duplicating it here."""

    result = dict(hook(build_resource_profile_request(row)))
    validate_ising_case_result(result)
    return result


def build_instrumentation_case_rows(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Materialize the frozen on/off fixed-work instrumentation panel."""

    validate_ising_manifest(manifest)
    phase = str(manifest["config"]["phase"])
    master_seed = int(manifest["config"]["master_seed"])
    rows: list[dict[str, Any]] = []
    for plan in manifest["design"]["instrumentation_plan"]["pairs"]:
        enabled_order = (
            (False, True)
            if plan["execution_order"] == "off_then_on"
            else (True, False)
        )
        load_batch_id = f"{plan['pair_id']}-idle-profile"
        load_seed = derive_u32(
            master_seed, "ising_instrumentation_load", plan["pair_id"]
        )
        for position, enabled in enumerate(enabled_order):
            identity = {
                "phase": phase,
                "pair_id": plan["pair_id"],
                "instrumentation_enabled": enabled,
            }
            rows.append(
                {
                    "schema_version": ISING_ROW_SCHEMA_VERSION,
                    "case_id": _case_id(identity),
                    "phase": phase,
                    "chain_id": str(plan["pair_id"]),
                    "chain_seed": int(plan["chain_seed"]),
                    "temperature_index": int(plan["temperature_index"]),
                    "temperature": float(plan["temperature"]),
                    "lattice_size": int(plan["lattice_size"]),
                    "coupling_j": float(plan["coupling_j"]),
                    "burn_in_sweeps": int(plan["burn_in_sweeps"]),
                    "burn_in_in_measurement": False,
                    "work_unit": "one_random_scan_sweep_L_squared_attempts",
                    "budget_mode": "fixed_sweeps",
                    "requested_budget_ns": None,
                    "requested_sweeps": int(plan["requested_sweeps"]),
                    "load_condition": "idle",
                    "load_batch_id": load_batch_id,
                    "load_seed": load_seed,
                    "load_period_order": "idle_then_loaded",
                    "instrumentation_enabled": bool(enabled),
                    "resource_profile_contract": {
                        "schema_version": RESOURCE_PROFILE_CONTRACT_VERSION,
                        "condition": "idle",
                        "load_batch_id": load_batch_id,
                        "load_seed": load_seed,
                        "requires_external_controller": True,
                    },
                    "execution_index": len(rows),
                    "instrumentation_pair_id": str(plan["pair_id"]),
                    "pair_plan_hash": str(plan["plan_row_hash"]),
                    "execution_position": position,
                }
            )
    return rows


def instrumentation_result_record(
    row: Mapping[str, Any], result: Mapping[str, Any]
) -> dict[str, Any]:
    """Reduce a full acquired result to the frozen paired overhead record."""

    validate_ising_case_result_against_row(result, row)
    if result.get("terminal_status") != "ok":
        raise ValueError("instrumentation result is not terminally successful")
    record: dict[str, Any] = {
        "schema_version": "ising-instrumentation-result-1.0.0",
        "pair_id": str(row["instrumentation_pair_id"]),
        "pair_plan_hash": str(row["pair_plan_hash"]),
        "case_id": str(row["case_id"]),
        "execution_position": int(row["execution_position"]),
        "instrumentation_enabled": bool(row["instrumentation_enabled"]),
        "budget_mode": "fixed_sweeps",
        "requested_sweeps": int(row["requested_sweeps"]),
        "completed_sweeps": int(result["completed_sweeps"]),
        "temperature_index": int(row["temperature_index"]),
        "temperature": float(row["temperature"]),
        "lattice_size": int(row["lattice_size"]),
        "coupling_j": float(row["coupling_j"]),
        "burn_in_sweeps": int(row["burn_in_sweeps"]),
        "chain_seed_hash": str(result["chain_seed_hash"]),
        "search_wall_ns": int(result["search_wall_ns"]),
        "scientific_fingerprint": fixed_work_replay_fingerprint(result),
        "source_result_artifact_sha256": result.get("artifact_sha256"),
    }
    record["record_hash"] = hash_json(record)
    return record


def fixed_work_replay_fingerprint(result: Mapping[str, Any]) -> str:
    """Hash scientific state only, excluding clocks, PID, and load metadata."""

    if result.get("budget_mode") != "fixed_sweeps":
        raise ValueError("clean-process replay is designated for fixed sweeps")
    validate_ising_case_result(result)
    return hash_json(
        {
            "chain_id": result["chain_id"],
            "chain_seed_hash": result["chain_seed_hash"],
            "temperature": result["temperature"],
            "lattice_size": result["lattice_size"],
            "coupling_j": result["coupling_j"],
            "burn_in_sweeps": result["burn_in_sweeps"],
            "completed_sweeps": result["completed_sweeps"],
            "measurement_attempted_flips": result["measurement_attempted_flips"],
            "magnetization_per_spin": result["magnetization_per_spin"],
            "absolute_magnetization_per_spin": result[
                "absolute_magnetization_per_spin"
            ],
            "energy_per_spin": result["energy_per_spin"],
            "initial_state_hash": result["initial_state_hash"],
            "final_state_hash": result["final_state_hash"],
            "terminal_status": result["terminal_status"],
        }
    )


def run_clean_process_replay(
    row: Mapping[str, Any],
    *,
    repeats: int = 2,
    python_executable: str | Path = sys.executable,
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    """Replay a fixed-work row in clean interpreters with varied hash seeds."""

    _validate_case_row(row)
    if row.get("budget_mode") != "fixed_sweeps":
        raise ValueError("clean-process replay requires a fixed-sweeps row")
    if repeats < 2:
        raise ValueError("clean-process replay requires at least two interpreters")
    root = Path(__file__).resolve().parents[1]
    fingerprints: list[str] = []
    output_hashes: list[str] = []
    for index in range(repeats):
        environment = dict(os.environ)
        environment["PYTHONHASHSEED"] = str(index + 1)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        current_path = environment.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = (
            str(root) if not current_path else f"{root}{os.pathsep}{current_path}"
        )
        completed = subprocess.run(
            [
                str(python_executable),
                "-B",
                "-m",
                "resource_envelope_study.ising_experiment",
                "--execute-row-stdin",
            ],
            cwd=root,
            env=environment,
            input=canonical_json_bytes(dict(row)),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"clean Ising subprocess {index} failed: "
                f"{completed.stderr.decode('utf-8', errors='replace').strip()}"
            )
        result = json.loads(completed.stdout)
        output_hashes.append(hash_json(result))
        fingerprints.append(fixed_work_replay_fingerprint(result))
    report: dict[str, Any] = {
        "schema_version": ISING_REPLAY_SCHEMA_VERSION,
        "case_id": str(row["case_id"]),
        "manifest_row_hash": hash_json(dict(row)),
        "repeats": repeats,
        "python_executable": str(Path(python_executable).resolve()),
        "python_hash_seeds": list(range(1, repeats + 1)),
        "scientific_fingerprints": fingerprints,
        "raw_output_hashes": output_hashes,
        "passed": len(set(fingerprints)) == 1,
    }
    report["report_hash"] = hash_json(report)
    return report


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute-row-stdin",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)
    if not args.execute_row_stdin:
        parser.error("this module exposes only the internal spawn execution entrypoint")
    row = json.loads(sys.stdin.buffer.read())
    sys.stdout.buffer.write(canonical_json_bytes(execute_ising_case(row)))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through clean subprocesses
    raise SystemExit(_main())
