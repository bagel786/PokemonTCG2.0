"""Locked, block-level analysis for the resource-envelope study.

The functions in this module never treat decisions, repeats, or schedule rows
as independent observations.  Main-game contrasts are formed within complete
seed/seat/order blocks; uncertainty resamples paired load batch, then common
session bundle, then block.  Frozen-state divergence is reduced to one value
per independently sourced state before aggregation.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict, dataclass
from itertools import combinations, product
import json
import math
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np

from .canonical import canonical_json_bytes, hash_file, hash_json, write_canonical_json


ANALYSIS_VERSION = "resource-envelope-analysis-1.2.0"
CONFIRMATORY_ESTIMAND_IDS = tuple(
    f"{estimand}_{lifecycle}_equal_agent"
    for lifecycle in ("fresh", "persistent")
    for estimand in (
        "wall_work_ratio",
        "wall_score_load_effect",
        "fixed_score_load_effect",
        "score_attenuation",
        "wall_action_excess_divergence",
    )
)
REQUIRED_ANALYSIS_SOURCE_ROLES = frozenset(
    {
        "final_schedule",
        "main_outcome_hash_manifest",
        "repeatability_outcome_hash_manifest",
        "protocol_freeze",
        "analysis_code",
    }
)
MAIN_RESULT_FIELDS = frozenset(
    {
        "schedule_row",
        "game",
        "decisions",
        "gameplay_decisions",
        "public_trace_sha256",
        "observed_worker",
        "artifact_sha256",
    }
)
SCHEDULE_ROW_FIELDS = frozenset(
    {
        "schema_version",
        "phase",
        "case_id",
        "block_id",
        "block_index",
        "agent_id",
        "budget_mode",
        "load_condition",
        "lifecycle",
        "physical_seat",
        "play_order",
        "environment_seed",
        "agent_seed",
        "schedule_seed",
        "load_seed",
        "load_batch_id",
        "load_period_order",
        "lifecycle_pair_id",
        "sequence_pair_id",
        "session_bundle_id",
        "lifecycle_id",
        "process_instance_id",
        "sequence_index",
        "execution_index",
        "requested_budget_ns",
        "requested_work_units",
    }
)
GAME_FIELDS = frozenset(
    {
        "schema_version",
        "case_id",
        "block_id",
        "agent_id",
        "score",
        "winner",
        "terminal_status",
        "decision_count",
        "completed_work_units",
        "completed_simulations",
        "completed_nodes",
        "completed_sweeps",
        "forward_model_calls",
        "decision_record_hashes",
        "error_type",
        "error_message",
    }
)
DECISION_FIELDS = frozenset(
    {
        "schema_version",
        "case_id",
        "block_id",
        "decision_index",
        "agent_id",
        "budget_mode",
        "load_condition",
        "lifecycle",
        "lifecycle_id",
        "process_instance_id",
        "worker_pid",
        "sequence_index",
        "load_batch_id",
        "requested_budget_ns",
        "requested_work_units",
        "completed_work_units",
        "completed_simulations",
        "completed_nodes",
        "completed_sweeps",
        "forward_model_calls",
        "setup_wall_ns",
        "search_wall_ns",
        "selection_wall_ns",
        "cleanup_wall_ns",
        "process_cpu_ns",
        "overshoot_ns",
        "state_hash",
        "agent_seed_hash",
        "selected_action",
        "selected_action_hash",
        "value_estimates",
        "timeout_reason",
        "fallback_reason",
        "cleanup_succeeded",
        "instrumentation_enabled",
        "work_counters_collected",
        "terminal_status",
        "error_type",
        "error_message",
        "extra",
    }
)
REPEATABILITY_RESULT_FIELDS = frozenset(
    {
        "schema_version",
        "case_id",
        "manifest_content_hash",
        "schedule_row",
        "state_artifact_sha256",
        "history_prefix_sha256",
        "budget_mode",
        "requested_budget_ns",
        "requested_work_units",
        "terminal_status",
        "eligible",
        "completed_work_units",
        "completed_simulations",
        "completed_nodes",
        "forward_model_calls",
        "search_wall_ns",
        "overshoot_ns",
        "state_hash",
        "selected_action_hash",
        "cleanup_succeeded",
        "warmup_steps_completed",
        "warmup_consumed_sha256",
        "warmup_replay_sha256",
        "observed_worker",
        "artifact_sha256",
    }
)
REPEATABILITY_ROW_FIELDS = frozenset(
    {
        "schema_version",
        "repeatability_case_id",
        "bank_id",
        "inference_unit_id",
        "state_id",
        "source_game_id",
        "state_artifact_sha256",
        "state_seed",
        "history_prefix_sha256",
        "history_seed",
        "history_length",
        "pseudo_sequence_slot",
        "sequence_index",
        "agent_id",
        "agent_seed",
        "envelope_id",
        "resource_profile_sha256",
        "load_condition",
        "lifecycle",
        "budget_mode",
        "requested_budget_ns",
        "requested_work_units",
        "repeat_index",
        "session_id",
        "process_instance_id",
        "session_seed",
        "schedule_seed",
        "load_batch_id",
        "load_seed",
        "load_period_order",
        "execution_index",
    }
)


@dataclass(frozen=True)
class AnalysisLock:
    bootstrap_seed: int = 2026082604
    bootstrap_replicates: int = 9_999
    confidence_level: float = 0.95
    score_equivalence_margin: float = 0.05
    work_relative_equivalence_margin: float = 0.10
    action_divergence_margin: float = 0.05
    rank_tie_margin: float = 0.05
    simultaneous_method: str = "bonferroni_over_10_confirmatory_estimands"

    def validate(self) -> None:
        if self.bootstrap_replicates < 1_999:
            raise ValueError("confirmatory bootstrap requires at least 1,999 replicates")
        if not 0.5 < self.confidence_level < 1.0:
            raise ValueError("confidence_level must lie between 0.5 and 1")
        for name in (
            "score_equivalence_margin",
            "work_relative_equivalence_margin",
            "action_divergence_margin",
            "rank_tie_margin",
        ):
            if not 0 < float(getattr(self, name)) < 1:
                raise ValueError(f"{name} must lie strictly between zero and one")
        if self.simultaneous_method != "bonferroni_over_10_confirmatory_estimands":
            raise ValueError("the confirmatory simultaneous method is frozen to Bonferroni")

    @property
    def content_hash(self) -> str:
        self.validate()
        return hash_json(
            {
                "analysis_version": ANALYSIS_VERSION,
                "confirmatory_estimand_ids": list(CONFIRMATORY_ESTIMAND_IDS),
                **asdict(self),
            }
        )

    @property
    def confirmatory_member_confidence_level(self) -> float:
        """Bonferroni member confidence yielding familywise coverage."""

        self.validate()
        return 1.0 - (1.0 - self.confidence_level) / len(
            CONFIRMATORY_ESTIMAND_IDS
        )


@dataclass(frozen=True)
class BlockContrast:
    load_batch_id: str
    session_bundle_id: str
    block_id: str
    value: float


@dataclass(frozen=True)
class BlockPair:
    load_batch_id: str
    session_bundle_id: str
    block_id: str
    idle: float
    loaded: float
    idle_eligible_decisions: int
    loaded_eligible_decisions: int


@dataclass(frozen=True)
class ClusteredBlockVector:
    """One complete block carrying every endpoint/component in a joint resample."""

    load_batch_id: str
    session_bundle_id: str
    block_id: str
    values: dict[str, float]


def _mean(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("cannot average an empty sequence")
    return float(sum(values) / len(values))


def _case_metric(case: Mapping[str, Any], metric: str) -> float:
    _validate_case_schema(case)
    game = case["game"]
    status = game.get("terminal_status")
    if status in {"engine_error", "infrastructure_error", "protocol_invalid"}:
        raise ValueError(
            f"case {game.get('case_id')} is scientifically invalid: {status}"
        )
    if metric == "score":
        score = game.get("score")
        if score is None:
            raise ValueError(f"assigned case {game.get('case_id')} lacks an ITT score")
        value = float(score)
        if value not in {0.0, 0.5, 1.0}:
            raise ValueError(f"case {game.get('case_id')} has an invalid score")
        return value
    if metric == "mean_decision_work":
        decisions = list(case.get("decisions", ()))
        # The prospective outcome is a block-equal per-game mean.  A valid
        # game can end before the study agent receives an eligible search
        # decision; that game remains in its matched block and contributes 0.
        if not decisions:
            return 0.0
        # A block-equal per-game mean avoids weighting long games more heavily.
        return _mean([float(row["completed_work_units"]) for row in decisions])
    if metric == "total_work":
        value = game.get("completed_work_units")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"case {game.get('case_id')} has invalid total work")
        # A valid game with zero eligible search decisions contributes zero.
        return float(value)
    raise ValueError(f"unsupported metric: {metric}")


def _validate_case_schema(case: Mapping[str, Any]) -> None:
    """Reject analysis-facing telemetry schema drift before reading outcomes."""

    if not isinstance(case, Mapping):
        raise ValueError("analysis case must be an object")
    if set(case) != MAIN_RESULT_FIELDS:
        raise ValueError("analysis main result top-level schema drift")
    row = case.get("schedule_row")
    game = case.get("game")
    decisions = case.get("decisions")
    if not isinstance(row, Mapping) or not isinstance(game, Mapping):
        raise ValueError("analysis case lacks schedule_row or game object")
    if set(row) != SCHEDULE_ROW_FIELDS:
        raise ValueError("analysis schedule-row fields differ from the locked schema")
    if set(game) != GAME_FIELDS:
        raise ValueError("analysis game fields differ from the locked schema")
    if not isinstance(decisions, (list, tuple)):
        raise ValueError("analysis case decisions must be an array")
    if row.get("schema_version") != "schedule-row-1.0.0":
        raise ValueError("analysis refuses unexpected schedule-row schema")
    if game.get("schema_version") != "game-1.0.0":
        raise ValueError("analysis refuses unexpected game outcome schema")
    for field, allowed in (
        ("budget_mode", {"wall_clock", "fixed_work"}),
        ("load_condition", {"idle", "loaded"}),
        ("lifecycle", {"fresh", "persistent"}),
    ):
        if row.get(field) not in allowed:
            raise ValueError(f"analysis schedule row has invalid {field}")
    required_schedule_fields = {
        "case_id",
        "block_id",
        "agent_id",
        "environment_seed",
        "physical_seat",
        "play_order",
        "load_batch_id",
        "session_bundle_id",
        "sequence_index",
    }
    if any(field not in row for field in required_schedule_fields):
        raise ValueError("analysis schedule row lacks a required matching field")
    if row.get("case_id") != game.get("case_id"):
        raise ValueError("analysis case identity differs between schedule and game")
    if row.get("block_id") != game.get("block_id"):
        raise ValueError("analysis block identity differs between schedule and game")
    if row.get("agent_id") != game.get("agent_id"):
        raise ValueError("analysis agent identity differs between schedule and game")
    game_statuses = {
        "completed",
        "agent_timeout",
        "agent_error",
        "illegal_action",
        "engine_error",
        "infrastructure_error",
        "protocol_invalid",
    }
    if game.get("terminal_status") not in game_statuses:
        raise ValueError("analysis game has an unknown terminal status")
    decision_count = game.get("decision_count")
    if (
        isinstance(decision_count, bool)
        or not isinstance(decision_count, int)
        or decision_count < 0
        or decision_count != len(decisions)
    ):
        raise ValueError("analysis game decision count does not reconcile")
    game_work = game.get("completed_work_units")
    if isinstance(game_work, bool) or not isinstance(game_work, int) or game_work < 0:
        raise ValueError("analysis game has invalid completed work")
    decision_work_total = 0
    decision_statuses = {
        "ok",
        "deadline_no_work",
        "search_error",
        "cleanup_error",
        "fixed_work_invalid",
        "illegal_action",
        "infrastructure_error",
    }
    for decision in decisions:
        if not isinstance(decision, Mapping):
            raise ValueError("analysis decision is not an object")
        if set(decision) != DECISION_FIELDS:
            raise ValueError("analysis decision fields differ from the locked schema")
        if decision.get("schema_version") != "decision-1.1.0":
            raise ValueError("analysis refuses unexpected decision outcome schema")
        if (
            decision.get("case_id") != row.get("case_id")
            or decision.get("block_id") != row.get("block_id")
            or decision.get("agent_id") != row.get("agent_id")
        ):
            raise ValueError("analysis decision identity differs from its schedule row")
        if decision.get("terminal_status") not in decision_statuses:
            raise ValueError("analysis decision has an unknown terminal status")
        decision_work = decision.get("completed_work_units")
        if (
            isinstance(decision_work, bool)
            or not isinstance(decision_work, int)
            or decision_work < 0
        ):
            raise ValueError("analysis decision has invalid completed work")
        decision_work_total += decision_work
    if decision_work_total != game_work:
        raise ValueError("analysis game work total does not reconcile with decisions")
    supplied_artifact_hash = case.get("artifact_sha256")
    artifact_payload = dict(case)
    artifact_payload.pop("artifact_sha256", None)
    if not _is_sha256(supplied_artifact_hash) or supplied_artifact_hash != hash_json(
        artifact_payload
    ):
        raise ValueError("analysis main result artifact hash mismatch")


def _eligible_decision_count(case: Mapping[str, Any]) -> int:
    _validate_case_schema(case)
    return len(case["decisions"])


def _indexed_cases(cases: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str, str, str, str], Mapping[str, Any]]:
    indexed: dict[tuple[str, str, str, str, str], Mapping[str, Any]] = {}
    for case in cases:
        _validate_case_schema(case)
        row = case["schedule_row"]
        key = (
            str(row["block_id"]),
            str(row["agent_id"]),
            str(row["budget_mode"]),
            str(row["load_condition"]),
            str(row["lifecycle"]),
        )
        if key in indexed:
            raise ValueError(f"duplicate factorial case: {key}")
        indexed[key] = case
    return indexed


def paired_load_pairs(
    cases: Iterable[Mapping[str, Any]],
    *,
    agent_id: str,
    budget_mode: str,
    lifecycle: str,
    metric: str,
    expected_block_ids: Iterable[str] | None = None,
) -> list[BlockPair]:
    """Return idle/loaded values without converting a ratio into block ratios."""

    indexed = _indexed_cases(cases)
    observed_block_ids = {
        key[0]
        for key in indexed
        if key[1] == agent_id and key[2] == budget_mode and key[4] == lifecycle
    }
    if expected_block_ids is not None:
        expected = set(map(str, expected_block_ids))
        if observed_block_ids != expected:
            raise ValueError(
                "analysis block inventory differs from the frozen schedule: "
                f"missing={sorted(expected - observed_block_ids)[:5]}, "
                f"unexpected={sorted(observed_block_ids - expected)[:5]}"
            )
    pairs: list[BlockPair] = []
    for block_id in sorted(observed_block_ids):
        idle_key = (block_id, agent_id, budget_mode, "idle", lifecycle)
        loaded_key = (block_id, agent_id, budget_mode, "loaded", lifecycle)
        if idle_key not in indexed or loaded_key not in indexed:
            raise ValueError(f"block {block_id} lacks a paired load observation")
        idle = indexed[idle_key]
        loaded = indexed[loaded_key]
        idle_row = idle["schedule_row"]
        loaded_row = loaded["schedule_row"]
        for field in (
            "environment_seed",
            "physical_seat",
            "play_order",
            "load_batch_id",
            "session_bundle_id",
            "sequence_index",
        ):
            if idle_row[field] != loaded_row[field]:
                raise ValueError(f"block {block_id} is unmatched on {field}")
        pairs.append(
            BlockPair(
                load_batch_id=str(idle_row["load_batch_id"]),
                session_bundle_id=str(idle_row["session_bundle_id"]),
                block_id=block_id,
                idle=_case_metric(idle, metric),
                loaded=_case_metric(loaded, metric),
                idle_eligible_decisions=_eligible_decision_count(idle),
                loaded_eligible_decisions=_eligible_decision_count(loaded),
            )
        )
    if not pairs:
        raise ValueError("no complete paired load observations")
    return pairs


def paired_load_contrasts(
    cases: Iterable[Mapping[str, Any]],
    *,
    agent_id: str,
    budget_mode: str,
    lifecycle: str,
    metric: str,
    expected_block_ids: Iterable[str] | None = None,
) -> list[BlockContrast]:
    """Return loaded-minus-idle values, one per complete matched block."""

    return [
        BlockContrast(
            load_batch_id=pair.load_batch_id,
            session_bundle_id=pair.session_bundle_id,
            block_id=pair.block_id,
            value=pair.loaded - pair.idle,
        )
        for pair in paired_load_pairs(
            cases,
            agent_id=agent_id,
            budget_mode=budget_mode,
            lifecycle=lifecycle,
            metric=metric,
            expected_block_ids=expected_block_ids,
        )
    ]


def ratio_of_means(pairs: Sequence[BlockPair]) -> float:
    """Return mean(loaded)/mean(idle)-1, never the mean of block ratios."""

    if not pairs:
        raise ValueError("ratio of means requires complete block pairs")
    denominator = _mean([pair.idle for pair in pairs])
    if denominator <= 0.0:
        raise ValueError("wall-work ratio denominator is not strictly positive")
    return _mean([pair.loaded for pair in pairs]) / denominator - 1.0


def equal_agent_wall_work_ratio(
    cases: Iterable[Mapping[str, Any]],
    *,
    agents: Sequence[str],
    lifecycle: str,
    expected_block_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Equal-weight agent ratios using per-game mean completed work.

    Work units are algorithm-specific.  The implementation first computes one
    ratio of means per agent and then averages those dimensionless ratios.  It
    never pools raw work counts across agents.  A valid zero-decision game has
    per-game mean zero and remains in the primary ratio.  The complete-pair
    nonzero-only calculation is reported as sensitivity, never substituted.
    """

    if len(agents) < 2 or len(set(agents)) != len(agents):
        raise ValueError("equal-agent work aggregation requires unique agents")
    materialized = list(cases)
    pairs_by_agent = {
        agent_id: paired_load_pairs(
            materialized,
            agent_id=agent_id,
            budget_mode="wall_clock",
            lifecycle=lifecycle,
            metric="mean_decision_work",
            expected_block_ids=expected_block_ids,
        )
        for agent_id in agents
    }
    reference = pairs_by_agent[agents[0]]
    reference_clusters = {
        pair.block_id: (pair.load_batch_id, pair.session_bundle_id)
        for pair in reference
    }
    for agent_id, pairs in pairs_by_agent.items():
        clusters = {
            pair.block_id: (pair.load_batch_id, pair.session_bundle_id)
            for pair in pairs
        }
        if clusters != reference_clusters:
            raise ValueError(
                f"agent {agent_id} work inventory is not the same complete block hierarchy"
            )
    per_agent = {
        agent_id: ratio_of_means(pairs_by_agent[agent_id])
        for agent_id in agents
    }
    sensitivity_pairs = {
        agent_id: [
            pair
            for pair in pairs_by_agent[agent_id]
            if pair.idle_eligible_decisions > 0
            and pair.loaded_eligible_decisions > 0
        ]
        for agent_id in agents
    }
    sensitivity_ratios: dict[str, float | None] = {}
    for agent_id in agents:
        pairs = sensitivity_pairs[agent_id]
        sensitivity_ratios[agent_id] = ratio_of_means(pairs) if pairs else None
    zero_game_count = sum(
        int(pair.idle_eligible_decisions == 0)
        + int(pair.loaded_eligible_decisions == 0)
        for pairs in pairs_by_agent.values()
        for pair in pairs
    )
    wall_game_count = 2 * len(reference) * len(agents)
    return {
        "estimand": "equal-agent mean of agent-specific wall-work ratios of means",
        "work_outcome": "per_game_mean_completed_work_per_eligible_decision_zero_if_none",
        "estimate": _mean([per_agent[agent_id] for agent_id in agents]),
        "per_agent_ratios": per_agent,
        "zero_decision_sensitivity": {
            "method": "exclude complete load pairs if either game has zero eligible decisions",
            "per_agent_ratios": sensitivity_ratios,
            "equal_agent_estimate": (
                _mean([float(sensitivity_ratios[agent_id]) for agent_id in agents])
                if all(sensitivity_ratios[agent_id] is not None for agent_id in agents)
                else None
            ),
            "complete_pair_count_by_agent": {
                agent_id: len(sensitivity_pairs[agent_id]) for agent_id in agents
            },
        },
        "agent_count": len(agents),
        "block_count": len(reference),
        "load_batch_count": len({pair.load_batch_id for pair in reference}),
        "wall_game_count": wall_game_count,
        "zero_eligible_decision_game_count": zero_game_count,
        "zero_eligible_decision_game_rate": zero_game_count / wall_game_count,
        "raw_work_counts_pooled_across_agents": False,
    }


