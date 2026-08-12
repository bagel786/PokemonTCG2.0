"""FESTIVAL-D1: narrow, fail-closed, completed-turn proof search.

D1 is an overlay around the frozen FESTIVAL-D0 action.  It searches only
deterministic MAIN-action siblings, completes the current global turn, and
admits an alternative only when public lexicographic outcomes dominate D0 in
every sampled hidden world.  Prompt indices never cross a native-search
boundary: root selections are captured and resolved by semantic card identity.

The native engine exposes a process-global RNG to sibling ``SearchStep`` calls.
Consequently this implementation refuses to certify any branch which touches a
shuffle, coin, hidden draw, deck-search, or top-deck effect before the boundary.
The deadline is necessarily a soft wall around synchronous native calls; an
over-budget return is discarded, never promoted.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import random
import time
import zlib
from collections import Counter
from dataclasses import dataclass, replace
from enum import Enum
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from cg.api import AreaType, OptionType, SelectContext, SelectType

from ptcg_ai.safety import sanitize_selection

from .cards import (
    APPLIN_DRAGON,
    APPLIN_GRASS,
    BLACK_BELT,
    BOSS,
    BRAVE_BANGLE,
    BROCK,
    BUG_SET,
    DIPPLIN,
    DO_THE_WAVE,
    EXACT_DECK,
    FESTIVAL,
    GRASS_ENERGY,
    GROOKEY,
    HILDA,
    LILLIE,
    NIGHT_STRETCHER,
    POFFIN,
    POKE_PAD,
    QUICK_SIGN,
    SACRED_ASH,
    SHAYMIN,
    THWACKEY,
    UNFAIR_STAMP,
    VOLBEAT,
)
from .damage import project_do_the_wave
from .snapshot import PlanMemory, PlanSnapshot


METRIC_FIELDS = (
    "terminal_win",
    "prizes_taken_this_turn",
    "productive_attacks_completed",
    "opponent_central_attacker_ko",
    "first_attack_ko_unlocked_second_target",
    "current_attacker_ready",
    "replacement_attacker_ready",
    "festival_active",
    "usable_thwackey_count",
    "end_of_turn_do_the_wave_output",
    "remaining_core_attacker_resources",
    "remaining_core_tutor_resources",
    "avoid_exposed_fragile_bench",
)

# Merely ending with Festival in play or another Thwackey available is setup,
# not a completed-turn tactical gain.  Earlier versions admitted those ties and
# mostly overrode END/ATTACH/PLAY with Festival; intervention games then won
# materially less often than D0-only games.  Require an actual prize, attack,
# KO, or attacker-readiness improvement before setup/resource fields may break
# a tie.  This remains opponent-agnostic and is derived solely from the public
# completed-turn state.
LOAD_BEARING_INDICES = frozenset(range(5))
DISRUPTION_OVERRIDE_CARDS = frozenset({BOSS, BLACK_BELT})

_RANDOM_OR_DECK_TOUCH_CARDS = frozenset(
    {
        UNFAIR_STAMP,
        POFFIN,
        BUG_SET,
        SACRED_ASH,
        POKE_PAD,
        BROCK,
        HILDA,
        LILLIE,
        THWACKEY,
    }
)
_CORE_ATTACKERS = frozenset(
    {GRASS_ENERGY, APPLIN_DRAGON, APPLIN_GRASS, DIPPLIN, GROOKEY, THWACKEY}
)
_CORE_TUTORS = frozenset(
    {POFFIN, BUG_SET, POKE_PAD, BROCK, HILDA, LILLIE, THWACKEY, NIGHT_STRETCHER}
)
_SOURCE_TYPES = frozenset(
    {
        int(OptionType.CARD),
        int(OptionType.PLAY),
        int(OptionType.ATTACH),
        int(OptionType.EVOLVE),
        int(OptionType.ABILITY),
        int(OptionType.DISCARD),
        int(OptionType.TOOL_CARD),
        int(OptionType.ENERGY_CARD),
        int(OptionType.ENERGY),
    }
)
_ATTACHED_TYPES = frozenset(
    {int(OptionType.TOOL_CARD), int(OptionType.ENERGY_CARD), int(OptionType.ENERGY)}
)
_TARGET_TYPES = frozenset({int(OptionType.ATTACH), int(OptionType.EVOLVE)})


class D1Error(RuntimeError):
    """The proposed comparison cannot be certified."""


class D1Timeout(D1Error):
    """A bounded search exceeded its synchronous soft deadline."""


class SemanticRemapError(D1Error):
    """A prompt-local action could not be represented or remapped safely."""


class IncompleteLeafError(D1Error):
    """A branch did not reach terminal or a new global turn."""


@dataclass(frozen=True)
class D1Config:
    worlds: int = 2
    max_candidates: int = 4
    max_steps_per_path: int = 48
    max_nodes_per_decision: int = 512
    max_native_calls_per_decision: int = 544
    soft_timeout_seconds: float = 0.65
    hard_timeout_seconds: float = 1.50
    max_searches_per_game: int = 32
    max_opponent_promotions: int = 5
    max_planning_branch_points: int = 3
    max_plan_candidates: int = 3
    seed_salt: str = "festival-d1-public-v1"

    def __post_init__(self) -> None:
        if not 2 <= int(self.worlds) <= 4:
            raise ValueError("FESTIVAL-D1 requires two to four worlds")
        if not 2 <= int(self.max_candidates) <= 4:
            raise ValueError("FESTIVAL-D1 requires two to four root candidates")
        if min(
            int(self.max_steps_per_path),
            int(self.max_nodes_per_decision),
            int(self.max_native_calls_per_decision),
            int(self.max_searches_per_game),
            int(self.max_planning_branch_points),
            int(self.max_plan_candidates),
        ) <= 0:
            raise ValueError("D1 bounds must be positive")
        if int(self.max_plan_candidates) > int(self.max_candidates):
            raise ValueError("D1 plan candidates cannot exceed root candidates")
        if not (
            math.isfinite(self.soft_timeout_seconds)
            and math.isfinite(self.hard_timeout_seconds)
            and 0 < self.soft_timeout_seconds <= self.hard_timeout_seconds <= 2.0
        ):
            raise ValueError("D1 deadlines must satisfy 0 < soft <= hard <= 2 seconds")


def _integer(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _primitive(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return int(value.value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return str(value)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _cards(zone: Any) -> list[Any]:
    return [card for card in (zone or []) if card is not None]


def _card_identity(card: Any) -> tuple[int, int, int] | None:
    if card is None or getattr(card, "id", None) is None or getattr(card, "serial", None) is None:
        return None
    return (
        int(card.id),
        int(card.serial),
        _integer(getattr(card, "playerIndex", None)),
    )


def _lineage(card: Any) -> int | None:
    if card is None:
        return None
    pre = _cards(getattr(card, "preEvolution", None))
    identity = _card_identity(pre[0] if pre else card)
    return identity[1] if identity is not None else None


def _zone_card(obs: Any, area: Any, index: Any, player_index: Any = None) -> Any | None:
    state = getattr(obs, "current", None)
    select = getattr(obs, "select", None)
    if state is None or area is None or index is None:
        return None
    area_value = _integer(area)
    position = _integer(index)
    if area_value == int(AreaType.LOOKING):
        zone = getattr(state, "looking", None) or []
    elif area_value == int(AreaType.STADIUM):
        zone = getattr(state, "stadium", None) or []
    elif area_value == int(AreaType.DECK):
        zone = getattr(select, "deck", None) or []
    else:
        owner = _integer(player_index, _integer(getattr(state, "yourIndex", None), 0))
        players = list(getattr(state, "players", None) or [])
        if not 0 <= owner < len(players):
            return None
        player = players[owner]
        zones = {
            int(AreaType.HAND): getattr(player, "hand", None) or [],
            int(AreaType.DISCARD): getattr(player, "discard", None) or [],
            int(AreaType.ACTIVE): getattr(player, "active", None) or [],
            int(AreaType.BENCH): getattr(player, "bench", None) or [],
            int(AreaType.PRIZE): getattr(player, "prize", None) or [],
        }
        zone = zones.get(area_value, [])
    return zone[position] if 0 <= position < len(zone) else None


def _option_source(obs: Any, option: Any) -> Any | None:
    option_type = _integer(getattr(option, "type", None))
    area = getattr(option, "area", None)
    owner = getattr(option, "playerIndex", None)
    if option_type == int(OptionType.PLAY):
        area = AreaType.HAND
        owner = getattr(obs.current, "yourIndex", None)
    return _zone_card(obs, area, getattr(option, "index", None), owner)


def _option_target(obs: Any, option: Any) -> Any | None:
    return _zone_card(
        obs,
        getattr(option, "inPlayArea", None),
        getattr(option, "inPlayIndex", None),
        getattr(obs.current, "yourIndex", None),
    )


@dataclass(frozen=True)
class SemanticOption:
    option_type: int
    payload_json: str


@dataclass(frozen=True)
class SemanticSelection:
    select_type: int
    context: int
    minimum: int
    maximum: int
    context_card: tuple[int, int, int] | None
    effect: tuple[int, int, int] | None
    options: tuple[SemanticOption, ...]

    @property
    def key(self) -> str:
        payload = (
            self.select_type,
            self.context,
            self.minimum,
            self.maximum,
            self.context_card,
            self.effect,
            tuple((item.option_type, item.payload_json) for item in self.options),
        )
        return hashlib.sha256(repr(payload).encode("utf-8")).hexdigest().upper()


def semantic_option(obs: Any, option: Any) -> SemanticOption:
    """Capture every intrinsic option field and visible source/target identity."""

    option_type = _integer(getattr(option, "type", None))
    payload: dict[str, Any] = {}
    for source_name, destination_name in (
        ("number", "number"),
        ("count", "count"),
        ("attackId", "attack_id"),
        ("cardId", "card_id"),
        ("serial", "serial"),
        ("specialConditionType", "special_condition_type"),
    ):
        value = getattr(option, source_name, None)
        if value is not None:
            payload[destination_name] = _primitive(value)

    raw_area = getattr(option, "area", None)
    raw_owner = getattr(option, "playerIndex", None)
    raw_index = getattr(option, "index", None)
    if option_type == int(OptionType.PLAY):
        raw_area = AreaType.HAND
        raw_owner = getattr(obs.current, "yourIndex", None)
    if option_type in _SOURCE_TYPES:
        if raw_area is not None:
            payload["area"] = int(raw_area)
        if raw_owner is not None:
            payload["player_index"] = int(raw_owner)
        if raw_area is not None and int(raw_area) == int(AreaType.PLAYER):
            payload["selected_player"] = int(raw_owner if raw_owner is not None else raw_index)
        else:
            source = _zone_card(obs, raw_area, raw_index, raw_owner)
            identity = _card_identity(source)
            if identity is None:
                # Face-down prizes are semantically interchangeable.  Retaining
                # their prompt index would be hidden-information leakage.
                if int(raw_area or -1) == int(AreaType.PRIZE):
                    payload["opaque_zone"] = int(AreaType.PRIZE)
                else:
                    raise SemanticRemapError(
                        f"cannot resolve source type={option_type} area={raw_area}"
                    )
            else:
                payload["source"] = identity
                if option_type in _ATTACHED_TYPES:
                    attached_name = (
                        "tools" if option_type == int(OptionType.TOOL_CARD) else "energyCards"
                    )
                    sub_name = (
                        "toolIndex" if option_type == int(OptionType.TOOL_CARD) else "energyIndex"
                    )
                    sub_index = _integer(getattr(option, sub_name, None))
                    attached = getattr(source, attached_name, None) or []
                    if not 0 <= sub_index < len(attached):
                        raise SemanticRemapError("cannot resolve attached source")
                    attached_identity = _card_identity(attached[sub_index])
                    if attached_identity is None:
                        raise SemanticRemapError("attached source has no public identity")
                    payload["attached"] = attached_identity
    elif raw_index is not None:
        raise SemanticRemapError(f"unsupported positional option type={option_type}")

    if option_type in _TARGET_TYPES:
        target_area = getattr(option, "inPlayArea", None)
        target = _option_target(obs, option)
        identity = _card_identity(target)
        if target_area is None or identity is None:
            raise SemanticRemapError("cannot resolve attachment/evolution target")
        payload["target_area"] = int(target_area)
        payload["target"] = identity
        payload["target_lineage"] = _lineage(target)
    return SemanticOption(option_type, _canonical(payload))


def capture_semantic_selection(obs: Any, action: Sequence[int]) -> SemanticSelection:
    select = getattr(obs, "select", None)
    if getattr(obs, "current", None) is None or select is None:
        raise SemanticRemapError("semantic selection requires a live prompt")
    indices = tuple(map(int, action))
    minimum, maximum = int(select.minCount), int(select.maxCount)
    if len(indices) != len(set(indices)) or not minimum <= len(indices) <= maximum:
        raise SemanticRemapError("selection count is invalid")
    if any(index < 0 or index >= len(select.option) for index in indices):
        raise SemanticRemapError("selection index is invalid")
    return SemanticSelection(
        select_type=int(select.type),
        context=int(select.context),
        minimum=minimum,
        maximum=maximum,
        context_card=_card_identity(getattr(select, "contextCard", None)),
        effect=_card_identity(getattr(select, "effect", None)),
        options=tuple(semantic_option(obs, select.option[index]) for index in indices),
    )


def resolve_semantic_selection(obs: Any, selection: SemanticSelection) -> list[int] | None:
    select = getattr(obs, "select", None)
    if getattr(obs, "current", None) is None or select is None:
        return None
    if (
        int(select.type) != selection.select_type
        or int(select.context) != selection.context
        or int(select.minCount) != selection.minimum
        or int(select.maxCount) != selection.maximum
        or _card_identity(getattr(select, "contextCard", None)) != selection.context_card
        or _card_identity(getattr(select, "effect", None)) != selection.effect
    ):
        return None
    available: dict[SemanticOption, list[int]] = {}
    for index, option in enumerate(select.option):
        try:
            available.setdefault(semantic_option(obs, option), []).append(index)
        except SemanticRemapError:
            continue
    resolved: list[int] = []
    for key in selection.options:
        matches = available.get(key, [])
        if not matches:
            return None
        resolved.append(matches.pop(0))
    return resolved


@dataclass(frozen=True)
class RootCandidate:
    original_action: tuple[int, ...]
    semantic: SemanticSelection
    category: str
    is_baseline: bool = False

    @property
    def key(self) -> str:
        return self.semantic.key


def _option_card_id(obs: Any, option: Any) -> int:
    source = _option_source(obs, option)
    return _integer(getattr(source, "id", None))


def _candidate_category(obs: Any, option: Any) -> tuple[str, tuple[int, ...]] | None:
    option_type = _integer(getattr(option, "type", None))
    card_id = _option_card_id(obs, option)
    target = _option_target(obs, option)
    target_id = _integer(getattr(target, "id", None))
    target_is_active = _integer(getattr(option, "inPlayArea", None)) == int(AreaType.ACTIVE)
    attack_id = _integer(getattr(option, "attackId", None))

    if option_type == int(OptionType.ATTACK):
        return "prize", (1000, int(attack_id == DO_THE_WAVE), -attack_id)
    if option_type == int(OptionType.PLAY) and card_id in {BOSS, BLACK_BELT}:
        return "prize", (900, int(card_id == BOSS), -card_id)
    if option_type == int(OptionType.ATTACH) and card_id == BRAVE_BANGLE:
        return "prize", (850, int(target_id == DIPPLIN), int(target_is_active))
    if option_type == int(OptionType.PLAY) and card_id in {
        APPLIN_DRAGON,
        APPLIN_GRASS,
        GROOKEY,
        SHAYMIN,
        VOLBEAT,
    }:
        # A Basic is a deterministic +20 Do-the-Wave modifier as well as a
        # replacement/engine resource.  When an attack is already legal it is
        # a genuine completed-turn prize candidate, not mere board cosmetics.
        attack_available = any(
            _integer(getattr(candidate, "type", None)) == int(OptionType.ATTACK)
            and _integer(getattr(candidate, "attackId", None)) == DO_THE_WAVE
            for candidate in (getattr(obs.select, "option", None) or [])
        )
        category = "prize" if attack_available else "replacement"
        return category, (825, int(card_id in {APPLIN_DRAGON, APPLIN_GRASS}), -card_id)
    if option_type == int(OptionType.PLAY) and card_id == FESTIVAL:
        return "enable", (900, 0, 0)
    if option_type == int(OptionType.RETREAT):
        return "enable", (850, 0, 0)
    if option_type == int(OptionType.EVOLVE):
        category = "enable" if target_is_active else "replacement"
        return category, (800, int(card_id == DIPPLIN), int(target_id in {APPLIN_GRASS, APPLIN_DRAGON}))
    if option_type == int(OptionType.ATTACH) and card_id == GRASS_ENERGY:
        category = "enable" if target_is_active else "replacement"
        return category, (750, int(target_id == DIPPLIN), int(target_is_active))
    if option_type == int(OptionType.ABILITY) and card_id == THWACKEY:
        return "replacement", (700, 0, 0)
    if option_type == int(OptionType.PLAY) and card_id in {
        NIGHT_STRETCHER,
        POFFIN,
        POKE_PAD,
        BUG_SET,
        SACRED_ASH,
        BROCK,
        HILDA,
        LILLIE,
    }:
        # Opening Supporter-vs-Quick-Sign and draw-vs-tutor sequencing are
        # precisely the high-leverage lines completed-turn search should
        # adjudicate.  The score is only a bounded candidate ordering; engine
        # outcomes still decide.  Prefer broad multi-piece Supporters when the
        # four-slot root budget cannot include every legal search card.
        priority = {
            HILDA: 790,
            LILLIE: 780,
            BROCK: 770,
            NIGHT_STRETCHER: 740,
            POKE_PAD: 720,
            BUG_SET: 710,
            POFFIN: 700,
            SACRED_ASH: 690,
        }.get(card_id, 600)
        return "replacement", (priority, -card_id, 0)
    if option_type == int(OptionType.END):
        return "end", (0, 0, 0)
    return None


def generate_root_candidates(obs: Any, baseline: Sequence[int], limit: int = 4) -> tuple[RootCandidate, ...]:
    """Return D0 plus at most one semantic macro root per declared category."""

    baseline_semantic = capture_semantic_selection(obs, baseline)
    baseline_candidate = RootCandidate(tuple(map(int, baseline)), baseline_semantic, "baseline", True)
    ranked: dict[str, list[tuple[tuple[int, ...], RootCandidate]]] = {}
    for index, option in enumerate(getattr(obs.select, "option", None) or []):
        classification = _candidate_category(obs, option)
        if classification is None:
            continue
        category, score = classification
        if category == "end":
            continue
        action = (index,)
        semantic = capture_semantic_selection(obs, action)
        if semantic.key == baseline_semantic.key:
            continue
        candidate = RootCandidate(action, semantic, category)
        tie_key = score + tuple(-ord(ch) for ch in semantic.key[:8])
        ranked.setdefault(category, []).append((tie_key, candidate))
    for rows in ranked.values():
        rows.sort(key=lambda item: item[0], reverse=True)

    alternatives = [
        ranked[name][0][1]
        for name in ("enable", "prize", "replacement")
        if ranked.get(name)
    ]
    # Use otherwise idle root slots for a second semantically distinct option
    # in the same macro category.  This is crucial for Hilda-vs-Lillie and
    # attachment/evolution target choices; the previous category compression
    # silently made those decisions unsearchable.
    leftovers = sorted(
        (
            item
            for rows in ranked.values()
            for item in rows[1:]
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    alternatives.extend(candidate for _score, candidate in leftovers)
    unique: list[RootCandidate] = [baseline_candidate]
    seen = {baseline_candidate.key}
    for candidate in alternatives:
        if candidate.key not in seen:
            unique.append(candidate)
            seen.add(candidate.key)
        if len(unique) >= min(4, int(limit)):
            break
    return tuple(unique)


def _public_state_digest(obs: Any) -> str:
    state = obs.current
    players = list(getattr(state, "players", None) or [])
    viewer = _integer(getattr(state, "yourIndex", None))

    def pokemon(card: Any) -> Any:
        if card is None:
            return None
        return {
            "identity": _card_identity(card),
            "lineage": _lineage(card),
            "hp": _integer(getattr(card, "hp", None), 0),
            "energies": sorted(_integer(value) for value in (getattr(card, "energies", None) or [])),
            "tools": sorted(filter(None, (_card_identity(x) for x in _cards(getattr(card, "tools", None))))),
        }

    payload_players = []
    for index, player in enumerate(players):
        payload_players.append(
            {
                "active": [pokemon(card) for card in (getattr(player, "active", None) or [])],
                "bench": [pokemon(card) for card in (getattr(player, "bench", None) or [])],
                "discard": sorted(filter(None, (_card_identity(x) for x in _cards(getattr(player, "discard", None))))),
                "hand_count": _integer(getattr(player, "handCount", None), 0),
                "hand": (
                    sorted(filter(None, (_card_identity(x) for x in _cards(getattr(player, "hand", None)))))
                    if index == viewer
                    else None
                ),
                "deck_count": _integer(getattr(player, "deckCount", None), 0),
                "prize_count": len(getattr(player, "prize", None) or []),
            }
        )
    payload = {
        "turn": _integer(getattr(state, "turn", None), 0),
        "viewer": viewer,
        "first": _integer(getattr(state, "firstPlayer", None)),
        "action_count": _integer(getattr(state, "turnActionCount", None), 0),
        "players": payload_players,
        "stadium": sorted(filter(None, (_card_identity(x) for x in _cards(getattr(state, "stadium", None))))),
        "select": {
            "type": _integer(getattr(obs.select, "type", None)),
            "context": _integer(getattr(obs.select, "context", None)),
            "min": _integer(getattr(obs.select, "minCount", None)),
            "max": _integer(getattr(obs.select, "maxCount", None)),
            "options": sorted(
                (
                    _integer(getattr(option, "type", None)),
                    _integer(getattr(option, "attackId", None)),
                    _integer(getattr(option, "cardId", None)),
                    _integer(getattr(option, "inPlayArea", None)),
                )
                for option in (getattr(obs.select, "option", None) or [])
            ),
        },
    }
    return hashlib.sha256(_canonical(payload).encode("ascii")).hexdigest().upper()


def _pokemon_zone_ids(zone: Any) -> list[int]:
    result: list[int] = []
    for pokemon in _cards(zone):
        result.append(int(pokemon.id))
        result.extend(int(card.id) for card in _cards(getattr(pokemon, "energyCards", None)))
        result.extend(int(card.id) for card in _cards(getattr(pokemon, "tools", None)))
        result.extend(int(card.id) for card in _cards(getattr(pokemon, "preEvolution", None)))
    return result


def _visible_ids(state: Any, player_index: int, *, include_hand: bool) -> list[int]:
    player = state.players[player_index]
    result = _pokemon_zone_ids(getattr(player, "active", None))
    result.extend(_pokemon_zone_ids(getattr(player, "bench", None)))
    result.extend(int(card.id) for card in _cards(getattr(player, "discard", None)))
    result.extend(
        int(card.id)
        for card in _cards(getattr(state, "stadium", None))
        if _integer(getattr(card, "playerIndex", None)) == player_index
    )
    if include_hand:
        result.extend(int(card.id) for card in _cards(getattr(player, "hand", None)))
    return result


def _known_prize_ids(player: Any) -> list[int]:
    return [int(card.id) for card in _cards(getattr(player, "prize", None))]


def _subtract(full_deck: Sequence[int], known: Iterable[int], label: str) -> list[int]:
    pool = Counter(map(int, full_deck))
    for card_id in known:
        if pool[int(card_id)] <= 0:
            raise D1Error(f"{label}: public card {card_id} exceeds deck multiplicity")
        pool[int(card_id)] -= 1
    return list(pool.elements())


def _basic_ids() -> frozenset[int]:
    try:
        from cg.api import all_card_data

        return frozenset(int(card.cardId) for card in all_card_data() if bool(card.basic))
    except Exception:
        return frozenset()


def _partition_hidden(
    full_deck: Sequence[int],
    state: Any,
    player_index: int,
    *,
    reveal_hand: bool,
    rng: random.Random,
    extra_known: Sequence[int] = (),
) -> tuple[list[int], list[int], list[int], list[int]]:
    player = state.players[player_index]
    known_prizes = _known_prize_ids(player)
    known = _visible_ids(state, player_index, include_hand=reveal_hand) + known_prizes + list(extra_known)
    pool = _subtract(full_deck, known, f"player {player_index}")
    rng.shuffle(pool)
    hidden_active: list[int] = []
    active = getattr(player, "active", None) or []
    if active and active[0] is None:
        basics = _basic_ids()
        position = next((index for index, card_id in enumerate(pool) if card_id in basics), None)
        if position is None:
            raise D1Error("face-down active has no compatible Basic")
        hidden_active = [pool.pop(position)]
    hand_count = 0 if reveal_hand else _integer(getattr(player, "handCount", None), 0)
    prize_total = len(getattr(player, "prize", None) or [])
    hidden_prizes = prize_total - len(known_prizes)
    deck_count = _integer(getattr(player, "deckCount", None), 0)
    expected = deck_count + hand_count + hidden_prizes
    if len(pool) != expected:
        raise D1Error(
            f"player {player_index}: hidden pool={len(pool)} expected={expected}"
        )
    deck = pool[:deck_count]
    sampled_prizes = iter(pool[deck_count : deck_count + hidden_prizes])
    prizes = [
        int(card.id) if card is not None else next(sampled_prizes)
        for card in (getattr(player, "prize", None) or [])
    ]
    hand = pool[deck_count + hidden_prizes :]
    return deck, prizes, hand, hidden_active


def determinize_public_world(
    obs: Any,
    opponent_deck: Sequence[int],
    rng: random.Random,
) -> dict[str, list[int]]:
    state = obs.current
    me = int(state.yourIndex)
    opponent = 1 - me
    looking = _cards(getattr(state, "looking", None))
    visible_serials = {
        int(card.serial)
        for card in _cards(getattr(state.players[me], "hand", None))
        + _cards(getattr(state.players[me], "discard", None))
        + looking
    }
    transient: list[int] = []
    for card in (getattr(obs.select, "contextCard", None), getattr(obs.select, "effect", None)):
        identity = _card_identity(card)
        if identity is not None and identity[2] == me and identity[1] not in visible_serials:
            transient.append(identity[0])
            visible_serials.add(identity[1])
    your_deck, your_prize, _your_hand, _your_active = _partition_hidden(
        EXACT_DECK,
        state,
        me,
        reveal_hand=True,
        rng=rng,
        extra_known=[int(card.id) for card in looking] + transient,
    )
    opponent_hidden_deck, opponent_prize, opponent_hand, opponent_active = _partition_hidden(
        opponent_deck,
        state,
        opponent,
        reveal_hand=False,
        rng=rng,
    )
    if getattr(obs.select, "deck", None) is not None:
        your_deck = []
    return {
        "your_deck": your_deck,
        "your_prize": your_prize,
        "opponent_deck": opponent_hidden_deck,
        "opponent_prize": opponent_prize,
        "opponent_hand": opponent_hand,
        "opponent_active": opponent_active,
    }


# Filled below from the audited data/meta/top_decklists.json snapshot.  Keeping
# a compiled fallback is necessary because submission archives intentionally do
# not ship repository data paths.  Runtime never reads an evaluator opponent.
_COMPILED_PUBLIC_DECKS_B85 = """c-rk*S#In&47^Le{h^H#b(SC>wk6;H2t!GBYqi^*^m`Kw24)qKAia?0Qj|YGKhO)uW~n#E#K-h$rvBngC2&zeE8V~pzz0yX2+oYH2*ck{_hd~;T!hb);U^G1;X#7io`mU1aw4z|eSJ-zAASW8^ov<7r*Oao6PHtXr^B=k#ub|+gA64nqj&?+KvwAE!3T5_9xm*&c<dBzTztiY$ibdsP#Ox362-`XMm}>~{JhQ-899ZE^TOmFoA4^5>hKUSq(X#E*wX?vj~M%krX;$l0}=;~!eLZJIa}Hw3=&1yp0vso1EZPsTKa{}xKUu}8$G`;nAO?nrmBv3_`jWOPucH8=Ac+A>OmpDo2(El+}@DcEro~*As;k|3dHi^(RuVrZb~ZSmH(~nW0Vyk-x9sGeXx~z?=5(W2!(^3+AqPfN$L$XL<V_Qft;+t3z&#Ik>E=7G%OccQBIrKIGDUwI68KZlp@RGH7?vU=7C}&rgXu6#T0p@g{?u+s=+g;0}BZelo0%07{Z%$H0UWe8mq;U_UbuH7o{V`fT(3#v`4Qkhtx1iQ-xu+Fkqxo4WNPnUE#c=cD*B#>`9rPntoExmh%BK%#)&z3YZZc^RveJ=%Y6RlWL06^)ftzkPIhC6AfwZ#h{3WdXPEmDVHGulS9JgLb{BtV7To@3)*a!6($Ok*+Riw)rcC<K!>$tue6zgimbV+kyI$qQ0gHF%7N2VLgtWVr6z-DI$IDNZ`Wftl<J#BSreQhOeV&~EfSqa5NOQ{t>j&8<k$8R>-2)!&6>^pmL}V)q*P>~Tu7#JU=fm9xM6lOoJCmbI0<;npFD)lis^jTG`WFzRVliq=(OCn4H&72#m$}5Y1s0@6k`o|4N98``p5(^DJ>($&ShyTRZpX`h}wzk0mbHt6-5EiQr$NpmBq@OBZUf1%-jE4Ts35I!ObaPo45Ctm2OqBf?cjFc|U1n*4es}>9RT8+F72gD-0I3sTo$|m*9TAzCOBTIZ3Wp*=D6xc6_s+?5!_tu=N^yvC!V$YSVrX3Kz9%;ko|nHS=c*NByK+a?KcPI8_WNxy;p4H@IkNN>Dpshb~|mU<J;Z=&2Z^d_dRR-9W6`p2pQ9VhlD7v}lFC?Ed;O;pwt}ch7H@*f;F?(oqXh!ZKXeZ?@5Iwb0+vM`vr$Z_-OEo}GE!Q&t+_R9&Tk^G6g`48@Bw3xM7LHEyuFq3_{flw=b%(AW}Wu;R933PAW01Ytxawymk<Wbzp6Y{#8=&`K?h0x(qA*dJmrI4InkijuIh+Vfd&bZh*H@5%H3pzo5&S!mdlTiEp&czFo417N5Yelh?~M!~oXoJ)qJp%}fD*M4TJeA_7aH=Y*B_sjzHdIl$rbmH=n(Lg)BqMLrMnO;1nP~X%{#j;`f!sg9Uu8cY*Ihc$}e7B1ut>Pq0#&CS^B<tMuctVvjBc3$#7bNxg)XFU+rrBbUMd3Kg3@EJ1k{4C=Rbre;=(}s@8+3He38t0Qa&=A#QRIZ$FWRl>qFyfOxA?Mz&=3N`O$s<B2oDbdWSk`7tOBq+w#tVR!y_tvoJ<T4rgC23$x$!jLG7aecG6iMPXWIE0iG#C;{"""


