from types import SimpleNamespace as NS

from cg.api import AreaType, EnergyType, Option, OptionType, SelectContext, SelectType

from ptcg_ai.card_ids import (
    BOSS_ORDERS,
    DARK_ENERGY,
    MARNIES_GRIMMSNARL_EX,
    MARNIES_IMPIDIMP,
    MUNKIDORI,
    SHADOW_BULLET,
    SNORUNT,
)
from ptcg_ai.grim_guardrails import GrimGuardrailDirector


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
        energyCards=[card(DARK_ENERGY, serial * 10 + offset, player) for offset, _ in enumerate(energies)],
        tools=[],
        preEvolution=[],
    )


def player(*, hand=(), active=(), bench=()):
    return NS(
        hand=list(hand),
        handCount=len(hand),
        active=list(active),
        bench=list(bench),
        discard=[],
        prize=[None] * 6,
        deckCount=40,
        benchMax=5,
        poisoned=False,
        burned=False,
        asleep=False,
        paralyzed=False,
        confused=False,
    )


def selection(context, options, *, select_type, minimum=1, maximum=1):
    return NS(
        type=select_type,
        context=context,
        option=list(options),
        effect=None,
        contextCard=None,
        minCount=minimum,
        maxCount=maximum,
        remainDamageCounter=0,
        remainEnergyCost=0,
        deck=None,
    )


def observation(select, me, opponent=None, *, turn=1):
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
            retreated=False,
            stadium=[],
            looking=None,
        ),
        logs=[],
    )


def setup_obs(cards, *, active=False, maximum=1):
    context = SelectContext.SETUP_ACTIVE_POKEMON if active else SelectContext.SETUP_BENCH_POKEMON
    minimum = 1 if active else 0
    hand = [card(card_id, serial=index + 1) for index, card_id in enumerate(cards)]
    options = [
        Option(OptionType.CARD, area=AreaType.HAND, index=index, playerIndex=0)
        for index in range(len(hand))
    ]
    return observation(
        selection(
            context,
            options,
            select_type=SelectType.CARD,
            minimum=minimum,
            maximum=1 if active else maximum,
        ),
        player(hand=hand),
        turn=0,
    )


def main_obs(options, me, opponent):
    return observation(
        selection(SelectContext.MAIN, options, select_type=SelectType.MAIN),
        me,
        opponent,
        turn=9,
    )


def ready_grim():
    return pokemon(
        MARNIES_GRIMMSNARL_EX,
        hp=320,
        max_hp=320,
        energies=(EnergyType.DARKNESS, EnergyType.DARKNESS),
    )


def test_staged_setup_tracks_committed_semantics_and_resets():
    director = GrimGuardrailDirector()

    active = setup_obs([MUNKIDORI, MARNIES_IMPIDIMP], active=True)
    ranked, desired, reason = director.apply(active, [0, 1], 1)
    assert (ranked[0], desired, reason) == (1, 1, "setup:active_impidimp")
    director.commit(active, ranked[:desired])

    # Indices are permuted at the next prompt.  The director remembers only
    # that one Impidimp was selected and resolves the new index from scratch.
    bench_imp = setup_obs([MARNIES_IMPIDIMP, MUNKIDORI, SNORUNT])
    ranked, desired, reason = director.apply(bench_imp, [1, 2, 0], 0)
    assert (ranked[0], desired, reason) == (0, 1, "setup:bench_impidimp")
    director.commit(bench_imp, ranked[:desired])

    bench_snorunt = setup_obs([MUNKIDORI, SNORUNT])
    ranked, desired, reason = director.apply(bench_snorunt, [0, 1], 0)
    assert (ranked[0], desired, reason) == (1, 1, "setup:bench_snorunt")
    director.commit(bench_snorunt, ranked[:desired])

    full = setup_obs([MUNKIDORI])
    assert director.apply(full, [0], 0) == ([0], 0, None)
    telemetry = director.telemetry()
    assert telemetry["setup_width"] == 3
    assert telemetry["setup_roles"] == {"impidimp": 2, "snorunt": 1, "munkidori": 0}
    assert telemetry["last_commit"] == "setup:bench:snorunt"
    assert telemetry["budgets"]["setup_bench"]["used"] == 2

    director.reset()
    assert director.telemetry()["setup_width"] == 0
    assert director.telemetry()["interventions"] == {}
    assert director.telemetry()["budgets"]["setup_bench"]["used"] == 0