def budget_sensitivity_interaction(
    cases: Iterable[Mapping[str, Any]],
    *,
    agent_id: str,
    lifecycle: str,
    metric: str,
) -> list[BlockContrast]:
    """Return (wall loaded-idle) - (fixed loaded-idle), by block."""

    materialized = list(cases)
    wall = {
        row.block_id: row
        for row in paired_load_contrasts(
            materialized,
            agent_id=agent_id,
            budget_mode="wall_clock",
            lifecycle=lifecycle,
            metric=metric,
        )
    }
    fixed = {
        row.block_id: row
        for row in paired_load_contrasts(
            materialized,
            agent_id=agent_id,
            budget_mode="fixed_work",
            lifecycle=lifecycle,
            metric=metric,
        )
    }
    if set(wall) != set(fixed):
        raise ValueError("wall-clock and fixed-work block inventories differ")
    return [
        BlockContrast(
            load_batch_id=wall[block_id].load_batch_id,
            session_bundle_id=wall[block_id].session_bundle_id,
            block_id=block_id,
            value=wall[block_id].value - fixed[block_id].value,
        )
        for block_id in sorted(wall)
    ]


def hierarchical_cluster_bootstrap(
    observations: Sequence[BlockContrast],
    lock: AnalysisLock,
    *,
    statistic: Callable[[Sequence[float]], float] = _mean,
) -> dict[str, Any]:
    """Resample batch -> common session bundle -> complete block vector."""

    lock.validate()
    if not observations:
        raise ValueError("bootstrap requires observations")
    by_batch: dict[str, dict[str, list[BlockContrast]]] = defaultdict(lambda: defaultdict(list))
    seen_blocks: set[str] = set()
    for row in observations:
        if row.block_id in seen_blocks:
            raise ValueError(f"block {row.block_id} appears more than once")
        seen_blocks.add(row.block_id)
        by_batch[row.load_batch_id][row.session_bundle_id].append(row)
    if len(by_batch) < 2:
        raise ValueError("cluster bootstrap requires at least two load batches")
    rng = np.random.default_rng(lock.bootstrap_seed)
    batch_ids = sorted(by_batch)
    draws = np.empty(lock.bootstrap_replicates, dtype=np.float64)
    for replicate in range(lock.bootstrap_replicates):
        sampled_values: list[float] = []
        for sampled_batch_index in rng.integers(0, len(batch_ids), size=len(batch_ids)):
            bundles = by_batch[batch_ids[int(sampled_batch_index)]]
            bundle_ids = sorted(bundles)
            for sampled_bundle_index in rng.integers(0, len(bundle_ids), size=len(bundle_ids)):
                block_rows = bundles[bundle_ids[int(sampled_bundle_index)]]
                for sampled_block_index in rng.integers(0, len(block_rows), size=len(block_rows)):
                    sampled_values.append(block_rows[int(sampled_block_index)].value)
        draws[replicate] = statistic(sampled_values)
    alpha = 1.0 - lock.confirmatory_member_confidence_level
    point = statistic([row.value for row in observations])
    return {
        "estimate": float(point),
        "confidence_level": lock.confirmatory_member_confidence_level,
        "multiplicity_method": lock.simultaneous_method,
        "interval": [
            float(np.quantile(draws, alpha / 2.0)),
            float(np.quantile(draws, 1.0 - alpha / 2.0)),
        ],
        "bootstrap_replicates": lock.bootstrap_replicates,
        "bootstrap_seed": lock.bootstrap_seed,
        "load_batch_count": len(by_batch),
        "session_bundle_count": sum(len(value) for value in by_batch.values()),
        "block_count": len(observations),
    }


def _validate_clustered_vectors(
    observations: Sequence[ClusteredBlockVector],
) -> tuple[tuple[str, ...], dict[str, dict[str, list[ClusteredBlockVector]]]]:
    if not observations:
        raise ValueError("joint resampling requires complete block vectors")
    endpoint_ids = tuple(sorted(observations[0].values))
    if not endpoint_ids:
        raise ValueError("clustered block vector has no endpoints")
    by_batch: dict[str, dict[str, list[ClusteredBlockVector]]] = defaultdict(
        lambda: defaultdict(list)
    )
    seen_blocks: set[str] = set()
    bundle_owner: dict[str, str] = {}
    for row in observations:
        if row.block_id in seen_blocks:
            raise ValueError(f"block {row.block_id} appears more than once")
        seen_blocks.add(row.block_id)
        if tuple(sorted(row.values)) != endpoint_ids:
            raise ValueError("joint resampling block vectors have incomplete endpoint keys")
        if any(not math.isfinite(float(value)) for value in row.values.values()):
            raise ValueError("joint resampling values must be finite")
        prior_batch = bundle_owner.setdefault(row.session_bundle_id, row.load_batch_id)
        if prior_batch != row.load_batch_id:
            raise ValueError("a session bundle crosses load batches")
        by_batch[row.load_batch_id][row.session_bundle_id].append(row)
    if len(by_batch) < 2:
        raise ValueError("joint cluster bootstrap requires at least two load batches")
    return endpoint_ids, by_batch


def _vector_means(rows: Sequence[ClusteredBlockVector]) -> dict[str, float]:
    if not rows:
        raise ValueError("cannot estimate an empty block-vector sample")
    endpoint_ids = tuple(sorted(rows[0].values))
    return {
        endpoint_id: _mean([float(row.values[endpoint_id]) for row in rows])
        for endpoint_id in endpoint_ids
    }


