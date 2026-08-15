"""Learned public-state gate between authentic A2 and a temporal continuation."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from cg.api import to_observation_class

from .agent import CompetitionAgent
from .features import DecisionFeatures, encode_observation
from .model import NumpyPolicyModel
from .safety import sanitize_selection


def _find(filename: str) -> Path:
    for candidate in (Path(filename), Path("/kaggle_simulations/agent") / filename):
        if candidate.exists():
            return candidate
    raise FileNotFoundError(filename)


def semantic_key(option) -> tuple:
    return (
        int(option.option_type),
        int(option.context),
        int(option.source_card),
        int(option.target_card),
        int(option.attack_id),
        int(option.area),
        int(option.in_play_area),
        tuple(
            round(float(value), 6)
            for index, value in enumerate(option.numeric)
            if index not in (9, 10, 11)
        ),
    )


def _softmax_stats(logits: np.ndarray) -> list[float]:
    values = np.asarray(logits, dtype=np.float64)
    centered = values - float(np.max(values))
    probabilities = np.exp(np.clip(centered, -60.0, 0.0))
    probabilities /= max(float(probabilities.sum()), 1e-12)
    ordered = np.sort(values)[::-1]
    top = float(ordered[0])
    second = float(ordered[1]) if len(ordered) > 1 else top
    third = float(ordered[2]) if len(ordered) > 2 else second
    entropy = -float(np.sum(probabilities * np.log(np.maximum(probabilities, 1e-12))))
    normalized_entropy = entropy / max(math.log(max(2, len(values))), 1e-12)
    return [
        float(probabilities.max()),
        top - second,
        top - third,
        float(values.std()),
        float(values.max() - values.min()),
        normalized_entropy,
    ]


def _shared_representation(model: NumpyPolicyModel, features: DecisionFeatures) -> np.ndarray:
    weights = model.weights
    token_rows = weights["state_embedding"][np.asarray(features.state_tokens, dtype=np.int64)]
    state = token_rows.sum(axis=0) / np.sqrt(max(1, len(token_rows)))
    global_hidden = np.tanh(
        np.asarray(features.global_features, dtype=np.float32) @ weights["global_w"]
        + weights["global_b"]
    )
    return np.concatenate([state, global_hidden]).astype(np.float32, copy=False)


def _choice_representation(model: NumpyPolicyModel, option) -> np.ndarray:
    weights = model.weights
    numeric = np.asarray(option.numeric, dtype=np.float32)
    return np.concatenate(
        [
            weights["card_embedding"][int(option.source_card)],
            weights["card_embedding"][int(option.target_card)],
            weights["attack_embedding"][int(option.attack_id)],
            weights["type_embedding"][int(option.option_type)],
            weights["context_embedding"][min(int(option.context), len(weights["context_embedding"]) - 1)],
            weights["area_embedding"][min(int(option.area), len(weights["area_embedding"]) - 1)],
            weights["area_embedding"][min(int(option.in_play_area), len(weights["area_embedding"]) - 1)],
            numeric,
        ]
    ).astype(np.float32, copy=False)


def public_gate_features(
    features: DecisionFeatures,
    a2: NumpyPolicyModel,
    continuation: NumpyPolicyModel,
    a2_logits: np.ndarray,
    continuation_logits: np.ndarray,
    a2_value: float,
    continuation_value: float,
    a2_index: int,
    continuation_index: int,
) -> np.ndarray:
    """The exact 858-value transform fit by the offline screen."""
    option_count = len(features.options)
    a2_order = np.argsort(-a2_logits, kind="stable")
    continuation_order = np.argsort(-continuation_logits, kind="stable")
    a2_rank_of_continuation = int(np.flatnonzero(a2_order == continuation_index)[0])
    continuation_rank_of_a2 = int(np.flatnonzero(continuation_order == a2_index)[0])
    confidence = np.asarray(
        [
            *_softmax_stats(a2_logits),
            *_softmax_stats(continuation_logits),
            float(a2_logits[a2_index] - a2_logits[continuation_index]),
            float(continuation_logits[continuation_index] - continuation_logits[a2_index]),
            a2_rank_of_continuation / max(1, option_count - 1),
            continuation_rank_of_a2 / max(1, option_count - 1),
            math.log1p(option_count),
            math.log1p(len(features.state_tokens)),
            float(a2_value),
            float(continuation_value),
            float(continuation_value - a2_value),
        ],
        dtype=np.float32,
    )
    global_features = np.asarray(features.global_features, dtype=np.float32)
    context = min(int(features.options[0].context), 63)
    context_one_hot = np.zeros(64, dtype=np.float32)
    context_one_hot[context] = 1.0
    a2_shared = _shared_representation(a2, features)
    continuation_shared = _shared_representation(continuation, features)
    a2_choice = _choice_representation(a2, features.options[a2_index])
    continuation_choice = _choice_representation(a2, features.options[continuation_index])
    return np.concatenate(
        [
            confidence,
            global_features,
            context_one_hot,
            a2_shared,
            continuation_shared - a2_shared,
            a2_choice,
            continuation_choice,
            continuation_choice - a2_choice,
        ]
    ).astype(np.float32, copy=False)


class LinearContextGate:
    def __init__(self, path: str | Path) -> None:
        with np.load(path, allow_pickle=False) as arrays:
            expected = {"coef", "bias", "mean", "std", "threshold", "schema_version"}
            if set(arrays.files) != expected:
                raise ValueError(f"context gate arrays changed: {sorted(arrays.files)}")
            self.coef = np.asarray(arrays["coef"], dtype=np.float32)
            self.bias = float(np.asarray(arrays["bias"]).item())
            self.mean = np.asarray(arrays["mean"], dtype=np.float32)
            self.std = np.asarray(arrays["std"], dtype=np.float32)
            self.threshold = float(np.asarray(arrays["threshold"]).item())
            schema = int(np.asarray(arrays["schema_version"]).item())
        if schema != 1 or self.coef.shape != (858,):
            raise ValueError("unsupported context gate schema or feature width")
        if self.mean.shape != self.coef.shape or self.std.shape != self.coef.shape:
            raise ValueError("context gate normalization shape mismatch")
        if not all(np.all(np.isfinite(value)) for value in (self.coef, self.mean, self.std)):
            raise ValueError("context gate contains non-finite arrays")
        if not np.isfinite(self.bias) or not 0.0 < self.threshold < 1.0 or np.any(self.std <= 0.0):
            raise ValueError("invalid context gate scalar or normalization")

    def probability(self, features: np.ndarray) -> float:
        if features.shape != self.coef.shape or not np.all(np.isfinite(features)):
            raise ValueError("invalid context gate feature vector")
        normalized = np.clip((features - self.mean) / self.std, -8.0, 8.0)
        logit = float(normalized @ self.coef + self.bias)
        return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, logit))))

    def choose_continuation(self, features: np.ndarray) -> bool:
        return self.probability(features) >= self.threshold


class TemporalContextGateAgent:
    """Route only raw single-action semantic disagreements; A2 is fail-closed."""

    def __init__(self) -> None:
        deck = _find("deck.csv")
        self.exact = CompetitionAgent(deck, _find("policy_a2_schema3.npz"))
        self.continuation = CompetitionAgent(deck, _find("policy_continuation.npz"))
        self.gate = LinearContextGate(_find("context_gate_weights.npz"))
        self.deck = list(self.exact.deck)
        self.errors = 0
        self.semantic_disagreements = 0
        self.continuation_routes = 0

    @staticmethod
    def _desired_count(obs, count_logits: np.ndarray) -> int:
        if obs.select.minCount == obs.select.maxCount:
            return int(obs.select.maxCount)
        minimum = int(obs.select.minCount)
        maximum = min(int(obs.select.maxCount), len(count_logits) - 1)
        return minimum + int(np.argmax(count_logits[minimum : maximum + 1]))

    def _reset(self, obs_dict: dict) -> list[int]:
        deck = self.exact(obs_dict)
        self.continuation(obs_dict)
        self.errors = 0
        self.semantic_disagreements = 0
        self.continuation_routes = 0
        return deck

    def _run(self, selected: CompetitionAgent, obs, obs_dict: dict) -> list[int]:
        before = int(getattr(selected, "errors", 0) or 0)
        try:
            action = selected(obs_dict)
        except Exception:
            self.errors += 1
            return self.exact(obs_dict) if selected is not self.exact else []
        after = int(getattr(selected, "errors", 0) or 0)
        if after != before:
            self.errors += max(1, after - before)
            if selected is not self.exact:
                return self.exact(obs_dict)
        return sanitize_selection(obs.select, action, len(action))

    def __call__(self, obs_dict: dict) -> list[int]:
        if not obs_dict or obs_dict.get("select") is None:
            return self._reset(obs_dict)
        try:
            obs = to_observation_class(obs_dict)
            features = encode_observation(obs, 3)
            a2_logits, a2_counts, a2_value = self.exact.policy.model.predict(features)
            continuation_logits, continuation_counts, continuation_value = (
                self.continuation.policy.model.predict(features)
            )
            if (
                not len(features.options)
                or self._desired_count(obs, a2_counts) != 1
                or self._desired_count(obs, continuation_counts) != 1
            ):
                return self._run(self.exact, obs, obs_dict)
            a2_index = int(np.argmax(a2_logits))
            continuation_index = int(np.argmax(continuation_logits))
            if semantic_key(features.options[a2_index]) == semantic_key(features.options[continuation_index]):
                return self._run(self.exact, obs, obs_dict)
            self.semantic_disagreements += 1
            vector = public_gate_features(
                features,
                self.exact.policy.model,
                self.continuation.policy.model,
                a2_logits,
                continuation_logits,
                a2_value,
                continuation_value,
                a2_index,
                continuation_index,
            )
            if self.gate.choose_continuation(vector):
                self.continuation_routes += 1
                return self._run(self.continuation, obs, obs_dict)
            return self._run(self.exact, obs, obs_dict)
        except Exception:
            self.errors += 1
            try:
                return self.exact(obs_dict)
            except Exception:
                return []
