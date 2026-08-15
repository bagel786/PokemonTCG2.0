"""Observation helpers shared by heuristics, encoders, and safety checks."""

from __future__ import annotations

from collections import Counter
from functools import lru_cache
from typing import Iterable

from cg.api import AreaType, Card, Observation, Option, OptionType, Pokemon, all_attack, all_card_data


@lru_cache(maxsize=1)
def card_table():
    return {card.cardId: card for card in all_card_data()}


@lru_cache(maxsize=1)
def attack_table():
    return {attack.attackId: attack for attack in all_attack()}


def cards_in_play(player) -> list[Pokemon]:
    return [p for p in (player.active or []) + (player.bench or []) if p is not None]


def resolve_area_card(obs: Observation, area, index, player_index=None):
    if obs.current is None or area is None or index is None:
        return None
    state = obs.current
    owner = state.yourIndex if player_index is None else player_index
    if area == AreaType.LOOKING:
        zone = state.looking or []
    elif area == AreaType.STADIUM:
        zone = state.stadium or []
    elif area == AreaType.DECK:
        zone = obs.select.deck or []
    else:
        player = state.players[owner]
        zone = {
            AreaType.HAND: player.hand or [],
            AreaType.DISCARD: player.discard or [],
            AreaType.ACTIVE: player.active or [],
            AreaType.BENCH: player.bench or [],
            AreaType.PRIZE: player.prize or [],
        }.get(area, [])
    if not 0 <= index < len(zone):
        return None
    return zone[index]


def option_source_card(obs: Observation, option: Option):
    """Return the card directly selected or played by an option."""
    # MAIN/PLAY options identify a card only by its hand index.  The engine
    # deliberately omits ``area`` and ``playerIndex`` for this option type.
    # Treating the missing area as an unknown zone made every PLAY option look
    # like card zero to schema 2/3 models.
    if option.type == OptionType.PLAY:
        return resolve_area_card(
            obs,
            AreaType.HAND,
            option.index,
            obs.current.yourIndex if obs.current is not None else None,
        )
    return resolve_area_card(
        obs,
        option.area,
        option.index,
        getattr(option, "playerIndex", None),
    )


def option_target_pokemon(obs: Observation, option: Option):
    """Return an in-play target for ATTACH/EVOLVE options."""
    area = getattr(option, "inPlayArea", None)
    index = getattr(option, "inPlayIndex", None)
    if area is None:
        return None
    return resolve_area_card(obs, area, index, obs.current.yourIndex)


def prize_value(pokemon: Pokemon | None) -> int:
    if pokemon is None:
        return 0
    data = card_table().get(pokemon.id)
    if data is None:
        return 1
    return 3 if data.megaEx else 2 if data.ex else 1


def attached_energy_count(pokemon: Pokemon | None) -> int:
    return len(getattr(pokemon, "energies", []) or []) if pokemon is not None else 0


def damage_on(pokemon: Pokemon | None) -> int:
    return max(0, getattr(pokemon, "maxHp", 0) - getattr(pokemon, "hp", 0)) if pokemon is not None else 0


def id_counts(items: Iterable[Card | Pokemon | None]) -> Counter:
    return Counter(item.id for item in items if item is not None)


def known_card_counts(player) -> Counter:
    known = list(player.hand or []) + list(player.discard or []) + list(player.prize or [])
    known.extend(cards_in_play(player))
    for pokemon in cards_in_play(player):
        known.extend(pokemon.energyCards or [])
        known.extend(pokemon.tools or [])
        known.extend(pokemon.preEvolution or [])
    return id_counts(known)
