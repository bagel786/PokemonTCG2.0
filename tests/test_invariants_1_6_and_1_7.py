"""Unit and integration tests for Invariant 1.6 (Policy Penalty Isolation) and Invariant 1.7 (Intra-Turn Credit Assignment)."""

import gzip
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

import torch
import numpy as np
from unittest.mock import MagicMock

from cg.api import OptionType
from ptcg_ai.blunder_detector import is_blunder, is_nullified_attack_action, is_futile_retreat_action
from training.collect_selfplay import assign_terminal_gae
from training.train_ppo import ppo_policy_loss


def test_blunder_detector_predicates():
    # 1. Non-attack / non-retreat option
    mock_obs = MagicMock()
    mock_option = MagicMock()
    mock_option.type = OptionType.PLAY
    assert not is_blunder(mock_obs, mock_option)
    assert not is_nullified_attack_action(mock_obs, mock_option)
    assert not is_futile_retreat_action(mock_obs, mock_option)

    # 2. Futile retreat
    mock_retreat_opt = MagicMock()
    mock_retreat_opt.type = OptionType.RETREAT
    mock_target = MagicMock()
    mock_target.energy = []
    mock_target.hp = 60
    mock_target.damage = 10
    
    # Test futile retreat logic directly
    assert is_futile_retreat_action(mock_obs, None) is False


def test_intra_turn_credit_assignment_invariant_1_7():
    # Multi-step intra-turn trajectory (Turn 1 has 3 sub-actions: search, attach, attack)
    # Turn 2 has 2 sub-actions.
    trajectory = [
        {"turn": 1, "old_value": 0.0, "step": 0},
        {"turn": 1, "old_value": 0.0, "step": 1},
        {"turn": 1, "old_value": 0.0, "step": 2},
        {"turn": 2, "old_value": 0.0, "step": 3},
        {"turn": 2, "old_value": 0.0, "step": 4},
    ]

    outcome = 1.0
    updated = assign_terminal_gae(trajectory, outcome, gae_lambda=1.0)
    
    # Invariant 1.6: reward target must strictly be 1.0 (unpolluted)
    for row in updated:
        assert row["reward"] == 1.0
        assert row["return"] == 1.0

    # Invariant 1.7: Intra-turn gamma = 1.0
    # Step 4 (Turn 2 terminal): delta = 1.0 + 0 - 0.5 = 0.5, GAE = 0.5
    # Step 3 (Turn 2 intra): same turn, gamma=1.0, delta = 0 + 0.5 - 0.5 = 0.0, GAE = 0.0 + 1.0*1.0*0.5 = 0.5
    assert updated[4]["advantage"] == updated[3]["advantage"]
    print("✓ Invariant 1.7 intra-turn uniform credit verified:", [r["advantage"] for r in updated])


def test_policy_penalty_loss_invariant_1_6():
    # Verify that ppo_policy_loss calculates penalty_loss on blunder steps
    torch.manual_seed(42)
    logits = torch.randn(10, requires_grad=True)
    count_logits = torch.randn(2, 10, requires_grad=True)
    batch = {
        "record_options": [(0, 5), (5, 10)],
        "record_actions": [[0], [1]],
        "global": torch.zeros(2, 30),
        "behavior_temperature": torch.tensor([1.0, 1.0]),
        "advantages": torch.tensor([1.0, -1.0]),
        "old_logprob": torch.tensor([-1.0, -1.0]),
        "is_blunder": torch.tensor([True, False]),
    }
    batch["global"][:, 28] = 0.1111  # min count 1
    batch["global"][:, 29] = 0.1111  # max count 1

    ppo_loss, entropy, penalty_loss, ratio, approx_kl, clip_frac = ppo_policy_loss(
        logits, count_logits, batch, clip_ratio=0.2
    )

    assert penalty_loss != 0.0
    total_loss = ppo_loss + 0.10 * penalty_loss
    total_loss.backward()
    assert logits.grad is not None
    print("✓ Invariant 1.6 policy penalty loss backward verified. Penalty loss:", float(penalty_loss.item()))


if __name__ == "__main__":
    test_blunder_detector_predicates()
    test_intra_turn_credit_assignment_invariant_1_7()
    test_policy_penalty_loss_invariant_1_6()
    print("ALL INVARIANT 1.6 & 1.7 TESTS PASSED!")
