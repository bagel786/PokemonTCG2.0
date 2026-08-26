"""Independent reaggregation from released main and frozen-state JSONL.

This program intentionally does not import :mod:`resource_envelope_study.analysis`.
It duplicates all ten locked point-estimate calculations and every published
inventory count through a separate implementation, then compares them with the
frozen analysis summary. It never computes uncertainty intervals.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from itertools import product
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .canonical import canonical_json_bytes, hash_json


REAGGREGATION_VERSION = "independent-confirmatory-reaggregation-1.0.0"
EXPECTED_ANALYSIS_VERSION = "resource-envelope-analysis-1.2.0"
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
MAIN_RESULT_FIELDS = frozenset(
    "schedule_row game decisions gameplay_decisions public_trace_sha256 observed_worker artifact_sha256".split()
)
SCHEDULE_ROW_FIELDS = frozenset(
    "schema_version phase case_id block_id block_index agent_id budget_mode load_condition lifecycle physical_seat play_order environment_seed agent_seed schedule_seed load_seed load_batch_id load_period_order lifecycle_pair_id sequence_pair_id session_bundle_id lifecycle_id process_instance_id sequence_index execution_index requested_budget_ns requested_work_units".split()
)
GAME_FIELDS = frozenset(
    "schema_version case_id block_id agent_id score winner terminal_status decision_count completed_work_units completed_simulations completed_nodes completed_sweeps forward_model_calls decision_record_hashes error_type error_message".split()
)
DECISION_FIELDS = frozenset(
    "schema_version case_id block_id decision_index agent_id budget_mode load_condition lifecycle lifecycle_id process_instance_id worker_pid sequence_index load_batch_id requested_budget_ns requested_work_units completed_work_units completed_simulations completed_nodes completed_sweeps forward_model_calls setup_wall_ns search_wall_ns selection_wall_ns cleanup_wall_ns process_cpu_ns overshoot_ns state_hash agent_seed_hash selected_action selected_action_hash value_estimates timeout_reason fallback_reason cleanup_succeeded instrumentation_enabled work_counters_collected terminal_status error_type error_message extra".split()
)
REPEATABILITY_RESULT_FIELDS = frozenset(
    "schema_version case_id manifest_content_hash schedule_row state_artifact_sha256 history_prefix_sha256 budget_mode requested_budget_ns requested_work_units terminal_status eligible completed_work_units completed_simulations completed_nodes forward_model_calls search_wall_ns overshoot_ns state_hash selected_action_hash cleanup_succeeded warmup_steps_completed warmup_consumed_sha256 warmup_replay_sha256 observed_worker artifact_sha256".split()
)
REPEATABILITY_ROW_FIELDS = frozenset(
    "schema_version repeatability_case_id bank_id inference_unit_id state_id source_game_id state_artifact_sha256 state_seed history_prefix_sha256 history_seed history_length pseudo_sequence_slot sequence_index agent_id agent_seed envelope_id resource_profile_sha256 load_condition lifecycle budget_mode requested_budget_ns requested_work_units repeat_index session_id process_instance_id session_seed schedule_seed load_batch_id load_seed load_period_order execution_index".split()
)


def read_jsonl(paths: Iterable[str | Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_path in paths:
        path = Path(raw_path)
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} is not a JSON object")
            rows.append(value)
    return rows


def _average(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("cannot average an empty reaggregation sample")
    return float(sum(values) / len(values))


def _validate_main_case(case: Mapping[str, Any]) -> None:
    if not isinstance(case, Mapping):
        raise ValueError("main reaggregation row is not an object")
    if set(case) != MAIN_RESULT_FIELDS:
        raise ValueError("main reaggregation top-level schema drift")
    row = case.get("schedule_row")
    game = case.get("game")
    decisions = case.get("decisions")
    if not isinstance(row, Mapping) or row.get("schema_version") != "schedule-row-1.0.0":
        raise ValueError("main reaggregation refuses unexpected schedule schema")
    if set(row) != SCHEDULE_ROW_FIELDS:
        raise ValueError("main reaggregation schedule-row fields differ")
    if not isinstance(game, Mapping) or game.get("schema_version") != "game-1.0.0":
        raise ValueError("main reaggregation refuses unexpected game schema")
    if set(game) != GAME_FIELDS:
        raise ValueError("main reaggregation game fields differ")
    if not isinstance(decisions, (list, tuple)):
        raise ValueError("main reaggregation decisions are not an array")
    for field, allowed in (
        ("budget_mode", {"wall_clock", "fixed_work"}),
        ("load_condition", {"idle", "loaded"}),
        ("lifecycle", {"fresh", "persistent"}),
    ):
        if row.get(field) not in allowed:
            raise ValueError(f"main reaggregation row has invalid {field}")
    required = {
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
    if any(field not in row for field in required):
        raise ValueError("main reaggregation row lacks matching fields")
    for field in ("case_id", "block_id", "agent_id"):
        if row.get(field) != game.get(field):
            raise ValueError(f"main reaggregation identity differs on {field}")
    statuses = {
        "completed",
        "agent_timeout",
        "agent_error",
        "illegal_action",
        "engine_error",
        "infrastructure_error",
        "protocol_invalid",
    }
    if game.get("terminal_status") not in statuses:
        raise ValueError("main reaggregation game status is unknown")
    count = game.get("decision_count")
    if (
        isinstance(count, bool)
        or not isinstance(count, int)
        or count != len(decisions)
    ):
        raise ValueError("main reaggregation decision count does not reconcile")
    total = 0
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
        if (
            not isinstance(decision, Mapping)
            or decision.get("schema_version") != "decision-1.1.0"
        ):
            raise ValueError("main reaggregation refuses unexpected decision schema")
        if set(decision) != DECISION_FIELDS:
            raise ValueError("main reaggregation decision fields differ")
        for field in ("case_id", "block_id", "agent_id"):
            if decision.get(field) != row.get(field):
                raise ValueError(f"main decision identity differs on {field}")
        if decision.get("terminal_status") not in decision_statuses:
            raise ValueError("main reaggregation decision status is unknown")
        work = decision.get("completed_work_units")
        if isinstance(work, bool) or not isinstance(work, int) or work < 0:
            raise ValueError("main reaggregation decision work is invalid")
        total += work
    game_work = game.get("completed_work_units")
    if (
        isinstance(game_work, bool)
        or not isinstance(game_work, int)
        or game_work < 0
        or game_work != total
    ):
        raise ValueError("main reaggregation game work does not reconcile")
    supplied_hash = case.get("artifact_sha256")
    artifact_payload = dict(case)
    artifact_payload.pop("artifact_sha256", None)
    if supplied_hash != hash_json(artifact_payload):
        raise ValueError("main reaggregation result artifact hash mismatch")


def _metric(case: Mapping[str, Any], name: str) -> float:
    _validate_main_case(case)
    game = case["game"]
    if game.get("terminal_status") in {
        "engine_error",
        "infrastructure_error",
        "protocol_invalid",
    }:
        raise ValueError(f"scientifically invalid case: {game.get('case_id')}")
    if name == "score":
        value = game.get("score")
        if value not in {0, 0.5, 1}:
            raise ValueError("assigned game lacks a valid ITT score")
        return float(value)
    if name == "mean_decision_work":
        decisions = list(case["decisions"])
        if not decisions:
            return 0.0
        return _average([float(row["completed_work_units"]) for row in decisions])
    raise ValueError(f"unsupported metric: {name}")


def _main_cells(
    cases: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str, str, str, str], Mapping[str, Any]]:
    cells: dict[tuple[str, str, str, str, str], Mapping[str, Any]] = {}
    case_ids: set[str] = set()
    for case in cases:
        _validate_main_case(case)
        row = case["schedule_row"]
        case_id = str(row["case_id"])
        if case_id in case_ids:
            raise ValueError(f"duplicate main case ID: {case_id}")
        case_ids.add(case_id)
        key = (
            str(row["block_id"]),
            str(row["agent_id"]),
            str(row["budget_mode"]),
            str(row["load_condition"]),
            str(row["lifecycle"]),
        )
        if key in cells:
            raise ValueError(f"duplicate main factorial cell: {key}")
        cells[key] = case
    return cells


def _load_pairs(
    cells: Mapping[tuple[str, str, str, str, str], Mapping[str, Any]],
    *,
    block_ids: Sequence[str],
    agent_id: str,
    budget_mode: str,
    lifecycle: str,
    metric: str,
) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    for block_id in block_ids:
        idle = cells.get((block_id, agent_id, budget_mode, "idle", lifecycle))
        loaded = cells.get((block_id, agent_id, budget_mode, "loaded", lifecycle))
        if idle is None or loaded is None:
            raise ValueError(f"incomplete load pair: {block_id}/{agent_id}")
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
                raise ValueError(f"independent load pair is unmatched on {field}")
        pairs.append(
            {
                "block_id": block_id,
                "load_batch_id": str(idle_row["load_batch_id"]),
                "session_bundle_id": str(idle_row["session_bundle_id"]),
                "idle": _metric(idle, metric),
                "loaded": _metric(loaded, metric),
                "idle_decisions": len(idle["decisions"]),
                "loaded_decisions": len(loaded["decisions"]),
            }
        )
    return pairs


def independent_load_estimate(
    cases: Iterable[Mapping[str, Any]],
    *,
    agent_id: str,
    budget_mode: str,
    lifecycle: str,
    metric: str,
) -> dict[str, Any]:
    """Legacy one-endpoint check retained for small audits."""

    materialized = list(cases)
    cells = _main_cells(materialized)
    block_ids = sorted(
        {
            key[0]
            for key in cells
            if key[1] == agent_id and key[2] == budget_mode and key[4] == lifecycle
        }
    )
    pairs = _load_pairs(
        cells,
        block_ids=block_ids,
        agent_id=agent_id,
        budget_mode=budget_mode,
        lifecycle=lifecycle,
        metric=metric,
    )
    differences = [float(pair["loaded"] - pair["idle"]) for pair in pairs]
    batches: dict[str, list[float]] = defaultdict(list)
    for pair, difference in zip(pairs, differences):
        batches[pair["load_batch_id"]].append(difference)
    if not differences:
        raise ValueError("no paired observations")
    return {
        "estimate": _average(differences),
        "block_count": len(differences),
        "load_batch_count": len(batches),
        "batch_means": {
            key: _average(values) for key, values in sorted(batches.items())
        },
    }


def _ratio_of_means(pairs: Sequence[Mapping[str, Any]]) -> float:
    if not pairs:
        raise ValueError("independent ratio of means has no pairs")
    denominator = _average([float(pair["idle"]) for pair in pairs])
    if denominator <= 0.0:
        raise ValueError("independent wall-work ratio denominator is not positive")
    return _average([float(pair["loaded"]) for pair in pairs]) / denominator - 1.0


def _validate_panel_result(result: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(result, Mapping) or result.get("schema_version") != "state-panel-result-1.0.0":
        raise ValueError("independent reaggregation refuses repeatability schema drift")
    if set(result) != REPEATABILITY_RESULT_FIELDS:
        raise ValueError("independent repeatability result fields differ")
    row = result.get("schedule_row")
    if not isinstance(row, Mapping) or row.get("schema_version") != "repeatability-row-1.0.0":
        raise ValueError("independent reaggregation refuses repeatability-row schema drift")
    if set(row) != REPEATABILITY_ROW_FIELDS:
        raise ValueError("independent repeatability row fields differ")
    if result.get("case_id") != row.get("repeatability_case_id"):
        raise ValueError("repeatability result/row identity mismatch")
    if result.get("terminal_status") not in {"ok", "deadline_no_work"}:
        raise ValueError("repeatability result is not a usable terminal result")
    if result.get("eligible") is not True or result.get("cleanup_succeeded") is not True:
        raise ValueError("repeatability result eligibility/cleanup failed")
    if result.get("state_artifact_sha256") != row.get("state_artifact_sha256"):
        raise ValueError("repeatability state artifact differs from frozen row")
    action_hash = result.get("selected_action_hash")
    if (
        not isinstance(action_hash, str)
        or len(action_hash) != 64
        or any(character not in "0123456789abcdef" for character in action_hash)
    ):
        raise ValueError("repeatability action hash is invalid")
    supplied_hash = result.get("artifact_sha256")
    artifact_payload = dict(result)
    artifact_payload.pop("artifact_sha256", None)
    if supplied_hash != hash_json(artifact_payload):
        raise ValueError("repeatability result artifact hash mismatch")
    return row


def _validate_panel_inventory(
    results: Sequence[Mapping[str, Any]], agents: Sequence[str]
) -> tuple[dict[tuple[str, str, str, str, str, int], Mapping[str, Any]], dict[str, int]]:
    cells: dict[tuple[str, str, str, str, str, int], Mapping[str, Any]] = {}
    state_sources: dict[str, str] = {}
    source_states: dict[str, str] = {}
    load_batches: set[str] = set()
    for result in results:
        row = _validate_panel_result(result)
        if row.get("agent_id") not in agents:
            raise ValueError("repeatability result has an unexpected agent")
        if row.get("budget_mode") not in {"wall_clock", "fixed_work"}:
            raise ValueError("repeatability budget mode is invalid")
        if row.get("load_condition") not in {"idle", "loaded"}:
            raise ValueError("repeatability load condition is invalid")
        if row.get("lifecycle") not in {"fresh", "persistent"}:
            raise ValueError("repeatability lifecycle is invalid")
        repeat = row.get("repeat_index")
        if isinstance(repeat, bool) or not isinstance(repeat, int) or not 0 <= repeat < 10:
            raise ValueError("repeatability repeat index is invalid")
        state = str(row["state_id"])
        source = str(row["source_game_id"])
        if state_sources.setdefault(state, source) != source:
            raise ValueError("repeatability state/source mapping changed")
        if source_states.setdefault(source, state) != state:
            raise ValueError("multiple states share a source game")
        key = (
            state,
            str(row["agent_id"]),
            str(row["budget_mode"]),
            str(row["load_condition"]),
            str(row["lifecycle"]),
            repeat,
        )
        if key in cells:
            raise ValueError(f"duplicate repeatability result: {key}")
        cells[key] = result
        load_batches.add(str(row["load_batch_id"]))
    expected = set(
        product(
            agents,
            ("wall_clock", "fixed_work"),
            ("idle", "loaded"),
            ("fresh", "persistent"),
            range(10),
        )
    )
    for state in state_sources:
        observed = {
            (key[1], key[2], key[3], key[4], key[5])
            for key in cells
            if key[0] == state
        }
        if observed != expected:
            raise ValueError(f"repeatability state {state} is factorially incomplete")
    if not state_sources:
        raise ValueError("repeatability reaggregation has no states")
    return cells, {
        "result_count": len(results),
        "state_count": len(state_sources),
        "source_game_count": len(source_states),
        "state_agent_count": len(state_sources) * len(agents),
        "load_batch_count": len(load_batches),
    }


def _within_disagreement(hashes: Sequence[str]) -> float:
    if len(hashes) != 10:
        raise ValueError("independent divergence requires exactly ten repeats")
    values = [
        float(hashes[left] != hashes[right])
        for left in range(10)
        for right in range(left + 1, 10)
    ]
    return _average(values)


def _cross_disagreement(left: Sequence[str], right: Sequence[str]) -> float:
    if len(left) != 10 or len(right) != 10:
        raise ValueError("independent cross divergence requires ten-by-ten repeats")
    return _average([float(a != b) for a in left for b in right])


def independent_confirmatory_reaggregation(
    cases: Iterable[Mapping[str, Any]],
    repeatability_results: Iterable[Mapping[str, Any]],
    *,
    agents: Sequence[str],
    expected_block_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Independently reproduce all ten point estimates and inventory counts."""

    frozen_agents = tuple(map(str, agents))
    if len(frozen_agents) != 3 or len(set(frozen_agents)) != 3:
        raise ValueError("independent confirmatory reaggregation requires three agents")
    materialized_cases = list(cases)
    materialized_results = list(repeatability_results)
    cells = _main_cells(materialized_cases)
    if {key[1] for key in cells} != set(frozen_agents):
        raise ValueError("main raw agent inventory differs from frozen agents")
    block_ids = sorted({key[0] for key in cells})
    if expected_block_ids is not None and set(block_ids) != set(map(str, expected_block_ids)):
        raise ValueError("main raw block inventory differs from frozen schedule")
    expected_main_cells = set(
        product(
            frozen_agents,
            ("wall_clock", "fixed_work"),
            ("idle", "loaded"),
            ("fresh", "persistent"),
        )
    )
    for block_id in block_ids:
        observed = {
            (key[1], key[2], key[3], key[4]) for key in cells if key[0] == block_id
        }
        if observed != expected_main_cells:
            raise ValueError(f"main raw block {block_id} is factorially incomplete")
        block_cases = [case for key, case in cells.items() if key[0] == block_id]
        for field in (
            "environment_seed",
            "physical_seat",
            "play_order",
            "load_batch_id",
            "session_bundle_id",
            "sequence_index",
        ):
            if len({case["schedule_row"][field] for case in block_cases}) != 1:
                raise ValueError(f"main raw block {block_id} is unmatched on {field}")
    if not block_ids:
        raise ValueError("main reaggregation has no blocks")
    main_load_batches = {
        str(case["schedule_row"]["load_batch_id"]) for case in materialized_cases
    }
    panel_cells, panel_inventory = _validate_panel_inventory(
        materialized_results, frozen_agents
    )
    state_ids = sorted({key[0] for key in panel_cells})

    estimands: list[dict[str, Any]] = []
    total_zero_games = 0
    total_wall_games = 0
    for lifecycle in ("fresh", "persistent"):
        work_pairs = {
            agent: _load_pairs(
                cells,
                block_ids=block_ids,
                agent_id=agent,
                budget_mode="wall_clock",
                lifecycle=lifecycle,
                metric="mean_decision_work",
            )
            for agent in frozen_agents
        }
        work_ratios = {
            agent: _ratio_of_means(work_pairs[agent]) for agent in frozen_agents
        }
        sensitivity_pairs = {
            agent: [
                pair
                for pair in work_pairs[agent]
                if pair["idle_decisions"] > 0 and pair["loaded_decisions"] > 0
            ]
            for agent in frozen_agents
        }
        sensitivity_ratios = {
            agent: (
                _ratio_of_means(sensitivity_pairs[agent])
                if sensitivity_pairs[agent]
                else None
            )
            for agent in frozen_agents
        }
        zero_games = sum(
            int(pair["idle_decisions"] == 0) + int(pair["loaded_decisions"] == 0)
            for pairs in work_pairs.values()
            for pair in pairs
        )
        wall_games = 2 * len(block_ids) * len(frozen_agents)
        total_zero_games += zero_games
        total_wall_games += wall_games
        estimands.append(
            {
                "estimand_id": f"wall_work_ratio_{lifecycle}_equal_agent",
                "estimate": _average([work_ratios[agent] for agent in frozen_agents]),
                "inventory": {
                    "agent_count": len(frozen_agents),
                    "matched_block_count": len(block_ids),
                    "load_batch_count": len(main_load_batches),
                    "contributing_case_count": wall_games,
                    "zero_eligible_decision_game_count": zero_games,
                    "zero_eligible_decision_game_rate": zero_games / wall_games,
                    "nonzero_complete_pair_count_by_agent": {
                        agent: len(sensitivity_pairs[agent]) for agent in frozen_agents
                    },
                },
                "per_agent_estimates": work_ratios,
                "zero_decision_sensitivity": {
                    "method": "exclude complete load pairs if either game has zero eligible decisions",
                    "per_agent_ratios": sensitivity_ratios,
                    "equal_agent_estimate": (
                        _average(
                            [float(sensitivity_ratios[agent]) for agent in frozen_agents]
                        )
                        if all(sensitivity_ratios[agent] is not None for agent in frozen_agents)
                        else None
                    ),
                    "complete_pair_count_by_agent": {
                        agent: len(sensitivity_pairs[agent]) for agent in frozen_agents
                    },
                },
            }
        )

        score_effects: dict[str, dict[str, float]] = {}
        for budget_mode, label in (("wall_clock", "wall"), ("fixed_work", "fixed")):
            by_agent: dict[str, float] = {}
            for agent in frozen_agents:
                pairs = _load_pairs(
                    cells,
                    block_ids=block_ids,
                    agent_id=agent,
                    budget_mode=budget_mode,
                    lifecycle=lifecycle,
                    metric="score",
                )
                by_agent[agent] = _average(
                    [float(pair["loaded"] - pair["idle"]) for pair in pairs]
                )
            score_effects[budget_mode] = by_agent
            estimands.append(
                {
                    "estimand_id": f"{label}_score_load_effect_{lifecycle}_equal_agent",
                    "estimate": _average([by_agent[agent] for agent in frozen_agents]),
                    "inventory": {
                        "agent_count": len(frozen_agents),
                        "matched_block_count": len(block_ids),
                        "load_batch_count": len(main_load_batches),
                        "contributing_case_count": 2
                        * len(block_ids)
                        * len(frozen_agents),
                    },
                    "per_agent_estimates": by_agent,
                }
            )
        attenuation = {
            agent: score_effects["wall_clock"][agent]
            - score_effects["fixed_work"][agent]
            for agent in frozen_agents
        }
        estimands.append(
            {
                "estimand_id": f"score_attenuation_{lifecycle}_equal_agent",
                "estimate": _average([attenuation[agent] for agent in frozen_agents]),
                "inventory": {
                    "agent_count": len(frozen_agents),
                    "matched_block_count": len(block_ids),
                    "load_batch_count": len(main_load_batches),
                    "contributing_case_count": 4
                    * len(block_ids)
                    * len(frozen_agents),
                },
                "per_agent_estimates": attenuation,
            }
        )

        state_values: list[float] = []
        selected_batches: set[str] = set()
        for state in state_ids:
            agent_values: list[float] = []
            for agent in frozen_agents:
                hashes: dict[str, list[str]] = {}
                for load in ("idle", "loaded"):
                    ordered_hashes: list[str] = []
                    for repeat in range(10):
                        result = panel_cells[(
                            state,
                            agent,
                            "wall_clock",
                            load,
                            lifecycle,
                            repeat,
                        )]
                        row = _validate_panel_result(result)
                        selected_batches.add(str(row["load_batch_id"]))
                        ordered_hashes.append(str(result["selected_action_hash"]))
                    hashes[load] = ordered_hashes
                agent_values.append(
                    _cross_disagreement(hashes["idle"], hashes["loaded"])
                    - 0.5
                    * (
                        _within_disagreement(hashes["idle"])
                        + _within_disagreement(hashes["loaded"])
                    )
                )
            state_values.append(_average(agent_values))
        estimands.append(
            {
                "estimand_id": f"wall_action_excess_divergence_{lifecycle}_equal_agent",
                "estimate": _average(state_values),
                "inventory": {
                    "agent_count": len(frozen_agents),
                    "state_count": len(state_ids),
                    "source_game_count": panel_inventory["source_game_count"],
                    "state_agent_count": len(state_ids) * len(frozen_agents),
                    "load_batch_count": len(selected_batches),
                    "contributing_result_count": 2
                    * 10
                    * len(frozen_agents)
                    * len(state_ids),
                    "repeats_per_envelope": 10,
                },
            }
        )

    ordered = sorted(
        estimands,
        key=lambda record: CONFIRMATORY_ESTIMAND_IDS.index(record["estimand_id"]),
    )
    if [record["estimand_id"] for record in ordered] != list(CONFIRMATORY_ESTIMAND_IDS):
        raise RuntimeError("independent confirmatory endpoint inventory did not reconcile")
    inventory_counts = {
        "agent_count": len(frozen_agents),
        "main_case_count": len(materialized_cases),
        "main_matched_block_count": len(block_ids),
        "main_load_batch_count": len(main_load_batches),
        "zero_eligible_decision_game_count": total_zero_games,
        "zero_eligible_decision_game_rate": total_zero_games / total_wall_games,
        "repeatability_result_count": panel_inventory["result_count"],
        "repeatability_state_count": panel_inventory["state_count"],
        "repeatability_source_game_count": panel_inventory["source_game_count"],
        "repeatability_state_agent_count": panel_inventory["state_agent_count"],
        "repeatability_load_batch_count": panel_inventory["load_batch_count"],
        "repeats_per_envelope": 10,
    }
    payload: dict[str, Any] = {
        "schema_version": "independent-confirmatory-reaggregation-1.0.0",
        "reaggregation_version": REAGGREGATION_VERSION,
        "work_outcome": "per_game_mean_completed_work_per_eligible_decision_zero_if_none",
        "confirmatory_estimand_ids": list(CONFIRMATORY_ESTIMAND_IDS),
        "inventory_counts": inventory_counts,
        "estimands": ordered,
    }
    payload["content_hash"] = hash_json(payload)
    return payload


