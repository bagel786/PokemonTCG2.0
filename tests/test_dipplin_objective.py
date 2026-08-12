"""Tests for complete-turn prize route model (objective.py)."""

from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from ptcg_ai.dipplin.cards import (
    APPLIN_DRAGON,
    APPLIN_GRASS,
    DIPPLIN,
    DO_THE_WAVE,
    FESTIVAL,
    GRASS_ENERGY,
)
from ptcg_ai.dipplin.damage import DamageProjection, project_do_the_wave
from ptcg_ai.dipplin.objective import (
    TurnRoute,
    bench_changes_prize_route,
    boss_improves_completed_turn,
    compute_turn_route,
    min_bench_for_ko,
    modifier_crosses_ko_threshold,
    route_with_boss,
    route_with_bench_expansion,
    route_with_modifier,
)
from ptcg_ai.dipplin.plan import build_macro_plan


def _card(card_id: int, serial: int, player: int = 0, **kwargs) -> NS:
    return NS(id=card_id, serial=serial, playerIndex=player, **kwargs)


def _pokemon(
    card_id: int,
    serial: int,
    *,
    player: int = 0,
    hp: int = 40,
    energies: tuple[int, ...] = (),
    tools: tuple[NS, ...] = (),
    pre: tuple[NS, ...] = (),
    **kwargs,
) -> NS:
    return NS(
        id=card_id,
        serial=serial,
        playerIndex=player,
        hp=hp,
        maxHp=hp,
        max_hp=hp,
        appearThisTurn=False,
        energies=list(energies),
        energyCards=[_card(GRASS_ENERGY, 1000 + offset, player) for offset in range(len(energies))],
        tools=list(tools),
        preEvolution=list(pre),
        **kwargs,
    )


def _player(
    player: int,
    *,
    active: NS | None = None,
    bench: tuple[NS, ...] = (),
    hand: tuple[NS, ...] = (),
    discard: tuple[NS, ...] = (),
    deck_count: int = 40,
) -> NS:
    return NS(
        active=[active] if active is not None else [],
        bench=list(bench),
        benchMax=5,
        deckCount=deck_count,
        discard=list(discard),
        prize=[None] * 6,
        handCount=len(hand),
        hand=list(hand),
        poisoned=False,
        burned=False,
        asleep=False,
        paralyzed=False,
        confused=False,
    )


def _observation(
    *,
    turn: int = 3,
    your_index: int = 0,
    first_player: int = 0,
    hero_active: NS | None = None,
    hero_bench: tuple[NS, ...] = (),
    hero_hand: tuple[NS, ...] = (),
    hero_discard: tuple[NS, ...] = (),
    opponent_active: NS | None = None,
    opponent_bench: tuple[NS, ...] = (),
    opponent_hand: tuple[NS, ...] = (),
    stadium: tuple[NS, ...] = (),
) -> NS:
    hero = _player(
        your_index,
        active=hero_active,
        bench=hero_bench,
        hand=hero_hand,
        discard=hero_discard,
    )
    opponent_index = 1 - your_index
    opponent = _player(
        opponent_index,
        active=opponent_active,
        bench=opponent_bench,
        hand=opponent_hand,
    )
    players = [NS(), NS()]
    players[your_index] = hero
    players[opponent_index] = opponent
    current = NS(
        turn=turn,
        turnActionCount=3,
        yourIndex=your_index,
        firstPlayer=first_player,
        supporterPlayed=False,
        stadiumPlayed=False,
        energyAttached=False,
        retreated=False,
        result=-1,
        stadium=list(stadium),
        looking=None,
        players=players,
    )
    select = NS(
        type=0,
        context=0,
        minCount=1,
        maxCount=1,
        option=[],
        deck=None,
        contextCard=None,
        effect=None,
    )
    return NS(current=current, select=select, logs=[])


def _applin_bench(count: int) -> tuple[NS, ...]:
    return tuple(
        _pokemon(APPLIN_GRASS if index == 0 else APPLIN_DRAGON, 101 + index)
        for index in range(count)
    )


