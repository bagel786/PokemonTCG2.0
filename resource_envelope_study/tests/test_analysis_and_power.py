from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import pytest

from resource_envelope_study.analysis import (
    CONFIRMATORY_ESTIMAND_IDS,
    AnalysisLock,
    ClusteredBlockVector,
    build_analysis_outcome_hash_manifest,
    build_frozen_analysis_summary,
    budget_sensitivity_interaction,
    common_resample_max_t_intervals,
    confirmatory_point_estimates,
    cross_envelope_disagreement,
    equal_agent_state_values,
    equal_agent_wall_work_ratio,
    equivalence_decision,
    hierarchical_cluster_bootstrap,
    paired_load_contrasts,
    rank_reversal_from_joint_intervals,
    run_locked_analysis,
    state_cluster_bootstrap,
    state_level_divergence,
    verify_frozen_analysis_summary,
    within_envelope_disagreement,
)
from resource_envelope_study.canonical import (
    canonical_json_bytes,
    hash_file,
    hash_json,
    write_canonical_json,
)
from resource_envelope_study.plots import (
    build_plot_source_inventory,
    render_publication_plots,
)
from resource_envelope_study.power import (
    BinaryPairedPowerInputs,
    ClusteredSchedulerPowerInputs,
    paired_binary_block_requirement,
    simulate_clustered_scheduler_power,
)
from resource_envelope_study.repeatability import (
    EnvelopeSpec,
    FrozenStateSpec,
    RepeatabilityConfig,
    build_repeatability_manifest,
)
from resource_envelope_study.reaggregate import (
    independent_confirmatory_reaggregation,
    independent_load_estimate,
    verify_confirmatory_summary,
    verify_headline,
)
from resource_envelope_study.scheduler import ScheduleConfig, build_schedule


