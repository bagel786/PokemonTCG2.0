"""Small deterministic logit mixer for d842/A2 emergency candidates."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from cg.api import OptionType, SelectContext, to_observation_class

from .agent import CompetitionAgent
from .features import encode_observation
from .model import NumpyPolicyModel
from .safety import sanitize_selection
from .tactical_shield import ShieldTelemetry, apply_tactical_shield
from .view import attack_table, card_table


def _find(filename: str) -> Path:
    for candidate in (Path(filename), Path("/kaggle_simulations/agent") / filename):
        if candidate.exists():
            return candidate
    raise FileNotFoundError(filename)


def _normalise(weights: dict[str, float]) -> dict[str, float]:
    clean = {str(key): float(value) for key, value in weights.items() if float(value) > 0}
    total = sum(clean.values())
    if total <= 0:
        raise ValueError("policy mixture must have positive total weight")
    return {key: value / total for key, value in clean.items()}


def _own_turn_ordinal(state) -> int:
    if state.firstPlayer not in (0, 1) or int(state.turn or 0) <= 0:
        return 0
    return ((int(state.turn) + 1) // 2 if state.yourIndex == state.firstPlayer
            else int(state.turn) // 2)


def _ready_replacement(obs) -> bool:
    state = obs.current
    me = state.players[state.yourIndex]
    for pokemon in me.bench or []:
        data = card_table().get(int(getattr(pokemon, "id", 0) or 0))
        attached = len(getattr(pokemon, "energies", []) or [])
        if data is None:
            continue
        for attack_id in data.attacks:
            attack = attack_table().get(attack_id)
            if attack is not None and len(attack.energies) <= attached:
                return True
    return False


class MixedPolicy:
    def __init__(self, config: dict):
        self.config = config
        self.models = {
            "d842": NumpyPolicyModel(_find("policy_d842.npz")),
            "a2": NumpyPolicyModel(_find("policy_a2.npz")),
        }
        master = Path("policy_master.npz")
        if not master.exists():
            master = Path("/kaggle_simulations/agent/policy_master.npz")
        if master.exists():
            self.models["master"] = NumpyPolicyModel(master)
        if len({model.feature_version for model in self.models.values()}) != 1:
            raise ValueError("mixed policies must share one feature schema")
        self.feature_version = next(iter(self.models.values())).feature_version
        self.shield_telemetry = ShieldTelemetry()

    def _base_weights(self, obs) -> dict[str, float]:
        state = obs.current
        order = "first" if state.firstPlayer == state.yourIndex else "second"
        weights = self.config.get(f"{order}_weights") or self.config["weights"]
        mode = self.config.get("phase_mode", "none")
        ordinal = _own_turn_ordinal(state)
        if mode == "early_a2":
            if ordinal and ordinal <= int(self.config.get("early_turns", 3)):
                weights = {"a2": 1.0}
            else:
                weights = self.config.get("late_weights", weights)
        elif mode == "development_combat":
            context = int(obs.select.context)
            combat_contexts = {
                int(SelectContext.SWITCH), int(SelectContext.TO_ACTIVE),
                int(SelectContext.DAMAGE_COUNTER), int(SelectContext.DAMAGE_COUNTER_ANY),
                int(SelectContext.DAMAGE), int(SelectContext.EFFECT_TARGET),
                int(SelectContext.ATTACK), int(SelectContext.DAMAGE_COUNTER_COUNT),
                int(SelectContext.REMOVE_DAMAGE_COUNTER_COUNT),
            }
            # MAIN presents development and combat options together, so routing it
            # from option presence would classify almost every turn as combat.
            # Only route semantic follow-up contexts whose purpose is unambiguous.
            is_combat = context in combat_contexts
            weights = (self.config.get("combat_weights", weights) if is_combat
                       else self.config.get("development_weights", {"a2": 1.0}))
        elif mode == "continuity":
            weights = (self.config.get("stable_weights", weights) if _ready_replacement(obs)
                       else self.config.get("unstable_weights", {"a2": 1.0}))
        return _normalise(weights)

    def choose(self, obs) -> list[int]:
        features = encode_observation(obs, self.feature_version)
        weights = self._base_weights(obs)
        predictions = {name: self.models[name].predict(features) for name in weights}
        logits = sum(weight * predictions[name][0] for name, weight in weights.items())
        count_logits = sum(weight * predictions[name][1] for name, weight in weights.items())
        if len(logits) == 0:
            return []
        ranked = np.argsort(-logits).astype(int).tolist()
        if obs.select.minCount == obs.select.maxCount:
            desired = int(obs.select.maxCount)
        else:
            minimum = int(obs.select.minCount)
            maximum = min(int(obs.select.maxCount), len(count_logits) - 1)
            desired = minimum + int(np.argmax(count_logits[minimum:maximum + 1]))
        ranked, desired, intervention = apply_tactical_shield(obs, ranked, desired)
        self.shield_telemetry.record(intervention)
        return sanitize_selection(obs.select, ranked, desired)


class MixedPolicyAgent:
    """Competition-facing wrapper with exact-d842 fail-closed fallback."""

    def __init__(self):
        self.deck_path = _find("deck.csv")
        self.deck = [int(line) for line in self.deck_path.read_text().splitlines() if line.strip()]
        if len(self.deck) != 60:
            raise ValueError("deck must contain exactly 60 cards")
        self.config = json.loads(_find("mix_config.json").read_text(encoding="utf-8"))
        self.policy = MixedPolicy(self.config)
        self.exact = CompetitionAgent(self.deck_path, _find("policy_d842.npz"))
        self.errors = 0

    def __call__(self, obs_dict: dict) -> list[int]:
        if not obs_dict or obs_dict.get("select") is None:
            self.errors = 0
            self.exact.errors = 0
            return list(self.deck)
        obs = to_observation_class(obs_dict)
        if obs.select.context == SelectContext.IS_FIRST:
            yes = [i for i, option in enumerate(obs.select.option) if option.type == OptionType.YES]
            if len(yes) == 1:
                return sanitize_selection(obs.select, yes, 1)
        try:
            return self.policy.choose(obs)
        except Exception:
            self.errors += 1
            return self.exact(obs_dict)
