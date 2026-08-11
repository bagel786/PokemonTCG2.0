"""Immutable public-state snapshots and supplemental planner memory.

The engine changes a Pokemon's top-card serial when it evolves.  This module
therefore exposes both the prompt-local physical ``serial`` and a stable
``lineage_serial`` taken from the underlying Basic in ``preEvolution``.

All readers are deliberately duck-typed: native ``cg.api`` dataclasses, JSON
dictionaries, and reduced test fixtures are accepted.  Missing data produces
an invalid/conservative snapshot instead of an exception.  Opponent hands are
never copied, even if a local simulator accidentally supplies them.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Iterable, Mapping, Sequence

from .cards import (
    APPLIN_DRAGON,
    APPLIN_GRASS,
    APPLIN_LINE,
    BLACK_BELT,
    BOSS,
    BROCK,
    DIPPLIN,
    DO_THE_WAVE,
    FESTIVAL,
    GROOKEY_LINE,
    HILDA,
    LILLIE,
    QUICK_SIGN,
    THWACKEY,
    VOLBEAT,
)


_MISSING = object()
_SUPPORTERS = frozenset({BOSS, BROCK, BLACK_BELT, HILDA, LILLIE})


def _field(value: Any, *names: str, default: Any = None) -> Any:
    if value is None:
        return default
    for name in names:
        if isinstance(value, Mapping) and name in value:
            return value[name]
        if hasattr(value, name):
            return getattr(value, name)
    return default


def _integer(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _optional_integer(value: Any) -> int | None:
    if value is None:
        return None
    result = _integer(value)
    return None if result < 0 else result


def _sequence(value: Any) -> tuple[Any, ...]:
    if value is None or isinstance(value, (str, bytes, Mapping)):
        return ()
    try:
        return tuple(value)
    except TypeError:
        return ()


def _card_id(value: Any) -> int | None:
    found = _field(value, "id", "card_id", "cardId", default=None)
    return _optional_integer(found)


def _serial(value: Any) -> int | None:
    return _optional_integer(_field(value, "serial", default=None))


@dataclass(frozen=True, slots=True)
class CardSnapshot:
    card_id: int
    serial: int
    player_index: int

    @property
    def id(self) -> int:
        return self.card_id

    @classmethod
    def from_value(cls, value: Any, *, default_player: int = -1) -> CardSnapshot | None:
        card_id = _card_id(value)
        serial = _serial(value)
        if card_id is None or serial is None:
            return None
        return cls(
            card_id=card_id,
            serial=serial,
            player_index=_integer(
                _field(value, "playerIndex", "player_index", default=default_player),
                default_player,
            ),
        )


@lru_cache(maxsize=1)
def _metadata_table() -> dict[int, Any]:
    try:
        from cg.api import all_card_data

        return {int(card.cardId): card for card in all_card_data()}
    except Exception:
        # Sterile packaging and unit tests may intentionally lack a loadable
        # native engine.  Snapshot construction must remain fail-closed.
        return {}


@lru_cache(maxsize=1)
def _attack_table() -> dict[int, Any]:
    try:
        from cg.api import all_attack

        return {int(attack.attackId): attack for attack in all_attack()}
    except Exception:
        return {}


def _card_traits(card_id: int) -> tuple[int, int | None, int | None, bool, int, tuple[str, ...]]:
    data = _metadata_table().get(card_id)
    if data is None:
        return 0, None, None, False, 1, ()
    ex = bool(_field(data, "ex", default=False))
    mega_ex = bool(_field(data, "megaEx", "mega_ex", default=False))
    skills: list[str] = []
    for skill in _sequence(_field(data, "skills", default=())):
        name = str(_field(skill, "name", default="") or "")
        text = str(_field(skill, "text", default="") or "")
        lowered = f"{name} {text}".lower()
        if any(token in lowered for token in ("prevent", "no damage", "isn't affected", "not affected")):
            skills.append(f"{name}: {text}".strip(": "))
    return (
        max(0, _integer(_field(data, "retreatCost", "retreat_cost", default=0), 0)),
        _optional_integer(_field(data, "weakness", default=None)),
        _optional_integer(_field(data, "resistance", default=None)),
        ex or mega_ex,
        3 if mega_ex else 2 if ex else 1,
        tuple(skills),
    )


def _can_pay(cost: Sequence[int], energy: Sequence[int]) -> bool:
    """Conservative attack-cost check for public attached energy units."""

    remaining = list(energy)
    # Pay typed requirements before Colorless.  Rainbow (10) can cover a type.
    for requirement in (value for value in cost if value != 0):
        try:
            remaining.remove(requirement)
        except ValueError:
            if 10 in remaining:
                remaining.remove(10)
            else:
                return False
    return len(remaining) >= sum(1 for value in cost if value == 0)


def _attack_ready(card_id: int, energy: tuple[int, ...]) -> bool:
    data = _metadata_table().get(card_id)
    attacks = _sequence(_field(data, "attacks", default=())) if data is not None else ()
    for attack_id in attacks:
        attack = _attack_table().get(_integer(attack_id))
        if attack is not None and _can_pay(
            tuple(_integer(value) for value in _sequence(_field(attack, "energies", default=()))),
            energy,
        ):
            return True
    # Exact-deck fallback used when metadata is unavailable.
    if card_id == DIPPLIN:
        return 1 in energy or 10 in energy
    if card_id == VOLBEAT:
        return bool(energy)
    if card_id == APPLIN_GRASS:
        return 1 in energy or 10 in energy
    if card_id == APPLIN_DRAGON:
        return bool(energy)  # Find Friend costs one Colorless.
    return False


@dataclass(frozen=True, slots=True)
class PokemonSnapshot:
    card_id: int
    serial: int
    lineage_serial: int
    player_index: int
    area: int
    index: int
    hp: int
    max_hp: int
    appear_this_turn: bool
    energies: tuple[int, ...]
    energy_cards: tuple[CardSnapshot, ...]
    tools: tuple[CardSnapshot, ...]
    pre_evolution: tuple[CardSnapshot, ...]
    retreat_cost: int
    weakness: int | None
    resistance: int | None
    rule_box: bool
    prize_count: int
    prevention_effects: tuple[str, ...]
    attack_ready: bool

    @property
    def id(self) -> int:
        return self.card_id

    @property
    def current_serial(self) -> int:
        return self.serial

    @property
    def lineage_key(self) -> tuple[int, int]:
        return self.player_index, self.lineage_serial

    @property
    def energy_count(self) -> int:
        return len(self.energies)

    @property
    def tool_ids(self) -> tuple[int, ...]:
        return tuple(card.card_id for card in self.tools)

    @property
    def remaining_hp(self) -> int:
        return self.hp

    @classmethod
    def from_value(
        cls,
        value: Any,
        *,
        area: int,
        index: int,
        default_player: int,
    ) -> PokemonSnapshot | None:
        card_id = _card_id(value)
        serial = _serial(value)
        if card_id is None or serial is None:
            return None
        player_index = _integer(
            _field(value, "playerIndex", "player_index", default=default_player),
            default_player,
        )
        pre = tuple(
            card
            for raw in _sequence(_field(value, "preEvolution", "pre_evolution", default=()))
            if (card := CardSnapshot.from_value(raw, default_player=player_index)) is not None
        )
        # The engine appends each old top card as evolution proceeds.  The first
        # entry is therefore the underlying Basic and remains stable.
        lineage_serial = pre[0].serial if pre else serial
        energies = tuple(
            integer
            for raw in _sequence(_field(value, "energies", default=()))
            if (integer := _optional_integer(raw)) is not None
        )
        energy_cards = tuple(
            card
            for raw in _sequence(_field(value, "energyCards", "energy_cards", default=()))
            if (card := CardSnapshot.from_value(raw, default_player=player_index)) is not None
        )
        tools = tuple(
            card
            for raw in _sequence(_field(value, "tools", default=()))
            if (card := CardSnapshot.from_value(raw, default_player=player_index)) is not None
        )
        retreat, weakness, resistance, rule_box, prize_count, prevention = _card_traits(card_id)
        hp = max(0, _integer(_field(value, "hp", default=0), 0))
        max_hp = max(hp, _integer(_field(value, "maxHp", "max_hp", default=hp), hp))
        return cls(
            card_id=card_id,
            serial=serial,
            lineage_serial=lineage_serial,
            player_index=player_index,
            area=area,
            index=index,
            hp=hp,
            max_hp=max_hp,
            appear_this_turn=bool(
                _field(value, "appearThisTurn", "appear_this_turn", default=False)
            ),
            energies=energies,
            energy_cards=energy_cards,
            tools=tools,
            pre_evolution=pre,
            retreat_cost=retreat,
            weakness=weakness,
            resistance=resistance,
            rule_box=rule_box,
            prize_count=prize_count,
            prevention_effects=prevention,
            attack_ready=_attack_ready(card_id, energies),
        )


@dataclass(frozen=True, slots=True)
class PlayerSnapshot:
    player_index: int
    active: PokemonSnapshot | None
    bench: tuple[PokemonSnapshot, ...]
    bench_max: int
    deck_count: int
    discard: tuple[CardSnapshot, ...]
    prizes: tuple[CardSnapshot | None, ...]
    hand_count: int
    hand: tuple[CardSnapshot, ...]
    hand_known: bool
    poisoned: bool
    burned: bool
    asleep: bool
    paralyzed: bool
    confused: bool

    @property
    def in_play(self) -> tuple[PokemonSnapshot, ...]:
        return ((self.active,) if self.active is not None else ()) + self.bench

    @property
    def prize_count(self) -> int:
        return len(self.prizes)

    @property
    def hand_ids(self) -> tuple[int, ...]:
        return tuple(card.card_id for card in self.hand)

    @property
    def discard_ids(self) -> tuple[int, ...]:
        return tuple(card.card_id for card in self.discard)

    @classmethod
    def empty(cls, player_index: int, *, hand_known: bool) -> PlayerSnapshot:
        return cls(
            player_index=player_index,
            active=None,
            bench=(),
            bench_max=0,
            deck_count=0,
            discard=(),
            prizes=(),
            hand_count=0,
            hand=(),
            hand_known=hand_known,
            poisoned=False,
            burned=False,
            asleep=False,
            paralyzed=False,
            confused=False,
        )

    @classmethod
    def from_value(
        cls,
        value: Any,
        *,
        player_index: int,
        expose_hand: bool,
    ) -> PlayerSnapshot:
        if value is None:
            return cls.empty(player_index, hand_known=expose_hand)
        active_values = _sequence(_field(value, "active", default=()))
        active = (
            PokemonSnapshot.from_value(
                active_values[0], area=4, index=0, default_player=player_index
            )
            if active_values and active_values[0] is not None
            else None
        )
        bench = tuple(
            pokemon
            for index, raw in enumerate(_sequence(_field(value, "bench", default=())))
            if (
                pokemon := PokemonSnapshot.from_value(
                    raw, area=5, index=index, default_player=player_index
                )
            )
            is not None
        )
        discard = tuple(
            card
            for raw in _sequence(_field(value, "discard", default=()))
            if (card := CardSnapshot.from_value(raw, default_player=player_index)) is not None
        )
        prizes = tuple(
            CardSnapshot.from_value(raw, default_player=player_index) if raw is not None else None
            for raw in _sequence(_field(value, "prize", "prizes", default=()))
        )
        raw_hand = _sequence(_field(value, "hand", default=())) if expose_hand else ()
        hand = tuple(
            card
            for raw in raw_hand
            if (card := CardSnapshot.from_value(raw, default_player=player_index)) is not None
        )
        return cls(
            player_index=player_index,
            active=active,
            bench=bench,
            bench_max=max(0, _integer(_field(value, "benchMax", "bench_max", default=0), 0)),
            deck_count=max(0, _integer(_field(value, "deckCount", "deck_count", default=0), 0)),
            discard=discard,
            prizes=prizes,
            hand_count=max(0, _integer(_field(value, "handCount", "hand_count", default=len(hand)), len(hand))),
            hand=hand,
            hand_known=expose_hand,
            poisoned=bool(_field(value, "poisoned", default=False)),
            burned=bool(_field(value, "burned", default=False)),
            asleep=bool(_field(value, "asleep", default=False)),
            paralyzed=bool(_field(value, "paralyzed", default=False)),
            confused=bool(_field(value, "confused", default=False)),
        )


@dataclass(frozen=True, slots=True)
class OptionSnapshot:
    type: int
    number: int | None
    area: int | None
    index: int | None
    player_index: int | None
    tool_index: int | None
    energy_index: int | None
    count: int | None
    in_play_area: int | None
    in_play_index: int | None
    attack_id: int | None
    card_id: int | None
    serial: int | None

    @classmethod
    def from_value(cls, value: Any) -> OptionSnapshot:
        return cls(
            type=_integer(_field(value, "type", default=-1)),
            number=_optional_integer(_field(value, "number", default=None)),
            area=_optional_integer(_field(value, "area", default=None)),
            index=_optional_integer(_field(value, "index", default=None)),
            player_index=_optional_integer(
                _field(value, "playerIndex", "player_index", default=None)
            ),
            tool_index=_optional_integer(_field(value, "toolIndex", "tool_index", default=None)),
            energy_index=_optional_integer(
                _field(value, "energyIndex", "energy_index", default=None)
            ),
            count=_optional_integer(_field(value, "count", default=None)),
            in_play_area=_optional_integer(
                _field(value, "inPlayArea", "in_play_area", default=None)
            ),
            in_play_index=_optional_integer(
                _field(value, "inPlayIndex", "in_play_index", default=None)
            ),
            attack_id=_optional_integer(_field(value, "attackId", "attack_id", default=None)),
            card_id=_optional_integer(_field(value, "cardId", "card_id", default=None)),
            serial=_optional_integer(_field(value, "serial", default=None)),
        )


@dataclass(frozen=True, slots=True)
class SelectSnapshot:
    type: int
    context: int
    min_count: int
    max_count: int
    options: tuple[OptionSnapshot, ...]
    deck: tuple[CardSnapshot, ...]
    context_card: CardSnapshot | None
    effect: CardSnapshot | None
    parent_card_id: int | None
    parent_serial: int | None
    parent_source: str

    @classmethod
    def empty(cls) -> SelectSnapshot:
        return cls(-1, -1, 0, 0, (), (), None, None, None, None, "none")

    @classmethod
    def from_value(cls, value: Any, *, default_player: int) -> SelectSnapshot:
        if value is None:
            return cls.empty()
        context_card = CardSnapshot.from_value(
            _field(value, "contextCard", "context_card", default=None),
            default_player=default_player,
        )
        effect = CardSnapshot.from_value(
            _field(value, "effect", default=None), default_player=default_player
        )
        parent = effect or context_card
        return cls(
            type=_integer(_field(value, "type", default=-1)),
            context=_integer(_field(value, "context", default=-1)),
            min_count=max(0, _integer(_field(value, "minCount", "min_count", default=0), 0)),
            max_count=max(0, _integer(_field(value, "maxCount", "max_count", default=0), 0)),
            options=tuple(
                OptionSnapshot.from_value(raw)
                for raw in _sequence(_field(value, "option", "options", default=()))
            ),
            deck=tuple(
                card
                for raw in _sequence(_field(value, "deck", default=()))
                if (card := CardSnapshot.from_value(raw, default_player=default_player)) is not None
            ),
            context_card=context_card,
            effect=effect,
            parent_card_id=parent.card_id if parent is not None else None,
            parent_serial=parent.serial if parent is not None else None,
            parent_source="effect" if effect is not None else "context_card" if context_card is not None else "none",
        )


@dataclass(frozen=True, slots=True)
class SemanticAction:
    """Prompt-independent description of one committed final selection."""

    kind: str
    card_id: int | None = None
    source_serial: int | None = None
    source_lineage: int | None = None
    target_serial: int | None = None
    target_lineage: int | None = None
    attack_id: int | None = None
    selected_indices: tuple[int, ...] = ()
    details: tuple[tuple[str, int | float | str | bool], ...] = ()
    origin: str = "policy"


@dataclass
class PlanMemory:
    """Cloneable facts not represented directly by the current observation.

    Observation flags remain authoritative.  This memory supplies only
    prompt-spanning semantic history and physical-to-lineage intent.
    """

    game_epoch: int = 0
    global_turn: int | None = None
    action_history: list[SemanticAction] = field(default_factory=list)
    quick_sign_used: bool = False
    used_thwackey_lineages: set[int] = field(default_factory=set)
    festival_attack_count: int = 0
    second_festival_attack_offered: bool = False
    second_festival_attack_taken: bool = False
    black_belt_used: bool = False
    supporter_played: bool = False
    energy_attached: bool = False
    retreated: bool = False
    primary_attacker_serial: int | None = None
    primary_attacker_lineage: int | None = None
    replacement_attacker_serial: int | None = None
    replacement_attacker_lineage: int | None = None
    intended_thwackey_lineages: set[int] = field(default_factory=set)
    trapped_active_serial: int | None = None
    _committed_decision_keys: set[Any] = field(default_factory=set, repr=False)
    _pending_public_events: Counter[tuple[Any, ...]] = field(default_factory=Counter, repr=False)
    _observed_batches: set[tuple[Any, ...]] = field(default_factory=set, repr=False)

    @property
    def first_festival_attack_made(self) -> bool:
        return self.festival_attack_count >= 1

    @property
    def each_thwackey_used(self) -> frozenset[int]:
        return frozenset(self.used_thwackey_lineages)

    def clone(self) -> PlanMemory:
        return deepcopy(self)

    fork = clone

    def reset_turn(self, global_turn: int | None) -> None:
        self.global_turn = global_turn
        self.action_history.clear()
        self.quick_sign_used = False
        self.used_thwackey_lineages.clear()
        self.festival_attack_count = 0
        self.second_festival_attack_offered = False
        self.second_festival_attack_taken = False
        self.black_belt_used = False
        self.supporter_played = False
        self.energy_attached = False
        self.retreated = False
        self._committed_decision_keys.clear()
        self._pending_public_events.clear()
        self._observed_batches.clear()

    def reset_game(self) -> None:
        self.game_epoch += 1
        self.reset_turn(None)
        self.primary_attacker_serial = None
        self.primary_attacker_lineage = None
        self.replacement_attacker_serial = None
        self.replacement_attacker_lineage = None
        self.intended_thwackey_lineages.clear()
        self.trapped_active_serial = None

    def commit(self, action: SemanticAction, *, decision_key: Any = None) -> bool:
        """Record the one final action selected for a prompt.

        Supplying a stable ``decision_key`` makes retries idempotent.  Without
        one, repeated actions are intentionally retained because two Festival
        attacks can have identical semantic fields.
        """

        if decision_key is not None:
            try:
                if decision_key in self._committed_decision_keys:
                    return False
                self._committed_decision_keys.add(decision_key)
            except TypeError:
                decision_key = repr(decision_key)
                if decision_key in self._committed_decision_keys:
                    return False
                self._committed_decision_keys.add(decision_key)
        self.action_history.append(action)
        kind = action.kind.strip().upper()
        if kind in {"ATTACK", "SECOND_ATTACK"}:
            if action.attack_id == QUICK_SIGN:
                self.quick_sign_used = True
            if action.attack_id == DO_THE_WAVE:
                self.festival_attack_count += 1
                if self.festival_attack_count >= 2 or kind == "SECOND_ATTACK":
                    self.second_festival_attack_taken = True
            self._pending_public_events[("attack", action.attack_id, action.source_serial)] += 1
        elif kind in {"ABILITY", "THWACKEY_ABILITY", "BOOM_BOOM_GROOVE"}:
            lineage = action.source_lineage if action.source_lineage is not None else action.source_serial
            if lineage is not None and action.card_id in {None, THWACKEY}:
                self.used_thwackey_lineages.add(lineage)
        elif kind in {"PLAY", "PLAY_SUPPORTER", "SUPPORTER"}:
            self.supporter_played = (
                self.supporter_played
                or kind != "PLAY"
                or action.card_id in _SUPPORTERS
            )
            self.black_belt_used = self.black_belt_used or action.card_id == BLACK_BELT
            self._pending_public_events[("play", action.card_id, action.source_serial)] += 1
        elif kind in {"ATTACH", "ENERGY_ATTACH"}:
            self.energy_attached = True
        elif kind == "RETREAT":
            self.retreated = True
        return True

    commit_semantic = commit

    def _observe_logs(self, logs: tuple[Any, ...], hero_index: int, turn_changed: bool) -> None:
        if not logs:
            return
        batch = tuple(
            (
                _integer(_field(log, "type", default=-1)),
                _optional_integer(_field(log, "playerIndex", "player_index", default=None)),
                _optional_integer(_field(log, "cardId", "card_id", default=None)),
                _optional_integer(_field(log, "serial", default=None)),
                _optional_integer(_field(log, "attackId", "attack_id", default=None)),
            )
            for log in logs
        )
        signature = (self.global_turn, batch)
        if signature in self._observed_batches:
            return
        self._observed_batches.add(signature)

        # If the global turn just changed, logs before the last TURN_START
        # describe the preceding turn and must not repopulate reset flags.
        start = 0
        turn_starts = [i for i, row in enumerate(batch) if row[0] == 2]
        if turn_changed:
            if not turn_starts:
                return
            start = turn_starts[-1] + 1
        for log_type, player, card_id, serial, attack_id in batch[start:]:
            if player != hero_index:
                continue
            if log_type == 15:  # LogType.ATTACK
                key = ("attack", attack_id, serial)
                if self._pending_public_events[key] > 0:
                    self._pending_public_events[key] -= 1
                    continue
                if attack_id == QUICK_SIGN:
                    self.quick_sign_used = True
                elif attack_id == DO_THE_WAVE:
                    self.festival_attack_count += 1
                    self.second_festival_attack_taken = self.festival_attack_count >= 2
            elif log_type == 10:  # LogType.PLAY
                key = ("play", card_id, serial)
                if self._pending_public_events[key] > 0:
                    self._pending_public_events[key] -= 1
                    continue
                if card_id == BLACK_BELT:
                    self.black_belt_used = True

    def reconcile(
        self,
        *,
        global_turn: int,
        hero_index: int,
        supporter_played: bool,
        energy_attached: bool,
        retreated: bool,
        second_attack_offered: bool,
        logs: Iterable[Any] = (),
        in_play: Iterable[PokemonSnapshot] = (),
    ) -> None:
        """Reconcile supplemental memory with a fresh public observation."""

        turn_changed = self.global_turn != global_turn
        if turn_changed:
            self.reset_turn(global_turn)
        self.supporter_played = bool(supporter_played)
        self.energy_attached = bool(energy_attached)
        self.retreated = bool(retreated)
        self.second_festival_attack_offered = bool(second_attack_offered)
        self._observe_logs(tuple(logs), hero_index, turn_changed)

        by_lineage = {pokemon.lineage_serial: pokemon.serial for pokemon in in_play}
        if self.primary_attacker_lineage in by_lineage:
            self.primary_attacker_serial = by_lineage[self.primary_attacker_lineage]
        if self.replacement_attacker_lineage in by_lineage:
            self.replacement_attacker_serial = by_lineage[self.replacement_attacker_lineage]


def _counts(cards: Iterable[CardSnapshot]) -> tuple[tuple[int, int], ...]:
    return tuple(sorted(Counter(card.card_id for card in cards).items()))


def _actual_order(your_index: int, first_player: int) -> tuple[str, bool | None]:
    if your_index not in {0, 1} or first_player not in {0, 1}:
        return "UNKNOWN", None
    is_first = your_index == first_player
    return ("FIRST" if is_first else "SECOND"), is_first


def _own_turn_ordinal(global_turn: int, your_index: int, first_player: int) -> int:
    if global_turn <= 0 or your_index not in {0, 1} or first_player not in {0, 1}:
        return 0
    first_own_turn = 1 if your_index == first_player else 2
    if global_turn < first_own_turn:
        return 0
    return ((global_turn - first_own_turn) // 2) + 1


def _is_our_turn(global_turn: int, your_index: int, first_player: int) -> bool:
    if global_turn <= 0 or your_index not in {0, 1} or first_player not in {0, 1}:
        return False
    current_player = first_player if global_turn % 2 == 1 else 1 - first_player
    return current_player == your_index


def _infer_phase(
    global_turn: int,
    select: SelectSnapshot,
    hero: PlayerSnapshot,
    festival_active: bool,
) -> str:
    if global_turn == 0 or select.context in {1, 2, 41, 42}:
        return "OPENING_SETUP"
    if hero.prize_count <= 2:
        return "CLOSE_GAME"
    in_play = hero.in_play
    active = hero.active
    if select.type == 6 and select.context == 35:
        return "MAXIMIZE_PRIZES_NOW"
    if active is not None and active.card_id == DIPPLIN and active.attack_ready:
        if any(pokemon.card_id in APPLIN_LINE for pokemon in hero.bench):
            return "MAXIMIZE_PRIZES_NOW" if festival_active else "BUILD_REPLACEMENT"
        return "BUILD_REPLACEMENT"
    if not any(pokemon.card_id in APPLIN_LINE for pokemon in in_play) and any(
        card.card_id in APPLIN_LINE for card in hero.discard
    ):
        return "RECOVER"
    return "ENABLE_FIRST_ATTACK"


def _strategic_board_refs(
    hero: PlayerSnapshot,
    memory: PlanMemory | None,
) -> tuple[
    PokemonSnapshot | None,
    PokemonSnapshot | None,
    PokemonSnapshot | None,
]:
    """Rebuild attacker/replacement/trapped identities from the live board.

    A still-live remembered replacement breaks ties between equivalent bench
    lines, but it cannot resurrect a missing Pokemon or override the Active
    Dipplin.  Physical serials are always refreshed from the selected lineage.
    """

    lines = tuple(pokemon for pokemon in hero.in_play if pokemon.card_id in APPLIN_LINE)
    by_lineage = {pokemon.lineage_serial: pokemon for pokemon in lines}
    active_dipplin = (
        hero.active
        if hero.active is not None and hero.active.card_id == DIPPLIN
        else None
    )
    active_quick_sign = (
        hero.active
        if hero.active is not None
        and hero.active.card_id == VOLBEAT
        and hero.active.attack_ready
        else None
    )
    remembered_primary = (
        by_lineage.get(memory.primary_attacker_lineage)
        if memory is not None and memory.primary_attacker_lineage is not None
        else None
    )
    primary = active_dipplin or active_quick_sign or remembered_primary or next(
        (
            pokemon
            for pokemon in lines
            if pokemon.card_id == DIPPLIN and pokemon.attack_ready
        ),
        None,
    )
    if primary is None:
        primary = next((pokemon for pokemon in lines if pokemon.card_id == DIPPLIN), None)
    if primary is None:
        primary = next(iter(lines), None)

    replacement_candidates = tuple(
        pokemon
        for pokemon in hero.bench
        if pokemon.card_id in APPLIN_LINE
        and (primary is None or pokemon.lineage_serial != primary.lineage_serial)
    )
    remembered_replacement = None
    if memory is not None and memory.replacement_attacker_lineage is not None:
        remembered_replacement = next(
            (
                pokemon
                for pokemon in replacement_candidates
                if pokemon.lineage_serial == memory.replacement_attacker_lineage
            ),
            None,
        )
    replacement = remembered_replacement or next(
        (
            pokemon
            for pokemon in replacement_candidates
            if pokemon.card_id == DIPPLIN and pokemon.attack_ready
        ),
        None,
    )
    if replacement is None:
        replacement = next(
            (pokemon for pokemon in replacement_candidates if pokemon.card_id == DIPPLIN),
            None,
        )
    if replacement is None:
        replacement = next(iter(replacement_candidates), None)
    trapped = (
        hero.active
        if hero.active is not None
        and hero.active.card_id not in APPLIN_LINE
        and hero.active is not active_quick_sign
        else None
    )
    return primary, replacement, trapped


@dataclass(frozen=True, slots=True)
class PlanSnapshot:
    valid: bool
    global_turn: int
    turn_action_count: int
    your_index: int
    first_player: int
    actual_order: str
    is_first: bool | None
    own_turn_ordinal: int
    current_turn_is_ours: bool
    phase: str
    result: int
    supporter_played: bool
    stadium_played: bool
    energy_attached: bool
    retreated: bool
    stadium: tuple[CardSnapshot, ...]
    looking: tuple[CardSnapshot, ...]
    festival_active: bool
    hero: PlayerSnapshot
    opponent: PlayerSnapshot
    select: SelectSnapshot
    parent_card_id: int | None
    parent_serial: int | None
    action_history: tuple[SemanticAction, ...]
    quick_sign_used: bool
    used_thwackey_lineages: frozenset[int]
    first_festival_attack_made: bool
    second_festival_attack_offered: bool
    second_festival_attack_taken: bool
    black_belt_used: bool
    primary_attacker_serial: int | None
    primary_attacker_lineage: int | None
    replacement_attacker_serial: int | None
    replacement_attacker_lineage: int | None
    trapped_active_serial: int | None
    hand_counts: tuple[tuple[int, int], ...]
    discard_counts: tuple[tuple[int, int], ...]

    @property
    def active(self) -> PokemonSnapshot | None:
        return self.hero.active

    @property
    def bench(self) -> tuple[PokemonSnapshot, ...]:
        return self.hero.bench

    @property
    def hand(self) -> tuple[CardSnapshot, ...]:
        return self.hero.hand

    @property
    def discard(self) -> tuple[CardSnapshot, ...]:
        return self.hero.discard

    @property
    def our_pokemon(self) -> tuple[PokemonSnapshot, ...]:
        return self.hero.in_play

    @property
    def opponent_pokemon(self) -> tuple[PokemonSnapshot, ...]:
        return self.opponent.in_play

    @property
    def applin_lines(self) -> tuple[PokemonSnapshot, ...]:
        return tuple(pokemon for pokemon in self.our_pokemon if pokemon.card_id in APPLIN_LINE)

    @property
    def grookey_lines(self) -> tuple[PokemonSnapshot, ...]:
        return tuple(pokemon for pokemon in self.our_pokemon if pokemon.card_id in GROOKEY_LINE)

    @property
    def volbeats(self) -> tuple[PokemonSnapshot, ...]:
        return tuple(pokemon for pokemon in self.our_pokemon if pokemon.card_id == VOLBEAT)

    @property
    def thwackeys(self) -> tuple[PokemonSnapshot, ...]:
        return tuple(pokemon for pokemon in self.our_pokemon if pokemon.card_id == THWACKEY)

    @property
    def second_attack_currently_offered(self) -> bool:
        return self.second_festival_attack_offered

    def hand_count(self, card_id: int) -> int:
        return dict(self.hand_counts).get(card_id, 0)

    def discard_count(self, card_id: int) -> int:
        return dict(self.discard_counts).get(card_id, 0)

    @classmethod
    def from_observation(
        cls,
        observation: Any,
        memory: PlanMemory | None = None,
        *,
        phase: str | Any | None = None,
    ) -> PlanSnapshot:
        state = _field(observation, "current", default=None)
        if state is None:
            if memory is not None:
                memory.reset_game()
            empty_hero = PlayerSnapshot.empty(-1, hand_known=True)
            empty_opponent = PlayerSnapshot.empty(-1, hand_known=False)
            return cls(
                valid=False,
                global_turn=0,
                turn_action_count=0,
                your_index=-1,
                first_player=-1,
                actual_order="UNKNOWN",
                is_first=None,
                own_turn_ordinal=0,
                current_turn_is_ours=False,
                phase="OPENING_SETUP",
                result=-1,
                supporter_played=False,
                stadium_played=False,
                energy_attached=False,
                retreated=False,
                stadium=(),
                looking=(),
                festival_active=False,
                hero=empty_hero,
                opponent=empty_opponent,
                select=SelectSnapshot.empty(),
                parent_card_id=None,
                parent_serial=None,
                action_history=(),
                quick_sign_used=False,
                used_thwackey_lineages=frozenset(),
                first_festival_attack_made=False,
                second_festival_attack_offered=False,
                second_festival_attack_taken=False,
                black_belt_used=False,
                primary_attacker_serial=None,
                primary_attacker_lineage=None,
                replacement_attacker_serial=None,
                replacement_attacker_lineage=None,
                trapped_active_serial=None,
                hand_counts=(),
                discard_counts=(),
            )

        global_turn = max(0, _integer(_field(state, "turn", default=0), 0))
        your_index = _integer(_field(state, "yourIndex", "your_index", default=-1))
        first_player = _integer(_field(state, "firstPlayer", "first_player", default=-1))
        players = _sequence(_field(state, "players", default=()))
        hero_value = players[your_index] if your_index in {0, 1} and your_index < len(players) else None
        opponent_index = 1 - your_index if your_index in {0, 1} else -1
        opponent_value = (
            players[opponent_index]
            if opponent_index in {0, 1} and opponent_index < len(players)
            else None
        )
        hero = PlayerSnapshot.from_value(hero_value, player_index=your_index, expose_hand=True)
        # Never expose an opponent hand, even if the supplied object contains one.
        opponent = PlayerSnapshot.from_value(
            opponent_value, player_index=opponent_index, expose_hand=False
        )
        select = SelectSnapshot.from_value(
            _field(observation, "select", default=None), default_player=your_index
        )
        stadium = tuple(
            card
            for raw in _sequence(_field(state, "stadium", default=()))
            if (card := CardSnapshot.from_value(raw, default_player=your_index)) is not None
        )
        looking = tuple(
            card
            for raw in _sequence(_field(state, "looking", default=()))
            if raw is not None
            and (card := CardSnapshot.from_value(raw, default_player=your_index)) is not None
        )
        supporter_played = bool(
            _field(state, "supporterPlayed", "supporter_played", default=False)
        )
        energy_attached = bool(
            _field(state, "energyAttached", "energy_attached", default=False)
        )
        retreated = bool(_field(state, "retreated", default=False))
        second_offered = (
            select.type == 6
            and select.context == 35
            and any(option.attack_id == DO_THE_WAVE for option in select.options)
        )
        if memory is not None:
            memory.reconcile(
                global_turn=global_turn,
                hero_index=your_index,
                supporter_played=supporter_played,
                energy_attached=energy_attached,
                retreated=retreated,
                second_attack_offered=second_offered,
                logs=_sequence(_field(observation, "logs", default=())),
                in_play=hero.in_play,
            )
        primary, replacement, trapped = _strategic_board_refs(hero, memory)
        if memory is not None:
            memory.primary_attacker_serial = primary.serial if primary is not None else None
            memory.primary_attacker_lineage = (
                primary.lineage_serial if primary is not None else None
            )
            memory.replacement_attacker_serial = (
                replacement.serial if replacement is not None else None
            )
            memory.replacement_attacker_lineage = (
                replacement.lineage_serial if replacement is not None else None
            )
            memory.intended_thwackey_lineages.clear()
            memory.intended_thwackey_lineages.update(
                pokemon.lineage_serial for pokemon in hero.in_play if pokemon.card_id == THWACKEY
            )
            memory.trapped_active_serial = trapped.serial if trapped is not None else None
        festival_active = any(card.card_id == FESTIVAL for card in stadium)
        phase_value = phase.value if hasattr(phase, "value") else phase
        if phase_value is None:
            phase_value = _infer_phase(global_turn, select, hero, festival_active)
        actual_order, is_first = _actual_order(your_index, first_player)
        return cls(
            valid=your_index in {0, 1} and hero_value is not None,
            global_turn=global_turn,
            turn_action_count=max(
                0, _integer(_field(state, "turnActionCount", "turn_action_count", default=0), 0)
            ),
            your_index=your_index,
            first_player=first_player,
            actual_order=actual_order,
            is_first=is_first,
            own_turn_ordinal=_own_turn_ordinal(global_turn, your_index, first_player),
            current_turn_is_ours=_is_our_turn(global_turn, your_index, first_player),
            phase=str(phase_value),
            result=_integer(_field(state, "result", default=-1)),
            supporter_played=supporter_played,
            stadium_played=bool(
                _field(state, "stadiumPlayed", "stadium_played", default=False)
            ),
            energy_attached=energy_attached,
            retreated=retreated,
            stadium=stadium,
            looking=looking,
            festival_active=festival_active,
            hero=hero,
            opponent=opponent,
            select=select,
            parent_card_id=select.parent_card_id,
            parent_serial=select.parent_serial,
            action_history=tuple(memory.action_history) if memory is not None else (),
            quick_sign_used=memory.quick_sign_used if memory is not None else False,
            used_thwackey_lineages=(
                frozenset(memory.used_thwackey_lineages) if memory is not None else frozenset()
            ),
            first_festival_attack_made=(
                memory.first_festival_attack_made if memory is not None else False
            ),
            second_festival_attack_offered=second_offered,
            second_festival_attack_taken=(
                memory.second_festival_attack_taken if memory is not None else False
            ),
            black_belt_used=memory.black_belt_used if memory is not None else False,
            primary_attacker_serial=(
                memory.primary_attacker_serial if memory is not None else (
                    primary.serial if primary is not None else None
                )
            ),
            primary_attacker_lineage=(
                memory.primary_attacker_lineage if memory is not None else (
                    primary.lineage_serial if primary is not None else None
                )
            ),
            replacement_attacker_serial=(
                memory.replacement_attacker_serial if memory is not None else (
                    replacement.serial if replacement is not None else None
                )
            ),
            replacement_attacker_lineage=(
                memory.replacement_attacker_lineage if memory is not None else (
                    replacement.lineage_serial if replacement is not None else None
                )
            ),
            trapped_active_serial=(
                memory.trapped_active_serial if memory is not None else (
                    trapped.serial if trapped is not None else None
                )
            ),
            hand_counts=_counts(hero.hand),
            discard_counts=_counts(hero.discard),
        )


def build_snapshot(
    observation: Any,
    memory: PlanMemory | None = None,
    *,
    phase: str | Any | None = None,
) -> PlanSnapshot:
    return PlanSnapshot.from_observation(observation, memory, phase=phase)


# Explicit name for callers that want to distinguish the public immutable value
# from ``PlanMemory``.  The dedicated runtime uses ``PlanSnapshot`` throughout.
ObservationSnapshot = PlanSnapshot
