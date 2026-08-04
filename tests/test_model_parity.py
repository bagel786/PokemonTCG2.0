import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))

try:
    import numpy as np
    import torch
except ImportError:  # pragma: no cover - base runtime intentionally has no torch
    np = torch = None

from ptcg_ai.features import DecisionFeatures, OptionFeatures, V2_GLOBAL_SIZE


@unittest.skipIf(torch is None, "training dependencies are not installed")
class ModelParityTests(unittest.TestCase):
    def test_exported_numpy_logits_match_torch(self):
        from ptcg_ai.model import NumpyPolicyModel
        from training.train_bc import PolicyNet, collate, export_npz

        torch.manual_seed(7)
        model = PolicyNet().eval()
        features = DecisionFeatures(
            global_features=[0.05] * V2_GLOBAL_SIZE,
            state_tokens=[7, 1300 + 648, 6 * 1300 + 381],
            options=[
                OptionFeatures(13, 0, 0, 0, 937, 0, 0, [0.0] * 12),
                OptionFeatures(14, 0, 0, 0, 0, 0, 0, [0.0] * 12),
            ],
            feature_version=2,
        )
        row = {
            "features": features.to_json(),
            "action": [0],
            "reward": 1,
        }
        batch = collate([row])
        with torch.no_grad():
            torch_logits, torch_count, torch_value = model(batch)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "weights.npz"
            export_npz(model, path)
            numpy_logits, numpy_count, numpy_value = NumpyPolicyModel(path).predict(features)
        # Export uses float16, so milliscale agreement is the appropriate contract.
        np.testing.assert_allclose(numpy_logits, torch_logits.numpy(), atol=2e-3, rtol=2e-3)
        np.testing.assert_allclose(numpy_count, torch_count.numpy()[0], atol=2e-3, rtol=2e-3)
        self.assertAlmostEqual(numpy_value, float(torch_value.numpy()[0]), delta=2e-3)

    def test_v2_count_head_supports_large_selections(self):
        from training.train_bc import PolicyNet, collate, masked_count_loss, policy_loss

        options = [OptionFeatures(3, 0, index, 0, 0, 0, 0, [0.0] * 12) for index in range(11)]
        features = DecisionFeatures([0.0] * V2_GLOBAL_SIZE, [1], options, 2)
        features.global_features[28] = 11 / 9
        features.global_features[29] = 11 / 9
        batch = collate([{"features": features.to_json(), "action": list(range(11)), "reward": 1}])
        logits, count_logits, _ = PolicyNet(2)(batch)
        self.assertEqual(count_logits.shape[1], 61)
        self.assertTrue(torch.isfinite(masked_count_loss(count_logits, batch)))
        policy_loss(logits, batch)[0].backward()


if __name__ == "__main__":
    unittest.main()
