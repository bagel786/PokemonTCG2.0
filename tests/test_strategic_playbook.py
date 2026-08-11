from types import SimpleNamespace as NS

import numpy as np
from cg.api import AreaType, EnergyType, Option, OptionType, SelectContext, SelectType

from ptcg_ai.strategic_playbook import (
    BOSS_ORDERS,
    DARK_ENERGY,
    FESTIVAL_GROUNDS,
    GRIMMSNARL,
    IMPIDIMP,
    MORGREM,
    MUNKIDORI,
    SHADOW_BULLET,
    SPIKEMUTH,
    Enforcement,
    Objective,
    PublicStrategicRouter,
    StrategicPolicy,
    build_public_summary,
)


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
        discard=list(discard), prize=[card(0, 900 + i) for i in range(prizes)], deckCount=deck_count,
        benchMax=5, poisoned=False, burned=False, asleep=False, paralyzed=False, confused=False,
    )


def selection(context, options, *, effect=None, minimum=1, maximum=1):
    return NS(
        type=SelectType.MAIN if context == SelectContext.MAIN else SelectType.CARD,
        context=context, option=list(options), effect=effect, contextCard=None,
        minCount=minimum, maxCount=maximum, remainDamageCounter=0, remainEnergyCost=0, deck=None,
    )


def observation(select, me, opponent=None, *, turn=3, first=0, own=0, stadium=()):
    opponent = opponent or player()
    players = [me, opponent] if own == 0 else [opponent, me]
    state = NS(
        players=players, yourIndex=own, firstPlayer=first, turn=turn, result=-1,
        turnActionCount=0, supporterPlayed=False, stadiumPlayed=False, energyAttached=False,
        retreated=False, stadium=list(stadium), looking=None,
    )
    return NS(select=select, current=state, logs=[])


def policy():
    return StrategicPolicy({"router_minimum": .55, "preference_logit_margin": .75}, model=NS(feature_version=2))


def focused_policy():
    objectives = {
        "grim": ["closeout_prize_route", "deny_evolution_engine"],
        "alakazam": ["closeout_prize_route", "deny_evolution_engine", "pressure_primary_attacker"],
        "lopunny": ["closeout_prize_route", "pressure_primary_attacker"],
        "dragapult": ["closeout_prize_route", "deny_evolution_engine", "pressure_primary_attacker"],
        "crustle": ["closeout_prize_route", "deny_stadium_engine", "deny_evolution_engine"],
        "kangaskhan_generic": ["closeout_prize_route", "pressure_primary_attacker"],
    }
    return StrategicPolicy({
        "router_minimum": .55,
        "actual_second_only": True,
        "enabled_routes": list(objectives),
        "allowed_route_statuses": ["provisional", "high_confidence", "locked"],
        "route_objectives": objectives,
        "require_main_for_plan": True,
        "require_owned_nested_prompts": True,
        "enable_build_commitments": False,
        "enable_count_overrides": False,
    }, model=NS(feature_version=2))


def ready_grim(serial=10, *, hp=320):
    return pokemon(GRIMMSNARL, serial, hp=hp, max_hp=320, energies=[EnergyType.DARKNESS] * 2)


def plan_for(controller, obs):
    summary = build_public_summary(obs, controller.router)
    controller._ensure_plan(obs, summary)
    return summary, controller.plan


def classify(controller, obs, summary, index, development=False):
    return controller._classify(obs, summary, index, development)


def test_router_adds_archaludon_and_refines_generic_kangaskhan():
    router = PublicStrategicRouter()
    me = player(active=[pokemon(IMPIDIMP)])
    generic = observation(selection(SelectContext.MAIN, [Option(OptionType.END)]), me,
                          player(active=[pokemon(756, player=1)]))
    assert router.update(generic) == ("kangaskhan_generic", .62, "provisional")
    refined = observation(selection(SelectContext.MAIN, [Option(OptionType.END)]), me,
                          player(active=[pokemon(756, player=1)], bench=[pokemon(96, 2, player=1)]))
    assert router.update(refined)[0] == "ogerpon"
    arch = PublicStrategicRouter()
    arch_obs = observation(selection(SelectContext.MAIN, [Option(OptionType.END)]), me,
                           player(active=[pokemon(169, player=1)]))
    assert arch.update(arch_obs)[0] == "archaludon"


