from __future__ import annotations

import copy

import pytest

from resource_envelope_study.canonical import hash_json
from resource_envelope_study.repeatability import (
    EnvelopeSpec,
    FrozenStateSpec,
    RepeatabilityConfig,
    RepeatabilityError,
    build_repeatability_manifest,
    validate_repeatability_manifest,
)


AGENTS = ("one_ply_value_v1", "flat_rollout_v1", "puct_tree_v1")
EMPTY_EXCLUSIONS = {
    "calibration": (),
    "gate": (),
    "final": (),
    "reserve": (),
}


def digest(character: str) -> str:
    return character * 64


def envelopes() -> tuple[EnvelopeSpec, ...]:
    return (
        EnvelopeSpec("wall-idle-fresh", "wall_clock", "idle", "fresh", digest("1")),
        EnvelopeSpec("wall-loaded-fresh", "wall_clock", "loaded", "fresh", digest("2")),
        EnvelopeSpec(
            "wall-idle-persistent", "wall_clock", "idle", "persistent", digest("3")
        ),
        EnvelopeSpec(
            "wall-loaded-persistent",
            "wall_clock",
            "loaded",
            "persistent",
            digest("4"),
        ),
        EnvelopeSpec("work-idle-fresh", "fixed_work", "idle", "fresh", digest("5")),
        EnvelopeSpec(
            "work-loaded-fresh", "fixed_work", "loaded", "fresh", digest("6")
        ),
        EnvelopeSpec(
            "work-idle-persistent", "fixed_work", "idle", "persistent", digest("7")
        ),
        EnvelopeSpec(
            "work-loaded-persistent",
            "fixed_work",
            "loaded",
            "persistent",
            digest("8"),
        ),
    )


def states(count: int) -> list[FrozenStateSpec]:
    return [
        FrozenStateSpec(
            state_id=f"state-{index:03d}",
            source_game_id=f"source-{index:03d}",
            state_artifact_sha256=digest("a"),
            state_seed=20_000 + index,
            history_prefix_sha256=digest("b"),
            history_seed=30_000 + index,
            history_length=(index % 7) + 1,
            pseudo_sequence_slot=(index % 7) + 1,
        )
        for index in range(count)
    ]


def config(count: int = 2) -> RepeatabilityConfig:
    return RepeatabilityConfig(
        bank_id="repeatability-bank-v1",
        master_seed=7_700_001,
        agents=AGENTS,
        envelopes=envelopes(),
        wall_clock_budget_ns=50_000_000,
        fixed_work_by_agent={AGENTS[0]: 7, AGENTS[1]: 5, AGENTS[2]: 11},
        target_state_count=count,
        load_batch_count=count * 10,
        persistent_sequence_length=8,
    )


def manifest(count: int = 2):
    return build_repeatability_manifest(
        config(count),
        states(count),
        excluded_seed_ledger=EMPTY_EXCLUSIONS,
    )


def test_repeatability_manifest_exact_factorial_and_deterministic() -> None:
    first = manifest(2)
    second = build_repeatability_manifest(
        config(2),
        list(reversed(states(2))),
        excluded_seed_ledger=EMPTY_EXCLUSIONS,
    )
    assert first == second
    assert len(first["rows"]) == 2 * 3 * 8 * 10
    assert first["design"]["inference_unit"] == "frozen_state"
    keys = {
        (
            row["state_id"],
            row["agent_id"],
            row["envelope_id"],
            row["repeat_index"],
        )
        for row in first["rows"]
    }
    assert len(keys) == len(first["rows"])
    assert len({row["session_id"] for row in first["rows"]}) == len(first["rows"])
    validate_repeatability_manifest(first)


def test_repeatability_holds_state_agent_seed_and_load_pair_fixed() -> None:
    built = manifest(2)
    agent_seed = {}
    load_assignment = {}
    for row in built["rows"]:
        agent_seed.setdefault((row["state_id"], row["agent_id"]), set()).add(
            row["agent_seed"]
        )
        load_assignment.setdefault((row["state_id"], row["repeat_index"]), set()).add(
            (row["load_batch_id"], row["load_seed"])
        )
        assert row["state_id"] == row["inference_unit_id"]
        assert row["history_length"] == row["pseudo_sequence_slot"]
        assert row["sequence_index"] == row["pseudo_sequence_slot"]
        if row["budget_mode"] == "wall_clock":
            assert row["requested_budget_ns"] == 50_000_000
            assert row["requested_work_units"] is None
        else:
            assert row["requested_budget_ns"] is None
            assert row["requested_work_units"] == config(2).fixed_work_by_agent[
                row["agent_id"]
            ]
    assert all(len(values) == 1 for values in agent_seed.values())
    assert all(len(values) == 1 for values in load_assignment.values())


