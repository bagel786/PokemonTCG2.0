"""Frozen pilot-based power calculations at the matched-block level."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from statistics import NormalDist
from typing import Any, Mapping

import numpy as np

from .canonical import hash_json
from .scheduler import ScheduleConfig, build_schedule


POWER_VERSION = "clustered-scheduler-power-1.0.0"
CONFIRMATORY_FAMILY_SIZE = 10


@dataclass(frozen=True)
class BinaryPairedPowerInputs:
    sesoi: float = 0.10
    two_sided_alpha: float = 0.05
    target_power: float = 0.80
    paired_disagreement_probability: float = 0.50
    cluster_design_effect: float = 1.0
    minimum_load_batches: int = 20
    target_blocks_per_cell_low: int = 200
    target_blocks_per_cell_high: int = 300

    def validate(self) -> None:
        if not 0 < self.sesoi < 1:
            raise ValueError("sesoi must lie between zero and one")
        if not 0 < self.two_sided_alpha < 0.5:
            raise ValueError("alpha must lie between zero and 0.5")
        if not 0.5 < self.target_power < 1:
            raise ValueError("target_power must lie between 0.5 and one")
        if not self.sesoi <= self.paired_disagreement_probability <= 1:
            raise ValueError("paired disagreement must be at least |paired mean difference|")
        if self.cluster_design_effect < 1:
            raise ValueError("cluster design effect cannot be below one")
        if self.minimum_load_batches < 20:
            raise ValueError("at least 20 independent load batches are required")


def paired_binary_block_requirement(inputs: BinaryPairedPowerInputs) -> dict[str, Any]:
    """Normal approximation for D=Y_loaded-Y_idle in {-1,0,1}.

    ``E[D^2]`` is the paired disagreement probability, so
    ``Var(D)=q-delta^2``.  The pilot must supply q and a cluster design effect;
    repeats/actions are never substituted for blocks.
    """

    inputs.validate()
    normal = NormalDist()
    z_alpha = normal.inv_cdf(1.0 - inputs.two_sided_alpha / 2.0)
    z_power = normal.inv_cdf(inputs.target_power)
    variance = inputs.paired_disagreement_probability - inputs.sesoi**2
    independent = math.ceil((z_alpha + z_power) ** 2 * variance / inputs.sesoi**2)
    clustered = math.ceil(independent * inputs.cluster_design_effect)
    rounded_for_four_strata = int(math.ceil(clustered / 4.0) * 4)
    if rounded_for_four_strata < inputs.target_blocks_per_cell_low:
        disposition = "GO_TARGET_LOW"
    elif rounded_for_four_strata <= inputs.target_blocks_per_cell_high:
        disposition = "GO_WITHIN_TARGET"
    else:
        disposition = "NARROW_OR_EXTEND"
    result = {
        "schema_version": "paired-binary-power-1.0.0",
        "inputs": asdict(inputs),
        "variance_of_paired_difference": variance,
        "independent_block_requirement": independent,
        "cluster_adjusted_block_requirement": clustered,
        "recommended_blocks_per_cell": rounded_for_four_strata,
        "minimum_load_batches": inputs.minimum_load_batches,
        "disposition": disposition,
        "method": "two-sided normal approximation for paired binary difference; pilot-frozen q and design effect",
    }
    result["content_hash"] = hash_json(result)
    return result


@dataclass(frozen=True)
class ClusteredSchedulerPowerInputs:
    """Pilot-frozen planning inputs for the equal-agent paired score endpoint."""

    agents: tuple[str, ...]
    paired_disagreement_by_agent: dict[str, float]
    candidate_block_counts: tuple[int, ...]
    master_seed: int = 2026082606
    paired_load_batches: int = 20
    persistent_sequence_length: int = 8
    minimum_retained_load_batches: int = 20
    sesoi: float = 0.10
    familywise_alpha: float = 0.05
    confirmatory_family_size: int = CONFIRMATORY_FAMILY_SIZE
    target_power: float = 0.80
    batch_icc: float = 0.05
    session_icc: float = 0.05
    load_batch_attrition_probability: float = 0.0
    session_attrition_probability: float = 0.0
    block_attrition_probability: float = 0.0
    seconds_per_case: float = 1.0
    seconds_per_load_batch: float = 30.0
    seconds_per_persistent_session: float = 2.0
    total_runtime_budget_hours: float = 120.0
    analysis_reserve_hours: float = 24.0
    simulation_replicates: int = 2_000

    def validate(self) -> None:
        if len(self.agents) != 3 or len(set(self.agents)) != 3:
            raise ValueError("power simulation requires exactly three unique agents")
        if set(self.paired_disagreement_by_agent) != set(self.agents):
            raise ValueError("pilot disagreement must name every and only agent")
        if not math.isclose(self.sesoi, 0.10, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("the prospective score SESOI is frozen to 10 percentage points")
        if self.confirmatory_family_size != CONFIRMATORY_FAMILY_SIZE:
            raise ValueError("power multiplicity must cover the exact ten-estimand family")
        if not 0.0 < self.familywise_alpha < 0.5:
            raise ValueError("familywise alpha must lie between zero and 0.5")
        if not 0.5 < self.target_power < 1.0:
            raise ValueError("target power must lie between 0.5 and one")
        if self.paired_load_batches < 20 or self.minimum_retained_load_batches < 20:
            raise ValueError("power planning requires at least 20 retained load batches")
        if self.minimum_retained_load_batches > self.paired_load_batches:
            raise ValueError("retained load-batch minimum exceeds scheduled batches")
        if self.persistent_sequence_length < 2:
            raise ValueError("persistent sequence length must be at least two")
        if not self.candidate_block_counts:
            raise ValueError("power simulation requires candidate block counts")
        if tuple(sorted(set(self.candidate_block_counts))) != self.candidate_block_counts:
            raise ValueError("candidate block counts must be sorted and unique")
        for count in self.candidate_block_counts:
            if (
                isinstance(count, bool)
                or not isinstance(count, int)
                or count < 4 * self.paired_load_batches
                or count % 4
            ):
                raise ValueError(
                    "candidate blocks must be multiples of four and provide four strata per batch"
                )
        for agent_id, probability in self.paired_disagreement_by_agent.items():
            if not self.sesoi <= probability <= 1.0:
                raise ValueError(
                    f"pilot disagreement for {agent_id} must be in [SESOI, 1]"
                )
        if (
            not 0.0 <= self.batch_icc < 1.0
            or not 0.0 <= self.session_icc < 1.0
            or self.batch_icc + self.session_icc >= 1.0
        ):
            raise ValueError("batch/session ICCs must be nonnegative and sum below one")
        for name in (
            "load_batch_attrition_probability",
            "session_attrition_probability",
            "block_attrition_probability",
        ):
            value = float(getattr(self, name))
            if not 0.0 <= value < 1.0:
                raise ValueError(f"{name} must lie in [0, 1)")
        for name in (
            "seconds_per_case",
            "seconds_per_load_batch",
            "seconds_per_persistent_session",
            "total_runtime_budget_hours",
            "analysis_reserve_hours",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and nonnegative")
        if self.analysis_reserve_hours >= self.total_runtime_budget_hours:
            raise ValueError("analysis reserve consumes the complete runtime budget")
        if self.simulation_replicates < 100:
            raise ValueError("clustered power simulation requires at least 100 replicates")

    @property
    def content_hash(self) -> str:
        self.validate()
        return hash_json({"power_version": POWER_VERSION, **asdict(self)})


def _dummy_artifact_hashes() -> dict[str, str]:
    return {
        key: f"{index:x}" * 64
        for index, key in enumerate(
            (
                "engine_binary",
                "engine_source",
                "hero_deck",
                "hero_model",
                "opponent_deck",
                "opponent_model",
                "run_config",
            ),
            1,
        )
    }


def _power_schedule(
    inputs: ClusteredSchedulerPowerInputs, block_count: int
) -> dict[str, Any]:
    return build_schedule(
        ScheduleConfig(
            phase="final",
            master_seed=inputs.master_seed,
            agents=inputs.agents,
            block_count=block_count,
            paired_load_batches=inputs.paired_load_batches,
            minimum_persistent_sessions=20,
            persistent_sequence_length=inputs.persistent_sequence_length,
            wall_clock_budget_ns=1,
            fixed_work_by_agent={agent_id: 1 for agent_id in inputs.agents},
            artifact_hashes=_dummy_artifact_hashes(),
        )
    )


def _schedule_block_layout(manifest: Mapping[str, Any]) -> list[dict[str, str]]:
    first_agent = str(manifest["config"]["agents"][0])
    rows = [
        row
        for row in manifest["rows"]
        if row["agent_id"] == first_agent
        and row["budget_mode"] == "wall_clock"
        and row["load_condition"] == "idle"
        and row["lifecycle"] == "fresh"
    ]
    layout = [
        {
            "block_id": str(row["block_id"]),
            "load_batch_id": str(row["load_batch_id"]),
            "session_bundle_id": str(row["session_bundle_id"]),
        }
        for row in sorted(rows, key=lambda value: int(value["block_index"]))
    ]
    if len(layout) != int(manifest["config"]["block_count"]):
        raise RuntimeError("power schedule block layout does not reconcile")
    return layout


def _cluster_robust_standard_error(
    values: np.ndarray,
    batches: Sequence[str],
) -> float:
    if len(values) != len(batches) or not len(values):
        raise ValueError("cluster standard error received malformed values")
    batch_ids = sorted(set(batches))
    if len(batch_ids) < 2:
        return math.inf
    point = float(np.mean(values))
    influences = np.asarray(
        [
            float(np.sum(values[[index for index, batch in enumerate(batches) if batch == key]] - point))
            for key in batch_ids
        ],
        dtype=np.float64,
    )
    variance = (
        len(batch_ids)
        / (len(batch_ids) - 1.0)
        * float(np.sum(influences**2))
        / float(len(values) ** 2)
    )
    return math.sqrt(max(0.0, variance))


def _wilson_interval(successes: int, trials: int) -> list[float]:
    if trials <= 0:
        raise ValueError("Wilson interval requires trials")
    z = NormalDist().inv_cdf(0.975)
    p = successes / trials
    denominator = 1.0 + z * z / trials
    center = (p + z * z / (2.0 * trials)) / denominator
    radius = (
        z
        * math.sqrt(p * (1.0 - p) / trials + z * z / (4.0 * trials * trials))
        / denominator
    )
    return [max(0.0, center - radius), min(1.0, center + radius)]


def _simulate_candidate(
    inputs: ClusteredSchedulerPowerInputs,
    manifest: Mapping[str, Any],
    *,
    candidate_index: int,
) -> dict[str, Any]:
    layout = _schedule_block_layout(manifest)
    rng = np.random.default_rng(inputs.master_seed + 10_000 * (candidate_index + 1))
    normal = NormalDist()
    thresholds = {}
    for agent_id in inputs.agents:
        disagreement = inputs.paired_disagreement_by_agent[agent_id]
        probability_negative = (disagreement - inputs.sesoi) / 2.0
        probability_zero_or_negative = 1.0 - (
            disagreement + inputs.sesoi
        ) / 2.0
        thresholds[agent_id] = (
            normal.inv_cdf(probability_negative)
            if probability_negative > 0.0
            else -math.inf,
            normal.inv_cdf(probability_zero_or_negative)
            if probability_zero_or_negative < 1.0
            else math.inf,
        )
    member_alpha = inputs.familywise_alpha / inputs.confirmatory_family_size
    critical = normal.inv_cdf(1.0 - member_alpha / 2.0)
    detections = 0
    valid_replicates = 0
    retained_batch_counts: list[int] = []
    retained_block_counts: list[int] = []
    batch_ids = sorted({row["load_batch_id"] for row in layout})
    bundle_ids = sorted({row["session_bundle_id"] for row in layout})
    residual_scale = math.sqrt(1.0 - inputs.batch_icc - inputs.session_icc)
    for _ in range(inputs.simulation_replicates):
        kept_batches = {
            key
            for key in batch_ids
            if rng.random() >= inputs.load_batch_attrition_probability
        }
        kept_bundles = {
            key
            for key in bundle_ids
            if rng.random() >= inputs.session_attrition_probability
        }
        kept_rows = [
            row
            for row in layout
            if row["load_batch_id"] in kept_batches
            and row["session_bundle_id"] in kept_bundles
            and rng.random() >= inputs.block_attrition_probability
        ]
        retained_batches = sorted({row["load_batch_id"] for row in kept_rows})
        retained_batch_counts.append(len(retained_batches))
        retained_block_counts.append(len(kept_rows))
        if (
            len(retained_batches) < inputs.minimum_retained_load_batches
            or not kept_rows
        ):
            continue
        valid_replicates += 1
        batch_effects = {key: rng.normal() for key in retained_batches}
        active_bundles = {row["session_bundle_id"] for row in kept_rows}
        session_effects = {key: rng.normal() for key in active_bundles}
        block_values: list[float] = []
        block_batches: list[str] = []
        for row in kept_rows:
            agent_values: list[float] = []
            for agent_id in inputs.agents:
                latent = (
                    math.sqrt(inputs.batch_icc)
                    * batch_effects[row["load_batch_id"]]
                    + math.sqrt(inputs.session_icc)
                    * session_effects[row["session_bundle_id"]]
                    + residual_scale * rng.normal()
                )
                lower, upper = thresholds[agent_id]
                agent_values.append(-1.0 if latent < lower else (0.0 if latent < upper else 1.0))
            block_values.append(float(np.mean(agent_values)))
            block_batches.append(row["load_batch_id"])
        values = np.asarray(block_values, dtype=np.float64)
        estimate = float(np.mean(values))
        standard_error = _cluster_robust_standard_error(values, block_batches)
        if math.isfinite(standard_error) and (
            (standard_error == 0.0 and estimate > 0.0)
            or (standard_error > 0.0 and estimate - critical * standard_error > 0.0)
        ):
            detections += 1

    rows = list(manifest["rows"])
    persistent_sessions = len(
        {
            row["process_instance_id"]
            for row in rows
            if row["lifecycle"] == "persistent"
        }
    )
    usable_fraction = (
        (1.0 - inputs.load_batch_attrition_probability)
        * (1.0 - inputs.session_attrition_probability)
        * (1.0 - inputs.block_attrition_probability)
    )
    base_runtime_seconds = (
        len(rows) * inputs.seconds_per_case
        + inputs.paired_load_batches * inputs.seconds_per_load_batch
        + persistent_sessions * inputs.seconds_per_persistent_session
    )
    projected_runtime_hours = base_runtime_seconds / usable_fraction / 3600.0
    available_hours = inputs.total_runtime_budget_hours - inputs.analysis_reserve_hours
    power = detections / inputs.simulation_replicates
    power_interval = _wilson_interval(detections, inputs.simulation_replicates)
    runtime_feasible = projected_runtime_hours <= available_hours
    meets_score_endpoint = power_interval[0] >= inputs.target_power and runtime_feasible
    return {
        "block_count": int(manifest["config"]["block_count"]),
        "schedule_content_hash": manifest["content_hash"],
        "scheduled_case_count": len(rows),
        "persistent_session_count": persistent_sessions,
        "detections": detections,
        "simulation_replicates": inputs.simulation_replicates,
        "valid_replicates": valid_replicates,
        "unconditional_power": power,
        "power_monte_carlo_95_interval": power_interval,
        "median_retained_load_batches": float(np.median(retained_batch_counts)),
        "median_retained_blocks": float(np.median(retained_block_counts)),
        "projected_runtime_hours_including_expected_replacement": projected_runtime_hours,
        "available_acquisition_hours_after_analysis_reserve": available_hours,
        "runtime_feasible": runtime_feasible,
        "meets_score_endpoint_power_and_runtime": meets_score_endpoint,
        # This simulation has no pilot-frozen joint distributions for the
        # other nine retained endpoints, so it can never authorize the locked
        # ten-member family.
        "meets_power_and_runtime": False,
    }


def simulate_clustered_scheduler_power(
    inputs: ClusteredSchedulerPowerInputs,
) -> dict[str, Any]:
    """Simulate planning power through the exact frozen assignment hierarchy.

    This powers only the equal-agent paired **score** effect. Work ratios, action
    divergence, attenuation, and equivalence-at-zero need their own pilot-frozen
    joint distributions and are explicitly not declared powered by this result.
    """

    inputs.validate()
    candidates = []
    for candidate_index, block_count in enumerate(inputs.candidate_block_counts):
        candidates.append(
            _simulate_candidate(
                inputs,
                _power_schedule(inputs, block_count),
                candidate_index=candidate_index,
            )
        )
    score_passing = [
        candidate
        for candidate in candidates
        if candidate["meets_score_endpoint_power_and_runtime"]
    ]
    score_candidate = score_passing[0]["block_count"] if score_passing else None
    payload: dict[str, Any] = {
        "schema_version": "clustered-scheduler-power-1.0.0",
        "power_version": POWER_VERSION,
        "input_lock_hash": inputs.content_hash,
        "inputs": asdict(inputs),
        "powered_estimand": "equal_agent_paired_score_load_effect_at_10pp",
        "inference_unit": "complete_matched_block",
        "assignment_hierarchy": "load_batch_to_common_session_bundle_to_complete_block",
        "multiplicity_method": "bonferroni_over_10_confirmatory_estimands",
        "two_sided_member_alpha": inputs.familywise_alpha
        / inputs.confirmatory_family_size,
        "planning_test": "load-batch-cluster-robust normal interval",
        "attrition_handling": "batch/session/block attrition drops complete vectors and counts as power failure when retained-batch gate fails",
        "candidates": candidates,
        "score_endpoint_candidate_blocks_per_cell": score_candidate,
        "recommended_blocks_per_cell": None,
        "full_confirmatory_family_power_established": False,
        "freeze_authorized": False,
        "disposition": "NARROW_OR_EXTEND",
        "not_powered_by_this_artifact": [
            "wall_work_ratio",
            "score_attenuation_difference_in_differences",
            "state_level_action_excess_divergence",
            "equivalence_at_true_zero",
            "rank_reversal",
        ],
        "limitation": (
            "The listed estimands cannot be declared adequately powered until "
            "their pilot-frozen joint distributions and cluster structure are supplied. "
            "This artifact therefore prohibits freezing the ten-endpoint family even "
            "when the score endpoint alone meets its target."
        ),
    }
    payload["content_hash"] = hash_json(payload)
    return payload
