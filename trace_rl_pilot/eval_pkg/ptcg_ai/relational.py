"""Pure-NumPy inference for schema-4 residual ensembles."""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

import numpy as np

from cg.api import OptionType, SelectContext

from .features import encode_observation
from .model import NumpyPolicyModel
from .safety import sanitize_selection
from .tactical_shield import ShieldTelemetry, apply_tactical_shield

MODEL_DIM = 128
HEADS = 4
HEAD_DIM = MODEL_DIM // HEADS


def _relu(value):
    return np.maximum(value, 0.0)


def _softmax(value, axis=-1):
    shifted = value - np.max(value, axis=axis, keepdims=True)
    exponential = np.exp(shifted)
    return exponential / np.maximum(exponential.sum(axis=axis, keepdims=True), 1e-12)


def _layer_norm(value, weight, bias, epsilon=1e-5):
    mean = value.mean(axis=-1, keepdims=True)
    variance = ((value - mean) ** 2).mean(axis=-1, keepdims=True)
    return (value - mean) / np.sqrt(variance + epsilon) * weight + bias


class NumpyRelationalResidualModel:
    def __init__(self, path: str | Path):
        arrays = np.load(path, allow_pickle=False)
        self.weights = {name: arrays[name].astype(np.float32, copy=False) for name in arrays.files}
        if int(np.asarray(arrays["residual_schema_version"]).item()) != 4:
            raise ValueError("residual artifact is not schema 4")
        self.mode = "r0" if int(np.asarray(arrays["residual_mode"]).item()) == 0 else "r1"
        self.support_margin = float(np.asarray(arrays["support_margin"]).item())

    def _weight(self, name: str):
        return self.weights[f"r__{name.replace('.', '__')}"]

    def _linear(self, value, name: str):
        return value @ self._weight(f"{name}.weight").T + self._weight(f"{name}.bias")

    def _entities(self, features):
        entities = features.entities
        if not entities:
            return np.zeros((1, MODEL_DIM), dtype=np.float32), np.zeros(1, dtype=bool)
        card = np.asarray([entity.card_id for entity in entities], dtype=np.int64)
        zone = np.asarray([entity.zone for entity in entities], dtype=np.int64).clip(0, 16)
        owner = np.asarray([entity.owner for entity in entities], dtype=np.int64).clip(0, 2)
        slot = np.asarray([entity.slot for entity in entities], dtype=np.int64).clip(0, 127)
        kind = np.asarray([entity.entity_type for entity in entities], dtype=np.int64).clip(0, 7)
        numeric = np.asarray([entity.numeric for entity in entities], dtype=np.float32)
        value = np.concatenate([
            self._weight("entity_card.weight")[card],
            self._weight("entity_zone.weight")[zone],
            self._weight("entity_owner.weight")[owner],
            self._weight("entity_slot.weight")[slot],
            self._weight("entity_type.weight")[kind],
            _relu(self._linear(numeric, "entity_numeric")),
        ], axis=1)
        value = _relu(self._linear(value, "entity_input"))
        mask = np.ones(len(entities), dtype=bool)
        for index in range(2):
            prefix = f"set_blocks.{index}"
            qkv = self._linear(value, f"{prefix}.qkv").reshape(len(value), 3, HEADS, HEAD_DIM)
            q, k, v = qkv[:, 0].transpose(1, 0, 2), qkv[:, 1].transpose(1, 0, 2), qkv[:, 2].transpose(1, 0, 2)
            scores = np.matmul(q, k.transpose(0, 2, 1)) / math.sqrt(HEAD_DIM)
            context = np.matmul(_softmax(scores, axis=-1), v).transpose(1, 0, 2).reshape(len(value), MODEL_DIM)
            value = _layer_norm(
                value + self._linear(context, f"{prefix}.out"),
                self._weight(f"{prefix}.norm1.weight"),
                self._weight(f"{prefix}.norm1.bias"),
            )
            feedforward = self._linear(_relu(self._linear(value, f"{prefix}.ff1")), f"{prefix}.ff2")
            value = _layer_norm(
                value + feedforward,
                self._weight(f"{prefix}.norm2.weight"),
                self._weight(f"{prefix}.norm2.bias"),
            )
        return value.astype(np.float32, copy=False), mask

    def _options(self, features):
        options = features.options
        if not options:
            return np.empty((0, MODEL_DIM), dtype=np.float32)
        typ = np.asarray([option.option_type for option in options], dtype=np.int64).clip(0, 17)
        card = np.asarray([option.source_card for option in options], dtype=np.int64)
        target = np.asarray([option.target_card for option in options], dtype=np.int64)
        attack = np.asarray([option.attack_id for option in options], dtype=np.int64)
        context = np.asarray([option.context for option in options], dtype=np.int64).clip(0, 63)
        area = np.asarray([option.area for option in options], dtype=np.int64).clip(0, 15)
        in_area = np.asarray([option.in_play_area for option in options], dtype=np.int64).clip(0, 15)
        numeric = np.asarray([option.numeric for option in options], dtype=np.float32)
        value = np.concatenate([
            self._weight("option_type.weight")[typ],
            self._weight("option_card.weight")[card],
            self._weight("option_target.weight")[target],
            self._weight("option_attack.weight")[attack],
            self._weight("option_context.weight")[context],
            self._weight("option_area.weight")[area],
            self._weight("option_area.weight")[in_area],
            _relu(self._linear(numeric, "option_numeric")),
        ], axis=1)
        return _relu(self._linear(value, "option_input"))

    def predict(self, features):
        entities, mask = self._entities(features)
        options = self._options(features)
        if not len(options):
            return np.empty(0, np.float32), np.zeros(61, np.float32), 0.0
        q = self._linear(options, "cross_q").reshape(len(options), HEADS, HEAD_DIM)
        k = self._linear(entities, "cross_k").reshape(len(entities), HEADS, HEAD_DIM).transpose(1, 0, 2)
        v = self._linear(entities, "cross_v").reshape(len(entities), HEADS, HEAD_DIM).transpose(1, 0, 2)
        scores = np.einsum("ohd,hed->ohe", q, k) / math.sqrt(HEAD_DIM)
        scores[:, :, ~mask] = -1e9
        cross = np.einsum("ohe,hed->ohd", _softmax(scores, axis=-1), v).reshape(len(options), MODEL_DIM)
        cross = self._linear(cross, "cross_out")

        source = np.zeros((len(options), MODEL_DIM), dtype=np.float32)
        target = np.zeros_like(source)
        for index, option in enumerate(features.options):
            if 0 <= option.source_entity < len(entities):
                source[index] = entities[option.source_entity]
            if 0 <= option.target_entity < len(entities):
                target[index] = entities[option.target_entity]
        joint = _relu(self._linear(np.concatenate([options, source, target, cross], axis=1), "joint1"))
        residual = self._linear(joint, "score").reshape(-1)

        visible = entities[mask]
        mean = visible.mean(axis=0) if len(visible) else np.zeros(MODEL_DIM, np.float32)
        maximum = visible.max(axis=0) if len(visible) else np.zeros(MODEL_DIM, np.float32)
        pooled = _relu(self._linear(
            np.concatenate([mean, maximum, np.asarray(features.global_features, dtype=np.float32)])[None, :],
            "pool1",
        ))
        count = self._linear(pooled, "count").reshape(-1)
        value = float(self._linear(pooled, "value").reshape(-1)[0])
        return residual, count, value