def _compiled_public_decks() -> tuple[tuple[str, tuple[int, ...]], ...]:
    rows = json.loads(zlib.decompress(base64.b85decode(_COMPILED_PUBLIC_DECKS_B85)).decode("ascii"))
    parsed = tuple((str(deck_id), tuple(map(int, cards))) for deck_id, cards in rows)
    if len(parsed) != 30 or any(len(cards) != 60 for _deck_id, cards in parsed):
        raise D1Error("compiled public belief snapshot is invalid")
    return parsed


_COMPILED_PUBLIC_DECKS = _compiled_public_decks()


def _load_public_decks(path: Path | None = None) -> tuple[tuple[str, tuple[int, ...]], ...]:
    candidates = []
    if path is not None:
        candidates.append(Path(path))
    candidates.extend(
        [
            Path(__file__).resolve().parents[2] / "data" / "meta" / "top_decklists.json",
            Path(__file__).with_name("top_decklists.json"),
        ]
    )
    for candidate in candidates:
        try:
            rows = json.loads(candidate.read_text(encoding="utf-8"))
            parsed = tuple(
                (str(row["id"]), tuple(map(int, row["card_ids"])))
                for row in rows
                if len(row.get("card_ids", ())) == 60
            )
            if parsed:
                return parsed
        except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
            continue
    return _COMPILED_PUBLIC_DECKS


