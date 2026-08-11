from __future__ import annotations

from types import SimpleNamespace

import ptcg_ai.damage_value_search as damage_search
from ptcg_ai.damage_value_search import (
    IndependentRootOnePlySearch,
    damage_search_eligible,
    opponent_grim_line_visible,
)


def _obs(*, context=13, turn=4, opponent_id=648, minimum=1, maximum=1, options=2):
    pokemon = SimpleNamespace(id=opponent_id, preEvolution=[])
    player = SimpleNamespace(active=[pokemon], bench=[], discard=[])
    me = SimpleNamespace(active=[], bench=[], discard=[])
    current = SimpleNamespace(turn=turn, yourIndex=0, players=[me, player])
    select = SimpleNamespace(
        context=context,
        minCount=minimum,
        maxCount=maximum,
        option=[SimpleNamespace() for _ in range(options)],
    )
    return SimpleNamespace(current=current, select=select, logs=[])


def test_damage_search_requires_public_mirror_evidence_and_safe_context():
    assert opponent_grim_line_visible(_obs())
    assert damage_search_eligible(_obs(), min_turn=3)
    assert not damage_search_eligible(_obs(opponent_id=741), min_turn=3)
    assert not damage_search_eligible(_obs(context=0), min_turn=3)
    assert not damage_search_eligible(_obs(turn=2), min_turn=3)
    assert not damage_search_eligible(_obs(maximum=2), min_turn=3)


def test_independent_roots_are_order_invariant_and_tie_break_to_policy_priority(monkeypatch):
    calls = {"determinize": 0, "begin": 0, "end": 0, "release": 0}

    class Model:
        feature_version = 2

        @staticmethod
        def predict(features):
            return [], [], features.score

    def determinize(*_args):
        calls["determinize"] += 1
        return {"frozen": True}

    def begin(_obs, **kwargs):
        assert kwargs == {"frozen": True}
        calls["begin"] += 1
        return SimpleNamespace(searchId=100 + calls["begin"])

    def step(_root_id, action):
        scores = {0: 0.5, 1: 0.8, 2: 0.8}
        current = SimpleNamespace(result=-1, yourIndex=0)
        observation = SimpleNamespace(
            current=current,
            select=SimpleNamespace(),
            score=scores[action[0]],
        )
        return SimpleNamespace(searchId=200 + calls["begin"], observation=observation)

    monkeypatch.setattr(damage_search, "determinize_state", determinize)
    monkeypatch.setattr(damage_search, "search_begin", begin)
    monkeypatch.setattr(damage_search, "search_step", step)
    monkeypatch.setattr(damage_search, "search_release", lambda _search_id: calls.__setitem__("release", calls["release"] + 1))
    monkeypatch.setattr(damage_search, "search_end", lambda: calls.__setitem__("end", calls["end"] + 1))
    monkeypatch.setattr(damage_search, "encode_observation", lambda child, _version: child)

    search = IndependentRootOnePlySearch(
        Model(), [646] * 60, registry=SimpleNamespace(), timeout_ms=1000
    )
    obs = SimpleNamespace(current=SimpleNamespace(yourIndex=0))
    candidates = [[0], [1], [2]]
    priorities = {(0,): 0, (1,): 1, (2,): 2}
    normal = search.evaluate_candidates(obs, candidates, [646] * 60, priorities=priorities)
    reverse = search.evaluate_candidates(
        obs, list(reversed(candidates)), [646] * 60, priorities=priorities
    )

    assert normal == reverse == [1]
    assert calls == {"determinize": 2, "begin": 6, "end": 6, "release": 12}

    def opponent_step(_root_id, _action):
        current = SimpleNamespace(result=-1, yourIndex=1)
        observation = SimpleNamespace(current=current, select=SimpleNamespace(), score=9.0)
        return SimpleNamespace(searchId=999, observation=observation)

    monkeypatch.setattr(damage_search, "search_step", opponent_step)
    search.telemetry.clear()
    assert search.evaluate_candidates(obs, candidates, [646] * 60, priorities=priorities) is None
    assert search.telemetry["opponent_to_act_rejections"] == 1
    assert search.telemetry["completed_candidates"] == 0
