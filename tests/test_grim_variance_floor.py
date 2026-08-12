from __future__ import annotations

from types import SimpleNamespace as NS
from unittest.mock import patch

from cg.api import AreaType, EnergyType, Option, OptionType, SelectContext, SelectType

from ptcg_ai.card_ids import (
    BOSS_ORDERS,
    DARK_ENERGY,
    MARNIES_GRIMMSNARL_EX,
    MARNIES_IMPIDIMP,
    MARNIES_MORGREM,
    MUNKIDORI,
    SHADOW_BULLET,
    SNORUNT,
)
from ptcg_ai.grim_variance_floor import (
    GrimVarianceConfig,
    GrimVarianceFloorDirector,
    useful_capacity,
)


def card(card_id, serial=1, player=0):
    return NS(id=card_id, serial=serial, playerIndex=player)


def pokemon(card_id, serial=1, *, hp=100, max_hp=100, energies=(), player=0):
    return NS(
        id=card_id,
        serial=serial,
        playerIndex=player,
        hp=hp,
        maxHp=max_hp,
        appearThisTurn=False,
        energies=list(energies),
        energyCards=[card(DARK_ENERGY, serial * 10 + i, player) for i, _ in enumerate(energies)],
        tools=[],
        preEvolution=[],
    )


def player(*, hand=(), active=(), bench=(), deck_count=40):
    return NS(
        hand=list(hand),
        handCount=len(hand),
        active=list(active),
        bench=list(bench),
        discard=[],
        prize=[None] * 6,
        deckCount=deck_count,
        benchMax=5,
        poisoned=False,
        burned=False,
        asleep=False,
        paralyzed=False,
        confused=False,
    )


def selection(context, options, *, select_type, minimum=1, maximum=1, effect=None, context_card=None):
    return NS(
        type=select_type,
        context=context,
        option=list(options),
        effect=effect,
        contextCard=context_card,
        minCount=minimum,
        maxCount=maximum,
        remainDamageCounter=0,
        remainEnergyCost=0,
        deck=None,
    )


def observation(select, me, opponent=None, *, turn=9, retreated=False):
    opponent = opponent or player()
    return NS(
        select=select,
        current=NS(
            players=[me, opponent],
            yourIndex=0,
            firstPlayer=0,
            turn=turn,
            turnActionCount=0,
            supporterPlayed=False,
            stadiumPlayed=False,
            energyAttached=False,
            retreated=retreated,
            stadium=[],
            looking=None,
        ),
        logs=[],
    )


def config(*, punk=False, escape=False):
    return GrimVarianceConfig(punk_up_floor=punk, dead_active_escape=escape)


def ready_grim(serial=2):
    return pokemon(
        MARNIES_GRIMMSNARL_EX,
        serial,
        hp=320,
        max_hp=320,
        energies=[EnergyType.DARKNESS, EnergyType.DARKNESS],
    )


def test_useful_capacity_uses_exact_attack_readiness_caps():
    assert useful_capacity(player(active=[pokemon(MARNIES_IMPIDIMP, energies=[7])])) == 0
    assert useful_capacity(player(active=[pokemon(MARNIES_MORGREM, energies=[])])) == 2
    assert useful_capacity(player(active=[pokemon(MARNIES_MORGREM, energies=[7])])) == 1
    assert useful_capacity(player(active=[pokemon(MARNIES_GRIMMSNARL_EX, energies=[])])) == 2
    assert useful_capacity(player(active=[pokemon(MARNIES_GRIMMSNARL_EX, energies=[7, 7])])) == 0


def test_punk_up_does_not_activate_when_all_useful_caps_are_full():
    me = player(
        active=[pokemon(MARNIES_GRIMMSNARL_EX, energies=[7, 7])],
        bench=[pokemon(MARNIES_MORGREM, 2, energies=[7, 7]), pokemon(MARNIES_IMPIDIMP, 3, energies=[7])],
    )
    obs = observation(
        selection(
            SelectContext.ACTIVATE,
            [Option(OptionType.NO), Option(OptionType.YES)],
            select_type=SelectType.YES_NO,
            effect=card(MARNIES_GRIMMSNARL_EX),
        ),
        me,
    )
    assert GrimVarianceFloorDirector(config=config(punk=True)).apply(obs, [0, 1], 1) == ([0, 1], 1, None)


