from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from cg.api import Option, OptionType, SelectContext, SelectType
from ptcg_ai.grim_runtime_policy import (
    SEARCH_DISABLED_RATIONALE,
    GrimRuntimePolicy,
    SearchDisabledProof,
)


def observation(option_types, *, context=SelectContext.MAIN, minimum=0, maximum=1):
    options = [
        Option(
            option_type,
            attackId=(900 + index) if int(option_type) == int(OptionType.ATTACK) else None,
        )
        for index, option_type in enumerate(option_types)
    ]
    return NS(
        select=NS(
            option=options,
            context=context,
            type=(
                SelectType.CARD
                if context
                in {
                    SelectContext.SETUP_ACTIVE_POKEMON,
                    SelectContext.SETUP_BENCH_POKEMON,
                }
                else SelectType.MAIN
            ),
            minCount=minimum,
            maxCount=maximum,
        ),
        current=NS(result=-1),
        logs=[],
        search_begin_input="opaque",
    )


class FakeGuardrail:
    def __init__(self, *, result=None, error=None, commit_error=None, events=None):
        self.result = result
        self.error = error
        self.commit_error = commit_error
        self.events = events if events is not None else []
        self.reset_calls = 0
        self.apply_calls = 0
        self.commit_calls = 0
        self.committed = []

    def reset(self):
        self.reset_calls += 1

    def apply(self, obs, ranked, desired):
        self.apply_calls += 1
        self.events.append(("guardrail", tuple(ranked), desired))
        if self.error is not None:
            raise self.error
        if self.result is not None:
            return self.result
        return list(ranked), int(desired), None

    def commit(self, obs, action):
        self.commit_calls += 1
        self.committed.append(list(action))
        self.events.append(("commit", tuple(action)))
        if self.commit_error is not None:
            raise self.commit_error


class FakeProof:
    def __init__(self, *, result=None, error=None, events=None, reason="fake_proof"):
        self.result = result
        self.error = error
        self.events = events if events is not None else []
        self.reason = reason
        self.reset_calls = 0
        self.choose_calls = 0
        self.inputs = []

    def reset(self):
        self.reset_calls += 1

    def choose(self, obs, action):
        self.choose_calls += 1
        self.inputs.append(list(action))
        self.events.append(("proof", tuple(action)))
        if self.error is not None:
            raise self.error
        return list(action) if self.result is None else list(self.result)

    @property
    def telemetry(self):
        return {"last": {"reason": self.reason}}


def policy(guardrail=None, proof=None, tactical=None):
    return GrimRuntimePolicy(
        guardrail=guardrail or FakeGuardrail(),
        proof=proof or FakeProof(),
        tactical=tactical,
    )


def test_pipeline_order_is_guardrail_tactical_sanitize_commit_then_proof():
    events = []
    guardrail = FakeGuardrail(
        result=([1, 0, 2], 1, "guardrail:attack"),
        events=events,
    )
    proof = FakeProof(result=[1], events=events, reason="proved_same_turn_terminal_win")

    def tactical(_obs, ranked, desired):
        events.append(("tactical", tuple(ranked), desired))
        return [2, 1, 0], 1, "end_with_productive_attack"

    runtime_policy = policy(guardrail, proof, tactical)
    obs = observation([OptionType.END, OptionType.ATTACK, OptionType.ATTACK])
    assert runtime_policy.choose(obs, [0, 1, 2], 1) == [1]
    assert events == [
        ("guardrail", (0, 1, 2), 1),
        ("tactical", (1, 0, 2), 1),
        ("commit", (2,)),
        ("proof", (2,)),
    ]
    assert guardrail.commit_calls == 1
    assert runtime_policy.telemetry()["last"] == {
        "status": "proof_override",
        "source": "proof",
        "guardrail_reason": "guardrail:attack",
        "tactical_reason": "end_with_productive_attack",
        "suppressed_tactical_reason": None,
        "proof_reason": "proved_same_turn_terminal_win",
        "commit_attempted": True,
        "error_stage": None,
        "error_type": None,
    }


def test_generic_setup_bench_rule_is_suppressed_and_guardrail_setup_is_committed_once():
    events = []
    guardrail = FakeGuardrail(
        result=([1, 0], 1, "setup:bench_impidimp"),
        events=events,
    )
    # A misbehaving injected proof demonstrates the coordinator's setup boundary:
    # committed setup decisions cannot be altered after commit.
    proof = FakeProof(result=[0], events=events)

    def generic_setup(_obs, _ranked, _desired):
        events.append(("tactical", (1, 0), 1))
        return [0, 1], 1, "setup_bench_basic"

    runtime_policy = policy(guardrail, proof, generic_setup)
    obs = observation(
        [OptionType.CARD, OptionType.CARD],
        context=SelectContext.SETUP_BENCH_POKEMON,
        minimum=0,
    )
    assert runtime_policy.choose(obs, [0, 1], 0) == [1]
    assert guardrail.committed == [[1]]
    assert guardrail.commit_calls == 1
    assert proof.inputs == [[1]]
    last = runtime_policy.telemetry()["last"]
    assert last["suppressed_tactical_reason"] == "setup_bench_basic"
    assert last["status"] == "proof_fallthrough"
    assert last["error_stage"] == "proof"


