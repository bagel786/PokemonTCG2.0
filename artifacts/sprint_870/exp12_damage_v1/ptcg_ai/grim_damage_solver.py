"""Exact, public-state damage conversion for A2 Grimmsnarl.

This layer only resolves Adrena-Brain destinations and Shadow Bullet's Bench
target.  It preserves A2 on ties, uncertainty, malformed observations, and all
unrelated prompts.  No opponent identity or archetype is consulted.
"""

from __future__ import annotations

from dataclasses import dataclass

from cg.api import AreaType, EnergyType, SelectContext

from .card_ids import MARNIES_GRIMMSNARL_EX, MUNKIDORI, SHADOW_BULLET
from .prevention import ability_damage_counter_nullified, attack_damage_nullified
from .view import card_table, prize_value, resolve_area_card


FROSLASS_IDS = frozenset({104, 861})


@dataclass(frozen=True)
class PublicTarget:
    option_index: int
    serial: int
    active: bool
    hp: int
    prizes: int
    munk_blocked: bool
    shadow_blocked: bool


@dataclass(frozen=True)
class RouteScore:
    terminal: int = 0
    prizes: int = 0
    kos: int = 0
    breakpoint: int = 0
    overkill: int = 0
    effective: int = 0
    uncertain: bool = False

    @property
    def objective(self) -> tuple[int, int, int, int, int, int]:
        return (
            self.terminal,
            self.prizes,
            self.kos,
            self.breakpoint,
            -self.overkill,
            self.effective,
        )


@dataclass
class PendingMove:
    effect_serial: int
    source_serial: int
    available: int
    count: int | None = None


def _effect_id(obs) -> int:
    effect = getattr(obs.select, "effect", None)
    context = getattr(obs.select, "contextCard", None)
    return int(getattr(effect or context, "id", 0) or 0)


def _effect_serial(obs) -> int:
    effect = getattr(obs.select, "effect", None)
    context = getattr(obs.select, "contextCard", None)
    return int(getattr(effect or context, "serial", 0) or 0)


def _context(obs, value: SelectContext) -> bool:
    return int(getattr(obs.select, "context", -1)) == int(value)


def _in_play(player):
    return [p for p in (player.active or []) + (player.bench or []) if p is not None]