def common_resample_max_t_intervals(
    observations: Sequence[ClusteredBlockVector],
    lock: AnalysisLock,
    *,
    statistic: Callable[[Sequence[ClusteredBlockVector]], Mapping[str, float]] = _vector_means,
    statistic_name: str = "componentwise_block_mean",
) -> dict[str, Any]:
    """Common batch -> session -> block bootstrap with max-T intervals.

    Every endpoint is recomputed from the same hierarchical resample.  A custom
    statistic can therefore recompute nonlinear estimands such as ratios of
    means from resampled numerator/denominator components.
    """

    lock.validate()
    component_ids, by_batch = _validate_clustered_vectors(observations)
    point_mapping = dict(statistic(observations))
    endpoint_ids = tuple(sorted(point_mapping))
    if not endpoint_ids:
        raise ValueError("joint statistic returned no endpoints")
    point = np.asarray([float(point_mapping[key]) for key in endpoint_ids])
    if not np.all(np.isfinite(point)):
        raise ValueError("joint statistic returned a non-finite point estimate")

    rng = np.random.default_rng(lock.bootstrap_seed)
    batch_ids = sorted(by_batch)
    draws = np.empty((lock.bootstrap_replicates, len(endpoint_ids)), dtype=np.float64)
    for replicate in range(lock.bootstrap_replicates):
        sample: list[ClusteredBlockVector] = []
        for sampled_batch_index in rng.integers(0, len(batch_ids), size=len(batch_ids)):
            bundles = by_batch[batch_ids[int(sampled_batch_index)]]
            bundle_ids = sorted(bundles)
            for sampled_bundle_index in rng.integers(
                0, len(bundle_ids), size=len(bundle_ids)
            ):
                block_rows = bundles[bundle_ids[int(sampled_bundle_index)]]
                for sampled_block_index in rng.integers(
                    0, len(block_rows), size=len(block_rows)
                ):
                    sample.append(block_rows[int(sampled_block_index)])
        estimate = dict(statistic(sample))
        if tuple(sorted(estimate)) != endpoint_ids:
            raise ValueError("joint statistic changed endpoint keys during resampling")
        draws[replicate] = [float(estimate[key]) for key in endpoint_ids]
    if not np.all(np.isfinite(draws)):
        raise ValueError("joint statistic produced non-finite bootstrap draws")

    standard_errors = np.std(draws, axis=0, ddof=1)
    standardized = np.zeros_like(draws)
    nondegenerate = standard_errors > 0.0
    standardized[:, nondegenerate] = np.abs(
        (draws[:, nondegenerate] - point[nondegenerate])
        / standard_errors[nondegenerate]
    )
    max_t = np.max(standardized, axis=1)
    critical = float(np.quantile(max_t, lock.confidence_level))
    intervals: dict[str, Any] = {}
    for index, endpoint_id in enumerate(endpoint_ids):
        radius = critical * float(standard_errors[index])
        intervals[endpoint_id] = {
            "estimate": float(point[index]),
            "standard_error": float(standard_errors[index]),
            "interval": [float(point[index] - radius), float(point[index] + radius)],
        }
    payload: dict[str, Any] = {
        "schema_version": "simultaneous-intervals-1.0.0",
        "analysis_version": ANALYSIS_VERSION,
        "analysis_lock_hash": lock.content_hash,
        "simultaneous_method": "common_hierarchical_cluster_bootstrap_max_t",
        "familywise_confidence_level": lock.confidence_level,
        "statistic_name": statistic_name,
        "endpoint_ids": list(endpoint_ids),
        "critical_value": critical,
        "bootstrap_seed": lock.bootstrap_seed,
        "bootstrap_replicates": lock.bootstrap_replicates,
        "load_batch_count": len(by_batch),
        "session_bundle_count": sum(len(bundles) for bundles in by_batch.values()),
        "block_count": len(observations),
        "input_component_ids": list(component_ids),
        "input_block_vector_hash": hash_json([asdict(row) for row in observations]),
        "intervals": intervals,
    }
    payload["content_hash"] = hash_json(payload)
    return payload


def confirmatory_main_block_vectors(
    cases: Iterable[Mapping[str, Any]],
    *,
    agents: Sequence[str],
    expected_block_ids: Iterable[str] | None = None,
) -> list[ClusteredBlockVector]:
    """Create complete raw-component vectors for all eight main endpoints."""

    materialized = list(cases)
    observed_blocks, _ = _validate_main_factorial_inventory(
        materialized,
        agents=agents,
        expected_block_ids=expected_block_ids,
    )
    indexed = _indexed_cases(materialized)
    vectors: list[ClusteredBlockVector] = []
    for block_id in sorted(observed_blocks):
        reference = indexed[(block_id, str(agents[0]), "wall_clock", "idle", "fresh")]
        row = reference["schedule_row"]
        values: dict[str, float] = {}
        for lifecycle, agent_id in product(("fresh", "persistent"), agents):
            for load_condition in ("idle", "loaded"):
                values[
                    f"work:{lifecycle}:{agent_id}:{load_condition}"
                ] = _case_metric(
                    indexed[
                        (
                            block_id,
                            str(agent_id),
                            "wall_clock",
                            load_condition,
                            lifecycle,
                        )
                    ],
                    "mean_decision_work",
                )
            for budget_mode, load_condition in product(
                ("wall_clock", "fixed_work"), ("idle", "loaded")
            ):
                values[
                    f"score:{lifecycle}:{agent_id}:{budget_mode}:{load_condition}"
                ] = _case_metric(
                    indexed[
                        (
                            block_id,
                            str(agent_id),
                            budget_mode,
                            load_condition,
                            lifecycle,
                        )
                    ],
                    "score",
                )
        vectors.append(
            ClusteredBlockVector(
                load_batch_id=str(row["load_batch_id"]),
                session_bundle_id=str(row["session_bundle_id"]),
                block_id=block_id,
                values=values,
            )
        )
    return vectors


def confirmatory_main_statistic(
    rows: Sequence[ClusteredBlockVector],
    *,
    agents: Sequence[str],
) -> dict[str, float]:
    """Recompute nonlinear work ratios and score effects from a block sample."""

    if not rows:
        raise ValueError("confirmatory main statistic has no complete block vectors")
    results: dict[str, float] = {}
    for lifecycle in ("fresh", "persistent"):
        work_ratios: list[float] = []
        wall_effects: list[float] = []
        fixed_effects: list[float] = []
        for agent_id in agents:
            idle_work = _mean(
                [row.values[f"work:{lifecycle}:{agent_id}:idle"] for row in rows]
            )
            if idle_work <= 0.0:
                raise ValueError(
                    "a hierarchical resample has a nonpositive wall-work denominator"
                )
            loaded_work = _mean(
                [row.values[f"work:{lifecycle}:{agent_id}:loaded"] for row in rows]
            )
            work_ratios.append(loaded_work / idle_work - 1.0)
            budget_effects: dict[str, float] = {}
            for budget_mode in ("wall_clock", "fixed_work"):
                budget_effects[budget_mode] = _mean(
                    [
                        row.values[
                            f"score:{lifecycle}:{agent_id}:{budget_mode}:loaded"
                        ]
                        - row.values[
                            f"score:{lifecycle}:{agent_id}:{budget_mode}:idle"
                        ]
                        for row in rows
                    ]
                )
            wall_effects.append(budget_effects["wall_clock"])
            fixed_effects.append(budget_effects["fixed_work"])
        results[f"wall_work_ratio_{lifecycle}_equal_agent"] = _mean(work_ratios)
        results[f"wall_score_load_effect_{lifecycle}_equal_agent"] = _mean(
            wall_effects
        )
        results[f"fixed_score_load_effect_{lifecycle}_equal_agent"] = _mean(
            fixed_effects
        )
        results[f"score_attenuation_{lifecycle}_equal_agent"] = _mean(
            [wall - fixed for wall, fixed in zip(wall_effects, fixed_effects)]
        )
    return results


def common_resample_bonferroni_intervals(
    observations: Sequence[ClusteredBlockVector],
    lock: AnalysisLock,
    *,
    statistic: Callable[[Sequence[ClusteredBlockVector]], Mapping[str, float]],
    statistic_name: str,
) -> dict[str, Any]:
    """Common hierarchical resamples with ten-family Bonferroni intervals.

    The main-game and frozen-state outcomes do not share an inference-unit
    population, so a single max-T resample over all ten is not defensible.
    Each member instead receives a 99.5% interval.  The eight main endpoints
    are still recomputed together from every common batch/session/block draw;
    the two state endpoints use the separately defined state bootstrap.
    """

    lock.validate()
    component_ids, by_batch = _validate_clustered_vectors(observations)
    point_mapping = dict(statistic(observations))
    endpoint_ids = tuple(sorted(point_mapping))
    if not endpoint_ids:
        raise ValueError("confirmatory statistic returned no endpoints")
    point = {key: float(point_mapping[key]) for key in endpoint_ids}
    if any(not math.isfinite(value) for value in point.values()):
        raise ValueError("confirmatory statistic returned a non-finite estimate")
    rng = np.random.default_rng(lock.bootstrap_seed)
    batch_ids = sorted(by_batch)
    draws = np.empty((lock.bootstrap_replicates, len(endpoint_ids)), dtype=np.float64)
    for replicate in range(lock.bootstrap_replicates):
        sample: list[ClusteredBlockVector] = []
        for sampled_batch_index in rng.integers(0, len(batch_ids), size=len(batch_ids)):
            bundles = by_batch[batch_ids[int(sampled_batch_index)]]
            bundle_ids = sorted(bundles)
            for sampled_bundle_index in rng.integers(
                0, len(bundle_ids), size=len(bundle_ids)
            ):
                block_rows = bundles[bundle_ids[int(sampled_bundle_index)]]
                for sampled_block_index in rng.integers(
                    0, len(block_rows), size=len(block_rows)
                ):
                    sample.append(block_rows[int(sampled_block_index)])
        estimate = dict(statistic(sample))
        if tuple(sorted(estimate)) != endpoint_ids:
            raise ValueError("confirmatory statistic changed endpoints during resampling")
        draws[replicate] = [float(estimate[key]) for key in endpoint_ids]
    if not np.all(np.isfinite(draws)):
        raise ValueError("confirmatory statistic produced non-finite resamples")
    alpha = 1.0 - lock.confirmatory_member_confidence_level
    intervals = {
        endpoint_id: {
            "estimate": point[endpoint_id],
            "interval": [
                float(np.quantile(draws[:, index], alpha / 2.0)),
                float(np.quantile(draws[:, index], 1.0 - alpha / 2.0)),
            ],
        }
        for index, endpoint_id in enumerate(endpoint_ids)
    }
    payload: dict[str, Any] = {
        "schema_version": "simultaneous-intervals-1.0.0",
        "analysis_version": ANALYSIS_VERSION,
        "analysis_lock_hash": lock.content_hash,
        "simultaneous_method": lock.simultaneous_method,
        "familywise_confidence_level": lock.confidence_level,
        "member_confidence_level": lock.confirmatory_member_confidence_level,
        "confirmatory_family_size": len(CONFIRMATORY_ESTIMAND_IDS),
        "statistic_name": statistic_name,
        "endpoint_ids": list(endpoint_ids),
        "bootstrap_seed": lock.bootstrap_seed,
        "bootstrap_replicates": lock.bootstrap_replicates,
        "load_batch_count": len(by_batch),
        "session_bundle_count": sum(len(bundles) for bundles in by_batch.values()),
        "block_count": len(observations),
        "input_component_ids": list(component_ids),
        "input_block_vector_hash": hash_json([asdict(row) for row in observations]),
        "intervals": intervals,
    }
    payload["content_hash"] = hash_json(payload)
    return payload


def verify_simultaneous_interval_result(result: Mapping[str, Any]) -> None:
    supplied = result.get("content_hash")
    payload = dict(result)
    payload.pop("content_hash", None)
    if supplied != hash_json(payload):
        raise ValueError("simultaneous interval content hash mismatch")
    if result.get("schema_version") != "simultaneous-intervals-1.0.0":
        raise ValueError("unsupported simultaneous interval schema")
    if result.get("simultaneous_method") not in {
        "common_hierarchical_cluster_bootstrap_max_t",
        "bonferroni_over_10_confirmatory_estimands",
    }:
        raise ValueError("rank inference requires a frozen simultaneous method")
    endpoint_ids = list(result.get("endpoint_ids", ()))
    intervals = result.get("intervals")
    if not isinstance(intervals, Mapping) or set(endpoint_ids) != set(intervals):
        raise ValueError("simultaneous interval endpoint inventory does not reconcile")


def rank_reversal_from_joint_intervals(
    simultaneous_result: Mapping[str, Any],
    *,
    comparisons: Mapping[str, tuple[str, str]],
    tie_margin: float,
) -> dict[str, Any]:
    """Admit reversal only when two jointly covered contrasts clear ±margin."""

    verify_simultaneous_interval_result(simultaneous_result)
    if not 0.0 < tie_margin < 1.0:
        raise ValueError("rank tie margin must lie strictly between zero and one")
    intervals = simultaneous_result["intervals"]
    decisions: dict[str, Any] = {}
    for comparison_id, endpoint_pair in sorted(comparisons.items()):
        if len(endpoint_pair) != 2 or any(key not in intervals for key in endpoint_pair):
            raise ValueError(f"rank comparison {comparison_id} references unknown endpoints")
        first = list(intervals[endpoint_pair[0]]["interval"])
        second = list(intervals[endpoint_pair[1]]["interval"])
        if (
            len(first) != 2
            or len(second) != 2
            or first[0] > first[1]
            or second[0] > second[1]
        ):
            raise ValueError("rank comparison interval is malformed")
        first_positive_second_negative = (
            float(first[0]) > tie_margin and float(second[1]) < -tie_margin
        )
        first_negative_second_positive = (
            float(first[1]) < -tie_margin and float(second[0]) > tie_margin
        )
        decisions[comparison_id] = {
            "endpoint_ids": list(endpoint_pair),
            "rank_reversal": bool(
                first_positive_second_negative or first_negative_second_positive
            ),
            "first_interval": [float(first[0]), float(first[1])],
            "second_interval": [float(second[0]), float(second[1])],
        }
    return {
        "joint_interval_content_hash": simultaneous_result["content_hash"],
        "tie_margin": tie_margin,
        "comparisons": decisions,
    }


def restricted_sign_flip_sensitivity(
    observations: Sequence[BlockContrast], *, permutations: int = 65_535, seed: int = 2026082605
) -> dict[str, float | int]:
    """Batch-level paired sign-flip sensitivity; descriptive, not a replacement CI."""

    by_batch: dict[str, list[float]] = defaultdict(list)
    for row in observations:
        by_batch[row.load_batch_id].append(row.value)
    batch_means = np.asarray([_mean(by_batch[key]) for key in sorted(by_batch)], dtype=np.float64)
    if len(batch_means) < 2:
        raise ValueError("sign-flip sensitivity requires at least two paired batches")
    observed = abs(float(np.mean(batch_means)))
    rng = np.random.default_rng(seed)
    extreme = 1
    for _ in range(permutations):
        signs = rng.choice(np.asarray((-1.0, 1.0)), size=len(batch_means))
        extreme += abs(float(np.mean(batch_means * signs))) >= observed
    return {
        "absolute_batch_mean": observed,
        "two_sided_randomization_p": extreme / float(permutations + 1),
        "permutations": permutations,
        "batch_count": len(batch_means),
    }


