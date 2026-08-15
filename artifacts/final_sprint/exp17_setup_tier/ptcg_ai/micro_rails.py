"""Micro rails on the frozen A2+Damage V0 policy. Reorder-only, fail-closed."""

from __future__ import annotations

from cg.api import OptionType, SelectContext

from .card_ids import MARNIES_IMPIDIMP, MUNKIDORI, SNORUNT

_SETUP_PRIORITY = (MARNIES_IMPIDIMP, MUNKIDORI, SNORUNT)


def _hand_id(obs, option) -> int:
    idx = getattr(option, "index", None)
    if idx is None:
        return int(getattr(option, "cardId", 0) or 0)
    me = obs.current.players[obs.current.yourIndex]
    hand = me.hand or []
    if 0 <= idx < len(hand) and hand[idx] is not None:
        return int(hand[idx].id)
    return int(getattr(option, "cardId", 0) or 0)


def _setup_active_tier(obs, ranked, desired):
    sel = obs.select
    try:
        if int(getattr(sel, "context", -1)) != int(SelectContext.SETUP_ACTIVE_POKEMON):
            return None
    except (AttributeError, TypeError, ValueError):
        return None
    if int(getattr(obs.current, "turn", -1)) != 0:
        return None
    def tier(index):
        card_id = _hand_id(obs, sel.option[index])
        return _SETUP_PRIORITY.index(card_id) if card_id in _SETUP_PRIORITY else len(_SETUP_PRIORITY)
    if not ranked:
        return None
    chosen = ranked[0]
    if tier(chosen) <= min(tier(i) for i in ranked):
        return None
    return sorted(list(ranked), key=tier), desired, "setup_active_tier"


def apply(obs, ranked, desired):
    result = _setup_active_tier(obs, ranked, desired)
    if result is None:
        return ranked, desired, None
    return result
