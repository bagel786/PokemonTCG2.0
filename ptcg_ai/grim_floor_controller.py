"""Deterministic public-information floor director for the frozen d842 policy.

The controller never creates an action.  It only reorders the legal option
indices ranked by d842 (and, for count prompts, selects a legal count).  Unknown
states return the inputs unchanged.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from cg.api import AreaType, OptionType, SelectContext

from .card_ids import (
    BOSS_ORDERS,
    DARK_ENERGY,
    FROSLASS,
    MARNIES_GRIMMSNARL_EX,
    MARNIES_IMPIDIMP,
    MARNIES_MORGREM,
    MUNKIDORI,
    NIGHT_STRETCHER,
    RARE_CANDY,
    SHADOW_BULLET,
    SNORUNT,
)
from .tactical_shield import apply_tactical_shield
from .view import card_table, option_source_card, option_target_pokemon, prize_value
from .wave1_rails import (
    _apply_early_search,
    _apply_munk_source,
    _apply_punk_up,
    _apply_setup,
    _board,
    _cards,
    _context_is,
    _effect_id,
    _energy_count,
    _minimum_attack_deficit,
    _option_card_id,
    _own_turn_ordinal,
    _public_opponent_ids,
    _ranked_with,
)


ROUTE_IDS = {
    "mirror": frozenset({MARNIES_IMPIDIMP, MARNIES_MORGREM, MARNIES_GRIMMSNARL_EX}),
    "fast_pressure": frozenset({673, 674, 675, 676, 677, 678}),
    "wall": frozenset({345, 533}),
    "bellibolt": frozenset({269}),
    "disruption": frozenset({104, 245, 361, 743, 861, 1031}),
}
ROUTE_ORDER = ("wall", "fast_pressure", "mirror", "bellibolt", "disruption")
PROTECTED = frozenset({RARE_CANDY, MARNIES_GRIMMSNARL_EX, MARNIES_MORGREM, DARK_ENERGY})
DEFAULT_RULES = frozenset({
    "setup", "conversion", "recovery", "resources", "matchups",
    "prize_conversion", "final_invariants",
})


def _load_policy(path: str | Path | None) -> dict:
    target = Path(path) if path is not None else Path(__file__).with_name("floor_policy.json")
    if not target.exists():
        return {"enabled_rule_ids": sorted(DEFAULT_RULES)}
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data.get("enabled_rule_ids"), list):
        raise ValueError("floor_policy.json must contain enabled_rule_ids")
    return data


def _option_target(obs, index: int):
    option = obs.select.option[index]
    return option_target_pokemon(obs, option) or option_source_card(obs, option)


def _ready(card) -> bool:
    return card is not None and _minimum_attack_deficit(card) == 0


def _damage(card) -> int:
    return max(0, int(getattr(card, "maxHp", 0) or 0) - int(getattr(card, "hp", 0) or 0))


class GrimFloorController:
    """Stateful, search-free policy overlay with in-memory telemetry."""

    def __init__(self, policy_path: str | Path | None = None) -> None:
        self.policy = _load_policy(policy_path)
        self.enabled = frozenset(str(x) for x in self.policy["enabled_rule_ids"])
        self.counts: Counter[str] = Counter()
        self.reset()

    def reset(self) -> None:
        self.counts.clear()
        self.route = "unknown"
        self.own_turn_ordinal = 0
        self.phase = "setup"
        self.previous_board = None
        self.previous_prizes = None
        self.board_changed = False
        self.prize_delta = 0
        self.last_intervention = None
        self.last_telemetry = {"phase": self.phase, "route": self.route, "reason": None}

    def _update_public_state(self, obs) -> None:
        state = getattr(obs, "current", None)
        if state is None:
            return
        me = state.players[state.yourIndex]
        public_ids = _public_opponent_ids(obs)
        if self.route == "unknown":
            for route in ROUTE_ORDER:
                if public_ids & ROUTE_IDS[route]:
                    self.route = route
                    break
        self.own_turn_ordinal = _own_turn_ordinal(state)
        own_ids = [int(card.id) for _, card in _board(me)]
        ready_grim = any(card_id == MARNIES_GRIMMSNARL_EX for card_id in own_ids)
        if self.own_turn_ordinal <= 1:
            self.phase = "setup"
        elif self.own_turn_ordinal >= 3 and not ready_grim:
            self.phase = "recovery"
        elif len(getattr(me, "prize", None) or []) <= 2:
            self.phase = "closeout"
        elif self.route == "wall":
            self.phase = "wall"
        else:
            self.phase = "race"
        board = tuple(own_ids)
        prizes = len(getattr(me, "prize", None) or [])
        self.board_changed = self.previous_board is not None and board != self.previous_board
        self.prize_delta = 0 if self.previous_prizes is None else prizes - self.previous_prizes
        self.previous_board = board
        self.previous_prizes = prizes

    def _conversion(self, obs, ranked, desired):
        result = _apply_early_search(obs, ranked, desired, max_ordinal=3)
        if result is not None:
            return (*result[:2], "conversion:" + result[2])
        return None

    def _recovery(self, obs, ranked, desired):
        if self.phase != "recovery":
            return None
        result = _apply_early_search(obs, ranked, desired, max_ordinal=99)
        if result is not None:
            return (*result[:2], "recovery:" + result[2])
        if _effect_id(obs) == NIGHT_STRETCHER and _context_is(
            obs.select, int(SelectContext.TO_HAND), "TO_HAND"
        ):
            me = obs.current.players[obs.current.yourIndex]
            board_ids = {int(card.id) for _, card in _board(me)}
            hand_ids = {int(card.id) for card in _cards(me, "hand")}
            priorities = []
            if MARNIES_IMPIDIMP in board_ids or MARNIES_MORGREM in board_ids:
                priorities.extend((MARNIES_GRIMMSNARL_EX, MARNIES_MORGREM))
            priorities.extend((RARE_CANDY, DARK_ENERGY, MARNIES_IMPIDIMP))
            for card_id in priorities:
                if card_id in hand_ids:
                    continue
                choices = [i for i in ranked if _option_card_id(obs, i) == card_id]
                if choices:
                    return _ranked_with(ranked, choices), max(1, desired), "recovery:night_stretcher"
        return None

    def _resource_rule(self, obs, ranked, desired):
        if not _context_is(obs.select, int(SelectContext.MAIN), "MAIN"):
            return None
        choices = []
        for index in ranked:
            option = obs.select.option[index]
            if int(option.type) != int(OptionType.ATTACH):
                continue
            source = option_source_card(obs, option)
            target = option_target_pokemon(obs, option)
            if source is None or target is None or int(source.id) != DARK_ENERGY:
                continue
            card_id = int(target.id)
            deficit = _minimum_attack_deficit(target)
            active = option.inPlayArea == AreaType.ACTIVE
            if active and deficit > 0:
                tier = 0
            elif card_id == MARNIES_GRIMMSNARL_EX and deficit > 0:
                tier = 1
            elif card_id == MUNKIDORI and _energy_count(target) == 0:
                tier = 2
            elif self.route == "wall" and card_id == MARNIES_MORGREM and deficit > 0:
                tier = 3
            else:
                tier = 9
            choices.append((tier, deficit <= 0, _energy_count(target), index))
        if choices and min(choices)[0] < 9:
            return _ranked_with(ranked, [min(choices)[-1]]), desired, "resources:attach_deficit"
        return None

    def _matchup_rule(self, obs, ranked, desired):
        select = obs.select
        me = obs.current.players[obs.current.yourIndex]
        if self.route == "disruption" and _context_is(select, int(SelectContext.MAIN), "MAIN"):
            if len(_board(me)) >= 3 and ranked:
                top = ranked[0]
                option = select.option[top]
                card = option_source_card(obs, option)
                if int(option.type) == int(OptionType.PLAY) and int(getattr(card, "id", 0) or 0) in {
                    MARNIES_IMPIDIMP, SNORUNT, MUNKIDORI
                }:
                    alternatives = [i for i in ranked if i != top]
                    if alternatives:
                        return alternatives + [top], desired, "matchups:sniper_bench_discipline"
        if self.route == "wall" and _context_is(select, int(SelectContext.EVOLVE), "EVOLVE"):
            choices = [
                i for i in ranked
                if int(getattr(option_source_card(obs, select.option[i]), "id", 0) or 0) == MARNIES_MORGREM
            ]
            if choices:
                return _ranked_with(ranked, choices), desired, "matchups:wall_morgrem"
        return None

    def _prize_rule(self, obs, ranked, desired):
        select = obs.select
        effect = _effect_id(obs)
        opponent_index = 1 - obs.current.yourIndex
        target_context = any(_context_is(select, int(ctx), name) for ctx, name in (
            (SelectContext.SWITCH, "SWITCH"),
            (SelectContext.EFFECT_TARGET, "EFFECT_TARGET"),
            (SelectContext.DAMAGE, "DAMAGE"),
            (SelectContext.DAMAGE_COUNTER, "DAMAGE_COUNTER"),
            (SelectContext.DAMAGE_COUNTER_ANY, "DAMAGE_COUNTER_ANY"),
        ))
        if not target_context or effect not in {BOSS_ORDERS, MARNIES_GRIMMSNARL_EX, MUNKIDORI}:
            return None
        candidates = []
        for index in ranked:
            option = select.option[index]
            owner = getattr(option, "playerIndex", None)
            if owner is not None and int(owner) != opponent_index:
                continue
            target = _option_target(obs, index)
            if target is None:
                continue
            hp = int(getattr(target, "hp", 999) or 999)
            prizes = prize_value(target)
            energy = _energy_count(target)
            if effect in {MARNIES_GRIMMSNARL_EX, MUNKIDORI}:
                lethal = hp <= 30
                key = (not lethal, -prizes, hp, -energy, index)
            else:
                lethal = hp <= 180
                ready = _ready(target)
                key = (not lethal, -prizes, not ready, hp, -energy, index)
            candidates.append(key)
        if candidates:
            reason = "prize_conversion:boss_target" if effect == BOSS_ORDERS else "prize_conversion:bench_ko"
            return _ranked_with(ranked, [min(candidates)[-1]]), desired, reason
        return None

    def _promotion_rule(self, obs, ranked, desired):
        if not any(_context_is(obs.select, int(ctx), name) for ctx, name in (
            (SelectContext.SWITCH, "SWITCH"), (SelectContext.TO_ACTIVE, "TO_ACTIVE")
        )):
            return None
        candidates = []
        for index in ranked:
            target = _option_target(obs, index)
            if target is None:
                continue
            card_id = int(target.id)
            ready = _ready(target)
            wall_morgrem = self.route == "wall" and card_id == MARNIES_MORGREM
            grim = card_id == MARNIES_GRIMMSNARL_EX
            candidates.append((not ready, not wall_morgrem, not grim, -int(getattr(target, "hp", 0) or 0), index))
        if candidates and not min(candidates)[0]:
            return _ranked_with(ranked, [min(candidates)[-1]]), desired, "final_invariants:ready_promotion"
        return None

    def _retreat_rule(self, obs, ranked, desired):
        if not _context_is(obs.select, int(SelectContext.MAIN), "MAIN"):
            return None
        me = obs.current.players[obs.current.yourIndex]
        active = _cards(me, "active")
        if not active:
            return None
        active_productive = _ready(active[0])
        if self.route == "wall" and int(active[0].id) == MARNIES_GRIMMSNARL_EX:
            active_productive = False
        ready_bench = [card for card in _cards(me, "bench") if _ready(card)]
        if active_productive or not ready_bench:
            return None
        retreats = [i for i in ranked if int(obs.select.option[i].type) == int(OptionType.RETREAT)]
        if retreats:
            return _ranked_with(ranked, retreats), desired, "final_invariants:retreat_to_ready"
        return None

    def _discard_rule(self, obs, ranked, desired):
        if not _context_is(obs.select, int(SelectContext.DISCARD), "DISCARD") or not ranked:
            return None
        top_id = _option_card_id(obs, ranked[0])
        if top_id not in PROTECTED:
            return None
        safe = [i for i in ranked if _option_card_id(obs, i) not in PROTECTED]
        if safe:
            return _ranked_with(ranked, safe), desired, "conversion:retain_critical_resource"
        return None

    def apply(self, obs, ranked: list[int], desired: int):
        ranked = list(ranked)
        self._update_public_state(obs)
        result = None
        if "setup" in self.enabled:
            base = _apply_setup(obs, ranked, desired)
            if base is not None:
                result = (*base[:2], "setup:" + base[2])
        if result is None and "conversion" in self.enabled:
            result = self._conversion(obs, ranked, desired) or self._discard_rule(obs, ranked, desired)
        if result is None and "recovery" in self.enabled:
            result = self._recovery(obs, ranked, desired)
        if result is None and "resources" in self.enabled:
            base = _apply_punk_up(obs, ranked, desired)
            result = ((*base[:2], "resources:" + base[2]) if base is not None else None)
            result = result or self._resource_rule(obs, ranked, desired)
        if result is None and "matchups" in self.enabled:
            result = self._matchup_rule(obs, ranked, desired)
        if result is None and "prize_conversion" in self.enabled:
            base = _apply_munk_source(obs, ranked, desired)
            result = ((*base[:2], "prize_conversion:" + base[2]) if base is not None else None)
            result = result or self._prize_rule(obs, ranked, desired)
        if result is None and "final_invariants" in self.enabled:
            result = self._promotion_rule(obs, ranked, desired) or self._retreat_rule(obs, ranked, desired)

        new_ranked, new_desired, reason = result or (ranked, desired, None)
        if "final_invariants" in self.enabled:
            shield_ranked, shield_desired, shield_reason = apply_tactical_shield(
                obs, new_ranked, new_desired
            )
            if shield_reason is not None:
                new_ranked, new_desired = shield_ranked, shield_desired
                reason = "final_invariants:" + shield_reason

        self.last_intervention = reason
        if reason is not None:
            self.counts[reason] += 1
        self.last_telemetry = {"phase": self.phase, "route": self.route, "reason": reason}
        return list(new_ranked), int(new_desired), reason