def _assert_equal_nested(
    expected: Any,
    observed: Any,
    *,
    label: str,
    tolerance: float,
) -> None:
    if isinstance(expected, Mapping):
        if not isinstance(observed, Mapping) or set(expected) != set(observed):
            raise ValueError(f"{label} object inventory differs")
        for key in expected:
            _assert_equal_nested(
                expected[key], observed[key], label=f"{label}.{key}", tolerance=tolerance
            )
        return
    if isinstance(expected, list):
        if not isinstance(observed, list) or len(expected) != len(observed):
            raise ValueError(f"{label} array inventory differs")
        for index, (left, right) in enumerate(zip(expected, observed)):
            _assert_equal_nested(
                left, right, label=f"{label}[{index}]", tolerance=tolerance
            )
        return
    if (
        isinstance(expected, (int, float))
        and not isinstance(expected, bool)
        and isinstance(observed, (int, float))
        and not isinstance(observed, bool)
    ):
        if not math.isclose(
            float(expected), float(observed), rel_tol=0.0, abs_tol=tolerance
        ):
            raise ValueError(f"{label} numeric value differs")
        return
    if expected != observed:
        raise ValueError(f"{label} differs")


def verify_confirmatory_summary(
    summary: Mapping[str, Any],
    recomputed: Mapping[str, Any],
    *,
    tolerance: float = 1e-12,
) -> dict[str, Any]:
    """Verify every frozen headline estimate and inventory count independently."""

    if recomputed.get("schema_version") != "independent-confirmatory-reaggregation-1.0.0":
        raise ValueError("unexpected independent reaggregation schema")
    recomputed_payload = dict(recomputed)
    supplied_recomputed_hash = recomputed_payload.pop("content_hash", None)
    if supplied_recomputed_hash != hash_json(recomputed_payload):
        raise ValueError("independent reaggregation content hash mismatch")
    if summary.get("schema_version") != "locked-analysis-summary-1.0.0":
        raise ValueError("unexpected frozen analysis summary schema")
    if summary.get("freeze_status") != "FROZEN_ANALYSIS_SUMMARY":
        raise ValueError("independent reaggregation refuses an unfrozen summary")
    summary_payload = dict(summary)
    supplied_summary_hash = summary_payload.pop("content_hash", None)
    if supplied_summary_hash != hash_json(summary_payload):
        raise ValueError("frozen analysis summary content hash mismatch")
    if summary.get("analysis_version") != EXPECTED_ANALYSIS_VERSION:
        raise ValueError("frozen summary analysis version differs from independent lock")
    if summary.get("confirmatory_estimand_ids") != list(CONFIRMATORY_ESTIMAND_IDS):
        raise ValueError("frozen summary confirmatory family differs from independent lock")
    if recomputed.get("confirmatory_estimand_ids") != list(CONFIRMATORY_ESTIMAND_IDS):
        raise ValueError("recomputed confirmatory family differs from independent lock")
    _assert_equal_nested(
        summary.get("inventory_counts"),
        recomputed.get("inventory_counts"),
        label="overall inventory",
        tolerance=tolerance,
    )
    summary_estimands = list(summary.get("estimands", ()))
    recomputed_estimands = list(recomputed.get("estimands", ()))
    if [row.get("estimand_id") for row in summary_estimands] != list(
        CONFIRMATORY_ESTIMAND_IDS
    ) or [row.get("estimand_id") for row in recomputed_estimands] != list(
        CONFIRMATORY_ESTIMAND_IDS
    ):
        raise ValueError("headline estimand order/inventory differs")
    for expected, observed in zip(summary_estimands, recomputed_estimands):
        _assert_equal_nested(
            expected.get("estimate"),
            observed.get("estimate"),
            label=f"{expected['estimand_id']}.estimate",
            tolerance=tolerance,
        )
        _assert_equal_nested(
            expected.get("inventory"),
            observed.get("inventory"),
            label=f"{expected['estimand_id']}.inventory",
            tolerance=tolerance,
        )
    payload: dict[str, Any] = {
        "schema_version": "independent-reaggregation-verification-1.0.0",
        "reaggregation_version": REAGGREGATION_VERSION,
        "summary_content_hash": supplied_summary_hash,
        "reaggregation_content_hash": supplied_recomputed_hash,
        "verified_estimand_ids": list(CONFIRMATORY_ESTIMAND_IDS),
        "verified_estimand_count": len(CONFIRMATORY_ESTIMAND_IDS),
        "verified_inventory_counts": dict(recomputed["inventory_counts"]),
        "all_headline_points_and_counts_match": True,
    }
    payload["content_hash"] = hash_json(payload)
    return payload