def _festival_stadium() -> tuple[NS, ...]:
    return (_card(FESTIVAL, 990),)


@pytest.fixture
def dipplin_attacker():
    return _pokemon(DIPPLIN, 100, energies=(GRASS_ENERGY,))


@pytest.fixture
def ex_target():
    # 2-prize EX, 160 HP, weak to Grass so 5-Bench first hit (200) KOs.
    return _pokemon(9999, 200, hp=160, rule_box=True, weakness=1)


@pytest.fixture
def non_ex_target():
    return _pokemon(8888, 300, hp=120)


def test_five_bench_base_damage(dipplin_attacker):
    """5 Bench: 100/hit, 200 total before weakness over two attacks."""
    proj = project_do_the_wave(dipplin_attacker, dipplin_attacker, bench_count=5)
    assert proj.base == 100
    assert proj.final == 100
    assert proj.projected_turn_damage == 200


def test_four_bench_base_damage(dipplin_attacker):
    """4 Bench: 80/hit, 160 total before weakness over two attacks."""
    proj = project_do_the_wave(dipplin_attacker, dipplin_attacker, bench_count=4)
    assert proj.base == 80
    assert proj.final == 80
    assert proj.projected_turn_damage == 160


def test_three_bench_base_damage(dipplin_attacker):
    """3 Bench: 60/hit, 120 total before weakness over two attacks."""
    proj = project_do_the_wave(dipplin_attacker, dipplin_attacker, bench_count=3)
    assert proj.base == 60
    assert proj.final == 60
    assert proj.projected_turn_damage == 120


def test_first_hit_ko_unlocks_second_target(dipplin_attacker, ex_target):
    """First-hit KO (2 prizes) then the second strike KOs a weak promotion."""
    obs = _observation(
        hero_active=dipplin_attacker,
        hero_bench=_applin_bench(5),
        opponent_active=ex_target,
        opponent_bench=(_pokemon(7777, 700, hp=80),),
        stadium=_festival_stadium(),
    )
    plan = build_macro_plan(obs)

    assert plan.festival_active
    route = compute_turn_route(obs, plan)
    assert route.festival_double_attack
    assert route.first_hit_damage >= 160
    assert route.first_hit_ko
    assert route.first_hit_prizes == 2
    assert route.second_hit_guaranteed
    assert route.second_hit_min_prizes == 1
    assert route.completed_turn_guaranteed_prizes == 3


def test_two_hit_ko_same_target_is_not_first_hit_ko(dipplin_attacker):
    """EX with 200 HP: no first-hit KO; both strikes finish one target (2 prizes)."""
    target = _pokemon(9999, 200, hp=200, rule_box=True)
    obs = _observation(
        hero_active=dipplin_attacker,
        hero_bench=_applin_bench(5),
        opponent_active=target,
        opponent_bench=(),
        stadium=_festival_stadium(),
    )
    route = compute_turn_route(obs, build_macro_plan(obs))

    assert not route.first_hit_ko
    assert route.first_hit_damage == 100
    assert route.second_hit_guaranteed
    assert route.completed_turn_guaranteed_prizes == 2


def test_black_belt_converts_two_hit_to_one_hit_ko(dipplin_attacker):
    """Black Belt changes a 2-hit KO into a first-hit KO, unlocking the second strike."""
    target = _pokemon(9999, 200, hp=120, rule_box=True)
    obs = _observation(
        hero_active=dipplin_attacker,
        hero_bench=_applin_bench(4),
        opponent_active=target,
        opponent_bench=(_pokemon(7777, 700, hp=80),),
        stadium=_festival_stadium(),
    )
    plan = build_macro_plan(obs)

    baseline = compute_turn_route(obs, plan)
    with_belt = route_with_modifier(obs, plan, black_belt=True)

    assert not baseline.first_hit_ko
    assert baseline.second_hit_guaranteed
    assert with_belt.first_hit_ko
    assert modifier_crosses_ko_threshold(baseline, with_belt)


