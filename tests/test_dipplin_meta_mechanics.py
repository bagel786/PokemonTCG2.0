"""Public-board META-MECHANICS property suite for the Dipplin agent.

These tests exercise mechanical properties of the damage/prize-route/search
reasoning against generic public states.  They never branch on an opponent
archetype name; only card IDs and public mechanics are used.  This is the
offline generalization evidence described in the second-order sprint.
"""

from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from ptcg_ai.dipplin.cards import (
    APPLIN_DRAGON,
    APPLIN_GRASS,
    DIPPLIN,
    FESTIVAL,
    GRASS_ENERGY,
)
from ptcg_ai.dipplin.damage import (
    BRAVE_BANGLE_CARD_ID,
    CORNERSTONE_MASK_OGERPON_EX_CARD_ID,
    JAMMING_TOWER_CARD_ID,
    NEUTRALIZATION_ZONE_CARD_ID,
    project_do_the_wave,
)
from ptcg_ai.dipplin.objective import (
    bench_changes_prize_route,
    boss_improves_completed_turn,
    compute_turn_route,
    modifier_crosses_ko_threshold,
    route_with_boss,
    route_with_bench_expansion,
    route_with_modifier,
)
from ptcg_ai.dipplin.plan import build_macro_plan


def _card(card_id: int, serial: int, player: int = 0, **kwargs) -> NS:
    return NS(id=card_id, serial=serial, playerIndex=player, **kwargs)


def _pokemon(card_id, serial, *, hp=100, energies=(), tools=(), pre=(), ex=False,
             mega_ex=False, weakness=None, resistance=None, has_ability=None, **kw):
    return NS(
        id=card_id, serial=serial, playerIndex=0, hp=hp, maxHp=hp, max_hp=hp,
        appearThisTurn=False, energies=list(energies),
        energyCards=[_card(GRASS_ENERGY, 9000 + i) for i in range(len(energies))],
        tools=list(tools), preEvolution=list(pre),
        ex=ex, mega_ex=mega_ex, weakness=weakness, resistance=resistance,
        has_ability=has_ability, **kw,
    )


def _player(*, active=None, bench=(), hand=(), discard=(), deck_count=40):
    return NS(
        active=[active] if active is not None else [],
        bench=list(bench), benchMax=5, deckCount=deck_count,
        discard=list(discard), prize=[None] * 6, handCount=len(hand), hand=list(hand),
        poisoned=False, burned=False, asleep=False, paralyzed=False, confused=False,
    )


def _obs(*, hero_active=None, hero_bench=(), opp_active=None, opp_bench=(),
         stadium=(), turn=3, first_player=0):
    hero = _player(active=hero_active, bench=hero_bench)
    opp = _player(active=opp_active, bench=opp_bench)
    players = [hero, opp]
    current = NS(turn=turn, turnActionCount=3, yourIndex=0, firstPlayer=first_player,
                 supporterPlayed=False, stadiumPlayed=False, energyAttached=False,
                 retreated=False, result=-1, stadium=list(stadium), looking=None, players=players)
    select = NS(type=0, context=0, minCount=1, maxCount=1, option=[], deck=None,
                contextCard=None, effect=None)
    return NS(current=current, select=select, logs=[])


def _dipplin(*, energy=True, tools=()):
    return _pokemon(DIPPLIN, 100, energies=(GRASS_ENERGY,) if energy else (), tools=tools,
                    has_ability=True)


def _applin_bench(count):
    return tuple(_pokemon(APPLIN_GRASS if i == 0 else APPLIN_DRAGON, 101 + i) for i in range(count))


def _festival():
    return (_card(FESTIVAL, 990),)


# 1. Single-prize non-ex target: modifiers change no prize route.
def test_single_prize_non_ex_target_ignores_ex_modifiers():
    target = _pokemon(8888, 300, hp=120)
    plain = project_do_the_wave(_dipplin(tools=(BRAVE_BANGLE_CARD_ID,)), target, bench_count=5, black_belt_used=True)
    assert plain.bangle_bonus == 0
    assert plain.black_belt_bonus == 0
    assert plain.prize_value == 1