def test_punk_up_count_and_target_order_respect_caps():
    active = pokemon(MARNIES_GRIMMSNARL_EX, energies=[7])
    me = player(
        active=[active],
        bench=[pokemon(MARNIES_MORGREM, 3), pokemon(MARNIES_IMPIDIMP, 4)],
    )
    director = GrimVarianceFloorDirector(config=config(punk=True))
    count_obs = observation(
        selection(
            SelectContext.ATTACH_TO,
            [Option(OptionType.CARD, area=AreaType.DECK, index=i) for i in range(5)],
            select_type=SelectType.CARD,
            minimum=0,
            maximum=5,
            effect=card(MARNIES_GRIMMSNARL_EX),
        ),
        me,
    )
    _, desired, reason = director.apply(count_obs, list(range(5)), 5)
    assert (desired, reason) == (4, "variance_floor:punk_up_count")

    target_me = player(
        active=[active],
        bench=[
            pokemon(MARNIES_GRIMMSNARL_EX, 2),
            pokemon(MARNIES_MORGREM, 3),
            pokemon(MARNIES_IMPIDIMP, 4),
        ],
    )
    target_options = [
        Option(OptionType.CARD, area=AreaType.BENCH, index=2, playerIndex=0),
        Option(OptionType.CARD, area=AreaType.BENCH, index=1, playerIndex=0),
        Option(OptionType.CARD, area=AreaType.BENCH, index=0, playerIndex=0),
        Option(OptionType.CARD, area=AreaType.ACTIVE, index=0, playerIndex=0),
    ]
    target_obs = observation(
        selection(
            SelectContext.ATTACH_FROM,
            target_options,
            select_type=SelectType.CARD,
            effect=card(MARNIES_GRIMMSNARL_EX),
            context_card=card(DARK_ENERGY),
        ),
        target_me,
    )
    ranked, _, reason = director.apply(target_obs, [0, 1, 2, 3], 1)
    assert ranked[0] == 3
    assert reason == "variance_floor:punk_up_target"


def test_no_variance_rule_is_exact_fallthrough_for_main_and_nested_prompts():
    me = player(active=[pokemon(MUNKIDORI)])
    director = GrimVarianceFloorDirector(config=config())
    for select in (
        selection(SelectContext.MAIN, [Option(OptionType.END)], select_type=SelectType.MAIN),
        selection(SelectContext.ACTIVATE, [Option(OptionType.NO)], select_type=SelectType.YES_NO),
        selection(SelectContext.ATTACH_TO, [Option(OptionType.CARD)], select_type=SelectType.CARD),
    ):
        obs = observation(select, me)
        assert director.apply(obs, [0], 1) == ([0], 1, None)


def test_wrapper_preserves_existing_setup_shadow_and_boss_guardrails():
    director = GrimVarianceFloorDirector(config=config())
    setup = observation(
        selection(
            SelectContext.SETUP_ACTIVE_POKEMON,
            [
                Option(OptionType.CARD, area=AreaType.HAND, index=0, playerIndex=0),
                Option(OptionType.CARD, area=AreaType.HAND, index=1, playerIndex=0),
            ],
            select_type=SelectType.CARD,
            minimum=1,
        ),
        player(hand=[card(MUNKIDORI), card(MARNIES_IMPIDIMP)]),
        turn=0,
    )
    assert director.apply(setup, [0, 1], 1)[0][0] == 1

    main = observation(
        selection(
            SelectContext.MAIN,
            [Option(OptionType.RETREAT), Option(OptionType.ATTACK, attackId=SHADOW_BULLET)],
            select_type=SelectType.MAIN,
        ),
        player(active=[ready_grim()]),
        player(active=[pokemon(MUNKIDORI, player=1)]),
    )
    assert director.apply(main, [0, 1], 1)[2] == "attack:shadow_over_retreat"

    boss = observation(
        selection(
            SelectContext.MAIN,
            [Option(OptionType.PLAY, index=0), Option(OptionType.ATTACK, attackId=SHADOW_BULLET)],
            select_type=SelectType.MAIN,
        ),
        player(hand=[card(BOSS_ORDERS)], active=[ready_grim()]),
        player(active=[pokemon(MARNIES_IMPIDIMP, player=1, hp=70, max_hp=70)]),
    )
    assert director.apply(boss, [0, 1], 1)[2] == "attack:shadow_over_boss_active_ko"


def dead_support_main(me, options, *, turn=9):
    return observation(
        selection(SelectContext.MAIN, options, select_type=SelectType.MAIN),
        me,
        turn=turn,
    )


