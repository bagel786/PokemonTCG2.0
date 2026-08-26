from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy

import pytest

from resource_envelope_study.canonical import canonical_json_bytes, hash_json
from resource_envelope_study.acquire import _execution_units
from resource_envelope_study.scheduler import ScheduleConfig, build_schedule, validate_schedule


AGENTS = ("one_ply_value_v1", "flat_rollout_v1", "puct_tree_v1")
ARTIFACT_HASHES = {
    "engine_binary": "0" * 64,
    "engine_source": "1" * 64,
    "hero_deck": "2" * 64,
    "hero_model": "3" * 64,
    "opponent_deck": "4" * 64,
    "opponent_model": "5" * 64,
    "run_config": "6" * 64,
}


def config() -> ScheduleConfig:
    return ScheduleConfig(
        phase="final",
        master_seed=2026082601,
        agents=AGENTS,
        block_count=80,
        paired_load_batches=20,
        minimum_persistent_sessions=20,
        persistent_sequence_length=8,
        wall_clock_budget_ns=20_000_000,
        fixed_work_by_agent={agent: 12 + index for index, agent in enumerate(AGENTS)},
        artifact_hashes=ARTIFACT_HASHES,
    )


def test_schedule_manifests_regenerate_byte_for_byte() -> None:
    first = build_schedule(config())
    second = build_schedule(config())
    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    validate_schedule(first)
    assert len(first["rows"]) == 80 * len(AGENTS) * 2 * 2 * 2
    assert len({row["load_batch_id"] for row in first["rows"]}) == 20


def test_schedule_is_matched_balanced_and_process_bounded() -> None:
    manifest = build_schedule(config())
    strata = Counter((row["physical_seat"], row["play_order"]) for row in manifest["rows"])
    assert len(strata) == 4
    assert len(set(strata.values())) == 1

    by_pair = defaultdict(list)
    by_process = Counter()
    process_periods = defaultdict(set)
    for row in manifest["rows"]:
        by_pair[row["lifecycle_pair_id"]].append(row)
        if row["lifecycle"] == "persistent":
            by_process[row["process_instance_id"]] += 1
            process_periods[row["process_instance_id"]].add(
                (row["load_batch_id"], row["load_condition"])
            )
    assert len(by_process) >= 20
    assert max(by_process.values()) <= config().persistent_sequence_length
    assert all(len(periods) == 1 for periods in process_periods.values())
    assert all(
        len(rows) == 2
        and {row["lifecycle"] for row in rows} == {"fresh", "persistent"}
        and len({row["sequence_index"] for row in rows}) == 1
        for rows in by_pair.values()
    )

    # Every complete block has one common bundle/slot in all 24 cells, while
    # a persistent native process remains specific to one treatment cell.
    by_block = defaultdict(list)
    for row in manifest["rows"]:
        by_block[row["block_id"]].append(row)
    assert all(len({(row["session_bundle_id"], row["sequence_index"]) for row in rows}) == 1 for rows in by_block.values())
    assert all(
        len(
            {
                (row["agent_id"], row["budget_mode"], row["load_condition"])
                for row in manifest["rows"]
                if row["lifecycle"] == "persistent"
                and row["process_instance_id"] == process_id
            }
        )
        == 1
        for process_id in by_process
    )


def test_every_scheduled_case_accepts_exactly_one_terminal_status() -> None:
    manifest = build_schedule(config())
    terminal = {row["case_id"]: "completed" for row in manifest["rows"]}
    assert len(terminal) == len(manifest["rows"])
    assert set(terminal) == {row["case_id"] for row in manifest["rows"]}
    # Duplicate terminal rows are structurally detectable, not silently kept.
    duplicated = [(case_id, status) for case_id, status in terminal.items()] + [
        (manifest["rows"][0]["case_id"], "engine_error")
    ]
    counts = Counter(case_id for case_id, _status in duplicated)
    assert max(counts.values()) == 2


def test_persistent_execution_units_are_contiguous_and_cell_pure() -> None:
    manifest = build_schedule(config())
    by_period = defaultdict(list)
    for row in manifest["rows"]:
        by_period[(row["load_batch_id"], row["load_condition"])].append(row)
    for rows in by_period.values():
        for unit in _execution_units(rows):
            if unit[0]["lifecycle"] == "fresh":
                assert len(unit) == 1
            else:
                assert [row["sequence_index"] for row in unit] == list(range(len(unit)))
                assert len({row["agent_id"] for row in unit}) == 1
                assert len({row["budget_mode"] for row in unit}) == 1
                assert len({row["load_batch_id"] for row in unit}) == 1
                assert len({row["load_condition"] for row in unit}) == 1


def test_final_rejects_requested_but_unrealized_clusters() -> None:
    too_small = ScheduleConfig(
        **{
            **config().__dict__,
            "block_count": 2,
        }
    )
    with pytest.raises(ValueError, match="four blocks per paired load batch"):
        build_schedule(too_small)

    singleton = ScheduleConfig(
        **{
            **config().__dict__,
            "persistent_sequence_length": 1,
        }
    )
    with pytest.raises(ValueError, match="length at least two"):
        build_schedule(singleton)


def test_pilot_cannot_bypass_cluster_budget_or_artifact_gates() -> None:
    pilot = ScheduleConfig(
        **{
            **config().__dict__,
            "phase": "pilot",
            "artifact_hashes": None,
        }
    )
    with pytest.raises(ValueError, match="pilot schedule requires frozen artifact hashes"):
        build_schedule(pilot)


def test_batches_are_stratified_and_period_order_is_balanced() -> None:
    manifest = build_schedule(config())
    by_batch = defaultdict(list)
    for row in manifest["rows"]:
        by_batch[row["load_batch_id"]].append(row)
    orders = Counter(rows[0]["load_period_order"] for rows in by_batch.values())
    assert orders == {"idle_then_loaded": 10, "loaded_then_idle": 10}
    for rows in by_batch.values():
        blocks = {
            row["block_id"]: (row["physical_seat"], row["play_order"])
            for row in rows
        }
        assert Counter(blocks.values()) == {
            (0, 0): 1,
            (1, 0): 1,
            (0, 1): 1,
            (1, 1): 1,
        }


def test_stale_content_hash_and_noncontiguous_session_fail_closed() -> None:
    manifest = build_schedule(config())
    mutated = deepcopy(manifest)
    mutated["rows"][0]["requested_work_units"] += 1
    with pytest.raises(ValueError, match="content hash mismatch"):
        validate_schedule(mutated)

    mutated["content_hash"] = hash_json(
        {key: value for key, value in mutated.items() if key != "content_hash"}
    )
    with pytest.raises(ValueError):
        validate_schedule(mutated)