def compatible_public_beliefs(
    obs: Any,
    *,
    path: Path | None = None,
    decks: Sequence[tuple[str, Sequence[int]]] | None = None,
) -> tuple[tuple[str, tuple[int, ...]], ...]:
    """Filter public decklists by visible opponent multiplicities only."""

    state = obs.current
    actor = int(state.yourIndex)
    opponent = 1 - actor
    visible = Counter(_visible_ids(state, opponent, include_hand=False))
    visible.update(_known_prize_ids(state.players[opponent]))
    source = decks if decks is not None else _load_public_decks(path)
    compatible: list[tuple[str, tuple[int, ...]]] = []
    for deck_id, raw_cards in source:
        cards = tuple(map(int, raw_cards))
        counts = Counter(cards)
        if len(cards) == 60 and all(counts[card_id] >= count for card_id, count in visible.items()):
            compatible.append((str(deck_id), cards))
    return tuple(sorted(compatible, key=lambda item: item[0]))


class _NativeBackend:
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


@dataclass
class _Budget:
    started: float
    soft_deadline: float
    hard_deadline: float
    max_nodes: int
    max_calls: int
    clock: Any
    nodes: int = 0
    calls: int = 0

    def check(self, label: str) -> None:
        now = float(self.clock())
        if now >= self.hard_deadline or now >= self.soft_deadline:
            raise D1Timeout(f"deadline:{label}")
        if self.nodes > self.max_nodes:
            raise D1Error("node_budget")
        if self.calls > self.max_calls:
            raise D1Error("call_budget")

    def before_call(self, label: str) -> None:
        self.check(label)
        self.calls += 1
        if self.calls > self.max_calls:
            raise D1Error("call_budget")

    def after_state(self, label: str) -> None:
        self.nodes += 1
        if self.nodes > self.max_nodes:
            raise D1Error("node_budget")
        self.check(label)


