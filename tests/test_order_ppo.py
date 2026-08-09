import copy
import math

import pytest
import torch

from training.collect_order_ppo import weighted_schedule
from training.order_ppo import assign_cross_fitted_advantages, complete_action_logprob, validate_row
from training.train_bc import collate


def feature():
    return {
        "feature_version": 2,
        "global": [0.0] * 118,
        "tokens": [0],
        "options": [
            {"option_type": 1, "context": 1, "source_card": 0, "target_card": 0,
             "attack_id": 0, "area": 0, "in_play_area": 0, "numeric": [0.0] * 12},
            {"option_type": 2, "context": 1, "source_card": 0, "target_card": 0,
             "attack_id": 0, "area": 0, "in_play_area": 0, "numeric": [0.0] * 12},
        ],
        "entities": [], "events": [],
    }


def rollout(episode="e0", opponent="opp", reward=1.0):
    return {
        "episode_id": episode, "opponent_id": opponent,
        "features": feature(), "action": [0], "choice": [0],
        "chooser": "torch_schema2_policy", "old_logprob": -0.5,
        "behavior_temperature": 0.70, "policy_hash": "A" * 64,
        "physical_seat": 0, "actual_order": "first", "terminal_reward": reward,
        "forced_order_decision": False, "shield_modified": False,
        "postprocessed": False, "trainable": True,
    }


def test_strict_rollout_schema_rejects_critic_q_and_postprocessed_training():
    validate_row(rollout(), "first")
    for forbidden in ("critic_features", "action_q", "old_value", "director_action"):
        row = rollout()
        row[forbidden] = 0
        with pytest.raises(ValueError, match="forbidden"):
            validate_row(row, "first")
    modified = rollout()
    modified["postprocessed"] = True
    with pytest.raises(ValueError, match="excluded"):
        validate_row(modified, "first")


def test_complete_action_logprob_includes_count_and_without_replacement_choice():
    features = feature()
    features["global"][28] = 0.0
    features["global"][29] = 2 / 9
    batch = collate([{"features": features, "action": [1], "reward": 1.0}])
    logits = torch.tensor([0.0, 0.0])
    counts = torch.zeros((1, 61))
    observed = complete_action_logprob(logits, counts, batch, 0, [1], 1.0)
    assert torch.allclose(observed, torch.tensor(-math.log(3.0) - math.log(2.0)))


def test_cross_fitted_baseline_is_episode_not_decision_weighted():
    rows = []
    # SHA-based folds need coverage, so discover one episode per fold.
    found = {}
    import hashlib
    for index in range(1000):
        episode = f"episode-{index}"
        fold = int(hashlib.sha256(episode.encode()).hexdigest()[:8], 16) % 5
        found.setdefault(fold, episode)
        if len(found) == 5:
            break
    for fold, episode in found.items():
        reward = 1.0 if fold == 0 else -1.0
        rows.extend([rollout(episode, reward=reward) for _ in range(20 if fold == 0 else 1)])
    stats = assign_cross_fitted_advantages(rows)
    assert stats["episodes"] == 5
    fold_zero = next(row for row in rows if row["episode_id"] == found[0])
    assert fold_zero["baseline"] == -1.0


def test_weighted_schedule_has_exact_70_20_10_mix_and_is_deterministic():
    specs = [
        {"id": "owned", "weight": 0.7},
        {"id": "auth", "weight": 0.2},
        {"id": "meta", "weight": 0.1},
    ]
    first = weighted_schedule(copy.deepcopy(specs), 5000, 7)
    second = weighted_schedule(copy.deepcopy(specs), 5000, 7)
    assert [row["id"] for row in first] == [row["id"] for row in second]
    assert [sum(row["id"] == name for row in first) for name in ("owned", "auth", "meta")] == [3500, 1000, 500]
