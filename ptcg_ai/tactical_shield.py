"""Three narrowly scoped, deterministic tactical safety interventions."""

from __future__ import annotations

from collections import Counter

from cg.api import OptionType

from .prevention import attack_nullified
from .view import card_table, option_source_card


SETUP_BENCH_CONTEXT = 2


def _context_is(select, numeric: int, name: str) -> bool:
    context = getattr(select, "context", None)
    return context == numeric or str(context).endswith(name)


def _option_type(option) -> int:
    return int(getattr(option, "type", -1))


def _productive_attacks(obs, ranked: list[int]) -> list[int]:
    return [
        index
        for index in ranked
        if _option_type(obs.select.option[index]) == int(OptionType.ATTACK)
        and not attack_nullified(obs, obs.select.option[index])
    ]


def _is_basic(card) -> bool:
    if card is None:
        return False
    if bool(getattr(card, "basic", False)):
        return True
    metadata = card_table().get(int(getattr(card, "id", 0) or 0))
    return bool(metadata is not None and metadata.basic)


def apply_tactical_shield(obs, ranked: list[int], desired: int) -> tuple[list[int], int, str | None]:
    """Apply at most one approved intervention without bypassing sanitization."""
    select = obs.select
    ranked = list(ranked)

    if _context_is(select, SETUP_BENCH_CONTEXT, "SETUP_BENCH_POKEMON") and select.maxCount > 0:
        source_cards = [option_source_card(obs, select.option[index]) for index in ranked]
        basic = [
            index
            for index, card in zip(ranked, source_cards)
            if _is_basic(card)
        ]
        # In older observations setup choices omit source-card metadata; those
        # options are nevertheless engine-filtered to legal Basic Pokemon.
        if not basic and ranked and all(card is None for card in source_cards):
            basic = ranked
        if basic and desired < 1:
            return basic + [i for i in ranked if i not in basic], 1, "setup_bench_basic"

    if desired == 1 and ranked:
        chosen = ranked[0]
        chosen_option = select.option[chosen]
        productive = _productive_attacks(obs, ranked)

        if _option_type(chosen_option) == int(OptionType.ATTACK) and attack_nullified(obs, chosen_option):
            alternatives = [
                index
                for index in ranked
                if index != chosen
                and not (
                    _option_type(select.option[index]) == int(OptionType.ATTACK)
                    and attack_nullified(obs, select.option[index])
                )
            ]
            if alternatives:
                preferred = productive[0] if productive else alternatives[0]
                return [preferred] + [i for i in ranked if i != preferred], desired, "nullified_attack"

        if _option_type(chosen_option) == int(OptionType.END) and productive:
            preferred = productive[0]
            return [preferred] + [i for i in ranked if i != preferred], desired, "end_with_productive_attack"

    return ranked, desired, None


class ShieldTelemetry:
    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.last_intervention: str | None = None

    def record(self, reason: str | None) -> None:
        self.last_intervention = reason
        if reason is not None:
            self.counts[reason] += 1