@dataclass(frozen=True)
class _AttackTrace:
    productive_attacks: int = 0
    do_wave_count: int = 0
    first_do_wave_ko: bool = False
    second_target_completed: bool = False
    log_rows: tuple[tuple[int, int, int, int], ...] = ()


def _log_rows(observation: Any) -> tuple[tuple[int, int, int, int], ...]:
    return tuple(
        (
            _integer(getattr(log, "type", None)),
            _integer(getattr(log, "playerIndex", None)),
            _integer(getattr(log, "cardId", None)),
            _integer(getattr(log, "attackId", None)),
        )
        for log in (getattr(observation, "logs", None) or [])
    )


def _logs_taint_rng_or_hidden_deck(observation: Any, root_turn: int) -> bool:
    """Detect automatic random/deck work not attributable to a selected option.

    A normal opponent draw after TURN_START belongs to the completed next turn
    and is outside the comparison horizon.  Every earlier shuffle, setup-basic
    check, draw, reverse draw, or coin result invalidates sibling RNG parity.
    """

    current = getattr(observation, "current", None)
    completed = current is None or _integer(getattr(current, "turn", None), -1) != root_turn
    for log in getattr(observation, "logs", None) or []:
        log_type = _integer(getattr(log, "type", None))
        if log_type in {0, 1, 4, 5} and not completed:
            return True
        if getattr(log, "head", None) is not None and not completed:
            return True
    return False