def verify_headline(
    expected: Mapping[str, Any],
    recomputed: Mapping[str, Any],
    *,
    tolerance: float = 1e-12,
) -> None:
    if expected.get("block_count") != recomputed.get("block_count"):
        raise ValueError("headline block counts differ")
    if expected.get("load_batch_count") != recomputed.get("load_batch_count"):
        raise ValueError("headline load-batch counts differ")
    if abs(float(expected["estimate"]) - float(recomputed["estimate"])) > tolerance:
        raise ValueError("headline estimate failed independent reaggregation")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", action="append", required=True, help="main outcome JSONL")
    parser.add_argument("--repeatability-raw", action="append")
    parser.add_argument("--agents", help="comma-separated frozen three-agent order")
    parser.add_argument("--agent")
    parser.add_argument("--budget-mode", choices=("wall_clock", "fixed_work"))
    parser.add_argument("--lifecycle", choices=("fresh", "persistent"))
    parser.add_argument("--metric", choices=("score", "mean_decision_work"))
    parser.add_argument("--expected", help="frozen summary or legacy headline JSON")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    if args.repeatability_raw:
        if not args.agents:
            parser.error("confirmatory reaggregation requires --agents")
        result = independent_confirmatory_reaggregation(
            read_jsonl(args.raw),
            read_jsonl(args.repeatability_raw),
            agents=tuple(value.strip() for value in args.agents.split(",")),
        )
        output: Mapping[str, Any] = result
        if args.expected:
            summary = json.loads(Path(args.expected).read_text(encoding="ascii"))
            output = verify_confirmatory_summary(summary, result)
    else:
        if not all((args.agent, args.budget_mode, args.lifecycle, args.metric)):
            parser.error(
                "legacy one-endpoint mode requires --agent, --budget-mode, --lifecycle, and --metric"
            )
        result = independent_load_estimate(
            read_jsonl(args.raw),
            agent_id=args.agent,
            budget_mode=args.budget_mode,
            lifecycle=args.lifecycle,
            metric=args.metric,
        )
        if args.expected:
            expected = json.loads(Path(args.expected).read_text(encoding="ascii"))
            verify_headline(expected, result)
        output = {
            "schema_version": "independent-reaggregation-1.0.0",
            **result,
        }
        output["content_hash"] = hash_json(output)
    Path(args.output).write_bytes(canonical_json_bytes(dict(output)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