def test_bangle_converts_two_hit_to_one_hit_ko():
    """Brave Bangle changes a 2-hit KO into a first-hit KO on an EX."""
    attacker = _pokemon(DIPPLIN, 100, energies=(GRASS_ENERGY,))
    target = _pokemon(9999, 200, hp=110, rule_box=True)
    obs = _observation(
        hero_active=attacker,
        hero_bench=_applin_bench(4),
        opponent_active=target,
        opponent_bench=(_pokemon(7777, 700, hp=80),),
        stadium=_festival_stadium(),
    )
    plan = build_macro_plan(obs)

    baseline = compute_turn_route(obs, plan)
    with_bangle = route_with_modifier(obs, plan, bangle=True)

    assert baseline.first_hit_damage == 80
    assert not baseline.first_hit_ko
    assert with_bangle.first_hit_damage == 110
    assert with_bangle.first_hit_ko
    assert with_bangle.bangle_required
    assert modifier_crosses_ko_threshold(baseline, with_bangle)


def test_modifier_no_ko_threshold_change(dipplin_attacker, non_ex_target):
    """Both modifiers are ignored on non-EX targets: no KO threshold change."""
    obs = _observation(
        hero_active=dipplin_attacker,
        hero_bench=_applin_bench(3),
        opponent_active=non_ex_target,
        opponent_bench=(),
        stadium=_festival_stadium(),
    )
    plan = build_macro_plan(obs)

    baseline = compute_turn_route(obs, plan)
    with_belt = route_with_modifier(obs, plan, black_belt=True)
    with_bangle = route_with_modifier(obs, plan, bangle=True)

    assert not baseline.first_hit_ko
    assert baseline.second_hit_guaranteed
    assert not with_belt.first_hit_ko
    assert not with_bangle.first_hit_ko
    assert not modifier_crosses_ko_threshold(baseline, with_belt)
    assert not modifier_crosses_ko_threshold(baseline, with_bangle)


def test_boss_targets_different_prize_value():
    """Boss onto an EX reaches a 2-prize complete-turn route vs the 1-prize active."""
    attacker = _pokemon(DIPPLIN, 100, energies=(GRASS_ENERGY,))
    non_ex_active = _pokemon(8888, 300, hp=120)
    ex_bench = _pokemon(9999, 200, hp=160, rule_box=True)
    obs = _observation(
        hero_active=attacker,
        hero_bench=_applin_bench(4),
        opponent_active=non_ex_active,
        opponent_bench=(ex_bench,),
        stadium=_festival_stadium(),
    )
    plan = build_macro_plan(obs)

    baseline = compute_turn_route(obs, plan)
    boss_route = route_with_boss(obs, plan)

    assert boss_route is not None
    assert boss_route.completed_turn_guaranteed_prizes > baseline.completed_turn_guaranteed_prizes
    assert boss_improves_completed_turn(baseline, boss_route)


def test_bench_expansion_changes_ko():
    """3->4 bench changes no KO into a first-hit KO."""
    target = _pokemon(9999, 200, hp=70, rule_box=True)
    promotion = (_pokemon(7777, 700, hp=80),)
    obs3 = _observation(
        hero_active=_pokemon(DIPPLIN, 100, energies=(GRASS_ENERGY,)),
        hero_bench=_applin_bench(3),
        opponent_active=target,
        opponent_bench=promotion,
        stadium=_festival_stadium(),
    )
    obs4 = _observation(
        hero_active=_pokemon(DIPPLIN, 100, energies=(GRASS_ENERGY,)),
        hero_bench=_applin_bench(4),
        opponent_active=target,
        opponent_bench=promotion,
        stadium=_festival_stadium(),
    )

    plan3 = build_macro_plan(obs3)
    plan4 = build_macro_plan(obs4)
    route3 = compute_turn_route(obs3, plan3)
    route4 = compute_turn_route(obs4, plan4)

    assert not route3.first_hit_ko
    assert route4.first_hit_ko
    assert bench_changes_prize_route(route3, route4)


