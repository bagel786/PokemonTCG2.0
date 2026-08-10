from __future__ import annotations

import pytest

from scripts import audit_grim_proof_search as audit


def raw_observation(*, seat: int = 0, option_count: int = 2) -> dict:
    return {
        "current": {"yourIndex": seat},
        "select": {
            "minCount": 1,
            "maxCount": 1,
            "option": [{"type": 1} for _ in range(option_count)],
        },
    }


def seat_row(*, status: str, observation: dict | None = None, action=None) -> dict:
    return {
        "status": status,
        "observation": observation,
        "action": [] if action is None else action,
    }


def test_replay_alignment_uses_observation_t_and_action_t_plus_one():
    observation_t = raw_observation()
    steps = [
        [seat_row(status="ACTIVE", observation=observation_t, action=[0])],
        [seat_row(status="ACTIVE", observation=raw_observation(), action=[1])],
    ]

    decision = audit.replay_aligned_decision(steps, seat=0, step_t=0)

    assert decision is not None
    assert decision.observation is observation_t
    assert decision.historical_action == (1,)
    assert decision.observation_step_t == 0
    assert decision.action_step_t_plus_1 == 1


def test_replay_alignment_ignores_inactive_stale_select_and_rejects_shifted_action():
    inactive = [
        [seat_row(status="INACTIVE", observation=raw_observation(), action=[0])],
        [seat_row(status="ACTIVE", observation=raw_observation(), action=[1])],
    ]
    assert audit.replay_aligned_decision(inactive, seat=0, step_t=0) is None

    invalid = [
        [seat_row(status="ACTIVE", observation=raw_observation(option_count=1))],
        [seat_row(status="ACTIVE", observation=raw_observation(), action=[1])],
    ]
    with pytest.raises(ValueError, match="outside row-t options"):
        audit.replay_aligned_decision(invalid, seat=0, step_t=0)


def test_replay_alignment_requires_observation_viewer_to_match_seat():
    steps = [
        [seat_row(status="ACTIVE", observation=raw_observation(seat=1))],
        [seat_row(status="ACTIVE", observation=raw_observation(), action=[0])],
    ]
    with pytest.raises(ValueError, match="viewer"):
        audit.replay_aligned_decision(steps, seat=0, step_t=0)


def test_complete_turn_factory_returns_fresh_exact_policy_wrappers(monkeypatch):
    model = object()
    seen = []

    def fake_d842(received_model, observation):
        seen.append((received_model, observation))
        return [3]

    monkeypatch.setattr(audit, "d842_action", fake_d842)
    factory = audit.FrozenD842SelectorFactory(model)  # type: ignore[arg-type]
    first = factory()
    second = factory()

    assert first is not second
    assert first.model is model and second.model is model
    assert first.choose("branch-a") == [3]
    assert second.choose("branch-b") == [3]
    assert seen == [(model, "branch-a"), (model, "branch-b")]


def test_repeat_signature_drift_is_detected_for_fail_closed_audit(monkeypatch):
    monkeypatch.setattr(audit, "proof_attempt_signature", lambda result, _obs: result)
    assert audit.proof_attempts_consistent([{"strict": 4}, {"strict": 4}], None)
    assert not audit.proof_attempts_consistent([{"strict": 4}, {"strict": 3}], None)


def test_cli_exposes_complete_turn_horizon_and_all_work_limits():
    args = audit.build_parser().parse_args(
        [
            "--runner-mode",
            "complete-turn",
            "--max-episodes",
            "3",
            "--max-decisions",
            "17",
            "--max-search-triggers",
            "5",
            "--search-trigger-stride",
            "11",
            "--search-trigger-offset",
            "2",
            "--max-turn-steps",
            "23",
            "--proof-repeats",
            "3",
            "--timeout-ms",
            "900",
        ]
    )
    assert args.runner_mode == "complete-turn"
    assert args.max_episodes == 3
    assert args.max_decisions == 17
    assert args.max_search_triggers == 5
    assert args.search_trigger_stride == 11
    assert args.search_trigger_offset == 2
    assert args.max_turn_steps == 23
    assert args.proof_repeats == 3
    assert args.timeout_ms == 900


def test_complete_turn_audit_defaults_to_three_repeat_fail_closed_gate():
    args = audit.build_parser().parse_args([])
    assert args.runner_mode == "complete-turn"
    assert args.proof_repeats == 3