# 2. Two-prize ex: modifier threshold arithmetic is exact.
def test_two_prize_ex_modifier_arithmetic():
    target = _pokemon(9999, 200, hp=140, ex=True)
    base = project_do_the_wave(_dipplin(), target, bench_count=5)
    bangle = project_do_the_wave(_dipplin(tools=(BRAVE_BANGLE_CARD_ID,)), target, bench_count=5)
    belt = project_do_the_wave(_dipplin(), target, bench_count=5, black_belt_used=True)
    assert base.final == 100 and not base.ko
    assert bangle.final == 130 and not bangle.ko
    assert belt.final == 140 and belt.ko
    assert target.ex and base.prize_value == 2


# 3. Three-prize Mega ex: prize value is 3.
def test_three_prize_mega_ex_prize_value():
    mega = _pokemon(9999, 200, hp=100, ex=True, mega_ex=True)
    proj = project_do_the_wave(_dipplin(), mega, bench_count=5)
    assert proj.prize_value == 3


# 4. Grass-weak high-HP target: Weakness doubles damage correctly.
def test_grass_weak_high_hp_target_weakness_math():
    weak = _pokemon(9999, 200, hp=500, ex=True, weakness=1)
    proj = project_do_the_wave(_dipplin(), weak, bench_count=5)
    assert proj.base == 100
    assert proj.final == 200
    assert proj.weakness_applied


# 5. First-hit KO vs two-hit KO are distinguished.
def test_first_hit_ko_vs_two_hit_ko():
    one_shot = _pokemon(9999, 200, hp=90, ex=True)
    two_shot = _pokemon(9999, 201, hp=150, ex=True)
    first = project_do_the_wave(_dipplin(), one_shot, bench_count=5, festival_active=True)
    second = project_do_the_wave(_dipplin(), two_shot, bench_count=5, festival_active=True)
    assert first.ko  # first hit KOs outright
    assert not second.ko and second.turn_ko  # two hits KO the same target


# 6. Boss: a low-HP bench target that unlocks a second strike is preferred.
def test_boss_prefers_bench_target_that_unlocks_second_strike():
    active = _pokemon(9999, 200, hp=400, ex=True)
    bench = _pokemon(7777, 700, hp=90, ex=True)
    obs = _obs(hero_active=_dipplin(), hero_bench=_applin_bench(5), opp_active=active,
               opp_bench=(bench,), stadium=_festival())
    plan = build_macro_plan(obs)
    baseline = compute_turn_route(obs, plan)
    boss = route_with_boss(obs, plan)
    assert boss is not None
    assert not baseline.first_hit_ko
    assert boss.first_hit_ko
    assert boss_improves_completed_turn(baseline, boss)
    assert boss.completed_turn_guaranteed_prizes > baseline.completed_turn_guaranteed_prizes


# 7. Jamming Tower disables Brave Bangle.
def test_jamming_tower_disables_brave_bangle():
    ex_target = _pokemon(9999, 200, hp=130, ex=True)
    with_jamming = project_do_the_wave(
        _dipplin(tools=(BRAVE_BANGLE_CARD_ID,)), ex_target, bench_count=5,
        stadium_id=JAMMING_TOWER_CARD_ID,
    )
    assert with_jamming.bangle_bonus == 0
    assert with_jamming.final == 100


# 8. Crustle-style ex-attack immunity does not nullify non-ex Dipplin.
def test_crustle_ex_immunity_does_not_nullify_dipplin():
    crustle = _pokemon(345, 700, hp=200)
    proj = project_do_the_wave(_dipplin(), crustle, bench_count=5)
    assert proj.final == 100
    assert not proj.nullified


# 9. Ability-based attack immunity nullifies Dipplin (which has an ability).
def test_ability_based_immunity_nullifies_dipplin():
    shield = {"id": 9999, "hp": 200, "maxHp": 200, "noDamageEnemyAbilityPokemonAttack": True}
    proj = project_do_the_wave(_dipplin(), shield, bench_count=5)
    assert proj.final == 0
    assert proj.nullified
    assert proj.reason == "ability_attack_immunity"


# 10. Neutralization Zone: no invented ex restriction for non-ex Dipplin.
def test_neutralization_zone_does_not_apply_ex_restriction_to_non_ex_dipplin():
    proj = project_do_the_wave(
        _dipplin(), _pokemon(9999, 200, hp=100), bench_count=5,
        stadium_id=NEUTRALIZATION_ZONE_CARD_ID,
    )
    assert proj.final == 100
    assert not proj.nullified


