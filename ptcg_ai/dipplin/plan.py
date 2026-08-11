"""Explicit macro planning for the rank-34 Festival Lead deck.

The planner deliberately uses requirement tiers instead of a blended card score.
Its output is rebuilt from the public observation at every prompt; persistent
memory is only used to disambiguate actions which the engine does not expose as
state flags (for example which Festival attack occurred earlier this turn).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

from .cards import (
    APPLIN_DRAGON,
    APPLIN_GRASS,
    BLACK_BELT,
    BRAVE_BANGLE,
    DIPPLIN,
    FESTIVAL,
    GRASS_ENERGY,
    GROOKEY,
    THWACKEY,
    VOLBEAT,
)


class Phase(str, Enum):
    OPENING_SETUP = "OPENING_SETUP"
    ENABLE_FIRST_ATTACK = "ENABLE_FIRST_ATTACK"
    MAXIMIZE_PRIZES_NOW = "MAXIMIZE_PRIZES_NOW"
    BUILD_REPLACEMENT = "BUILD_REPLACEMENT"
    RECOVER = "RECOVER"
    CLOSE_GAME = "CLOSE_GAME"


@dataclass(frozen=True)
class BoardLine:
    card_id: int
    current_serial: int
    lineage_serial: int
    area: int
    index: int
    hp: int
    max_hp: int
    energy_count: int
    tool_ids: tuple[int, ...]
    appeared_this_turn: bool

    @property
    def is_applin_line(self) -> bool:
        return self.card_id in {APPLIN_DRAGON, APPLIN_GRASS, DIPPLIN}

    @property
    def is_engine_line(self) -> bool:
        return self.card_id in {GROOKEY, THWACKEY}

    @property
    def attack_ready(self) -> bool:
        return self.card_id == DIPPLIN and self.energy_count >= 1


@dataclass(frozen=True)
class MacroPlan:
    phase: Phase
    actual_order: str
    own_turn_ordinal: int
    active: BoardLine | None
    bench: tuple[BoardLine, ...]
    current_attacker_serial: int | None
    replacement_attacker_serial: int | None
    thwackey_serials: tuple[int, ...]
    trapped_active_serial: int | None
    festival_active: bool
    current_attacker_ready: bool
    replacement_attacker_ready: bool
    productive_attack_legal: bool
    second_attack_offered: bool
    black_belt_used: bool
    missing_prerequisites: tuple[str, ...]
    known_hand_ids: tuple[int, ...]
    known_discard_ids: tuple[int, ...]
    opponent_visible_ids: tuple[int, ...]
    fragile_bench_count: int

    @property
    def bench_count(self) -> int:
        return len(self.bench)

    @property
    def has_applin_line(self) -> bool:
        return bool(self.active and self.active.is_applin_line) or any(
            line.is_applin_line for line in self.bench
        )

    @property
    def has_engine_line(self) -> bool:
        return bool(self.active and self.active.is_engine_line) or any(
            line.is_engine_line for line in self.bench
        )


def _int(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _line(card: Any, area: int, index: int) -> BoardLine | None:
    if card is None:
        return None
    pre = list(getattr(card, "preEvolution", None) or [])
    # The physical top-card serial changes on evolution.  The Basic at the
    # bottom of preEvolution is the stable public identity for this board line.
    lineage = _int(getattr(pre[0], "serial", None), _int(getattr(card, "serial", None))) if pre else _int(getattr(card, "serial", None))
    tools = tuple(_int(getattr(tool, "id", None)) for tool in (getattr(card, "tools", None) or []))
    energies = getattr(card, "energies", None) or []
    return BoardLine(
        card_id=_int(getattr(card, "id", None)),
        current_serial=_int(getattr(card, "serial", None)),
        lineage_serial=lineage,
        area=area,
        index=index,
        hp=max(0, _int(getattr(card, "hp", None), 0)),
        max_hp=max(0, _int(getattr(card, "maxHp", getattr(card, "max_hp", None)), 0)),
        energy_count=len(energies),
        tool_ids=tools,
        appeared_this_turn=bool(getattr(card, "appearThisTurn", False)),
    )


def _ids(cards: Iterable[Any]) -> tuple[int, ...]:
    return tuple(_int(getattr(card, "id", None)) for card in cards if card is not None)


def _memory_flag(memory: Any, name: str, default: bool = False) -> bool:
    value = getattr(memory, name, default) if memory is not None else default
    return bool(value)


def _legal_attack_ids(obs: Any) -> set[int]:
    select = getattr(obs, "select", None)
    result: set[int] = set()
    for option in getattr(select, "option", None) or []:
        attack_id = getattr(option, "attackId", None)
        if attack_id is not None:
            result.add(_int(attack_id))
    return result


def build_macro_plan(obs: Any, memory: Any = None) -> MacroPlan:
    """Build the deterministic public macro state for the current selector."""

    state = getattr(obs, "current", None)
    if state is None:
        return MacroPlan(
            phase=Phase.OPENING_SETUP,
            actual_order="unknown",
            own_turn_ordinal=0,
            active=None,
            bench=(),
            current_attacker_serial=None,
            replacement_attacker_serial=None,
            thwackey_serials=(),
            trapped_active_serial=None,
            festival_active=False,
            current_attacker_ready=False,
            replacement_attacker_ready=False,
            productive_attack_legal=False,
            second_attack_offered=False,
            black_belt_used=False,
            missing_prerequisites=("setup",),
            known_hand_ids=(),
            known_discard_ids=(),
            opponent_visible_ids=(),
            fragile_bench_count=0,
        )

    hero_index = _int(getattr(state, "yourIndex", None), 0)
    players = list(getattr(state, "players", None) or [])
    hero = players[hero_index] if 0 <= hero_index < len(players) else None
    opponent_index = 1 - hero_index
    opponent = players[opponent_index] if 0 <= opponent_index < len(players) else None
    active_cards = list(getattr(hero, "active", None) or []) if hero is not None else []
    active = _line(active_cards[0], 4, 0) if active_cards and active_cards[0] is not None else None
    bench = tuple(
        result
        for index, card in enumerate(getattr(hero, "bench", None) or [])
        if (result := _line(card, 5, index)) is not None
    )
    all_lines = tuple(([active] if active is not None else []) + list(bench))
    attackers = tuple(line for line in all_lines if line.card_id == DIPPLIN)
    current_attacker = active if active is not None and active.card_id == DIPPLIN else None
    replacement_candidates = tuple(line for line in attackers if current_attacker is None or line.lineage_serial != current_attacker.lineage_serial)
    replacement = next((line for line in replacement_candidates if line.attack_ready), None)
    if replacement is None:
        replacement = next(iter(replacement_candidates), None)
    if replacement is None:
        replacement = next(
            (line for line in bench if line.card_id in {APPLIN_GRASS, APPLIN_DRAGON}),
            None,
        )

    stadium = list(getattr(state, "stadium", None) or [])
    festival_active = bool(stadium and _int(getattr(stadium[0], "id", None)) == FESTIVAL)
    select = getattr(obs, "select", None)
    select_type = _int(getattr(select, "type", None))
    context = _int(getattr(select, "context", None))
    second_attack = select_type == 6 and context == 35
    legal_attacks = _legal_attack_ids(obs)
    # Attack 115 is imported lazily to keep the list of strategic card IDs above
    # easy to audit against the deck manifest.
    from .cards import DO_THE_WAVE

    productive = DO_THE_WAVE in legal_attacks and active is not None and active.attack_ready and len(bench) > 0
    current_ready = bool(active and active.attack_ready)
    replacement_ready = bool(replacement and replacement.attack_ready)

    hand_ids = _ids(getattr(hero, "hand", None) or []) if hero is not None else ()
    discard_ids = _ids(getattr(hero, "discard", None) or []) if hero is not None else ()
    opponent_in_play = []
    if opponent is not None:
        opponent_in_play.extend(card for card in (getattr(opponent, "active", None) or []) if card is not None)
        opponent_in_play.extend(card for card in (getattr(opponent, "bench", None) or []) if card is not None)

    missing: list[str] = []
    if active is None or active.card_id != DIPPLIN:
        missing.append("active_dipplin")
    if active is None or active.energy_count < 1:
        missing.append("current_energy")
    if not festival_active:
        missing.append("festival")
    if not any(line.card_id == THWACKEY for line in all_lines):
        missing.append("thwackey")
    if replacement is None:
        missing.append("replacement_applin")
    elif replacement.card_id != DIPPLIN:
        missing.append("replacement_dipplin")
    elif not replacement.attack_ready:
        missing.append("replacement_energy")

    turn = max(0, _int(getattr(getattr(obs, "current", None), "turn", None), 0))
    first = _int(getattr(getattr(obs, "current", None), "firstPlayer", None))
    actual_order = "first" if hero_index == first else "second" if first in {0, 1} else "unknown"
    own_turn = (turn + 1) // 2 if hero_index == first else turn // 2 if first in {0, 1} else 0
    own_prizes = len(getattr(hero, "prize", None) or []) if hero is not None else 6
    has_applin = any(line.is_applin_line for line in all_lines)
    has_engine = any(line.is_engine_line for line in all_lines)
    discarded_core = any(card_id in {APPLIN_DRAGON, APPLIN_GRASS, DIPPLIN} for card_id in discard_ids)

    if own_prizes <= 2:
        phase = Phase.CLOSE_GAME
    elif turn <= 2 or not has_applin or not has_engine:
        phase = Phase.OPENING_SETUP
    elif productive or second_attack:
        phase = Phase.MAXIMIZE_PRIZES_NOW
    elif not current_ready:
        phase = Phase.ENABLE_FIRST_ATTACK
    elif replacement is None and discarded_core:
        phase = Phase.RECOVER
    else:
        phase = Phase.BUILD_REPLACEMENT

    trapped = active.current_serial if active is not None and active.card_id not in {DIPPLIN, APPLIN_DRAGON, APPLIN_GRASS} else None
    fragile = sum(1 for line in bench if line.max_hp and line.max_hp <= 50)
    return MacroPlan(
        phase=phase,
        actual_order=actual_order,
        own_turn_ordinal=own_turn,
        active=active,
        bench=bench,
        current_attacker_serial=current_attacker.current_serial if current_attacker is not None else None,
        replacement_attacker_serial=replacement.current_serial if replacement is not None else None,
        thwackey_serials=tuple(line.current_serial for line in all_lines if line.card_id == THWACKEY),
        trapped_active_serial=trapped,
        festival_active=festival_active,
        current_attacker_ready=current_ready,
        replacement_attacker_ready=replacement_ready,
        productive_attack_legal=productive,
        second_attack_offered=second_attack,
        black_belt_used=_memory_flag(memory, "black_belt_used"),
        missing_prerequisites=tuple(missing),
        known_hand_ids=hand_ids,
        known_discard_ids=discard_ids,
        opponent_visible_ids=_ids(opponent_in_play),
        fragile_bench_count=fragile,
    )


def tutor_prerequisite_order(plan: MacroPlan) -> tuple[int, ...]:
    """Return exact card IDs for the next Boom Boom Groove target tiers."""

    targets: list[int] = []
    for missing in plan.missing_prerequisites:
        if missing in {"active_dipplin", "replacement_dipplin"}:
            targets.append(DIPPLIN)
        elif missing == "festival":
            targets.append(FESTIVAL)
        elif missing in {"current_energy", "replacement_energy"}:
            targets.append(GRASS_ENERGY)
        elif missing == "replacement_applin":
            targets.extend((APPLIN_GRASS, APPLIN_DRAGON))
        elif missing == "thwackey":
            targets.append(THWACKEY)
    targets.extend((BRAVE_BANGLE, BLACK_BELT))
    deduplicated: list[int] = []
    for card_id in targets:
        if card_id not in deduplicated:
            deduplicated.append(card_id)
    return tuple(deduplicated)
