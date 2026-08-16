"""Small NumPy policy/value network used in Kaggle submissions."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from .features import MAX_SELECT_COUNT, encode_observation
from .safety import sanitize_selection
from .tactical_shield import ShieldTelemetry, apply_tactical_shield
from .grim_damage_solver import GrimDamageSolver
from .grim_variance_floor import GrimVarianceConfig, GrimVarianceFloorDirector


class NumpyPolicyModel:
    """Inference-only mirror of the PyTorch behavior-cloning model."""

    def __init__(self, path: str | Path):
        arrays = np.load(path, allow_pickle=False)
        self.weights = {name: arrays[name].astype(np.float32, copy=False) for name in arrays.files}
        self.feature_version = int(np.asarray(arrays["model_schema_version"]).item()) if "model_schema_version" in arrays else 1

    @staticmethod
    def _embedding(table, indices):
        return table[np.asarray(indices, dtype=np.int64)]

    def predict(self, features):
        w = self.weights
        state_rows = self._embedding(w["state_embedding"], features.state_tokens)
        if self.feature_version >= 2:
            state = state_rows.sum(axis=0) / np.sqrt(max(1, len(state_rows)))
        else:
            state = state_rows.mean(axis=0)
        global_vector = np.tanh(np.asarray(features.global_features, dtype=np.float32) @ w["global_w"] + w["global_b"])
        shared = np.concatenate([state, global_vector])
        option_rows = []
        for option in features.options:
            numeric = np.tanh(np.asarray(option.numeric, dtype=np.float32) @ w["numeric_w"] + w["numeric_b"])
            option_rows.append(np.concatenate([
                shared,
                w["card_embedding"][option.source_card],
                w["card_embedding"][option.target_card],
                w["attack_embedding"][option.attack_id],
                w["type_embedding"][option.option_type],
                w["context_embedding"][min(option.context, len(w["context_embedding"]) - 1)],
                w["area_embedding"][min(option.area, len(w["area_embedding"]) - 1)],
                w["area_embedding"][min(option.in_play_area, len(w["area_embedding"]) - 1)],
                numeric,
            ]))
        if option_rows:
            option_matrix = np.stack(option_rows)
            hidden = np.tanh(option_matrix @ w["option_w"] + w["option_b"])
            logits = hidden @ w["score_w"] + w["score_b"]
            context = features.options[0].context
        else:
            logits = np.empty(0, dtype=np.float32)
            context = 0
        count_input = np.concatenate([shared, w["context_embedding"][min(context, len(w["context_embedding"]) - 1)]])
        count_logits = count_input @ w["count_w"] + w["count_b"]
        value_logit = shared @ w["value_w"] + w["value_b"]
        return logits.reshape(-1), count_logits.reshape(-1), float(value_logit.reshape(-1)[0])


class NeuralPolicy:
    def __init__(self, path: str | Path, fallback):
        self.model = NumpyPolicyModel(path)
        self.fallback = fallback
        self.shield_telemetry = ShieldTelemetry()
        enabled = (Path(path).name != 'policy_d842_exact.npz' and os.environ.get('PTCG_GRIM_DAMAGE_SOLVER') == 'v0')
        self.damage_solver = GrimDamageSolver(enabled)
        escape_enabled = (Path(path).name != 'policy_d842_exact.npz' and os.environ.get('PTCG_GRIM_ESCAPE_SOLVER') == 'v0')
        self.escape_director = (
            GrimVarianceFloorDirector(
                GrimVarianceConfig(dead_active_escape=True),
                budgets={
                    'setup_active': 0, 'setup_bench': 0,
                    'shadow_over_retreat': 0, 'shadow_over_boss': 0,
                },
            ) if escape_enabled else None
        )
        self.escape_last_intervention = None

    def reset(self) -> None:
        self.damage_solver.reset()
        self.escape_last_intervention = None
        if self.escape_director is not None:
            self.escape_director.reset()

    def choose(self, obs) -> list[int]:
        features = encode_observation(obs, self.model.feature_version)
        logits, count_logits, _ = self.model.predict(features)
        if len(logits) == 0:
            return []
        ranked = np.argsort(-logits).astype(int).tolist()
        if obs.select.minCount == obs.select.maxCount:
            desired = obs.select.maxCount
        else:
            minimum = int(obs.select.minCount)
            maximum = min(int(obs.select.maxCount), len(count_logits) - 1)
            desired = minimum + int(np.argmax(count_logits[minimum : maximum + 1]))
        ranked, desired, intervention = apply_tactical_shield(obs, ranked, desired)
        self.shield_telemetry.record(intervention)
        self.escape_last_intervention = None
        escape_ok = self.escape_director is not None
        if escape_ok:
            try:
                ranked, desired, self.escape_last_intervention = self.escape_director.apply(obs, ranked, desired)
            except Exception:
                self.escape_director.reset()
                self.escape_last_intervention = None
                escape_ok = False
        ranked, desired, _ = self.damage_solver.apply(obs, ranked, desired)
        action = sanitize_selection(obs.select, ranked, desired)
        if escape_ok:
            try:
                self.escape_director.commit(obs, action)
            except Exception:
                self.escape_director.reset()
        return action
