from __future__ import annotations

from types import SimpleNamespace as NS

from cg.api import SelectContext

from ptcg_ai import a2_outcome_order_router as router


class FakeAgent:
    def __init__(self, action):
        self.action = list(action)
        self.calls = 0
        self.errors = 0
        self.policy = NS()
        self.fallback = NS()

    def __call__(self, _observation):
        self.calls += 1
        return list(self.action)


def _agent() -> router.OutcomeOrderAgent:
    value = router.OutcomeOrderAgent.__new__(router.OutcomeOrderAgent)
    value.exact = FakeAgent([9])
    value.policy_first = FakeAgent([1])
    value.policy_second = FakeAgent([2])
    value.deck = list(range(60))
    value.actual_order = None
    value.errors = 0
    return value


def _observation(context=SelectContext.MAIN, first=0, yours=0):
    return NS(select=NS(context=context), current=NS(firstPlayer=first, yourIndex=yours))


def test_router_keeps_prelatch_exact_and_routes_only_after_latch(monkeypatch):
    agent = _agent()
    monkeypatch.setattr(router, "to_observation_class", lambda value: value["parsed"])
    monkeypatch.setattr(router, "sanitize_selection", lambda _select, action, _count: list(action))

    assert agent({"select": {}, "parsed": _observation(SelectContext.IS_FIRST)}) == [9]
    assert agent.actual_order is None
    assert agent.policy_first.calls == 0
    assert agent.policy_second.calls == 0
    assert agent({"select": {}, "parsed": _observation(first=0, yours=0)}) == [1]
    assert agent.actual_order == "first"

    agent({"select": None})
    assert agent.actual_order is None
    assert agent({"select": {}, "parsed": _observation(first=0, yours=1)}) == [2]
    assert agent.actual_order == "second"


def test_router_fails_closed_on_candidate_error_sanitizer_error_and_order_change(monkeypatch):
    agent = _agent()
    monkeypatch.setattr(router, "to_observation_class", lambda value: value["parsed"])
    monkeypatch.setattr(router, "sanitize_selection", lambda _select, action, _count: list(action))
    second = _observation(first=0, yours=1)
    assert agent({"select": {}, "parsed": second}) == [2]

    class Incrementing(FakeAgent):
        def __call__(self, observation):
            self.errors += 1
            return super().__call__(observation)

    agent.policy_second = Incrementing([7])
    assert agent({"select": {}, "parsed": second}) == [9]
    assert agent.errors == 1

    agent.policy_second = FakeAgent([7])
    monkeypatch.setattr(router, "sanitize_selection", lambda *_args: (_ for _ in ()).throw(ValueError("bad")))
    assert agent({"select": {}, "parsed": second}) == [9]
    assert agent.errors == 2

    changed = _observation(first=1, yours=1)
    assert agent({"select": {}, "parsed": changed}) == [9]
    assert agent.errors == 3


def test_router_fails_closed_when_observation_conversion_fails(monkeypatch):
    agent = _agent()
    monkeypatch.setattr(router, "to_observation_class", lambda _value: (_ for _ in ()).throw(ValueError("bad")))

    assert agent({"select": {}}) == [9]
    assert agent.errors == 1
