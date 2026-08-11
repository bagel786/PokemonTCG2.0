from __future__ import annotations

import numpy as np

from training.train_public_value import _auc, binary_metrics


def test_auc_and_calibration_metrics_distinguish_ordered_predictions():
    labels = np.asarray([0.0, 0.0, 1.0, 1.0], dtype=np.float32)
    logits = np.asarray([-2.0, -1.0, 1.0, 2.0], dtype=np.float32)
    metrics = binary_metrics(labels, logits)
    assert metrics["auc"] == 1.0
    assert metrics["accuracy"] == 1.0
    assert metrics["brier"] < 0.1


def test_auc_handles_ties_and_single_class():
    assert _auc(
        np.asarray([0.0, 1.0], dtype=np.float32),
        np.asarray([0.5, 0.5], dtype=np.float32),
    ) == 0.5
    assert _auc(
        np.asarray([1.0, 1.0], dtype=np.float32),
        np.asarray([0.2, 0.8], dtype=np.float32),
    ) is None