def test_dead_support_false_positive_guards():
    director = GrimVarianceFloorDirector(config=config(escape=True))
    cases = [
        player(active=[ready_grim()], bench=[ready_grim(2)]),
        player(active=[pokemon(MARNIES_IMPIDIMP)], bench=[ready_grim(2)]),
        player(active=[pokemon(MARNIES_MORGREM)], bench=[ready_grim(2)]),
        player(active=[pokemon(MUNKIDORI)]),
        player(active=[pokemon(MUNKIDORI)], bench=[pokemon(SNORUNT, 2, energies=[])]),
    ]
    for me in cases:
        obs = dead_support_main(me, [Option(OptionType.END), Option(OptionType.RETREAT)])
        assert director.apply(obs, [0, 1], 1) == ([0, 1], 1, None)


def test_dead_support_direct_retreat_promotes_ready_grim():
    director = GrimVarianceFloorDirector(config=config(escape=True))
    me = player(
        active=[pokemon(MUNKIDORI, serial=1)],
        bench=[pokemon(SNORUNT, serial=3), ready_grim(2)],
    )
    obs = dead_support_main(
        me,
        [Option(OptionType.END), Option(OptionType.RETREAT)],
    )
    ranked, _, reason = director.apply(obs, [0, 1], 1)
    assert ranked[0] == 1
    assert reason == "variance_floor:dead_support_retreat_to_ready_grim"
    director.commit(obs, [ranked[0]])
    assert director.telemetry()["variance_state"]["escape_stage"] == "promote"

    # The ready Grim is now option 0, but d842's semantic ranking puts the
    # other bench support first.  The wrapper must resolve the target anew.
    promote = observation(
        selection(
            SelectContext.TO_ACTIVE,
            [
                Option(OptionType.CARD, area=AreaType.BENCH, index=1, playerIndex=0),
                Option(OptionType.CARD, area=AreaType.BENCH, index=0, playerIndex=0),
            ],
            select_type=SelectType.CARD,
        ),
        me,
    )
    ranked, _, reason = director.apply(promote, [1, 0], 1)
    assert (ranked[0], reason) == (0, "variance_floor:escape_promote_ready_grim")
    assert promote.select.option[ranked[0]].index == 1
    director.commit(promote, [ranked[0]])
    assert director.telemetry()["variance_state"]["escape_pending"] is False


def test_attach_escape_then_semantic_retreat_and_promotion_with_reordered_indices():
    director = GrimVarianceFloorDirector(config=config(escape=True))
    me = player(
        hand=[card(DARK_ENERGY, 10)],
        active=[pokemon(MUNKIDORI, serial=1)],
        bench=[ready_grim(2)],
    )
    attach = dead_support_main(
        me,
        [
            Option(OptionType.END),
            Option(
                OptionType.ATTACH,
                area=AreaType.HAND,
                index=0,
                playerIndex=0,
                inPlayArea=AreaType.ACTIVE,
                inPlayIndex=0,
            ),
        ],
    )
    ranked, _, reason = director.apply(attach, [0, 1], 1)
    assert (ranked[0], reason) == (1, "variance_floor:attach_to_escape_dead_support")
    director.commit(attach, [1])
    assert director.telemetry()["variance_state"]["escape_pending"] is True

    me.active[0].energies = [EnergyType.DARKNESS]
    me.active[0].energyCards.append(card(DARK_ENERGY, 11))
    retreat = dead_support_main(me, [Option(OptionType.RETREAT), Option(OptionType.END)])
    ranked, _, reason = director.apply(retreat, [1, 0], 1)
    assert (ranked[0], reason) == (0, "variance_floor:complete_escape_retreat")
    director.commit(retreat, [0])

    promote = observation(
        selection(
            SelectContext.TO_ACTIVE,
            [Option(OptionType.CARD, area=AreaType.BENCH, index=0, playerIndex=0)],
            select_type=SelectType.CARD,
        ),
        me,
    )
    ranked, _, reason = director.apply(promote, [0], 1)
    assert (ranked[0], reason) == (0, "variance_floor:escape_promote_ready_grim")
    director.commit(promote, [0])
    assert director.telemetry()["variance_state"]["escape_pending"] is False


def test_escape_state_clears_on_reset_turn_change_target_loss_malformed_and_alternate_action():
    director = GrimVarianceFloorDirector(config=config(escape=True))
    me = player(hand=[card(DARK_ENERGY, 10)], active=[pokemon(MUNKIDORI, serial=1)], bench=[ready_grim(2)])
    attach = dead_support_main(
        me,
        [Option(OptionType.ATTACH, area=AreaType.HAND, index=0, inPlayArea=AreaType.ACTIVE, inPlayIndex=0)],
    )
    director.commit(attach, [0])
    assert director.telemetry()["variance_state"]["escape_pending"] is True
    director.reset()
    assert director.telemetry()["variance_state"]["escape_pending"] is False

    director.commit(attach, [0])
    next_turn = dead_support_main(me, [Option(OptionType.RETREAT)], turn=10)
    director.apply(next_turn, [0], 1)
    assert director.telemetry()["variance_state"]["escape_pending"] is False

    director.commit(attach, [0])
    me.active[0].serial = 9
    lost_target = dead_support_main(me, [Option(OptionType.RETREAT)], turn=9)
    director.apply(lost_target, [0], 1)
    assert director.telemetry()["variance_state"]["escape_pending"] is False

    director.commit(attach, [0])
    director.apply(None, [0], 1)
    assert director.telemetry()["variance_state"]["escape_pending"] is False


