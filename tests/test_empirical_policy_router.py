from __future__ import annotations

from types import SimpleNamespace as NS

from ptcg_ai.features import DecisionFeatures, OptionFeatures
from ptcg_ai import empirical_policy_router as router_module


class FakeAgent:
    def __init__(self, action, *, increment_error=False):
        self.action = list(action)
        self.errors = 0
        self.calls = 0
        self.increment_error = increment_error

    def __call__(self, _obs):
        self.calls += 1
        if self.increment_error:
            self.errors += 1
        return list(self.action)


def features(context=0, a2_type=10, temporal_type=7):
    numeric = [0.0] * 13
    return DecisionFeatures(
        global_features=[0.0] * 118,
        state_tokens=[1],
        options=[
            OptionFeatures(a2_type, context, 1, 0, 0, 0, 0, numeric),
            OptionFeatures(temporal_type, context, 2, 0, 0, 0, 0, numeric),
        ],
        feature_version=3,
    )


def make_agent(*, exact_action=(0,), temporal_action=(1,), temporal_error=False):
    agent = router_module.EmpiricalPolicyRouterAgent.__new__(router_module.EmpiricalPolicyRouterAgent)
    agent.exact = FakeAgent(exact_action)
    agent.temporal = FakeAgent(temporal_action, increment_error=temporal_error)
    agent.routes = [
        {"context": 7},
        {"context": 0, "a2_option_type": 10, "temporal_option_type": 7},
    ]
    agent.actual_order = "second"
    agent.deck = list(range(60))
    agent.errors = 0
    agent.semantic_disagreements = 0
    agent.temporal_routes = 0
    return agent


def install_mocks(monkeypatch, obs, encoded):
    monkeypatch.setattr(router_module, "to_observation_class", lambda _value: obs)
    monkeypatch.setattr(router_module, "encode_observation", lambda _obs, _schema: encoded)
    monkeypatch.setattr(
        router_module,
        "sanitize_selection",
        lambda _select, action, _count: list(action),
    )


def observation(*, first_player=0, your_index=1):
    return NS(
        select=NS(minCount=1, maxCount=1, option=[object(), object()]),
        current=NS(firstPlayer=first_player, yourIndex=your_index),
    )


def test_routes_only_configured_public_cell_and_actual_order(monkeypatch):
    obs = observation()
    install_mocks(monkeypatch, obs, features())
    agent = make_agent()
    assert agent({"select": {}}) == [1]
    assert agent.semantic_disagreements == 1
    assert agent.temporal_routes == 1

    # The same cell while playing first is exact A2 and does not query temporal.
    obs = observation(first_player=1, your_index=1)
    install_mocks(monkeypatch, obs, features())
    agent = make_agent()
    assert agent({"select": {}}) == [0]
    assert agent.temporal.calls == 0

    # A semantic disagreement outside configured cells stays with A2.
    obs = observation()
    install_mocks(monkeypatch, obs, features(context=3))
    agent = make_agent()
    assert agent({"select": {}}) == [0]
    assert agent.semantic_disagreements == 1
    assert agent.temporal_routes == 0


def test_multi_action_and_temporal_error_fail_closed(monkeypatch):
    obs = observation()
    install_mocks(monkeypatch, obs, features())
    agent = make_agent(exact_action=(0, 1))
    assert agent({"select": {}}) == [0, 1]
    assert agent.temporal.calls == 0

    agent = make_agent(temporal_error=True)
    assert agent({"select": {}}) == [0]
    assert agent.errors == 1
    assert agent.temporal_routes == 0