def test_focused_profile_is_actual_second_only_and_waits_for_a_supported_route():
    controller = focused_policy()
    me = player(active=[ready_grim()])
    grim = player(active=[pokemon(GRIMMSNARL, player=1)])
    actual_first = observation(
        selection(SelectContext.MAIN, [Option(OptionType.END)]), me, grim, first=0, own=0,
    )
    first_summary = build_public_summary(actual_first, controller.router)
    controller._ensure_plan(actual_first, first_summary)
    assert not first_summary.actual_second
    assert controller.plan is None

    controller.reset()
    unknown = observation(
        selection(SelectContext.MAIN, [Option(OptionType.END)]), me,
        player(active=[pokemon(999, player=1)]), first=1, own=0,
    )
    unknown_summary = build_public_summary(unknown, controller.router)
    controller._ensure_plan(unknown, unknown_summary)
    assert unknown_summary.actual_second
    assert controller.plan is None

    controller.reset()
    actual_second = observation(
        selection(SelectContext.MAIN, [Option(OptionType.END)]), me, grim, first=1, own=0,
    )
    second_summary = build_public_summary(actual_second, controller.router)
    controller._ensure_plan(actual_second, second_summary)
    assert second_summary.actual_second
    assert controller.plan is not None
    assert controller.plan.route == "grim"


def test_focused_profile_does_not_restore_generic_build_control():
    controller = focused_policy()
    me = player(active=[pokemon(IMPIDIMP)], hand=[card(13)])
    opponent = player(active=[pokemon(GRIMMSNARL, player=1)])
    obs = observation(
        selection(SelectContext.MAIN, [Option(OptionType.PLAY, index=0), Option(OptionType.END)]),
        me, opponent, first=1, own=0,
    )
    _, plan = plan_for(controller, obs)
    assert plan.objective == Objective.DEFAULT_A2


def test_focused_profile_leaves_mirror_primary_pressure_to_a2():
    controller = focused_policy()
    me = player(hand=[card(BOSS_ORDERS)], active=[ready_grim()])
    opponent = player(
        active=[pokemon(646, player=1)],
        bench=[pokemon(GRIMMSNARL, 42, hp=180, max_hp=320,
                       energies=[EnergyType.DARKNESS] * 2, player=1)],
    )
    obs = observation(selection(SelectContext.MAIN, [
        Option(OptionType.PLAY, index=0), Option(OptionType.ATTACK, attackId=SHADOW_BULLET),
    ]), me, opponent, first=1, own=0)
    _, plan = plan_for(controller, obs)
    assert plan.objective != Objective.PRESSURE_PRIMARY_ATTACKER


def test_focused_profile_never_hijacks_an_unowned_nested_prompt():
    controller = focused_policy()
    me = player(hand=[card(BOSS_ORDERS)], active=[ready_grim()])
    opponent = player(active=[pokemon(646, player=1)], bench=[pokemon(GRIMMSNARL, 42, player=1)])
    main = observation(
        selection(SelectContext.MAIN, [Option(OptionType.PLAY, index=0), Option(OptionType.ATTACK, attackId=SHADOW_BULLET)]),
        me, opponent, first=1, own=0,
    )
    plan_for(controller, main)
    nested = observation(selection(SelectContext.SWITCH, [
        Option(OptionType.CARD, area=AreaType.BENCH, index=0, playerIndex=1),
    ], effect=card(BOSS_ORDERS)), me, opponent, first=1, own=0)
    summary = build_public_summary(nested, controller.router)
    controller._ensure_plan(nested, summary)
    assert classify(controller, nested, summary, 0) == ("neutral", "unowned_nested_prompt")