def test_bench_expansion_no_prize_change():
    """3->4 bench does not change the route when both remain a 2-hit KO on 300 HP."""
    target = _pokemon(9999, 200, hp=300, rule_box=True)
    obs3 = _observation(
        hero_active=_pokemon(DIPPLIN, 100, energies=(GRASS_ENERGY,)),
        hero_bench=_applin_bench(3),
        opponent_active=target,
        opponent_bench=(),
        stadium=_festival_stadium(),
    )
    obs4 = _observation(
        hero_active=_pokemon(DIPPLIN, 100, energies=(GRASS_ENERGY,)),
        hero_bench=_applin_bench(4),
        opponent_active=target,
        opponent_bench=(),
        stadium=_festival_stadium(),
    )

    plan3 = build_macro_plan(obs3)
    plan4 = build_macro_plan(obs4)
    route3 = compute_turn_route(obs3, plan3)
    route4 = compute_turn_route(obs4, plan4)

    assert not route3.first_hit_ko
    assert not route4.first_hit_ko
    assert route3.completed_turn_guaranteed_prizes == 0
    assert route4.completed_turn_guaranteed_prizes == 0
    assert not bench_changes_prize_route(route3, route4)


def test_bench_expansion_creates_first_hit_ko():
    """4->5 bench converts a 2-hit KO into a first-hit KO (80 < HP <= 100)."""
    target = _pokemon(9999, 200, hp=90, rule_box=True)
    promotion = (_pokemon(7777, 700, hp=80),)
    obs4 = _observation(
        hero_active=_pokemon(DIPPLIN, 100, energies=(GRASS_ENERGY,)),
        hero_bench=_applin_bench(4),
        opponent_active=target,
        opponent_bench=promotion,
        stadium=_festival_stadium(),
    )
    plan4 = build_macro_plan(obs4)

    route4 = compute_turn_route(obs4, plan4)
    expanded = route_with_bench_expansion(obs4, plan4, additional_bodies=1)

    assert not route4.first_hit_ko
    assert expanded.first_hit_ko
    assert expanded.completed_turn_guaranteed_prizes > route4.completed_turn_guaranteed_prizes


def test_min_bench_for_ko():
    """Minimum Bench for a first-hit KO on a Grass-weak 160 HP EX is 4."""
    attacker = _pokemon(DIPPLIN, 100, energies=(GRASS_ENERGY,))
    ex_160 = _pokemon(9999, 200, hp=160, rule_box=True, weakness=1)

    obs = _observation(
        hero_active=attacker,
        opponent_active=ex_160,
    )
    plan = build_macro_plan(obs)

    assert plan.bench_count == 0
    assert min_bench_for_ko(obs, plan, ex_160) == 4


def test_continuity_same_prizes_replacement_ready():
    """Same prizes and attacks, but candidate has a ready replacement and baseline does not."""
    attacker = _pokemon(DIPPLIN, 100, energies=(GRASS_ENERGY,))
    target = _pokemon(9999, 200, hp=160, rule_box=True)

    obs_base = _observation(
        hero_active=attacker,
        hero_bench=_applin_bench(3),
        opponent_active=target,
        opponent_bench=(),
        stadium=_festival_stadium(),
    )
    plan_base = build_macro_plan(obs_base)
    route_base = compute_turn_route(obs_base, plan_base)

    obs_cand = _observation(
        hero_active=attacker,
        hero_bench=_applin_bench(2) + (_pokemon(DIPPLIN, 104, energies=(GRASS_ENERGY,)),),
        opponent_active=target,
        opponent_bench=(),
        stadium=_festival_stadium(),
    )
    plan_cand = build_macro_plan(obs_cand)
    route_cand = compute_turn_route(obs_cand, plan_cand)

    assert route_base.completed_turn_guaranteed_prizes == route_cand.completed_turn_guaranteed_prizes
    assert route_base.replacement_ready is False
    assert route_cand.replacement_ready is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])