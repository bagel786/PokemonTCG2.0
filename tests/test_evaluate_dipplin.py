from __future__ import annotations

import math

from scripts.evaluate_dipplin import (
    build_parser,
    intervention_analysis,
    latency_summary,
    merge_numeric_rows,
    numeric_mapping,
    seat_order_cells,
    wilson,
)


def _row(*, seat: int, order: str, win: int, telemetry=None):
    return {
        "hero_seat": seat,
        "actual_order": order,
        "completed": True,
        "win": win,
        "draw": 0,
        "hero_policy_errors": 0,
        "opponent_policy_errors": 0,
        "hero_illegal_actions": 0,
        "opponent_illegal_actions": 0,
        "decisions": 10,
        "hero_telemetry": telemetry or {},
        "d1_intervened": bool((telemetry or {}).get("d1_overrides", 0)),
    }


def test_latency_summary_has_requested_exact_fields():
    summary = latency_summary([1.0, 2.0, 3.0, 4.0, 5.0])
    assert summary == {
        "count": 5,
        "mean": 3.0,
        "p50": 3.0,
        "p95": 4.8,
        "p99": 4.96,
        "max": 5.0,
    }


def test_numeric_mapping_rejects_nested_bool_and_nonfinite_values():
    assert numeric_mapping(
        {"count": 2, "rate": 0.5, "flag": True, "nested": {"x": 1}, "bad": math.inf}
    ) == {"count": 2.0, "rate": 0.5}


def test_seat_order_cells_include_wilson_for_every_cross_cell():
    rows = [
        _row(seat=0, order="first", win=1),
        _row(seat=0, order="second", win=0),
        _row(seat=1, order="first", win=0),
        _row(seat=1, order="second", win=1),
    ]
    cells = seat_order_cells(rows)
    assert cells["overall"]["games"] == 4
    assert cells["overall"]["wins"] == 2
    assert cells["seat"]["0"]["games"] == 2
    assert cells["actual_order"]["second"]["games"] == 2
    assert cells["seat_x_actual_order"]["seat_1_first"]["games"] == 1
    for group in (
        [cells["overall"]],
        cells["seat"].values(),
        cells["actual_order"].values(),
        cells["seat_x_actual_order"].values(),
    ):
        assert all(len(cell["wilson_95"]) == 2 for cell in group)


def test_telemetry_merge_sums_counters_but_preserves_maximum_gauges():
    rows = [
        {"hero_telemetry": {"decisions": 3, "latency_ms_max": 8}},
        {"hero_telemetry": {"decisions": 4, "latency_ms_max": 5}},
    ]
    assert merge_numeric_rows(rows, "hero_telemetry") == {
        "decisions": 7.0,
        "latency_ms_max": 8.0,
    }


def test_intervention_analysis_understands_canonical_d1_keys_without_double_counting():
    rows = [
        _row(
            seat=0,
            order="first",
            win=1,
            telemetry={
                "d1_attempts": 3,
                "d1_abstentions": 2,
                "d1_overrides": 1,
                "d0_d1_disagreements": 1,
            },
        ),
        _row(
            seat=1,
            order="second",
            win=0,
            telemetry={"d1_attempts": 2, "d1_abstentions": 2, "d1_overrides": 0},
        ),
    ]
    analysis = intervention_analysis(rows, ("d1_overrides", "d0_d1_disagreements"))
    assert analysis["enabled"] is True
    assert analysis["intervention_games"] == 1
    assert analysis["canonical_counts"] == {
        "attempts": 5.0,
        "abstentions": 4.0,
        "overrides": 1.0,
        "d0_d1_disagreements": 1.0,
    }
    assert analysis["intervened"]["overall"]["win_rate"] == 1.0
    assert analysis["returned_d0"]["overall"]["win_rate"] == 0.0


def test_wilson_and_fail_closed_decision_default():
    lower, upper = wilson(50, 100)
    assert lower < 0.5 < upper
    assert build_parser().get_default("max_decisions") == 2000