def _in_play(player: Any) -> list[Any]:
    return _cards(getattr(player, "active", None)) + _cards(getattr(player, "bench", None))


def _opponent_damage(player: Any) -> int:
    return sum(
        max(0, _integer(getattr(card, "maxHp", None), 0) - _integer(getattr(card, "hp", None), 0))
        for card in _in_play(player)
    )


def _attack_productive(before: Any, after: Any, root_player: int) -> bool:
    if getattr(after, "current", None) is None:
        return True
    before_state, after_state = before.current, after.current
    before_me = before_state.players[root_player]
    after_me = after_state.players[root_player]
    if len(getattr(after_me, "prize", None) or []) < len(getattr(before_me, "prize", None) or []):
        return True
    before_opponent = before_state.players[1 - root_player]
    after_opponent = after_state.players[1 - root_player]
    if _opponent_damage(after_opponent) > _opponent_damage(before_opponent):
        return True
    before_ids = {_card_identity(card) for card in _in_play(before_opponent)}
    after_ids = {_card_identity(card) for card in _in_play(after_opponent)}
    return bool(before_ids - after_ids)


def _advance_trace(
    trace: _AttackTrace,
    before: Any,
    after: Any,
    root_player: int,
    action_attack_id: int | None,
) -> _AttackTrace:
    rows = trace.log_rows + _log_rows(after)
    if action_attack_id != DO_THE_WAVE:
        return replace(trace, log_rows=rows)
    productive = _attack_productive(before, after, root_player)
    before_active = _cards(getattr(before.current.players[1 - root_player], "active", None))
    after_in_play = _in_play(after.current.players[1 - root_player]) if after.current is not None else []
    old_identity = _card_identity(before_active[0]) if before_active else None
    ko = old_identity is not None and old_identity not in {_card_identity(card) for card in after_in_play}
    first_ko = trace.first_do_wave_ko or (trace.do_wave_count == 0 and ko)
    second_target = trace.second_target_completed or (
        trace.do_wave_count >= 1 and trace.first_do_wave_ko and productive
    )
    return _AttackTrace(
        productive_attacks=trace.productive_attacks + int(productive),
        do_wave_count=trace.do_wave_count + 1,
        first_do_wave_ko=first_ko,
        second_target_completed=second_target,
        log_rows=rows,
    )


def _action_attack_id(obs: Any, action: Sequence[int]) -> int | None:
    options = getattr(obs.select, "option", None) or []
    for index in action:
        if 0 <= int(index) < len(options):
            option = options[int(index)]
            if _integer(getattr(option, "type", None)) == int(OptionType.ATTACK):
                attack_id = _integer(getattr(option, "attackId", None))
                return attack_id if attack_id >= 0 else None
    return None


def _action_touches_rng_or_hidden_deck(obs: Any, action: Sequence[int]) -> bool:
    select = obs.select
    context = _integer(getattr(select, "context", None))
    if context in {
        int(SelectContext.COIN_HEAD),
        int(SelectContext.LOOK),
        int(SelectContext.DRAW_COUNT),
    }:
        return True
    parent = getattr(select, "effect", None) or getattr(select, "contextCard", None)
    if _integer(getattr(parent, "id", None)) in _RANDOM_OR_DECK_TOUCH_CARDS:
        return True
    for index in action:
        option = select.option[int(index)]
        card_id = _option_card_id(obs, option)
        attack_id = _integer(getattr(option, "attackId", None))
        if card_id in _RANDOM_OR_DECK_TOUCH_CARDS or attack_id == QUICK_SIGN:
            return True
    return False


def _completed(observation: Any, root_turn: int) -> bool:
    current = getattr(observation, "current", None)
    return (
        current is None
        or _integer(getattr(current, "result", None), -1) >= 0
        or _integer(getattr(current, "turn", None), -1) != root_turn
    )


def _ready_dipplin(card: Any, player: Any, *, active: bool) -> bool:
    return bool(
        card is not None
        and _integer(getattr(card, "id", None)) == DIPPLIN
        and len(getattr(card, "energies", None) or []) >= 1
        and (not active or not any(
            bool(getattr(player, name, False))
            for name in ("asleep", "paralyzed")
        ))
    )


def _resource_score(player: Any, ids: frozenset[int]) -> int:
    components: list[Any] = []
    for card in _in_play(player):
        components.append(card)
        components.extend(_cards(getattr(card, "energyCards", None)))
        components.extend(_cards(getattr(card, "tools", None)))
        components.extend(_cards(getattr(card, "preEvolution", None)))
    # The leaf may be rendered for a defender selector, in which case the root
    # player's hand is intentionally hidden.  Never let selector perspective
    # alter a metric: retained exact-deck copies are inferred from public loss
    # (discard) and public board components only.
    retained = sum(_integer(getattr(card, "id", None)) in ids for card in components)
    discarded = sum(
        _integer(getattr(card, "id", None)) in ids
        for card in _cards(getattr(player, "discard", None))
    )
    registered = sum(card_id in ids for card_id in EXACT_DECK)
    return registered - discarded + retained


