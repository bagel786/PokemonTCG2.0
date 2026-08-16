"""Hidden-information-safe feature extraction for policy and value models."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from cg.api import AreaType, LogType, OptionType

from .prevention import attack_nullified
from .view import cards_in_play, option_source_card, option_target_pokemon, prize_value

CARD_LIMIT = 1300
ATTACK_LIMIT = 1600
V1_ZONE_COUNT = 12
V2_ZONE_COUNT = 16
ZONE_COUNT = V2_ZONE_COUNT
STATE_TOKEN_VOCAB = CARD_LIMIT * ZONE_COUNT
V1_GLOBAL_SIZE = 32
V2_GLOBAL_SIZE = 118
GLOBAL_SIZE = V2_GLOBAL_SIZE
OPTION_NUMERIC_SIZE = 12
V3_OPTION_NUMERIC_SIZE = OPTION_NUMERIC_SIZE + 1  # + attack-nullified flag
MAX_SELECT_COUNT = 9
V2_COUNT_CLASSES = 61


class TokenZone:
    OWN_ACTIVE = 0
    OWN_BENCH = 1
    OWN_HAND = 2
    OWN_DISCARD = 3
    OWN_ATTACHED = 4
    OPP_ACTIVE = 5
    OPP_BENCH = 6
    OPP_DISCARD = 7
    OPP_ATTACHED = 8
    STADIUM = 9
    OPP_REVEALED_LOG = 10
    OWN_REVEALED_LOG = 11
    LOOKING = 12
    SELECT_DECK = 13
    CONTEXT_CARD = 14
    EFFECT_CARD = 15


@dataclass
class OptionFeatures:
    option_type: int
    context: int
    source_card: int
    target_card: int
    attack_id: int
    area: int
    in_play_area: int
    numeric: list[float]


@dataclass
class DecisionFeatures:
    global_features: list[float]
    state_tokens: list[int]
    options: list[OptionFeatures]
    feature_version: int = 1

    def to_json(self) -> dict[str, Any]:
        return {
            "feature_version": self.feature_version,
            "global": self.global_features,
            "tokens": self.state_tokens,
            "options": [asdict(option) for option in self.options],
        }

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> "DecisionFeatures":
        return cls(
            global_features=value["global"],
            state_tokens=value["tokens"],
            options=[OptionFeatures(**option) for option in value["options"]],
            feature_version=int(value.get("feature_version", 1)),
        )


def _token(zone: int, card_id: int) -> int:
    return zone * CARD_LIMIT + max(0, min(CARD_LIMIT - 1, int(card_id)))


def _add_cards(tokens: list[int], zone: int, cards) -> None:
    for card in cards or []:
        if card is not None:
            tokens.append(_token(zone, card.id))


def _add_pokemon(tokens: list[int], zone: int, attached_zone: int, pokemon_list) -> None:
    for pokemon in pokemon_list or []:
        if pokemon is None:
            continue
        tokens.append(_token(zone, pokemon.id))
        _add_cards(tokens, attached_zone, pokemon.energyCards)
        _add_cards(tokens, attached_zone, pokemon.tools)
        _add_cards(tokens, attached_zone, pokemon.preEvolution)


def _pokemon_slots(player) -> list[float]:
    """Encode active plus five bench slots without hiding card multiplicity or damage."""
    pokemon = list(player.active or [])[:1] + list(player.bench or [])[:5]
    pokemon.extend([None] * (6 - len(pokemon)))
    values: list[float] = []
    for card in pokemon:
        if card is None:
            values.extend([0.0] * 7)
            continue
        values.extend([
            1.0,
            (card.hp or 0) / 400.0,
            max(0, (card.maxHp or 0) - (card.hp or 0)) / 400.0,
            len(card.energies or []) / 10.0,
            len(card.tools or []) / 4.0,
            prize_value(card) / 3.0,
            float(card.appearThisTurn),
        ])
    return values


def encode_observation(obs, feature_version: int = 2) -> DecisionFeatures:
    """Encode only fields delivered to the acting seat.

    Replay visualizer data, shuffled deck contents, face-down prizes, and the opponent's
    hand are intentionally impossible to pass through this interface.
    """
    state = obs.current
    select = obs.select
    me = state.players[state.yourIndex]
    opponent = state.players[1 - state.yourIndex]

    tokens: list[int] = []
    _add_pokemon(tokens, TokenZone.OWN_ACTIVE, TokenZone.OWN_ATTACHED, me.active)
    _add_pokemon(tokens, TokenZone.OWN_BENCH, TokenZone.OWN_ATTACHED, me.bench)
    _add_cards(tokens, TokenZone.OWN_HAND, me.hand)
    _add_cards(tokens, TokenZone.OWN_DISCARD, me.discard)
    _add_pokemon(tokens, TokenZone.OPP_ACTIVE, TokenZone.OPP_ATTACHED, opponent.active)
    _add_pokemon(tokens, TokenZone.OPP_BENCH, TokenZone.OPP_ATTACHED, opponent.bench)
    _add_cards(tokens, TokenZone.OPP_DISCARD, opponent.discard)
    _add_cards(tokens, TokenZone.STADIUM, state.stadium)
    for log in obs.logs:
        if log.cardId is None:
            continue
        zone = TokenZone.OWN_REVEALED_LOG if log.playerIndex == state.yourIndex else TokenZone.OPP_REVEALED_LOG
        if log.type not in {LogType.DRAW_REVERSE, LogType.MOVE_CARD_REVERSE}:
            tokens.append(_token(zone, log.cardId))
    if feature_version >= 2:
        _add_cards(tokens, TokenZone.LOOKING, state.looking)
        _add_cards(tokens, TokenZone.SELECT_DECK, select.deck)
        _add_cards(tokens, TokenZone.CONTEXT_CARD, [select.contextCard] if select.contextCard else [])
        _add_cards(tokens, TokenZone.EFFECT_CARD, [select.effect] if select.effect else [])
    if not tokens:
        tokens.append(_token(TokenZone.OWN_HAND, 0))

    own_active = me.active[0] if me.active else None
    opp_active = opponent.active[0] if opponent.active else None
    global_features = [
        min(state.turn, 100) / 100.0,
        min(state.turnActionCount, 50) / 50.0,
        float(state.yourIndex),
        float(state.firstPlayer == state.yourIndex),
        float(state.supporterPlayed),
        float(state.stadiumPlayed),
        float(state.energyAttached),
        float(state.retreated),
        me.deckCount / 60.0,
        opponent.deckCount / 60.0,
        len(me.prize) / 6.0,
        len(opponent.prize) / 6.0,
        me.handCount / 30.0,
        opponent.handCount / 30.0,
        len(me.bench) / max(1, me.benchMax),
        len(opponent.bench) / max(1, opponent.benchMax),
        (own_active.hp / max(1, own_active.maxHp)) if own_active else 0.0,
        (opp_active.hp / max(1, opp_active.maxHp)) if opp_active else 0.0,
        float(me.poisoned),
        float(me.burned),
        float(me.asleep),
        float(me.paralyzed),
        float(me.confused),
        float(opponent.poisoned),
        float(opponent.burned),
        float(opponent.asleep),
        float(opponent.paralyzed),
        float(opponent.confused),
        select.minCount / MAX_SELECT_COUNT,
        select.maxCount / MAX_SELECT_COUNT,
        select.remainDamageCounter / 50.0,
        select.remainEnergyCost / 10.0,
    ]
    if feature_version >= 2:
        global_features.extend(_pokemon_slots(me))
        global_features.extend(_pokemon_slots(opponent))
        global_features.extend([
            len(state.looking or []) / 60.0,
            len(select.deck or []) / 60.0,
        ])

    option_features = [encode_option(obs, option, feature_version) for option in select.option]
    return DecisionFeatures(global_features, tokens, option_features, feature_version)


PLAY_IDENTITY_ENABLED = False


def encode_option(obs, option, feature_version: int = 2) -> OptionFeatures:
    source = option_source_card(obs, option)
    if (
        PLAY_IDENTITY_ENABLED
        and source is None
        and option.type == OptionType.PLAY
    ):
        state = obs.current
        hand = state.players[state.yourIndex].hand or []
        index = getattr(option, "index", None)
        source = hand[index] if index is not None and 0 <= index < len(hand) else None
    target = option_target_pokemon(obs, option)
    if target is None and option.type == OptionType.CARD:
        target = source
    source_id = source.id if source is not None else int(option.cardId or 0)
    target_id = target.id if target is not None else 0
    numeric = [
        (option.number or 0) / 20.0,
        (option.count or 0) / 10.0,
        (getattr(target, "hp", 0) or 0) / 400.0,
        (getattr(target, "maxHp", 0) or 0) / 400.0,
        len(getattr(target, "energies", []) or []) / 10.0,
        len(getattr(target, "tools", []) or []) / 4.0,
        prize_value(target) / 3.0,
        float(getattr(target, "appearThisTurn", False)),
        float(option.playerIndex == obs.current.yourIndex) if option.playerIndex is not None else 0.0,
        (option.index or 0) / 60.0,
        (option.inPlayIndex or 0) / 8.0,
        (option.energyIndex or option.toolIndex or 0) / 10.0,
    ]
    if feature_version >= 3:
        # The engine never surfaces computed damage on an attack option, so a
        # blanked attack is otherwise indistinguishable from a lethal one.
        numeric.append(float(attack_nullified(obs, option)))
    return OptionFeatures(
        option_type=int(option.type),
        context=int(obs.select.context),
        source_card=max(0, min(CARD_LIMIT - 1, source_id)),
        target_card=max(0, min(CARD_LIMIT - 1, target_id)),
        attack_id=max(0, min(ATTACK_LIMIT - 1, int(option.attackId or 0))),
        area=int(option.area or 0),
        in_play_area=int(option.inPlayArea or 0),
        numeric=numeric,
    )
