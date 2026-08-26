from __future__ import annotations

import copy

import pytest

from resource_envelope_study.calibration import (
    DEADLINE_WHITELIST_MS,
    CalibrationConfig,
    CalibrationError,
    CalibrationState,
    DeadlineCriteria,
    build_calibration_manifest,
    collect_persisted_seeds,
    select_deadline,
    select_fixed_work_counts,
    validate_calibration_manifest,
)


AGENTS = ("one_ply_value_v1", "flat_rollout_v1", "puct_tree_v1")
EMPTY_EXCLUSIONS = {"gate": (), "final": (), "reserve": ()}


def digest(character: str) -> str:
    return character * 64


def states(count: int, *, offset: int = 0) -> list[CalibrationState]:
    return [
        CalibrationState(
            state_id=f"state-{offset + index:03d}",
            source_game_id=f"source-game-{offset + index:03d}",
            state_artifact_sha256=digest("a"),
            state_seed=10_000 + offset + index,
            eligibility_sha256=digest("b"),
        )
        for index in range(count)
    ]


def deadline_manifest(count: int = 4):
    return build_calibration_manifest(
        CalibrationConfig(
            bank_id="deadline-bank-v1",
            role="deadline_selection",
            master_seed=901_001,
            agents=AGENTS,
        ),
        states(count),
        excluded_seed_ledger=EMPTY_EXCLUSIONS,
    )


def latency_record(row: dict, *, work: int, overshoot_ns: int, search_wall_ns: int):
    return {
        "calibration_case_id": row["calibration_case_id"],
        "agent_id": row["agent_id"],
        "state_id": row["state_id"],
        "block_id": row["block_id"],
        "requested_budget_ns": row["requested_budget_ns"],
        "completed_work_units": work,
        "search_wall_ns": search_wall_ns,
        "overshoot_ns": overshoot_ns,
        "terminal_status": "ok" if work else "deadline_no_work",
        "eligible": True,
    }


def passing_deadline_selection(manifest: dict):
    records = []
    for row in manifest["rows"]:
        deadline_ms = row["deadline_ms"]
        if deadline_ms == 10:
            work, overshoot = 0, 0
        elif deadline_ms == 25:
            work, overshoot = 2, 5_000_000
        elif deadline_ms == 50:
            work, overshoot = 5, 2_000_000
        else:
            work, overshoot = 11, 3_000_000
        records.append(
            latency_record(
                row,
                work=work,
                overshoot_ns=overshoot,
                search_wall_ns=deadline_ms * 1_000_000 + overshoot,
            )
        )
    return select_deadline(
        manifest,
        records,
        DeadlineCriteria(
            minimum_valid_states_per_agent=len(manifest["states"]),
            maximum_zero_work_fraction=0.0,
            maximum_p99_overshoot_fraction=0.10,
            maximum_single_overshoot_fraction=0.25,
            maximum_p95_search_wall_fraction=1.10,
            minimum_median_completed_work=1.0,
        ),
    )


def test_calibration_manifest_is_deterministic_disjoint_and_envelope_pure() -> None:
    config = CalibrationConfig(
        bank_id="deadline-bank-v1",
        role="deadline_selection",
        master_seed=901_001,
        agents=AGENTS,
    )
    first = build_calibration_manifest(
        config,
        states(5),
        excluded_seed_ledger=EMPTY_EXCLUSIONS,
    )
    second = build_calibration_manifest(
        config,
        list(reversed(states(5))),
        excluded_seed_ledger=EMPTY_EXCLUSIONS,
    )
    assert first == second
    assert len(first["rows"]) == 5 * len(AGENTS) * len(DEADLINE_WHITELIST_MS)
    assert {
        (row["budget_mode"], row["load_condition"], row["lifecycle"])
        for row in first["rows"]
    } == {("wall_clock", "idle", "fresh")}
    assert len({state["source_game_id"] for state in first["states"]}) == 5
    validate_calibration_manifest(first)


def test_calibration_rejects_seed_overlap_and_reused_source_game() -> None:
    manifest = deadline_manifest(3)
    collided_seed = manifest["rows"][0]["agent_seed"]
    with pytest.raises(CalibrationError, match="overlap excluded bank gate"):
        build_calibration_manifest(
            CalibrationConfig("deadline-bank-v1", "deadline_selection", 901_001, AGENTS),
            states(3),
            excluded_seed_ledger={
                "gate": (collided_seed,),
                "final": (),
                "reserve": (),
            },
        )

    duplicate_game = states(2, offset=200)
    duplicate_game[1] = CalibrationState(
        state_id=duplicate_game[1].state_id,
        source_game_id=duplicate_game[0].source_game_id,
        state_artifact_sha256=duplicate_game[1].state_artifact_sha256,
        state_seed=duplicate_game[1].state_seed,
        eligibility_sha256=duplicate_game[1].eligibility_sha256,
    )
    with pytest.raises(ValueError, match="at most one state per source game"):
        build_calibration_manifest(
            CalibrationConfig("bad-source-bank", "deadline_selection", 992_002, AGENTS),
            duplicate_game,
            excluded_seed_ledger=EMPTY_EXCLUSIONS,
        )