def completed_turn_metric(
    root_obs: Any,
    leaf_obs: Any,
    root_player: int,
    memory: PlanMemory,
    trace: _AttackTrace,
) -> tuple[float, ...]:
    """Return only actor-visible, named, finite lexicographic fields."""

    root_state = root_obs.current
    leaf_state = getattr(leaf_obs, "current", None)
    if leaf_state is None:
        raise IncompleteLeafError("leaf has no current state")
    result = _integer(getattr(leaf_state, "result", None), -1)
    terminal_win = 1 if result == root_player else -1 if result >= 0 and result not in {2} else 0
    root_me = root_state.players[root_player]
    leaf_me = leaf_state.players[root_player]
    root_opponent = root_state.players[1 - root_player]
    leaf_opponent = leaf_state.players[1 - root_player]
    prizes = len(getattr(root_me, "prize", None) or []) - len(getattr(leaf_me, "prize", None) or [])
    root_active = _cards(getattr(root_opponent, "active", None))
    central = _card_identity(root_active[0]) if root_active else None
    central_ko = int(central is not None and central not in {_card_identity(card) for card in _in_play(leaf_opponent)})
    active_cards = _cards(getattr(leaf_me, "active", None))
    active = active_cards[0] if active_cards else None
    current_ready = int(_ready_dipplin(active, leaf_me, active=True))
    replacement_ready = int(
        any(
            _ready_dipplin(card, leaf_me, active=False)
            for card in _cards(getattr(leaf_me, "bench", None))
        )
    )
    stadium = _cards(getattr(leaf_state, "stadium", None))
    festival = int(bool(stadium and _integer(getattr(stadium[0], "id", None)) == FESTIVAL))
    active_has_festival_lead = _integer(getattr(active, "id", None)) == DIPPLIN
    usable_thwackey = sum(
        _integer(getattr(card, "id", None)) == THWACKEY
        for card in _in_play(leaf_me)
    ) if active_has_festival_lead else 0
    do_wave_output = 0
    opponent_active = _cards(getattr(leaf_opponent, "active", None))
    if current_ready and opponent_active:
        projection = project_do_the_wave(
            active,
            opponent_active[0],
            bench_count=len(getattr(leaf_me, "bench", None) or []),
            black_belt_used=False,
            stadium_id=_integer(getattr(stadium[0], "id", None)) if stadium else None,
            festival_active=bool(festival),
        )
        do_wave_output = int(projection.final)
    fragile = sum(
        0 < _integer(getattr(card, "maxHp", None), 0) <= 50
        for card in _cards(getattr(leaf_me, "bench", None))
    )
    values = (
        terminal_win,
        prizes,
        trace.productive_attacks,
        central_ko,
        int(trace.first_do_wave_ko and trace.second_target_completed),
        current_ready,
        replacement_ready,
        festival,
        usable_thwackey,
        do_wave_output,
        _resource_score(leaf_me, _CORE_ATTACKERS),
        _resource_score(leaf_me, _CORE_TUTORS),
        -fragile,
    )
    result_vector = tuple(float(value) for value in values)
    if len(result_vector) != len(METRIC_FIELDS) or not all(math.isfinite(value) for value in result_vector):
        raise D1Error("nonfinite_metric")
    return result_vector


def _lex_compare(left: Sequence[float], right: Sequence[float]) -> int:
    if len(left) != len(METRIC_FIELDS) or len(right) != len(METRIC_FIELDS):
        raise D1Error("metric_shape")
    if not all(math.isfinite(float(value)) for value in tuple(left) + tuple(right)):
        raise D1Error("nonfinite_metric")
    return (tuple(left) > tuple(right)) - (tuple(left) < tuple(right))


def _strict_load_bearing(left: Sequence[float], right: Sequence[float]) -> bool:
    return any(float(left[index]) > float(right[index]) for index in LOAD_BEARING_INDICES)


def _override_is_causally_admissible(
    candidate: RootCandidate,
    obs: Any,
    left_worlds: Sequence[Sequence[float]],
    right_worlds: Sequence[Sequence[float]],
) -> bool:
    """Require the root action itself to explain the completed-turn gain.

    A prior version credited arbitrary setup roots when D0's later continuation
    happened to find a KO in one determinization.  Deterministic attack,
    enablement, and explicit Boss/Belt roots have a direct causal route.  Other
    setup roots must improve the completed turn in every world, not merely one.
    """

    option = obs.select.option[int(candidate.original_action[0])]
    option_type = _integer(getattr(option, "type", None))
    card_id = _option_card_id(obs, option)
    direct = (
        option_type in {
            int(OptionType.ATTACK),
            int(OptionType.RETREAT),
            int(OptionType.EVOLVE),
            int(OptionType.ATTACH),
        }
        or card_id in DISRUPTION_OVERRIDE_CARDS | {FESTIVAL}
    )
    tactical = [
        any(
            float(left[index]) > float(right[index])
            for index in range(5)
        )
        for left, right in zip(left_worlds, right_worlds)
    ]
    return any(tactical) if direct else all(tactical)


