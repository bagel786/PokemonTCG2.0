from __future__ import annotations

import gzip
from pathlib import Path

import numpy as np

from scripts.run_grim_sequence_oracle_v0 import (
    SequencePlan,
    _complete_actions,
    aggregate,
    choose_confirmation_plan,
    decision_from,
    own_turn_ordinal,
    seed_for,
    structural_static_audit,
    summarize_worlds,
    synthetic_stranded_munk_discovery,
    write_jsonl_gz,
)


class _Select:
    def __init__(self, minimum: int, maximum: int, options: int):
        self.minCount = minimum
        self.maxCount = maximum
        self.option = [object() for _ in range(options)]


class _Obs:
    def __init__(self, minimum: int, maximum: int, options: int):
        self.select = _Select(minimum, maximum, options)


def _terminal(score: float, win: int, deviations: int = 0, invalidated: bool = False) -> dict:
    return {
        "score": score,
        "win": win,
        "draw": 0,
        "result": 0,
        "executed_deviations": deviations,
        "invalidated": invalidated,
        "steps": 1,
        "action_trace_sha256": "A" * 64,
    }


def _paired(baseline: tuple[float, int], candidate: tuple[float, int], deviations: int = 1) -> dict:
    return {
        "baseline": _terminal(*baseline),
        "candidate": _terminal(*candidate, deviations=deviations),
    }


def test_own_turn_ordinal_respects_actual_first_player() -> None:
    assert own_turn_ordinal(3, 0, 0) == 2
    assert own_turn_ordinal(4, 0, 1) == 2


def test_seed_schedules_are_purpose_and_phase_separated() -> None:
    values = {
        seed_for(schedule, 123, "B" * 64, world, purpose)
        for schedule in ("proposal", "confirmation")
        for world in range(4)
        for purpose in ("hidden", "rollout")
    }
    assert len(values) == 16


def test_complete_action_prior_respects_count_bounds_and_includes_baseline() -> None:
    actions = _complete_actions(
        _Obs(1, 2, 4),
        [2],
        np.asarray([4.0, 3.0, 2.0, 1.0]),
        np.asarray([0.0, 1.0, 2.0]),
        alternatives=3,
        exhaustive_options=6,
    )
    selected = {action for action, _score in actions}
    assert (2,) in selected
    assert all(1 <= len(action) <= 2 for action in selected)
    assert len(selected) == 10


def test_complete_action_prior_never_reads_a_value_head() -> None:
    # The helper accepts only option and count logits; there is no value input.
    actions = _complete_actions(
        _Obs(1, 1, 3),
        [0],
        np.asarray([1.0, 3.0, 2.0]),
        np.asarray([0.0, 0.0]),
        alternatives=2,
        exhaustive_options=2,
    )
    assert [action for action, _score in actions] == [(1,), (2,), (0,)]


def test_synthetic_stranded_munk_requires_two_coordinated_deviations() -> None:
    proof = synthetic_stranded_munk_discovery()
    assert proof["passed"] is True
    assert proof["winning_trace"] == [
        "attach_active",
        "retreat",
        "promote_grim",
        "shadow_bullet",
    ]
    assert len(proof["deviations"]) == 2
    assert proof["hard_coded_in_runtime"] is False


def test_static_contract_is_index_free_and_truncation_has_no_value() -> None:
    audit = structural_static_audit()
    assert audit["raw_prompt_local_indices_persisted"] is False
    assert audit["truncation_terminal_value"] is None
    assert audit["nested_boundaries_eligible"] is True
    assert audit["policy_engine_errors_fail_closed"] is True


def test_world_summary_allows_expected_gain_with_some_downside() -> None:
    worlds = [
        _paired((-1.0, 0), (1.0, 1)),
        _paired((-1.0, 0), (1.0, 1)),
        _paired((1.0, 1), (-1.0, 0)),
        _paired((1.0, 1), (1.0, 1)),
    ]
    summary = summarize_worlds(worlds)
    assert summary["better"] == 2
    assert summary["worse"] == 1
    assert summary["paired_mean_terminal_delta"] == 0.5
    assert summary["downside_rate"] == 0.25


def test_nonpositive_proposal_selects_exact_baseline() -> None:
    plan = SequencePlan()
    selected = choose_confirmation_plan(
        [plan],
        [
            {
                "plan_id": plan.digest,
                "plan": plan.to_dict(),
                "summary": {
                    "paired_mean_terminal_delta": 0.0,
                    "downside_rate": 0.0,
                    "paired_win_delta": 0.0,
                },
            }
        ],
    )
    assert selected == SequencePlan()


def test_aggregate_counts_two_actual_deviation_rescue_once_per_root() -> None:
    rows = [
        {
            "root_id": "root-a",
            "mechanism": "attach -> retreat",
            "confirmation": {
                "plan": {"planned_deviations": 2},
                "worlds": [
                    _paired((-1.0, 0), (1.0, 1), deviations=2),
                    _paired((1.0, 1), (1.0, 1), deviations=2),
                ],
            },
        }
    ]
    result = aggregate(rows)
    assert result["candidate_only_wins"] == 1
    assert result["candidate_only_wins_with_two_actual_deviations"] == 1
    assert result["independent_two_actual_deviation_rescue_roots"] == 1


def test_hard_interpretation_gate_rejects_large_one_action_signal() -> None:
    recommendation, reason = decision_from(
        {
            "paired_win_delta_pp": 9.0,
            "independent_two_actual_deviation_rescue_roots": 0,
            "selected_mechanism_families": {"play": 10},
        }
    )
    assert recommendation == "SEQUENCE_SEARCH_WEAK"
    assert "0 independent" in reason


def test_hard_interpretation_gate_marks_large_sequence_signal_strong() -> None:
    recommendation, _reason = decision_from(
        {
            "paired_win_delta_pp": 8.0,
            "independent_two_actual_deviation_rescue_roots": 6,
            "selected_mechanism_families": {"attach -> retreat": 3},
        }
    )
    assert recommendation == "SEQUENCE_SEARCH_STRONG"


def test_jsonl_gzip_is_deterministic(tmp_path: Path) -> None:
    first, second = tmp_path / "a.jsonl.gz", tmp_path / "b.jsonl.gz"
    rows = [{"b": 2, "a": 1}, {"x": [3, 4]}]
    write_jsonl_gz(first, rows)
    write_jsonl_gz(second, rows)
    assert first.read_bytes() == second.read_bytes()
    with gzip.open(first, "rt", encoding="utf-8") as handle:
        assert len(handle.readlines()) == 2
