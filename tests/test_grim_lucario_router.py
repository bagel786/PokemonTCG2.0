from types import SimpleNamespace

import ptcg_ai.agent as agent_module
from ptcg_ai.agent import CompetitionAgent, lucario_publicly_detected


def card(card_id):
    return SimpleNamespace(id=card_id, energyCards=[], tools=[], preEvolution=[])


def observation(opponent_cards=(), own_cards=(), select=True):
    players = [
        SimpleNamespace(active=[card(value) for value in own_cards], bench=[], discard=[]),
        SimpleNamespace(active=[card(value) for value in opponent_cards], bench=[], discard=[]),
    ]
    return SimpleNamespace(
        current=SimpleNamespace(players=players, yourIndex=0),
        logs=[],
        select=SimpleNamespace() if select else None,
    )


def test_detector_reads_only_opponent_public_cards():
    assert lucario_publicly_detected(observation(opponent_cards=[677]))
    assert lucario_publicly_detected(observation(opponent_cards=[678]))
    assert not lucario_publicly_detected(observation(own_cards=[678]))
    assert not lucario_publicly_detected(observation(opponent_cards=[675, 676]))


def test_router_latches_and_resets(monkeypatch):
    monkeypatch.setattr(agent_module, "to_observation_class", lambda value: value)
    calls = []

    class Policy:
        def __init__(self, name):
            self.name = name

        def choose(self, obs):
            calls.append(self.name)
            return [0]

    agent = CompetitionAgent.__new__(CompetitionAgent)
    agent.deck = [1] * 60
    agent.policy = Policy("base")
    agent.specialist = Policy("specialist")
    agent.fallback = Policy("fallback")
    agent.lucario_routed = False
    agent.errors = 0

    assert agent(observation(opponent_cards=[100])) == [0]
    assert agent(observation(opponent_cards=[677])) == [0]
    assert agent(observation(opponent_cards=[100])) == [0]
    assert calls == ["base", "specialist", "specialist"]

    assert agent(observation(select=False)) == [1] * 60
    assert not agent.lucario_routed
    assert agent(observation(opponent_cards=[100])) == [0]
    assert calls[-1] == "base"
