from types import SimpleNamespace as NS

from cg.api import AreaType, EnergyType, Option, OptionType, SelectContext

from ptcg_ai.card_ids import (
    BOSS_ORDERS,
    DARK_ENERGY,
    FROSLASS,
    LILLIES_DETERMINATION,
    MARNIES_GRIMMSNARL_EX,
    MARNIES_IMPIDIMP,
    MARNIES_MORGREM,
    MUNKIDORI,
    NIGHT_STRETCHER,
    RARE_CANDY,
    SHADOW_BULLET,
    SNORUNT,
)
from ptcg_ai.grim_floor_controller import GrimFloorController


def card(card_id, serial=1, player=0):
    return NS(id=card_id, serial=serial, playerIndex=player)


def pokemon(card_id, serial=1, *, hp=100, max_hp=100, energies=(), appeared=False, player=0):
    return NS(
        id=card_id, serial=serial, playerIndex=player, hp=hp, maxHp=max_hp,
        appearThisTurn=appeared, energies=list(energies),
        energyCards=[card(DARK_ENERGY, serial * 10 + i, player) for i, _ in enumerate(energies)],
        tools=[], preEvolution=[],
    )


def player(*, hand=(), active=(), bench=(), discard=(), prizes=6, deck_count=40):
    return NS(
        hand=list(hand), handCount=len(hand), active=list(active), bench=list(bench),
        discard=list(discard), prize=[card(0, 900 + i) for i in range(prizes)],
        deckCount=deck_count, benchMax=5, poisoned=False, burned=False, asleep=False,
        paralyzed=False, confused=False,
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


def test_reset_and_public_route_latching():
    controller = GrimFloorController()
    me = player(active=[pokemon(MARNIES_IMPIDIMP)])
    opponent = player(active=[pokemon(678, player=1)])
    select = selection(SelectContext.MAIN, [Option(OptionType.END)])
    controller.apply(observation(select, me, opponent), [0], 1)
    assert controller.route == "fast_pressure"
    assert controller.last_telemetry["route"] == "fast_pressure"
    controller.reset()
    assert controller.route == "unknown"
    assert controller.own_turn_ordinal == 0


def test_setup_and_candy_conversion_are_controller_rules():
    me = player(hand=[card(MUNKIDORI), card(MARNIES_IMPIDIMP, 2)])
    select = selection(SelectContext.SETUP_ACTIVE_POKEMON, [
        Option(OptionType.CARD, area=AreaType.HAND, index=0, playerIndex=0),
        Option(OptionType.CARD, area=AreaType.HAND, index=1, playerIndex=0),
    ])
    ranked, desired, reason = GrimFloorController().apply(observation(select, me, turn=0), [0, 1], 1)
    assert (ranked[0], desired, reason) == (1, 1, "setup:tempo_setup_active")

    imp = pokemon(MARNIES_IMPIDIMP, appeared=False)
    me = player(hand=[card(LILLIES_DETERMINATION), card(RARE_CANDY, 2), card(MARNIES_GRIMMSNARL_EX, 3)], active=[imp])
    select = selection(SelectContext.MAIN, [
        Option(OptionType.PLAY, index=0), Option(OptionType.PLAY, index=1), Option(OptionType.END),
    ])
    ranked, _, reason = GrimFloorController().apply(observation(select, me, turn=3), [0, 2, 1], 1)
    assert ranked[0] == 1
    assert reason == "conversion:tempo_play_candy"


def test_post_turn_three_recovery_uses_night_stretcher_for_grim():
    me = player(
        hand=[], active=[pokemon(MARNIES_IMPIDIMP)],
        discard=[card(MARNIES_GRIMMSNARL_EX, 4), card(DARK_ENERGY, 5)],
    )
    select = selection(SelectContext.TO_HAND, [
        Option(OptionType.CARD, area=AreaType.DISCARD, index=1, playerIndex=0),
        Option(OptionType.CARD, area=AreaType.DISCARD, index=0, playerIndex=0),
    ], effect=card(NIGHT_STRETCHER))
    ranked, _, reason = GrimFloorController().apply(observation(select, me, turn=7), [0, 1], 1)
    assert ranked[0] == 1
    assert reason == "recovery:night_stretcher"


def test_resource_attachment_funds_active_then_backup_and_munk():
    active = pokemon(MARNIES_GRIMMSNARL_EX, energies=[EnergyType.DARKNESS])
    backup = pokemon(MARNIES_GRIMMSNARL_EX, 2)
    munk = pokemon(MUNKIDORI, 3)
    me = player(hand=[card(DARK_ENERGY)], active=[active], bench=[backup, munk])
    select = selection(SelectContext.MAIN, [
        Option(OptionType.ATTACH, area=AreaType.HAND, index=0, inPlayArea=AreaType.BENCH, inPlayIndex=1),
        Option(OptionType.ATTACH, area=AreaType.HAND, index=0, inPlayArea=AreaType.BENCH, inPlayIndex=0),
        Option(OptionType.ATTACH, area=AreaType.HAND, index=0, inPlayArea=AreaType.ACTIVE, inPlayIndex=0),
    ])
    ranked, _, reason = GrimFloorController().apply(observation(select, me, turn=5), [0, 1, 2], 1)
    assert ranked[0] == 2
    assert reason == "resources:attach_deficit"


def test_punk_up_uses_deficit_count():
    active = pokemon(MARNIES_GRIMMSNARL_EX, energies=[EnergyType.DARKNESS])
    me = player(active=[active], bench=[pokemon(MARNIES_MORGREM, 2)])
    select = selection(
        SelectContext.ATTACH_TO,
        [Option(OptionType.CARD, area=AreaType.DECK, index=i, playerIndex=0) for i in range(5)],
        effect=card(MARNIES_GRIMMSNARL_EX), minimum=0, maximum=5,
    )
    _, desired, reason = GrimFloorController().apply(observation(select, me, turn=3), list(range(5)), 5)
    assert desired == 3
    assert reason == "resources:punk_up_energy_count"


def test_wall_route_prefers_non_ex_morgrem_evolution():
    me = player(
        hand=[card(MARNIES_GRIMMSNARL_EX), card(MARNIES_MORGREM, 2)],
        active=[pokemon(MARNIES_IMPIDIMP)], bench=[pokemon(MARNIES_IMPIDIMP, 2)],
    )
    opponent = player(active=[pokemon(345, player=1)])
    select = selection(SelectContext.EVOLVE, [
        Option(OptionType.EVOLVE, area=AreaType.HAND, index=0, inPlayArea=AreaType.ACTIVE, inPlayIndex=0),
        Option(OptionType.EVOLVE, area=AreaType.HAND, index=1, inPlayArea=AreaType.BENCH, inPlayIndex=0),
    ])
    ranked, _, reason = GrimFloorController().apply(observation(select, me, opponent, turn=5), [0, 1], 1)
    assert ranked[0] == 1
    assert reason == "matchups:wall_morgrem"


def test_sniper_route_stops_redundant_low_hp_bench():
    me = player(
        hand=[card(MARNIES_IMPIDIMP)], active=[pokemon(MARNIES_IMPIDIMP)],
        bench=[pokemon(MARNIES_MORGREM, 2), pokemon(SNORUNT, 3)],
    )
    opponent = player(active=[pokemon(FROSLASS, player=1)])
    select = selection(SelectContext.MAIN, [Option(OptionType.PLAY, index=0), Option(OptionType.END)])
    ranked, _, reason = GrimFloorController().apply(observation(select, me, opponent, turn=5), [0, 1], 1)
    assert ranked[0] == 1
    assert reason == "matchups:sniper_bench_discipline"


def test_munkidori_heals_survival_relevant_grim():
    grim = pokemon(MARNIES_GRIMMSNARL_EX, hp=260, max_hp=320)
    munk = pokemon(MUNKIDORI, 2, hp=50, max_hp=110)
    me = player(active=[grim], bench=[munk])
    select = selection(SelectContext.REMOVE_DAMAGE_COUNTER, [
        Option(OptionType.CARD, area=AreaType.BENCH, index=0, playerIndex=0),
        Option(OptionType.CARD, area=AreaType.ACTIVE, index=0, playerIndex=0),
    ], effect=card(MUNKIDORI))
    ranked, _, reason = GrimFloorController().apply(observation(select, me, turn=5), [0, 1], 1)
    assert ranked[0] == 1
    assert reason == "prize_conversion:munk_damage_source"


def test_boss_and_shadow_bullet_rank_immediate_lethal():
    me = player(active=[pokemon(MARNIES_GRIMMSNARL_EX, energies=[EnergyType.DARKNESS] * 2)])
    opponent = player(bench=[
        pokemon(678, hp=300, max_hp=330, player=1),
        pokemon(677, 2, hp=100, max_hp=100, player=1),
    ])
    select = selection(SelectContext.SWITCH, [
        Option(OptionType.CARD, area=AreaType.BENCH, index=0, playerIndex=1),
        Option(OptionType.CARD, area=AreaType.BENCH, index=1, playerIndex=1),
    ], effect=card(BOSS_ORDERS))
    ranked, _, reason = GrimFloorController().apply(observation(select, me, opponent, turn=7), [0, 1], 1)
    assert ranked[0] == 1
    assert reason == "prize_conversion:boss_target"

    opponent = player(bench=[
        pokemon(677, hp=80, max_hp=100, player=1), pokemon(675, 2, hp=20, max_hp=90, player=1)
    ])
    select = selection(SelectContext.DAMAGE, [
        Option(OptionType.CARD, area=AreaType.BENCH, index=0, playerIndex=1),
        Option(OptionType.CARD, area=AreaType.BENCH, index=1, playerIndex=1),
    ], effect=card(MARNIES_GRIMMSNARL_EX))
    ranked, _, reason = GrimFloorController().apply(observation(select, me, opponent, turn=7), [0, 1], 1)
    assert ranked[0] == 1
    assert reason == "prize_conversion:bench_ko"


def test_ready_promotion_and_productive_attack_over_end():
    grim = pokemon(MARNIES_GRIMMSNARL_EX, 2, energies=[EnergyType.DARKNESS] * 2)
    me = player(active=[pokemon(MUNKIDORI)], bench=[pokemon(SNORUNT, 3), grim])
    select = selection(SelectContext.TO_ACTIVE, [
        Option(OptionType.CARD, area=AreaType.BENCH, index=0, playerIndex=0),
        Option(OptionType.CARD, area=AreaType.BENCH, index=1, playerIndex=0),
    ])
    ranked, _, reason = GrimFloorController().apply(observation(select, me, turn=7), [0, 1], 1)
    assert ranked[0] == 1
    assert reason == "final_invariants:ready_promotion"

    me = player(active=[grim])
    select = selection(SelectContext.MAIN, [
        Option(OptionType.ATTACK, attackId=SHADOW_BULLET), Option(OptionType.END),
    ])
    ranked, _, reason = GrimFloorController().apply(observation(select, me, turn=7), [1, 0], 1)
    assert ranked[0] == 0
    assert reason == "final_invariants:end_with_productive_attack"


def test_main_phase_retreats_into_ready_attacker():
    me = player(
        active=[pokemon(MARNIES_IMPIDIMP)],
        bench=[pokemon(MARNIES_GRIMMSNARL_EX, 2, energies=[EnergyType.DARKNESS] * 2)],
    )
    select = selection(SelectContext.MAIN, [Option(OptionType.END), Option(OptionType.RETREAT)])
    ranked, _, reason = GrimFloorController().apply(observation(select, me, turn=7), [0, 1], 1)
    assert ranked[0] == 1
    assert reason == "final_invariants:retreat_to_ready"


def test_nullified_attack_is_not_fired_when_retreat_exists():
    me = player(active=[pokemon(MARNIES_GRIMMSNARL_EX, energies=[EnergyType.DARKNESS] * 2)])
    opponent = player(active=[pokemon(345, player=1)])
    select = selection(SelectContext.MAIN, [
        Option(OptionType.ATTACK, attackId=SHADOW_BULLET), Option(OptionType.RETREAT),
    ])
    ranked, _, reason = GrimFloorController().apply(observation(select, me, opponent, turn=7), [0, 1], 1)
    assert ranked[0] == 1
    assert reason == "final_invariants:nullified_attack"


def test_protected_discard_and_exact_fallthrough():
    me = player(hand=[card(RARE_CANDY), card(LILLIES_DETERMINATION, 2)], active=[pokemon(MUNKIDORI)])
    select = selection(SelectContext.DISCARD, [
        Option(OptionType.CARD, area=AreaType.HAND, index=0, playerIndex=0),
        Option(OptionType.CARD, area=AreaType.HAND, index=1, playerIndex=0),
    ])
    ranked, _, reason = GrimFloorController().apply(observation(select, me, turn=5), [0, 1], 1)
    assert ranked[0] == 1
    assert reason == "conversion:retain_critical_resource"

    select = selection(SelectContext.MAIN, [Option(OptionType.END)])
    ranked, desired, reason = GrimFloorController().apply(observation(select, me, turn=9), [0], 1)
    assert ranked == [0]
    assert desired == 1
    assert reason is None
