from collections import Counter
from types import SimpleNamespace

import numpy as np

import training.search_teacher as search_teacher
from training.collect_selfplay import exact_binary_schedule, exact_weighted_schedule
from training.search_teacher import SearchConfig, candidate_actions, determinize_known_matchup


def card(card_id, player=0, serial=None):
    return SimpleNamespace(id=card_id, playerIndex=player, serial=card_id if serial is None else serial)


def pokemon(card_id, player=0):
    return SimpleNamespace(
        id=card_id,
        playerIndex=player,
        serial=card_id,
        energyCards=[],
        tools=[],
        preEvolution=[],
    )


def test_exact_weighted_and_seat_schedules_have_exact_quotas():
    entries = [
        {"name": "lucario", "weight": 25.0},
        {"name": "bellibolt", "weight": 15.0},
        {"name": "anchors", "weight": 60.0},
    ]
    first = exact_weighted_schedule(entries, 100, seed=7)
    second = exact_weighted_schedule(entries, 100, seed=7)
    assert [row["name"] for row in first] == [row["name"] for row in second]
    assert Counter(row["name"] for row in first) == {
        "lucario": 25,
        "bellibolt": 15,
        "anchors": 60,
    }
    seats = exact_binary_schedule(101, 0.5, seed=9)
    assert len(seats) == 101
    assert sum(seats) == 50


def test_known_matchup_determinization_conserves_both_decks():
    own_deck = [1, 2, 3, 4]
    opponent_deck = [5, 6, 7, 8, 9]
    own = SimpleNamespace(
        active=[pokemon(2, 0)], bench=[], discard=[], prize=[None],
        hand=[card(1, 0)], handCount=1, deckCount=1,
    )
    opponent = SimpleNamespace(
        active=[pokemon(5, 1)], bench=[], discard=[card(6, 1)], prize=[None],
        hand=None, handCount=1, deckCount=1,
    )
    state = SimpleNamespace(yourIndex=0, players=[own, opponent], stadium=[])
    obs = SimpleNamespace(current=state, select=SimpleNamespace(deck=None))
    result = determinize_known_matchup(obs, own_deck, opponent_deck, __import__("random").Random(3))
    assert Counter(result["your_deck"] + result["your_prize"] + [1, 2]) == Counter(own_deck)
    assert Counter(
        result["opponent_deck"] + result["opponent_prize"] + result["opponent_hand"] + [5, 6]
    ) == Counter(opponent_deck)


def test_candidate_actions_are_prior_ranked_and_legally_bounded(monkeypatch):
    monkeypatch.setattr(search_teacher, "encode_observation", lambda obs, version: object())

    class Model:
        feature_version = 2

        @staticmethod
        def predict(_features):
            return np.asarray([0.0, 2.0, 1.0]), np.zeros(61), 0.0

    select = SimpleNamespace(minCount=1, maxCount=1, option=[object(), object(), object()])
    obs = SimpleNamespace(select=select)
    candidates = candidate_actions(Model(), obs, SearchConfig(max_candidates=3, candidate_width=3))
    assert candidates[0][0] == [1]
    assert {tuple(action) for action, _ in candidates} == {(0,), (1,), (2,)}


def test_exhaustive_candidates_ignore_weak_policy_width(monkeypatch):
    monkeypatch.setattr(search_teacher, "encode_observation", lambda obs, version: object())

    class Model:
        feature_version = 2

        @staticmethod
        def predict(_features):
            return np.asarray([4.0, 3.0, 2.0, -20.0]), np.zeros(61), 0.0

    select = SimpleNamespace(minCount=1, maxCount=1, option=[object()] * 4)
    obs = SimpleNamespace(select=select)
    prior = candidate_actions(
        Model(), obs, SearchConfig(max_candidates=8, candidate_width=2, candidate_mode="prior")
    )
    exhaustive = candidate_actions(
        Model(), obs, SearchConfig(max_candidates=8, candidate_width=2, candidate_mode="exhaustive")
    )
    assert {tuple(action) for action, _ in prior} == {(0,), (1,)}
    assert {tuple(action) for action, _ in exhaustive} == {(0,), (1,), (2,), (3,)}


def test_exhaustive_candidates_cover_all_unordered_multiselections(monkeypatch):
    monkeypatch.setattr(search_teacher, "encode_observation", lambda obs, version: object())

    class Model:
        feature_version = 2

        @staticmethod
        def predict(_features):
            return np.asarray([0.0, 1.0, 2.0, 3.0]), np.zeros(61), 0.0

    select = SimpleNamespace(minCount=2, maxCount=2, option=[object()] * 4)
    obs = SimpleNamespace(select=select)
    candidates = candidate_actions(
        Model(), obs, SearchConfig(max_candidates=512, candidate_width=1, candidate_mode="exhaustive")
    )
    assert len(candidates) == 6
    assert {frozenset(action) for action, _ in candidates} == {
        frozenset(pair) for pair in ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))
    }