def test_immediate_closeout_does_not_promote_boss_over_the_winning_attack():
    controller = focused_policy()
    me = player(hand=[card(BOSS_ORDERS)], active=[ready_grim()], prizes=1)
    opponent = player(active=[pokemon(646, hp=180, max_hp=180, player=1)], bench=[pokemon(GRIMMSNARL, 42, player=1)])
    obs = observation(selection(SelectContext.MAIN, [
        Option(OptionType.PLAY, index=0), Option(OptionType.ATTACK, attackId=SHADOW_BULLET),
    ]), me, opponent, first=1, own=0)
    summary, plan = plan_for(controller, obs)
    assert plan.objective == Objective.CLOSEOUT_PRIZE_ROUTE
    assert classify(controller, obs, summary, 0)[0] == "neutral"
    assert classify(controller, obs, summary, 1)[0] == "advancing"


def test_focused_lopunny_route_can_boss_an_invested_three_prize_primary():
    controller = focused_policy()
    me = player(hand=[card(BOSS_ORDERS)], active=[ready_grim()])
    opponent = player(
        active=[pokemon(66, player=1)],
        bench=[pokemon(849, 42, hp=330, max_hp=330, energies=[EnergyType.DARKNESS] * 3, player=1)],
    )
    obs = observation(selection(SelectContext.MAIN, [
        Option(OptionType.PLAY, index=0), Option(OptionType.ATTACK, attackId=SHADOW_BULLET),
    ]), me, opponent, first=1, own=0)
    summary, plan = plan_for(controller, obs)
    assert plan.route == "lopunny"
    assert plan.objective == Objective.PRESSURE_PRIMARY_ATTACKER
    assert plan.target_serial == 42
    assert classify(controller, obs, summary, 0) == ("advancing", "boss_invested_primary")


def test_dead_active_sequence_is_hard_and_persists_across_prompts():
    controller = policy()
    me = player(active=[pokemon(MUNKIDORI)], bench=[ready_grim()])
    main = observation(selection(SelectContext.MAIN, [Option(OptionType.END), Option(OptionType.RETREAT)]), me)
    summary, plan = plan_for(controller, main)
    assert (plan.objective, plan.enforcement) == (Objective.ESCAPE_DEAD_ACTIVE, Enforcement.HARD)
    assert classify(controller, main, summary, 1)[0] == "advancing"
    promote = observation(selection(SelectContext.TO_ACTIVE, [
        Option(OptionType.CARD, area=AreaType.BENCH, index=0, playerIndex=0)
    ]), me, turn=3)
    promote_summary = build_public_summary(promote, controller.router)
    controller._ensure_plan(promote, promote_summary)
    assert controller.plan.objective == Objective.ESCAPE_DEAD_ACTIVE
    assert classify(controller, promote, promote_summary, 0)[0] == "advancing"


def test_stadium_denial_commits_before_attack():
    controller = policy()
    me = player(hand=[card(SPIKEMUTH)], active=[ready_grim()], bench=[ready_grim(11)])
    opponent = player(active=[pokemon(93, player=1)])
    obs = observation(selection(SelectContext.MAIN, [
        Option(OptionType.PLAY, index=0), Option(OptionType.ATTACK, attackId=SHADOW_BULLET)
    ]), me, opponent, stadium=[card(FESTIVAL_GROUNDS)])
    summary, plan = plan_for(controller, obs)
    assert plan.objective == Objective.DENY_STADIUM_ENGINE
    assert classify(controller, obs, summary, 0)[0] == "advancing"
    assert classify(controller, obs, summary, 1)[0] == "contradicting"


def test_lucario_target_commitment_rejects_irrelevant_solrock():
    controller = policy()
    me = player(hand=[card(BOSS_ORDERS)], active=[ready_grim()], bench=[ready_grim(11)])
    opponent = player(active=[pokemon(675, 1, player=1)], bench=[
        pokemon(678, 42, hp=150, max_hp=330, energies=[EnergyType.FIGHTING], player=1),
        pokemon(676, 43, player=1),
    ])
    main = observation(selection(SelectContext.MAIN, [
        Option(OptionType.PLAY, index=0),
        Option(OptionType.ATTACK, attackId=SHADOW_BULLET),
    ]), me, opponent, turn=5)
    summary, plan = plan_for(controller, main)
    assert plan.objective == Objective.PRESSURE_PRIMARY_ATTACKER
    assert plan.target_serial == 42
    assert classify(controller, main, summary, 0)[0] == "advancing"
    target = observation(selection(SelectContext.SWITCH, [
        Option(OptionType.CARD, area=AreaType.BENCH, index=0, playerIndex=1),
        Option(OptionType.CARD, area=AreaType.BENCH, index=1, playerIndex=1),
    ], effect=card(BOSS_ORDERS)), me, opponent, turn=5)
    summary = build_public_summary(target, controller.router)
    controller._ensure_plan(target, summary)
    assert classify(controller, target, summary, 0)[0] == "neutral"
    controller.plan.subgoals["initiated_target_sequence"] = True
    assert classify(controller, target, summary, 0)[0] == "advancing"
    assert classify(controller, target, summary, 1)[0] == "contradicting"


