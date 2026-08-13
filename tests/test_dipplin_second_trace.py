from __future__ import annotations

from types import SimpleNamespace as NS

from cg.api import OptionType

from scripts.dipplin_second_trace import SecondBucketTrace, opening_bucket


def pokemon(card_id, serial, energy=0):
    return NS(
        id=card_id,
        serial=serial,
        energyCards=[NS(id=1, serial=1000 + serial)] * energy,
        energies=[1] * energy,
        tools=[],
        preEvolution=[],
        hp=70,
        maxHp=70,
    )


def observation(
    *,
    turn,
    first=0,
    actor=1,
    active=88,
    bench=(),
    prizes=6,
    attacks=(),
    stadium=False,
):
    hero = NS(
        active=[pokemon(active, 10, 1 if active in {88, 93} else 0)],
        bench=list(bench),
        prize=[None] * prizes,
        hand=[NS(id=999, serial=999)],
        handCount=1,
    )
    opponent = NS(
        active=[pokemon(500, 20)],
        bench=[],
        prize=[None] * 6,
        hand=[NS(id=777, serial=777)],
        handCount=1,
    )
    options = [NS(type=OptionType.ATTACK, attackId=attack) for attack in attacks]
    return NS(
        current=NS(
            turn=turn,
            firstPlayer=first,
            yourIndex=actor,
            players=[opponent, hero],
            stadium=[NS(id=1245, serial=30)] if stadium else [],
            result=-1,
        ),
        select=NS(option=options),
    )


def test_opening_buckets_keep_applin_printings_distinct():
    assert opening_bucket(88, True) == "volbeat_active_quick_sign_legal"
    assert opening_bucket(88, False) == "volbeat_active_quick_sign_unavailable"
    assert opening_bucket(42, False) == "applin_42_active"
    assert opening_bucket(92, False) == "applin_92_active"


def test_trace_captures_opening_attack_board_and_public_only_metrics():
    trace = SecondBucketTrace(hero_seat=1)
    opening = observation(
        turn=2,
        active=88,
        bench=(pokemon(42, 11), pokemon(89, 12)),
        attacks=(107,),
    )
    trace.observe(opening)
    # The following opponent turn exposes the public end-of-turn board after
    # Quick Sign added a second Applin, without reading either hand.
    after_opening = observation(
        turn=3,
        actor=0,
        active=88,
        bench=(pokemon(42, 11), pokemon(89, 12), pokemon(92, 13)),
    )
    trace.observe(after_opening)
    attack = observation(
        turn=4,
        active=93,
        bench=(pokemon(89, 12), pokemon(90, 14), pokemon(42, 15, 1)),
        attacks=(115,),
        stadium=True,
    )
    trace.observe(attack)
    trace.record_action(attack, [0], 1)
    # Prize decrement after the first hit certifies a first-hit KO.
    prize = observation(
        turn=4,
        active=93,
        bench=(pokemon(89, 12), pokemon(90, 14), pokemon(42, 15, 1)),
        prizes=5,
        stadium=True,
    )
    trace.observe(prize)
    trace.observe(observation(turn=5, actor=0, active=93, prizes=5))
    result = trace.finalize(completed=True, result_seat=1)

    assert result["opening_bucket"] == "volbeat_active_quick_sign_legal"
    assert result["turn_one_board"]["applin_lines"] == 2
    assert result["turn_one_board"]["engine_lines"] == 1
    assert result["first_productive_attack_own_turn"] == 2
    assert result["first_attack_board"]["thwackey_count"] == 1
    assert result["first_attack_board"]["replacement_state"] == "energized_applin"
    assert result["first_attack_board"]["dipplin_count"] == 1
    assert result["first_attack_board"]["ready_dipplin_count"] == 1
    assert result["productive_attacks"] == 1
    assert result["first_hit_kos"] == 1
    assert result["prizes_taken"] == 1
    assert not any(result["public_information_contract"].values())


def test_dead_support_turn_reports_causal_prerequisites():
    trace = SecondBucketTrace(hero_seat=1)
    trace.observe(observation(turn=2, active=89, attacks=()))
    trace.observe(observation(turn=3, actor=0, active=89))
    trace.observe(observation(turn=4, active=89, bench=(pokemon(93, 15, 1),)))
    trace.observe(observation(turn=5, actor=0, active=89, bench=(pokemon(93, 15, 1),)))
    result = trace.finalize(completed=True, result_seat=0)

    assert result["opening_bucket"] == "grookey_active"
    assert result["dead_turns"] == 1
    assert result["trapped_active_turns"] == 1
    assert result["missed_attack_prerequisites"]["retreat_promotion"] == 1
    assert result["missed_attack_prerequisites"]["festival"] == 1