def test_deadline_selection_is_smallest_passing_whitelist_member() -> None:
    manifest = deadline_manifest(4)
    result = passing_deadline_selection(manifest)
    assert result["selected_deadline_ms"] == 50
    assert not result["candidate_metrics"]["10"]["passes"]
    assert not result["candidate_metrics"]["25"]["passes"]
    assert result["candidate_metrics"]["50"]["passes"]
    assert result["competitive_outcome_fields_consumed"] == []
    assert result["input_manifest_content_hash"] == manifest["content_hash"]


def test_deadline_selector_rejects_outcomes_missing_rows_and_tampering() -> None:
    manifest = deadline_manifest(3)
    records = [
        latency_record(
            row,
            work=3,
            overshoot_ns=0,
            search_wall_ns=row["requested_budget_ns"],
        )
        for row in manifest["rows"]
    ]
    leaked = [dict(record) for record in records]
    leaked[0]["score"] = 1.0
    with pytest.raises(CalibrationError, match="competitive outcome fields"):
        select_deadline(
            manifest,
            leaked,
            DeadlineCriteria(3, 0.0, 0.1, 0.25, 1.1),
        )
    with pytest.raises(CalibrationError, match="incomplete"):
        select_deadline(
            manifest,
            records[:-1],
            DeadlineCriteria(3, 0.0, 0.1, 0.25, 1.1),
        )

    tampered = copy.deepcopy(manifest)
    tampered["rows"][0]["requested_budget_ns"] += 1
    with pytest.raises(CalibrationError, match="content hash mismatch"):
        validate_calibration_manifest(tampered)


def test_fixed_work_counts_use_equal_complete_blocks_and_half_up_median() -> None:
    deadline_bank = deadline_manifest(4)
    selection = passing_deadline_selection(deadline_bank)
    exclusions = {
        "gate": (),
        "final": (),
        "reserve": (),
        "deadline_calibration": tuple(collect_persisted_seeds(deadline_bank)),
    }
    fixed_manifest = build_calibration_manifest(
        CalibrationConfig(
            bank_id="fixed-work-bank-v1",
            role="fixed_work",
            master_seed=5_500_001,
            agents=AGENTS,
            deadline_ms=selection["selected_deadline_ms"],
            deadline_selection_hash=selection["content_hash"],
        ),
        states(4, offset=500),
        excluded_seed_ledger=exclusions,
    )
    by_agent = {
        AGENTS[0]: [1, 2, 8, 9],
        AGENTS[1]: [1, 2, 3, 4],
        AGENTS[2]: [4, 4, 4, 4],
    }
    records = []
    for row in fixed_manifest["rows"]:
        work = by_agent[row["agent_id"]][row["block_index"]]
        records.append(
            latency_record(
                row,
                work=work,
                overshoot_ns=0,
                search_wall_ns=row["requested_budget_ns"],
            )
        )
    result = select_fixed_work_counts(
        fixed_manifest,
        records,
        selection,
        minimum_complete_blocks=4,
    )
    assert result["fixed_work_by_agent"] == {
        AGENTS[0]: 5,
        AGENTS[1]: 3,
        AGENTS[2]: 4,
    }
    assert len(result["included_block_ids"]) == 4
    assert result["excluded_blocks"] == {}
    assert result["deadline_selection_content_hash"] == selection["content_hash"]
    assert result["input_records_sha256"]


def test_fixed_work_bank_requires_deadline_bank_seed_exclusion() -> None:
    deadline_bank = deadline_manifest(2)
    selection = passing_deadline_selection(deadline_bank)
    config = CalibrationConfig(
        bank_id="fixed-without-deadline-exclusion",
        role="fixed_work",
        master_seed=6_600_001,
        agents=AGENTS,
        deadline_ms=selection["selected_deadline_ms"],
        deadline_selection_hash=selection["content_hash"],
    )
    with pytest.raises(ValueError, match="deadline_calibration"):
        build_calibration_manifest(
            config,
            states(2, offset=700),
            excluded_seed_ledger=EMPTY_EXCLUSIONS,
        )


def test_fixed_work_calibration_drops_whole_block_not_one_agent_row() -> None:
    deadline_bank = deadline_manifest(3)
    selection = passing_deadline_selection(deadline_bank)
    fixed_manifest = build_calibration_manifest(
        CalibrationConfig(
            "fixed-complete-block-bank",
            "fixed_work",
            8_800_001,
            AGENTS,
            selection["selected_deadline_ms"],
            selection["content_hash"],
        ),
        states(5, offset=800),
        excluded_seed_ledger={
            "gate": (),
            "final": (),
            "reserve": (),
            "deadline_calibration": tuple(collect_persisted_seeds(deadline_bank)),
        },
    )
    records = [
        latency_record(
            row,
            work=5,
            overshoot_ns=0,
            search_wall_ns=row["requested_budget_ns"],
        )
        for row in fixed_manifest["rows"]
    ]
    failed_block = fixed_manifest["rows"][0]["block_id"]
    for record in records:
        if record["block_id"] == failed_block and record["agent_id"] == AGENTS[0]:
            record["terminal_status"] = "search_error"
            break
    result = select_fixed_work_counts(
        fixed_manifest,
        records,
        selection,
        minimum_complete_blocks=4,
    )
    assert failed_block in result["excluded_blocks"]
    assert failed_block not in result["included_block_ids"]
    assert all(
        failed_block not in values
        for values in result["per_agent_block_values"].values()
    )