def test_setup_generic_rule_cannot_turn_d842_zero_selection_into_a_bench_action():
    guardrail = FakeGuardrail()
    proof = FakeProof()

    def generic_setup(_obs, ranked, _desired):
        return list(ranked), 1, "setup_bench_basic"

    runtime_policy = policy(guardrail, proof, generic_setup)
    obs = observation(
        [OptionType.CARD],
        context=SelectContext.SETUP_BENCH_POKEMON,
        minimum=0,
    )
    assert runtime_policy.choose(obs, [0], 0) == []
    assert guardrail.committed == [[]]
    assert proof.inputs == [[]]


@pytest.mark.parametrize(
    ("error_stage", "guardrail_error", "tactical_error"),
    [
        ("guardrail", RuntimeError("guardrail failed"), None),
        ("tactical", None, RuntimeError("tactical failed")),
    ],
)
def test_guardrail_or_coordinator_invariant_failure_preserves_exact_d842(
    error_stage,
    guardrail_error,
    tactical_error,
):
    guardrail = FakeGuardrail(
        result=([1, 0], 1, "guardrail:changed"),
        error=guardrail_error,
    )
    proof = FakeProof(result=[1])

    def tactical(_obs, ranked, desired):
        if tactical_error is not None:
            raise tactical_error
        return list(ranked), desired, None

    runtime_policy = policy(guardrail, proof, tactical)
    obs = observation([OptionType.END, OptionType.ATTACK])
    assert runtime_policy.choose(obs, [0, 0, 99, 1], 1) == [0]
    assert proof.choose_calls == 0
    assert guardrail.commit_calls == 1
    assert guardrail.committed == [[0]]
    last = runtime_policy.telemetry()["last"]
    assert last["status"] == "d842_fallthrough"
    assert last["source"] == "d842"
    assert last["error_stage"] == error_stage


def test_proof_exception_or_invalid_selection_preserves_sanitized_guardrail_action():
    obs = observation([OptionType.END, OptionType.ATTACK])
    for proof in (FakeProof(error=RuntimeError("proof failed")), FakeProof(result=[99])):
        guardrail = FakeGuardrail(result=([1, 0], 1, "guardrail:attack"))
        runtime_policy = policy(
            guardrail,
            proof,
            lambda _obs, ranked, desired: (ranked, desired, None),
        )
        assert runtime_policy.choose(obs, [0, 1], 1) == [1]
        assert proof.inputs == [[1]]
        assert guardrail.committed == [[1]]
        assert runtime_policy.telemetry()["last"]["status"] == "proof_fallthrough"


def test_only_attack_related_tactical_invariants_are_admitted(monkeypatch):
    guardrail = FakeGuardrail()
    proof = FakeProof()
    runtime_policy = policy(guardrail, proof)

    end_obs = observation([OptionType.END, OptionType.ATTACK], minimum=0)
    monkeypatch.setattr("ptcg_ai.tactical_shield.attack_nullified", lambda _obs, _option: False)
    assert runtime_policy.choose(end_obs, [0, 1], 1) == [1]
    assert runtime_policy.telemetry()["last"]["tactical_reason"] == "end_with_productive_attack"

    nullified_obs = observation(
        [OptionType.ATTACK, OptionType.ATTACK, OptionType.END],
        minimum=1,
    )
    monkeypatch.setattr(
        "ptcg_ai.tactical_shield.attack_nullified",
        lambda _obs, option: option.attackId == 900,
    )
    assert runtime_policy.choose(nullified_obs, [0, 1, 2], 1) == [1]
    assert runtime_policy.telemetry()["last"]["tactical_reason"] == "nullified_attack"


def test_commit_failure_is_coordinator_fallthrough_and_is_attempted_only_once():
    guardrail = FakeGuardrail(
        result=([1, 0], 1, "guardrail:attack"),
        commit_error=RuntimeError("commit failed"),
    )
    proof = FakeProof(result=[1])
    runtime_policy = policy(guardrail, proof, lambda _obs, ranked, desired: (ranked, desired, None))
    assert runtime_policy.choose(observation([OptionType.END, OptionType.ATTACK]), [0, 1], 1) == [0]
    assert guardrail.commit_calls == 1
    assert proof.choose_calls == 0
    assert runtime_policy.telemetry()["last"]["error_stage"] == "coordinator"


def test_reset_reaches_both_components_and_no_option_indices_persist():
    guardrail = FakeGuardrail()
    proof = FakeProof()
    runtime_policy = policy(guardrail, proof, lambda _obs, ranked, desired: (ranked, desired, None))
    assert guardrail.reset_calls == proof.reset_calls == 1
    runtime_policy.choose(observation([OptionType.END]), [0], 1)
    assert runtime_policy.telemetry()["calls"] == 1

    runtime_policy.reset()
    assert guardrail.reset_calls == proof.reset_calls == 2
    assert runtime_policy.telemetry()["calls"] == 0
    assert runtime_policy.telemetry()["last"]["status"] == "reset"
    assert not any(
        "action" in name or "ranked" in name or "option" in name
        for name in runtime_policy.__dict__
    )


def test_packaged_search_disabled_proof_is_exact_stateless_fallthrough():
    proof = SearchDisabledProof()
    proof.reset()
    baseline = [2, 0]
    assert proof.choose(object(), baseline) == baseline
    assert proof.telemetry == {
        "phase": "runtime_proof",
        "calls": 1,
        "last": {"status": "disabled", "reason": SEARCH_DISABLED_RATIONALE},
    }
    assert not any("action" in name or "option" in name for name in proof.__dict__)
    proof.reset()
    assert proof.telemetry["calls"] == 0
