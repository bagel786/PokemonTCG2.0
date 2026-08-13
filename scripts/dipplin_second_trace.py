"""Read-only per-game tracing for actual-second Dipplin causal buckets.

The tracer lives in evaluator infrastructure rather than the competition
package.  It observes only public boards, Stadiums, Prize counts, and the
hero's selected public action.  It never reads either hidden hand, hidden
Prize identity, deck contents, or ``search_begin_input`` and cannot influence
the action sent to the engine.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from cg.api import OptionType

from ptcg_ai.dipplin.cards import (
    APPLIN_DRAGON,
    APPLIN_GRASS,
    DIPPLIN,
    DO_THE_WAVE,
    FESTIVAL,
    GROOKEY,
    QUICK_SIGN,
    SHAYMIN,
    THWACKEY,
    VOLBEAT,
)


SCHEMA = "dipplin-second-bucket-trace-v1"
APPLIN_LINE = frozenset({APPLIN_DRAGON, APPLIN_GRASS, DIPPLIN})
ENGINE_LINE = frozenset({GROOKEY, THWACKEY})
SUPPORT_ACTIVE = frozenset({VOLBEAT, GROOKEY, THWACKEY, SHAYMIN})


def _int(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _cards(zone: Any) -> list[Any]:
    return [card for card in (zone or ()) if card is not None]


def _card_id(card: Any) -> int:
    return _int(getattr(card, "id", None))


def _energy_count(card: Any) -> int:
    if card is None:
        return 0
    energies = getattr(card, "energyCards", None)
    if energies is None:
        energies = getattr(card, "energies", None)
    return len(energies or ())


def _own_turn_ordinal(global_turn: int, hero_seat: int, first_player: int) -> int:
    if first_player not in {0, 1} or global_turn <= 0:
        return 0
    first_turn = 1 if hero_seat == first_player else 2
    return 0 if global_turn < first_turn else ((global_turn - first_turn) // 2) + 1


def _is_hero_turn(global_turn: int, hero_seat: int, first_player: int) -> bool:
    if first_player not in {0, 1} or global_turn <= 0:
        return False
    owner = first_player if global_turn % 2 else 1 - first_player
    return owner == hero_seat


def _replacement_state(active: Any, bench: Sequence[Any]) -> str:
    active_serial = _int(getattr(active, "serial", None)) if active is not None else -1
    candidates = [
        card
        for card in bench
        if _int(getattr(card, "serial", None)) != active_serial
    ]
    if any(_card_id(card) == DIPPLIN and _energy_count(card) >= 1 for card in candidates):
        return "ready_dipplin"
    if any(_card_id(card) == DIPPLIN for card in candidates):
        return "dipplin_no_energy"
    if any(
        _card_id(card) in {APPLIN_DRAGON, APPLIN_GRASS}
        and _energy_count(card) >= 1
        for card in candidates
    ):
        return "energized_applin"
    if any(_card_id(card) in {APPLIN_DRAGON, APPLIN_GRASS} for card in candidates):
        return "applin_no_energy"
    return "none"


def public_board_snapshot(obs: Any, hero_seat: int) -> dict[str, Any] | None:
    """Return the named public board metrics needed by bucket analysis."""
    state = getattr(obs, "current", None)
    players = list(getattr(state, "players", None) or ()) if state is not None else []
    if not 0 <= int(hero_seat) < len(players):
        return None
    hero = players[int(hero_seat)]
    active_cards = _cards(getattr(hero, "active", None))
    active = active_cards[0] if active_cards else None
    bench = _cards(getattr(hero, "bench", None))
    in_play = ([active] if active is not None else []) + bench
    stadium = _cards(getattr(state, "stadium", None))

    energy_by_role = Counter()
    for card in in_play:
        count = _energy_count(card)
        if card is active:
            energy_by_role["active"] += count
        if _card_id(card) in APPLIN_LINE:
            energy_by_role["applin_line"] += count
        elif _card_id(card) in ENGINE_LINE:
            energy_by_role["engine_line"] += count
        else:
            energy_by_role["other_support"] += count

    active_id = _card_id(active)
    active_ready = active_id == DIPPLIN and _energy_count(active) >= 1
    dipplin_count = sum(_card_id(card) == DIPPLIN for card in in_play)
    ready_dipplin_count = sum(
        _card_id(card) == DIPPLIN and _energy_count(card) >= 1
        for card in in_play
    )
    return {
        "active_id": active_id if active is not None else None,
        "active_energy": _energy_count(active),
        "active_ready": active_ready,
        "bench_count": len(bench),
        "bench_ids": [_card_id(card) for card in bench],
        "applin_lines": sum(_card_id(card) in APPLIN_LINE for card in in_play),
        "engine_lines": sum(_card_id(card) in ENGINE_LINE for card in in_play),
        "dipplin_count": dipplin_count,
        "ready_dipplin_count": ready_dipplin_count,
        "thwackey_count": sum(_card_id(card) == THWACKEY for card in in_play),
        "festival_active": bool(stadium and _card_id(stadium[0]) == FESTIVAL),
        "replacement_state": _replacement_state(active, bench),
        "energy_placement": {
            "total": sum(_energy_count(card) for card in in_play),
            "active": energy_by_role["active"],
            "applin_line": energy_by_role["applin_line"],
            "engine_line": energy_by_role["engine_line"],
            "other_support": energy_by_role["other_support"],
        },
    }


def opening_bucket(active_id: int | None, quick_sign_legal: bool) -> str:
    if active_id == VOLBEAT:
        return (
            "volbeat_active_quick_sign_legal"
            if quick_sign_legal
            else "volbeat_active_quick_sign_unavailable"
        )
    return {
        APPLIN_DRAGON: "applin_42_active",
        APPLIN_GRASS: "applin_92_active",
        GROOKEY: "grookey_active",
        SHAYMIN: "shaymin_active",
    }.get(active_id, "other_unusual")


def _missed_prerequisites(board: Mapping[str, Any], *, attacks: int) -> tuple[str, ...]:
    """Describe visible deficiencies on an incomplete attack turn.

    Categories are intentionally non-exclusive.  ``festival`` describes a
    missed double-attack prerequisite, while the other fields explain a missed
    first productive attack or missing continuation line.
    """
    missing: list[str] = []
    active_id = board.get("active_id")
    active_ready = bool(board.get("active_ready"))
    dipplin_count = int(board.get("dipplin_count") or 0)
    ready_dipplin_count = int(board.get("ready_dipplin_count") or 0)
    replacement = str(board.get("replacement_state") or "none")
    if attacks == 0:
        if dipplin_count <= 0:
            missing.append("dipplin")
        if dipplin_count > 0 and ready_dipplin_count <= 0:
            missing.append("energy")
        if active_id != DIPPLIN and replacement == "ready_dipplin":
            missing.append("retreat_promotion")
        if active_id == DIPPLIN and active_ready:
            missing.append("other")
    if attacks < 2 and not bool(board.get("festival_active")):
        missing.append("festival")
    if int(board.get("thwackey_count") or 0) <= 0:
        missing.append("thwackey")
    if replacement != "ready_dipplin":
        missing.append("replacement")
    if not missing:
        # A board can be nominally complete yet have an attack lock, prevention,
        # or another public mechanic that this coarse causal taxonomy does not
        # safely assign.
        missing.append("other")
    # Keep a stable category order and avoid double counting.
    order = (
        "dipplin",
        "energy",
        "festival",
        "thwackey",
        "replacement",
        "retreat_promotion",
        "other",
    )
    selected = set(missing)
    return tuple(name for name in order if name in selected)


@dataclass
class _Turn:
    ordinal: int
    global_turn: int
    start_active_id: int | None
    start_prizes: int
    latest_board: dict[str, Any]
    productive_attacks: int = 0
    do_wave_attacks: int = 0
    first_hit_kos: int = 0


@dataclass
class SecondBucketTrace:
    hero_seat: int
    actual_order: str = "unknown"
    opening_active_id: int | None = None
    quick_sign_legal: bool = False
    first_productive_attack_own_turn: int | None = None
    first_festival_double_attack_own_turn: int | None = None
    productive_attacks: int = 0
    festival_double_attacks: int = 0
    first_hit_kos: int = 0
    turn_one_board: dict[str, Any] | None = None
    first_attack_board: dict[str, Any] | None = None
    dead_turns: int = 0
    trapped_active_turns: int = 0
    missed_attack_prerequisites: Counter[str] = field(default_factory=Counter)
    turn_records: list[dict[str, Any]] = field(default_factory=list)
    _turn: _Turn | None = None
    _pending_attack_hit: int | None = None
    _pending_attack_ko_counted: bool = False
    _last_prizes: int | None = None
    _max_prizes: int = 0
    _final_prizes: int | None = None

    def _hero_prizes(self, obs: Any) -> int | None:
        state = getattr(obs, "current", None)
        players = list(getattr(state, "players", None) or ()) if state is not None else []
        if not 0 <= int(self.hero_seat) < len(players):
            return None
        return len(getattr(players[int(self.hero_seat)], "prize", None) or ())

    def _record_prize_delta(self, prizes: int | None) -> None:
        if prizes is None:
            return
        self._max_prizes = max(self._max_prizes, prizes)
        if self._last_prizes is not None and prizes < self._last_prizes:
            if (
                self._turn is not None
                and self._pending_attack_hit == 1
                and not self._pending_attack_ko_counted
            ):
                self._turn.first_hit_kos += 1
                self.first_hit_kos += 1
                self._pending_attack_ko_counted = True
        self._last_prizes = prizes
        self._final_prizes = prizes

    def _close_turn(self, board: dict[str, Any] | None = None) -> None:
        turn = self._turn
        if turn is None:
            return
        end_board = dict(board or turn.latest_board)
        if turn.ordinal == 1:
            self.turn_one_board = end_board
        missing = _missed_prerequisites(
            end_board,
            attacks=turn.productive_attacks,
        )
        dead = turn.ordinal >= 2 and turn.productive_attacks == 0
        trapped = bool(
            dead
            and turn.start_active_id in SUPPORT_ACTIVE
            and end_board.get("active_id") == turn.start_active_id
        )
        if dead:
            self.dead_turns += 1
        if trapped:
            self.trapped_active_turns += 1
        if turn.ordinal >= 2 and turn.productive_attacks < 2:
            self.missed_attack_prerequisites.update(missing)
        self.turn_records.append(
            {
                "own_turn": turn.ordinal,
                "global_turn": turn.global_turn,
                "start_active_id": turn.start_active_id,
                "productive_attacks": turn.productive_attacks,
                "do_wave_attacks": turn.do_wave_attacks,
                "first_hit_kos": turn.first_hit_kos,
                "dead_turn": dead,
                "trapped_active": trapped,
                "missed_attack_prerequisites": list(missing),
                "end_board": end_board,
            }
        )
        self._turn = None
        self._pending_attack_hit = None
        self._pending_attack_ko_counted = False

    def observe(self, obs: Any) -> None:
        state = getattr(obs, "current", None)
        if state is None:
            return
        first_player = _int(getattr(state, "firstPlayer", None))
        if first_player in {0, 1}:
            self.actual_order = "first" if self.hero_seat == first_player else "second"
        prizes = self._hero_prizes(obs)
        self._record_prize_delta(prizes)
        global_turn = max(0, _int(getattr(state, "turn", None), 0))
        board = public_board_snapshot(obs, self.hero_seat)
        if board is None:
            return
        hero_turn = _is_hero_turn(global_turn, self.hero_seat, first_player)
        ordinal = _own_turn_ordinal(global_turn, self.hero_seat, first_player)
        if self._turn is not None and self._turn.global_turn != global_turn:
            self._close_turn(board)
        if not hero_turn or ordinal <= 0:
            return
        if self._turn is None:
            self._turn = _Turn(
                ordinal=ordinal,
                global_turn=global_turn,
                start_active_id=board.get("active_id"),
                start_prizes=prizes if prizes is not None else 0,
                latest_board=board,
            )
        else:
            self._turn.latest_board = board
        if ordinal == 1:
            if self.opening_active_id is None:
                self.opening_active_id = board.get("active_id")
            if _int(getattr(state, "yourIndex", None)) == self.hero_seat:
                self.quick_sign_legal = self.quick_sign_legal or any(
                    _int(getattr(option, "attackId", None)) == QUICK_SIGN
                    for option in (getattr(getattr(obs, "select", None), "option", None) or ())
                )

    def _do_wave_productive(self, obs: Any, board: Mapping[str, Any]) -> bool:
        if board.get("active_id") != DIPPLIN or int(board.get("bench_count") or 0) <= 0:
            return False
        try:
            from ptcg_ai.dipplin.damage import project_do_the_wave

            state = obs.current
            hero = state.players[self.hero_seat]
            opponent = state.players[1 - self.hero_seat]
            active = _cards(hero.active)[0]
            target = _cards(opponent.active)[0]
            stadium = _cards(state.stadium)
            projection = project_do_the_wave(
                active,
                target,
                bench_count=len(_cards(hero.bench)),
                black_belt_used=False,
                stadium_id=_card_id(stadium[0]) if stadium else None,
                festival_active=bool(board.get("festival_active")),
            )
            return bool(projection.productive)
        except (AttributeError, IndexError, TypeError, ValueError):
            # The structural fallback remains public and errs conservatively
            # only when an incomplete synthetic/test observation lacks damage
            # metadata.
            return True

    def record_action(self, obs: Any, action: Sequence[int], acting_seat: int) -> None:
        if int(acting_seat) != int(self.hero_seat) or self._turn is None:
            return
        select = getattr(obs, "select", None)
        options = list(getattr(select, "option", None) or ())
        selected = [
            options[int(index)]
            for index in action
            if 0 <= int(index) < len(options)
        ]
        if not any(
            _int(getattr(option, "type", None)) == int(OptionType.ATTACK)
            and _int(getattr(option, "attackId", None)) == DO_THE_WAVE
            for option in selected
        ):
            return
        board = public_board_snapshot(obs, self.hero_seat)
        if board is None:
            return
        self._turn.do_wave_attacks += 1
        hit = self._turn.do_wave_attacks
        self._pending_attack_hit = hit
        self._pending_attack_ko_counted = False
        if not self._do_wave_productive(obs, board):
            return
        self._turn.productive_attacks += 1
        self.productive_attacks += 1
        if self.first_productive_attack_own_turn is None:
            self.first_productive_attack_own_turn = self._turn.ordinal
            self.first_attack_board = board
        if hit >= 2:
            self.festival_double_attacks += 1
            if self.first_festival_double_attack_own_turn is None:
                self.first_festival_double_attack_own_turn = self._turn.ordinal

    def finalize(
        self,
        *,
        completed: bool,
        result_seat: int | None,
        final_observation: Any | None = None,
    ) -> dict[str, Any]:
        if final_observation is not None:
            self.observe(final_observation)
        self._close_turn()
        prizes_taken = max(0, self._max_prizes - (self._final_prizes or 0))
        return {
            "schema": SCHEMA,
            "actual_order": self.actual_order,
            "opening_bucket": (
                opening_bucket(self.opening_active_id, self.quick_sign_legal)
                if self.actual_order == "second"
                else "not_actual_second"
            ),
            "opening_active_id": self.opening_active_id,
            "quick_sign_legal": self.quick_sign_legal,
            "completed": bool(completed),
            "win": bool(completed and result_seat == self.hero_seat),
            "first_productive_attack_own_turn": self.first_productive_attack_own_turn,
            "first_festival_double_attack_own_turn": self.first_festival_double_attack_own_turn,
            "productive_attacks": self.productive_attacks,
            "festival_double_attacks": self.festival_double_attacks,
            "first_hit_kos": self.first_hit_kos,
            "prizes_taken": prizes_taken,
            "turn_one_board": self.turn_one_board,
            "first_attack_board": self.first_attack_board,
            "dead_turns": self.dead_turns,
            "trapped_active_turns": self.trapped_active_turns,
            "missed_attack_prerequisites": dict(
                sorted(self.missed_attack_prerequisites.items())
            ),
            "turn_records": self.turn_records,
            "public_information_contract": {
                "hands_read": False,
                "deck_contents_read": False,
                "prize_identities_read": False,
                "search_begin_input_read": False,
            },
        }


__all__ = [
    "SCHEMA",
    "SecondBucketTrace",
    "opening_bucket",
    "public_board_snapshot",
]
