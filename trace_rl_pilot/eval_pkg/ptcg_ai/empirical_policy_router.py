"""Outcome-grounded categorical router between A2 and temporal continuation."""

from __future__ import annotations

import json
from pathlib import Path

from cg.api import to_observation_class

from .agent import CompetitionAgent
from .features import encode_observation
from .safety import sanitize_selection
from .temporal_context_gate import semantic_key


def _find(filename: str) -> Path:
    for candidate in (Path(filename), Path("/kaggle_simulations/agent") / filename):
        if candidate.exists():
            return candidate
    raise FileNotFoundError(filename)


class EmpiricalPolicyRouterAgent:
    """Use temporal only for public categorical cells selected by gameplay."""

    def __init__(self) -> None:
        deck = _find("deck.csv")
        self.exact = CompetitionAgent(deck, _find("policy_a2_schema3.npz"))
        self.temporal = CompetitionAgent(deck, _find("policy_continuation.npz"))
        config = json.loads(_find("empirical_router.json").read_text(encoding="utf-8"))
        if int(config.get("schema_version", 0)) != 1:
            raise ValueError("unsupported empirical router schema")
        self.routes = []
        for raw in config.get("temporal_routes", []):
            route = {
                key: int(value)
                for key, value in raw.items()
                if key in {"context", "a2_option_type", "temporal_option_type"}
            }
            if not route or any(value < 0 for value in route.values()):
                raise ValueError("invalid empirical route")
            self.routes.append(route)
        if not self.routes:
            raise ValueError("empirical router has no routes")
        self.actual_order = str(config.get("actual_order", ""))
        if self.actual_order not in {"first", "second", "both"}:
            raise ValueError("invalid empirical router actual_order")
        self.deck = list(self.exact.deck)
        self.errors = 0
        self.semantic_disagreements = 0
        self.temporal_routes = 0

    def _reset(self, obs_dict: dict) -> list[int]:
        deck = self.exact(obs_dict)
        self.temporal(obs_dict)
        self.errors = 0
        self.semantic_disagreements = 0
        self.temporal_routes = 0
        return deck

    @staticmethod
    def _call(agent: CompetitionAgent, obs_dict: dict, obs) -> tuple[list[int], int]:
        before = int(getattr(agent, "errors", 0) or 0)
        action = agent(obs_dict)
        errors = max(0, int(getattr(agent, "errors", 0) or 0) - before)
        return sanitize_selection(obs.select, action, len(action)), errors

    def _order_matches(self, obs) -> bool:
        if self.actual_order == "both":
            return True
        first = int(obs.current.firstPlayer)
        yours = int(obs.current.yourIndex)
        if first not in (0, 1):
            return False
        observed = "first" if first == yours else "second"
        return observed == self.actual_order

    def __call__(self, obs_dict: dict) -> list[int]:
        if not obs_dict or obs_dict.get("select") is None:
            return self._reset(obs_dict)
        try:
            obs = to_observation_class(obs_dict)
            a2_action, a2_errors = self._call(self.exact, obs_dict, obs)
            if a2_errors:
                self.errors += a2_errors
                return a2_action
            if not self._order_matches(obs) or len(a2_action) != 1:
                return a2_action
            temporal_action, temporal_errors = self._call(self.temporal, obs_dict, obs)
            if temporal_errors or len(temporal_action) != 1:
                self.errors += temporal_errors
                return a2_action
            features = encode_observation(obs, 3)
            a2_index = int(a2_action[0])
            temporal_index = int(temporal_action[0])
            if (
                not 0 <= a2_index < len(features.options)
                or not 0 <= temporal_index < len(features.options)
                or semantic_key(features.options[a2_index])
                == semantic_key(features.options[temporal_index])
            ):
                return a2_action
            self.semantic_disagreements += 1
            cell = {
                "context": int(features.options[0].context),
                "a2_option_type": int(features.options[a2_index].option_type),
                "temporal_option_type": int(features.options[temporal_index].option_type),
            }
            if any(all(cell[key] == value for key, value in route.items()) for route in self.routes):
                self.temporal_routes += 1
                return temporal_action
            return a2_action
        except Exception:
            self.errors += 1
            try:
                obs = to_observation_class(obs_dict)
                action = self.exact(obs_dict)
                return sanitize_selection(obs.select, action, len(action))
            except Exception:
                return []