def test_setup_uses_next_currently_legal_role_and_only_setup_prompts():
    director = GrimGuardrailDirector()
    obs = setup_obs([MUNKIDORI, SNORUNT])
    ranked, desired, reason = director.apply(obs, [0, 1], 0)
    assert (ranked[0], desired, reason) == (1, 1, "setup:bench_snorunt")

    not_setup = observation(
        selection(
            SelectContext.TO_HAND,
            obs.select.option,
            select_type=SelectType.CARD,
            minimum=0,
            maximum=1,
        ),
        obs.current.players[0],
        turn=0,
    )
    assert director.apply(not_setup, [0, 1], 0) == ([0, 1], 0, None)

    mandatory_bench = setup_obs([MARNIES_IMPIDIMP])
    mandatory_bench.select.minCount = 1
    assert director.apply(mandatory_bench, [0], 1) == ([0], 1, None)


def test_setup_option_permutation_does_not_change_semantic_choice():
    first = GrimGuardrailDirector()
    left = setup_obs([MUNKIDORI, MARNIES_IMPIDIMP], active=True)
    assert first.apply(left, [0, 1], 1)[0][0] == 1

    second = GrimGuardrailDirector()
    right = setup_obs([MARNIES_IMPIDIMP, MUNKIDORI], active=True)
    assert second.apply(right, [1, 0], 1)[0][0] == 0


def test_real_single_bench_multiselect_fills_width_three_in_role_order():
    director = GrimGuardrailDirector()
    active = setup_obs([MARNIES_IMPIDIMP], active=True)
    director.commit(active, [0])

    # The engine presents one optional multi-select prompt, not repeated
    # one-card prompts.  Fill both remaining board slots in this call.
    bench = setup_obs(
        [MUNKIDORI, SNORUNT, MARNIES_IMPIDIMP],
        maximum=3,
    )
    ranked, desired, reason = director.apply(bench, [0, 1, 2], 0)
    assert (ranked, desired, reason) == (
        [2, 1, 0],
        2,
        "setup:bench_impidimp_snorunt",
    )
    director.commit(bench, ranked[:desired])
    assert director.telemetry()["setup_width"] == 3
    assert director.telemetry()["setup_roles"] == {
        "impidimp": 2,
        "snorunt": 1,
        "munkidori": 0,
    }
    assert not any("option" in name or "obs" in name for name in director.__dict__)


def test_setup_width_falls_back_to_duplicate_legal_roles_when_ideal_roles_absent():
    director = GrimGuardrailDirector()
    active = setup_obs([MUNKIDORI], active=True)
    director.commit(active, [0])
    bench = setup_obs([MUNKIDORI, MUNKIDORI], maximum=2)
    ranked, desired, reason = director.apply(bench, [1, 0], 0)
    assert (ranked, desired, reason) == (
        [1, 0],
        2,
        "setup:bench_munkidori_munkidori",
    )
    director.commit(bench, ranked[:desired])
    assert director.telemetry()["setup_width"] == 3


def test_ready_productive_shadow_bullet_replaces_retreat():
    options = [Option(OptionType.RETREAT), Option(OptionType.ATTACK, attackId=SHADOW_BULLET)]
    obs = main_obs(
        options,
        player(active=[ready_grim()]),
        player(active=[pokemon(MUNKIDORI, player=1, hp=110, max_hp=110)]),
    )
    ranked, desired, reason = GrimGuardrailDirector().apply(obs, [0, 1], 1)
    assert (ranked, desired, reason) == ([1, 0], 1, "attack:shadow_over_retreat")


