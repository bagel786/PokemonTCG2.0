from __future__ import annotations

from types import SimpleNamespace

from scripts.build_a2_rebased_mirror_q_pilot import (
    ALREADY_ADOPTED,
    PILOT_CANDIDATE,
    SHIELD_CONFLICT_ADOPTED,
    SHIELD_CONFLICT_NONADOPTED,
    classify_semantics,
    q_evaluation_signature,
    rejected_nondeterministic_evaluation,
    retention_decision,
    route_continuation,
    score_diagnostics,
)
import scripts.build_a2_rebased_mirror_q_pilot as pilot


def semantic(value: int) -> dict:
    return {"options": [{"value": value}]}


def test_classification_keeps_only_same_baseline_nonlabels():
    baseline, label, other = semantic(1), semantic(2), semantic(3)
    assert classify_semantics(baseline, baseline, label) == PILOT_CANDIDATE
    assert classify_semantics(label, label, label) == ALREADY_ADOPTED
    assert classify_semantics(baseline, label, label) == SHIELD_CONFLICT_ADOPTED
    assert classify_semantics(baseline, other, label) == SHIELD_CONFLICT_NONADOPTED


def test_continuation_is_routed_by_acting_seat():
    hero_calls, opponent_calls = [], []
    hero = lambda obs: hero_calls.append(obs.current.yourIndex) or [10]
    opponent = lambda obs: opponent_calls.append(obs.current.yourIndex) or [20]
    assert route_continuation(SimpleNamespace(current=SimpleNamespace(yourIndex=0)), 0, hero, opponent) == [10]
    assert route_continuation(SimpleNamespace(current=SimpleNamespace(yourIndex=1)), 0, hero, opponent) == [20]
    assert hero_calls == [0]
    assert opponent_calls == [1]


def test_retention_fails_closed_on_truncation_or_error():
    admitted = retention_decision([-1, -1, 0, 0], [0, 0, 0, 0], [], 4)
    assert admitted["retained"] is True
    assert admitted["coverage_complete"] is True
    assert retention_decision([-1, None, 0, 0], [0, 0, 0, 0], [], 4)["retained"] is False
    assert retention_decision([-1, -1, 0, 0], [0, 0, 0, 0], ["failure"], 4)["retained"] is False


def test_retention_requires_no_regressing_worlds():
    result = retention_decision([-1, -1, 0, 1], [0, 0, 1, 0], [], 4)
    assert result["coverage_complete"] is True
    assert result["all_worlds_nonnegative"] is False
    assert result["retained"] is False


def test_score_diagnostics_separates_neutral_and_mixed_rows():
    rows = [
        {
            "actual_order": "first",
            "q_evaluation": {"worlds": [{"delta": 0.0}, {"delta": 0.0}]},
        },
        {
            "actual_order": "second",
            "q_evaluation": {"worlds": [{"delta": 2.0}, {"delta": -2.0}]},
        },
    ]
    diagnostics = score_diagnostics(rows)
    assert diagnostics["overall"]["all_worlds_equal"] == 1
    assert diagnostics["overall"]["any_positive_world"] == 1
    assert diagnostics["overall"]["any_negative_world"] == 1


def test_nondeterministic_audit_payload_is_fixed_and_fail_closed():
    rejected = rejected_nondeterministic_evaluation(8, 320, 3)
    assert rejected["retained"] is False
    assert rejected["raw_rollout_values_persisted"] is False
    assert rejected["worlds"] == []
    row = {"q_evaluation": rejected}
    assert q_evaluation_signature(row) == q_evaluation_signature(row)


def test_score_branch_resets_rng_and_uses_a_fresh_root(monkeypatch):
    calls = []

    class Backend:
        def reset_seed(self, seed):
            calls.append(("reset", seed))

        def begin(self, observation, kwargs, *, manual_coin):
            calls.append(("begin", manual_coin, kwargs))
            return SimpleNamespace(searchId=10)

        def step(self, search_id, action):
            calls.append(("step", search_id, list(action)))
            return SimpleNamespace(searchId=11)

        def release(self, search_id):
            calls.append(("release", search_id))

        def end(self):
            calls.append(("end",))

    backend = Backend()
    monkeypatch.setattr(pilot, "_SEARCH_BACKEND", backend)
    expected = pilot.Rollout(1.0, 3, True)
    monkeypatch.setattr(pilot, "_rollout", lambda child, player: expected)
    obs = SimpleNamespace(search_begin_input="opaque")
    kwargs = {"your_deck": [1]}
    assert pilot._score_branch(obs, kwargs, [4], 0, 123) == expected
    assert calls == [
        ("reset", 123),
        ("begin", False, kwargs),
        ("step", 10, [4]),
        ("release", 10),
        ("end",),
    ]