def _desired_count(select, count_logits) -> int:
    if select.minCount == select.maxCount:
        return int(select.maxCount)
    minimum = int(select.minCount)
    maximum = min(int(select.maxCount), len(count_logits) - 1)
    return minimum + int(np.argmax(count_logits[minimum:maximum + 1]))


def _action(logits, count_logits, select) -> tuple[list[int], list[int], int]:
    ranked = np.argsort(-np.asarray(logits), kind="stable").astype(int).tolist()
    desired = _desired_count(select, count_logits)
    return sanitize_selection(select, ranked, desired), ranked, desired


def _logsumexp(value):
    maximum = float(np.max(value))
    return maximum + math.log(float(np.exp(value - maximum).sum()))


def _complete_score(logits, count_logits, action, select) -> float:
    available = list(range(len(logits)))
    score = 0.0
    for selected in action:
        local = np.asarray([logits[index] for index in available], dtype=np.float64)
        score += float(logits[selected]) - _logsumexp(local)
        if selected in available:
            available.remove(selected)
    valid_counts = np.asarray(count_logits[int(select.minCount):int(select.maxCount) + 1], dtype=np.float64)
    count_index = len(action) - int(select.minCount)
    if 0 <= count_index < len(valid_counts):
        score += float(valid_counts[count_index]) - _logsumexp(valid_counts)
    return score


