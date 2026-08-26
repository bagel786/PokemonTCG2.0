from __future__ import annotations

import os

import pytest

from resource_envelope_study.adapters.synthetic import SyntheticSearchAdapter
from resource_envelope_study.runner import CaseContext, run_decision
from resource_envelope_study.stop_policy import FixedWorkStop, WallClockStop
from resource_envelope_study.telemetry import GameTelemetry


class FakeClock:
    def __init__(self) -> None:
        self.now = 0

    def __call__(self) -> int:
        return self.now

    def advance(self, amount: int) -> None:
        self.now += amount


def context(**overrides) -> CaseContext:
    values = {
        "case_id": "case-1",
        "block_id": "block-1",
        "decision_index": 0,
        "load_condition": "idle",
        "lifecycle": "fresh",
        "lifecycle_id": "fresh-1",
        "process_instance_id": "fresh-1",
        "sequence_index": 0,
        "load_batch_id": "batch-1",
        "agent_seed": 991,
        "instrumentation_enabled": True,
    }
    values.update(overrides)
    return CaseContext(**values)


def test_fixed_work_executes_exactly_n_and_has_no_clock_dependency() -> None:
    adapter = SyntheticSearchAdapter()
    row = run_decision(adapter, {"state": 7}, FixedWorkStop(13), context())
    assert row.terminal_status == "ok"
    assert row.completed_work_units == 13
    assert row.completed_simulations == 13
    assert row.forward_model_calls == 26
    assert row.worker_pid == os.getpid()
    assert row.process_instance_id == "fresh-1"
    assert row.work_counters_collected
    assert adapter.cleaned
    method_names = set(FixedWorkStop.should_start_unit.__code__.co_names)
    method_names.update(FixedWorkStop.record_completed_unit.__code__.co_names)
    assert not {"time", "clock", "monotonic", "monotonic_ns"} & method_names
    assert set(FixedWorkStop.__dataclass_fields__) == {
        "requested_units",
        "completed_units",
        "mode",
    }


def test_stop_policies_reject_truncating_non_integer_inputs() -> None:
    with pytest.raises(ValueError, match="integer"):
        FixedWorkStop(2.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="integer"):
        WallClockStop(3.5, lambda: 0)  # type: ignore[arg-type]


def test_fixed_work_hashes_match_across_resource_envelopes() -> None:
    rows = []
    for load in ("idle", "loaded"):
        for lifecycle in ("fresh", "persistent"):
            rows.append(
                run_decision(
                    SyntheticSearchAdapter(),
                    {"public": [1, 2, 3]},
                    FixedWorkStop(17),
                    context(
                        case_id=f"{load}-{lifecycle}",
                        load_condition=load,
                        lifecycle=lifecycle,
                        lifecycle_id=f"{lifecycle}-1",
                        process_instance_id=f"{lifecycle}-1",
                    ),
                )
            )
    assert {row.state_hash for row in rows} == {rows[0].state_hash}
    assert {row.agent_seed_hash for row in rows} == {rows[0].agent_seed_hash}
    assert {row.selected_action_hash for row in rows} == {rows[0].selected_action_hash}
    assert {row.completed_work_units for row in rows} == {17}


def _timed_row(unit_duration: int, budget: int = 10):
    clock = FakeClock()
    adapter = SyntheticSearchAdapter(unit_hook=lambda _index: clock.advance(unit_duration))
    stop = WallClockStop(budget, clock)
    return run_decision(
        adapter,
        {"state": "timed"},
        stop,
        context(load_condition="loaded" if unit_duration > 1 else "idle"),
        monotonic_ns=clock,
        process_time_ns=clock,
    )


def test_wall_clock_completed_work_changes_under_load_intervention() -> None:
    idle = _timed_row(1)
    loaded = _timed_row(3)
    assert idle.completed_work_units == 10
    assert loaded.completed_work_units == 4
    assert loaded.completed_work_units <= 0.8 * idle.completed_work_units


def test_deadline_overshoot_is_bounded_and_recorded() -> None:
    row = _timed_row(3, budget=10)
    assert row.overshoot_ns == 2
    assert 0 <= row.overshoot_ns < 3


def test_selection_and_cleanup_are_timed_but_excluded_from_deadline_overshoot() -> None:
    clock = FakeClock()
    adapter = SyntheticSearchAdapter(
        unit_hook=lambda _index: clock.advance(3),
        selection_hook=lambda: clock.advance(100),
        cleanup_hook=lambda: clock.advance(50),
    )
    row = run_decision(
        adapter,
        {"state": "timing-boundaries"},
        WallClockStop(10, clock),
        context(),
        monotonic_ns=clock,
        process_time_ns=clock,
    )
    assert row.completed_work_units == 4
    assert row.search_wall_ns == 12
    assert row.process_cpu_ns == 12
    assert row.overshoot_ns == 2
    assert row.selection_wall_ns == 100
    assert row.cleanup_wall_ns == 50


def test_cleanup_succeeds_after_deadline_and_error() -> None:
    deadline_clock = FakeClock()
    deadline_adapter = SyntheticSearchAdapter()
    deadline = run_decision(
        deadline_adapter,
        {"state": "deadline"},
        WallClockStop(0, deadline_clock),
        context(),
        monotonic_ns=deadline_clock,
        process_time_ns=deadline_clock,
    )
    assert deadline.terminal_status == "deadline_no_work"
    assert deadline.cleanup_succeeded and deadline_adapter.cleaned

    error_adapter = SyntheticSearchAdapter(fail_on_unit=2)
    error = run_decision(error_adapter, {"state": "error"}, FixedWorkStop(5), context())
    assert error.terminal_status == "fixed_work_invalid"
    assert error.completed_work_units == 2
    assert error.cleanup_succeeded and error_adapter.cleaned


def test_game_telemetry_reconciles_decision_totals() -> None:
    decisions = [
        run_decision(
            SyntheticSearchAdapter(),
            {"decision": index},
            FixedWorkStop(index + 1),
            context(case_id="game-1", decision_index=index),
        )
        for index in range(3)
    ]
    game = GameTelemetry.from_decisions(
        case_id="game-1",
        block_id="block-1",
        agent_id="synthetic_counter_search",
        decisions=decisions,
        score=1.0,
        winner=0,
        terminal_status="completed",
    )
    assert game.decision_count == 3
    assert game.completed_work_units == 6
    assert game.completed_simulations == 6
    assert game.forward_model_calls == 12
    game.validate()
