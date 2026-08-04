from types import SimpleNamespace

import numpy as np

import training.mcts_teacher as mcts
from training.mcts_teacher import Edge, neural_leaf_value, normalized_priors, puct_score


def test_puct_maximizes_for_root_and_minimizes_for_opponent():
    edge = Edge((0,), prior=0.2, visits=2, value_sum=1.0)
    root_score = puct_score(edge, parent_visits=8, root_to_move=True, exploration=1.0)
    opponent_score = puct_score(edge, parent_visits=8, root_to_move=False, exploration=1.0)
    assert root_score > opponent_score


def test_normalized_priors_are_probabilities():
    priors = normalized_priors([([0], -10.0), ([1], 0.0), ([2], -1.0)])
    assert np.isclose(sum(priors), 1.0)
    assert priors[1] > priors[2] > priors[0]


def test_neural_leaf_value_is_converted_to_root_perspective(monkeypatch):
    monkeypatch.setattr(mcts, "encode_observation", lambda obs, version: object())

    class Model:
        feature_version = 2

        @staticmethod
        def predict(_features):
            return np.zeros(1), np.zeros(1), 2.0

    obs = SimpleNamespace(current=SimpleNamespace(yourIndex=1))
    local = neural_leaf_value(Model(), obs, root_player=1)
    remote = neural_leaf_value(Model(), obs, root_player=0)
    assert local > 0
    assert np.isclose(local, -remote)