class ResidualEnsemblePolicy:
    def __init__(self, manifest_path: str | Path, fallback):
        manifest_path = Path(manifest_path)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        root = manifest_path.parent
        self.base = NumpyPolicyModel(root / manifest["base_model"])
        self.heads = [NumpyRelationalResidualModel(root / path) for path in manifest["residual_heads"]]
        if len(self.heads) != 3:
            raise ValueError("a residual ensemble requires exactly three heads")
        if len({head.mode for head in self.heads}) != 1:
            raise ValueError("residual heads disagree on mode")
        self.mode = self.heads[0].mode
        self.support_margin = max(head.support_margin for head in self.heads)
        self.fallback = fallback
        self.shield_telemetry = ShieldTelemetry()
        self.history: list[dict] = []
        self.history_turn = -1

    def reset(self) -> None:
        self.history = []
        self.history_turn = -1

    def _remember(self, features, action) -> None:
        for index in action:
            if 0 <= index < len(features.options):
                option = features.options[index]
                self.history.append({
                    "option_type": option.option_type,
                    "source_card": option.source_card,
                    "source_serial": option.source_serial,
                    "target_card": option.target_card,
                    "target_serial": option.target_serial,
                })
        self.history = self.history[-16:]

    def choose(self, obs) -> list[int]:
        if obs.select.context == SelectContext.IS_FIRST:
            for index, option in enumerate(obs.select.option):
                if option.type == OptionType.YES:
                    return sanitize_selection(obs.select, [index], 1)
        turn = int(obs.current.turn or 0)
        if turn != self.history_turn:
            self.history_turn = turn
            self.history = []
        legacy = encode_observation(obs, 2)
        relational = encode_observation(obs, 4, action_history=self.history)
        base_logits, base_count, _ = self.base.predict(legacy)
        base_action, base_ranked, base_desired = _action(base_logits, base_count, obs.select)

        play_count = sum(option.type == OptionType.PLAY for option in obs.select.option)
        eligible = self.mode == "r1" or (
            obs.select.context == SelectContext.MAIN and play_count >= 2
        )
        chosen, ranked, desired = base_action, base_ranked, base_desired
        if eligible and len(base_logits):
            final_logits = []
            final_counts = []
            actions = []
            for head in self.heads:
                residual, count_residual, _ = head.predict(relational)
                logits = base_logits + residual
                counts = base_count + count_residual
                final_logits.append(logits)
                final_counts.append(counts)
                actions.append(_action(logits, counts, obs.select)[0])
            votes = Counter(tuple(action) for action in actions)
            candidate_tuple, support = votes.most_common(1)[0]
            mean_logits = np.mean(final_logits, axis=0)
            mean_counts = np.mean(final_counts, axis=0)
            candidate = list(candidate_tuple)
            margin = _complete_score(mean_logits, mean_counts, candidate, obs.select)
            margin -= _complete_score(mean_logits, mean_counts, base_action, obs.select)
            if support >= 2 and (candidate == base_action or margin >= self.support_margin):
                chosen = candidate
                desired = len(candidate)
                ranked = candidate + [
                    index for index in np.argsort(-mean_logits, kind="stable").astype(int).tolist()
                    if index not in candidate
                ]
        ranked, desired, intervention = apply_tactical_shield(obs, ranked, desired)
        self.shield_telemetry.record(intervention)
        result = sanitize_selection(obs.select, ranked, desired)
        self._remember(relational, result)
        return result