def test_dragapult_tera_bench_damage_is_mechanically_forbidden():
    controller = policy()
    me = player(active=[ready_grim()], bench=[ready_grim(11)])
    opponent = player(active=[pokemon(119, player=1)], bench=[pokemon(121, 42, player=1)])
    obs = observation(selection(SelectContext.DAMAGE, [
        Option(OptionType.CARD, area=AreaType.BENCH, index=0, playerIndex=1)
    ], effect=card(GRIMMSNARL)), me, opponent, turn=5)
    summary, _ = plan_for(controller, obs)
    assert controller._mechanically_forbidden(obs, summary, 0) == "protected_tera_bench"


def test_crustle_nullifies_grim_attack_and_one_prize_plan_stays_disabled():
    controller = policy()
    me = player(active=[ready_grim()], bench=[pokemon(MORGREM, 11, energies=[EnergyType.DARKNESS])])
    opponent = player(active=[pokemon(345, player=1)])
    obs = observation(selection(SelectContext.MAIN, [
        Option(OptionType.ATTACK, attackId=SHADOW_BULLET), Option(OptionType.END)
    ]), me, opponent, turn=5)
    summary, plan = plan_for(controller, obs)
    assert plan.objective != Objective.PRESERVE_ONE_PRIZE_ATTACKER
    assert plan.objective != Objective.PRESSURE_PRIMARY_ATTACKER
    assert controller._mechanically_forbidden(obs, summary, 0) == "nullified_attack"


def test_proactive_munkidori_energy_is_not_mislabeled_mechanically_forbidden():
    controller = policy()
    me = player(hand=[card(DARK_ENERGY)], active=[pokemon(IMPIDIMP)], bench=[pokemon(MUNKIDORI, 12)])
    obs = observation(selection(SelectContext.MAIN, [
        Option(OptionType.ATTACH, index=0, inPlayArea=AreaType.BENCH, inPlayIndex=0),
        Option(OptionType.END),
    ]), me, turn=3)
    summary, _ = plan_for(controller, obs)
    assert controller._mechanically_forbidden(obs, summary, 0) is None


def test_build_and_count_overrides_are_disabled_until_ablation_certifies_them():
    controller = policy()
    me = player(active=[pokemon(IMPIDIMP)], bench=[])
    main = observation(selection(SelectContext.MAIN, [Option(OptionType.END)]), me, turn=1)
    _, plan = plan_for(controller, main)
    assert plan.objective != Objective.BUILD_FIRST_ATTACKER

    setup = observation(selection(SelectContext.SETUP_BENCH_POKEMON, [
        Option(OptionType.CARD, area=AreaType.HAND, index=i, playerIndex=0) for i in range(4)
    ], minimum=0, maximum=4), me, turn=0)
    summary = build_public_summary(setup, controller.router)
    controller._ensure_plan(setup, summary)
    assert controller._desired_count(setup, summary, np.zeros(8)) == 0


def test_ogerpon_180_plus_30_breakpoint_selects_conversion():
    controller = policy()
    me = player(active=[ready_grim(hp=290)], bench=[ready_grim(11), pokemon(MUNKIDORI, 12)])
    opponent = player(active=[pokemon(96, 42, hp=210, max_hp=210, player=1)])
    obs = observation(selection(SelectContext.MAIN, [
        Option(OptionType.ABILITY, area=AreaType.BENCH, index=1),
        Option(OptionType.ATTACK, attackId=SHADOW_BULLET),
    ]), me, opponent, turn=5)
    summary, plan = plan_for(controller, obs)
    assert plan.objective == Objective.CONVERT_DAMAGE_BREAKPOINT
    assert classify(controller, obs, summary, 0)[0] == "advancing"


