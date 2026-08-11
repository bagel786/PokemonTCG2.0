from __future__ import annotations

from types import SimpleNamespace as NS

import numpy as np

from ptcg_ai.features import DecisionFeatures, OptionFeatures
from ptcg_ai import temporal_context_gate as gate_module


class FakeModel:
    def __init__(self, logits):
        self.logits = np.asarray(logits, dtype=np.float32)

    def predict(self, _features):
        counts = np.full(61, -10.0, dtype=np.float32)
        counts[1] = 10.0
        return self.logits, counts, 0.0


class FakeAgent:
    def __init__(self, action, logits, *, increment_error=False):
        self.action = list(action)
        self.policy = NS(model=FakeModel(logits), tactical_shield=True)
        self.errors = 0
        self.calls = 0
        self.increment_error = increment_error

    def __call__(self, _obs):
        self.calls += 1
        if self.increment_error:
            self.errors += 1
        return list(self.action)


class FakeGate:
    def __init__(self, choose):
        self.choose = choose
        self.calls = 0

    def choose_continuation(self, vector):
        self.calls += 1
        assert vector.shape == (858,)
        return self.choose


def features():
    numeric = [0.0] * 13
    return DecisionFeatures(
        global_features=[0.0] * 118,
        state_tokens=[1],
        options=[
            OptionFeatures(1, 0, 0, 0, 0, 0, 0, numeric),
            OptionFeatures(2, 0, 0, 0, 0, 0, 0, numeric),
        ],
        feature_version=3,
    )


def make_agent(*, choose=True, continuation_error=False):
    agent = gate_module.TemporalContextGateAgent.__new__(gate_module.TemporalContextGateAgent)
    agent.exact = FakeAgent([0], [2.0, 0.0])
    agent.continuation = FakeAgent([1], [0.0, 2.0], increment_error=continuation_error)
    agent.gate = FakeGate(choose)
    agent.deck = list(range(60))
    agent.errors = 0
    agent.semantic_disagreements = 0
    agent.continuation_routes = 0
    return agent


def observation(minimum=1, maximum=1):
    return NS(select=NS(minCount=minimum, maxCount=maximum, option=[object(), object()]))


def install_mocks(monkeypatch, obs):
    monkeypatch.setattr(gate_module, "to_observation_class", lambda _value: obs)
    monkeypatch.setattr(gate_module, "encode_observation", lambda _obs, _schema: features())
    monkeypatch.setattr(gate_module, "public_gate_features", lambda *args: np.zeros(858, dtype=np.float32))
    monkeypatch.setattr(gate_module, "sanitize_selection", lambda _select, action, _count: list(action))


def test_routes_only_single_action_semantic_disagreement(monkeypatch):
    obs = observation()
    install_mocks(monkeypatch, obs)
    agent = make_agent(choose=True)
    assert agent({"select": {}, "parsed": obs}) == [1]
    assert agent.semantic_disagreements == 1
    assert agent.continuation_routes == 1
    assert agent.gate.calls == 1
    assert agent.exact.policy.tactical_shield and agent.continuation.policy.tactical_shield

    # The learned gate can explicitly keep A2.
    agent = make_agent(choose=False)
    assert agent({"select": {}, "parsed": obs}) == [0]
    assert agent.gate.calls == 1

    # A semantic agreement bypasses the gate and is exactly A2-routed.
    agent = make_agent(choose=True)
    agent.continuation.policy.model = FakeModel([3.0, 0.0])
    assert agent({"select": {}, "parsed": obs}) == [0]
    assert agent.gate.calls == 0


def test_multi_action_and_candidate_error_fail_closed_to_a2(monkeypatch):
    obs = observation(minimum=2, maximum=2)
    install_mocks(monkeypatch, obs)
    agent = make_agent(choose=True)
    assert agent({"select": {}, "parsed": obs}) == [0]
    assert agent.gate.calls == 0

    obs = observation()
    install_mocks(monkeypatch, obs)
    agent = make_agent(choose=True, continuation_error=True)
    assert agent({"select": {}, "parsed": obs}) == [0]
    assert agent.continuation.calls == 1
    assert agent.exact.calls == 1
    assert agent.errors == 1
