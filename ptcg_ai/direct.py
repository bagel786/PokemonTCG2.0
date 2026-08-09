"""Pure-NumPy inference for the schema-5 direct temporal policy."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np

from cg.api import OptionType, SelectContext

from .features import EVENT_HISTORY_LENGTH, encode_observation, public_state_summary
from .safety import sanitize_selection
from .tactical_shield import ShieldTelemetry, apply_tactical_shield


def _relu(value):
    return np.maximum(value, 0.0)


def _sigmoid(value):
    return 1.0 / (1.0 + np.exp(-np.clip(value, -30.0, 30.0)))


def _logsumexp(value):
    value = np.asarray(value, np.float64)
    if not len(value):
        return 0.0
    maximum = float(np.max(value))
    return maximum + float(np.log(np.exp(value - maximum).sum()))


def _complete_score(logits, counts, action, minimum, maximum):
    available = list(range(len(logits)))
    score = 0.0
    for selected in action:
        if selected not in available:
            return float("-inf")
        score += float(logits[selected]) - _logsumexp(logits[available])
        available.remove(selected)
    maximum = min(int(maximum), len(counts) - 1)
    minimum = min(int(minimum), maximum)
    valid = counts[minimum:maximum + 1]
    count_index = len(action) - minimum
    if not 0 <= count_index < len(valid):
        return float("-inf")
    return score + float(valid[count_index]) - _logsumexp(valid)


def _family(context: int) -> int:
    if context == 0:
        return 0
    if context in {7, 8, 9, 10, 11, 12, 24, 34, 38}:
        return 1
    if context in {18, 19, 20, 21, 22, 23, 26, 28, 30, 31, 32, 33, 37}:
        return 2
    if context in {3, 4, 5, 6, 25, 35, 36}:
        return 3
    if context in {13, 14, 15, 16, 17, 39, 40}:
        return 4
    return 5


class NumpyDirectPolicyModel:
    def __init__(self, path: str | Path | None = None, *, arrays=None, prefix="d__"):
        arrays = np.load(path, allow_pickle=False) if arrays is None else arrays
        if int(np.asarray(arrays["model_schema_version"]).item()) != 5:
            raise ValueError("direct policy artifact is not schema 5")
        self.weights = {name: arrays[name].astype(np.float32, copy=False) for name in arrays.files}
        self.prefix = prefix
        self.feature_version = 5

    def _weight(self, name: str):
        return self.weights[f"{self.prefix}{name.replace('.', '__')}"]

    def _linear(self, value, name: str):
        return value @ self._weight(f"{name}.weight").T + self._weight(f"{name}.bias")

    def _entities(self, features):
        if not features.entities:
            values = np.zeros((1, 96), dtype=np.float32)
            return values, np.zeros(192, dtype=np.float32)
        rows = features.entities
        value = np.concatenate([
            self._weight("entity_card.weight")[np.asarray([row.card_id for row in rows])],
            self._weight("entity_zone.weight")[np.asarray([row.zone for row in rows]).clip(0, 16)],
            self._weight("entity_owner.weight")[np.asarray([row.owner for row in rows]).clip(0, 2)],
            self._weight("entity_slot.weight")[np.asarray([row.slot for row in rows]).clip(0, 127)],
            self._weight("entity_type.weight")[np.asarray([row.entity_type for row in rows]).clip(0, 7)],
            _relu(self._linear(np.asarray([row.numeric for row in rows], np.float32), "entity_numeric")),
        ], axis=1)
        value = _relu(self._linear(value, "entity_input"))
        value = _relu(self._linear(value, "entity_hidden"))
        return value, np.concatenate([value.mean(axis=0), value.max(axis=0)])

    def _events(self, features):
        hidden = np.zeros(96, dtype=np.float32)
        for event in features.events[-EVENT_HISTORY_LENGTH:]:
            value = np.concatenate([
                self._weight("event_context.weight")[min(63, event.context)],
                self._weight("event_type.weight")[min(17, event.option_type)],
                self._weight("event_source.weight")[event.source_card],
                self._weight("event_target.weight")[event.target_card],
                self._weight("event_attack.weight")[event.attack_id],
                self._weight("event_serial.weight")[min(127, event.source_serial)],
                self._weight("event_serial.weight")[min(127, event.target_serial)],
                self._weight("event_position.weight")[min(EVENT_HISTORY_LENGTH - 1, event.position)],
                _relu(self._linear(np.asarray(event.numeric, np.float32), "event_numeric")),
            ])
            x = _relu(self._linear(value, "event_input"))
            weight_ih = self._weight("event_gru.weight_ih_l0")
            weight_hh = self._weight("event_gru.weight_hh_l0")
            bias_ih = self._weight("event_gru.bias_ih_l0")
            bias_hh = self._weight("event_gru.bias_hh_l0")
            gi = x @ weight_ih.T + bias_ih
            gh = hidden @ weight_hh.T + bias_hh
            ir, iz, inn = np.split(gi, 3)
            hr, hz, hn = np.split(gh, 3)
            reset = _sigmoid(ir + hr)
            update = _sigmoid(iz + hz)
            new = np.tanh(inn + reset * hn)
            hidden = (1.0 - update) * new + update * hidden
        return hidden

    def predict(self, features):
        entities, board = self._entities(features)
        history = self._events(features)
        global_vector = _relu(self._linear(np.asarray(features.global_features, np.float32), "global_input"))
        order = int(float(features.global_features[3]) >= 0.5)
        order_vector = self._weight("order_embedding.weight")[order]
        option_rows = []
        for option in features.options:
            option_rows.append(np.concatenate([
                self._weight("option_type.weight")[min(17, option.option_type)],
                self._weight("option_context.weight")[min(63, option.context)],
                self._weight("option_source.weight")[option.source_card],
                self._weight("option_target.weight")[option.target_card],
                self._weight("option_attack.weight")[option.attack_id],
                self._weight("option_area.weight")[min(15, option.area)],
                self._weight("option_area.weight")[min(15, option.in_play_area)],
                _relu(self._linear(np.asarray(option.numeric, np.float32), "option_numeric")),
            ]))
        if not option_rows:
            return np.empty(0, np.float32), np.zeros(61, np.float32)
        options = _relu(self._linear(np.stack(option_rows), "option_input"))
        source = np.zeros((len(options), 96), np.float32)
        target = np.zeros_like(source)
        for index, option in enumerate(features.options):
            if 0 <= option.source_entity < len(entities):
                source[index] = entities[option.source_entity]
            if 0 <= option.target_entity < len(entities):
                target[index] = entities[option.target_entity]
        shared = np.concatenate([board, history, global_vector, order_vector])
        joint = np.concatenate([
            options, source, target,
            np.repeat(board[None, :], len(options), axis=0),
            np.repeat(history[None, :], len(options), axis=0),
            np.repeat(global_vector[None, :], len(options), axis=0),
            np.repeat(order_vector[None, :], len(options), axis=0),
        ], axis=1)
        hidden = _relu(self._linear(joint, "joint1"))
        hidden = _relu(self._linear(hidden, "joint2"))
        scores = self._linear(hidden, "score_heads")
        context = int(features.options[0].context)
        logits = scores[:, _family(context)]
        count_input = np.concatenate([
            shared,
            self._weight("count_context.weight")[min(63, context)],
        ])
        count = self._linear(_relu(self._linear(count_input, "count1")), "count")
        return logits.astype(np.float32, copy=False), count.reshape(-1).astype(np.float32, copy=False)


class NumpyRelationalDirectPolicyModel:
    """NumPy parity runtime for direct model version 2 (D1)."""

    def __init__(self, path: str | Path):
        arrays = np.load(path, allow_pickle=False)
        if int(np.asarray(arrays["model_schema_version"]).item()) != 5:
            raise ValueError("relational direct policy artifact is not schema 5")
        if int(np.asarray(arrays["direct_model_version"]).item()) != 2:
            raise ValueError("relational direct policy artifact is not version 2")
        self.weights = {name: arrays[name].astype(np.float32, copy=False) for name in arrays.files}
        self.base = NumpyDirectPolicyModel(arrays=arrays, prefix="d2__base__")
        self.feature_version = 5

    def _weight(self, name: str):
        return self.weights[f"d2__{name.replace('.', '__')}"]

    @staticmethod
    def _softmax(value, axis=-1):
        shifted = value - np.max(value, axis=axis, keepdims=True)
        exponential = np.exp(shifted)
        return exponential / np.maximum(exponential.sum(axis=axis, keepdims=True), 1e-12)

    def _linear(self, value, name: str):
        return value @ self._weight(f"{name}.weight").T + self._weight(f"{name}.bias")

    def _norm(self, value, name: str):
        mean = value.mean(axis=-1, keepdims=True)
        variance = ((value - mean) ** 2).mean(axis=-1, keepdims=True)
        normalized = (value - mean) / np.sqrt(variance + 1e-5)
        return normalized * self._weight(f"{name}.weight") + self._weight(f"{name}.bias")

    def _attention(self, query, key, value, name: str):
        in_weight = self._weight(f"{name}.in_proj_weight")
        in_bias = self._weight(f"{name}.in_proj_bias")
        q_weight, k_weight, v_weight = np.split(in_weight, 3)
        q_bias, k_bias, v_bias = np.split(in_bias, 3)
        q = query @ q_weight.T + q_bias
        k = key @ k_weight.T + k_bias
        v = value @ v_weight.T + v_bias
        heads, width = 4, 24
        q = q.reshape(len(q), heads, width).transpose(1, 0, 2)
        k = k.reshape(len(k), heads, width).transpose(1, 0, 2)
        v = v.reshape(len(v), heads, width).transpose(1, 0, 2)
        weights = self._softmax((q @ k.transpose(0, 2, 1)) / np.sqrt(width), axis=-1)
        attended = (weights @ v).transpose(1, 0, 2).reshape(len(query), heads * width)
        return self._linear(attended, f"{name}.out_proj")

    def _options(self, features):
        base = self.base
        return _relu(base._linear(np.stack([
            np.concatenate([
                base._weight("option_type.weight")[min(17, option.option_type)],
                base._weight("option_context.weight")[min(63, option.context)],
                base._weight("option_source.weight")[option.source_card],
                base._weight("option_target.weight")[option.target_card],
                base._weight("option_attack.weight")[option.attack_id],
                base._weight("option_area.weight")[min(15, option.area)],
                base._weight("option_area.weight")[min(15, option.in_play_area)],
                _relu(base._linear(np.asarray(option.numeric, np.float32), "option_numeric")),
            ]) for option in features.options
        ]), "option_input"))

    def predict(self, features):
        base_logits, base_counts = self.base.predict(features)
        if not features.options:
            return base_logits, base_counts
        entities, _ = self.base._entities(features)
        for index in range(2):
            prefix = f"entity_attention.{index}"
            entities = self._norm(
                entities + self._attention(entities, entities, entities, f"{prefix}.attention"),
                f"{prefix}.norm1",
            )
            entities = self._norm(
                entities + self._linear(_relu(self._linear(entities, f"{prefix}.ff1")), f"{prefix}.ff2"),
                f"{prefix}.norm2",
            )
        board = np.concatenate([entities.mean(axis=0), entities.max(axis=0)])
        history = self.base._events(features)
        global_vector = _relu(self.base._linear(np.asarray(features.global_features, np.float32), "global_input"))
        order = int(float(features.global_features[3]) >= 0.5)
        order_vector = self.base._weight("order_embedding.weight")[order]
        options = self._options(features)
        attended = self._norm(
            options + self._attention(options, entities, entities, "option_cross_attention"),
            "cross_norm",
        )
        source = np.zeros((len(options), 96), np.float32)
        target = np.zeros_like(source)
        for index, option in enumerate(features.options):
            if 0 <= option.source_entity < len(entities):
                source[index] = entities[option.source_entity]
            if 0 <= option.target_entity < len(entities):
                target[index] = entities[option.target_entity]
        joint = np.concatenate([
            options, source, target, attended,
            np.repeat(board[None, :], len(options), axis=0),
            np.repeat(history[None, :], len(options), axis=0),
            np.repeat(global_vector[None, :], len(options), axis=0),
            np.repeat(order_vector[None, :], len(options), axis=0),
        ], axis=1)
        hidden = _relu(self._linear(joint, "relational_joint1"))
        hidden = _relu(self._linear(hidden, "relational_joint2"))
        context = int(features.options[0].context)
        residual_logits = self._linear(hidden, "relational_score_heads")[:, _family(context)]
        count_input = np.concatenate([
            board, history, global_vector, order_vector,
            self.base._weight("count_context.weight")[min(63, context)],
        ])
        residual_counts = self._linear(
            _relu(self._linear(count_input, "relational_count1")), "relational_count"
        ).reshape(-1)
        return (
            (base_logits + residual_logits).astype(np.float32, copy=False),
            (base_counts + residual_counts).astype(np.float32, copy=False),
        )


class DirectPolicy:
    def __init__(self, path: str | Path, fallback=None, runtime_path: str | Path | None = None):
        path = Path(path)
        self.model_sha256 = hashlib.sha256(path.read_bytes()).hexdigest().upper()
        with np.load(path, allow_pickle=False) as artifact:
            version = int(np.asarray(artifact["direct_model_version"]).item())
        if version == 1:
            self.model = NumpyDirectPolicyModel(path)
        elif version == 2:
            self.model = NumpyRelationalDirectPolicyModel(path)
        else:
            raise ValueError(f"unsupported direct model version {version}")
        self.fallback = fallback
        runtime_path = Path(runtime_path) if runtime_path else path.with_name("direct_runtime.json")
        self.enabled_contexts: set[int] | None = None
        self.disqualified_contexts: set[int] = set()
        self.require_fallback_comparison = False
        self.minimum_complete_advantage = 0.0
        if runtime_path.exists():
            runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
            if str(runtime.get("model_sha256", "")).upper() != self.model_sha256:
                raise ValueError("direct runtime manifest/model hash mismatch")
            enabled = runtime.get("enabled_contexts")
            if enabled is not None:
                self.enabled_contexts = {int(value) for value in enabled}
            self.disqualified_contexts = {int(value) for value in runtime.get("disqualified_contexts", [])}
            self.require_fallback_comparison = bool(runtime.get("require_fallback_comparison", False))
            self.minimum_complete_advantage = float(runtime.get("minimum_complete_advantage", 0.0))
        self.history: list[dict] = []
        self.history_turn = -1
        self.pending_summary: list[float] | None = None
        self.pending_index: int | None = None
        self.shield_telemetry = ShieldTelemetry()
        self.fallback_telemetry = {
            "total": 0, "unrepresented": 0, "inference": 0,
            "nonfinite": 0, "low_advantage": 0,
        }
        self.trace_dir = os.environ.get("PTCG_TRACE_DIR", "").strip()
        self.trace_game = 0
        self.trace_step = 0

    def reset(self) -> None:
        self.history = []
        self.history_turn = -1
        self.pending_summary = None
        self.pending_index = None
        self.trace_game += 1
        self.trace_step = 0
        if self.fallback is not None and hasattr(self.fallback, "reset"):
            self.fallback.reset()

    def _fallback_choose(self, obs, reason: str) -> list[int]:
        if self.fallback is None:
            raise RuntimeError(f"direct policy has no fallback for {reason}")
        self.fallback_telemetry["total"] += 1
        self.fallback_telemetry[reason] = self.fallback_telemetry.get(reason, 0) + 1
        if hasattr(self.fallback, "history"):
            self.fallback.history = [dict(event) for event in self.history]
        if hasattr(self.fallback, "history_turn"):
            self.fallback.history_turn = self.history_turn
        trace_features = None
        if self.trace_dir:
            try:
                trace_features = encode_observation(obs, 5, action_history=self.history)
            except Exception:
                trace_features = None
        result = self.fallback.choose(obs)
        if trace_features is not None:
            self._trace(obs, trace_features, result)
        if hasattr(self.fallback, "history"):
            self.history = [dict(event) for event in self.fallback.history][-EVENT_HISTORY_LENGTH:]
        return result

    def _resolve_pending(self, obs) -> None:
        if self.pending_summary is None or self.pending_index is None:
            return
        current = public_state_summary(obs)
        scales = (6.0, 6.0, 10.0, 10.0, 10.0, 10.0, 5.0, 5.0, 400.0, 400.0, 10.0, 10.0)
        delta = [
            max(-1.0, min(1.0, (after - before) / scale))
            for before, after, scale in zip(self.pending_summary, current, scales)
        ]
        if 0 <= self.pending_index < len(self.history):
            self.history[self.pending_index]["numeric"] = delta
        self.pending_summary = None
        self.pending_index = None

    def _remember(self, obs, features, action) -> None:
        start = len(self.history)
        for position, index in enumerate(action):
            if 0 <= index < len(features.options):
                option = features.options[index]
                self.history.append({
                    "context": option.context,
                    "option_type": option.option_type,
                    "source_card": option.source_card,
                    "source_serial": option.source_serial,
                    "target_card": option.target_card,
                    "target_serial": option.target_serial,
                    "attack_id": option.attack_id,
                    "numeric": [0.0] * 12,
                })
        if len(self.history) > EVENT_HISTORY_LENGTH:
            removed = len(self.history) - EVENT_HISTORY_LENGTH
            self.history = self.history[-EVENT_HISTORY_LENGTH:]
            start = max(0, start - removed)
        if len(self.history) > start:
            self.pending_summary = public_state_summary(obs)
            self.pending_index = len(self.history) - 1

    def _trace(self, obs, features, action) -> None:
        if not self.trace_dir:
            return
        directory = Path(self.trace_dir)
        directory.mkdir(parents=True, exist_ok=True)
        row = {
            "episode_id": f"rollout-{os.getpid()}-{self.trace_game}",
            "seat": int(obs.current.yourIndex),
            "step": self.trace_step,
            "action": [int(index) for index in action],
            "reward": 0.0,
            "hero_order": "first" if obs.current.yourIndex == obs.current.firstPlayer else "second",
            "source": "schema5_on_policy_rollout",
            "features": features.to_json(),
        }
        with (directory / f"trace-{os.getpid()}.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
        self.trace_step += 1

    def choose(self, obs) -> list[int]:
        if obs.select.context == SelectContext.IS_FIRST:
            for index, option in enumerate(obs.select.option):
                if option.type == OptionType.YES:
                    return sanitize_selection(obs.select, [index], 1)
        turn = int(obs.current.turn or 0)
        if turn != self.history_turn:
            self.history_turn = turn
            self.history = []
            self.pending_summary = None
            self.pending_index = None
        else:
            self._resolve_pending(obs)
        context = int(obs.select.context)
        if context in self.disqualified_contexts or (
            self.enabled_contexts is not None and context not in self.enabled_contexts
        ):
            return self._fallback_choose(obs, "unrepresented")
        try:
            features = encode_observation(obs, 5, action_history=self.history)
            logits, counts = self.model.predict(features)
        except Exception:
            return self._fallback_choose(obs, "inference")
        if not np.all(np.isfinite(logits)) or not np.all(np.isfinite(counts)):
            return self._fallback_choose(obs, "nonfinite")
        if not len(logits):
            return []
        ranked = np.argsort(-logits, kind="stable").astype(int).tolist()
        if obs.select.minCount == obs.select.maxCount:
            desired = int(obs.select.maxCount)
        else:
            minimum = int(obs.select.minCount)
            maximum = min(int(obs.select.maxCount), len(counts) - 1)
            desired = minimum + int(np.argmax(counts[minimum:maximum + 1]))
        ranked, desired, intervention = apply_tactical_shield(obs, ranked, desired)
        self.shield_telemetry.record(intervention)
        result = sanitize_selection(obs.select, ranked, desired)
        if self.require_fallback_comparison and self.fallback is not None:
            if hasattr(self.fallback, "history"):
                self.fallback.history = [dict(event) for event in self.history]
            if hasattr(self.fallback, "history_turn"):
                self.fallback.history_turn = self.history_turn
            fallback_choice = self.fallback.choose(obs)
            fallback_result = sanitize_selection(obs.select, fallback_choice, len(fallback_choice))
            advantage = _complete_score(
                logits, counts, result, obs.select.minCount, obs.select.maxCount
            ) - _complete_score(
                logits, counts, fallback_result, obs.select.minCount, obs.select.maxCount
            )
            if result != fallback_result and advantage < self.minimum_complete_advantage:
                self.fallback_telemetry["total"] += 1
                self.fallback_telemetry["low_advantage"] += 1
                result = fallback_result
        self._trace(obs, features, result)
        self._remember(obs, features, result)
        return result
