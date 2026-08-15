"""Narrow Spikemuth Gym search-tier rail on the frozen A2+Damage V0 policy.

Causal evidence (live replays, mirror-first losses): when the Gym search
prompt offers evolution pieces (Morgrem 647 / Grimmsnarl ex 648) while we
already control an Impidimp, choosing another Impidimp delays the candy chain
by a turn and loses the first-Grimmsnarl race.  Reorder-only and fail-closed.
"""

from __future__ import annotations

from cg.api import SelectContext

from .card_ids import MARNIES_GRIMMSNARL_EX, MARNIES_IMPIDIMP, MARNIES_MORGREM, SPIKEMUTH_GYM

_PIECE_TIERS = (MARNIES_GRIMMSNARL_EX, MARNIES_MORGREM, MARNIES_IMPIDIMP)


def _effect_id(obs) -> int:
    effect = getattr(obs.select, "effect", None)
    context = getattr(obs.select, "contextCard", None)
    return int(getattr(effect or context, "id", 0) or 0)


def _deck_card_id(obs, index: int) -> int:
    deck = getattr(obs.select, "deck", None) or []
    if not 0 <= index < len(deck):
        return 0
    card = deck[index]
    return int(getattr(card, "id", 0) or 0)


def apply(obs, ranked: list[int], desired: int):
    """Return (ranked, desired, reason); no-op unless this is our Gym search."""
    if _effect_id(obs) != SPIKEMUTH_GYM:
        return ranked, desired, None
    try:
        if int(getattr(obs.select, "context", -1)) != int(SelectContext.TO_HAND):
            return ranked, desired, None
    except (AttributeError, TypeError, ValueError):
        return ranked, desired, None
    state = getattr(obs, "current", None)
    if state is None:
        return ranked, desired, None
    first_player = int(getattr(state, "firstPlayer", -1))
    turn = int(getattr(state, "turn", 0) or 0)
    own_turn = (turn + 1) // 2 if state.yourIndex == first_player else turn // 2
    if own_turn != 1:
        return ranked, desired, None
    me = state.players[state.yourIndex]
    board = [c for c in ((me.active or []) + (me.bench or [])) if c is not None]
    if not any(int(c.id) == MARNIES_IMPIDIMP for c in board):
        return ranked, desired, None
    hand_ids = {int(c.id) for c in (me.hand or []) if c is not None}
    if MARNIES_GRIMMSNARL_EX in hand_ids and MARNIES_MORGREM in hand_ids:
        return ranked, desired, None
    def tier(index):
        card_id = _deck_card_id(obs, index)
        if card_id in _PIECE_TIERS:
            return _PIECE_TIERS.index(card_id)
        return len(_PIECE_TIERS)
    chosen = ranked[0] if ranked else -1
    if tier(chosen) <= tier(min(ranked, key=tier) if ranked else chosen):
        # model's top pick is already at least as good as the best available
        return ranked, desired, None
    reordered = sorted(list(ranked), key=tier)
    return reordered, desired, "gym_piece_tier"
