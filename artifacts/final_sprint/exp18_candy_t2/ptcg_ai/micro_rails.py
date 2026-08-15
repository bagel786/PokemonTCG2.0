"""Micro rails on the frozen A2+Damage V0 policy. Reorder-only, fail-closed."""

from __future__ import annotations

from cg.api import OptionType, SelectContext

from .card_ids import MARNIES_IMPIDIMP, MARNIES_GRIMMSNARL_EX, RARE_CANDY


def _play_card(obs, option) -> int:
    idx = getattr(option, "index", None)
    if idx is None:
        return int(getattr(option, "cardId", 0) or 0)
    me = obs.current.players[obs.current.yourIndex]
    hand = me.hand or []
    if 0 <= idx < len(hand) and hand[idx] is not None:
        return int(hand[idx].id)
    return int(getattr(option, "cardId", 0) or 0)


def _candy_t2(obs, ranked, desired):
    """If an old Impidimp, Rare Candy, and Grimmsnarl ex are all available on
    our second turn, promote the candy play above other non-attack options."""
    sel = obs.select
    try:
        if int(getattr(sel, "context", -1)) != int(SelectContext.MAIN):
            return None
    except (AttributeError, TypeError, ValueError):
        return None
    state = obs.current
    first_player = int(getattr(state, "firstPlayer", -1))
    turn = int(getattr(state, "turn", 0) or 0)
    own_turn = (turn + 1) // 2 if state.yourIndex == first_player else turn // 2
    if own_turn != 2:
        return None
    me = state.players[state.yourIndex]
    board = [c for c in ((me.active or []) + (me.bench or [])) if c is not None]
    if not any(int(c.id) == MARNIES_IMPIDIMP and not bool(getattr(c, "appearThisTurn", False)) for c in board):
        return None
    hand_ids = {int(c.id) for c in (me.hand or []) if c is not None}
    if RARE_CANDY not in hand_ids or MARNIES_GRIMMSNARL_EX not in hand_ids:
        return None
    candy_idx = None
    for i in ranked:
        opt = sel.option[i]
        if int(getattr(opt, "type", -1)) == int(OptionType.PLAY) and _play_card(obs, opt) == RARE_CANDY:
            candy_idx = i
            break
    if candy_idx is None or candy_idx == ranked[0]:
        return None
    return [candy_idx] + [i for i in ranked if i != candy_idx], desired, "candy_t2_push"


def apply(obs, ranked, desired):
    result = _candy_t2(obs, ranked, desired)
    if result is None:
        return ranked, desired, None
    return result
