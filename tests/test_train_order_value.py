from __future__ import annotations

import numpy as np

from training.train_order_value import (
    ValueRow,
    episode_turn_weights,
    episode_turn_weights_from,
    weighted_metrics,
)


def _row(episode: str, turn: int) -> ValueRow:
    return ValueRow(episode, 0, 1.0, (0.0,), (0,), turn, turn)


def test_episode_turn_weights_equalize_episodes_and_turns():
    rows = [_row("a", 0), _row("a", 0), _row("a", 1), _row("b", 0)]
    weights = episode_turn_weights(rows)
    assert np.isclose(weights[:3].sum(), weights[3:].sum())
    assert np.isclose(weights[:2].sum(), weights[2])
    units = [(row.episode_id, row.seat) for row in rows]
    assert np.allclose(weights, episode_turn_weights_from(units, [row.turn for row in rows]))


def test_weighted_metrics_respect_episode_weights():
    labels = np.asarray([0.0, 1.0], dtype=np.float32)
    logits = np.asarray([-2.0, 2.0], dtype=np.float32)
    metrics = weighted_metrics(labels, logits, np.asarray([1.0, 3.0], dtype=np.float32))
    assert metrics["auc"] == 1.0
    assert metrics["accuracy"] == 1.0
    assert np.isclose(metrics["positive_rate"], 0.75)