def test_shadow_over_retreat_is_option_permutation_safe():
    options = [Option(OptionType.ATTACK, attackId=SHADOW_BULLET), Option(OptionType.RETREAT)]
    obs = main_obs(
        options,
        player(active=[ready_grim()]),
        player(active=[pokemon(MUNKIDORI, player=1, hp=110, max_hp=110)]),
    )
    assert GrimGuardrailDirector().apply(obs, [1, 0], 1)[0] == [0, 1]


def test_boss_is_replaced_only_for_best_immediate_active_ko():
    me = player(hand=[card(BOSS_ORDERS)], active=[ready_grim()])
    options = [Option(OptionType.PLAY, index=0), Option(OptionType.ATTACK, attackId=SHADOW_BULLET)]
    opponent = player(
        active=[pokemon(MARNIES_IMPIDIMP, player=1, hp=70, max_hp=70)],
        bench=[pokemon(MARNIES_IMPIDIMP, 2, player=1, hp=70, max_hp=70)],
    )
    obs = main_obs(options, me, opponent)
    ranked, desired, reason = GrimGuardrailDirector().apply(obs, [0, 1], 1)
    assert (ranked, desired, reason) == ([1, 0], 1, "attack:shadow_over_boss_active_ko")

    # A two-prize benched KO could improve immediate conversion, so the rule
    # is uncertain and must preserve d842's Boss decision.
    better_bench = player(
        active=[pokemon(MARNIES_IMPIDIMP, player=1, hp=70, max_hp=70)],
        bench=[pokemon(MARNIES_GRIMMSNARL_EX, 2, player=1, hp=170, max_hp=320)],
    )
    uncertain = main_obs(options, me, better_bench)
    assert GrimGuardrailDirector().apply(uncertain, [0, 1], 1) == ([0, 1], 1, None)


def test_boss_falls_through_when_active_is_not_an_immediate_ko():
    me = player(hand=[card(BOSS_ORDERS)], active=[ready_grim()])
    options = [Option(OptionType.PLAY, index=0), Option(OptionType.ATTACK, attackId=SHADOW_BULLET)]
    opponent = player(active=[pokemon(MARNIES_GRIMMSNARL_EX, player=1, hp=320, max_hp=320)])
    obs = main_obs(options, me, opponent)
    assert GrimGuardrailDirector().apply(obs, [0, 1], 1) == ([0, 1], 1, None)


def test_nullified_shadow_and_uncertain_states_fall_through():
    options = [Option(OptionType.RETREAT), Option(OptionType.ATTACK, attackId=SHADOW_BULLET)]
    wall = player(active=[pokemon(345, player=1, hp=150, max_hp=150)])
    obs = main_obs(options, player(active=[ready_grim()]), wall)
    assert GrimGuardrailDirector().apply(obs, [0, 1], 1) == ([0, 1], 1, None)

    not_ready = main_obs(
        options,
        player(active=[pokemon(MARNIES_GRIMMSNARL_EX, hp=320, max_hp=320, energies=())]),
        player(active=[pokemon(MUNKIDORI, player=1, hp=110, max_hp=110)]),
    )
    assert GrimGuardrailDirector().apply(not_ready, [0, 1], 1) == ([0, 1], 1, None)


def test_unapproved_item_and_supporter_patterns_remain_exact_fallthrough():
    for card_id in (1152, 1097, 1219):  # Poké Pad, Night Stretcher, Petrel
        me = player(hand=[card(card_id)], active=[ready_grim()])
        options = [Option(OptionType.PLAY, index=0), Option(OptionType.ATTACK, attackId=SHADOW_BULLET)]
        obs = main_obs(
            options,
            me,
            player(active=[pokemon(MARNIES_IMPIDIMP, player=1, hp=70, max_hp=70)]),
        )
        assert GrimGuardrailDirector().apply(obs, [0, 1], 1) == ([0, 1], 1, None)