class GrimDamageSolver:
    """Small deterministic post-policy solver for exact damage conversion."""

    def __init__(self, enabled: bool = True):
        self.enabled = bool(enabled)
        self.telemetry: dict[str, int] = {}
        self.last_intervention: str | None = None
        self._turn_key: tuple[int, int] | None = None
        self._pending: PendingMove | None = None

    def reset(self) -> None:
        self._turn_key = None
        self._pending = None
        self.last_intervention = None

    def _record(self, reason: str) -> None:
        self.telemetry[reason] = self.telemetry.get(reason, 0) + 1
        self.last_intervention = reason

    def apply(self, obs, ranked: list[int], desired: int):
        """Return ``(ranked, desired, reason)`` and fail closed to A2."""
        self.last_intervention = None
        if not self.enabled:
            return ranked, desired, None
        try:
            state = obs.current
            key = (int(state.yourIndex), int(state.turn))
            if key != self._turn_key:
                self._turn_key = key
                self._pending = None

            effect_id = _effect_id(obs)
            if effect_id == MUNKIDORI:
                if _context(obs, SelectContext.REMOVE_DAMAGE_COUNTER):
                    self._observe_source(obs, ranked)
                elif _context(obs, SelectContext.REMOVE_DAMAGE_COUNTER_COUNT):
                    self._observe_count(obs, ranked)
                elif _context(obs, SelectContext.DAMAGE_COUNTER):
                    return self._solve_munk_destination(obs, ranked, desired)
                return ranked, desired, None

            if effect_id == MARNIES_GRIMMSNARL_EX and _context(obs, SelectContext.DAMAGE):
                return self._solve_shadow_target(obs, ranked, desired)
            return ranked, desired, None
        except (AttributeError, IndexError, KeyError, TypeError, ValueError):
            self._pending = None
            return ranked, desired, None

    def _observe_source(self, obs, ranked: list[int]) -> None:
        self._pending = None
        if not ranked:
            return
        option = obs.select.option[ranked[0]]
        card = resolve_area_card(obs, option.area, option.index, option.playerIndex)
        if card is None:
            return
        maximum = int(getattr(card, "maxHp", 0) or 0)
        damage = max(0, maximum - int(getattr(card, "hp", 0) or 0))
        serial = int(getattr(card, "serial", 0) or 0)
        effect_serial = _effect_serial(obs)
        if serial and effect_serial and damage >= 10:
            self._pending = PendingMove(effect_serial, serial, min(3, damage // 10))

    def _observe_count(self, obs, ranked: list[int]) -> None:
        pending = self._matching_pending(obs)
        if pending is None or not ranked:
            return
        number = int(getattr(obs.select.option[ranked[0]], "number", 0) or 0)
        if 1 <= number <= pending.available:
            pending.count = number
        else:
            self._pending = None

    def _matching_pending(self, obs) -> PendingMove | None:
        pending = self._pending
        if pending is None or pending.effect_serial != _effect_serial(obs):
            return None
        me = obs.current.players[obs.current.yourIndex]
        if pending.source_serial not in {
            int(getattr(card, "serial", 0) or 0) for card in _in_play(me)
        }:
            self._pending = None
            return None
        return pending

    def _target(self, obs, option_index: int, effect: str) -> PublicTarget | None:
        option = obs.select.option[option_index]
        owner = getattr(option, "playerIndex", None)
        owner = obs.current.yourIndex if owner is None else int(owner)
        card = resolve_area_card(obs, option.area, option.index, owner)
        if card is None or option.area not in {AreaType.ACTIVE, AreaType.BENCH}:
            return None
        opponent_index = 1 - obs.current.yourIndex
        if owner != opponent_index:
            return None
        opponent = obs.current.players[opponent_index]
        benched = option.area == AreaType.BENCH
        serial = int(getattr(card, "serial", 0) or 0)
        if not serial:
            return None
        return PublicTarget(
            option_index=option_index,
            serial=serial,
            active=not benched,
            hp=int(getattr(card, "hp", 0) or 0),
            prizes=prize_value(card),
            munk_blocked=ability_damage_counter_nullified(
                obs, card, opponent, defender_benched=benched
            ) if effect == "munk" else False,
            shadow_blocked=attack_damage_nullified(
                obs, SHADOW_BULLET, card, opponent, defender_benched=benched
            ) if effect == "shadow" else False,
        )

    def _opponent_targets(self, obs, effect: str) -> list[PublicTarget]:
        targets = []
        for index in range(len(obs.select.option)):
            target = self._target(obs, index, effect)
            if target is not None:
                targets.append(target)
        return targets

    def _shadow_ready(self, obs) -> bool:
        state = obs.current
        me = state.players[state.yourIndex]
        active = next(iter(me.active or []), None)
        if active is None or int(active.id) != MARNIES_GRIMMSNARL_EX:
            return False
        if bool(me.asleep) or bool(me.paralyzed) or bool(me.confused):
            return False
        payable = {
            int(EnergyType.DARKNESS), int(EnergyType.RAINBOW), int(EnergyType.TEAM_ROCKET)
        }
        if sum(int(energy) in payable for energy in (active.energies or [])) < 2:
            return False
        opponent = state.players[1 - state.yourIndex]
        defender = next(iter(opponent.active or []), None)
        return defender is not None and not attack_damage_nullified(
            obs, SHADOW_BULLET, defender, opponent, defender_benched=False
        )

    def _active_shadow_damage(self, obs, target) -> int:
        opponent = obs.current.players[1 - obs.current.yourIndex]
        if attack_damage_nullified(obs, SHADOW_BULLET, target, opponent, False):
            return 0
        meta = card_table().get(int(target.id))
        if meta is None:
            return 180
        damage = 180
        if meta.weakness is not None and int(meta.weakness) == int(EnergyType.DARKNESS):
            damage *= 2
        if meta.resistance is not None and int(meta.resistance) == int(EnergyType.DARKNESS):
            damage = max(0, damage - 30)
        return damage

    def _score_munk(self, obs, chosen: PublicTarget, count: int) -> RouteScore:
        state = obs.current
        me = state.players[state.yourIndex]
        opponent = state.players[1 - state.yourIndex]
        opponent_cards = [p for p in _in_play(opponent)]
        hp = {int(p.serial): int(p.hp) for p in opponent_cards}
        moved = 0 if chosen.munk_blocked else 10 * count
        hp[chosen.serial] = hp.get(chosen.serial, chosen.hp) - moved

        knocked = [p for p in opponent_cards if hp[int(p.serial)] <= 0]
        prizes = sum(prize_value(p) for p in knocked)
        kos = len(knocked)
        overkill = max(0, moved - chosen.hp)
        terminal = int(prizes >= len(me.prize))
        active = next(iter(opponent.active or []), None)
        active_ko = active is not None and hp.get(int(active.serial), int(active.hp)) <= 0
        if active_ko and not terminal:
            return RouteScore(terminal, prizes, kos, 0, overkill, moved, uncertain=True)
        if not self._shadow_ready(obs) or active_ko:
            return RouteScore(terminal, prizes, kos, 0, overkill, moved)

        active_hp = hp[int(active.serial)]
        active_damage = self._active_shadow_damage(obs, active)
        active_shadow_ko = active_damage >= active_hp
        base_prizes = prizes + (prize_value(active) if active_shadow_ko else 0)
        base_kos = kos + int(active_shadow_ko)
        base_overkill = overkill + (max(0, active_damage - active_hp) if active_shadow_ko else 0)
        base_effective = moved + min(active_damage, active_hp)
        base_terminal = int(base_prizes >= len(me.prize))

        routes = [RouteScore(base_terminal, base_prizes, base_kos, 0,
                             base_overkill, base_effective)]
        for bench in opponent.bench or []:
            serial = int(bench.serial)
            bench_hp = hp[serial]
            if bench_hp <= 0 or attack_damage_nullified(
                obs, SHADOW_BULLET, bench, opponent, defender_benched=True
            ):
                continue
            bench_ko = bench_hp <= 30
            route_prizes = base_prizes + (prize_value(bench) if bench_ko else 0)
            breakpoint = int(
                serial == chosen.serial and chosen.hp > 30 and bench_hp <= 30
            )
            routes.append(RouteScore(
                int(route_prizes >= len(me.prize)), route_prizes,
                base_kos + int(bench_ko), breakpoint,
                base_overkill + (max(0, 30 - bench_hp) if bench_ko else 0),
                base_effective + min(30, bench_hp),
            ))
        return max(routes, key=lambda score: score.objective)

    def _solve_munk_destination(self, obs, ranked: list[int], desired: int):
        pending = self._matching_pending(obs)
        if pending is None or not ranked:
            self._pending = None
            return ranked, desired, None
        count = pending.available if pending.count is None else pending.count
        self._pending = None
        targets = self._opponent_targets(obs, "munk")
        by_index = {target.option_index: target for target in targets}
        selected = by_index.get(ranked[0])
        if selected is None:
            return ranked, desired, None
        base = self._score_munk(obs, selected, count)
        if base.uncertain:
            return ranked, desired, None
        scored = [(self._score_munk(obs, target, count), target) for target in targets]
        certain = [(score, target) for score, target in scored if not score.uncertain]
        if not certain:
            return ranked, desired, None
        top_score = max(score.objective for score, _ in certain)
        if top_score <= base.objective:
            return ranked, desired, None
        best = min(
            (target for score, target in certain if score.objective == top_score),
            key=lambda target: target.serial,
        )
        reordered = [best.option_index] + [i for i in ranked if i != best.option_index]
        self._record("munk_exact_conversion")
        return reordered, desired, self.last_intervention

    def _chip_breakpoint(self, obs, card) -> int:
        """Freezing Shroud checkup chip extends our lethal window by 10."""
        if card is None:
            return 0
        me = obs.current.players[obs.current.yourIndex]
        board = [p for p in _in_play(me)]
        if not any(int(p.id) in FROSLASS_IDS for p in board):
            return 0
        data = card_table().get(int(card.id))
        if data is None or not getattr(data, "skills", None):
            return 0
        return 10

    def _score_shadow(self, obs, target: PublicTarget) -> RouteScore:
        damage = 0 if target.shadow_blocked else 30
        breakpoint = damage + self._chip_breakpoint(obs, target)
        ko = breakpoint >= target.hp
        return RouteScore(
            prizes=target.prizes if ko else 0,
            kos=int(ko),
            breakpoint=int(ko),
            overkill=max(0, damage - target.hp) if ko else 0,
            effective=min(damage, target.hp),
        )

    def _solve_shadow_target(self, obs, ranked: list[int], desired: int):
        if not ranked:
            return ranked, desired, None
        targets = self._opponent_targets(obs, "shadow")
        by_index = {target.option_index: target for target in targets}
        selected = by_index.get(ranked[0])
        if selected is None:
            return ranked, desired, None
        base = self._score_shadow(obs, selected)
        scores = [(self._score_shadow(obs, target), target) for target in targets]
        top = max(score.objective for score, _ in scores)
        if top <= base.objective:
            return ranked, desired, None
        best = min(
            (target for score, target in scores if score.objective == top),
            key=lambda target: target.serial,
        )
        reordered = [best.option_index] + [i for i in ranked if i != best.option_index]
        self._record("shadow_exact_conversion")
        return reordered, desired, self.last_intervention