def _case(
    block: int,
    budget: str,
    load: str,
    score: float,
    work: int,
    *,
    agent: str = "a",
    decision_count: int = 2,
    lifecycle: str = "fresh",
):
    case_id = f"{block}-{agent}-{budget}-{load}-{lifecycle}"
    requested_budget = 10_000_000 if budget == "wall_clock" else None
    requested_work = work if budget == "fixed_work" else None
    lifecycle_id = f"life-{block}-{agent}-{budget}-{load}-{lifecycle}"
    decisions = [
        {
            "schema_version": "decision-1.1.0",
            "case_id": case_id,
            "block_id": f"b{block}",
            "decision_index": index,
            "agent_id": agent,
            "budget_mode": budget,
            "load_condition": load,
            "lifecycle": lifecycle,
            "lifecycle_id": lifecycle_id,
            "process_instance_id": lifecycle_id,
            "worker_pid": 1,
            "sequence_index": block % 2,
            "load_batch_id": f"batch-{block // 2}",
            "requested_budget_ns": requested_budget,
            "requested_work_units": requested_work,
            "terminal_status": "ok",
            "completed_work_units": work,
            "completed_simulations": work,
            "completed_nodes": work,
            "completed_sweeps": 0,
            "forward_model_calls": work,
            "setup_wall_ns": 1,
            "search_wall_ns": 1,
            "selection_wall_ns": 1,
            "cleanup_wall_ns": 1,
            "process_cpu_ns": 1,
            "overshoot_ns": 0,
            "state_hash": hash_json({"case": case_id, "decision": index}),
            "agent_seed_hash": hash_json({"agent": agent, "block": block}),
            "selected_action": [0],
            "selected_action_hash": hash_json({"action": 0}),
            "value_estimates": [0.0],
            "timeout_reason": "",
            "fallback_reason": "",
            "cleanup_succeeded": True,
            "instrumentation_enabled": True,
            "work_counters_collected": True,
            "error_type": "",
            "error_message": "",
            "extra": {},
        }
        for index in range(decision_count)
    ]
    result = {
        "schedule_row": {
            "schema_version": "schedule-row-1.0.0",
            "phase": "smoke",
            "case_id": case_id,
            "block_id": f"b{block}",
            "block_index": block,
            "agent_id": agent,
            "budget_mode": budget,
            "load_condition": load,
            "lifecycle": lifecycle,
            "environment_seed": block,
            "agent_seed": block + 100,
            "schedule_seed": block + 200,
            "load_seed": block // 2 + 300,
            "physical_seat": block % 2,
            "play_order": (block // 2) % 2,
            "load_batch_id": f"batch-{block // 2}",
            "load_period_order": "idle_then_loaded",
            "lifecycle_pair_id": f"pair-{block}-{agent}-{budget}-{load}",
            "sequence_pair_id": f"sequence-{block}-{agent}-{budget}",
            "session_bundle_id": f"bundle-{block // 2}",
            "lifecycle_id": lifecycle_id,
            "process_instance_id": lifecycle_id,
            "sequence_index": block % 2,
            "execution_index": 0,
            "requested_budget_ns": requested_budget,
            "requested_work_units": requested_work,
        },
        "game": {
            "schema_version": "game-1.0.0",
            "case_id": case_id,
            "block_id": f"b{block}",
            "agent_id": agent,
            "terminal_status": "completed",
            "score": score,
            "winner": 1 if score == 1 else (2 if score == 0 else None),
            "decision_count": decision_count,
            "completed_work_units": work * decision_count,
            "completed_simulations": work * decision_count,
            "completed_nodes": work * decision_count,
            "completed_sweeps": 0,
            "forward_model_calls": work * decision_count,
            "decision_record_hashes": [hash_json(decision) for decision in decisions],
            "error_type": "",
            "error_message": "",
        },
        "decisions": decisions,
        "gameplay_decisions": decision_count,
        "public_trace_sha256": hash_json({"trace": case_id}),
        "observed_worker": {"worker_pid": 1},
    }
    result["artifact_sha256"] = hash_json(result)
    return result


def _cases():
    rows = []
    for block in range(4):
        for budget in ("wall_clock", "fixed_work"):
            rows.append(_case(block, budget, "idle", 0.0, 10))
            rows.append(
                _case(
                    block,
                    budget,
                    "loaded",
                    1.0 if budget == "wall_clock" else 0.0,
                    6 if budget == "wall_clock" else 10,
                )
            )
    return rows


def _panel_result(
    state: int,
    agent: str,
    budget: str,
    load: str,
    lifecycle: str,
    repeat: int,
    action: str,
) -> dict:
    case_id = f"repeat-{state}-{agent}-{budget}-{load}-{lifecycle}-{repeat}"
    state_hash = hash_json({"state": state})
    history_hash = hash_json({"history": state})
    requested_budget = 10_000_000 if budget == "wall_clock" else None
    requested_work = 10 if budget == "fixed_work" else None
    session_id = f"session-{case_id}"
    row = {
        "schema_version": "repeatability-row-1.0.0",
        "repeatability_case_id": case_id,
        "bank_id": "test-panel",
        "inference_unit_id": f"s{state}",
        "state_id": f"s{state}",
        "source_game_id": f"g{state}",
        "state_artifact_sha256": state_hash,
        "state_seed": state + 10,
        "history_prefix_sha256": history_hash,
        "history_seed": state + 20,
        "history_length": 0,
        "pseudo_sequence_slot": 0,
        "sequence_index": 0,
        "agent_id": agent,
        "agent_seed": state + 30,
        "budget_mode": budget,
        "load_condition": load,
        "lifecycle": lifecycle,
        "repeat_index": repeat,
        "envelope_id": f"{budget}-{load}-{lifecycle}",
        "resource_profile_sha256": hash_json(
            {"budget": budget, "load": load, "lifecycle": lifecycle}
        ),
        "requested_budget_ns": requested_budget,
        "requested_work_units": requested_work,
        "session_id": session_id,
        "process_instance_id": session_id,
        "session_seed": repeat + 100,
        "schedule_seed": repeat + 200,
        "load_batch_id": f"panel-batch-{state % 2}",
        "load_seed": state + 300,
        "load_period_order": "idle_then_loaded",
        "execution_index": 0,
    }
    result = {
        "schema_version": "state-panel-result-1.0.0",
        "case_id": case_id,
        "manifest_content_hash": hash_json({"manifest": "test"}),
        "schedule_row": row,
        "state_artifact_sha256": state_hash,
        "history_prefix_sha256": history_hash if lifecycle == "persistent" else None,
        "budget_mode": budget,
        "requested_budget_ns": requested_budget,
        "requested_work_units": requested_work,
        "terminal_status": "ok",
        "eligible": True,
        "completed_work_units": requested_work if requested_work is not None else 5,
        "completed_simulations": 1,
        "completed_nodes": 1,
        "forward_model_calls": 1,
        "search_wall_ns": 1,
        "overshoot_ns": 0,
        "state_hash": state_hash,
        "cleanup_succeeded": True,
        "selected_action_hash": hash_json({"action": action}),
        "warmup_steps_completed": 0,
        "warmup_consumed_sha256": history_hash if lifecycle == "persistent" else None,
        "warmup_replay_sha256": (
            hash_json({"warmup": state, "agent": agent, "budget": budget, "repeat": repeat})
            if lifecycle == "persistent"
            else None
        ),
        "observed_worker": {"worker_pid": 1},
    }
    result["artifact_sha256"] = hash_json(result)
    return result


def test_block_level_contrasts_and_independent_reaggregation_agree() -> None:
    cases = _cases()
    work = paired_load_contrasts(
        cases,
        agent_id="a",
        budget_mode="wall_clock",
        lifecycle="fresh",
        metric="mean_decision_work",
    )
    assert [row.value for row in work] == [-4.0] * 4
    score = paired_load_contrasts(
        cases,
        agent_id="a",
        budget_mode="wall_clock",
        lifecycle="fresh",
        metric="score",
    )
    independent = independent_load_estimate(
        cases,
        agent_id="a",
        budget_mode="wall_clock",
        lifecycle="fresh",
        metric="score",
    )
    expected = hierarchical_cluster_bootstrap(
        score,
        AnalysisLock(bootstrap_replicates=1_999),
    )
    verify_headline(expected, independent)
    assert expected["estimate"] == 1.0
    interaction = budget_sensitivity_interaction(
        cases, agent_id="a", lifecycle="fresh", metric="mean_decision_work"
    )
    assert [row.value for row in interaction] == [-4.0] * 4


def test_incomplete_block_and_individual_decision_weighting_fail_closed() -> None:
    cases = _cases()
    cases.pop()
    with pytest.raises(ValueError, match="lacks a paired"):
        paired_load_contrasts(
            cases,
            agent_id="a",
            budget_mode="fixed_work",
            lifecycle="fresh",
            metric="score",
        )


def test_state_is_unit_for_repeatability_divergence() -> None:
    rows = []
    for state in range(3):
        for load in ("idle", "loaded"):
            for repeat in range(10):
                rows.append(
                    _panel_result(
                        state,
                        "a",
                        "wall_clock",
                        load,
                        "fresh",
                        repeat,
                        "x" if load == "idle" else ("y" if state == 0 else "x"),
                    )
                )
    state_rows = state_level_divergence(
        rows,
        left_envelope="wall_clock-idle-fresh",
        right_envelope="wall_clock-loaded-fresh",
    )
    assert len(state_rows) == 3
    assert state_rows[0]["cross"] == 1.0
    assert within_envelope_disagreement(["x"] * 10) == 0.0
    assert cross_envelope_disagreement(["x"] * 10, ["y"] * 10) == 1.0
    assert equivalence_decision([-0.01, 0.02], 0.05) == "equivalent"


def test_power_calculation_reproduces_conservative_385_block_case() -> None:
    result = paired_binary_block_requirement(BinaryPairedPowerInputs())
    assert result["independent_block_requirement"] == 385
    assert result["recommended_blocks_per_cell"] == 388
    assert result["disposition"] == "NARROW_OR_EXTEND"
    assert math.isclose(result["variance_of_paired_difference"], 0.49)


def test_wall_work_is_ratio_of_agent_means_without_scale_pooling() -> None:
    cases = []
    scales = {
        "small": (10, 5),
        "medium": (100, 80),
        "large": (1_000, 900),
    }
    for block in range(4):
        for agent, (idle, loaded) in scales.items():
            cases.append(_case(block, "wall_clock", "idle", 0.5, idle, agent=agent))
            cases.append(_case(block, "wall_clock", "loaded", 0.5, loaded, agent=agent))
    result = equal_agent_wall_work_ratio(
        cases,
        agents=tuple(scales),
        lifecycle="fresh",
        expected_block_ids={f"b{index}" for index in range(4)},
    )
    assert math.isclose(result["per_agent_ratios"]["small"], -0.5)
    assert math.isclose(result["per_agent_ratios"]["medium"], -0.2)
    assert math.isclose(result["per_agent_ratios"]["large"], -0.1)
    assert math.isclose(result["estimate"], (-0.5 - 0.2 - 0.1) / 3.0)
    pooled = (5 + 80 + 900) / (10 + 100 + 1_000) - 1.0
    assert not math.isclose(result["estimate"], pooled)
    assert result["raw_work_counts_pooled_across_agents"] is False


def test_zero_decision_game_contributes_zero_mean_work_without_block_deletion() -> None:
    cases = []
    for agent in ("a", "b"):
        cases.extend(
            [
                _case(0, "wall_clock", "idle", 0.5, 0, agent=agent, decision_count=0),
                _case(0, "wall_clock", "loaded", 0.5, 0, agent=agent, decision_count=0),
                _case(1, "wall_clock", "idle", 0.5, 4, agent=agent),
                _case(1, "wall_clock", "loaded", 0.5, 2, agent=agent),
            ]
        )
    result = equal_agent_wall_work_ratio(
        cases,
        agents=("a", "b"),
        lifecycle="fresh",
    )
    assert result["estimate"] == -0.5
    assert result["zero_eligible_decision_game_count"] == 4
    assert result["zero_eligible_decision_game_rate"] == 0.5
    assert result["zero_decision_sensitivity"]["equal_agent_estimate"] == -0.5
    # The primary per-game mean retains both blocks, including block 0.
    contrasts = paired_load_contrasts(
        cases,
        agent_id="a",
        budget_mode="wall_clock",
        lifecycle="fresh",
        metric="mean_decision_work",
        expected_block_ids=("b0", "b1"),
    )
    assert len(contrasts) == 2
    assert contrasts[0].value == 0.0


def test_outcome_schema_drift_fails_before_analysis() -> None:
    cases = _cases()
    cases[0] = copy.deepcopy(cases[0])
    cases[0]["game"]["schema_version"] = "game-2.0.0"
    with pytest.raises(ValueError, match="unexpected game outcome schema"):
        paired_load_contrasts(
            cases,
            agent_id="a",
            budget_mode="wall_clock",
            lifecycle="fresh",
            metric="score",
        )


def test_rehashed_fields_cannot_bypass_per_record_artifact_hashes() -> None:
    cases = _cases()
    cases[0] = copy.deepcopy(cases[0])
    cases[0]["game"]["score"] = 0.5
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        independent_load_estimate(
            cases,
            agent_id="a",
            budget_mode="wall_clock",
            lifecycle="fresh",
            metric="score",
        )

    panel = [
        _panel_result(0, "a", "wall_clock", load, "fresh", repeat, "x")
        for load in ("idle", "loaded")
        for repeat in range(10)
    ]
    panel[0] = copy.deepcopy(panel[0])
    panel[0]["selected_action_hash"] = hash_json({"action": "tampered"})
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        state_level_divergence(
            panel,
            left_envelope="wall_clock-idle-fresh",
            right_envelope="wall_clock-loaded-fresh",
        )


def test_common_resampling_rejects_cluster_pseudoreplication() -> None:
    lock = AnalysisLock(bootstrap_replicates=1_999)
    one_batch = [
        ClusteredBlockVector("batch", f"bundle-{index // 2}", f"b{index}", {"x": float(index)})
        for index in range(20)
    ]
    with pytest.raises(ValueError, match="at least two load batches"):
        common_resample_max_t_intervals(one_batch, lock)

    vectors = [
        ClusteredBlockVector(
            f"batch-{index // 2}",
            f"bundle-{index // 2}",
            f"b{index}",
            {"x": float(index % 2), "y": float((index + 1) % 2)},
        )
        for index in range(4)
    ]
    result = common_resample_max_t_intervals(vectors, lock)
    assert result["simultaneous_method"] == "common_hierarchical_cluster_bootstrap_max_t"
    assert result["block_count"] == 4
    assert set(result["intervals"]) == {"x", "y"}


def _joint_interval_result(first: list[float], second: list[float]) -> dict:
    payload = {
        "schema_version": "simultaneous-intervals-1.0.0",
        "simultaneous_method": "common_hierarchical_cluster_bootstrap_max_t",
        "endpoint_ids": ["pair-wall", "pair-fixed"],
        "intervals": {
            "pair-wall": {"estimate": 0.1, "interval": first},
            "pair-fixed": {"estimate": -0.1, "interval": second},
        },
    }
    payload["content_hash"] = hash_json(payload)
    return payload


def test_rank_reversal_requires_joint_intervals_beyond_tie_margin() -> None:
    uncertain = rank_reversal_from_joint_intervals(
        _joint_interval_result([0.01, 0.20], [-0.20, -0.01]),
        comparisons={"a-minus-b": ("pair-wall", "pair-fixed")},
        tie_margin=0.05,
    )
    assert uncertain["comparisons"]["a-minus-b"]["rank_reversal"] is False
    supported = rank_reversal_from_joint_intervals(
        _joint_interval_result([0.06, 0.20], [-0.20, -0.06]),
        comparisons={"a-minus-b": ("pair-wall", "pair-fixed")},
        tie_margin=0.05,
    )
    assert supported["comparisons"]["a-minus-b"]["rank_reversal"] is True


def test_repeatability_bootstrap_resamples_states_not_repeat_pairs() -> None:
    rows = []
    agents = ("a", "b", "c")
    for state in range(4):
        for agent in agents:
            rows.append(
                {
                    "state_id": f"s{state}",
                    "source_game_id": f"g{state}",
                    "agent_id": agent,
                    "excess_cross_divergence": 0.1 * state,
                }
            )
    state_rows = equal_agent_state_values(rows, agents=agents)
    result = state_cluster_bootstrap(
        state_rows,
        AnalysisLock(bootstrap_replicates=1_999),
    )
    assert result["state_count"] == 4
    assert result["repeat_rows_resampled"] is False
    assert result["inference_unit"] == "frozen_state"


def test_clustered_power_uses_exact_scheduler_attrition_runtime_and_multiplicity() -> None:
    inputs = ClusteredSchedulerPowerInputs(
        agents=("a", "b", "c"),
        paired_disagreement_by_agent={"a": 0.5, "b": 0.5, "c": 0.5},
        candidate_block_counts=(80,),
        simulation_replicates=100,
        batch_icc=0.05,
        session_icc=0.05,
        seconds_per_case=0.1,
        total_runtime_budget_hours=10.0,
        analysis_reserve_hours=1.0,
    )
    first = simulate_clustered_scheduler_power(inputs)
    second = simulate_clustered_scheduler_power(inputs)
    assert first == second
    assert first["two_sided_member_alpha"] == pytest.approx(0.005)
    assert first["candidates"][0]["scheduled_case_count"] == 80 * 24
    assert first["assignment_hierarchy"].startswith("load_batch_to_common_session")
    assert "wall_work_ratio" in first["not_powered_by_this_artifact"]
    assert first["full_confirmatory_family_power_established"] is False
    assert first["freeze_authorized"] is False
    assert first["recommended_blocks_per_cell"] is None
    assert first["disposition"] == "NARROW_OR_EXTEND"


def _confirmatory_inputs() -> tuple[list[dict], list[dict], tuple[str, ...]]:
    agents = ("a", "b", "c")
    scales = {"a": (10, 5), "b": (100, 80), "c": (1_000, 900)}
    cases: list[dict] = []
    for block in range(4):
        for agent in agents:
            idle_work, loaded_work = scales[agent]
            for lifecycle in ("fresh", "persistent"):
                for budget in ("wall_clock", "fixed_work"):
                    for load in ("idle", "loaded"):
                        work = (
                            idle_work
                            if load == "idle"
                            else (loaded_work if budget == "wall_clock" else idle_work)
                        )
                        decision_count = (
                            0
                            if block == 0
                            and agent == "a"
                            and budget == "wall_clock"
                            and lifecycle == "fresh"
                            else 2
                        )
                        score = (
                            0.0
                            if load == "idle"
                            else (1.0 if budget == "wall_clock" else 0.5)
                        )
                        cases.append(
                            _case(
                                block,
                                budget,
                                load,
                                score,
                                work if decision_count else 0,
                                agent=agent,
                                decision_count=decision_count,
                                lifecycle=lifecycle,
                            )
                        )
    panel: list[dict] = []
    for state in range(2):
        for agent in agents:
            for lifecycle in ("fresh", "persistent"):
                for budget in ("wall_clock", "fixed_work"):
                    for load in ("idle", "loaded"):
                        for repeat in range(10):
                            panel.append(
                                _panel_result(
                                    state,
                                    agent,
                                    budget,
                                    load,
                                    lifecycle,
                                    repeat,
                                    (
                                        "y"
                                        if state == 0
                                        and budget == "wall_clock"
                                        and load == "loaded"
                                        else "x"
                                    ),
                                )
                            )
    return cases, panel, agents


def _summary_from_points(points: dict, lock: AnalysisLock) -> dict:
    estimands = []
    for point in points["estimands"]:
        estimand_id = point["estimand_id"]
        margin = (
            lock.work_relative_equivalence_margin
            if estimand_id.startswith("wall_work_ratio")
            else (
                lock.action_divergence_margin
                if "action_excess_divergence" in estimand_id
                else lock.score_equivalence_margin
            )
        )
        estimate = float(point["estimate"])
        interval = [estimate - 0.01, estimate + 0.01]
        estimands.append(
            {
                "estimand_id": estimand_id,
                "display_label": estimand_id,
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
                "inventory": point["inventory"],
            }
        )
    sources = [
        {"role": role, "schema_version": "test-1.0.0", "sha256": char * 64}
        for role, char in zip(
            (
                "final_schedule",
                "main_outcome_hash_manifest",
                "repeatability_outcome_hash_manifest",
                "protocol_freeze",
                "analysis_code",
            ),
            "abcde",
        )
    ]
    return build_frozen_analysis_summary(
        lock,
        point_estimates=points,
        simultaneous_evidence=_test_interval_evidence(lock, estimands),
        source_artifacts=sources,
        protocol_freeze_hash="f" * 64,
        rank_reversal={"comparisons": {}},
    )


def test_all_ten_headlines_and_inventories_independently_reaggregate() -> None:
    cases, panel, agents = _confirmatory_inputs()
    production = confirmatory_point_estimates(cases, panel, agents=agents)
    independent = independent_confirmatory_reaggregation(cases, panel, agents=agents)
    assert [row["estimand_id"] for row in production["estimands"]] == list(
        CONFIRMATORY_ESTIMAND_IDS
    )
    for left, right in zip(production["estimands"], independent["estimands"]):
        assert left["estimate"] == pytest.approx(right["estimate"])
        assert left["inventory"] == right["inventory"]
    assert production["inventory_counts"] == independent["inventory_counts"]
    assert production["inventory_counts"]["zero_eligible_decision_game_count"] == 2

    summary = _summary_from_points(
        production,
        AnalysisLock(bootstrap_replicates=1_999),
    )
    verification = verify_confirmatory_summary(summary, independent)
    assert verification["verified_estimand_count"] == 10
    assert verification["all_headline_points_and_counts_match"] is True

    tampered = copy.deepcopy(summary)
    tampered["estimands"][0]["inventory"]["matched_block_count"] += 1
    tampered["content_hash"] = hash_json(
        {key: value for key, value in tampered.items() if key != "content_hash"}
    )
    with pytest.raises(ValueError, match="inventory"):
        verify_confirmatory_summary(tampered, independent)


def test_confirmatory_reaggregation_refuses_incomplete_state_panel() -> None:
    cases, panel, agents = _confirmatory_inputs()
    panel.pop()
    with pytest.raises(ValueError, match="factorially incomplete"):
        independent_confirmatory_reaggregation(cases, panel, agents=agents)
    with pytest.raises(ValueError, match="factorially incomplete"):
        confirmatory_point_estimates(cases, panel, agents=agents)


def _test_interval_evidence(
    lock: AnalysisLock,
    records: list[dict],
) -> dict[str, dict]:
    evidence: dict[str, dict] = {}
    for role, state_role in (("main_matched_blocks", False), ("frozen_states", True)):
        selected = [
            record
            for record in records
            if ("action_excess_divergence" in record["estimand_id"]) == state_role
        ]
        payload = {
            "schema_version": "simultaneous-intervals-1.0.0",
            "analysis_version": "resource-envelope-analysis-1.2.0",
            "analysis_lock_hash": lock.content_hash,
            "simultaneous_method": lock.simultaneous_method,
            "familywise_confidence_level": lock.confidence_level,
            "member_confidence_level": lock.confirmatory_member_confidence_level,
            "confirmatory_family_size": 10,
            "endpoint_ids": [record["estimand_id"] for record in selected],
            "intervals": {
                record["estimand_id"]: {
                    "estimate": record["estimate"],
                    "interval": record["interval"],
                }
                for record in selected
            },
        }
        payload["content_hash"] = hash_json(payload)
        evidence[role] = payload
    return evidence


def _frozen_summary(lock: AnalysisLock) -> dict:
    estimands = []
    for index, estimand_id in enumerate(CONFIRMATORY_ESTIMAND_IDS):
        margin = (
            lock.work_relative_equivalence_margin
            if estimand_id.startswith("wall_work_ratio")
            else (
                lock.action_divergence_margin
                if "action_excess_divergence" in estimand_id
                else lock.score_equivalence_margin
            )
        )
        interval = [-0.01, 0.01]
        if "action_excess_divergence" in estimand_id:
            inventory = {
                "agent_count": 3,
                "state_count": 1,
                "source_game_count": 1,
                "state_agent_count": 3,
                "load_batch_count": 1,
                "contributing_result_count": 60,
                "repeats_per_envelope": 10,
            }
        else:
            inventory = {
                "agent_count": 3,
                "matched_block_count": 1,
                "load_batch_count": 1,
                "contributing_case_count": (
                    12 if estimand_id.startswith("score_attenuation") else 6
                ),
            }
            if estimand_id.startswith("wall_work_ratio"):
                inventory.update(
                    {
                        "zero_eligible_decision_game_count": 0,
                        "zero_eligible_decision_game_rate": 0.0,
                        "nonzero_complete_pair_count_by_agent": {
                            "a": 1,
                            "b": 1,
                            "c": 1,
                        },
                    }
                )
        estimands.append(
            {
                "estimand_id": estimand_id,
                "display_label": f"Estimand {index + 1}",
                "estimate": 0.0,
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
                "inventory": inventory,
            }
        )
    sources = [
        {"role": role, "schema_version": "test-1.0.0", "sha256": character * 64}
        for role, character in zip(
            (
                "final_schedule",
                "main_outcome_hash_manifest",
                "repeatability_outcome_hash_manifest",
                "protocol_freeze",
                "analysis_code",
            ),
            "abcde",
        )
    ]
    inventory_counts = {
        "agent_count": 3,
        "main_case_count": 24,
        "main_matched_block_count": 1,
        "main_load_batch_count": 1,
        "zero_eligible_decision_game_count": 0,
        "zero_eligible_decision_game_rate": 0.0,
        "repeatability_result_count": 240,
        "repeatability_state_count": 1,
        "repeatability_source_game_count": 1,
        "repeatability_state_agent_count": 3,
        "repeatability_load_batch_count": 1,
        "repeats_per_envelope": 10,
    }
    points = {
        "schema_version": "confirmatory-point-estimates-1.0.0",
        "analysis_version": "resource-envelope-analysis-1.2.0",
        "work_outcome": "per_game_mean_completed_work_per_eligible_decision_zero_if_none",
        "confirmatory_estimand_ids": list(CONFIRMATORY_ESTIMAND_IDS),
        "inventory_counts": inventory_counts,
        "estimands": [
            {
                "estimand_id": record["estimand_id"],
                "estimate": record["estimate"],
                "inventory": record["inventory"],
            }
            for record in estimands
        ],
    }
    points["content_hash"] = hash_json(points)
    return build_frozen_analysis_summary(
        lock,
        point_estimates=points,
        simultaneous_evidence=_test_interval_evidence(lock, estimands),
        source_artifacts=sources,
        protocol_freeze_hash="f" * 64,
        rank_reversal={"comparisons": {}},
    )


def test_plots_accept_only_frozen_summary_and_are_hash_deterministic(tmp_path: Path) -> None:
    summary = _frozen_summary(AnalysisLock(bootstrap_replicates=1_999))
    summary_path = tmp_path / "analysis-summary.json"
    inventory_path = tmp_path / "plot-source-inventory.json"
    write_canonical_json(summary_path, summary)
    build_plot_source_inventory(summary_path, inventory_path)
    first = render_publication_plots(summary_path, inventory_path, tmp_path / "plots-a")
    second = render_publication_plots(summary_path, inventory_path, tmp_path / "plots-b")
    assert first["plots"] == second["plots"]

    raw_path = tmp_path / "raw.jsonl"
    raw_path.write_text("{}\n", encoding="ascii")
    with pytest.raises(ValueError, match="refuses raw"):
        build_plot_source_inventory(raw_path, tmp_path / "bad-inventory.json")

    unfrozen = copy.deepcopy(summary)
    unfrozen["freeze_status"] = "DRAFT"
    unfrozen["content_hash"] = hash_json(
        {key: value for key, value in unfrozen.items() if key != "content_hash"}
    )
    unfrozen_path = tmp_path / "unfrozen-summary.json"
    write_canonical_json(unfrozen_path, unfrozen)
    with pytest.raises(ValueError, match="not frozen"):
        build_plot_source_inventory(unfrozen_path, tmp_path / "unfrozen-inventory.json")


def test_frozen_summary_rejects_rehashed_arbitrary_interval_evidence() -> None:
    summary = _frozen_summary(AnalysisLock(bootstrap_replicates=1_999))
    tampered = copy.deepcopy(summary)
    evidence = tampered["simultaneous_evidence"]["main_matched_blocks"]
    endpoint = evidence["endpoint_ids"][0]
    evidence["intervals"][endpoint]["interval"] = [-0.9, 0.9]
    evidence["content_hash"] = hash_json(
        {key: value for key, value in evidence.items() if key != "content_hash"}
    )
    tampered["simultaneous_evidence_hashes"] = sorted(
        item["content_hash"] for item in tampered["simultaneous_evidence"].values()
    )
    tampered["content_hash"] = hash_json(
        {key: value for key, value in tampered.items() if key != "content_hash"}
    )
    with pytest.raises(ValueError, match="differs from evidence"):
        verify_frozen_analysis_summary(tampered)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_bytes(b"".join(canonical_json_bytes(row) for row in rows))


def _driver_main_result(row: dict) -> dict:
    scales = {"a": (10, 5), "b": (100, 80), "c": (1_000, 900)}
    idle_work, loaded_work = scales[row["agent_id"]]
    work = (
        idle_work
        if row["load_condition"] == "idle"
        else (loaded_work if row["budget_mode"] == "wall_clock" else idle_work)
    )
    score = (
        0.0
        if row["load_condition"] == "idle"
        else (1.0 if row["budget_mode"] == "wall_clock" else 0.5)
    )
    decision = {
        "schema_version": "decision-1.1.0",
        "case_id": row["case_id"],
        "block_id": row["block_id"],
        "decision_index": 0,
        "agent_id": row["agent_id"],
        "budget_mode": row["budget_mode"],
        "load_condition": row["load_condition"],
        "lifecycle": row["lifecycle"],
        "lifecycle_id": row["lifecycle_id"],
        "process_instance_id": row["process_instance_id"],
        "worker_pid": 1,
        "sequence_index": row["sequence_index"],
        "load_batch_id": row["load_batch_id"],
        "requested_budget_ns": row["requested_budget_ns"],
        "requested_work_units": row["requested_work_units"],
        "terminal_status": "ok",
        "completed_work_units": work,
        "completed_simulations": work,
        "completed_nodes": work,
        "completed_sweeps": 0,
        "forward_model_calls": work,
        "setup_wall_ns": 1,
        "search_wall_ns": 1,
        "selection_wall_ns": 1,
        "cleanup_wall_ns": 1,
        "process_cpu_ns": 1,
        "overshoot_ns": 0,
        "state_hash": hash_json({"state": row["case_id"]}),
        "agent_seed_hash": hash_json({"seed": row["agent_seed"]}),
        "selected_action": [0],
        "selected_action_hash": hash_json({"action": 0}),
        "value_estimates": [0.0],
        "timeout_reason": "",
        "fallback_reason": "",
        "cleanup_succeeded": True,
        "instrumentation_enabled": True,
        "work_counters_collected": True,
        "error_type": "",
        "error_message": "",
        "extra": {},
    }
    game = {
        "schema_version": "game-1.0.0",
        "case_id": row["case_id"],
        "block_id": row["block_id"],
        "agent_id": row["agent_id"],
        "terminal_status": "completed",
        "score": score,
        "winner": 1 if score == 1 else (2 if score == 0 else None),
        "decision_count": 1,
        "completed_work_units": work,
        "completed_simulations": work,
        "completed_nodes": work,
        "completed_sweeps": 0,
        "forward_model_calls": work,
        "decision_record_hashes": [hash_json(decision)],
        "error_type": "",
        "error_message": "",
    }
    result = {
        "schedule_row": dict(row),
        "game": game,
        "decisions": [decision],
        "gameplay_decisions": 1,
        "public_trace_sha256": hash_json({"case": row["case_id"]}),
        "observed_worker": {"case": row["case_id"]},
    }
    result["artifact_sha256"] = hash_json(result)
    return result


def _driver_repeatability_manifest() -> dict:
    agents = ("a", "b", "c")
    envelopes = tuple(
        EnvelopeSpec(
            envelope_id=f"{budget}-{load}-{lifecycle}",
            budget_mode=budget,
            load_condition=load,
            lifecycle=lifecycle,
            resource_profile_sha256=hash_json(
                {"budget": budget, "load": load, "lifecycle": lifecycle}
            ),
        )
        for budget in ("wall_clock", "fixed_work")
        for load in ("idle", "loaded")
        for lifecycle in ("fresh", "persistent")
    )
    states = [
        FrozenStateSpec(
            state_id=f"s{index}",
            source_game_id=f"g{index}",
            state_artifact_sha256=hash_json({"state": index}),
            state_seed=100 + index,
            history_prefix_sha256=hash_json({"history": index}),
            history_seed=200 + index,
            history_length=0,
            pseudo_sequence_slot=0,
        )
        for index in range(2)
    ]
    return build_repeatability_manifest(
        RepeatabilityConfig(
            bank_id="analysis-test",
            master_seed=2026082699,
            agents=agents,
            envelopes=envelopes,
            wall_clock_budget_ns=10_000_000,
            fixed_work_by_agent={"a": 10, "b": 100, "c": 1_000},
            target_state_count=2,
            load_batch_count=2,
            persistent_sequence_length=2,
        ),
        states,
        excluded_seed_ledger={
            "calibration": [],
            "gate": [],
            "final": [],
            "reserve": [],
        },
    )


def _driver_panel_result(row: dict, manifest_hash: str) -> dict:
    action = (
        "y"
        if row["state_id"] == "s0"
        and row["budget_mode"] == "wall_clock"
        and row["load_condition"] == "loaded"
        else "x"
    )
    warmup_hash = hash_json(
        {
            "state": row["state_id"],
            "agent": row["agent_id"],
            "budget": row["budget_mode"],
            "repeat": row["repeat_index"],
        }
    )
    result = {
        "schema_version": "state-panel-result-1.0.0",
        "case_id": row["repeatability_case_id"],
        "manifest_content_hash": manifest_hash,
        "schedule_row": dict(row),
        "state_artifact_sha256": row["state_artifact_sha256"],
        "history_prefix_sha256": (
            row["history_prefix_sha256"] if row["lifecycle"] == "persistent" else None
        ),
        "budget_mode": row["budget_mode"],
        "requested_budget_ns": row["requested_budget_ns"],
        "requested_work_units": row["requested_work_units"],
        "terminal_status": "ok",
        "eligible": True,
        "completed_work_units": (
            row["requested_work_units"]
            if row["budget_mode"] == "fixed_work"
            else 5
        ),
        "completed_simulations": 1,
        "completed_nodes": 1,
        "forward_model_calls": 1,
        "search_wall_ns": 1,
        "overshoot_ns": 0,
        "state_hash": row["state_artifact_sha256"],
        "selected_action_hash": hash_json({"action": action}),
        "cleanup_succeeded": True,
        "warmup_steps_completed": row["history_length"] if row["lifecycle"] == "persistent" else 0,
        "warmup_consumed_sha256": (
            row["history_prefix_sha256"] if row["lifecycle"] == "persistent" else None
        ),
        "warmup_replay_sha256": warmup_hash if row["lifecycle"] == "persistent" else None,
        "observed_worker": {"case": row["repeatability_case_id"]},
    }
    result["artifact_sha256"] = hash_json(result)
    return result


def _driver_journals(
    directory: Path,
    schedule: dict,
    repeat_manifest: dict,
) -> tuple[Path, Path]:
    main_rows = sorted(schedule["rows"], key=lambda row: row["execution_index"])
    main_results = [_driver_main_result(row) for row in main_rows]
    main_by_case = {row["game"]["case_id"]: row for row in main_results}
    main_rows_by_batch: dict[str, list[dict]] = {}
    for row in main_rows:
        main_rows_by_batch.setdefault(row["load_batch_id"], []).append(row)
    main_episodes: list[dict] = []
    main_commits: list[dict] = []
    for batch_id, rows in main_rows_by_batch.items():
        batch_episodes = []
        for load in ("idle", "loaded"):
            period_rows = [row for row in rows if row["load_condition"] == load]
            metadata = {
                "schema_version": "resource-episode-1.0.0",
                "load_batch_id": batch_id,
                "load_seed": rows[0]["load_seed"],
                "profile": {"condition": load},
                "status": "scientific_complete",
            }
            episode = {
                **metadata,
                "period_case_ids": [row["case_id"] for row in period_rows],
                "metadata_hash": hash_json(metadata),
            }
            main_episodes.append(episode)
            batch_episodes.append(episode)
        commit = {
            "schema_version": "load-batch-commit-1.0.0",
            "load_batch_id": batch_id,
            "batch_status": "scientific_complete",
            "case_ids": [row["case_id"] for row in rows],
            "result_hashes": [
                main_by_case[row["case_id"]]["artifact_sha256"] for row in rows
            ],
            "episode_hashes": [row["metadata_hash"] for row in batch_episodes],
        }
        commit["content_hash"] = hash_json(commit)
        main_commits.append(commit)
    main_results_path = directory / "main-results.jsonl"
    main_commits_path = directory / "main-commits.jsonl"
    main_episodes_path = directory / "main-episodes.jsonl"
    _write_jsonl(main_results_path, main_results)
    _write_jsonl(main_commits_path, main_commits)
    _write_jsonl(main_episodes_path, main_episodes)
    main_hash_manifest = directory / "main-outcome-hashes.json"
    build_analysis_outcome_hash_manifest(
        outcome_kind="main_game",
        design_manifest_content_hash=schedule["content_hash"],
        results_path=main_results_path,
        commits_path=main_commits_path,
        episodes_path=main_episodes_path,
        output_path=main_hash_manifest,
    )

    panel_rows = sorted(
        repeat_manifest["rows"], key=lambda row: row["execution_index"]
    )
    panel_results = [
        _driver_panel_result(row, repeat_manifest["content_hash"])
        for row in panel_rows
    ]
    panel_by_case = {row["case_id"]: row for row in panel_results}
    panel_rows_by_batch: dict[str, list[dict]] = {}
    for row in panel_rows:
        panel_rows_by_batch.setdefault(row["load_batch_id"], []).append(row)
    panel_episodes: list[dict] = []
    panel_commits: list[dict] = []
    for batch_id, rows in panel_rows_by_batch.items():
        periods: list[list[dict]] = []
        for row in rows:
            if not periods or periods[-1][0]["load_condition"] != row["load_condition"]:
                periods.append([])
            periods[-1].append(row)
        batch_episodes = []
        for period_index, period_rows in enumerate(periods):
            episode = {
                "schema_version": "state-panel-resource-episode-1.0.0",
                "group_id": batch_id,
                "period_id": f"{batch_id}-period-{period_index:02d}",
                "period_index": period_index,
                "load_condition": period_rows[0]["load_condition"],
                "case_ids": [row["repeatability_case_id"] for row in period_rows],
                "resource_profile_sha256": sorted(
                    {row["resource_profile_sha256"] for row in period_rows}
                ),
                "status": "scientific_complete",
                "error": None,
                "test_mode": True,
                "resource_metadata": {},
            }
            episode["artifact_sha256"] = hash_json(episode)
            panel_episodes.append(episode)
            batch_episodes.append(episode)
        commit = {
            "schema_version": "state-panel-batch-commit-1.0.0",
            "group_kind": "paired_load_batch",
            "group_id": batch_id,
            "manifest_content_hash": repeat_manifest["content_hash"],
            "run_config_file_sha256": None,
            "batch_status": "scientific_complete",
            "case_ids": [row["repeatability_case_id"] for row in rows],
            "result_hashes": [
                panel_by_case[row["repeatability_case_id"]]["artifact_sha256"]
                for row in rows
            ],
            "episode_hashes": [row["artifact_sha256"] for row in batch_episodes],
        }
        commit["content_hash"] = hash_json(commit)
        panel_commits.append(commit)
    panel_results_path = directory / "panel-results.jsonl"
    panel_commits_path = directory / "panel-commits.jsonl"
    panel_episodes_path = directory / "panel-episodes.jsonl"
    _write_jsonl(panel_results_path, panel_results)
    _write_jsonl(panel_commits_path, panel_commits)
    _write_jsonl(panel_episodes_path, panel_episodes)
    panel_hash_manifest = directory / "panel-outcome-hashes.json"
    build_analysis_outcome_hash_manifest(
        outcome_kind="repeatability",
        design_manifest_content_hash=repeat_manifest["content_hash"],
        results_path=panel_results_path,
        commits_path=panel_commits_path,
        episodes_path=panel_episodes_path,
        output_path=panel_hash_manifest,
    )
    return main_hash_manifest, panel_hash_manifest


def test_locked_driver_binds_canonical_raw_commits_and_interval_evidence(
    tmp_path: Path,
) -> None:
    schedule = build_schedule(
        ScheduleConfig(
            phase="smoke",
            master_seed=2026082611,
            agents=("a", "b", "c"),
            block_count=8,
            paired_load_batches=2,
            minimum_persistent_sessions=1,
            persistent_sequence_length=4,
            wall_clock_budget_ns=10_000_000,
            fixed_work_by_agent={"a": 10, "b": 100, "c": 1_000},
        )
    )
    repeat_manifest = _driver_repeatability_manifest()
    schedule_path = tmp_path / "schedule.json"
    repeat_manifest_path = tmp_path / "repeatability.json"
    write_canonical_json(schedule_path, schedule)
    write_canonical_json(repeat_manifest_path, repeat_manifest)
    main_hash_manifest, panel_hash_manifest = _driver_journals(
        tmp_path, schedule, repeat_manifest
    )
    protocol_path = tmp_path / "protocol.freeze"
    analysis_code_path = tmp_path / "analysis-code.freeze"
    protocol_path.write_text("frozen protocol\n", encoding="ascii")
    analysis_code_path.write_text("frozen analysis code\n", encoding="ascii")
    result = run_locked_analysis(
        AnalysisLock(bootstrap_replicates=1_999),
        schedule_path=schedule_path,
        expected_schedule_sha256=hash_file(schedule_path),
        repeatability_manifest_path=repeat_manifest_path,
        expected_repeatability_manifest_sha256=hash_file(repeat_manifest_path),
        main_outcome_hash_manifest_path=main_hash_manifest,
        expected_main_outcome_hash_manifest_sha256=hash_file(main_hash_manifest),
        repeatability_outcome_hash_manifest_path=panel_hash_manifest,
        expected_repeatability_outcome_hash_manifest_sha256=hash_file(
            panel_hash_manifest
        ),
        protocol_path=protocol_path,
        expected_protocol_sha256=hash_file(protocol_path),
        analysis_code_path=analysis_code_path,
        expected_analysis_code_sha256=hash_file(analysis_code_path),
        output_dir=tmp_path / "analysis-output",
        test_mode=True,
    )
    assert result["schema_version"] == "locked-analysis-driver-result-1.0.0"
    summary = json.loads(
        (tmp_path / "analysis-output" / "locked-analysis-summary.json").read_text(
            encoding="ascii"
        )
    )
    verify_frozen_analysis_summary(summary)

    main_results_path = tmp_path / "main-results.jsonl"
    main_results_path.write_bytes(main_results_path.read_bytes() + b" \n")
    with pytest.raises(ValueError, match="file SHA-256 mismatch"):
        run_locked_analysis(
            AnalysisLock(bootstrap_replicates=1_999),
            schedule_path=schedule_path,
            expected_schedule_sha256=hash_file(schedule_path),
            repeatability_manifest_path=repeat_manifest_path,
            expected_repeatability_manifest_sha256=hash_file(repeat_manifest_path),
            main_outcome_hash_manifest_path=main_hash_manifest,
            expected_main_outcome_hash_manifest_sha256=hash_file(main_hash_manifest),
            repeatability_outcome_hash_manifest_path=panel_hash_manifest,
            expected_repeatability_outcome_hash_manifest_sha256=hash_file(
                panel_hash_manifest
            ),
            protocol_path=protocol_path,
            expected_protocol_sha256=hash_file(protocol_path),
            analysis_code_path=analysis_code_path,
            expected_analysis_code_sha256=hash_file(analysis_code_path),
            output_dir=tmp_path / "tampered-output",
            test_mode=True,
        )
