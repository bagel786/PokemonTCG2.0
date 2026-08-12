"""Complete-turn prize route model for Festival Lead.

This module unifies prize reasoning across both Festival attacks, Boss, Bangle,
Black Belt, and bench expansion. It reasons about the full two-strike outcome
rather than fragmented single-attack heuristics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .cards import DO_THE_WAVE
from .damage import DamageProjection, project_do_the_wave
from .plan import MacroPlan


@dataclass(frozen=True, slots=True)
class TurnRoute:
    """Complete two-strike Festival Lead prize route.

    Festival Lead is unusual because attack 1 may KO, then the opponent promotes,
    and attack 2 hits the new Active. The prize consequences differ from a
    single 200-damage attack.
    """

    target_serial: int | None
    bench_count: int

    attack_available: bool
    festival_double_attack: bool

    first_hit_damage: int
    first_hit_ko: bool
    first_hit_prizes: int

    second_hit_guaranteed: bool
    second_hit_min_damage: int
    second_hit_min_prizes: int

    completed_turn_guaranteed_prizes: int

    boss_used: bool
    black_belt_used: bool
    bangle_required: bool

    current_attacker_ready: bool
    replacement_ready: bool

    fragile_bench_count: int

    @property
    def total_guaranteed_prizes(self) -> int:
        return self.completed_turn_guaranteed_prizes


def _int(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _active(player: Any) -> Any | None:
    cards = list(getattr(player, "active", None) or []) if player is not None else []
    return cards[0] if cards and cards[0] is not None else None


def _players(obs: Any) -> tuple[Any | None, Any | None]:
    state = getattr(obs, "current", None)
    players = list(getattr(state, "players", None) or []) if state is not None else []
    hero_index = _int(getattr(state, "yourIndex", None), 0) if state is not None else 0
    hero = players[hero_index] if 0 <= hero_index < len(players) else None
    opponent_index = 1 - hero_index
    opponent = players[opponent_index] if 0 <= opponent_index < len(players) else None
    return hero, opponent


def _stadium_id(obs: Any) -> int | None:
    stadium = list(getattr(getattr(obs, "current", None), "stadium", None) or [])
    return _int(getattr(stadium[0], "id", None)) if stadium else None


def _prize_value(defender: Any) -> int:
    from .damage import _is_ex
    return 2 if _is_ex(defender) else 1


def _opponent_promotion_candidates(opponent: Any) -> tuple[Any, ...]:
    """Return all publicly legal opponent promotions after a KO."""
    if opponent is None:
        return ()
    bench = tuple(getattr(opponent, "bench", None) or [])
    return tuple(p for p in bench if p is not None)


def _worst_case_second_strike(
    attacker: Any,
    opponent: Any,
    bench_count: int,
    black_belt_used: bool,
    bangle_attached: bool,
    stadium_id: int | None,
    festival_active: bool,
) -> DamageProjection:
    """Project the worst public promotion outcome for the second Festival strike.

    The opponent controls promotion after a first-hit KO. For a deterministic
    floor, evaluate against the promotion that minimizes our second-hit prizes.
    """
    candidates = _opponent_promotion_candidates(opponent)
    if not candidates:
        # No promotion possible; second strike hits empty bench
        return DamageProjection(
            attack_id=DO_THE_WAVE,
            base=0,
            raw=0,
            final=0,
            bangle_bonus=0,
            black_belt_bonus=0,
            weakness_applied=False,
            resistance_applied=False,
            nullified=True,
            productive=False,
            ko=False,
            turn_ko=False,
            attacks_to_ko=None,
            prize_value=0,
            prizes_this_attack=0,
            attacks_available=1,
            reason="no_promotion_target",
        )

    worst = None
    for candidate in candidates:
        proj = project_do_the_wave(
            attacker,
            candidate,
            bench_count=bench_count,
            black_belt_used=black_belt_used,
            bangle_attached=bangle_attached,
            stadium_id=stadium_id,
            festival_active=festival_active,
        )
        if worst is None or proj.prizes_this_attack < worst.prizes_this_attack:
            worst = proj
    return worst


def _best_case_second_strike(
    attacker: Any,
    opponent: Any,
    bench_count: int,
    black_belt_used: bool,
    bangle_attached: bool,
    stadium_id: int | None,
    festival_active: bool,
) -> DamageProjection:
    """Project the best public promotion outcome for the second Festival strike."""
    candidates = _opponent_promotion_candidates(opponent)
    if not candidates:
        return DamageProjection(
            attack_id=DO_THE_WAVE,
            base=0,
            raw=0,
            final=0,
            bangle_bonus=0,
            black_belt_bonus=0,
            weakness_applied=False,
            resistance_applied=False,
            nullified=True,
            productive=False,
            ko=False,
            turn_ko=False,
            attacks_to_ko=None,
            prize_value=0,
            prizes_this_attack=0,
            attacks_available=1,
            reason="no_promotion_target",
        )

    best = None
    for candidate in candidates:
        proj = project_do_the_wave(
            attacker,
            candidate,
            bench_count=bench_count,
            black_belt_used=black_belt_used,
            bangle_attached=bangle_attached,
            stadium_id=stadium_id,
            festival_active=festival_active,
        )
        if best is None or proj.prizes_this_attack > best.prizes_this_attack:
            best = proj
    return best


def compute_turn_route(
    obs: Any,
    plan: MacroPlan,
    *,
    black_belt: bool = False,
    bangle_attached: bool = False,
    boss_target: Any | None = None,
    bench_delta: int = 0,
) -> TurnRoute:
    """Compute the complete-turn Festival Lead prize route.

    Args:
        obs: Engine observation
        plan: Macro plan with public state
        black_belt: Whether Black Belt is used this turn
        bangle_attached: Whether Brave Bangle is attached to attacker
        boss_target: If Boss is played, the chosen target (None = current Active)
        bench_delta: Additional bench bodies assumed (for expansion reasoning)
    """
    hero, opponent = _players(obs)
    active_attacker = _active(hero)
    opp_active = _active(opponent)

    if active_attacker is None or opp_active is None:
        return TurnRoute(
            target_serial=None,
            bench_count=plan.bench_count + bench_delta,
            attack_available=False,
            festival_double_attack=False,
            first_hit_damage=0,
            first_hit_ko=False,
            first_hit_prizes=0,
            second_hit_guaranteed=False,
            second_hit_min_damage=0,
            second_hit_min_prizes=0,
            completed_turn_guaranteed_prizes=0,
            boss_used=boss_target is not None,
            black_belt_used=black_belt,
            bangle_required=bangle_attached,
            current_attacker_ready=plan.current_attacker_ready,
            replacement_ready=plan.replacement_attacker_ready,
            fragile_bench_count=plan.fragile_bench_count,
        )

    # Determine target
    target = boss_target if boss_target is not None else opp_active
    target_serial = _int(getattr(target, "serial", None))

    bench_count = max(0, plan.bench_count + bench_delta)
    festival_active = plan.festival_active
    attacks_available = 2 if festival_active else 1

    # First hit projection
    first_proj = project_do_the_wave(
        active_attacker,
        target,
        bench_count=bench_count,
        black_belt_used=black_belt,
        bangle_attached=bangle_attached,
        stadium_id=_stadium_id(obs),
        festival_active=festival_active,
    )

    first_hit_damage = first_proj.final
    first_hit_ko = first_proj.ko
    first_hit_prizes = first_proj.prize_value if first_proj.ko else 0

    # Second hit analysis
    second_hit_guaranteed = False
    second_hit_min_damage = 0
    second_hit_min_prizes = 0

    if festival_active and attacks_available >= 2:
        if first_proj.ko:
            # First hit KO'd; opponent promotes. Use worst public promotion.
            second_proj = _worst_case_second_strike(
                active_attacker,
                opponent,
                bench_count,
                black_belt,
                bangle_attached,
                _stadium_id(obs),
                festival_active,
            )
            second_hit_min_damage = second_proj.final
            second_hit_min_prizes = second_proj.prize_value if second_proj.ko else 0
            second_hit_guaranteed = second_proj.ko
        else:
            # First hit didn't KO; same target for second hit
            second_proj = project_do_the_wave(
                active_attacker,
                target,
                bench_count=bench_count,
                black_belt_used=black_belt,
                bangle_attached=bangle_attached,
                stadium_id=_stadium_id(obs),
                festival_active=festival_active,
            )
            second_hit_min_damage = second_proj.final
            second_hit_min_prizes = second_proj.prize_value if second_proj.turn_ko else 0
            second_hit_guaranteed = second_proj.turn_ko

    # Completed-turn guaranteed prizes
    completed_prizes = 0
    if first_proj.ko:
        completed_prizes += first_proj.prize_value
        if second_hit_guaranteed:
            completed_prizes += second_hit_min_prizes
    elif first_proj.turn_ko and festival_active:
        # Two-hit KO on same target
        completed_prizes = first_proj.prize_value
    elif first_proj.productive and not festival_active:
        # Single attack only
        completed_prizes = 0  # No guaranteed KO this turn

    return TurnRoute(
        target_serial=target_serial,
        bench_count=bench_count,
        attack_available=first_proj.productive,
        festival_double_attack=festival_active and attacks_available >= 2,
        first_hit_damage=first_hit_damage,
        first_hit_ko=first_proj.ko,
        first_hit_prizes=first_hit_prizes,
        second_hit_guaranteed=second_hit_guaranteed,
        second_hit_min_damage=second_hit_min_damage,
        second_hit_min_prizes=second_hit_min_prizes,
        completed_turn_guaranteed_prizes=completed_prizes,
        boss_used=boss_target is not None,
        black_belt_used=black_belt,
        bangle_required=bangle_attached,
        current_attacker_ready=plan.current_attacker_ready,
        replacement_ready=plan.replacement_attacker_ready,
        fragile_bench_count=plan.fragile_bench_count,
    )


def route_with_boss(
    obs: Any,
    plan: MacroPlan,
) -> TurnRoute | None:
    """Compute route if Boss is played, selecting the best public target."""
    _, opponent = _players(obs)
    opp_active = _active(opponent)
    if opp_active is None:
        return None

    candidates = [opp_active] + list(_opponent_promotion_candidates(opponent))
    best_route = None
    best_prizes = -1

    for candidate in candidates:
        route = compute_turn_route(
            obs,
            plan,
            boss_target=candidate,
        )
        if route.completed_turn_guaranteed_prizes > best_prizes:
            best_prizes = route.completed_turn_guaranteed_prizes
            best_route = route

    return best_route


def route_with_modifier(
    obs: Any,
    plan: MacroPlan,
    *,
    black_belt: bool = False,
    bangle: bool = False,
) -> TurnRoute:
    """Compute route with a damage modifier (Black Belt or Brave Bangle)."""
    return compute_turn_route(
        obs,
        plan,
        black_belt=black_belt,
        bangle_attached=bangle,
    )


def route_with_bench_expansion(
    obs: Any,
    plan: MacroPlan,
    additional_bodies: int,
) -> TurnRoute:
    """Compute route assuming additional bench bodies."""
    return compute_turn_route(
        obs,
        plan,
        bench_delta=additional_bodies,
    )


def modifier_crosses_ko_threshold(
    baseline: TurnRoute,
    modified: TurnRoute,
) -> bool:
    """Does the modifier convert a 2-hit KO into a 1-hit KO, unlocking a second target?"""
    if not baseline.festival_double_attack:
        return False
    # Baseline: first hit doesn't KO, but two hits do
    baseline_two_hit_ko = (not baseline.first_hit_ko) and baseline.second_hit_guaranteed
    # Modified: first hit KOs
    modified_one_hit_ko = modified.first_hit_ko
    return baseline_two_hit_ko and modified_one_hit_ko


def boss_improves_completed_turn(
    baseline: TurnRoute,
    boss_route: TurnRoute | None,
) -> bool:
    """Does Boss strictly improve the completed-turn guaranteed prizes?"""
    if boss_route is None:
        return False
    return boss_route.completed_turn_guaranteed_prizes > baseline.completed_turn_guaranteed_prizes


def bench_changes_prize_route(
    current: TurnRoute,
    expanded: TurnRoute,
) -> bool:
    """Does the bench expansion change the guaranteed prize outcome?"""
    return expanded.completed_turn_guaranteed_prizes != current.completed_turn_guaranteed_prizes


def min_bench_for_ko(
    obs: Any,
    plan: MacroPlan,
    target: Any,
    *,
    black_belt: bool = False,
    bangle: bool = False,
    festival_active: bool = True,
) -> int:
    """Find minimum bench count to achieve first-hit KO on target."""
    hero, _ = _players(obs)
    attacker = _active(hero)
    if attacker is None or target is None:
        return 99

    for bench in range(0, 6):
        proj = project_do_the_wave(
            attacker,
            target,
            bench_count=bench,
            black_belt_used=black_belt,
            bangle_attached=bangle,
            stadium_id=_stadium_id(obs),
            festival_active=festival_active,
        )
        if proj.ko:
            return bench
    return 99