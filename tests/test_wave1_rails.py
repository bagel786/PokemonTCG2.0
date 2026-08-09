from types import SimpleNamespace as NS

from cg.api import AreaType, EnergyType, Option, OptionType, SelectContext

from ptcg_ai.card_ids import (
    HANDHELD_FAN,
    LILLIES_DETERMINATION,
    MARNIES_GRIMMSNARL_EX,
    MARNIES_IMPIDIMP,
    MARNIES_MORGREM,
    MUNKIDORI,
    RARE_CANDY,
    SHADOW_BULLET,
)
from ptcg_ai.wave1_rails import Wave1Rail


def card(card_id, serial=1):
    return NS(id=card_id, serial=serial, playerIndex=0)


def pokemon(card_id, serial=1, *, hp=100, max_hp=100, energies=(), appeared=False):
    return NS(
        id=card_id,
        serial=serial,
        playerIndex=0,
        hp=hp,
        maxHp=max_hp,
        appearThisTurn=appeared,
        energies=list(energies),
        energyCards=[card(value, serial * 10 + index) for index, value in enumerate(energies)],
        tools=[],
        preEvolution=[],
    )


def player(*, hand=(), active=(), bench=(), discard=(), deck_count=40):
    return NS(
        hand=list(hand), handCount=len(hand), active=list(active), bench=list(bench),
        discard=list(discard), prize=[], deckCount=deck_count, benchMax=5,
        poisoned=False, burned=False, asleep=False, paralyzed=False, confused=False,
    )


def observation(select, me, opponent=None, *, turn=1, first=0, own=0):
    opponent = opponent or player()
    players = [me, opponent] if own == 0 else [opponent, me]
    state = NS(
        players=players, yourIndex=own, firstPlayer=first, turn=turn,
        turnActionCount=0, supporterPlayed=False, stadiumPlayed=False,
        energyAttached=False, retreated=False, stadium=[], looking=None,
    )
    return NS(select=select, current=state, logs=[])


def selection(context, options, *, effect=None, context_card=None, minimum=1, maximum=1):
    return NS(
        context=context, option=list(options), effect=effect, contextCard=context_card,
        minCount=minimum, maxCount=maximum, remainDamageCounter=0,
        remainEnergyCost=0, deck=None,
    )


def test_tempo_setup_active_prefers_impidimp():
    me = player(hand=[card(MUNKIDORI), card(MARNIES_IMPIDIMP, 2)])
    select = selection(SelectContext.SETUP_ACTIVE_POKEMON, [
        Option(OptionType.CARD, area=AreaType.HAND, index=0, playerIndex=0),
        Option(OptionType.CARD, area=AreaType.HAND, index=1, playerIndex=0),
    ])
    ranked, desired, reason = Wave1Rail("tempo").apply(observation(select, me, turn=0), [0, 1], 1)
    assert ranked[0] == 1
    assert desired == 1
    assert reason == "tempo_setup_active"


def test_tempo_turn_two_plays_candy_before_lillie():
    imp = pokemon(MARNIES_IMPIDIMP, appeared=False)
    me = player(hand=[card(LILLIES_DETERMINATION), card(RARE_CANDY, 2), card(MARNIES_GRIMMSNARL_EX, 3)], active=[imp])
    select = selection(SelectContext.MAIN, [
        Option(OptionType.PLAY, index=0),
        Option(OptionType.PLAY, index=1),
        Option(OptionType.END),
    ])
    ranked, _, reason = Wave1Rail("tempo").apply(observation(select, me, turn=3), [0, 2, 1], 1)
    assert ranked[0] == 1
    assert reason == "tempo_play_candy"


def test_punk_up_limits_energy_and_funds_active_grim_first():
    active = pokemon(MARNIES_GRIMMSNARL_EX, energies=[EnergyType.DARKNESS])
    bench = pokemon(MARNIES_MORGREM, 2)
    me = player(active=[active], bench=[bench])
    count_select = selection(
        SelectContext.ATTACH_TO,
        [Option(OptionType.CARD, area=AreaType.DECK, index=i, playerIndex=0) for i in range(5)],
        effect=card(MARNIES_GRIMMSNARL_EX), minimum=0, maximum=5,
    )
    _, desired, reason = Wave1Rail("tempo").apply(observation(count_select, me, turn=3), list(range(5)), 5)
    assert desired == 3
    assert reason == "punk_up_energy_count"

    target_select = selection(SelectContext.ATTACH_FROM, [
        Option(OptionType.CARD, area=AreaType.BENCH, index=0, playerIndex=0),
        Option(OptionType.CARD, area=AreaType.ACTIVE, index=0, playerIndex=0),
    ], effect=card(MARNIES_GRIMMSNARL_EX), context_card=card(7))
    ranked, _, reason = Wave1Rail("tempo").apply(observation(target_select, me, turn=3), [0, 1], 1)
    assert ranked[0] == 1
    assert reason == "punk_up_target"


def test_munk_damage_source_prefers_damaged_grim_over_munk():
    grim = pokemon(MARNIES_GRIMMSNARL_EX, hp=260, max_hp=320)
    munk = pokemon(MUNKIDORI, 2, hp=50, max_hp=110)
    me = player(active=[grim], bench=[munk])
    select = selection(SelectContext.REMOVE_DAMAGE_COUNTER, [
        Option(OptionType.CARD, area=AreaType.BENCH, index=0, playerIndex=0),
        Option(OptionType.CARD, area=AreaType.ACTIVE, index=0, playerIndex=0),
    ], effect=card(MUNKIDORI))
    ranked, _, reason = Wave1Rail("tempo").apply(observation(select, me, turn=5), [0, 1], 1)
    assert ranked[0] == 1
    assert reason == "munk_damage_source"


