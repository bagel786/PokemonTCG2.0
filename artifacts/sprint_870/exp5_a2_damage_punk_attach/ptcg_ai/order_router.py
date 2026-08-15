"""Actual-order router for the controlled 5k+ submission package.

The package builder copies this small module into an otherwise exact d842
archive.  It deliberately depends only on modules already present in d842.
"""

from __future__ import annotations

from pathlib import Path

from cg.api import OptionType, SelectContext, to_observation_class

from .agent import CompetitionAgent
from .safety import sanitize_selection


def _find(filename: str) -> Path:
    for candidate in (Path(filename), Path("/kaggle_simulations/agent") / filename):
        if candidate.exists():
            return candidate
    raise FileNotFoundError(filename)


class ActualOrderAgent:
    """Choose a policy from latched actual order, with exact d842 fallback."""

    def __init__(self) -> None:
        deck = _find("deck.csv")
        self.exact = CompetitionAgent(deck, _find("policy_d842_exact.npz"))
        self.policy_first = CompetitionAgent(deck, _find("policy_first.npz"))
        self.policy_second = CompetitionAgent(deck, _find("policy_second.npz"))
        self.deck = list(self.exact.deck)
        self.actual_order = None
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

    def __call__(self, obs_dict: dict) -> list[int]:
        if not obs_dict or obs_dict.get("select") is None:
            return self._reset()
        obs = to_observation_class(obs_dict)
        if obs.select.context == SelectContext.IS_FIRST:
            # Today's controlled candidate always requests first when asked.
            yes = [index for index, option in enumerate(obs.select.option) if option.type == OptionType.YES]
            if len(yes) == 1:
                return sanitize_selection(obs.select, yes, 1)
            self.errors += 1
            return self.exact(obs_dict)

        if self.actual_order is None and obs.current is not None:
            first_player = int(obs.current.firstPlayer)
            your_index = int(obs.current.yourIndex)
            if first_player in (0, 1) and your_index in (0, 1):
                self.actual_order = "first" if first_player == your_index else "second"
        if self.actual_order not in {"first", "second"}:
            self.errors += 1
            return self.exact(obs_dict)
        selected = self.policy_first if self.actual_order == "first" else self.policy_second
        before = int(getattr(selected, "errors", 0) or 0)
        try:
            action = selected(obs_dict)
        except Exception:
            self.errors += 1
            return self.exact(obs_dict)
        after = int(getattr(selected, "errors", 0) or 0)
        if after != before:
            # CompetitionAgent swallowed a model exception; replace its heuristic
            # answer with the exact d842 policy answer.
            self.errors += after - before
            return self.exact(obs_dict)
        return sanitize_selection(obs.select, action, len(action))
