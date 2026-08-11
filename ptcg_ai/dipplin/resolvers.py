"""Parent-aware prompt resolvers for FESTIVAL-D0.

Engine contexts are intentionally not treated as globally unique.  Dispatch uses
selection type, context, parent effect, and the shape of the legal options.  Each
resolver returns an intent; the agent performs one final legality sanitation and
commits only the final action.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterable, Sequence

from cg.api import AreaType, CardType, OptionType, SelectContext, SelectType, all_card_data

from .cards import (
    APPLIN_DRAGON,
    APPLIN_GRASS,
    BOSS,
    BROCK,
    BUG_SET,
    DIPPLIN,
    DO_THE_WAVE,
    GRASS_ENERGY,
    GROOKEY,
    HILDA,
    NIGHT_STRETCHER,
    POFFIN,
    POKE_PAD,
    QUICK_SIGN,
    SACRED_ASH,
    SHAYMIN,
    THWACKEY,
    VOLBEAT,
)
from .plan import MacroPlan, tutor_prerequisite_order


@dataclass(frozen=True)
class SelectionIntent:
    ranked_indices: tuple[int, ...]
    desired_count: int
    resolver: str
    reason: str
    known_context: bool = True


def _int(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def effect_id(obs: Any) -> int | None:
    effect = getattr(getattr(obs, "select", None), "effect", None)
    value = getattr(effect, "id", None)
    return _int(value) if value is not None else None


def context_card_id(obs: Any) -> int | None:
    card = getattr(getattr(obs, "select", None), "contextCard", None)
    value = getattr(card, "id", None)
    return _int(value) if value is not None else None


def _zone(obs: Any, area: Any, player_index: Any = None) -> Sequence[Any]:
    state = getattr(obs, "current", None)
    if state is None or area is None:
        return ()
    area_value = _int(area)
    owner = _int(player_index, _int(getattr(state, "yourIndex", None), 0))
    if area_value == int(AreaType.LOOKING):
        return tuple(getattr(state, "looking", None) or [])
    if area_value == int(AreaType.STADIUM):
        return tuple(getattr(state, "stadium", None) or [])
    if area_value == int(AreaType.DECK):
        return tuple(getattr(getattr(obs, "select", None), "deck", None) or [])
    players = list(getattr(state, "players", None) or [])
    if not 0 <= owner < len(players):
        return ()
    player = players[owner]
    mapping = {
        int(AreaType.HAND): getattr(player, "hand", None) or [],
        int(AreaType.DISCARD): getattr(player, "discard", None) or [],
        int(AreaType.ACTIVE): getattr(player, "active", None) or [],
        int(AreaType.BENCH): getattr(player, "bench", None) or [],
        int(AreaType.PRIZE): getattr(player, "prize", None) or [],
    }
    return tuple(mapping.get(area_value, ()))


def zone_card(obs: Any, area: Any, index: Any, player_index: Any = None) -> Any | None:
    position = _int(index)
    cards = _zone(obs, area, player_index)
    return cards[position] if 0 <= position < len(cards) else None


def option_source(obs: Any, option: Any) -> Any | None:
    option_type = _int(getattr(option, "type", None))
    state = getattr(obs, "current", None)
    owner = _int(getattr(state, "yourIndex", None), 0) if state is not None else 0
    if option_type == int(OptionType.PLAY):
        return zone_card(obs, AreaType.HAND, getattr(option, "index", None), owner)
    return zone_card(
        obs,
        getattr(option, "area", None),
        getattr(option, "index", None),
        getattr(option, "playerIndex", None),
    )


def option_target(obs: Any, option: Any) -> Any | None:
    state = getattr(obs, "current", None)
    owner = _int(getattr(state, "yourIndex", None), 0) if state is not None else 0
    return zone_card(
        obs,
        getattr(option, "inPlayArea", None),
        getattr(option, "inPlayIndex", None),
        owner,
    )


def option_card_id(obs: Any, index: int) -> int:
    options = getattr(getattr(obs, "select", None), "option", None) or []
    if not 0 <= index < len(options):
        return -1
    card = option_source(obs, options[index])
    return _int(getattr(card, "id", None))


def option_target_id(obs: Any, index: int) -> int:
    options = getattr(getattr(obs, "select", None), "option", None) or []
    if not 0 <= index < len(options):
        return -1
    card = option_target(obs, options[index])
    return _int(getattr(card, "id", None))


def _rank_by_ids(obs: Any, priorities: Iterable[int]) -> list[int]:
    priority = list(priorities)
    values: dict[int, int] = {}
    for index, card_id in enumerate(priority):
        # Repeated IDs express availability in later tiers; the first (highest)
        # tier must not be overwritten by the final occurrence.
        values.setdefault(card_id, len(priority) - index)
    indices = list(range(len(getattr(obs.select, "option", None) or [])))
    return sorted(indices, key=lambda index: (values.get(option_card_id(obs, index), 0), -index), reverse=True)


def _in_play(player: Any) -> tuple[Any, ...]:
    if player is None:
        return ()
    return tuple(
        card
        for card in tuple(getattr(player, "active", None) or ()) + tuple(getattr(player, "bench", None) or ())
        if card is not None
    )


def _hero(obs: Any) -> Any | None:
    state = getattr(obs, "current", None)
    players = list(getattr(state, "players", None) or []) if state is not None else []
    index = _int(getattr(state, "yourIndex", None), 0) if state is not None else 0
    return players[index] if 0 <= index < len(players) else None


def _board_counts(obs: Any) -> dict[int, int]:
    result: dict[int, int] = {}
    for card in _in_play(_hero(obs)):
        card_id = _int(getattr(card, "id", None))
        result[card_id] = result.get(card_id, 0) + 1
    return result


@lru_cache(maxsize=1)
def _metadata() -> dict[int, Any]:
    try:
        return {int(card.cardId): card for card in all_card_data()}
    except Exception:
        return {}


def _is_rule_box(card: Any) -> bool:
    data = _metadata().get(_int(getattr(card, "id", None)))
    return bool(data is not None and (getattr(data, "ex", False) or getattr(data, "megaEx", False)))


def _prize_value(card: Any) -> int:
    data = _metadata().get(_int(getattr(card, "id", None)))
    if data is None:
        return 1
    return 3 if bool(getattr(data, "megaEx", False)) else 2 if bool(getattr(data, "ex", False)) else 1


class PromptResolver:
    """Resolve every non-main prompt from its exact parent contract."""

    def __init__(self, *, go_first: bool = True) -> None:
        self.go_first = bool(go_first)

    def resolve(self, obs: Any, plan: MacroPlan, memory: Any = None) -> SelectionIntent:
        select = obs.select
        select_type = _int(getattr(select, "type", None))
        context = _int(getattr(select, "context", None))
        parent = effect_id(obs)

        if select_type == int(SelectType.YES_NO) and context == int(SelectContext.IS_FIRST):
            wanted = OptionType.YES if self.go_first else OptionType.NO
            ranked = [i for i, option in enumerate(select.option) if _int(option.type) == int(wanted)]
            ranked.extend(i for i in range(len(select.option)) if i not in ranked)
            return SelectionIntent(tuple(ranked), 1, "is_first", "Quick Sign opening order")

        if context == int(SelectContext.SETUP_ACTIVE_POKEMON):
            return self._setup_active(obs)
        if context == int(SelectContext.SETUP_BENCH_POKEMON):
            return self._setup_bench(obs)

        # Festival Lead's second strike is an optional ATTACK/ATTACK prompt,
        # never a main action.  Selecting it is a hard invariant.
        if select_type == int(SelectType.ATTACK) and context == int(SelectContext.ATTACK):
            attacks = [
                i
                for i, option in enumerate(select.option)
                if _int(getattr(option, "type", None)) == int(OptionType.ATTACK)
                and _int(getattr(option, "attackId", None)) == DO_THE_WAVE
            ]
            if attacks:
                return SelectionIntent(tuple(attacks), 1, "festival_second_attack", "never decline productive second strike")
            return SelectionIntent(tuple(range(len(select.option))), int(select.minCount), "attack_prompt", "no known Festival attack")

        if select_type == int(SelectType.CARD):
            if parent == VOLBEAT:
                return self._board_search(obs, plan, "quick_sign")
            if parent == POFFIN:
                return self._board_search(obs, plan, "poffin")
            if parent == BUG_SET:
                return self._bug_set(obs, plan)
            if parent == HILDA:
                return self._hilda(obs, plan)
            if parent == BROCK:
                return self._brock(obs, plan)
            if parent == POKE_PAD:
                return self._poke_pad(obs, plan)
            if parent == THWACKEY:
                return self._thwackey(obs, plan)
            if parent == NIGHT_STRETCHER:
                return self._night_stretcher(obs, plan)
            if parent == SACRED_ASH:
                return self._sacred_ash(obs, plan)
            if parent == BOSS or context == int(SelectContext.SWITCH):
                return self._boss(obs, plan)
            if context == int(SelectContext.TO_ACTIVE):
                return self._promotion(obs, plan)
            if context == int(SelectContext.TO_HAND) and parent is None:
                return SelectionIntent(tuple(range(len(select.option))), max(1, int(select.minCount)), "prize", "face-down prize choice")

        if context in {int(SelectContext.SWITCH), int(SelectContext.TO_ACTIVE)}:
            return self._promotion(obs, plan)

        if select_type == int(SelectType.COUNT):
            ranked = sorted(
                range(len(select.option)),
                key=lambda i: (_int(getattr(select.option[i], "number", None), 0), -i),
                reverse=True,
            )
            return SelectionIntent(tuple(ranked), 1, "count", "maximize useful exact effect count")

        if select_type == int(SelectType.ENERGY):
            # Retreat and effect payments encode attached Energy units, not
            # cards.  Prefer the smallest count and preserve prompt order for
            # otherwise identical Basic Grass units.
            ranked = sorted(
                range(len(select.option)),
                key=lambda i: (_int(getattr(select.option[i], "count", None), 1), i),
            )
            return SelectionIntent(tuple(ranked), int(select.minCount), "energy_payment", "minimum exact retreat/effect payment")

        if select_type in {
            int(SelectType.ATTACHED_CARD),
            int(SelectType.CARD_OR_ATTACHED_CARD),
        }:
            return SelectionIntent(
                tuple(range(len(select.option))),
                int(select.minCount),
                "attached_card_effect",
                "forced public attached-card selection",
            )

        if select_type == int(SelectType.SKILL):
            # SKILL_ORDER requires an ordered list.  Card/serial are intrinsic
            # option fields, so the deterministic ordering remains valid after
            # engine option reordering and selects exactly the requested count.
            ranked = sorted(
                range(len(select.option)),
                key=lambda i: (
                    -_int(getattr(select.option[i], "cardId", None), 10**9),
                    -_int(getattr(select.option[i], "serial", None), 10**9),
                    -i,
                ),
                reverse=True,
            )
            return SelectionIntent(tuple(ranked), int(select.maxCount), "skill_order", "deterministic public trigger order")

        if select_type == int(SelectType.SPECIAL_CONDITION):
            return SelectionIntent(tuple(range(len(select.option))), int(select.minCount), "special_condition", "forced condition choice")

        if select_type == int(SelectType.YES_NO):
            yes = [i for i, option in enumerate(select.option) if _int(option.type) == int(OptionType.YES)]
            no = [i for i, option in enumerate(select.option) if _int(option.type) == int(OptionType.NO)]
            return SelectionIntent(tuple(yes + no), 1, "activation", "activate known legal effect")

        # This is deliberately not a generic TO_HAND resolver.  An unknown
        # composite contract is sent to the agent's fail-closed boundary.
        return SelectionIntent((), int(select.minCount), "unknown", f"type={select_type},context={context},effect={parent}", False)

    def _setup_active(self, obs: Any) -> SelectionIntent:
        hand_ids = [_int(getattr(card, "id", None)) for card in (getattr(_hero(obs), "hand", None) or [])]
        # Bug Catching Set is a genuine (though not guaranteed) turn-one path
        # to the single Grass Energy Quick Sign needs.  Other Supporter-based
        # paths are illegal for the starting player and do not qualify.
        volbeat_path = GRASS_ENERGY in hand_ids or BUG_SET in hand_ids
        priorities = (
            (VOLBEAT, APPLIN_GRASS, APPLIN_DRAGON, GROOKEY, SHAYMIN)
            if volbeat_path
            else (APPLIN_GRASS, APPLIN_DRAGON, GROOKEY, SHAYMIN, VOLBEAT)
        )
        return SelectionIntent(tuple(_rank_by_ids(obs, priorities)), 1, "setup_active", "state-aware opening pivot")

    def _setup_bench(self, obs: Any) -> SelectionIntent:
        counts = _board_counts(obs)
        applin_count = counts.get(APPLIN_GRASS, 0) + counts.get(APPLIN_DRAGON, 0) + counts.get(DIPPLIN, 0)
        engine_count = counts.get(GROOKEY, 0) + counts.get(THWACKEY, 0)
        available: dict[int, list[int]] = {}
        for index in range(len(obs.select.option)):
            available.setdefault(option_card_id(obs, index), []).append(index)
        useful: list[int] = []

        def take_one(card_ids: Iterable[int]) -> None:
            for card_id in card_ids:
                choices = available.get(card_id, [])
                if choices:
                    useful.append(choices.pop(0))
                    return

        if applin_count == 0:
            take_one((APPLIN_GRASS, APPLIN_DRAGON))
            applin_count += int(bool(useful))
        if engine_count == 0:
            before = len(useful)
            take_one((GROOKEY,))
            engine_count += int(len(useful) > before)
        if applin_count < 2:
            before = len(useful)
            take_one((APPLIN_GRASS, APPLIN_DRAGON))
            applin_count += int(len(useful) > before)
        if engine_count < 2:
            take_one((GROOKEY,))
        take_one((SHAYMIN,))
        if counts.get(VOLBEAT, 0) == 0:
            take_one((VOLBEAT,))
        ranked = _rank_by_ids(obs, (APPLIN_GRASS, APPLIN_DRAGON, GROOKEY, SHAYMIN, VOLBEAT))
        useful.extend(index for index in ranked if index not in useful and option_card_id(obs, index) != VOLBEAT)
        desired = min(int(obs.select.maxCount), len(useful))
        return SelectionIntent(tuple(useful), desired, "setup_bench", "Applin plus Grookey composition")

    def _board_search(self, obs: Any, plan: MacroPlan, name: str) -> SelectionIntent:
        counts = _board_counts(obs)
        applin_count = counts.get(APPLIN_GRASS, 0) + counts.get(APPLIN_DRAGON, 0) + counts.get(DIPPLIN, 0)
        engine_count = counts.get(GROOKEY, 0) + counts.get(THWACKEY, 0)
        available: dict[int, list[int]] = {}
        for index in range(len(obs.select.option)):
            available.setdefault(option_card_id(obs, index), []).append(index)
        useful: list[int] = []

        def take_one(card_ids: Iterable[int]) -> None:
            for card_id in card_ids:
                choices = available.get(card_id, [])
                while choices and choices[0] in useful:
                    choices.pop(0)
                if choices:
                    useful.append(choices.pop(0))
                    return

        # Composition is sequential: first attacker, first engine, replacement,
        # then redundant engine.  A flat rank could select two copies of one ID
        # and reproduce the plateau policy's brittle board.
        if applin_count == 0:
            take_one((APPLIN_GRASS, APPLIN_DRAGON))
        if engine_count == 0:
            take_one((GROOKEY,))
        if applin_count + sum(option_card_id(obs, i) in {APPLIN_GRASS, APPLIN_DRAGON} for i in useful) < 2:
            take_one((APPLIN_GRASS, APPLIN_DRAGON))
        if engine_count + sum(option_card_id(obs, i) == GROOKEY for i in useful) < 2:
            take_one((GROOKEY,))
        take_one((SHAYMIN,))
        remaining = _rank_by_ids(obs, (APPLIN_GRASS, APPLIN_DRAGON, GROOKEY, SHAYMIN))
        useful.extend(index for index in remaining if index not in useful and option_card_id(obs, index) in {APPLIN_GRASS, APPLIN_DRAGON, GROOKEY, SHAYMIN})
        desired = min(int(obs.select.maxCount), 2, len(useful))
        return SelectionIntent(tuple(useful), desired, name, "fill missing attacker and engine lines")

    def _bug_set(self, obs: Any, plan: MacroPlan) -> SelectionIntent:
        priorities: list[int] = []
        active = _in_play(_hero(obs))[0] if _in_play(_hero(obs)) else None
        if (
            _int(getattr(active, "id", None)) == VOLBEAT
            and int(getattr(obs.current, "turn", 0) or 0) == 1
        ):
            priorities.extend((GRASS_ENERGY, APPLIN_GRASS, GROOKEY))
        elif "active_dipplin" in plan.missing_prerequisites:
            priorities.append(DIPPLIN)
        if "current_energy" in plan.missing_prerequisites:
            priorities.append(GRASS_ENERGY)
        priorities.extend((THWACKEY, APPLIN_GRASS, GROOKEY, DIPPLIN, GRASS_ENERGY, SHAYMIN))
        ranked = _rank_by_ids(obs, priorities)
        legal_useful = [index for index in ranked if option_card_id(obs, index) != APPLIN_DRAGON]
        desired = min(int(obs.select.maxCount), len(legal_useful))
        return SelectionIntent(tuple(legal_useful), desired, "bug_set", "visible Grass-only top-seven priorities")

    def _hilda(self, obs: Any, plan: MacroPlan) -> SelectionIntent:
        ids = [option_card_id(obs, index) for index in range(len(obs.select.option))]
        energy_stage = bool(ids) and all(card_id == GRASS_ENERGY for card_id in ids)
        if energy_stage:
            useful = "current_energy" in plan.missing_prerequisites or "replacement_energy" in plan.missing_prerequisites
            return SelectionIntent(tuple(_rank_by_ids(obs, (GRASS_ENERGY,))), 1 if useful else 0, "hilda_energy", "complete current or replacement attacker")
        counts = _board_counts(obs)
        has_applin = any(counts.get(card_id, 0) for card_id in (APPLIN_GRASS, APPLIN_DRAGON))
        has_grookey = counts.get(GROOKEY, 0) > 0
        priorities: tuple[int, ...]
        if has_applin:
            priorities = (DIPPLIN, THWACKEY)
        elif has_grookey:
            priorities = (THWACKEY, DIPPLIN)
        else:
            priorities = (DIPPLIN, THWACKEY)
        useful_ids = ({DIPPLIN} if has_applin else set()) | ({THWACKEY} if has_grookey else set())
        useful = any(card_id in useful_ids for card_id in ids)
        return SelectionIntent(tuple(_rank_by_ids(obs, priorities)), 1 if useful else 0, "hilda_evolution", "phase-specific evolution")

    def _brock(self, obs: Any, plan: MacroPlan) -> SelectionIntent:
        ids = [option_card_id(obs, index) for index in range(len(obs.select.option))]
        # An immediately enabling evolution is worth terminating Brock's Basic
        # branch.  Otherwise take Basics and allow the engine's second prompt.
        if DIPPLIN in ids and "active_dipplin" in plan.missing_prerequisites:
            priorities = (DIPPLIN, APPLIN_GRASS, APPLIN_DRAGON, GROOKEY, THWACKEY, SHAYMIN, VOLBEAT)
            reason = "critical evolution over two slower Basics"
        else:
            priorities = (APPLIN_GRASS, APPLIN_DRAGON, GROOKEY, SHAYMIN, VOLBEAT, DIPPLIN, THWACKEY)
            reason = "missing Basic board lines"
        return SelectionIntent(tuple(_rank_by_ids(obs, priorities)), 1 if ids else 0, "brock", reason)

    def _poke_pad(self, obs: Any, plan: MacroPlan) -> SelectionIntent:
        counts = _board_counts(obs)
        has_applin_line = any(
            counts.get(card_id, 0) for card_id in (APPLIN_GRASS, APPLIN_DRAGON, DIPPLIN)
        )
        priorities = ([] if has_applin_line else [APPLIN_GRASS, APPLIN_DRAGON])
        priorities += list(tutor_prerequisite_order(plan)) + [DIPPLIN, APPLIN_GRASS, APPLIN_DRAGON, THWACKEY, GROOKEY, SHAYMIN, VOLBEAT]
        return SelectionIntent(tuple(_rank_by_ids(obs, priorities)), 1 if obs.select.option else 0, "poke_pad", "exact missing non-rule Pokemon")

    def _thwackey(self, obs: Any, plan: MacroPlan) -> SelectionIntent:
        from .cards import BOSS, HILDA, LILLIE, NIGHT_STRETCHER

        priorities = list(tutor_prerequisite_order(plan))
        priorities.extend((BOSS, DIPPLIN, APPLIN_GRASS, APPLIN_DRAGON, THWACKEY, NIGHT_STRETCHER, HILDA, LILLIE))
        return SelectionIntent(tuple(_rank_by_ids(obs, priorities)), 1, "thwackey", "one explicit missing prerequisite")

    def _night_stretcher(self, obs: Any, plan: MacroPlan) -> SelectionIntent:
        priorities: list[int] = []
        if "active_dipplin" in plan.missing_prerequisites:
            priorities.append(DIPPLIN)
        if "current_energy" in plan.missing_prerequisites:
            priorities.append(GRASS_ENERGY)
        priorities.extend((DIPPLIN, GRASS_ENERGY, APPLIN_GRASS, APPLIN_DRAGON, THWACKEY, GROOKEY, SHAYMIN, VOLBEAT))
        return SelectionIntent(tuple(_rank_by_ids(obs, priorities)), 1, "night_stretcher", "recover immediate attack before redundancy")

    def _sacred_ash(self, obs: Any, plan: MacroPlan) -> SelectionIntent:
        priorities = (DIPPLIN, APPLIN_GRASS, APPLIN_DRAGON, THWACKEY, GROOKEY, SHAYMIN, VOLBEAT)
        ranked = _rank_by_ids(obs, priorities)
        useful = [index for index in ranked if option_card_id(obs, index) in set(priorities)]
        desired = min(int(obs.select.maxCount), len(useful))
        return SelectionIntent(tuple(useful), desired, "sacred_ash", "restore exhausted searchable core")

    def _boss(self, obs: Any, plan: MacroPlan) -> SelectionIntent:
        def score(index: int) -> tuple[int, int, int, int]:
            card = option_source(obs, obs.select.option[index])
            hp = max(0, _int(getattr(card, "hp", None), 0))
            prize = _prize_value(card)
            # Public complete-turn approximation: exact KO tier first, then
            # prize value, then preserve damage efficiency.
            per_hit = max(0, 20 * plan.bench_count)
            ko_one = int(per_hit >= hp > 0)
            ko_two = int(per_hit * 2 >= hp > 0)
            return (ko_one * prize, ko_two * prize, prize, -hp)

        ranked = sorted(range(len(obs.select.option)), key=lambda i: (score(i), -i), reverse=True)
        return SelectionIntent(tuple(ranked), 1, "boss", "maximize complete-turn prizes")

    def _promotion(self, obs: Any, plan: MacroPlan) -> SelectionIntent:
        def score(index: int) -> tuple[int, int, int]:
            card = option_source(obs, obs.select.option[index])
            card_id = _int(getattr(card, "id", None))
            energy = len(getattr(card, "energies", None) or [])
            values = {
                DIPPLIN: 1000 + 100 * int(energy >= 1),
                APPLIN_GRASS: 800,
                APPLIN_DRAGON: 780,
                VOLBEAT: 450,
                GROOKEY: 300,
                THWACKEY: 100,
                SHAYMIN: 50,
            }
            return (values.get(card_id, 0), energy, -index)

        ranked = sorted(range(len(obs.select.option)), key=score, reverse=True)
        return SelectionIntent(tuple(ranked), 1, "promotion", "attack-ready replacement before support bodies")


__all__ = [
    "PromptResolver",
    "SelectionIntent",
    "context_card_id",
    "effect_id",
    "option_card_id",
    "option_source",
    "option_target",
    "option_target_id",
    "zone_card",
]
