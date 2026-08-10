"""Fail-closed selective proof search around an externally supplied policy action.

This module intentionally does not know how the baseline action was produced.  In
particular, it does not import or call the d842 model: callers pass the exact
already-sanitized action and that action remains the fallback on every failure.

The native evaluator is deliberately only a *one prompt* diagnostic.  All root
candidates are stepped as siblings from one native search root, so they share one
determinization.  A non-terminal candidate can only override the baseline when
every sibling reaches the same semantic boundary.  Effects which need unequal
numbers of prompts therefore abstain instead of comparing unequal horizons.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence

from cg.api import AreaType, EnergyType, OptionType, SelectContext, to_observation_class

from .card_ids import (
    BOSS_ORDERS,
    DAWN,
    MARNIES_GRIMMSNARL_EX,
    MARNIES_IMPIDIMP,
    MARNIES_MORGREM,
    POKE_PAD,
    RARE_CANDY,
    TOOL_SCRAPPER,
    UNFAIR_STAMP,
)


OUTCOME_FIELDS = (
    "terminal_win",
    "terminal_not_loss",
    "prizes_taken",
    "ko_value",
    "damage_pressure",
    "ready_attackers",
    "route_progress",
    "unexposed_prizes",
    "retained_critical_resources",
)

_TARGET_CONTEXTS = frozenset(
    {
        int(SelectContext.SWITCH),
        int(SelectContext.TO_ACTIVE),
        int(SelectContext.DAMAGE_COUNTER),
        int(SelectContext.DAMAGE_COUNTER_ANY),
        int(SelectContext.DAMAGE),
        int(SelectContext.EFFECT_TARGET),
    }
)
_PROMOTION_CONTEXTS = frozenset({int(SelectContext.SWITCH), int(SelectContext.TO_ACTIVE)})
_DAMAGE_TARGET_CONTEXTS = frozenset(
    {
        int(SelectContext.DAMAGE_COUNTER),
        int(SelectContext.DAMAGE_COUNTER_ANY),
        int(SelectContext.DAMAGE),
        int(SelectContext.EFFECT_TARGET),
    }
)
_CRITICAL_RESOURCE_IDS = frozenset(
    {RARE_CANDY, UNFAIR_STAMP, TOOL_SCRAPPER, POKE_PAD, BOSS_ORDERS, DAWN}
)
_REASON_PRIORITY = {
    "ko_target": 100,
    "attack_over_end": 95,
    "lethal_attack": 94,
    "attack_choice": 93,
    "ready_promotion": 90,
    "ready_retreat": 85,
    "readiness_evolve": 80,
    "readiness_attach": 75,
}


class ProofSearchError(RuntimeError):
    """A search comparison could not be completed safely."""


class ProofSearchTimeout(TimeoutError):
    """The hard proof-search deadline expired."""


@dataclass(frozen=True)
class ProofSearchConfig:
    """Conservative proof requirements for a single decision."""

    worlds: int = 8
    min_strict_worlds: int = 4
    max_candidates: int = 8
    timeout_seconds: float = 0.25
    seed_salt: str = "grim-selective-proof-v1"

    def __post_init__(self) -> None:
        if self.worlds <= 0:
            raise ValueError("worlds must be positive")
        if not 1 <= self.min_strict_worlds <= self.worlds:
            raise ValueError("min_strict_worlds must be in [1, worlds]")
        if self.max_candidates < 2:
            raise ValueError("max_candidates must leave room for baseline and one alternative")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")


@dataclass(frozen=True)
class SemanticCandidate:
    """A current-prompt action identified without relying on option positions."""

    action: tuple[int, ...]
    key: str
    reason: str
    is_baseline: bool = False

    @property
    def token(self) -> str:
        return hashlib.sha256(self.key.encode("utf-8")).hexdigest().upper()[:16]


@dataclass(frozen=True)
class WorldOutcome:
    """Public lexicographic result at a named semantic horizon."""

    vector: tuple[float, ...]
    boundary: tuple[str, ...]


@dataclass
class ProofSearchResult:
    """Search result; ``action`` is always safe to return directly."""

    status: str
    action: list[int]
    trigger: str | None
    reason: str
    public_state_digest: str = ""
    coverage: dict[str, int] = field(default_factory=dict)
    strict_worlds: int = 0
    candidate_tokens: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


WorldRunner = Callable[
    [Any, tuple[SemanticCandidate, ...], int, float, Sequence[int] | None],
    Mapping[str, WorldOutcome],
]
ContinuationSelectorFactory = Callable[[], Any]
Determinizer = Callable[[Any, list[int], list[int], random.Random], Mapping[str, Any]]


class NativeSearchBackend(Protocol):
    """Small injectable boundary around the process-global native search API."""

    def begin(self, obs: Any, determinization: Mapping[str, Any]) -> Any: ...

    def step(self, search_id: int, action: Sequence[int]) -> Any: ...

    def release(self, search_id: int) -> None: ...

    def end(self) -> None: ...


class _CgNativeSearchBackend:
    def begin(self, obs: Any, determinization: Mapping[str, Any]) -> Any:
        from cg.api import search_begin

        return search_begin(obs, manual_coin=True, **dict(determinization))

    def step(self, search_id: int, action: Sequence[int]) -> Any:
        from cg.api import search_step

        return search_step(int(search_id), list(map(int, action)))

    def release(self, search_id: int) -> None:
        from cg.api import search_release

        search_release(int(search_id))

    def end(self) -> None:
        from cg.api import search_end

        search_end()


def _default_determinizer(
    obs: Any,
    hero_deck: list[int],
    opponent_deck: list[int],
    rng: random.Random,
) -> Mapping[str, Any]:
    from .search import determinize_state

    return determinize_state(obs, hero_deck, opponent_deck, rng)


def _primitive(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return int(value.value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return str(value)


def _integer(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _cards(zone: Any) -> list[Any]:
    return [card for card in (zone or []) if card is not None]


def _card_identity(card: Any) -> dict[str, int] | None:
    if card is None or getattr(card, "id", None) is None:
        return None
    return {
        "id": int(card.id),
        "serial": _integer(getattr(card, "serial", None)),
        "owner": _integer(getattr(card, "playerIndex", None)),
    }


def _public_pokemon(card: Any) -> dict[str, Any] | None:
    identity = _card_identity(card)
    if identity is None:
        return None
    identity.update(
        {
            "hp": _integer(getattr(card, "hp", None), 0),
            "max_hp": _integer(getattr(card, "maxHp", None), 0),
            "appeared": bool(getattr(card, "appearThisTurn", False)),
            "energies": sorted(_integer(item) for item in (getattr(card, "energies", None) or [])),
            "energy_cards": sorted(
                (_card_identity(item) for item in _cards(getattr(card, "energyCards", None))),
                key=lambda item: (item["id"], item["serial"]),
            ),
            "tools": sorted(
                (_card_identity(item) for item in _cards(getattr(card, "tools", None))),
                key=lambda item: (item["id"], item["serial"]),
            ),
            "pre_evolution": sorted(
                (_card_identity(item) for item in _cards(getattr(card, "preEvolution", None))),
                key=lambda item: (item["id"], item["serial"]),
            ),
        }
    )
    return identity


def _public_player(player: Any) -> dict[str, Any]:
    """Serialize zones visible to both players; never serialize hand/prize IDs."""

    return {
        "active": [_public_pokemon(item) for item in (getattr(player, "active", None) or [])],
        "bench": [_public_pokemon(item) for item in (getattr(player, "bench", None) or [])],
        "discard": [_card_identity(item) for item in _cards(getattr(player, "discard", None))],
        "hand_count": _integer(getattr(player, "handCount", None), 0),
        "deck_count": _integer(getattr(player, "deckCount", None), 0),
        "prize_count": len(getattr(player, "prize", None) or []),
        "bench_max": _integer(getattr(player, "benchMax", None), 0),
        "conditions": [
            bool(getattr(player, name, False))
            for name in ("poisoned", "burned", "asleep", "paralyzed", "confused")
        ],
    }


def _public_option(option: Any) -> dict[str, Any]:
    """Selection shape for seeding, stripped of transient indices and private cards."""

    result = {
        "type": _integer(getattr(option, "type", None)),
        "number": _primitive(getattr(option, "number", None)),
        "area": _primitive(getattr(option, "area", None)),
        "player": _primitive(getattr(option, "playerIndex", None)),
        "count": _primitive(getattr(option, "count", None)),
        "target_area": _primitive(getattr(option, "inPlayArea", None)),
        "attack_id": _primitive(getattr(option, "attackId", None)),
        "card_id": _primitive(getattr(option, "cardId", None)),
        "condition": _primitive(getattr(option, "specialConditionType", None)),
    }
    return result


def _public_log(log: Any) -> dict[str, Any]:
    # Card identities are deliberately excluded because draw logs can contain a
    # private identity.  Public board/discard state already records visible cards.
    names = (
        "type",
        "playerIndex",
        "fromArea",
        "toArea",
        "attackId",
        "value",
        "putDamageCounter",
        "isRecover",
        "head",
        "result",
        "reason",
    )
    return {name: _primitive(getattr(log, name, None)) for name in names}


def public_state_digest(obs_or_dict: Any) -> str:
    """Return a stable hash containing no hand, prize, rating, or submission IDs."""

    obs = to_observation_class(obs_or_dict) if isinstance(obs_or_dict, dict) else obs_or_dict
    current = getattr(obs, "current", None)
    select = getattr(obs, "select", None)
    if current is None:
        state_payload: Any = None
    else:
        state_payload = {
            "turn": _integer(getattr(current, "turn", None), 0),
            "actor": _integer(getattr(current, "yourIndex", None), -1),
            "first": _integer(getattr(current, "firstPlayer", None), -1),
            "action_count": _integer(getattr(current, "turnActionCount", None), 0),
            "result": _integer(getattr(current, "result", None), -1),
            "supporter": bool(getattr(current, "supporterPlayed", False)),
            "stadium_played": bool(getattr(current, "stadiumPlayed", False)),
            "energy_attached": bool(getattr(current, "energyAttached", False)),
            "retreated": bool(getattr(current, "retreated", False)),
            "stadium": [_card_identity(item) for item in _cards(getattr(current, "stadium", None))],
            "players": [_public_player(player) for player in (getattr(current, "players", None) or [])],
        }
    if select is None:
        select_payload: Any = None
    else:
        public_options = [_public_option(option) for option in (getattr(select, "option", None) or [])]
        select_payload = {
            "type": _primitive(getattr(select, "type", None)),
            "context": _primitive(getattr(select, "context", None)),
            "minimum": _integer(getattr(select, "minCount", None), 0),
            "maximum": _integer(getattr(select, "maxCount", None), 0),
            "remaining_damage": _integer(getattr(select, "remainDamageCounter", None), 0),
            "remaining_energy": _integer(getattr(select, "remainEnergyCost", None), 0),
            # Option order is an engine-local implementation detail.
            "options": sorted(
                public_options,
                key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
            ),
        }
    payload = {
        "current": state_payload,
        "select": select_payload,
        "logs": [_public_log(log) for log in (getattr(obs, "logs", None) or [])],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()


def deterministic_world_seeds(obs: Any, config: ProofSearchConfig) -> tuple[int, ...]:
    digest = public_state_digest(obs)
    seeds: list[int] = []
    for index in range(config.worlds):
        material = f"{config.seed_salt}:{digest}:{index}".encode("ascii")
        seeds.append(int.from_bytes(hashlib.sha256(material).digest()[:8], "big"))
    return tuple(seeds)


def _zone_card(obs: Any, area: Any, index: Any, player_index: Any = None) -> Any:
    current = getattr(obs, "current", None)
    select = getattr(obs, "select", None)
    if current is None or area is None or index is None:
        return None
    area_value = _integer(area)
    if area_value == int(AreaType.LOOKING):
        zone = getattr(current, "looking", None) or []
    elif area_value == int(AreaType.STADIUM):
        zone = getattr(current, "stadium", None) or []
    elif area_value == int(AreaType.DECK):
        zone = getattr(select, "deck", None) or []
    else:
        owner = _integer(player_index, _integer(getattr(current, "yourIndex", None), 0))
        players = getattr(current, "players", None) or []
        if not 0 <= owner < len(players):
            return None
        player = players[owner]
        zone = {
            int(AreaType.HAND): getattr(player, "hand", None) or [],
            int(AreaType.DISCARD): getattr(player, "discard", None) or [],
            int(AreaType.ACTIVE): getattr(player, "active", None) or [],
            int(AreaType.BENCH): getattr(player, "bench", None) or [],
            int(AreaType.PRIZE): getattr(player, "prize", None) or [],
        }.get(area_value, [])
    position = _integer(index)
    return zone[position] if 0 <= position < len(zone) else None


def _selected_card(obs: Any, option: Any) -> Any:
    if _integer(getattr(option, "type", None)) == int(OptionType.PLAY):
        current = getattr(obs, "current", None)
        owner = _integer(getattr(current, "yourIndex", None), 0) if current is not None else 0
        return _zone_card(obs, AreaType.HAND, getattr(option, "index", None), owner)
    return _zone_card(
        obs,
        getattr(option, "area", None),
        getattr(option, "index", None),
        getattr(option, "playerIndex", None),
    )


def _target_pokemon(obs: Any, option: Any) -> Any:
    current = getattr(obs, "current", None)
    owner = _integer(getattr(current, "yourIndex", None), 0) if current is not None else 0
    return _zone_card(
        obs,
        getattr(option, "inPlayArea", None),
        getattr(option, "inPlayIndex", None),
        owner,
    )


def semantic_option(obs: Any, option: Any) -> dict[str, Any]:
    """Resolve one option to card/target identities instead of temporary indices."""

    option_type = _integer(getattr(option, "type", None))
    source = _selected_card(obs, option)
    target = _target_pokemon(obs, option)
    source_area = getattr(option, "area", None)
    if option_type == int(OptionType.PLAY):
        source_area = AreaType.HAND
    return {
        "type": option_type,
        "number": _primitive(getattr(option, "number", None)),
        "source_area": _primitive(source_area),
        "source": _card_identity(source),
        "owner": _primitive(getattr(option, "playerIndex", None)),
        "target_area": _primitive(getattr(option, "inPlayArea", None)),
        "target": _card_identity(target),
        "attack_id": _primitive(getattr(option, "attackId", None)),
        "card_id": _primitive(getattr(option, "cardId", None)),
        "serial": _primitive(getattr(option, "serial", None)),
        "condition": _primitive(getattr(option, "specialConditionType", None)),
    }


def semantic_action_key(obs: Any, action: Iterable[int]) -> str:
    select = obs.select
    payload = {
        "select_type": _primitive(getattr(select, "type", None)),
        "context": _primitive(getattr(select, "context", None)),
        "options": [semantic_option(obs, select.option[int(index)]) for index in action],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _validate_baseline(select: Any, action: Sequence[int]) -> tuple[int, ...]:
    normalized = tuple(int(index) for index in action)
    option_count = len(getattr(select, "option", None) or [])
    if len(set(normalized)) != len(normalized):
        raise ValueError("baseline contains duplicate option indices")
    if any(index < 0 or index >= option_count for index in normalized):
        raise ValueError("baseline option index is out of range")
    minimum = _integer(getattr(select, "minCount", None), 0)
    maximum = _integer(getattr(select, "maxCount", None), 0)
    if not minimum <= len(normalized) <= maximum:
        raise ValueError("baseline selection count is illegal")
    return normalized


def _attack_tables() -> tuple[Mapping[int, Any], Mapping[int, Any]]:
    # Lazy import avoids native card-table initialization for non-trigger states.
    from .view import attack_table, card_table

    return card_table(), attack_table()


def _can_pay(cost: Sequence[Any], attached: Sequence[Any]) -> bool:
    remaining = [_integer(item) for item in attached]
    colored = [_integer(item) for item in cost if _integer(item) != int(EnergyType.COLORLESS)]
    colorless = sum(1 for item in cost if _integer(item) == int(EnergyType.COLORLESS))

    def compatible(given: int, required: int) -> bool:
        return (
            given == required
            or given == int(EnergyType.RAINBOW)
            or (
                given == int(EnergyType.TEAM_ROCKET)
                and required in {int(EnergyType.PSYCHIC), int(EnergyType.DARKNESS)}
            )
        )

    for required in colored:
        match = next((index for index, given in enumerate(remaining) if compatible(given, required)), None)
        if match is None:
            return False
        remaining.pop(match)
    return len(remaining) >= colorless


def _readiness_level(card_id: int, energies: Sequence[Any]) -> float:
    try:
        cards, attacks = _attack_tables()
        data = cards.get(int(card_id))
        if data is None:
            return 0.0
        damage = [
            max(0, _integer(getattr(attacks.get(int(attack_id)), "damage", None), 0))
            for attack_id in (getattr(data, "attacks", None) or [])
            if attacks.get(int(attack_id)) is not None
            and _can_pay(getattr(attacks[int(attack_id)], "energies", None) or [], energies)
        ]
        return float(max(damage, default=0))
    except Exception:
        # Exact-deck fallback keeps candidate generation deterministic even if
        # metadata is unavailable.  It is intentionally narrower than guessing.
        darkness = sum(_integer(item) == int(EnergyType.DARKNESS) for item in energies)
        requirements = {
            MARNIES_IMPIDIMP: (1, 10.0),
            MARNIES_MORGREM: (2, 60.0),
            MARNIES_GRIMMSNARL_EX: (2, 180.0),
        }
        required, damage = requirements.get(int(card_id), (10**9, 0.0))
        return damage if darkness >= required else 0.0


def _pokemon_readiness(card: Any, *, card_id: int | None = None, energies: Sequence[Any] | None = None) -> float:
    if card is None:
        return 0.0
    identity = int(getattr(card, "id", 0) if card_id is None else card_id)
    attached = list(getattr(card, "energies", None) or []) if energies is None else list(energies)
    return _readiness_level(identity, attached)


def _energy_type_for_card(card: Any) -> int | None:
    if card is None or getattr(card, "id", None) is None:
        return None
    try:
        cards, _attacks = _attack_tables()
        data = cards.get(int(card.id))
        if data is not None and getattr(data, "energyType", None) is not None:
            return int(data.energyType)
    except Exception:
        pass
    # Card ID 7 is the exact Grim deck's basic Darkness Energy.
    return int(EnergyType.DARKNESS) if int(card.id) == 7 else None


def _attachment_improves_readiness(obs: Any, option: Any) -> bool:
    target = _target_pokemon(obs, option)
    source = _selected_card(obs, option)
    energy_type = _energy_type_for_card(source)
    if target is None or energy_type is None:
        return False
    before = _pokemon_readiness(target)
    after = _pokemon_readiness(target, energies=[*(getattr(target, "energies", None) or []), energy_type])
    return after > before


def _attachment_context_improves_readiness(obs: Any, option: Any) -> bool:
    target = _selected_card(obs, option)
    if target is None:
        return False
    select = obs.select
    source = getattr(select, "contextCard", None) or getattr(select, "effect", None)
    energy_type = _energy_type_for_card(source)
    if energy_type is None:
        return False
    before = _pokemon_readiness(target)
    after = _pokemon_readiness(target, energies=[*(getattr(target, "energies", None) or []), energy_type])
    return after > before


def _evolution_improves_readiness(obs: Any, option: Any) -> bool:
    target = _target_pokemon(obs, option)
    evolution = _selected_card(obs, option)
    if target is None or evolution is None or getattr(evolution, "id", None) is None:
        return False
    before = _pokemon_readiness(target)
    after = _pokemon_readiness(target, card_id=int(evolution.id))
    return after > before


def _selected_owner(obs: Any, option: Any) -> int:
    owner = getattr(option, "playerIndex", None)
    card = _selected_card(obs, option)
    if owner is None and card is not None:
        owner = getattr(card, "playerIndex", None)
    if owner is None and getattr(obs, "current", None) is not None:
        owner = obs.current.yourIndex
    return _integer(owner)


def semantic_candidates(
    obs: Any,
    baseline_action: Sequence[int],
    *,
    max_candidates: int = 8,
) -> tuple[SemanticCandidate, ...]:
    """Generate only bounded tactical alternatives, ordered by semantic identity."""

    select = getattr(obs, "select", None)
    current = getattr(obs, "current", None)
    if select is None or current is None:
        return ()
    baseline = _validate_baseline(select, baseline_action)
    baseline_key = semantic_action_key(obs, baseline)
    baseline_candidate = SemanticCandidate(baseline, baseline_key, "d842_baseline", True)
    minimum = _integer(getattr(select, "minCount", None), 0)
    maximum = _integer(getattr(select, "maxCount", None), 0)
    if not minimum <= 1 <= maximum:
        return (baseline_candidate,)

    options = list(getattr(select, "option", None) or [])
    context = _integer(getattr(select, "context", None))
    me = _integer(getattr(current, "yourIndex", None), 0)
    baseline_types = {
        _integer(getattr(options[index], "type", None)) for index in baseline
    }
    proposed: dict[str, SemanticCandidate] = {}

    def add(index: int, reason: str) -> None:
        action = (int(index),)
        key = semantic_action_key(obs, action)
        if key == baseline_key:
            return
        candidate = SemanticCandidate(action, key, reason, False)
        previous = proposed.get(key)
        if previous is None or _REASON_PRIORITY[reason] > _REASON_PRIORITY[previous.reason]:
            proposed[key] = candidate

    if context == int(SelectContext.MAIN):
        attack_indices = [
            index
            for index, option in enumerate(options)
            if _integer(getattr(option, "type", None)) == int(OptionType.ATTACK)
        ]
        if attack_indices:
            if int(OptionType.END) in baseline_types:
                reason = "attack_over_end"
            elif int(OptionType.ATTACK) not in baseline_types:
                # Only a terminal child can dominate a non-attack that leaves the
                # player in MAIN; the boundary check enforces that lethal-only use.
                reason = "lethal_attack"
            else:
                reason = "attack_choice"
            for index in attack_indices:
                add(index, reason)

        active = _cards(getattr(current.players[me], "active", None))
        bench = _cards(getattr(current.players[me], "bench", None))
        active_level = _pokemon_readiness(active[0]) if active else 0.0
        has_ready_bench = any(_pokemon_readiness(card) > active_level for card in bench)
        if has_ready_bench:
            for index, option in enumerate(options):
                if _integer(getattr(option, "type", None)) == int(OptionType.RETREAT):
                    add(index, "ready_retreat")

        for index, option in enumerate(options):
            option_type = _integer(getattr(option, "type", None))
            if option_type == int(OptionType.ATTACH) and _attachment_improves_readiness(obs, option):
                add(index, "readiness_attach")
            elif option_type == int(OptionType.EVOLVE) and _evolution_improves_readiness(obs, option):
                add(index, "readiness_evolve")

    elif context == int(SelectContext.ATTACK):
        for index, option in enumerate(options):
            if _integer(getattr(option, "type", None)) == int(OptionType.ATTACK):
                add(index, "attack_choice")

    elif context in _TARGET_CONTEXTS:
        for index, option in enumerate(options):
            owner = _selected_owner(obs, option)
            if owner == 1 - me and context in (_DAMAGE_TARGET_CONTEXTS | {int(SelectContext.SWITCH)}):
                add(index, "ko_target")
            elif owner == me and context in _PROMOTION_CONTEXTS:
                selected = _selected_card(obs, option)
                if _pokemon_readiness(selected) > 0:
                    add(index, "ready_promotion")

    elif context == int(SelectContext.ATTACH_FROM):
        for index, option in enumerate(options):
            if _attachment_context_improves_readiness(obs, option):
                add(index, "readiness_attach")

    alternatives = sorted(
        proposed.values(),
        key=lambda item: (-_REASON_PRIORITY[item.reason], item.key),
    )
    return tuple([baseline_candidate, *alternatives[: max(0, max_candidates - 1)]])


def _cards_in_play(player: Any) -> list[Any]:
    return _cards(getattr(player, "active", None)) + _cards(getattr(player, "bench", None))


def _prize_value(card: Any) -> float:
    if card is None:
        return 0.0
    try:
        cards, _attacks = _attack_tables()
        data = cards.get(int(card.id))
        if data is not None:
            return 3.0 if bool(data.megaEx) else 2.0 if bool(data.ex) else 1.0
    except Exception:
        pass
    return 2.0 if int(getattr(card, "id", 0)) == MARNIES_GRIMMSNARL_EX else 1.0


def _damage_fraction(card: Any) -> float:
    maximum = max(1.0, float(getattr(card, "maxHp", 0) or 0))
    return max(0.0, maximum - float(getattr(card, "hp", 0) or 0)) / maximum


def _readiness_score(player: Any) -> float:
    score = 0.0
    for multiplier, zone in (
        (2.0, getattr(player, "active", None)),
        (1.0, getattr(player, "bench", None)),
    ):
        for card in _cards(zone):
            damage = _pokemon_readiness(card)
            if damage > 0:
                score += multiplier * (1.0 + min(300.0, damage) / 300.0)
    return score


def _route_progress(player: Any) -> float:
    weights = {
        MARNIES_IMPIDIMP: 0.5,
        MARNIES_MORGREM: 1.0,
        MARNIES_GRIMMSNARL_EX: 2.0,
        112: 0.75,  # Munkidori
        860: 0.4,  # Snorunt
        104: 0.9,  # Froslass
    }
    return sum(weights.get(int(card.id), 0.0) for card in _cards_in_play(player))


def _boundary(root_obs: Any, child_obs: Any, root_player: int) -> tuple[str, ...]:
    current = getattr(child_obs, "current", None)
    if current is None or _integer(getattr(current, "result", None), -1) >= 0:
        return ("terminal",)
    root_turn = _integer(getattr(root_obs.current, "turn", None), -1)
    child_turn = _integer(getattr(current, "turn", None), -1)
    child_actor = _integer(getattr(current, "yourIndex", None), -1)
    if child_turn == root_turn and child_actor == root_player:
        phase = "same_turn"
    elif child_actor != root_player:
        phase = "opponent_turn"
    else:
        phase = "later_own_turn"
    select = getattr(child_obs, "select", None)
    return (
        phase,
        str(_primitive(getattr(select, "type", None))),
        str(_primitive(getattr(select, "context", None))),
    )


def public_outcome(root_obs: Any, child_obs: Any, root_player: int) -> WorldOutcome:
    """Build the audited, value-head-free lexicographic outcome vector."""

    root_state = root_obs.current
    child_state = getattr(child_obs, "current", None)
    if child_state is None:
        raise ProofSearchError("native child has no current state")
    result = _integer(getattr(child_state, "result", None), -1)
    win = 1.0 if result == root_player else 0.0
    not_loss = -1.0 if result >= 0 and result not in {root_player, 2} else 0.0
    root_me = root_state.players[root_player]
    child_me = child_state.players[root_player]
    root_opponent = root_state.players[1 - root_player]
    child_opponent = child_state.players[1 - root_player]
    prizes_taken = float(len(getattr(root_me, "prize", None) or []) - len(getattr(child_me, "prize", None) or []))

    child_opponent_serials = {
        _integer(getattr(card, "serial", None)) for card in _cards_in_play(child_opponent)
    }
    ko_value = sum(
        _prize_value(card)
        for card in _cards_in_play(root_opponent)
        if _integer(getattr(card, "serial", None)) not in child_opponent_serials
    )

    def pressure(player: Any) -> float:
        return sum(_damage_fraction(card) * _prize_value(card) for card in _cards_in_play(player))

    damage_pressure = (
        pressure(child_opponent)
        - pressure(root_opponent)
        - pressure(child_me)
        + pressure(root_me)
    )
    exposed = -sum(
        _damage_fraction(card) * _prize_value(card) for card in _cards_in_play(child_me)
    )
    critical_in_discard = sum(
        int(getattr(card, "id", -1)) in _CRITICAL_RESOURCE_IDS
        for card in _cards(getattr(child_me, "discard", None))
    )
    vector = (
        win,
        not_loss,
        prizes_taken,
        float(ko_value),
        float(damage_pressure),
        _readiness_score(child_me),
        _route_progress(child_me),
        float(exposed),
        -float(critical_in_discard),
    )
    return WorldOutcome(vector=vector, boundary=_boundary(root_obs, child_obs, root_player))


class NativeOnePromptRunner:
    """Diagnostic native evaluator with common-root sibling expansion."""

    def __init__(self, hero_deck: Sequence[int]):
        self.hero_deck = tuple(map(int, hero_deck))
        if len(self.hero_deck) != 60:
            raise ValueError("native proof search requires the exact 60-card hero deck")

    def __call__(
        self,
        obs: Any,
        candidates: tuple[SemanticCandidate, ...],
        seed: int,
        deadline: float,
        opponent_deck: Sequence[int] | None,
    ) -> Mapping[str, WorldOutcome]:
        if opponent_deck is None or len(opponent_deck) != 60:
            raise ProofSearchError("native proof search requires a registered 60-card opponent deck")
        if time.monotonic() >= deadline:
            raise ProofSearchTimeout("deadline before determinization")

        # Lazy imports keep this isolated module d842-agnostic and make the
        # injected-runner test path independent of the native search library.
        from cg.api import search_begin, search_end, search_release, search_step
        from .search import determinize_state

        kwargs = determinize_state(obs, list(self.hero_deck), list(map(int, opponent_deck)), random.Random(seed))
        if time.monotonic() >= deadline:
            raise ProofSearchTimeout("deadline after determinization")
        root = None
        cleanup_errors: list[str] = []
        outcomes: dict[str, WorldOutcome] = {}
        try:
            root = search_begin(obs, manual_coin=True, **kwargs)
            root_player = int(obs.current.yourIndex)
            for candidate in candidates:
                if time.monotonic() >= deadline:
                    raise ProofSearchTimeout("deadline during sibling expansion")
                child = None
                try:
                    child = search_step(root.searchId, list(candidate.action))
                    outcomes[candidate.key] = public_outcome(obs, child.observation, root_player)
                finally:
                    if child is not None:
                        try:
                            search_release(child.searchId)
                        except Exception as exc:  # cleanup defects invalidate the comparison
                            cleanup_errors.append(f"child_release:{type(exc).__name__}:{exc}")
        finally:
            if root is not None:
                try:
                    search_release(root.searchId)
                except Exception as exc:
                    cleanup_errors.append(f"root_release:{type(exc).__name__}:{exc}")
            try:
                search_end()
            except Exception as exc:
                cleanup_errors.append(f"search_end:{type(exc).__name__}:{exc}")
        if cleanup_errors:
            raise ProofSearchError(";".join(cleanup_errors))
        return outcomes


def _turn_is_complete(observation: Any, root_player: int, root_turn: int) -> bool:
    current = getattr(observation, "current", None)
    return (
        current is None
        or _integer(getattr(current, "result", None), -1) >= 0
        or _integer(getattr(current, "yourIndex", None), -1) != root_player
        or _integer(getattr(current, "turn", None), -1) != root_turn
    )


def _continuation_action(selector: Any, observation: Any) -> tuple[int, ...]:
    choose = getattr(selector, "choose", None)
    if callable(choose):
        raw = choose(observation)
    elif callable(selector):
        raw = selector(observation)
    else:
        raise ProofSearchError("continuation selector is neither callable nor exposes choose()")
    if raw is None:
        raise ProofSearchError("continuation selector returned None")
    return _validate_baseline(observation.select, list(raw))


class NativeCompleteTurnRunner:
    """Advance every common-root sibling through the root player's whole turn.

    The continuation factory is called once per candidate branch, including a
    branch whose root action immediately ends the turn.  A selector may maintain
    state inside one branch, but no selector instance is ever shared with another
    candidate or world.
    """

    def __init__(
        self,
        hero_deck: Sequence[int],
        continuation_selector_factory: ContinuationSelectorFactory,
        *,
        max_steps_per_branch: int = 48,
        backend: NativeSearchBackend | None = None,
        determinizer: Determinizer | None = None,
    ) -> None:
        self.hero_deck = tuple(map(int, hero_deck))
        if len(self.hero_deck) != 60:
            raise ValueError("native proof search requires the exact 60-card hero deck")
        if not callable(continuation_selector_factory):
            raise ValueError("complete-turn proof search requires a continuation selector factory")
        if max_steps_per_branch <= 0:
            raise ValueError("max_steps_per_branch must be positive")
        self.continuation_selector_factory = continuation_selector_factory
        self.max_steps_per_branch = int(max_steps_per_branch)
        self.backend = backend or _CgNativeSearchBackend()
        self.determinizer = determinizer or _default_determinizer

    @staticmethod
    def _check_deadline(deadline: float, label: str) -> None:
        if time.monotonic() >= deadline:
            raise ProofSearchTimeout(f"deadline {label}")

    def __call__(
        self,
        obs: Any,
        candidates: tuple[SemanticCandidate, ...],
        seed: int,
        deadline: float,
        opponent_deck: Sequence[int] | None,
    ) -> Mapping[str, WorldOutcome]:
        if opponent_deck is None or len(opponent_deck) != 60:
            raise ProofSearchError("native proof search requires a registered 60-card opponent deck")
        self._check_deadline(deadline, "before determinization")
        kwargs = self.determinizer(
            obs,
            list(self.hero_deck),
            list(map(int, opponent_deck)),
            random.Random(seed),
        )
        self._check_deadline(deadline, "after determinization")

        created: dict[int, Any] = {}
        release_attempted: set[int] = set()
        cleanup_errors: list[str] = []
        outcomes: dict[str, WorldOutcome] = {}
        primary_error: Exception | None = None

        def remember(state: Any) -> Any:
            if state is None or getattr(state, "searchId", None) is None:
                raise ProofSearchError("native backend returned a state without searchId")
            search_id = int(state.searchId)
            if search_id in created and created[search_id] is not state:
                raise ProofSearchError(f"native backend reused live searchId {search_id}")
            created[search_id] = state
            return state

        def release_state(state: Any) -> None:
            if state is None or getattr(state, "searchId", None) is None:
                return
            search_id = int(state.searchId)
            if search_id in release_attempted:
                return
            release_attempted.add(search_id)
            try:
                self.backend.release(search_id)
            except Exception as exc:
                cleanup_errors.append(f"release[{search_id}]:{type(exc).__name__}:{exc}")

        root = None
        try:
            root = remember(self.backend.begin(obs, kwargs))
            root_player = int(obs.current.yourIndex)
            root_turn = int(obs.current.turn)
            for candidate in candidates:
                self._check_deadline(deadline, f"before branch {candidate.token}")
                # The factory boundary is deliberate: a stateful policy wrapper
                # can never leak latches or cached selections across siblings.
                selector = self.continuation_selector_factory()
                if selector is None:
                    raise ProofSearchError("continuation selector factory returned None")
                branch = None
                try:
                    branch = remember(self.backend.step(root.searchId, candidate.action))
                    steps = 1
                    while not _turn_is_complete(branch.observation, root_player, root_turn):
                        if steps >= self.max_steps_per_branch:
                            raise ProofSearchError(
                                f"complete-turn truncation for {candidate.token} at {steps} steps"
                            )
                        if getattr(branch.observation, "select", None) is None:
                            raise ProofSearchError(
                                f"incomplete turn for {candidate.token} has no selection"
                            )
                        self._check_deadline(deadline, f"before continuation {candidate.token}")
                        action = _continuation_action(selector, branch.observation)
                        self._check_deadline(deadline, f"after continuation {candidate.token}")
                        child = remember(self.backend.step(branch.searchId, action))
                        release_state(branch)
                        branch = child
                        steps += 1
                    raw_outcome = public_outcome(obs, branch.observation, root_player)
                    boundary = (
                        ("terminal",)
                        if raw_outcome.boundary == ("terminal",)
                        else ("complete_turn",)
                    )
                    outcomes[candidate.key] = WorldOutcome(raw_outcome.vector, boundary)
                finally:
                    release_state(branch)
            if set(outcomes) != {candidate.key for candidate in candidates}:
                raise ProofSearchError("complete-turn runner produced unequal candidate coverage")
        except Exception as exc:
            primary_error = exc
        finally:
            # Reverse creation order releases descendants before the common root.
            for state in reversed(tuple(created.values())):
                release_state(state)
            try:
                self.backend.end()
            except Exception as exc:
                cleanup_errors.append(f"search_end:{type(exc).__name__}:{exc}")

        if cleanup_errors:
            prefix = (
                f"{type(primary_error).__name__}:{primary_error};"
                if primary_error is not None
                else ""
            )
            raise ProofSearchError(prefix + ";".join(cleanup_errors))
        if primary_error is not None:
            raise primary_error
        return outcomes


def _validate_outcome(outcome: Any) -> WorldOutcome:
    if not isinstance(outcome, WorldOutcome):
        raise ProofSearchError("runner returned a non-WorldOutcome value")
    if not outcome.boundary:
        raise ProofSearchError("runner returned an empty boundary")
    if not outcome.vector or len(outcome.vector) != len(OUTCOME_FIELDS):
        raise ProofSearchError(
            f"runner outcome has {len(outcome.vector)} fields; expected {len(OUTCOME_FIELDS)}"
        )
    normalized = tuple(float(value) for value in outcome.vector)
    if not all(math.isfinite(value) for value in normalized):
        raise ProofSearchError("runner outcome contains a non-finite value")
    return WorldOutcome(normalized, tuple(map(str, outcome.boundary)))


def _compatible_boundaries(outcomes: Iterable[WorldOutcome]) -> bool:
    # A terminal node is absorbing and needs no further prompt to reach the
    # sibling horizon.  All non-terminal siblings must name exactly one horizon.
    nonterminal = {
        outcome.boundary for outcome in outcomes if outcome.boundary != ("terminal",)
    }
    return len(nonterminal) <= 1


def _trigger_name(candidates: Sequence[SemanticCandidate]) -> str | None:
    reasons = sorted(
        {item.reason for item in candidates if not item.is_baseline},
        key=lambda reason: (-_REASON_PRIORITY.get(reason, 0), reason),
    )
    return "+".join(reasons) if reasons else None


class SelectiveProofSearch:
    """Prove a tactical override or return the exact supplied baseline action."""

    def __init__(
        self,
        hero_deck: Sequence[int] | None = None,
        config: ProofSearchConfig | None = None,
        world_runner: WorldRunner | None = None,
        *,
        native_mode: str = "one_prompt",
        continuation_selector_factory: ContinuationSelectorFactory | None = None,
        max_turn_steps: int = 48,
        native_backend: NativeSearchBackend | None = None,
        determinizer: Determinizer | None = None,
    ) -> None:
        self.config = config or ProofSearchConfig()
        if native_mode not in {"one_prompt", "complete_turn"}:
            raise ValueError(f"unsupported native proof-search mode: {native_mode!r}")
        if world_runner is None:
            if hero_deck is None:
                raise ValueError("hero_deck is required when using the native runner")
            if native_mode == "one_prompt":
                self.world_runner = NativeOnePromptRunner(hero_deck)
            else:
                if continuation_selector_factory is None:
                    raise ValueError(
                        "complete_turn mode requires continuation_selector_factory"
                    )
                self.world_runner = NativeCompleteTurnRunner(
                    hero_deck,
                    continuation_selector_factory,
                    max_steps_per_branch=max_turn_steps,
                    backend=native_backend,
                    determinizer=determinizer,
                )
        else:
            self.world_runner = world_runner

    def choose(
        self,
        obs_or_dict: Any,
        baseline_action: Sequence[int],
        opponent_deck: Sequence[int] | None = None,
    ) -> ProofSearchResult:
        """Return a proved sibling action, otherwise fall through byte-for-byte."""

        baseline = list(map(int, baseline_action))
        started = time.monotonic()
        deadline = started + self.config.timeout_seconds
        try:
            obs = to_observation_class(obs_or_dict) if isinstance(obs_or_dict, dict) else obs_or_dict
            digest = public_state_digest(obs)
            candidates = semantic_candidates(
                obs,
                baseline,
                max_candidates=self.config.max_candidates,
            )
        except Exception as exc:
            return ProofSearchResult(
                "abstained",
                baseline,
                None,
                "candidate_generation_error",
                errors=(f"{type(exc).__name__}:{exc}",),
            )
        if len(candidates) <= 1:
            return ProofSearchResult(
                "not_triggered",
                baseline,
                None,
                "no_tactical_alternative",
                public_state_digest=digest,
                candidate_tokens=tuple(item.token for item in candidates),
            )

        expected = {candidate.key for candidate in candidates}
        trigger = _trigger_name(candidates)
        scores: dict[str, list[tuple[float, ...]]] = {key: [] for key in expected}
        coverage = {candidate.token: 0 for candidate in candidates}
        errors: list[str] = []
        try:
            seeds = deterministic_world_seeds(obs, self.config)
            for world_index, seed in enumerate(seeds):
                if time.monotonic() >= deadline:
                    raise ProofSearchTimeout(f"deadline before world {world_index}")
                raw = self.world_runner(obs, candidates, seed, deadline, opponent_deck)
                if time.monotonic() >= deadline:
                    raise ProofSearchTimeout(f"deadline after world {world_index}")
                if set(raw) != expected:
                    missing = expected - set(raw)
                    extra = set(raw) - expected
                    raise ProofSearchError(
                        f"unequal coverage in world {world_index}: missing={len(missing)} extra={len(extra)}"
                    )
                outcomes = {key: _validate_outcome(raw[key]) for key in expected}
                if not _compatible_boundaries(outcomes.values()):
                    raise ProofSearchError(f"unequal semantic boundaries in world {world_index}")
                for candidate in candidates:
                    scores[candidate.key].append(outcomes[candidate.key].vector)
                    coverage[candidate.token] += 1
        except (ProofSearchTimeout, TimeoutError) as exc:
            errors.append(f"{type(exc).__name__}:{exc}")
            return ProofSearchResult(
                "abstained",
                baseline,
                trigger,
                "timeout",
                digest,
                coverage,
                candidate_tokens=tuple(item.token for item in candidates),
                errors=tuple(errors),
            )
        except Exception as exc:
            errors.append(f"{type(exc).__name__}:{exc}")
            reason = "unequal_coverage_or_boundary" if isinstance(exc, ProofSearchError) else "world_error"
            return ProofSearchResult(
                "abstained",
                baseline,
                trigger,
                reason,
                digest,
                coverage,
                candidate_tokens=tuple(item.token for item in candidates),
                errors=tuple(errors),
            )

        if any(count != self.config.worlds for count in coverage.values()):
            return ProofSearchResult(
                "abstained",
                baseline,
                trigger,
                "unequal_coverage_or_boundary",
                digest,
                coverage,
                candidate_tokens=tuple(item.token for item in candidates),
            )

        baseline_candidate = next(item for item in candidates if item.is_baseline)
        baseline_vectors = scores[baseline_candidate.key]
        qualified: list[tuple[SemanticCandidate, int, tuple[tuple[float, ...], ...]]] = []
        best_noninferior_strict = 0
        for candidate in candidates:
            if candidate.is_baseline:
                continue
            comparisons = [
                (candidate_vector > baseline_vector) - (candidate_vector < baseline_vector)
                for candidate_vector, baseline_vector in zip(scores[candidate.key], baseline_vectors)
            ]
            if all(comparison >= 0 for comparison in comparisons):
                strict = sum(comparison > 0 for comparison in comparisons)
                best_noninferior_strict = max(best_noninferior_strict, strict)
                if strict >= self.config.min_strict_worlds:
                    # Lexicographic maximin without converting fields to a scalar.
                    robust_profile = tuple(sorted(scores[candidate.key]))
                    qualified.append((candidate, strict, robust_profile))

        tokens = tuple(item.token for item in candidates)
        if not qualified:
            reason = (
                "insufficient_strict_worlds"
                if best_noninferior_strict > 0
                else "no_worldwise_dominance"
            )
            return ProofSearchResult(
                "baseline",
                baseline,
                trigger,
                reason,
                digest,
                coverage,
                strict_worlds=best_noninferior_strict,
                candidate_tokens=tokens,
            )

        best_profile = max((item[2], item[1]) for item in qualified)
        winners = [item for item in qualified if (item[2], item[1]) == best_profile]
        if len(winners) != 1:
            return ProofSearchResult(
                "baseline",
                baseline,
                trigger,
                "ambiguous_proof",
                digest,
                coverage,
                strict_worlds=max(item[1] for item in winners),
                candidate_tokens=tokens,
            )
        selected, strict_worlds, _profile = winners[0]
        return ProofSearchResult(
            "proved",
            list(selected.action),
            trigger,
            "worldwise_lexicographic_dominance",
            digest,
            coverage,
            strict_worlds=strict_worlds,
            candidate_tokens=tokens,
        )