def test_fan_attach_prefers_active_grim_line_and_is_orthogonal():
    fan = card(HANDHELD_FAN)
    me = player(
        hand=[fan, card(RARE_CANDY, 2), card(MARNIES_GRIMMSNARL_EX, 3)],
        active=[pokemon(MARNIES_IMPIDIMP)],
        bench=[pokemon(MARNIES_MORGREM, 2)],
    )
    select = selection(SelectContext.MAIN, [
        Option(OptionType.ATTACH, area=AreaType.HAND, index=0, inPlayArea=AreaType.BENCH, inPlayIndex=0),
        Option(OptionType.ATTACH, area=AreaType.HAND, index=0, inPlayArea=AreaType.ACTIVE, inPlayIndex=0),
        Option(OptionType.PLAY, index=1),
        Option(OptionType.END),
    ])
    ranked, _, reason = Wave1Rail("fan").apply(observation(select, me, turn=3), [2, 0, 1, 3], 1)
    assert ranked[0] == 1
    assert reason == "fan_attach"


def test_fan_is_retained_when_only_munk_or_froslass_targets_exist():
    me = player(
        hand=[card(HANDHELD_FAN)], active=[pokemon(MUNKIDORI)], bench=[pokemon(104, 2)]
    )
    select = selection(SelectContext.MAIN, [
        Option(OptionType.ATTACH, area=AreaType.HAND, index=0, inPlayArea=AreaType.ACTIVE, inPlayIndex=0),
        Option(OptionType.ATTACH, area=AreaType.HAND, index=0, inPlayArea=AreaType.BENCH, inPlayIndex=0),
        Option(OptionType.END),
    ])
    ranked, _, reason = Wave1Rail("fan").apply(observation(select, me), [0, 1, 2], 1)
    assert ranked[0] == 2
    assert reason == "fan_retain_no_target"


def test_fan_lucario_sink_prefers_lunatone():
    me = player(active=[pokemon(MARNIES_GRIMMSNARL_EX)])
    opponent = player(
        active=[pokemon(678, energies=[EnergyType.FIGHTING])],
        bench=[pokemon(677, 2), pokemon(675, 3)],
    )
    select = selection(SelectContext.ATTACH_FROM, [
        Option(OptionType.CARD, area=AreaType.BENCH, index=0, playerIndex=1),
        Option(OptionType.CARD, area=AreaType.BENCH, index=1, playerIndex=1),
    ], effect=card(HANDHELD_FAN), context_card=card(20))
    ranked, _, reason = Wave1Rail("fan").apply(observation(select, me, opponent), [0, 1], 1)
    assert ranked[0] == 1
    assert reason == "fan_sink_known"


def test_non_trigger_state_is_identical_to_a2_ordering():
    me = player(active=[pokemon(MUNKIDORI)])
    select = selection(SelectContext.MAIN, [Option(OptionType.END)])
    ranked, desired, reason = Wave1Rail("tempo").apply(observation(select, me, turn=7), [0], 1)
    assert ranked == [0]
    assert desired == 1
    assert reason is None


def test_floor_forces_legal_shadow_bullet_over_end():
    me = player(active=[pokemon(MARNIES_GRIMMSNARL_EX, energies=[EnergyType.DARKNESS] * 2)])
    select = selection(SelectContext.MAIN, [
        Option(OptionType.ATTACK, attackId=SHADOW_BULLET),
        Option(OptionType.END),
    ])
    ranked, desired, reason = Wave1Rail("floor").apply(observation(select, me, turn=7), [1, 0], 1)
    assert ranked[0] == 0
    assert desired == 1
    assert reason == "floor_shadow_over_end"
    ranked, desired, reason = Wave1Rail("floor").apply_post_shield(
        observation(select, me, turn=7), [1, 0], 1
    )
    assert ranked[0] == 0
    assert desired == 1
    assert reason == "floor_shadow_over_end"


def test_floor_does_not_force_non_shadow_attack():
    me = player(active=[pokemon(MARNIES_GRIMMSNARL_EX, energies=[EnergyType.DARKNESS])])
    select = selection(SelectContext.MAIN, [
        Option(OptionType.ATTACK, attackId=934),
        Option(OptionType.END),
    ])
    ranked, desired, reason = Wave1Rail("floor").apply(observation(select, me, turn=7), [1, 0], 1)
    assert ranked == [1, 0]
    assert desired == 1
    assert reason is None


def test_floor_extends_candy_conversion_through_third_own_turn():
    imp = pokemon(MARNIES_IMPIDIMP, appeared=False)
    me = player(hand=[card(LILLIES_DETERMINATION), card(RARE_CANDY, 2), card(MARNIES_GRIMMSNARL_EX, 3)], active=[imp])
    select = selection(SelectContext.MAIN, [
        Option(OptionType.PLAY, index=0),
        Option(OptionType.PLAY, index=1),
        Option(OptionType.END),
    ])
    # turn 5 is the third own turn for the first player.
    ranked, _, reason = Wave1Rail("floor").apply(observation(select, me, turn=5), [0, 2, 1], 1)
    assert ranked[0] == 1
    assert reason == "tempo_play_candy"
