"""Minimal actual-order router for an authentic A2 shield package."""

from __future__ import annotations

from pathlib import Path

from cg.api import SelectContext, to_observation_class

from .agent import CompetitionAgent
from .safety import sanitize_selection


def _find(filename: str) -> Path:
    for candidate in (Path(filename), Path("/kaggle_simulations/agent") / filename):
        if candidate.exists():
            return candidate
    raise FileNotFoundError(filename)


class ActualOrderAgent:
    """Route by latched firstPlayer, falling back to byte-exact A2 policy."""

    def __init__(self) -> None:
        deck = _find("deck.csv")
        self.exact = CompetitionAgent(deck, _find("policy_weights.npz"))
        self.policy_first = CompetitionAgent(deck, _find("policy_first.npz"))
        self.policy_second = CompetitionAgent(deck, _find("policy_second.npz"))
        self.deck = list(self.exact.deck)
        self.actual_order: str | None = None
        self.errors = 0

    def _reset(self) -> list[int]:
        self.actual_order = None
        self.errors = 0
        for agent in (self.exact, self.policy_first, self.policy_second):
            agent.errors = 0
            if hasattr(agent.policy, "reset"):
                agent.policy.reset()
            if hasattr(agent.fallback, "reset"):
                agent.fallback.reset()
        return list(self.deck)

    def _exact(self, obs_dict: dict) -> list[int]:
        return self.exact(obs_dict)

    def _run(self, selected, obs, obs_dict: dict) -> list[int]:
        before = int(getattr(selected, "errors", 0) or 0)
        try:
            action = selected(obs_dict)
        except Exception:
            self.errors += 1
            return self._exact(obs_dict)
        after = int(getattr(selected, "errors", 0) or 0)
        if after != before:
            self.errors += max(1, after - before)
            return self._exact(obs_dict)
        return sanitize_selection(obs.select, action, len(action))

    def __call__(self, obs_dict: dict) -> list[int]:
        if not obs_dict or obs_dict.get("select") is None:
            return self._reset()
        obs = to_observation_class(obs_dict)
        if obs.select.context == SelectContext.IS_FIRST:
            # Actual order is not known yet.  Preserve the designated first
            # policy's pre-latch choice instead of adding an order heuristic.
            return self._run(self.policy_first, obs, obs_dict)

        observed_order = None
        if obs.current is not None:
            first_player = int(obs.current.firstPlayer)
            your_index = int(obs.current.yourIndex)
            if first_player in (0, 1) and your_index in (0, 1):
                observed_order = "first" if first_player == your_index else "second"
        if self.actual_order is None and observed_order is not None:
            self.actual_order = observed_order
        elif observed_order is not None and observed_order != self.actual_order:
            self.errors += 1
            return self._exact(obs_dict)
        if self.actual_order not in {"first", "second"}:
            self.errors += 1
            return self._exact(obs_dict)
        selected = self.policy_first if self.actual_order == "first" else self.policy_second
        return self._run(selected, obs, obs_dict)
