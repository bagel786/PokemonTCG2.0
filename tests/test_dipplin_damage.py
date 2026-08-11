from dataclasses import dataclass

import pytest

from ptcg_ai.dipplin.damage import (
    BRAVE_BANGLE_CARD_ID,
    CORNERSTONE_MASK_OGERPON_EX_CARD_ID,
    JAMMING_TOWER_CARD_ID,
    NEUTRALIZATION_ZONE_CARD_ID,
    is_do_the_wave_productive,
    project_do_the_wave,
)


@dataclass
class Mon:
    id: int
    hp: int
    max_hp: int
    tools: tuple[int, ...] = ()
    ex: bool = False
    mega_ex: bool = False
    basic: bool = False
    energy_type: int = 1
    weakness: int | None = None
    resistance: int | None = None
    has_ability: bool | None = None


def dipplin(*, bangle=False):
    return Mon(
        id=93,
        hp=100,
        max_hp=100,
        tools=(BRAVE_BANGLE_CARD_ID,) if bangle else (),
        has_ability=True,
    )


def target(*, hp=400, ex=False, weakness=None, resistance=None, card_id=9999):
    return Mon(
        id=card_id,
        hp=hp,
        max_hp=hp,
        ex=ex,
        weakness=weakness,
        resistance=resistance,
    )


@pytest.mark.parametrize(
    ("bangle", "belt", "expected"),
    [
        (False, False, 100),
        (True, False, 130),
        (False, True, 140),
        (True, True, 170),
    ],
)
def test_five_bench_exact_damage_thresholds(bangle, belt, expected):
    result = project_do_the_wave(
        dipplin(bangle=bangle),
        target(ex=True),
        bench_count=5,
        black_belt_used=belt,
    )

    assert result.base == 100
    assert result.raw == expected
    assert result.final == expected
    assert result.projected_turn_damage == 2 * expected
    assert result.productive
    assert not result.nullified


def test_jamming_tower_disables_bangle_but_not_black_belt():
    result = project_do_the_wave(
        dipplin(bangle=True),
        target(ex=True),
        bench_count=5,
        black_belt_used=True,
        stadium_id={"id": JAMMING_TOWER_CARD_ID},
    )

    assert result.bangle_bonus == 0
    assert result.black_belt_bonus == 40
    assert result.raw == result.final == 140


def test_cornerstone_stance_nullifies_dynamic_damage():
    defender = target(
        hp=210,
        ex=True,
        weakness=1,
        card_id=CORNERSTONE_MASK_OGERPON_EX_CARD_ID,
    )
    result = project_do_the_wave(
        dipplin(bangle=True),
        defender,
        bench_count=5,
        black_belt_used=True,
    )

    # The pre-prevention calculation remains inspectable: (100 + 30 + 40) * 2.
    assert result.raw == 170
    assert result.final == 0
    assert result.nullified
    assert not result.productive
    assert not result.ko
    assert result.reason == "cornerstone_stance"
    assert not is_do_the_wave_productive(dipplin(), defender, bench_count=5)


def test_non_ex_dipplin_bypasses_crustle_and_neutralization_zone():
    crustle = target(card_id=345, hp=200)
    crustle_result = project_do_the_wave(dipplin(), crustle, bench_count=5)
    zone_result = project_do_the_wave(
        dipplin(),
        target(hp=100),
        bench_count=5,
        stadium_id=NEUTRALIZATION_ZONE_CARD_ID,
    )

    assert crustle_result.final == 100
    assert not crustle_result.nullified
    assert zone_result.final == 100
    assert not zone_result.nullified


def test_explicit_ex_only_shield_does_not_block_dipplin():
    defender = {
        "id": 9999,
        "hp": 200,
        "maxHp": 200,
        "noDamageEnemyExAttack": True,
    }

    result = project_do_the_wave(
        {"id": 93, "tools": [], "has_ability": True, "ex": False},
        defender,
        bench_count=5,
    )

    assert result.final == 100
    assert result.productive


def test_modifiers_then_weakness_then_resistance():
    # Both are artificial but make ordering observable: (100 + 30 + 40) * 2 - 30.
    defender = target(ex=True, weakness=1, resistance=1, hp=311)
    result = project_do_the_wave(
        dipplin(bangle=True),
        defender,
        bench_count=5,
        black_belt_used=True,
        festival_active=False,
    )

    assert result.base == 100
    assert result.raw == 170
    assert result.final == 310
    assert result.weakness_applied
    assert result.resistance_applied
    assert not result.ko
    assert not result.turn_ko
    assert result.attacks_available == 1


def test_damage_recalculates_from_current_bench_each_call():
    attacker = dipplin()
    defender = target(hp=150)

    four = project_do_the_wave(attacker, defender, bench_count=4)
    five = project_do_the_wave(attacker, defender, bench_count=5)

    assert four.base_damage == four.final_damage == 80
    assert five.base_damage == five.final_damage == 100
    assert four.projected_turn_damage == 160
    assert five.projected_turn_damage == 200
    assert not four.ko and four.turn_ko
    assert not five.ko and five.turn_ko


def test_damage_threshold_prevention_uses_computed_not_printed_damage():
    defender = {
        "id": 158,
        "hp": 220,
        "maxHp": 220,
        "weakness": 1,
    }
    result = project_do_the_wave(dipplin(), defender, bench_count=5)

    assert result.raw == 100
    assert result.weakness_applied
    assert result.final == 0
    assert result.nullified
    assert result.reason == "damage_threshold_immunity"


def test_prize_and_ko_fields_distinguish_first_from_second_attack():
    defender = target(ex=True, hp=200)
    one = project_do_the_wave(dipplin(), defender, bench_count=5, festival_active=False)
    two = project_do_the_wave(dipplin(), defender, bench_count=5, festival_active=True)

    assert one.prize_value == two.prize_value == 2
    assert not one.ko and not one.turn_ko
    assert not two.ko and two.turn_ko
    assert two.attacks_to_ko == 2
    assert two.prizes_this_attack == 0

