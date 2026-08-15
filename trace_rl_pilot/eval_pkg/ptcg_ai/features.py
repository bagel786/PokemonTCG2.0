"""Hidden-information-safe feature extraction for policy and value models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from cg.api import AreaType, LogType, OptionType

from .prevention import attack_nullified
from .view import attack_table, card_table, cards_in_play, option_source_card, option_target_pokemon, prize_value

CARD_LIMIT = 1300
ATTACK_LIMIT = 1600
V1_ZONE_COUNT = 12
V2_ZONE_COUNT = 16
ZONE_COUNT = V2_ZONE_COUNT
STATE_TOKEN_VOCAB = CARD_LIMIT * ZONE_COUNT
V1_GLOBAL_SIZE = 32
V2_GLOBAL_SIZE = 118
V4_GLOBAL_SIZE = 124
V5_GLOBAL_SIZE = V4_GLOBAL_SIZE
GLOBAL_SIZE = V4_GLOBAL_SIZE
OPTION_NUMERIC_SIZE = 12
V3_OPTION_NUMERIC_SIZE = OPTION_NUMERIC_SIZE + 1  # + attack-nullified flag
V4_OPTION_NUMERIC_SIZE = V3_OPTION_NUMERIC_SIZE + 6
ENTITY_NUMERIC_SIZE = 16
ENTITY_ZONE_COUNT = 17
EVENT_HISTORY_LENGTH = 16
EVENT_NUMERIC_SIZE = 12
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
    HISTORY = 16


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
    source_serial: int = 0
    target_serial: int = 0
    source_entity: int = -1
    target_entity: int = -1


@dataclass
class EntityFeatures:
    """One visible card/Pokemon with stable source and board-slot binding."""

    card_id: int
    serial: int
    owner: int
    zone: int
    slot: int
    entity_type: int
    numeric: list[float]


@dataclass
class EventFeatures:
    """One ordered, already-observed action from the current turn."""

    context: int
    option_type: int
    source_card: int
    source_serial: int
    target_card: int
    target_serial: int
    attack_id: int
    position: int
    numeric: list[float]


@dataclass
class DecisionFeatures:
    global_features: list[float]
    state_tokens: list[int]
    options: list[OptionFeatures]
    feature_version: int = 1
    entities: list[EntityFeatures] = field(default_factory=list)
    events: list[EventFeatures] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "feature_version": self.feature_version,
            "global": self.global_features,
            "tokens": self.state_tokens,
            "options": [asdict(option) for option in self.options],
            "entities": [asdict(entity) for entity in self.entities],
            "events": [asdict(event) for event in self.events],
        }

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> "DecisionFeatures":
        return cls(
            global_features=value["global"],
            state_tokens=value["tokens"],
            options=[OptionFeatures(**option) for option in value["options"]],
            feature_version=int(value.get("feature_version", 1)),
            entities=[EntityFeatures(**entity) for entity in value.get("entities", [])],
            events=[EventFeatures(**event) for event in value.get("events", [])],
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


def _card_metadata(card_id: int):
    return card_table().get(int(card_id or 0))


def _attack_ready(pokemon) -> float:
    data = _card_metadata(getattr(pokemon, "id", 0))
    if data is None or not data.attacks:
        return 0.0
    attached = len(getattr(pokemon, "energies", []) or [])
    return float(any(len(attack_table().get(attack_id).energies) <= attached
                     for attack_id in data.attacks if attack_table().get(attack_id) is not None))


def _entity_numeric(card, *, pokemon=None, active: bool = False) -> list[float]:
    card_id = int(getattr(card, "id", 0) or 0)
    data = _card_metadata(card_id)
    current_hp = float(getattr(pokemon, "hp", 0) or 0)
    maximum_hp = float(getattr(pokemon, "maxHp", 0) or 0)
    attached = len(getattr(pokemon, "energies", []) or []) if pokemon is not None else 0
    tools = len(getattr(pokemon, "tools", []) or []) if pokemon is not None else 0
    return [
        1.0,
        current_hp / 400.0,
        maximum_hp / 400.0,
        max(0.0, maximum_hp - current_hp) / 400.0,
        attached / 10.0,
        tools / 4.0,
        prize_value(pokemon) / 3.0 if pokemon is not None else 0.0,
        float(getattr(pokemon, "appearThisTurn", False)),
        float(bool(data and data.basic)),
        float(bool(data and data.stage1)),
        float(bool(data and data.stage2)),
        float(bool(data and data.ex)),
        float(bool(data and data.megaEx)),
        _attack_ready(pokemon) if pokemon is not None else 0.0,
        (float(data.retreatCost) / 5.0) if data is not None else 0.0,
        float(active),
    ]


def _visible_entities(obs, action_history: list[dict[str, Any]] | None = None) -> list[EntityFeatures]:
    state = obs.current
    me = state.players[state.yourIndex]
    opponent = state.players[1 - state.yourIndex]
    entities: list[EntityFeatures] = []

    def add(card, owner: int, zone: int, slot: int, *, pokemon=None, active=False) -> None:
        if card is None:
            return
        card_id = int(getattr(card, "id", 0) or 0)
        data = _card_metadata(card_id)
        entities.append(EntityFeatures(
            card_id=max(0, min(CARD_LIMIT - 1, card_id)),
            serial=max(0, int(getattr(card, "serial", 0) or 0)),
            owner=owner,
            zone=zone,
            slot=max(0, min(127, slot)),
            entity_type=min(7, 1 + int(data.cardType)) if data is not None else 0,
            numeric=_entity_numeric(card, pokemon=pokemon, active=active),
        ))

    def add_pokemon(pokemon, owner: int, zone: int, slot: int, active: bool) -> None:
        if pokemon is None:
            return
        add(pokemon, owner, zone, slot, pokemon=pokemon, active=active)
        for attached in getattr(pokemon, "energyCards", []) or []:
            add(attached, owner, TokenZone.OWN_ATTACHED if owner == 0 else TokenZone.OPP_ATTACHED, slot)
        for attached in getattr(pokemon, "tools", []) or []:
            add(attached, owner, TokenZone.OWN_ATTACHED if owner == 0 else TokenZone.OPP_ATTACHED, slot)
        for attached in getattr(pokemon, "preEvolution", []) or []:
            add(attached, owner, TokenZone.OWN_ATTACHED if owner == 0 else TokenZone.OPP_ATTACHED, slot)

    for index, card in enumerate(me.hand or []):
        add(card, 0, TokenZone.OWN_HAND, index)
    for index, pokemon in enumerate(me.active or []):
        add_pokemon(pokemon, 0, TokenZone.OWN_ACTIVE, index, True)
    for index, pokemon in enumerate(me.bench or []):
        add_pokemon(pokemon, 0, TokenZone.OWN_BENCH, index + 1, False)
    for index, card in enumerate((me.discard or [])[-20:]):
        add(card, 0, TokenZone.OWN_DISCARD, index)
    for index, pokemon in enumerate(opponent.active or []):
        add_pokemon(pokemon, 1, TokenZone.OPP_ACTIVE, index, True)
    for index, pokemon in enumerate(opponent.bench or []):
        add_pokemon(pokemon, 1, TokenZone.OPP_BENCH, index + 1, False)
    for index, card in enumerate((opponent.discard or [])[-20:]):
        add(card, 1, TokenZone.OPP_DISCARD, index)
    for index, card in enumerate(state.stadium or []):
        add(card, 2, TokenZone.STADIUM, index)
    for index, card in enumerate(state.looking or []):
        add(card, 0, TokenZone.LOOKING, index)
    for index, card in enumerate(obs.select.deck or []):
        add(card, 0, TokenZone.SELECT_DECK, index)
    if obs.select.contextCard is not None:
        add(obs.select.contextCard, 0, TokenZone.CONTEXT_CARD, 0)
    if obs.select.effect is not None:
        add(obs.select.effect, 0, TokenZone.EFFECT_CARD, 0)
    for index, event in enumerate((action_history or [])[-16:]):
        card_id = int(event.get("source_card", 0) or 0)
        if card_id:
            synthetic = type("HistoryCard", (), {
                "id": card_id,
                "serial": int(event.get("source_serial", 0) or 0),
            })()
            add(synthetic, 0, TokenZone.HISTORY, index)
            entities[-1].numeric[-1] = min(17, int(event.get("option_type", 0))) / 17.0
    return entities


def _own_turn_ordinal(state) -> int:
    if state.firstPlayer not in (0, 1) or state.turn <= 0:
        return 0
    return (state.turn + 1) // 2 if state.yourIndex == state.firstPlayer else state.turn // 2


def _evolution_ready_count(player) -> int:
    names = {
        data.name for pokemon in cards_in_play(player)
        if (data := _card_metadata(getattr(pokemon, "id", 0))) is not None
    }
    return sum(
        bool(data and data.evolvesFrom and data.evolvesFrom in names)
        for card in (player.hand or [])
        if (data := _card_metadata(getattr(card, "id", 0))) is not None
    )


def _minimum_attack_deficit(player) -> int:
    deficits: list[int] = []
    for pokemon in cards_in_play(player):
        data = _card_metadata(getattr(pokemon, "id", 0))
        attached = len(getattr(pokemon, "energies", []) or [])
        for attack_id in (data.attacks if data is not None else []):
            attack = attack_table().get(attack_id)
            if attack is not None:
                deficits.append(max(0, len(attack.energies) - attached))
    return min(deficits) if deficits else 5


def public_state_summary(obs) -> list[float]:
    """Return an acting-seat-relative summary containing public information only."""
    state = obs.current
    me = state.players[state.yourIndex]
    opponent = state.players[1 - state.yourIndex]

    def board_damage(player) -> float:
        return float(sum(
            max(0, int(getattr(card, "maxHp", 0) or 0) - int(getattr(card, "hp", 0) or 0))
            for card in cards_in_play(player)
        ))

    def board_energy(player) -> float:
        return float(sum(len(getattr(card, "energies", []) or []) for card in cards_in_play(player)))

    return [
        float(len(me.prize)),
        float(len(opponent.prize)),
        float(me.handCount),
        float(opponent.handCount),
        float(me.deckCount),
        float(opponent.deckCount),
        float(len(me.bench)),
        float(len(opponent.bench)),
        board_damage(me),
        board_damage(opponent),
        board_energy(me),
        board_energy(opponent),
    ]


def public_state_delta(before, after) -> list[float]:
    """Scaled public-state delta from two acting-seat-relative observations."""
    left = public_state_summary(before)
    right = public_state_summary(after)
    scales = (6.0, 6.0, 10.0, 10.0, 10.0, 10.0, 5.0, 5.0, 400.0, 400.0, 10.0, 10.0)
    return [max(-1.0, min(1.0, (b - a) / scale)) for a, b, scale in zip(left, right, scales)]


def _event_features(action_history: list[dict[str, Any]] | None) -> list[EventFeatures]:
    history = list(action_history or [])[-EVENT_HISTORY_LENGTH:]
    events: list[EventFeatures] = []
    for index, event in enumerate(history):
        numeric = [float(value) for value in event.get("numeric", [])[:EVENT_NUMERIC_SIZE]]
        numeric.extend([0.0] * (EVENT_NUMERIC_SIZE - len(numeric)))
        events.append(EventFeatures(
            context=max(0, min(63, int(event.get("context", 0) or 0))),
            option_type=max(0, min(17, int(event.get("option_type", 0) or 0))),
            source_card=max(0, min(CARD_LIMIT - 1, int(event.get("source_card", 0) or 0))),
            source_serial=max(0, int(event.get("source_serial", 0) or 0)),
            target_card=max(0, min(CARD_LIMIT - 1, int(event.get("target_card", 0) or 0))),
            target_serial=max(0, int(event.get("target_serial", 0) or 0)),
            attack_id=max(0, min(ATTACK_LIMIT - 1, int(event.get("attack_id", 0) or 0))),
            position=index,
            numeric=numeric,
        ))
    return events


def encode_observation(
    obs,
    feature_version: int = 2,
    action_history: list[dict[str, Any]] | None = None,
) -> DecisionFeatures:
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

    entities: list[EntityFeatures] = []
    events: list[EventFeatures] = []
    entity_index: dict[int, int] = {}
    if feature_version >= 4:
        # Schema 4 represented history as source-card pseudo-entities.  Preserve
        # that contract for its frozen artifacts; schema 5 has a causal event stream.
        entities = _visible_entities(obs, action_history if feature_version == 4 else None)
        entity_index = {
            entity.serial: index for index, entity in enumerate(entities) if entity.serial > 0
        }
        global_features.extend([
            min(20, _own_turn_ordinal(state)) / 20.0,
            (len(opponent.prize) - len(me.prize)) / 6.0,
            min(16, len(action_history or [])) / 16.0,
            min(6, _evolution_ready_count(me)) / 6.0,
            min(6, sum(_attack_ready(card) for card in cards_in_play(me))) / 6.0,
            min(5, _minimum_attack_deficit(me)) / 5.0,
        ])
    if feature_version >= 5:
        events = _event_features(action_history)

    option_features = [encode_option(obs, option, feature_version, entity_index) for option in select.option]
    return DecisionFeatures(global_features, tokens, option_features, feature_version, entities, events)


def encode_option(
    obs,
    option,
    feature_version: int = 2,
    entity_index: dict[int, int] | None = None,
) -> OptionFeatures:
    # Preserve the exact schema-1/2/3 inference contract for frozen historical
    # models.  Schema 4 is the first schema that intentionally binds PLAY to
    # the indexed hand card.
    selected = (
        None
        if feature_version < 4 and option.type == OptionType.PLAY and option.area is None
        else option_source_card(obs, option)
    )
    target = option_target_pokemon(obs, option)
    source = selected
    if option.type == OptionType.CARD:
        target = selected
        if feature_version >= 5:
            # Follow-up choices (ability damage movement, attack targets,
            # searches, recovery, etc.) select a target card while the causal
            # source lives in effect/contextCard. Binding the selected card as
            # both source and target loses the relation schema 5 is meant to fix.
            source = obs.select.effect or obs.select.contextCard or selected
    elif feature_version >= 5 and option.type in {
        OptionType.NUMBER, OptionType.YES, OptionType.NO,
    }:
        source = obs.select.effect or obs.select.contextCard or selected
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
    source_serial = int(getattr(source, "serial", 0) or 0)
    target_serial = int(getattr(target, "serial", 0) or 0)
    if feature_version >= 4:
        data = _card_metadata(source_id)
        numeric.extend([
            (int(data.cardType) / 6.0) if data is not None else 0.0,
            float(bool(data and data.basic)),
            float(bool(data and data.stage1)),
            float(bool(data and data.stage2)),
            min(120, source_serial) / 120.0,
            min(120, target_serial) / 120.0,
        ])
    return OptionFeatures(
        option_type=int(option.type),
        context=int(obs.select.context),
        source_card=max(0, min(CARD_LIMIT - 1, source_id)),
        target_card=max(0, min(CARD_LIMIT - 1, target_id)),
        attack_id=max(0, min(ATTACK_LIMIT - 1, int(option.attackId or 0))),
        area=int(option.area or 0),
        in_play_area=int(option.inPlayArea or 0),
        numeric=numeric,
        source_serial=source_serial,
        target_serial=target_serial,
        source_entity=(entity_index or {}).get(source_serial, -1),
        target_entity=(entity_index or {}).get(target_serial, -1),
    )
