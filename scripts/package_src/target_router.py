"""Public-information target router over the actual-order base agent.

Start every game as exact EXP-23 base. Continuously accumulate PUBLIC opponent
evidence. When a target archetype becomes confidently identified, mark the
route pending; lock it at the next safe switch boundary (our MAIN context).
Once locked the route never changes. Missed detection is safe (base EXP-23);
false positives are dangerous, so the frozen rules are precision-first.

Specialist models are optional: a missing npz disables that route.
"""

from __future__ import annotations

import os
from pathlib import Path

from cg.api import OptionType, SelectContext, to_observation_class

from .agent import CompetitionAgent
from .safety import sanitize_selection

DIP_DISTINCTIVE = {88, 89, 90, 1245}
DIP_COMMON = {42, 92, 93}
LUC_DISTINCTIVE = {673, 674, 677, 678}
LUC_COMMON = {675, 676}
LUC_ALL = LUC_DISTINCTIVE | LUC_COMMON
DIP_ALL = DIP_DISTINCTIVE | DIP_COMMON


def _find(filename: str) -> Path:
    for candidate in (Path(filename), Path("/kaggle_simulations/agent") / filename):
        if candidate.exists():
            return candidate
    raise FileNotFoundError(filename)


def _optional_find(filename: str) -> Path | None:
    for candidate in (Path(filename), Path("/kaggle_simulations/agent") / filename):
        if candidate.exists():
            return candidate
    return None


def public_ids(obs) -> set[int]:
    ids: set[int] = set()
    current = obs.current
    if current is None:
        return ids
    players = current.players or []
    opponent_index = 1 - int(current.yourIndex)
    if opponent_index < 0 or opponent_index >= len(players):
        return ids
    opp = players[opponent_index]
    for slot in list(opp.active or []) + list(opp.bench or []):
        if slot is None:
            continue
        ids.add(int(slot.id))
        for pre in slot.preEvolution or []:
            ids.add(int(pre.id))
    for card in opp.discard or []:
        if card is not None:
            ids.add(int(card.id))
    for card in current.stadium or []:
        if card is not None:
            ids.add(int(card.id))
    return ids


def dip_confident(ids: set[int]) -> bool:
    distinct = ids & DIP_DISTINCTIVE
    common = ids & DIP_COMMON
    if ids & {88, 89, 90}:
        return True
    if len(distinct) >= 2:
        return True
    if distinct and common:
        return True
    return False


def luc_confident(ids: set[int]) -> bool:
    distinct = ids & LUC_DISTINCTIVE
    common = ids & LUC_COMMON
    if 678 in ids:
        return True
    if 677 in ids and ids & (LUC_COMMON | {673, 674}):
        return True
    if ids & {673, 674}:
        return True
    if len(distinct) >= 2:
        return True
    return False


class TargetRouterAgent:
    """EXP-23 base with optional Dipplin/Lucario specialist routes."""

    def __init__(self) -> None:
        deck = _find("deck.csv")
        self.exact = CompetitionAgent(deck, _find("policy_d842_exact.npz"))
        self.policy_first = CompetitionAgent(deck, _find("policy_first.npz"))
        self.policy_second = CompetitionAgent(deck, _find("policy_second.npz"))
        self.deck = list(self.exact.deck)
        dip_path = _optional_find("policy_dip.npz")
        luc_path = _optional_find("policy_luc.npz")
        self.dip = CompetitionAgent(deck, dip_path) if dip_path else None
        self.luc = CompetitionAgent(deck, luc_path) if luc_path else None
        self.actual_order = None
        self.route = None
        self.pending = None
        self.conflicted = False
        self.forced = os.environ.get("PTCG_TARGET_ROUTE", "")
        if self.forced.startswith("force_"):
            self.forced = self.forced[len("force_"):]
        self.errors = 0

    def _reset(self) -> list[int]:
        self.actual_order = None
        self.route = None
        self.pending = None
        self.conflicted = False
        self.errors = 0
        for agent in (self.exact, self.policy_first, self.policy_second, self.dip, self.luc):
            if agent is None:
                continue
            agent.errors = 0
            if hasattr(agent.policy, "reset"):
                agent.policy.reset()
            if hasattr(agent.fallback, "reset"):
                agent.fallback.reset()
        return list(self.deck)

    def _selected_agent(self):
        if self.route == "dipplin" and self.dip is not None:
            return self.dip
        if self.route == "lucario" and self.luc is not None:
            return self.luc
        return self.policy_first if self.actual_order == "first" else self.policy_second

    def _update_detector(self, obs) -> None:
        if self.route is not None or self.conflicted:
            return
        ids = public_ids(obs)
        dip = dip_confident(ids)
        luc = luc_confident(ids)
        if dip and luc:
            self.pending = None
            self.conflicted = True
            return
        if self.pending is None:
            if dip:
                self.pending = "dipplin"
            elif luc:
                self.pending = "lucario"
        elif self.pending == "dipplin" and luc:
            self.pending = None
            self.conflicted = True
        elif self.pending == "lucario" and dip:
            self.pending = None
            self.conflicted = True

    def __call__(self, obs_dict: dict) -> list[int]:
        if not obs_dict or obs_dict.get("select") is None:
            return self._reset()
        obs = to_observation_class(obs_dict)
        if obs.select.context == SelectContext.IS_FIRST:
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

        if self.forced:
            if self.forced in ("dipplin", "lucario"):
                self.route = self.forced
                self.pending = None
            else:
                self.route = None
                self.pending = None
        else:
            self._update_detector(obs)
            if self.pending is not None and obs.select.context == SelectContext.MAIN:
                self.route = self.pending
                self.pending = None

        selected = self._selected_agent()
        before = int(getattr(selected, "errors", 0) or 0)
        try:
            action = selected(obs_dict)
        except Exception:
            self.errors += 1
            return self.exact(obs_dict)
        after = int(getattr(selected, "errors", 0) or 0)
        if after != before:
            self.errors += after - before
            return self.exact(obs_dict)
        return sanitize_selection(obs.select, action, len(action))