def test_repeatability_balances_ab_ba_load_periods() -> None:
    built = manifest(2)
    orders = {}
    for row in built["rows"]:
        orders.setdefault(row["load_batch_id"], set()).add(row["load_period_order"])
    assert all(len(values) == 1 for values in orders.values())
    counts = {
        order: sum(next(iter(values)) == order for values in orders.values())
        for order in ("idle_then_loaded", "loaded_then_idle")
    }
    assert abs(counts["idle_then_loaded"] - counts["loaded_then_idle"]) <= 1


def test_repeatability_requires_complete_budget_load_cells() -> None:
    incomplete = RepeatabilityConfig(
        bank_id="incomplete",
        master_seed=7_700_001,
        agents=AGENTS,
        envelopes=envelopes()[:-1],
        wall_clock_budget_ns=50_000_000,
        fixed_work_by_agent={AGENTS[0]: 7, AGENTS[1]: 5, AGENTS[2]: 11},
        target_state_count=2,
        load_batch_count=20,
    )
    with pytest.raises(ValueError, match="budget_mode x load_condition"):
        incomplete.validate()


def test_repeatability_rejects_reused_source_game_bad_history_and_wrong_count() -> None:
    duplicate = states(2)
    duplicate[1] = FrozenStateSpec(
        state_id=duplicate[1].state_id,
        source_game_id=duplicate[0].source_game_id,
        state_artifact_sha256=duplicate[1].state_artifact_sha256,
        state_seed=duplicate[1].state_seed,
        history_prefix_sha256=duplicate[1].history_prefix_sha256,
        history_seed=duplicate[1].history_seed,
        history_length=duplicate[1].history_length,
        pseudo_sequence_slot=duplicate[1].pseudo_sequence_slot,
    )
    with pytest.raises(ValueError, match="at most one state per source game"):
        build_repeatability_manifest(
            config(2),
            duplicate,
            excluded_seed_ledger=EMPTY_EXCLUSIONS,
        )

    bad_history = states(2)
    bad_history[0] = FrozenStateSpec(
        state_id=bad_history[0].state_id,
        source_game_id=bad_history[0].source_game_id,
        state_artifact_sha256=bad_history[0].state_artifact_sha256,
        state_seed=bad_history[0].state_seed,
        history_prefix_sha256=bad_history[0].history_prefix_sha256,
        history_seed=bad_history[0].history_seed,
        history_length=1,
        pseudo_sequence_slot=2,
    )
    with pytest.raises(ValueError, match="history length"):
        build_repeatability_manifest(
            config(2),
            bad_history,
            excluded_seed_ledger=EMPTY_EXCLUSIONS,
        )

    with pytest.raises(ValueError, match="received 1 states"):
        build_repeatability_manifest(
            config(2),
            states(1),
            excluded_seed_ledger=EMPTY_EXCLUSIONS,
        )


def test_repeatability_rejects_seed_overlap_and_hash_tampering() -> None:
    built = manifest(2)
    collision = built["rows"][0]["session_seed"]
    with pytest.raises(RepeatabilityError, match="overlap excluded bank final"):
        build_repeatability_manifest(
            config(2),
            states(2),
            excluded_seed_ledger={
                "calibration": (),
                "gate": (),
                "final": (collision,),
                "reserve": (),
            },
        )

    tampered = copy.deepcopy(built)
    tampered["rows"][0]["agent_seed"] += 1
    with pytest.raises(RepeatabilityError, match="content hash mismatch"):
        validate_repeatability_manifest(tampered)


def test_repeatability_detects_hostile_rehash_of_seed_and_profile_changes() -> None:
    built = manifest(2)
    hostile_seed = copy.deepcopy(built)
    hostile_seed["rows"][0]["agent_seed"] += 1
    hostile_seed["content_hash"] = hash_json(
        {key: value for key, value in hostile_seed.items() if key != "content_hash"}
    )
    with pytest.raises(RepeatabilityError, match="agent seed changes"):
        validate_repeatability_manifest(hostile_seed)

    hostile_profile = copy.deepcopy(built)
    hostile_profile["rows"][0]["resource_profile_sha256"] = digest("f")
    hostile_profile["content_hash"] = hash_json(
        {key: value for key, value in hostile_profile.items() if key != "content_hash"}
    )
    with pytest.raises(RepeatabilityError, match="frozen envelope spec"):
        validate_repeatability_manifest(hostile_profile)
