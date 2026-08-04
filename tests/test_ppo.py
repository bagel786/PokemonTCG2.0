import unittest

import torch

from training.train_ppo import normalize_advantages_by_group, ppo_policy_loss


class PPOTests(unittest.TestCase):
    def test_advantages_are_normalized_within_matchup_and_seat_groups(self):
        advantages = torch.tensor([1.0, 3.0, 10.0, 14.0])
        groups = torch.tensor([0, 0, 1, 1])
        normalized = normalize_advantages_by_group(advantages, groups)
        torch.testing.assert_close(normalized, torch.tensor([-1.0, 1.0, -1.0, 1.0]), atol=1e-5, rtol=0)

    def test_unchanged_temperature_scaled_policy_has_unit_ratio(self):
        logits = torch.tensor([0.2, 1.1, -0.4, 0.7], dtype=torch.float32)
        temperatures = torch.tensor([0.65, 0.9], dtype=torch.float32)
        selected = torch.tensor([0.0, 1.0, 0.0, 1.0], dtype=torch.float32)
        old_logprob = torch.stack([
            torch.log_softmax(logits[0:2] / temperatures[0], dim=0)[1],
            torch.log_softmax(logits[2:4] / temperatures[1], dim=0)[1],
        ])
        batch = {
            "record_options": [(0, 2), (2, 4)],
            "selected": selected,
            "old_logprob": old_logprob,
            "old_value": torch.tensor([0.0, 0.0]),
            "values": torch.tensor([1.0, 0.0]),
            "behavior_temperature": temperatures,
        }
        batch["record_actions"] = [[1], [1]]
        batch["global"] = torch.zeros((2, 118), dtype=torch.float32)
        batch["global"][:, 28] = 1 / 9
        batch["global"][:, 29] = 1 / 9
        batch["advantages"] = torch.tensor([0.5, -0.5])
        count_logits = torch.zeros((2, 9), dtype=torch.float32)
        _, _, _, ratio, approximate_kl, clip_fraction = ppo_policy_loss(logits, count_logits, batch, 0.2)
        self.assertAlmostEqual(ratio, 1.0, places=6)
        self.assertAlmostEqual(approximate_kl, 0.0, places=6)
        self.assertAlmostEqual(clip_fraction, 0.0, places=6)

    def test_multiselection_logprob_matches_behavior(self):
        logits = torch.tensor([0.2, 1.1, -0.4], dtype=torch.float32, requires_grad=True)
        temperature = torch.tensor([0.7])
        first = torch.log_softmax(logits / temperature[0], dim=0)[1]
        second_logits = (logits / temperature[0]).clone()
        second_logits[1] = -torch.inf
        second = torch.log_softmax(second_logits, dim=0)[0]
        batch = {
            "record_options": [(0, 3)],
            "record_actions": [[1, 0]],
            "old_logprob": (first + second).detach().unsqueeze(0),
            "behavior_temperature": temperature,
            "advantages": torch.tensor([1.0]),
            "global": torch.zeros((1, 118)),
        }
        batch["global"][:, 28] = 2 / 9
        batch["global"][:, 29] = 2 / 9
        result = ppo_policy_loss(logits, torch.zeros((1, 9)), batch, 0.1)
        self.assertAlmostEqual(result[3], 1.0, places=6)
        self.assertAlmostEqual(result[4], 0.0, places=6)
        result[0].backward()
        self.assertIsNotNone(logits.grad)


if __name__ == "__main__":
    unittest.main()
