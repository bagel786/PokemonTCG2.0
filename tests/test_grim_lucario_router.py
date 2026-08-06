from types import SimpleNamespace

import ptcg_ai.agent as agent_module
from ptcg_ai.agent import CompetitionAgent, lucario_publicly_detected


def card(card_id):
    return SimpleNamespace(id=card_id, energyCards=[], tools=[], preEvolution=[])


class Obs(dict):
    """Dict-shaped observation (as Kaggle passes) that also supports attribute
    access, so it works both through ``obs_dict.get("select")`` in ``__call__``
    and through the identity-monkeypatched ``to_observation_class`` afterwards."""

    def __init__(self, current, logs, select):
        super().__init__(select=select, logs=logs)
        self.current = current
        self.logs = logs
        self.select = select


def observation(
    opponent_cards=(),
    own_cards=(),
    opponent_bench=(),
    opponent_discard=(),
    opponent_hand=(),
    opponent_deck=(),
    select=True,
):
    opponent = SimpleNamespace(
        active=[card(value) for value in opponent_cards],
        bench=[card(value) for value in opponent_bench],
        discard=[card(value) for value in opponent_discard],
        # Private zones: present on the object but must never be inspected.
        hand=[card(value) for value in opponent_hand],
        deck=[card(value) for value in opponent_deck],
    )
    own = SimpleNamespace(
        active=[card(value) for value in own_cards], bench=[], discard=[]
    )
    return Obs(
        current=SimpleNamespace(players=[own, opponent], yourIndex=0),
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
    agent.mirror_specialist = None
    agent.fallback = Policy("fallback")
    agent.lucario_routed = False
    agent.mirror_routed = False
    agent.errors = 0

    assert agent(observation(opponent_cards=[100])) == [0]
    assert agent(observation(opponent_cards=[677])) == [0]
    assert agent(observation(opponent_cards=[100])) == [0]
    assert calls == ["base", "specialist", "specialist"]

    assert agent(observation(select=False)) == [1] * 60
    assert not agent.lucario_routed
    assert agent(observation(opponent_cards=[100])) == [0]
    assert calls[-1] == "base"