def test_punk_up_count_funds_real_deficits_not_mechanical_maximum():
    controller = policy()
    controller.config["enable_count_overrides"] = True
    me = player(active=[pokemon(GRIMMSNARL, energies=[EnergyType.DARKNESS])],
                bench=[pokemon(MORGREM, 2)])
    obs = observation(selection(SelectContext.ATTACH_TO, [
        Option(OptionType.CARD, area=AreaType.DECK, index=i, playerIndex=0) for i in range(5)
    ], effect=card(GRIMMSNARL), minimum=0, maximum=5), me)
    summary, _ = plan_for(controller, obs)
    assert controller._desired_count(obs, summary, np.zeros(8)) == 3


def test_froslass_lethal_activates_hand_management():
    controller = policy()
    me = player(hand=[card(1000 + i, i + 1) for i in range(6)], active=[ready_grim(hp=250)], bench=[ready_grim(11)])
    opponent = player(active=[pokemon(861, 42, energies=[EnergyType.WATER], player=1)])
    obs = observation(selection(SelectContext.MAIN, [Option(OptionType.END)]), me, opponent, turn=5)
    _, plan = plan_for(controller, obs)
    assert plan.objective == Objective.MANAGE_HAND_SIZE


def test_immediate_closeout_interrupts_prior_plan():
    controller = policy()
    me = player(active=[ready_grim()], bench=[ready_grim(11)])
    opponent = player(active=[pokemon(678, 42, hp=180, max_hp=330, player=1)])
    no_attack = observation(selection(SelectContext.EFFECT_TARGET, [
        Option(OptionType.CARD, area=AreaType.ACTIVE, index=0, playerIndex=1)
    ]), me, opponent, turn=5)
    plan_for(controller, no_attack)
    win = observation(selection(SelectContext.MAIN, [
        Option(OptionType.ATTACK, attackId=SHADOW_BULLET), Option(OptionType.END)
    ]), player(active=[ready_grim()], bench=[ready_grim(11)], prizes=2), opponent, turn=5)
    summary = build_public_summary(win, controller.router)
    controller._ensure_plan(win, summary)
    assert (controller.plan.objective, controller.plan.enforcement) == (Objective.CLOSEOUT_PRIZE_ROUTE, Enforcement.HARD)


def test_target_disappearance_terminates_cleanly():
    controller = policy()
    me = player(active=[ready_grim()], bench=[ready_grim(11)])
    opponent = player(active=[pokemon(678, 42, hp=150, max_hp=330, player=1)])
    first = observation(selection(SelectContext.MAIN, [Option(OptionType.ATTACK, attackId=SHADOW_BULLET)]), me, opponent, turn=5)
    _, plan = plan_for(controller, first)
    assert plan.target_serial == 42
    gone = observation(selection(SelectContext.MAIN, [Option(OptionType.END)]), me,
                       player(active=[pokemon(675, 55, player=1)]), turn=5)
    summary = build_public_summary(gone, controller.router)
    controller._ensure_plan(gone, summary)
    assert controller.telemetry["termination:target_disappeared"] == 1
    assert controller.plan.target_serial != 42


def test_archaludon_duraludon_is_evolution_denial_target():
    controller = policy()
    me = player(hand=[card(BOSS_ORDERS)], active=[ready_grim()], bench=[ready_grim(11)])
    opponent = player(active=[pokemon(57, player=1)], bench=[pokemon(169, 42, player=1)])
    obs = observation(selection(SelectContext.MAIN, [
        Option(OptionType.PLAY, index=0),
        Option(OptionType.ATTACK, attackId=SHADOW_BULLET),
    ]), me, opponent, turn=5)
    _, plan = plan_for(controller, obs)
    assert plan.route == "archaludon"
    assert plan.objective == Objective.DENY_EVOLUTION_ENGINE
    assert plan.target_serial == 42