class _WorldRunner:
    def __init__(
        self,
        planner: Any,
        backend: Any,
        budget: _Budget,
        config: D1Config,
        *,
        allow_random: bool = False,
        planning_enabled: bool = True,
    ) -> None:
        self.planner = planner
        self.backend = backend
        self.budget = budget
        self.config = config
        self.allow_random = bool(allow_random)
        self.planning_enabled = bool(planning_enabled)
        self.created: list[Any] = []
        self.created_ids: set[int] = set()
        self.release_attempted: set[int] = set()
        self.cleanup_errors: list[str] = []
        self.plan_branch_points = 0
        self.plan_alternatives = 0

    def _remember(self, state: Any, label: str) -> Any:
        if state is None or getattr(state, "searchId", None) is None:
            raise D1Error("native state missing searchId")
        search_id = int(state.searchId)
        if search_id in self.created_ids:
            raise D1Error("native reused live searchId")
        self.created_ids.add(search_id)
        self.created.append(state)
        self.budget.after_state(label)
        return state

    def _step(self, state: Any, action: Sequence[int], label: str) -> Any:
        self.budget.before_call(label)
        child = self.backend.step(int(state.searchId), list(map(int, action)))
        remembered = self._remember(child, label)
        return remembered

    def _release_all(self) -> None:
        for state in reversed(self.created):
            search_id = int(state.searchId)
            if search_id in self.release_attempted:
                continue
            self.release_attempted.add(search_id)
            try:
                self.backend.release(search_id)
            except Exception as exc:
                self.cleanup_errors.append(f"release[{search_id}]:{type(exc).__name__}:{exc}")

    def _opponent_actions(self, obs: Any) -> tuple[tuple[int, ...], ...]:
        select = obs.select
        minimum, maximum = int(select.minCount), int(select.maxCount)
        count = len(select.option)
        if minimum == maximum == count:
            return (tuple(range(count)),)
        if minimum == maximum == 1 and 1 <= count <= self.config.max_opponent_promotions:
            context = _integer(getattr(select, "context", None))
            if context in {int(SelectContext.SWITCH), int(SelectContext.TO_ACTIVE)}:
                return tuple((index,) for index in range(count))
        raise D1Error("ambiguous_nonhero_prompt")

    def _hero_action(self, obs: Any, memory: PlanMemory) -> tuple[list[int], Any]:
        if not self.allow_random and _action_touches_rng_or_hidden_deck(obs, []):
            raise D1Error("rng_or_hidden_deck_taint")
        snapshot = PlanSnapshot.from_observation(obs, memory)
        proposal = self.planner.propose(obs, snapshot, memory)
        action = sanitize_selection(
            obs.select,
            list(proposal.intent.ranked_indices),
            proposal.intent.desired_count,
        )
        if not self.allow_random and _action_touches_rng_or_hidden_deck(obs, action):
            raise D1Error("rng_or_hidden_deck_taint")
        return action, proposal

    def _rollout(
        self,
        state: Any,
        root_obs: Any,
        root_player: int,
        root_turn: int,
        memory: PlanMemory,
        trace: _AttackTrace,
        depth: int,
        planning_branch_points: int,
    ) -> list[tuple[tuple[float, ...], _AttackTrace]]:
        observation = state.observation
        if _completed(observation, root_turn):
            return [(completed_turn_metric(root_obs, observation, root_player, memory, trace), trace)]
        if depth >= self.config.max_steps_per_path:
            raise IncompleteLeafError("path_depth")
        if getattr(observation, "select", None) is None:
            raise IncompleteLeafError("same-turn state has no prompt")
        actor = _integer(getattr(observation.current, "yourIndex", None))
        if actor != root_player:
            leaves: list[tuple[tuple[float, ...], _AttackTrace]] = []
            for action in self._opponent_actions(observation):
                if not self.allow_random and _action_touches_rng_or_hidden_deck(observation, action):
                    raise D1Error("rng_or_hidden_deck_taint")
                child = self._step(state, action, "opponent_continuation")
                if not self.allow_random and _logs_taint_rng_or_hidden_deck(child.observation, root_turn):
                    raise D1Error("rng_or_hidden_deck_taint")
                leaves.extend(
                    self._rollout(
                        child,
                        root_obs,
                        root_player,
                        root_turn,
                        memory.clone(),
                        replace(trace, log_rows=trace.log_rows + _log_rows(child.observation)),
                        depth + 1,
                        planning_branch_points,
                    )
                )
            if not leaves:
                raise IncompleteLeafError("opponent branch has no completed leaf")
            return leaves

        baseline_action, proposal = self._hero_action(observation, memory)
        actions: tuple[RootCandidate, ...] = ()
        select = observation.select
        can_plan = (
            self.planning_enabled
            and not self.allow_random
            and planning_branch_points < self.config.max_planning_branch_points
            and _integer(getattr(select, "type", None)) == int(SelectType.MAIN)
            and _integer(getattr(select, "context", None)) == int(SelectContext.MAIN)
            and int(getattr(select, "minCount", 0)) == 1
            and int(getattr(select, "maxCount", 0)) == 1
        )
        if can_plan:
            actions = generate_root_candidates(
                observation,
                baseline_action,
                self.config.max_plan_candidates,
            )
            actions = tuple(
                candidate
                for candidate in actions
                if candidate.is_baseline
                or not _action_touches_rng_or_hidden_deck(
                    observation,
                    candidate.original_action,
                )
            )
        if not actions:
            actions = (
                RootCandidate(
                    tuple(map(int, baseline_action)),
                    capture_semantic_selection(observation, baseline_action),
                    "baseline",
                    True,
                ),
            )

        if len(actions) > 1:
            self.plan_branch_points += 1
            self.plan_alternatives += len(actions) - 1

        from .policy import semantic_final_action

        planned: list[tuple[tuple[float, ...], list[tuple[tuple[float, ...], _AttackTrace]]]] = []
        last_uncertifiable: D1Error | None = None
        for candidate in actions:
            action = list(candidate.original_action)
            branch_memory = memory.clone()
            resolver = proposal.intent.resolver if candidate.is_baseline else "d1_plan"
            reason = proposal.intent.reason if candidate.is_baseline else candidate.category
            branch_memory.commit(
                semantic_final_action(
                    observation,
                    action,
                    resolver,
                    reason,
                )
            )
            try:
                child = self._step(state, action, f"hero_plan:{candidate.category}")
                if not self.allow_random and _logs_taint_rng_or_hidden_deck(child.observation, root_turn):
                    raise D1Error("rng_or_hidden_deck_taint")
                attack_id = _action_attack_id(observation, action)
                child_trace = _advance_trace(
                    trace,
                    observation,
                    child.observation,
                    root_player,
                    attack_id,
                )
                leaves = self._rollout(
                    child,
                    root_obs,
                    root_player,
                    root_turn,
                    branch_memory,
                    child_trace,
                    depth + 1,
                    planning_branch_points + int(len(actions) > 1),
                )
            except D1Timeout:
                raise
            except D1Error as exc:
                if str(exc) in {"call_budget", "node_budget"}:
                    raise
                last_uncertifiable = exc
                continue
            if leaves:
                # The hero chooses a plan by its adversarial public-promotion
                # floor. Ties retain D0 because it is listed first.
                planned.append((min(leaf[0] for leaf in leaves), leaves))
        if not planned:
            if last_uncertifiable is not None:
                raise last_uncertifiable
            raise IncompleteLeafError("hero plan has no completed leaf")
        best_floor = max(item[0] for item in planned)
        return next(leaves for floor, leaves in planned if floor == best_floor)

    def run(
        self,
        obs: Any,
        candidates: Sequence[RootCandidate],
        determinization: Mapping[str, Any],
        base_memory: PlanMemory,
    ) -> dict[str, tuple[float, ...]]:
        outcomes: dict[str, tuple[float, ...]] = {}
        primary_error: Exception | None = None
        begin_attempted = False
        try:
            self.budget.before_call("search_begin")
            begin_attempted = True
            root = self._remember(self.backend.begin(obs, determinization), "search_begin")
            root_player = int(obs.current.yourIndex)
            root_turn = int(obs.current.turn)
            root_observation = root.observation
            for candidate in candidates:
                try:
                    remapped = resolve_semantic_selection(root_observation, candidate.semantic)
                    if remapped is None:
                        raise SemanticRemapError("root semantic remap failed")
                    if not self.allow_random and _action_touches_rng_or_hidden_deck(root_observation, remapped):
                        raise D1Error("rng_or_hidden_deck_taint")
                    memory = base_memory.clone()
                    from .policy import semantic_final_action

                    root_semantic = semantic_final_action(
                        root_observation,
                        remapped,
                        "d1_root",
                        candidate.category,
                    )
                    memory.commit(root_semantic)
                    branch = self._step(root, remapped, f"root:{candidate.category}")
                    if not self.allow_random and _logs_taint_rng_or_hidden_deck(branch.observation, root_turn):
                        raise D1Error("rng_or_hidden_deck_taint")
                    attack_id = _action_attack_id(root_observation, remapped)
                    trace = _advance_trace(
                        _AttackTrace(),
                        root_observation,
                        branch.observation,
                        root_player,
                        attack_id,
                    )
                    leaves = self._rollout(
                        branch,
                        root_observation,
                        root_player,
                        root_turn,
                        memory,
                        trace,
                        1,
                        0,
                    )
                except D1Timeout:
                    raise
                except D1Error as exc:
                    if candidate.is_baseline or str(exc) in {"call_budget", "node_budget"}:
                        raise
                    # One uncertifiable alternative must not poison otherwise
                    # deterministic root siblings. It simply has no evidence
                    # in this world and cannot qualify globally.
                    continue
                vectors = [leaf[0] for leaf in leaves]
                outcomes[candidate.key] = min(vectors)
            if candidates[0].key not in outcomes:
                raise D1Error("baseline_missing")
        except Exception as exc:
            primary_error = exc
        finally:
            self._release_all()
            if begin_attempted:
                try:
                    self.backend.end()
                except Exception as exc:
                    self.cleanup_errors.append(f"search_end:{type(exc).__name__}:{exc}")
        if self.cleanup_errors:
            message = ";".join(self.cleanup_errors)
            if primary_error is not None:
                message = f"{type(primary_error).__name__}:{primary_error};{message}"
            raise D1Error(message)
        if primary_error is not None:
            raise primary_error
        return outcomes


