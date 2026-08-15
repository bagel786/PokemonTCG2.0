"""Actual-order schema-2 router with byte-exact A2 as the fail-closed policy.

The learned policies are used only after ``current.firstPlayer`` identifies
the hero's actual order.  The pre-latch ``IS_FIRST`` decision and every
candidate failure are delegated to the unchanged A2 policy.
"""

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


class OutcomeOrderAgent:
    """Route schema-2 policies by actual order, failing closed to exact A2."""

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
            for policy in (getattr(agent, "policy", None), getattr(agent, "fallback", None)):
                if policy is not None and hasattr(policy, "reset"):
                    policy.reset()
        return list(self.deck)

    def _exact(self, obs_dict: dict) -> list[int]:
        return self.exact(obs_dict)

    def _candidate(self, selected: CompetitionAgent, obs, obs_dict: dict) -> list[int]:
        before = int(getattr(selected, "errors", 0) or 0)
        try:
            action = selected(obs_dict)
            after = int(getattr(selected, "errors", 0) or 0)
            if after != before:
                self.errors += max(1, after - before)
                return self._exact(obs_dict)
            return sanitize_selection(obs.select, action, len(action))
        except Exception:
            self.errors += 1
            return self._exact(obs_dict)

    def __call__(self, obs_dict: dict) -> list[int]:
        if not obs_dict or obs_dict.get("select") is None:
            return self._reset()
        try:
            obs = to_observation_class(obs_dict)
        except Exception:
            self.errors += 1
            return self._exact(obs_dict)

        # Training forces order externally and contains no IS_FIRST examples.
        # Keep that untrained pre-latch decision behavior-identical to A2.
        if obs.select.context == SelectContext.IS_FIRST:
            return self._exact(obs_dict)

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
        return self._candidate(selected, obs, obs_dict)
