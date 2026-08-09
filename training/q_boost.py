"""Training-only exact-state action comparisons for Q-boosted advantages."""

from __future__ import annotations

from dataclasses import asdict
from typing import Callable

from cg.api import search_begin, search_end, search_release, search_step


def exact_hidden_arguments(obs, visualizer_frame: dict) -> dict:
    full = visualizer_frame["current"]
    me = int(obs.current.yourIndex)
    opponent = 1 - me
    mine = full["players"][me]
    theirs = full["players"][opponent]
    card_ids = lambda cards: [int(card["id"]) for card in cards or [] if card is not None]
    opponent_active = []
    visible_active = obs.current.players[opponent].active or []
    if visible_active and visible_active[0] is None:
        opponent_active = card_ids(theirs.get("active"))
    return {
        "your_deck": card_ids(mine.get("deck")),
        "your_prize": card_ids(mine.get("prize")),
        "opponent_deck": card_ids(theirs.get("deck")),
        "opponent_prize": card_ids(theirs.get("prize")),
        "opponent_hand": card_ids(theirs.get("hand")),
        "opponent_active": opponent_active,
        "manual_coin": True,
    }


def _rollout(state, root_player: int, selector: Callable, max_steps: int) -> float:
    try:
        for _ in range(max_steps):
            current = state.observation.current
            if current is None:
                return 0.0
            if int(current.result) >= 0:
                if int(current.result) == 2:
                    return 0.0
                return 1.0 if int(current.result) == root_player else -1.0
            if state.observation.select is None:
                return 0.0
            action = selector(state.observation)
            next_state = search_step(state.searchId, action)
            search_release(state.searchId)
            state = next_state
        return 0.0
    finally:
        try:
            search_release(state.searchId)
        except Exception:
            pass


def compare_actions(obs, visualizer_frame: dict, actions: list[list[int]], selector: Callable, max_steps: int = 320) -> list[float]:
    """Return terminal Q estimates on one exact training-only hidden state."""
    if len(actions) < 2:
        raise ValueError("Q comparison requires at least two actions")
    root = None
    try:
        root = search_begin(obs, **exact_hidden_arguments(obs, visualizer_frame))
        scores = []
        for action in actions:
            child = search_step(root.searchId, action)
            scores.append(_rollout(child, int(obs.current.yourIndex), selector, max_steps))
        return scores
    finally:
        if root is not None:
            try:
                search_release(root.searchId)
            except Exception:
                pass
        try:
            search_end()
        except Exception:
            pass