def within_envelope_disagreement(action_hashes: Sequence[str]) -> float:
    if len(action_hashes) < 2:
        raise ValueError("within-envelope disagreement requires at least two repeats")
    pairs = list(combinations(action_hashes, 2))
    return _mean([float(left != right) for left, right in pairs])


def cross_envelope_disagreement(left: Sequence[str], right: Sequence[str]) -> float:
    if not left or not right:
        raise ValueError("cross-envelope disagreement requires both repeat sets")
    return _mean([float(a != b) for a in left for b in right])


def _validated_repeatability_result(result: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the frozen manifest row bound into one usable panel result."""

    if not isinstance(result, Mapping):
        raise ValueError("repeatability result must be an object")
    if set(result) != REPEATABILITY_RESULT_FIELDS:
        raise ValueError("analysis repeatability result fields differ from locked schema")
    if result.get("schema_version") != "state-panel-result-1.0.0":
        raise ValueError("analysis refuses unexpected repeatability result schema")
    row = result.get("schedule_row")
    if not isinstance(row, Mapping) or row.get("schema_version") != "repeatability-row-1.0.0":
        raise ValueError("analysis refuses unexpected repeatability schedule schema")
    if set(row) != REPEATABILITY_ROW_FIELDS:
        raise ValueError("analysis repeatability row fields differ from locked schema")
    if result.get("case_id") != row.get("repeatability_case_id"):
        raise ValueError("repeatability result identity differs from its frozen row")
    if result.get("terminal_status") not in {"ok", "deadline_no_work"}:
        raise ValueError("repeatability result is not a successful terminal execution")
    if result.get("eligible") is not True or result.get("cleanup_succeeded") is not True:
        raise ValueError("repeatability result is ineligible or cleanup failed")
    if result.get("state_artifact_sha256") != row.get("state_artifact_sha256"):
        raise ValueError("repeatability result consumed a different state artifact")
    action_hash = result.get("selected_action_hash")
    if (
        not isinstance(action_hash, str)
        or len(action_hash) != 64
        or any(character not in "0123456789abcdef" for character in action_hash)
    ):
        raise ValueError("repeatability result has an invalid selected-action hash")
    supplied_artifact_hash = result.get("artifact_sha256")
    artifact_payload = dict(result)
    artifact_payload.pop("artifact_sha256", None)
    if not _is_sha256(supplied_artifact_hash) or supplied_artifact_hash != hash_json(
        artifact_payload
    ):
        raise ValueError("repeatability result artifact hash mismatch")
    return row


def _repeatability_envelope_id(
    repeat_rows: Sequence[Mapping[str, Any]],
    *,
    budget_mode: str,
    load_condition: str,
    lifecycle: str,
) -> str:
    envelope_ids = {
        str(row["envelope_id"])
        for result in repeat_rows
        for row in (_validated_repeatability_result(result),)
        if row.get("budget_mode") == budget_mode
        and row.get("load_condition") == load_condition
        and row.get("lifecycle") == lifecycle
    }
    if len(envelope_ids) != 1:
        raise ValueError(
            "repeatability panel does not identify exactly one requested envelope cell"
        )
    return next(iter(envelope_ids))


def state_level_divergence(
    repeat_rows: Iterable[Mapping[str, Any]], *, left_envelope: str, right_envelope: str
) -> list[dict[str, Any]]:
    """Reduce 10x10 comparisons to one U-statistic vector per source state."""

    grouped: dict[tuple[str, str], dict[str, dict[int, str]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    source_games: dict[str, str] = {}
    state_by_source_game: dict[str, str] = {}
    for result in repeat_rows:
        row = _validated_repeatability_result(result)
        state_id = str(row["state_id"])
        source_game_id = str(row["source_game_id"])
        if state_id in source_games and source_games[state_id] != source_game_id:
            raise ValueError(f"state {state_id} has inconsistent source games")
        source_games[state_id] = source_game_id
        prior_state = state_by_source_game.setdefault(source_game_id, state_id)
        if prior_state != state_id:
            raise ValueError("repeatability inference has multiple states from one source game")
        repeat_index = row.get("repeat_index")
        if (
            isinstance(repeat_index, bool)
            or not isinstance(repeat_index, int)
            or not 0 <= repeat_index < 10
        ):
            raise ValueError("repeatability result has an invalid repeat index")
        envelope_id = str(row["envelope_id"])
        repeats = grouped[(state_id, str(row["agent_id"]))][envelope_id]
        if repeat_index in repeats:
            raise ValueError(
                f"duplicate repeat index for {state_id}/{row['agent_id']}/{envelope_id}"
            )
        repeats[repeat_index] = str(result["selected_action_hash"])
    agents_by_state: dict[str, set[str]] = defaultdict(set)
    for state_id, agent_id in grouped:
        agents_by_state[state_id].add(agent_id)
    agent_inventories = {tuple(sorted(values)) for values in agents_by_state.values()}
    if len(agent_inventories) != 1:
        raise ValueError("repeatability states do not share the same complete agent inventory")
    results: list[dict[str, Any]] = []
    for (state_id, agent_id), envelopes in sorted(grouped.items()):
        left_by_repeat = envelopes.get(left_envelope, {})
        right_by_repeat = envelopes.get(right_envelope, {})
        if set(left_by_repeat) != set(range(10)) or set(right_by_repeat) != set(
            range(10)
        ):
            raise ValueError(f"state {state_id}/{agent_id} does not have 10 repeats per envelope")
        left = [left_by_repeat[index] for index in range(10)]
        right = [right_by_repeat[index] for index in range(10)]
        within_left = within_envelope_disagreement(left)
        within_right = within_envelope_disagreement(right)
        cross = cross_envelope_disagreement(left, right)
        results.append(
            {
                "state_id": state_id,
                "source_game_id": source_games[state_id],
                "agent_id": agent_id,
                "within_left": within_left,
                "within_right": within_right,
                "cross": cross,
                "excess_cross_divergence": cross - 0.5 * (within_left + within_right),
            }
        )
    if not results:
        raise ValueError("no state-level divergence observations")
    return results


def equal_agent_state_values(
    state_agent_rows: Iterable[Mapping[str, Any]],
    *,
    agents: Sequence[str],
    metric: str = "excess_cross_divergence",
) -> list[dict[str, Any]]:
    """Collapse agent values within state, leaving one independent state row."""

    if not agents or len(set(agents)) != len(agents):
        raise ValueError("state aggregation requires unique frozen agents")
    grouped: dict[str, dict[str, Mapping[str, Any]]] = defaultdict(dict)
    source_by_state: dict[str, str] = {}
    state_by_source: dict[str, str] = {}
    for row in state_agent_rows:
        state_id = str(row["state_id"])
        source_game_id = str(row["source_game_id"])
        agent_id = str(row["agent_id"])
        if agent_id not in agents:
            raise ValueError(f"unexpected repeatability agent: {agent_id}")
        if agent_id in grouped[state_id]:
            raise ValueError(f"duplicate state-agent divergence row: {state_id}/{agent_id}")
        grouped[state_id][agent_id] = row
        if source_by_state.setdefault(state_id, source_game_id) != source_game_id:
            raise ValueError("state has inconsistent source-game identity")
        if state_by_source.setdefault(source_game_id, state_id) != state_id:
            raise ValueError("multiple inference states came from one source game")
    results: list[dict[str, Any]] = []
    expected_agents = set(agents)
    for state_id, by_agent in sorted(grouped.items()):
        if set(by_agent) != expected_agents:
            raise ValueError(f"state {state_id} lacks the complete agent vector")
        values = [float(by_agent[agent_id][metric]) for agent_id in agents]
        if any(not math.isfinite(value) for value in values):
            raise ValueError("state-level divergence value is not finite")
        results.append(
            {
                "state_id": state_id,
                "source_game_id": source_by_state[state_id],
                "value": _mean(values),
                "agent_values": {
                    agent_id: float(by_agent[agent_id][metric]) for agent_id in agents
                },
            }
        )
    if not results:
        raise ValueError("no independent state observations")
    return results


def state_cluster_bootstrap(
    state_rows: Sequence[Mapping[str, Any]],
    lock: AnalysisLock,
) -> dict[str, Any]:
    """Bootstrap independently sourced states, never repeats or repeat pairs."""

    lock.validate()
    if not state_rows:
        raise ValueError("state bootstrap requires state-level rows")
    state_ids = [str(row["state_id"]) for row in state_rows]
    source_ids = [str(row["source_game_id"]) for row in state_rows]
    if len(state_ids) != len(set(state_ids)) or len(source_ids) != len(set(source_ids)):
        raise ValueError("state bootstrap requires one row per state and source game")
    values = np.asarray([float(row["value"]) for row in state_rows], dtype=np.float64)
    if not np.all(np.isfinite(values)):
        raise ValueError("state bootstrap values must be finite")
    rng = np.random.default_rng(lock.bootstrap_seed)
    draws = np.empty(lock.bootstrap_replicates, dtype=np.float64)
    for replicate in range(lock.bootstrap_replicates):
        indexes = rng.integers(0, len(values), size=len(values))
        draws[replicate] = float(np.mean(values[indexes]))
    alpha = 1.0 - lock.confirmatory_member_confidence_level
    return {
        "estimate": float(np.mean(values)),
        "interval": [
            float(np.quantile(draws, alpha / 2.0)),
            float(np.quantile(draws, 1.0 - alpha / 2.0)),
        ],
        "confidence_level": lock.confirmatory_member_confidence_level,
        "multiplicity_method": lock.simultaneous_method,
        "inference_unit": "frozen_state",
        "state_count": len(values),
        "repeat_rows_resampled": False,
        "bootstrap_replicates": lock.bootstrap_replicates,
        "bootstrap_seed": lock.bootstrap_seed,
    }


def repeatability_bonferroni_intervals(
    repeatability_results: Iterable[Mapping[str, Any]],
    lock: AnalysisLock,
    *,
    agents: Sequence[str],
) -> dict[str, Any]:
    """Build the two 99.5% state-level members of the ten-family intervals."""

    materialized = list(repeatability_results)
    inventory = _validate_repeatability_inventory(materialized, agents=agents)
    intervals: dict[str, Any] = {}
    state_inventory_hashes: dict[str, str] = {}
    for lifecycle in ("fresh", "persistent"):
        idle_envelope = _repeatability_envelope_id(
            materialized,
            budget_mode="wall_clock",
            load_condition="idle",
            lifecycle=lifecycle,
        )
        loaded_envelope = _repeatability_envelope_id(
            materialized,
            budget_mode="wall_clock",
            load_condition="loaded",
            lifecycle=lifecycle,
        )
        state_agent_rows = state_level_divergence(
            materialized,
            left_envelope=idle_envelope,
            right_envelope=loaded_envelope,
        )
        state_rows = equal_agent_state_values(state_agent_rows, agents=agents)
        result = state_cluster_bootstrap(state_rows, lock)
        endpoint_id = f"wall_action_excess_divergence_{lifecycle}_equal_agent"
        intervals[endpoint_id] = {
            "estimate": result["estimate"],
            "interval": result["interval"],
        }
        state_inventory_hashes[lifecycle] = hash_json(state_rows)
    payload: dict[str, Any] = {
        "schema_version": "simultaneous-intervals-1.0.0",
        "analysis_version": ANALYSIS_VERSION,
        "analysis_lock_hash": lock.content_hash,
        "simultaneous_method": lock.simultaneous_method,
        "familywise_confidence_level": lock.confidence_level,
        "member_confidence_level": lock.confirmatory_member_confidence_level,
        "confirmatory_family_size": len(CONFIRMATORY_ESTIMAND_IDS),
        "statistic_name": "equal_agent_state_mean_excess_cross_divergence",
        "inference_unit": "frozen_state",
        "endpoint_ids": sorted(intervals),
        "bootstrap_seed": lock.bootstrap_seed,
        "bootstrap_replicates": lock.bootstrap_replicates,
        "state_count": inventory["state_count"],
        "source_game_count": inventory["source_game_count"],
        "input_state_inventory_hashes": state_inventory_hashes,
        "intervals": {key: intervals[key] for key in sorted(intervals)},
    }
    payload["content_hash"] = hash_json(payload)
    return payload


def _validate_main_factorial_inventory(
    cases: Sequence[Mapping[str, Any]],
    *,
    agents: Sequence[str],
    expected_block_ids: Iterable[str] | None,
) -> tuple[set[str], int]:
    if len(agents) != 3 or len(set(agents)) != 3:
        raise ValueError("confirmatory analysis requires exactly three unique agents")
    indexed = _indexed_cases(cases)
    case_ids = [str(case["schedule_row"]["case_id"]) for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("analysis input has duplicate case IDs")
    if {key[1] for key in indexed} != set(agents):
        raise ValueError("analysis agent inventory differs from the frozen three agents")
    observed_blocks = {key[0] for key in indexed}
    if expected_block_ids is not None and observed_blocks != set(
        map(str, expected_block_ids)
    ):
        raise ValueError("analysis block inventory differs from the frozen schedule")
    expected_cells = set(
        product(
            agents,
            ("wall_clock", "fixed_work"),
            ("idle", "loaded"),
            ("fresh", "persistent"),
        )
    )
    for block_id in observed_blocks:
        keys = [key for key in indexed if key[0] == block_id]
        cells = {(key[1], key[2], key[3], key[4]) for key in keys}
        if cells != expected_cells:
            raise ValueError(f"confirmatory block {block_id} is factorially incomplete")
        block_cases = [indexed[key] for key in keys]
        for field in (
            "environment_seed",
            "physical_seat",
            "play_order",
            "load_batch_id",
            "session_bundle_id",
            "sequence_index",
        ):
            if len({case["schedule_row"][field] for case in block_cases}) != 1:
                raise ValueError(f"confirmatory block {block_id} is unmatched on {field}")
    if not observed_blocks:
        raise ValueError("confirmatory analysis has no matched blocks")
    load_batch_count = len(
        {case["schedule_row"]["load_batch_id"] for case in cases}
    )
    return observed_blocks, load_batch_count


def _validate_common_pair_hierarchy(
    pairs_by_agent: Mapping[str, Sequence[BlockPair]],
    agents: Sequence[str],
) -> list[BlockPair]:
    reference = list(pairs_by_agent[agents[0]])
    reference_hierarchy = {
        pair.block_id: (pair.load_batch_id, pair.session_bundle_id)
        for pair in reference
    }
    for agent_id in agents:
        hierarchy = {
            pair.block_id: (pair.load_batch_id, pair.session_bundle_id)
            for pair in pairs_by_agent[agent_id]
        }
        if hierarchy != reference_hierarchy:
            raise ValueError("agents do not share one complete block hierarchy")
    return reference


def _equal_agent_score_load_effect(
    cases: Sequence[Mapping[str, Any]],
    *,
    agents: Sequence[str],
    budget_mode: str,
    lifecycle: str,
    expected_block_ids: Iterable[str],
) -> tuple[float, dict[str, float], list[BlockPair]]:
    pairs_by_agent = {
        agent_id: paired_load_pairs(
            cases,
            agent_id=agent_id,
            budget_mode=budget_mode,
            lifecycle=lifecycle,
            metric="score",
            expected_block_ids=expected_block_ids,
        )
        for agent_id in agents
    }
    reference = _validate_common_pair_hierarchy(pairs_by_agent, agents)
    per_agent = {
        agent_id: _mean(
            [pair.loaded - pair.idle for pair in pairs_by_agent[agent_id]]
        )
        for agent_id in agents
    }
    return _mean([per_agent[agent_id] for agent_id in agents]), per_agent, reference


def _validate_repeatability_inventory(
    results: Sequence[Mapping[str, Any]],
    *,
    agents: Sequence[str],
) -> dict[str, int]:
    if not results:
        raise ValueError("confirmatory repeatability panel has no results")
    cells: dict[tuple[str, str, str, str, str, int], Mapping[str, Any]] = {}
    state_sources: dict[str, str] = {}
    source_states: dict[str, str] = {}
    load_batches: set[str] = set()
    for result in results:
        row = _validated_repeatability_result(result)
        if row.get("agent_id") not in agents:
            raise ValueError("repeatability panel contains an unexpected agent")
        if row.get("budget_mode") not in {"wall_clock", "fixed_work"}:
            raise ValueError("repeatability panel has an invalid budget mode")
        if row.get("load_condition") not in {"idle", "loaded"}:
            raise ValueError("repeatability panel has an invalid load condition")
        if row.get("lifecycle") not in {"fresh", "persistent"}:
            raise ValueError("repeatability panel has an invalid lifecycle")
        repeat_index = row.get("repeat_index")
        if (
            isinstance(repeat_index, bool)
            or not isinstance(repeat_index, int)
            or not 0 <= repeat_index < 10
        ):
            raise ValueError("repeatability panel has an invalid repeat index")
        state_id = str(row["state_id"])
        source_game_id = str(row["source_game_id"])
        if state_sources.setdefault(state_id, source_game_id) != source_game_id:
            raise ValueError("repeatability state maps to multiple source games")
        if source_states.setdefault(source_game_id, state_id) != state_id:
            raise ValueError("repeatability panel uses multiple states from one source game")
        key = (
            state_id,
            str(row["agent_id"]),
            str(row["budget_mode"]),
            str(row["load_condition"]),
            str(row["lifecycle"]),
            repeat_index,
        )
        if key in cells:
            raise ValueError(f"duplicate repeatability factorial result: {key}")
        cells[key] = result
        load_batches.add(str(row["load_batch_id"]))
    expected_within_state = set(
        product(
            agents,
            ("wall_clock", "fixed_work"),
            ("idle", "loaded"),
            ("fresh", "persistent"),
            range(10),
        )
    )
    for state_id in state_sources:
        observed = {
            (key[1], key[2], key[3], key[4], key[5])
            for key in cells
            if key[0] == state_id
        }
        if observed != expected_within_state:
            raise ValueError(f"repeatability state {state_id} is factorially incomplete")
    return {
        "result_count": len(results),
        "state_count": len(state_sources),
        "source_game_count": len(source_states),
        "state_agent_count": len(state_sources) * len(agents),
        "load_batch_count": len(load_batches),
    }


def confirmatory_point_estimates(
    cases: Iterable[Mapping[str, Any]],
    repeatability_results: Iterable[Mapping[str, Any]],
    *,
    agents: Sequence[str],
    expected_block_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Compute the exact ten locked headline point estimates and inventories.

    This is the production analysis path.  ``reaggregate.py`` duplicates these
    calculations independently and is forbidden from importing this module.
    """

    materialized_cases = list(cases)
    materialized_results = list(repeatability_results)
    frozen_agents = tuple(map(str, agents))
    observed_blocks, main_load_batch_count = _validate_main_factorial_inventory(
        materialized_cases,
        agents=frozen_agents,
        expected_block_ids=expected_block_ids,
    )
    repeat_inventory = _validate_repeatability_inventory(
        materialized_results,
        agents=frozen_agents,
    )
    block_ids = sorted(observed_blocks)
    estimands: list[dict[str, Any]] = []
    all_zero_game_count = 0
    all_wall_game_count = 0
    for lifecycle in ("fresh", "persistent"):
        work = equal_agent_wall_work_ratio(
            materialized_cases,
            agents=frozen_agents,
            lifecycle=lifecycle,
            expected_block_ids=block_ids,
        )
        all_zero_game_count += int(work["zero_eligible_decision_game_count"])
        all_wall_game_count += int(work["wall_game_count"])
        estimands.append(
            {
                "estimand_id": f"wall_work_ratio_{lifecycle}_equal_agent",
                "estimate": work["estimate"],
                "inventory": {
                    "agent_count": len(frozen_agents),
                    "matched_block_count": len(block_ids),
                    "load_batch_count": work["load_batch_count"],
                    "contributing_case_count": work["wall_game_count"],
                    "zero_eligible_decision_game_count": work[
                        "zero_eligible_decision_game_count"
                    ],
                    "zero_eligible_decision_game_rate": work[
                        "zero_eligible_decision_game_rate"
                    ],
                    "nonzero_complete_pair_count_by_agent": work[
                        "zero_decision_sensitivity"
                    ]["complete_pair_count_by_agent"],
                },
                "per_agent_estimates": work["per_agent_ratios"],
                "zero_decision_sensitivity": work["zero_decision_sensitivity"],
            }
        )
        score_results: dict[str, tuple[float, dict[str, float], list[BlockPair]]] = {}
        for budget_mode in ("wall_clock", "fixed_work"):
            score_results[budget_mode] = _equal_agent_score_load_effect(
                materialized_cases,
                agents=frozen_agents,
                budget_mode=budget_mode,
                lifecycle=lifecycle,
                expected_block_ids=block_ids,
            )
            label = "wall" if budget_mode == "wall_clock" else "fixed"
            estimate, per_agent, reference = score_results[budget_mode]
            estimands.append(
                {
                    "estimand_id": f"{label}_score_load_effect_{lifecycle}_equal_agent",
                    "estimate": estimate,
                    "inventory": {
                        "agent_count": len(frozen_agents),
                        "matched_block_count": len(reference),
                        "load_batch_count": len(
                            {pair.load_batch_id for pair in reference}
                        ),
                        "contributing_case_count": 2
                        * len(reference)
                        * len(frozen_agents),
                    },
                    "per_agent_estimates": per_agent,
                }
            )
        wall_per_agent = score_results["wall_clock"][1]
        fixed_per_agent = score_results["fixed_work"][1]
        attenuation_by_agent = {
            agent_id: wall_per_agent[agent_id] - fixed_per_agent[agent_id]
            for agent_id in frozen_agents
        }
        estimands.append(
            {
                "estimand_id": f"score_attenuation_{lifecycle}_equal_agent",
                "estimate": _mean(
                    [attenuation_by_agent[agent_id] for agent_id in frozen_agents]
                ),
                "inventory": {
                    "agent_count": len(frozen_agents),
                    "matched_block_count": len(block_ids),
                    "load_batch_count": main_load_batch_count,
                    "contributing_case_count": 4
                    * len(block_ids)
                    * len(frozen_agents),
                },
                "per_agent_estimates": attenuation_by_agent,
            }
        )

        idle_envelope = _repeatability_envelope_id(
            materialized_results,
            budget_mode="wall_clock",
            load_condition="idle",
            lifecycle=lifecycle,
        )
        loaded_envelope = _repeatability_envelope_id(
            materialized_results,
            budget_mode="wall_clock",
            load_condition="loaded",
            lifecycle=lifecycle,
        )
        state_agent = state_level_divergence(
            materialized_results,
            left_envelope=idle_envelope,
            right_envelope=loaded_envelope,
        )
        state_values = equal_agent_state_values(
            state_agent,
            agents=frozen_agents,
        )
        selected_result_count = 2 * 10 * len(frozen_agents) * len(state_values)
        selected_batches = {
            str(row["load_batch_id"])
            for result in materialized_results
            for row in (_validated_repeatability_result(result),)
            if row["budget_mode"] == "wall_clock"
            and row["lifecycle"] == lifecycle
        }
        estimands.append(
            {
                "estimand_id": (
                    f"wall_action_excess_divergence_{lifecycle}_equal_agent"
                ),
                "estimate": _mean([float(row["value"]) for row in state_values]),
                "inventory": {
                    "agent_count": len(frozen_agents),
                    "state_count": len(state_values),
                    "source_game_count": len(
                        {str(row["source_game_id"]) for row in state_values}
                    ),
                    "state_agent_count": len(state_agent),
                    "load_batch_count": len(selected_batches),
                    "contributing_result_count": selected_result_count,
                    "repeats_per_envelope": 10,
                },
            }
        )

    ordered = sorted(
        estimands,
        key=lambda record: CONFIRMATORY_ESTIMAND_IDS.index(record["estimand_id"]),
    )
    if [record["estimand_id"] for record in ordered] != list(
        CONFIRMATORY_ESTIMAND_IDS
    ):
        raise RuntimeError("confirmatory point-estimate inventory did not reconcile")
    inventory_counts = {
        "agent_count": len(frozen_agents),
        "main_case_count": len(materialized_cases),
        "main_matched_block_count": len(block_ids),
        "main_load_batch_count": main_load_batch_count,
        "zero_eligible_decision_game_count": all_zero_game_count,
        "zero_eligible_decision_game_rate": all_zero_game_count
        / all_wall_game_count,
        "repeatability_result_count": repeat_inventory["result_count"],
        "repeatability_state_count": repeat_inventory["state_count"],
        "repeatability_source_game_count": repeat_inventory["source_game_count"],
        "repeatability_state_agent_count": repeat_inventory["state_agent_count"],
        "repeatability_load_batch_count": repeat_inventory["load_batch_count"],
        "repeats_per_envelope": 10,
    }
    payload: dict[str, Any] = {
        "schema_version": "confirmatory-point-estimates-1.0.0",
        "analysis_version": ANALYSIS_VERSION,
        "work_outcome": (
            "per_game_mean_completed_work_per_eligible_decision_zero_if_none"
        ),
        "confirmatory_estimand_ids": list(CONFIRMATORY_ESTIMAND_IDS),
        "inventory_counts": inventory_counts,
        "estimands": ordered,
    }
    payload["content_hash"] = hash_json(payload)
    return payload


def _read_canonical_json_artifact(
    path: str | Path,
    *,
    expected_file_sha256: str,
    label: str,
) -> tuple[dict[str, Any], str]:
    source = Path(path).resolve()
    observed = hash_file(source)
    if not _is_sha256(expected_file_sha256) or observed != expected_file_sha256:
        raise ValueError(f"{label} file SHA-256 mismatch")
    raw = source.read_bytes()
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not ASCII JSON") from exc
    if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
        raise ValueError(f"{label} is not canonical JSON bytes")
    return value, observed


def _read_canonical_jsonl_artifact(
    path: Path,
    *,
    expected_file_sha256: str,
    expected_record_count: int,
    label: str,
) -> list[dict[str, Any]]:
    if path.name != str(path.name) or not path.is_file():
        raise ValueError(f"missing {label} JSONL artifact")
    if hash_file(path) != expected_file_sha256:
        raise ValueError(f"{label} JSONL file SHA-256 mismatch")
    records: list[dict[str, Any]] = []
    with path.open("rb") as handle:
        for line_number, raw in enumerate(handle, 1):
            try:
                value = json.loads(raw.decode("ascii"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid {label} JSONL line {line_number}") from exc
            if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
                raise ValueError(f"noncanonical {label} JSONL line {line_number}")
            records.append(value)
    if len(records) != expected_record_count:
        raise ValueError(f"{label} JSONL record count differs from hash manifest")
    return records


def build_analysis_outcome_hash_manifest(
    *,
    outcome_kind: str,
    design_manifest_content_hash: str,
    results_path: str | Path,
    commits_path: str | Path,
    episodes_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    """Hash-bind canonical acquisition journals before locked analysis."""

    if outcome_kind not in {"main_game", "repeatability"}:
        raise ValueError("analysis outcome kind must be main_game or repeatability")
    if not _is_sha256(design_manifest_content_hash):
        raise ValueError("analysis outcome manifest requires a design content hash")
    output = Path(output_path).resolve()
    files: dict[str, Any] = {}
    for role, raw_path in (
        ("results", results_path),
        ("commits", commits_path),
        ("episodes", episodes_path),
    ):
        source = Path(raw_path).resolve()
        if source.parent != output.parent:
            raise ValueError("analysis outcome files must share the hash-manifest directory")
        raw_lines = source.read_bytes().splitlines(keepends=True)
        for line_number, raw in enumerate(raw_lines, 1):
            try:
                value = json.loads(raw.decode("ascii"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"cannot hash-bind invalid {role} JSONL line {line_number}"
                ) from exc
            if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
                raise ValueError(
                    f"cannot hash-bind noncanonical {role} JSONL line {line_number}"
                )
        files[role] = {
            "filename": source.name,
            "sha256": hash_file(source),
            "record_count": len(raw_lines),
        }
    payload: dict[str, Any] = {
        "schema_version": "analysis-outcome-hash-manifest-1.0.0",
        "outcome_kind": outcome_kind,
        "design_manifest_content_hash": design_manifest_content_hash,
        "files": files,
    }
    payload["content_hash"] = hash_json(payload)
    write_canonical_json(output, payload)
    return payload


def _load_analysis_outcome_bundle(
    manifest_path: str | Path,
    *,
    expected_manifest_sha256: str,
    expected_kind: str,
    expected_design_content_hash: str,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], str]:
    manifest, observed_manifest_sha256 = _read_canonical_json_artifact(
        manifest_path,
        expected_file_sha256=expected_manifest_sha256,
        label=f"{expected_kind} outcome hash manifest",
    )
    if set(manifest) != {
        "schema_version",
        "outcome_kind",
        "design_manifest_content_hash",
        "files",
        "content_hash",
    }:
        raise ValueError("analysis outcome hash-manifest schema drift")
    payload = dict(manifest)
    supplied = payload.pop("content_hash", None)
    if supplied != hash_json(payload):
        raise ValueError("analysis outcome hash-manifest content hash mismatch")
    if (
        manifest["schema_version"] != "analysis-outcome-hash-manifest-1.0.0"
        or manifest["outcome_kind"] != expected_kind
        or manifest["design_manifest_content_hash"] != expected_design_content_hash
    ):
        raise ValueError("analysis outcome hash manifest targets another design")
    files = manifest["files"]
    if not isinstance(files, Mapping) or set(files) != {
        "results",
        "commits",
        "episodes",
    }:
        raise ValueError("analysis outcome hash manifest lacks journal files")
    directory = Path(manifest_path).resolve().parent
    loaded: dict[str, list[dict[str, Any]]] = {}
    for role in ("results", "commits", "episodes"):
        record = files[role]
        if not isinstance(record, Mapping) or set(record) != {
            "filename",
            "sha256",
            "record_count",
        }:
            raise ValueError("analysis outcome file inventory schema drift")
        filename = record["filename"]
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise ValueError("analysis outcome inventory filename is not a basename")
        digest = record["sha256"]
        count = record["record_count"]
        if not _is_sha256(digest):
            raise ValueError("analysis outcome inventory SHA-256 is invalid")
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ValueError("analysis outcome inventory count is invalid")
        loaded[role] = _read_canonical_jsonl_artifact(
            directory / filename,
            expected_file_sha256=digest,
            expected_record_count=count,
            label=f"{expected_kind} {role}",
        )
    return manifest, loaded, observed_manifest_sha256


def _validate_main_committed_raw(
    schedule: Mapping[str, Any],
    *,
    results: Sequence[Mapping[str, Any]],
    commits: Sequence[Mapping[str, Any]],
    episodes: Sequence[Mapping[str, Any]],
) -> None:
    schedule_rows = {str(row["case_id"]): row for row in schedule["rows"]}
    if len(schedule_rows) != len(schedule["rows"]):
        raise ValueError("final schedule case IDs are not unique")
    results_by_id: dict[str, Mapping[str, Any]] = {}
    for result in results:
        _validate_case_schema(result)
        case_id = str(result["game"]["case_id"])
        if case_id in results_by_id or case_id not in schedule_rows:
            raise ValueError("main raw result identity is duplicated or unscheduled")
        if result["schedule_row"] != schedule_rows[case_id]:
            raise ValueError("main raw result differs from the frozen schedule row")
        results_by_id[case_id] = result
    if set(results_by_id) != set(schedule_rows):
        raise ValueError("main raw terminal accounting is incomplete")
    episodes_by_batch: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for episode in episodes:
        metadata = dict(episode)
        supplied = metadata.pop("metadata_hash", None)
        metadata.pop("period_case_ids", None)
        if not _is_sha256(supplied) or supplied != hash_json(metadata):
            raise ValueError("main resource-episode metadata hash mismatch")
        episodes_by_batch[str(episode.get("load_batch_id"))].append(episode)
    commits_by_batch: dict[str, Mapping[str, Any]] = {}
    for commit in commits:
        if commit.get("schema_version") != "load-batch-commit-1.0.0":
            raise ValueError("main commit schema drift")
        payload = dict(commit)
        supplied = payload.pop("content_hash", None)
        if not _is_sha256(supplied) or supplied != hash_json(payload):
            raise ValueError("main commit content hash mismatch")
        batch_id = str(commit.get("load_batch_id"))
        if batch_id in commits_by_batch or commit.get("batch_status") != "scientific_complete":
            raise ValueError("main commit is duplicated or not scientifically complete")
        commits_by_batch[batch_id] = commit
    rows_by_batch: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in sorted(schedule["rows"], key=lambda item: int(item["execution_index"])):
        rows_by_batch[str(row["load_batch_id"])].append(row)
    if set(commits_by_batch) != set(rows_by_batch) or set(episodes_by_batch) != set(
        rows_by_batch
    ):
        raise ValueError("main batch commit/episode inventory differs from schedule")
    for batch_id, rows in rows_by_batch.items():
        commit = commits_by_batch[batch_id]
        ordered_results = [results_by_id[str(row["case_id"])] for row in rows]
        batch_episodes = episodes_by_batch[batch_id]
        if (
            commit.get("case_ids") != [row["case_id"] for row in rows]
            or commit.get("result_hashes")
            != [result["artifact_sha256"] for result in ordered_results]
            or len(batch_episodes) != 2
            or sorted(commit.get("episode_hashes", ()))
            != sorted(str(episode["metadata_hash"]) for episode in batch_episodes)
        ):
            raise ValueError("main committed batch does not bind its raw artifacts")


def _validate_repeatability_committed_raw(
    manifest: Mapping[str, Any],
    *,
    results: Sequence[Mapping[str, Any]],
    commits: Sequence[Mapping[str, Any]],
    episodes: Sequence[Mapping[str, Any]],
) -> None:
    schedule_rows = {
        str(row["repeatability_case_id"]): row for row in manifest["rows"]
    }
    if len(schedule_rows) != len(manifest["rows"]):
        raise ValueError("repeatability schedule case IDs are not unique")
    results_by_id: dict[str, Mapping[str, Any]] = {}
    for result in results:
        row = _validated_repeatability_result(result)
        case_id = str(result["case_id"])
        if case_id in results_by_id or case_id not in schedule_rows:
            raise ValueError("repeatability raw result is duplicated or unscheduled")
        if row != schedule_rows[case_id]:
            raise ValueError("repeatability result differs from its frozen manifest row")
        if result.get("manifest_content_hash") != manifest["content_hash"]:
            raise ValueError("repeatability result targets another manifest")
        results_by_id[case_id] = result
    if set(results_by_id) != set(schedule_rows):
        raise ValueError("repeatability terminal accounting is incomplete")
    episodes_by_group: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for episode in episodes:
        if episode.get("schema_version") != "state-panel-resource-episode-1.0.0":
            raise ValueError("repeatability resource-episode schema drift")
        payload = dict(episode)
        supplied = payload.pop("artifact_sha256", None)
        if not _is_sha256(supplied) or supplied != hash_json(payload):
            raise ValueError("repeatability resource-episode artifact hash mismatch")
        episodes_by_group[str(episode.get("group_id"))].append(episode)
    commits_by_group: dict[str, Mapping[str, Any]] = {}
    for commit in commits:
        if commit.get("schema_version") != "state-panel-batch-commit-1.0.0":
            raise ValueError("repeatability commit schema drift")
        payload = dict(commit)
        supplied = payload.pop("content_hash", None)
        if not _is_sha256(supplied) or supplied != hash_json(payload):
            raise ValueError("repeatability commit content hash mismatch")
        group_id = str(commit.get("group_id"))
        if (
            group_id in commits_by_group
            or commit.get("group_kind") != "paired_load_batch"
            or commit.get("batch_status") != "scientific_complete"
            or commit.get("manifest_content_hash") != manifest["content_hash"]
        ):
            raise ValueError("repeatability commit is duplicated or scientifically invalid")
        commits_by_group[group_id] = commit
    rows_by_group: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in sorted(manifest["rows"], key=lambda item: int(item["execution_index"])):
        rows_by_group[str(row["load_batch_id"])].append(row)
    if set(commits_by_group) != set(rows_by_group) or set(episodes_by_group) != set(
        rows_by_group
    ):
        raise ValueError("repeatability group commit/episode inventory differs from manifest")
    for group_id, rows in rows_by_group.items():
        commit = commits_by_group[group_id]
        ordered_results = [
            results_by_id[str(row["repeatability_case_id"])] for row in rows
        ]
        group_episodes = sorted(
            episodes_by_group[group_id], key=lambda value: int(value["period_index"])
        )
        if (
            commit.get("case_ids")
            != [row["repeatability_case_id"] for row in rows]
            or commit.get("result_hashes")
            != [result["artifact_sha256"] for result in ordered_results]
            or commit.get("episode_hashes")
            != [episode["artifact_sha256"] for episode in group_episodes]
        ):
            raise ValueError("repeatability commit does not bind its raw artifacts")


def run_locked_analysis(
    lock: AnalysisLock,
    *,
    schedule_path: str | Path,
    expected_schedule_sha256: str,
    repeatability_manifest_path: str | Path,
    expected_repeatability_manifest_sha256: str,
    main_outcome_hash_manifest_path: str | Path,
    expected_main_outcome_hash_manifest_sha256: str,
    repeatability_outcome_hash_manifest_path: str | Path,
    expected_repeatability_outcome_hash_manifest_sha256: str,
    protocol_path: str | Path,
    expected_protocol_sha256: str,
    analysis_code_path: str | Path,
    expected_analysis_code_sha256: str,
    output_dir: str | Path,
    test_mode: bool = False,
) -> dict[str, Any]:
    """Run the only fail-closed raw-to-publication analysis path."""

    from .repeatability import validate_repeatability_manifest
    from .scheduler import validate_schedule

    lock.validate()
    schedule, observed_schedule_hash = _read_canonical_json_artifact(
        schedule_path,
        expected_file_sha256=expected_schedule_sha256,
        label="final schedule",
    )
    validate_schedule(schedule)
    if not test_mode and schedule.get("config", {}).get("phase") != "final":
        raise ValueError("locked scientific analysis requires the final schedule")
    repeat_manifest, observed_repeat_manifest_hash = _read_canonical_json_artifact(
        repeatability_manifest_path,
        expected_file_sha256=expected_repeatability_manifest_sha256,
        label="repeatability manifest",
    )
    validate_repeatability_manifest(repeat_manifest)
    if not test_mode and int(repeat_manifest["config"]["target_state_count"]) != 100:
        raise ValueError("locked scientific analysis requires the frozen 100-state panel")
    _, main_bundle, observed_main_hash_manifest = _load_analysis_outcome_bundle(
        main_outcome_hash_manifest_path,
        expected_manifest_sha256=expected_main_outcome_hash_manifest_sha256,
        expected_kind="main_game",
        expected_design_content_hash=str(schedule["content_hash"]),
    )
    _, repeat_bundle, observed_repeat_hash_manifest = _load_analysis_outcome_bundle(
        repeatability_outcome_hash_manifest_path,
        expected_manifest_sha256=expected_repeatability_outcome_hash_manifest_sha256,
        expected_kind="repeatability",
        expected_design_content_hash=str(repeat_manifest["content_hash"]),
    )
    _validate_main_committed_raw(
        schedule,
        results=main_bundle["results"],
        commits=main_bundle["commits"],
        episodes=main_bundle["episodes"],
    )
    _validate_repeatability_committed_raw(
        repeat_manifest,
        results=repeat_bundle["results"],
        commits=repeat_bundle["commits"],
        episodes=repeat_bundle["episodes"],
    )
    if hash_file(protocol_path) != expected_protocol_sha256 or not _is_sha256(
        expected_protocol_sha256
    ):
        raise ValueError("protocol freeze file hash mismatch")
    if hash_file(analysis_code_path) != expected_analysis_code_sha256 or not _is_sha256(
        expected_analysis_code_sha256
    ):
        raise ValueError("analysis code file hash mismatch")
    agents = tuple(map(str, schedule["config"]["agents"]))
    if tuple(map(str, repeat_manifest["config"]["agents"])) != agents:
        raise ValueError("main and repeatability agent inventories differ")
    expected_blocks = [str(row["block_id"]) for row in schedule["rows"]]
    expected_blocks = sorted(set(expected_blocks))
    points = confirmatory_point_estimates(
        main_bundle["results"],
        repeat_bundle["results"],
        agents=agents,
        expected_block_ids=expected_blocks,
    )
    main_vectors = confirmatory_main_block_vectors(
        main_bundle["results"],
        agents=agents,
        expected_block_ids=expected_blocks,
    )
    main_evidence = common_resample_bonferroni_intervals(
        main_vectors,
        lock,
        statistic=lambda rows: confirmatory_main_statistic(rows, agents=agents),
        statistic_name="eight_main_endpoints_with_agent_specific_work_ratios",
    )
    state_evidence = repeatability_bonferroni_intervals(
        repeat_bundle["results"],
        lock,
        agents=agents,
    )
    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    point_path = destination / "confirmatory-point-estimates.json"
    main_evidence_path = destination / "main-simultaneous-evidence.json"
    state_evidence_path = destination / "state-simultaneous-evidence.json"
    write_canonical_json(point_path, points)
    write_canonical_json(main_evidence_path, main_evidence)
    write_canonical_json(state_evidence_path, state_evidence)
    source_artifacts = [
        {
            "role": "final_schedule",
            "schema_version": str(schedule["schema_version"]),
            "sha256": observed_schedule_hash,
        },
        {
            "role": "main_outcome_hash_manifest",
            "schema_version": "analysis-outcome-hash-manifest-1.0.0",
            "sha256": observed_main_hash_manifest,
        },
        {
            "role": "repeatability_outcome_hash_manifest",
            "schema_version": "analysis-outcome-hash-manifest-1.0.0",
            "sha256": observed_repeat_hash_manifest,
        },
        {
            "role": "protocol_freeze",
            "schema_version": "protocol-freeze-bytes-1.0.0",
            "sha256": expected_protocol_sha256,
        },
        {
            "role": "analysis_code",
            "schema_version": ANALYSIS_VERSION,
            "sha256": expected_analysis_code_sha256,
        },
    ]
    summary = build_frozen_analysis_summary(
        lock,
        point_estimates=points,
        simultaneous_evidence={
            "main_matched_blocks": main_evidence,
            "frozen_states": state_evidence,
        },
        source_artifacts=source_artifacts,
        protocol_freeze_hash=expected_protocol_sha256,
        rank_reversal={"comparisons": {}},
    )
    summary_path = destination / "locked-analysis-summary.json"
    write_canonical_json(summary_path, summary)
    driver_manifest: dict[str, Any] = {
        "schema_version": "locked-analysis-driver-result-1.0.0",
        "analysis_version": ANALYSIS_VERSION,
        "analysis_lock_hash": lock.content_hash,
        "schedule_file_sha256": observed_schedule_hash,
        "repeatability_manifest_file_sha256": observed_repeat_manifest_hash,
        "main_outcome_hash_manifest_file_sha256": observed_main_hash_manifest,
        "repeatability_outcome_hash_manifest_file_sha256": observed_repeat_hash_manifest,
        "protocol_file_sha256": expected_protocol_sha256,
        "analysis_code_file_sha256": expected_analysis_code_sha256,
        "outputs": {
            point_path.name: hash_file(point_path),
            main_evidence_path.name: hash_file(main_evidence_path),
            state_evidence_path.name: hash_file(state_evidence_path),
            summary_path.name: hash_file(summary_path),
        },
        "summary_content_hash": summary["content_hash"],
    }
    driver_manifest["content_hash"] = hash_json(driver_manifest)
    write_canonical_json(destination / "locked-analysis-driver-result.json", driver_manifest)
    return driver_manifest


def equivalence_decision(interval: Sequence[float], margin: float) -> str:
    if len(interval) != 2 or interval[0] > interval[1] or margin <= 0:
        raise ValueError("invalid equivalence interval or margin")
    return "equivalent" if interval[0] > -margin and interval[1] < margin else "not_established"


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_count(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def _validate_overall_inventory(inventory: Mapping[str, Any]) -> None:
    required = {
        "agent_count",
        "main_case_count",
        "main_matched_block_count",
        "main_load_batch_count",
        "zero_eligible_decision_game_count",
        "zero_eligible_decision_game_rate",
        "repeatability_result_count",
        "repeatability_state_count",
        "repeatability_source_game_count",
        "repeatability_state_agent_count",
        "repeatability_load_batch_count",
        "repeats_per_envelope",
    }
    if not isinstance(inventory, Mapping) or set(inventory) != required:
        raise ValueError("analysis summary overall inventory schema drift")
    if _validate_count(inventory["agent_count"], "agent_count", minimum=1) != 3:
        raise ValueError("analysis summary inventory must contain three agents")
    for field in required - {"zero_eligible_decision_game_rate"}:
        minimum = 1 if field not in {"zero_eligible_decision_game_count"} else 0
        _validate_count(inventory[field], field, minimum=minimum)
    if inventory["repeats_per_envelope"] != 10:
        raise ValueError("analysis summary inventory must use ten repeats per envelope")
    if inventory["main_case_count"] != (
        inventory["main_matched_block_count"] * inventory["agent_count"] * 8
    ):
        raise ValueError("analysis summary main case inventory does not reconcile")
    if inventory["repeatability_state_count"] != inventory[
        "repeatability_source_game_count"
    ]:
        raise ValueError("analysis summary state/source inventory does not reconcile")
    if inventory["repeatability_state_agent_count"] != (
        inventory["repeatability_state_count"] * inventory["agent_count"]
    ):
        raise ValueError("analysis summary state-agent inventory does not reconcile")
    if inventory["repeatability_result_count"] != (
        inventory["repeatability_state_agent_count"]
        * 8
        * inventory["repeats_per_envelope"]
    ):
        raise ValueError("analysis summary repeatability result inventory does not reconcile")
    zero_rate = float(inventory["zero_eligible_decision_game_rate"])
    if not math.isfinite(zero_rate) or not 0.0 <= zero_rate <= 1.0:
        raise ValueError("analysis summary zero-decision rate is invalid")
    wall_game_count = (
        inventory["main_matched_block_count"] * inventory["agent_count"] * 4
    )
    if not math.isclose(
        zero_rate,
        inventory["zero_eligible_decision_game_count"] / wall_game_count,
        rel_tol=0.0,
        abs_tol=1e-15,
    ):
        raise ValueError("analysis summary overall zero-decision rate does not reconcile")


def _validate_estimand_inventory(estimand_id: str, inventory: Any) -> None:
    if not isinstance(inventory, Mapping):
        raise ValueError("analysis summary estimand inventory must be an object")
    if "action_excess_divergence" in estimand_id:
        required = {
            "agent_count",
            "state_count",
            "source_game_count",
            "state_agent_count",
            "load_batch_count",
            "contributing_result_count",
            "repeats_per_envelope",
        }
        if set(inventory) != required:
            raise ValueError("action-divergence inventory schema drift")
        for field in required:
            _validate_count(inventory[field], field, minimum=1)
        if inventory["agent_count"] != 3 or inventory["repeats_per_envelope"] != 10:
            raise ValueError("action-divergence inventory design differs from the lock")
        if inventory["state_count"] != inventory["source_game_count"]:
            raise ValueError("action-divergence state/source counts differ")
        if inventory["state_agent_count"] != (
            inventory["state_count"] * inventory["agent_count"]
        ):
            raise ValueError("action-divergence state-agent count differs")
        if inventory["contributing_result_count"] != (
            inventory["state_count"]
            * inventory["agent_count"]
            * 2
            * inventory["repeats_per_envelope"]
        ):
            raise ValueError("action-divergence contributing result count differs")
        return
    base = {
        "agent_count",
        "matched_block_count",
        "load_batch_count",
        "contributing_case_count",
    }
    if estimand_id.startswith("wall_work_ratio"):
        required = base | {
            "zero_eligible_decision_game_count",
            "zero_eligible_decision_game_rate",
            "nonzero_complete_pair_count_by_agent",
        }
    else:
        required = base
    if set(inventory) != required:
        raise ValueError("matched-block estimand inventory schema drift")
    for field in base:
        _validate_count(inventory[field], field, minimum=1)
    if inventory["agent_count"] != 3:
        raise ValueError("matched-block inventory must contain three agents")
    multiplier = 4 if estimand_id.startswith("score_attenuation") else 2
    if inventory["contributing_case_count"] != (
        inventory["matched_block_count"] * inventory["agent_count"] * multiplier
    ):
        raise ValueError("matched-block contributing case count does not reconcile")
    if estimand_id.startswith("wall_work_ratio"):
        zero_count = _validate_count(
            inventory["zero_eligible_decision_game_count"],
            "zero_eligible_decision_game_count",
        )
        zero_rate = float(inventory["zero_eligible_decision_game_rate"])
        if not math.isclose(
            zero_rate,
            zero_count / inventory["contributing_case_count"],
            rel_tol=0.0,
            abs_tol=1e-15,
        ):
            raise ValueError("work inventory zero-decision rate does not reconcile")
        pair_counts = inventory["nonzero_complete_pair_count_by_agent"]
        if not isinstance(pair_counts, Mapping) or len(pair_counts) != 3:
            raise ValueError("work sensitivity lacks all three agent pair counts")
        for count in pair_counts.values():
            if _validate_count(count, "nonzero complete pair count") > inventory[
                "matched_block_count"
            ]:
                raise ValueError("work sensitivity pair count exceeds matched blocks")


def _validate_summary_estimand(record: Mapping[str, Any], lock: AnalysisLock) -> None:
    required = {
        "estimand_id",
        "display_label",
        "estimate",
        "interval",
        "confidence_level",
        "multiplicity_method",
        "inference_unit",
        "plot_group",
        "equivalence_margin",
        "equivalence_decision",
        "inventory",
    }
    if set(record) != required:
        raise ValueError("analysis summary estimand schema drift")
    if record["estimand_id"] not in CONFIRMATORY_ESTIMAND_IDS:
        raise ValueError("analysis summary contains a non-confirmatory estimand")
    estimate = float(record["estimate"])
    interval = list(record["interval"])
    if (
        not math.isfinite(estimate)
        or len(interval) != 2
        or not all(math.isfinite(float(value)) for value in interval)
        or float(interval[0]) > float(interval[1])
    ):
        raise ValueError("analysis summary estimand has invalid estimate/interval")
    if not math.isclose(
        float(record["confidence_level"]),
        lock.confirmatory_member_confidence_level,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ValueError("analysis summary interval lacks frozen simultaneous coverage")
    if record["multiplicity_method"] != lock.simultaneous_method:
        raise ValueError("analysis summary multiplicity method differs from lock")
    if record["inference_unit"] not in {"matched_block", "frozen_state"}:
        raise ValueError("analysis summary has an invalid inference unit")
    expected_unit = (
        "frozen_state"
        if "action_excess_divergence" in str(record["estimand_id"])
        else "matched_block"
    )
    if record["inference_unit"] != expected_unit:
        raise ValueError("analysis summary uses the wrong inference unit")
    expected_group = (
        "work_relative"
        if str(record["estimand_id"]).startswith("wall_work_ratio")
        else "probability_difference"
    )
    if record["plot_group"] != expected_group:
        raise ValueError("analysis summary plot group differs from estimand scale")
    margin = float(record["equivalence_margin"])
    expected_margin = (
        lock.work_relative_equivalence_margin
        if str(record["estimand_id"]).startswith("wall_work_ratio")
        else (
            lock.action_divergence_margin
            if "action_excess_divergence" in str(record["estimand_id"])
            else lock.score_equivalence_margin
        )
    )
    if not math.isclose(margin, expected_margin, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("analysis summary equivalence margin differs from lock")
    if not isinstance(record["display_label"], str) or not record["display_label"]:
        raise ValueError("analysis summary display label is empty")
    expected_decision = equivalence_decision(interval, margin)
    if record["equivalence_decision"] != expected_decision:
        raise ValueError("analysis summary equivalence decision does not reconcile")
    _validate_estimand_inventory(str(record["estimand_id"]), record["inventory"])


def build_frozen_analysis_summary(
    lock: AnalysisLock,
    *,
    point_estimates: Mapping[str, Any],
    simultaneous_evidence: Mapping[str, Mapping[str, Any]],
    source_artifacts: Sequence[Mapping[str, str]],
    protocol_freeze_hash: str,
    rank_reversal: Mapping[str, Any],
    display_labels: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Derive the publication summary from locked points and interval evidence.

    Callers cannot supply estimates or intervals to this API.  Both are read
    from content-hashed analysis artifacts and must reconcile endpoint-for-
    endpoint before a frozen summary can exist.
    """

    lock.validate()
    if not _is_sha256(protocol_freeze_hash):
        raise ValueError("analysis summary requires a protocol-freeze SHA-256")
    if point_estimates.get("schema_version") != "confirmatory-point-estimates-1.0.0":
        raise ValueError("analysis summary requires locked point-estimate evidence")
    if point_estimates.get("analysis_version") != ANALYSIS_VERSION:
        raise ValueError("point-estimate evidence targets another analysis version")
    point_payload = dict(point_estimates)
    point_hash = point_payload.pop("content_hash", None)
    if not _is_sha256(point_hash) or point_hash != hash_json(point_payload):
        raise ValueError("point-estimate evidence content hash mismatch")
    if point_estimates.get("confirmatory_estimand_ids") != list(
        CONFIRMATORY_ESTIMAND_IDS
    ):
        raise ValueError("point-estimate evidence has the wrong confirmatory family")
    _validate_overall_inventory(point_estimates.get("inventory_counts"))
    point_records = list(point_estimates.get("estimands", ()))
    if [record.get("estimand_id") for record in point_records] != list(
        CONFIRMATORY_ESTIMAND_IDS
    ):
        raise ValueError("point-estimate evidence endpoints are incomplete or reordered")
    if set(simultaneous_evidence) != {"main_matched_blocks", "frozen_states"}:
        raise ValueError("analysis summary requires main-block and frozen-state evidence")
    evidence_artifacts = {
        role: dict(artifact) for role, artifact in simultaneous_evidence.items()
    }
    interval_by_endpoint: dict[str, Mapping[str, Any]] = {}
    for role, artifact in evidence_artifacts.items():
        verify_simultaneous_interval_result(artifact)
        if artifact.get("analysis_version") != ANALYSIS_VERSION:
            raise ValueError(f"{role} interval evidence targets another analysis version")
        if artifact.get("analysis_lock_hash") != lock.content_hash:
            raise ValueError(f"{role} interval evidence uses another analysis lock")
        if artifact.get("simultaneous_method") != lock.simultaneous_method:
            raise ValueError(f"{role} interval evidence is not ten-family Bonferroni")
        if not math.isclose(
            float(artifact.get("member_confidence_level")),
            lock.confirmatory_member_confidence_level,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError(f"{role} interval evidence has wrong member coverage")
        endpoints = list(artifact["endpoint_ids"])
        expected_role_endpoints = {
            endpoint_id
            for endpoint_id in CONFIRMATORY_ESTIMAND_IDS
            if ("action_excess_divergence" in endpoint_id)
            == (role == "frozen_states")
        }
        if set(endpoints) != expected_role_endpoints or len(endpoints) != len(
            expected_role_endpoints
        ):
            raise ValueError(f"{role} interval endpoint inventory differs from lock")
        for endpoint_id in endpoints:
            if endpoint_id in interval_by_endpoint:
                raise ValueError("simultaneous evidence duplicates an endpoint")
            interval_by_endpoint[endpoint_id] = artifact["intervals"][endpoint_id]
    labels = dict(display_labels or {})
    if set(labels) - set(CONFIRMATORY_ESTIMAND_IDS):
        raise ValueError("analysis display labels name non-confirmatory endpoints")
    ordered_estimands: list[dict[str, Any]] = []
    for point_record in point_records:
        estimand_id = str(point_record["estimand_id"])
        estimate = float(point_record["estimate"])
        interval_record = interval_by_endpoint[estimand_id]
        if not math.isclose(
            estimate,
            float(interval_record["estimate"]),
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError(f"point and interval estimates differ for {estimand_id}")
        interval = [float(value) for value in interval_record["interval"]]
        margin = (
            lock.work_relative_equivalence_margin
            if estimand_id.startswith("wall_work_ratio")
            else (
                lock.action_divergence_margin
                if "action_excess_divergence" in estimand_id
                else lock.score_equivalence_margin
            )
        )
        record = {
            "estimand_id": estimand_id,
            "display_label": labels.get(estimand_id, estimand_id),
            "estimate": estimate,
            "interval": interval,
            "confidence_level": lock.confirmatory_member_confidence_level,
            "multiplicity_method": lock.simultaneous_method,
            "inference_unit": (
                "frozen_state"
                if "action_excess_divergence" in estimand_id
                else "matched_block"
            ),
            "plot_group": (
                "work_relative"
                if estimand_id.startswith("wall_work_ratio")
                else "probability_difference"
            ),
            "equivalence_margin": margin,
            "equivalence_decision": equivalence_decision(interval, margin),
            "inventory": dict(point_record["inventory"]),
        }
        _validate_summary_estimand(record, lock)
        ordered_estimands.append(record)
    artifacts = [dict(record) for record in source_artifacts]
    if {record.get("role") for record in artifacts} != REQUIRED_ANALYSIS_SOURCE_ROLES:
        raise ValueError("analysis summary source inventory is incomplete")
    if len(artifacts) != len(REQUIRED_ANALYSIS_SOURCE_ROLES):
        raise ValueError("analysis summary source roles are duplicated")
    for record in artifacts:
        if set(record) != {"role", "schema_version", "sha256"}:
            raise ValueError("analysis source inventory schema drift")
        digest = record["sha256"]
        if not _is_sha256(digest):
            raise ValueError("analysis source inventory has an invalid SHA-256")
    evidence_hashes = sorted(
        str(artifact["content_hash"]) for artifact in evidence_artifacts.values()
    )
    payload: dict[str, Any] = {
        "schema_version": "locked-analysis-summary-1.0.0",
        "freeze_status": "FROZEN_ANALYSIS_SUMMARY",
        "analysis_version": ANALYSIS_VERSION,
        "analysis_lock": asdict(lock),
        "analysis_lock_hash": lock.content_hash,
        "protocol_freeze_hash": protocol_freeze_hash,
        "confirmatory_estimand_ids": list(CONFIRMATORY_ESTIMAND_IDS),
        "familywise_confidence_level": lock.confidence_level,
        "simultaneous_method": lock.simultaneous_method,
        "member_confidence_level": lock.confirmatory_member_confidence_level,
        "point_estimate_content_hash": point_hash,
        "inventory_counts": dict(point_estimates["inventory_counts"]),
        "simultaneous_evidence_hashes": evidence_hashes,
        "simultaneous_evidence": {
            role: evidence_artifacts[role] for role in sorted(evidence_artifacts)
        },
        "source_artifacts": sorted(artifacts, key=lambda record: record["role"]),
        "source_artifact_inventory_hash": hash_json(
            sorted(artifacts, key=lambda record: record["role"])
        ),
        "estimands": ordered_estimands,
        "rank_reversal": dict(rank_reversal),
    }
    payload["content_hash"] = hash_json(payload)
    verify_frozen_analysis_summary(payload)
    return payload


def verify_frozen_analysis_summary(summary: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "freeze_status",
        "analysis_version",
        "analysis_lock",
        "analysis_lock_hash",
        "protocol_freeze_hash",
        "confirmatory_estimand_ids",
        "familywise_confidence_level",
        "simultaneous_method",
        "member_confidence_level",
        "point_estimate_content_hash",
        "inventory_counts",
        "simultaneous_evidence_hashes",
        "simultaneous_evidence",
        "source_artifacts",
        "source_artifact_inventory_hash",
        "estimands",
        "rank_reversal",
        "content_hash",
    }
    if set(summary) != required:
        raise ValueError("analysis summary top-level schema drift")
    if summary.get("schema_version") != "locked-analysis-summary-1.0.0":
        raise ValueError("unsupported analysis summary schema")
    if summary.get("freeze_status") != "FROZEN_ANALYSIS_SUMMARY":
        raise ValueError("publication analysis summary is not frozen")
    payload = dict(summary)
    supplied = payload.pop("content_hash", None)
    if supplied != hash_json(payload):
        raise ValueError("analysis summary content hash mismatch")
    lock = AnalysisLock(**dict(summary["analysis_lock"]))
    lock.validate()
    if summary["analysis_lock_hash"] != lock.content_hash:
        raise ValueError("analysis summary lock hash mismatch")
    if summary["analysis_version"] != ANALYSIS_VERSION:
        raise ValueError("analysis summary version differs from locked code")
    if summary["confirmatory_estimand_ids"] != list(CONFIRMATORY_ESTIMAND_IDS):
        raise ValueError("analysis summary confirmatory family differs from lock")
    if summary["simultaneous_method"] != lock.simultaneous_method:
        raise ValueError("analysis summary simultaneous method differs from lock")
    if not math.isclose(
        float(summary["familywise_confidence_level"]),
        lock.confidence_level,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ValueError("analysis summary familywise confidence differs from lock")
    if not math.isclose(
        float(summary["member_confidence_level"]),
        lock.confirmatory_member_confidence_level,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ValueError("analysis summary member confidence differs from lock")
    if not _is_sha256(summary["protocol_freeze_hash"]):
        raise ValueError("analysis summary protocol-freeze hash is invalid")
    if not _is_sha256(summary["point_estimate_content_hash"]):
        raise ValueError("analysis summary point-estimate evidence hash is invalid")
    evidence_hashes = summary["simultaneous_evidence_hashes"]
    if (
        not isinstance(evidence_hashes, list)
        or not evidence_hashes
        or evidence_hashes != sorted(evidence_hashes)
        or len(evidence_hashes) != len(set(evidence_hashes))
        or any(not _is_sha256(value) for value in evidence_hashes)
    ):
        raise ValueError("analysis summary simultaneous evidence inventory is invalid")
    _validate_overall_inventory(summary["inventory_counts"])
    estimands = list(summary["estimands"])
    if [record.get("estimand_id") for record in estimands] != list(
        CONFIRMATORY_ESTIMAND_IDS
    ):
        raise ValueError("analysis summary estimands are missing, duplicated, or reordered")
    for record in estimands:
        _validate_summary_estimand(record, lock)
    evidence = summary["simultaneous_evidence"]
    if not isinstance(evidence, Mapping) or set(evidence) != {
        "main_matched_blocks",
        "frozen_states",
    }:
        raise ValueError("analysis summary simultaneous evidence inventory is incomplete")
    observed_evidence_hashes: list[str] = []
    interval_by_endpoint: dict[str, Mapping[str, Any]] = {}
    for role, artifact in evidence.items():
        if not isinstance(artifact, Mapping):
            raise ValueError("analysis summary interval evidence is malformed")
        verify_simultaneous_interval_result(artifact)
        observed_evidence_hashes.append(str(artifact["content_hash"]))
        if artifact.get("analysis_version") != ANALYSIS_VERSION:
            raise ValueError("analysis summary interval evidence version differs")
        if artifact.get("analysis_lock_hash") != lock.content_hash:
            raise ValueError("analysis summary interval evidence lock differs")
        if artifact.get("simultaneous_method") != lock.simultaneous_method:
            raise ValueError("analysis summary interval evidence multiplicity differs")
        if not math.isclose(
            float(artifact.get("member_confidence_level")),
            lock.confirmatory_member_confidence_level,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("analysis summary interval evidence coverage differs")
        expected_role_endpoints = {
            endpoint_id
            for endpoint_id in CONFIRMATORY_ESTIMAND_IDS
            if ("action_excess_divergence" in endpoint_id)
            == (role == "frozen_states")
        }
        if set(artifact.get("endpoint_ids", ())) != expected_role_endpoints:
            raise ValueError("analysis summary interval evidence endpoints differ")
        for endpoint_id in artifact["endpoint_ids"]:
            if endpoint_id in interval_by_endpoint:
                raise ValueError("analysis summary interval evidence duplicates endpoints")
            interval_by_endpoint[endpoint_id] = artifact["intervals"][endpoint_id]
    if sorted(observed_evidence_hashes) != evidence_hashes:
        raise ValueError("analysis summary evidence hashes do not bind embedded evidence")
    for record in estimands:
        interval_record = interval_by_endpoint[record["estimand_id"]]
        if not math.isclose(
            float(record["estimate"]),
            float(interval_record["estimate"]),
            rel_tol=0.0,
            abs_tol=1e-12,
        ) or [float(value) for value in record["interval"]] != [
            float(value) for value in interval_record["interval"]
        ]:
            raise ValueError("analysis summary estimate/interval differs from evidence")
    artifacts = list(summary["source_artifacts"])
    if summary["source_artifact_inventory_hash"] != hash_json(artifacts):
        raise ValueError("analysis summary source artifact inventory hash mismatch")
    if {record.get("role") for record in artifacts} != REQUIRED_ANALYSIS_SOURCE_ROLES:
        raise ValueError("analysis summary source inventory is incomplete")
    if len(artifacts) != len(REQUIRED_ANALYSIS_SOURCE_ROLES) or artifacts != sorted(
        artifacts, key=lambda record: record.get("role", "")
    ):
        raise ValueError("analysis summary source inventory is duplicated or unordered")
    for record in artifacts:
        if set(record) != {"role", "schema_version", "sha256"}:
            raise ValueError("analysis summary source inventory schema drift")
        if not isinstance(record["schema_version"], str) or not record[
            "schema_version"
        ]:
            raise ValueError("analysis summary source schema version is empty")
        if not _is_sha256(record["sha256"]):
            raise ValueError("analysis summary source SHA-256 is invalid")
    rank_reversal = summary["rank_reversal"]
    if not isinstance(rank_reversal, Mapping) or "comparisons" not in rank_reversal:
        raise ValueError("analysis summary rank-reversal record is malformed")
    if not isinstance(rank_reversal["comparisons"], Mapping):
        raise ValueError("analysis summary rank-reversal comparisons are malformed")
    if "tie_margin" in rank_reversal and not math.isclose(
        float(rank_reversal["tie_margin"]),
        lock.rank_tie_margin,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ValueError("analysis summary rank tie margin differs from lock")
    if "joint_interval_content_hash" in rank_reversal and not _is_sha256(
        rank_reversal["joint_interval_content_hash"]
    ):
        raise ValueError("analysis summary rank-reversal evidence hash is invalid")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the hash-bound, non-bypassable locked analysis driver."
    )
    parser.add_argument("--schedule", required=True)
    parser.add_argument("--schedule-sha256", required=True)
    parser.add_argument("--repeatability-manifest", required=True)
    parser.add_argument("--repeatability-manifest-sha256", required=True)
    parser.add_argument("--main-outcome-hash-manifest", required=True)
    parser.add_argument("--main-outcome-hash-manifest-sha256", required=True)
    parser.add_argument("--repeatability-outcome-hash-manifest", required=True)
    parser.add_argument("--repeatability-outcome-hash-manifest-sha256", required=True)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--protocol-sha256", required=True)
    parser.add_argument("--analysis-code", required=True)
    parser.add_argument("--analysis-code-sha256", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    run_locked_analysis(
        AnalysisLock(),
        schedule_path=args.schedule,
        expected_schedule_sha256=args.schedule_sha256,
        repeatability_manifest_path=args.repeatability_manifest,
        expected_repeatability_manifest_sha256=args.repeatability_manifest_sha256,
        main_outcome_hash_manifest_path=args.main_outcome_hash_manifest,
        expected_main_outcome_hash_manifest_sha256=(
            args.main_outcome_hash_manifest_sha256
        ),
        repeatability_outcome_hash_manifest_path=(
            args.repeatability_outcome_hash_manifest
        ),
        expected_repeatability_outcome_hash_manifest_sha256=(
            args.repeatability_outcome_hash_manifest_sha256
        ),
        protocol_path=args.protocol,
        expected_protocol_sha256=args.protocol_sha256,
        analysis_code_path=args.analysis_code,
        expected_analysis_code_sha256=args.analysis_code_sha256,
        output_dir=args.output_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
