import copy

import pytest

from training.outcome_rl import PRIVATE_CRITIC_SIZE, validate_rollout
from training.private_critic import encode_private_visualize
from training.psro_outcome import admission, solve_maximin


def rollout():
    return {
        "features": {"feature_version": 5, "options": [{"option_type": 14}]},
        "critic_features": [0.0] * PRIVATE_CRITIC_SIZE,
        "action": [0], "old_logprob": 0.0, "terminal_reward": 1.0,
    }


def test_actor_critic_features_are_physically_separate():
    row = rollout()
    validate_rollout(row)
    leaked = copy.deepcopy(row)
    leaked["features"]["critic_features"] = leaked["critic_features"]
    with pytest.raises(ValueError, match="leaked"):
        validate_rollout(leaked)


def test_private_visualizer_encoding_is_fixed_and_deterministic():
    payload = [{"current": {"players": [{"hand": [{"id": 648}]}, {"deck": [{"id": 7}]}]}}]
    first = encode_private_visualize(payload)
    assert len(first) == PRIVATE_CRITIC_SIZE
    assert first == encode_private_visualize(payload)


def test_psro_solver_favors_robust_policy():
    mixture = solve_maximin([[0.6, 0.6], [0.9, 0.1]], iterations=4000)
    assert mixture[0] > mixture[1]


def test_psro_admission_requires_zero_errors_and_both_orders():
    cells = []
    for lineage in ("a", "b"):
        for order in ("first", "second"):
            cells.append({
                "lineage": lineage, "actual_order": order,
                "candidate_wins": 2700, "candidate_games": 5000,
                "baseline_wins": 2400, "baseline_games": 5000,
                "policy_errors": 0, "candidate_sha256": "A", "opponent_sha256": "B",
            })
    assert admission(cells)["passed"]
    cells[0]["policy_errors"] = 1
    assert not admission(cells)["passed"]