class FestivalD1Search:
    """Selective D0 override with a byte-exact-baseline failure boundary."""

    def __init__(
        self,
        planner: Any,
        telemetry: Any,
        config: D1Config | None = None,
        *,
        backend: Any | None = None,
        belief_path: Path | None = None,
        belief_decks: Sequence[tuple[str, Sequence[int]]] | None = None,
        clock: Any = time.monotonic,
    ) -> None:
        self.planner = planner
        self.telemetry = telemetry
        self.config = config or D1Config(
            worlds=max(2, min(4, _integer(os.environ.get("PTCG_DIPPLIN_WORLDS"), 2)))
        )
        self.backend = backend or _NativeBackend()
        self.belief_path = belief_path
        self.belief_decks = belief_decks
        self.clock = clock
        self.searches_this_game = 0

    def reset(self) -> None:
        self.searches_this_game = 0

    def _increment(self, key: str, amount: int | float = 1) -> None:
        try:
            self.telemetry.increment(key, amount)
        except Exception:
            # Telemetry can never change the selected action.
            pass

    def _abstain(self, baseline: Sequence[int], reason: str) -> list[int]:
        self._increment("d1_abstentions")
        safe = "".join(character if character.isalnum() else "_" for character in reason.lower()).strip("_")
        self._increment(f"d1_abstention_reason_{safe or 'unknown'}")
        return list(baseline)

    def choose(
        self,
        raw: Mapping[str, Any],
        obs: Any,
        snapshot: PlanSnapshot,
        working_memory: PlanMemory,
        proposal: Any,
        baseline: Sequence[int],
    ) -> list[int]:
        del raw, proposal
        fallback = list(baseline)
        select = getattr(obs, "select", None)
        if (
            select is None
            or _integer(getattr(select, "type", None)) != int(SelectType.MAIN)
            or _integer(getattr(select, "context", None)) != int(SelectContext.MAIN)
            or int(getattr(select, "minCount", 0)) != 1
            or int(getattr(select, "maxCount", 0)) != 1
            or snapshot.second_attack_currently_offered
        ):
            return fallback
        if not getattr(obs, "search_begin_input", None):
            return self._abstain(fallback, "invalid_root")
        if self.searches_this_game >= self.config.max_searches_per_game:
            return self._abstain(fallback, "game_budget")

        try:
            candidates = generate_root_candidates(obs, fallback, self.config.max_candidates)
        except Exception:
            return self._abstain(fallback, "semantic_capture")
        # Hidden-deck roots use isolated fresh-root replay certification below.
        # Deterministic roots retain the cheaper common-root comparison.
        replay_required = any(
            _action_touches_rng_or_hidden_deck(obs, candidate.original_action)
            for candidate in candidates
        )
        if len(candidates) < 2:
            return fallback
        beliefs = compatible_public_beliefs(
            obs,
            path=self.belief_path,
            decks=self.belief_decks,
        )
        if not beliefs:
            return self._abstain(fallback, "no_public_belief")

        self.searches_this_game += 1
        self._increment("d1_attempts")
        self._increment("d1_searches_started")
        self._increment("d1_root_candidates", len(candidates))
        self._increment(f"d1_context_{_integer(getattr(select, 'context', None))}")
        started = float(self.clock())
        budget = _Budget(
            started=started,
            soft_deadline=started + self.config.soft_timeout_seconds,
            hard_deadline=started + self.config.hard_timeout_seconds,
            max_nodes=self.config.max_nodes_per_decision,
            max_calls=self.config.max_native_calls_per_decision,
            clock=self.clock,
        )
        digest = _public_state_digest(obs)
        outcomes: dict[str, list[tuple[float, ...]]] = {candidate.key: [] for candidate in candidates}
        reason = "error"
        try:
            # Rotate deterministically through compatible public archetypes;
            # no runtime/evaluator opponent identity participates.
            offset = int(digest[:8], 16) % len(beliefs)
            selected_beliefs = [
                beliefs[(offset + index) % len(beliefs)]
                for index in range(self.config.worlds)
            ]
            for world_index, (_deck_id, opponent_deck) in enumerate(selected_beliefs):
                material = f"{self.config.seed_salt}:{digest}:{world_index}".encode("ascii")
                seed = int.from_bytes(hashlib.sha256(material).digest()[:8], "big")
                determinization = determinize_public_world(
                    obs,
                    opponent_deck,
                    random.Random(seed),
                )
                if replay_required:
                    passes: list[dict[str, tuple[float, ...]]] = []
                    for ordered in (candidates, tuple(reversed(candidates))):
                        replay: dict[str, tuple[float, ...]] = {}
                        for candidate in ordered:
                            runner = _WorldRunner(
                                self.planner,
                                self.backend,
                                budget,
                                self.config,
                                allow_random=True,
                                planning_enabled=False,
                            )
                            self._increment("d1_native_roots")
                            try:
                                result = runner.run(
                                    obs,
                                    (candidate,),
                                    determinization,
                                    working_memory,
                                )
                            except D1Timeout:
                                raise
                            except D1Error as exc:
                                message = str(exc).lower()
                                if any(
                                    token in message
                                    for token in (
                                        "call_budget",
                                        "node_budget",
                                        "release[",
                                        "search_end",
                                    )
                                ):
                                    raise
                                continue
                            vector = result.get(candidate.key)
                            if vector is not None:
                                replay[candidate.key] = vector
                        passes.append(replay)
                    world = {}
                    for candidate in candidates:
                        key = candidate.key
                        if key not in passes[0] or key not in passes[1]:
                            continue
                        if passes[0][key] != passes[1][key]:
                            self._increment("d1_rng_replay_disagreements")
                            continue
                        world[key] = passes[0][key]
                        self._increment("d1_rng_replay_agreements")
                    self._increment("d1_rng_replay_worlds")
                else:
                    runner = _WorldRunner(self.planner, self.backend, budget, self.config)
                    world = runner.run(obs, candidates, determinization, working_memory)
                    self._increment("d1_plan_branch_points", runner.plan_branch_points)
                    self._increment("d1_plan_alternatives", runner.plan_alternatives)
                self._increment("d1_root_candidates_dropped", len(candidates) - len(world))
                for key, vector in world.items():
                    if len(vector) != len(METRIC_FIELDS) or not all(math.isfinite(x) for x in vector):
                        raise D1Error("nonfinite_metric")
                    outcomes[key].append(tuple(vector))
            eligible = tuple(
                candidate
                for candidate in candidates
                if len(outcomes[candidate.key]) == self.config.worlds
            )
            if not eligible or not eligible[0].is_baseline:
                raise D1Error(
                    "rng_replay_disagreement"
                    if replay_required
                    else "baseline_world_coverage"
                )
            budget.check("comparison")

            baseline_candidate = eligible[0]
            baseline_worlds = outcomes[baseline_candidate.key]
            admitted: list[RootCandidate] = []
            for candidate in eligible[1:]:
                candidate_worlds = outcomes[candidate.key]
                comparisons = [
                    _lex_compare(candidate_metric, baseline_metric)
                    for candidate_metric, baseline_metric in zip(candidate_worlds, baseline_worlds)
                ]
                if all(value >= 0 for value in comparisons) and any(
                    _strict_load_bearing(candidate_metric, baseline_metric)
                    for candidate_metric, baseline_metric in zip(candidate_worlds, baseline_worlds)
                ) and _override_is_causally_admissible(
                    candidate,
                    obs,
                    candidate_worlds,
                    baseline_worlds,
                ):
                    admitted.append(candidate)
            if not admitted:
                self._increment("d1_searches_completed")
                return self._abstain(fallback, "no_dominance")

            # Multiple admitted actions are safe only if one itself dominates
            # every other admitted action worldwise; otherwise the proof is
            # genuinely ambiguous and D0 retains control.
            winners: list[RootCandidate] = []
            for candidate in admitted:
                if all(
                    all(
                        _lex_compare(left, right) >= 0
                        for left, right in zip(outcomes[candidate.key], outcomes[other.key])
                    )
                    for other in admitted
                    if other.key != candidate.key
                ):
                    winners.append(candidate)
            if len(winners) != 1:
                self._increment("d1_searches_completed")
                return self._abstain(fallback, "ambiguous_dominance")
            winner = winners[0]
            result = list(winner.original_action)
            if result == fallback:
                self._increment("d1_searches_completed")
                return self._abstain(fallback, "semantic_tie")
            self._increment("d1_searches_completed")
            self._increment("d1_overrides")
            self._increment("d0_d1_disagreements")
            self._increment(f"d1_override_category_{winner.category}")
            baseline_option = obs.select.option[int(fallback[0])]
            winner_option = obs.select.option[int(result[0])]
            baseline_card = _option_card_id(obs, baseline_option)
            winner_card = _option_card_id(obs, winner_option)
            baseline_type = _integer(getattr(baseline_option, "type", None))
            winner_type = _integer(getattr(winner_option, "type", None))
            self._increment(
                f"d1_override_transition_t{baseline_type}_c{baseline_card}_to_t{winner_type}_c{winner_card}"
            )
            return result
        except D1Timeout:
            reason = "timeout"
            self._increment("d1_timeouts")
        except SemanticRemapError:
            reason = "semantic_remap"
        except IncompleteLeafError:
            reason = "incomplete_leaf"
        except Exception as exc:
            text = str(exc).lower()
            if "release[" in text or "search_end" in text:
                reason = "cleanup_error"
                self._increment("d1_cleanup_errors")
            elif "unequal" in text:
                reason = "unequal_coverage"
            elif "nonfinite" in text:
                reason = "nonfinite_metric"
            elif "rng_or_hidden_deck" in text:
                reason = "rng_or_hidden_deck_taint"
            elif "rng_replay" in text:
                reason = "rng_replay_disagreement"
            elif "incomplete" in text or "path_depth" in text:
                reason = "incomplete_leaf"
            else:
                reason = "engine_error"
                self._increment("d1_errors")
                detail = "".join(
                    character if character.isalnum() else "_"
                    for character in f"{type(exc).__name__}_{text}".lower()
                ).strip("_")[:96]
                self._increment(f"d1_error_detail_{detail or 'unknown'}")
        finally:
            elapsed_ms = max(0.0, (float(self.clock()) - started) * 1000.0)
            if math.isfinite(elapsed_ms):
                self._increment("d1_latency_count")
                self._increment("d1_latency_ms_total", elapsed_ms)
                self._increment("d1_latency_ms_max", elapsed_ms)
            self._increment("d1_nodes", budget.nodes)
            self._increment("d1_native_calls", budget.calls)
            self._increment("d1_worlds", min(self.config.worlds, max((len(x) for x in outcomes.values()), default=0)))
        return self._abstain(fallback, reason)


__all__ = [
    "D1Config",
    "FestivalD1Search",
    "METRIC_FIELDS",
    "SemanticOption",
    "SemanticSelection",
    "capture_semantic_selection",
    "compatible_public_beliefs",
    "completed_turn_metric",
    "determinize_public_world",
    "generate_root_candidates",
    "resolve_semantic_selection",
    "semantic_option",
]