# 11. Bench threshold: an added body that changes the KO route is useful.
def test_bench_threshold_change_is_useful():
    ex_target = _pokemon(9999, 200, hp=180, ex=True)
    obs = _obs(hero_active=_dipplin(), hero_bench=_applin_bench(4), opp_active=ex_target,
               stadium=_festival())
    plan = build_macro_plan(obs)
    before = compute_turn_route(obs, plan)
    after = route_with_bench_expansion(obs, plan, additional_bodies=1)
    assert bench_changes_prize_route(before, after)


# 12. Bench threshold no-change: do not force a body for no route change.
def test_bench_threshold_no_change_is_not_useful():
    ex_target = _pokemon(9999, 200, hp=400, ex=True)
    obs = _obs(hero_active=_dipplin(), hero_bench=_applin_bench(5), opp_active=ex_target,
               stadium=_festival())
    plan = build_macro_plan(obs)
    before = compute_turn_route(obs, plan)
    after = route_with_bench_expansion(obs, plan, additional_bodies=1)
    assert not bench_changes_prize_route(before, after)


# 13. Fragile bench: the search metric penalizes exposed <=50 HP bodies.
def test_fragile_bench_is_penalized_in_metric():
    from ptcg_ai.dipplin.search import METRIC_FIELDS, completed_turn_metric, _AttackTrace
    from ptcg_ai.dipplin.snapshot import PlanMemory

    fragile_hero = _player(active=_dipplin(), bench=(_pokemon(APPLIN_GRASS, 101, hp=40),))
    sturdy_hero = _player(active=_dipplin(), bench=(_pokemon(APPLIN_DRAGON, 101, hp=70),))
    opp = _player(active=_pokemon(9999, 200, hp=100, ex=True))

    def metric_for(hero):
        current = NS(turn=3, turnActionCount=0, yourIndex=0, firstPlayer=0, result=-1,
                     stadium=[_card(FESTIVAL, 990)], players=[hero, opp])
        root = NS(current=current)
        leaf = NS(current=current)
        vec = completed_turn_metric(root, leaf, 0, PlanMemory(), _AttackTrace())
        return vec

    fragile_vec = metric_for(fragile_hero)
    sturdy_vec = metric_for(sturdy_hero)
    idx = METRIC_FIELDS.index("avoid_exposed_fragile_bench")
    assert fragile_vec[idx] < sturdy_vec[idx]


# 14. Replacement continuity: only the strict contract qualifies.
def test_replacement_continuity_requires_strict_contract():
    from cg.api import AreaType, OptionType
    from ptcg_ai.dipplin.search import (
        METRIC_FIELDS,
        RootCandidate,
        _continuity_proof_admissible,
        _continuity_root_causal,
    )

    festival = _card(FESTIVAL, 5000, 0)
    hero = NS(hand=[festival], active=[], bench=[], discard=[], prize=[])
    opp = NS(hand=[], active=[], bench=[], discard=[], prize=[])
    current = NS(yourIndex=0, players=[hero, opp], looking=[], stadium=[])
    option = NS(type=int(OptionType.PLAY), index=0, area=int(AreaType.HAND), playerIndex=0)
    obs = NS(current=current, select=NS(type=0, context=0, option=[option]))
    candidate = RootCandidate((0,), None, "replacement")

    # A generic Stadium play is not a continuity-causal root, so the strict
    # contract must reject it even when a ready replacement appears.
    assert _continuity_root_causal(obs, candidate) is False
    baseline = [0.0] * len(METRIC_FIELDS)
    repl_ready = baseline.copy()
    repl_ready[METRIC_FIELDS.index("replacement_attacker_ready")] = 1.0
    assert not _continuity_proof_admissible(candidate, obs, [repl_ready], [baseline])


# 15. Support active: attack-ready Dipplin on the bench outranks dead setup.
def test_support_active_prefers_retreat_to_ready_dipplin():
    support = _pokemon(88, 300, hp=60)  # Volbeat active
    ready = _pokemon(DIPPLIN, 101, energies=(GRASS_ENERGY,))
    obs = _obs(hero_active=support, hero_bench=(ready,), opp_active=_pokemon(9999, 200, hp=100))
    plan = build_macro_plan(obs)
    assert plan.current_attacker_ready is False
    assert plan.replacement_attacker_ready is True
    assert plan.trapped_active_serial == 300