def test_escape_fails_closed_for_used_retreat_attack_and_disappearing_grim():
    for retreated in (True,):
        director = GrimVarianceFloorDirector(config=config(escape=True))
        obs = observation(
            selection(
                SelectContext.MAIN,
                [Option(OptionType.RETREAT), Option(OptionType.END)],
                select_type=SelectType.MAIN,
            ),
            player(active=[pokemon(MUNKIDORI)], bench=[ready_grim(2)]),
            retreated=retreated,
        )
        assert director.apply(obs, [1, 0], 1) == ([1, 0], 1, None)

    director = GrimVarianceFloorDirector(config=config(escape=True))
    productive = dead_support_main(
        player(active=[pokemon(MUNKIDORI)], bench=[ready_grim(2)]),
        [Option(OptionType.END), Option(OptionType.ATTACK, attackId=SHADOW_BULLET)],
    )
    assert director.apply(productive, [0, 1], 1) == ([0, 1], 1, None)

    me = player(active=[pokemon(MUNKIDORI, serial=1)], bench=[ready_grim(2)])
    direct = dead_support_main(me, [Option(OptionType.END), Option(OptionType.RETREAT)])
    ranked, _, _ = director.apply(direct, [0, 1], 1)
    director.commit(direct, [ranked[0]])
    me.bench.clear()
    promote = observation(
        selection(
            SelectContext.TO_ACTIVE,
            [Option(OptionType.CARD, area=AreaType.BENCH, index=0, playerIndex=0)],
            select_type=SelectType.CARD,
        ),
        me,
    )
    assert director.apply(promote, [0], 1) == ([0], 1, None)
    assert director.telemetry()["variance_state"]["escape_pending"] is False


def test_attach_escape_requires_active_basic_darkness_and_provable_retreat():
    me = player(
        hand=[card(DARK_ENERGY, 10), card(999, 11)],
        active=[pokemon(MUNKIDORI, serial=1)],
        bench=[ready_grim(2)],
    )
    cases = [
        Option(
            OptionType.ATTACH,
            area=AreaType.HAND,
            index=0,
            inPlayArea=AreaType.BENCH,
            inPlayIndex=0,
        ),
        Option(
            OptionType.ATTACH,
            area=AreaType.HAND,
            index=1,
            inPlayArea=AreaType.ACTIVE,
            inPlayIndex=0,
        ),
    ]
    director = GrimVarianceFloorDirector(config=config(escape=True))
    for option in cases:
        obs = dead_support_main(me, [Option(OptionType.END), option])
        assert director.apply(obs, [0, 1], 1) == ([0, 1], 1, None)

    # A one-Energy escape is not accepted when public card metadata proves the
    # support Active needs two Energy to retreat.
    option = Option(
        OptionType.ATTACH,
        area=AreaType.HAND,
        index=0,
        inPlayArea=AreaType.ACTIVE,
        inPlayIndex=0,
    )
    obs = dead_support_main(me, [Option(OptionType.END), option])
    with patch(
        "ptcg_ai.grim_variance_floor.card_table",
        return_value={MUNKIDORI: NS(retreatCost=2)},
    ):
        assert director.apply(obs, [0, 1], 1) == ([0, 1], 1, None)


def test_punk_count_option_number_is_selected_semantically():
    me = player(active=[pokemon(MARNIES_GRIMMSNARL_EX, energies=[7])])
    obs = observation(
        selection(
            SelectContext.ATTACH_TO,
            [Option(OptionType.NUMBER, number=2), Option(OptionType.NUMBER, number=1), Option(OptionType.NUMBER, number=3)],
            select_type=SelectType.COUNT,
            minimum=1,
            maximum=1,
            effect=card(MARNIES_GRIMMSNARL_EX),
        ),
        me,
    )
    ranked, desired, reason = GrimVarianceFloorDirector(config=config(punk=True)).apply(obs, [2, 0, 1], 1)
    assert (ranked[0], desired, reason) == (1, 1, "variance_floor:punk_up_count")
