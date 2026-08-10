from __future__ import annotations

from types import SimpleNamespace as NS

from cg.api import AreaType, Option, OptionType, SelectContext

from ptcg_ai.card_ids import (
    DARK_ENERGY,
    FROSLASS,
    MARNIES_GRIMMSNARL_EX,
    MARNIES_IMPIDIMP,
    MARNIES_MORGREM,
    MUNKIDORI,
    RARE_CANDY,
    SNORUNT,
)
from ptcg_ai.grim_candidate_proposals import grim_semantic_candidates
from ptcg_ai.proof_search import semantic_action_key
from ptcg_ai.view import option_source_card


def card(card_id: int, serial: int = 1, player: int = 0):
    return NS(id=card_id, serial=serial, playerIndex=player)


def pokemon(
    card_id: int,
    serial: int = 1,
    *,
    hp: int = 100,
    max_hp: int = 100,
    player: int = 0,
):
    return NS(
        id=card_id,
        serial=serial,
        playerIndex=player,
        hp=hp,
        maxHp=max_hp,
        appearThisTurn=False,
        energies=[],
        energyCards=[],
        tools=[],
        preEvolution=[],
    )


def player(*, hand=(), active=(), bench=(), discard=(), hidden_deck=()):
    return NS(
        hand=list(hand),
        handCount=len(hand),
        active=list(active),
        bench=list(bench),
        discard=list(discard),
        prize=[None] * 6,
        deck=list(hidden_deck),
        deckCount=40,
        benchMax=5,
        poisoned=False,
        burned=False,
        asleep=False,
        paralyzed=False,
        confused=False,
    )


def selection(
    context,
    options,
    *,
    minimum: int = 1,
    maximum: int = 1,
    effect=None,
    context_card=None,
    deck=None,
):
    return NS(
        type=0,
        context=context,
        option=list(options),
        minCount=minimum,
        maxCount=maximum,
        remainDamageCounter=0,
        remainEnergyCost=0,
        effect=effect,
        contextCard=context_card,
        deck=deck,
    )


def observation(select, me, opponent=None):
    opponent = opponent or player()
    state = NS(
        players=[me, opponent],
        yourIndex=0,
        firstPlayer=0,
        turn=5,
        turnActionCount=2,
        supporterPlayed=False,
        stadiumPlayed=False,
        energyAttached=False,
        retreated=False,
        stadium=[],
        looking=None,
        result=-1,
    )
    return NS(select=select, current=state, logs=[])


def candidate_source_ids(obs, candidates):
    result = set()
    for candidate in candidates[1:]:
        if len(candidate.action) != 1:
            continue
        source = option_source_card(obs, obs.select.option[candidate.action[0]])
        if source is not None:
            result.add(int(source.id))
    return result


def test_semantic_dedup_happens_before_cap_and_keeps_baseline_first():
    me = player(
        hand=[
            card(SNORUNT, 11),
            card(MUNKIDORI, 12),
            card(MARNIES_IMPIDIMP, 13),
        ]
    )
    options = [Option(OptionType.END)]
    options.extend(Option(OptionType.PLAY, index=0) for _ in range(10))
    options.extend([Option(OptionType.PLAY, index=1), Option(OptionType.PLAY, index=2)])
    obs = observation(selection(SelectContext.MAIN, options), me)

    candidates = grim_semantic_candidates(obs, [0], max_candidates=4)

    assert candidates[0].is_baseline is True
    assert candidates[0].action == (0,)
    assert len(candidates) == 4
    assert len({candidate.key for candidate in candidates}) == 4
    assert candidate_source_ids(obs, candidates) == {
        SNORUNT,
        MUNKIDORI,
        MARNIES_IMPIDIMP,
    }


def test_semantic_order_is_stable_when_current_option_indices_are_permuted():
    me = player(
        hand=[card(SNORUNT, 11), card(MUNKIDORI, 12), card(MARNIES_IMPIDIMP, 13)]
    )
    original_options = [
        Option(OptionType.END),
        Option(OptionType.PLAY, index=0),
        Option(OptionType.PLAY, index=1),
        Option(OptionType.PLAY, index=2),
    ]
    permuted_options = [original_options[2], original_options[0], original_options[3], original_options[1]]
    original = observation(selection(SelectContext.MAIN, original_options), me)
    permuted = observation(selection(SelectContext.MAIN, permuted_options), me)

    first = grim_semantic_candidates(original, [0])
    second = grim_semantic_candidates(permuted, [1])

    assert [candidate.key for candidate in first] == [candidate.key for candidate in second]
    assert [candidate.action for candidate in first] != [candidate.action for candidate in second]
    assert all(
        candidate.key == semantic_action_key(original, candidate.action) for candidate in first
    )
    assert all(
        candidate.key == semantic_action_key(permuted, candidate.action) for candidate in second
    )


def test_targeted_to_hand_and_evolution_progress_roles_are_proposed():
    me = player(
        hand=[card(FROSLASS, 21)],
        active=[pokemon(SNORUNT, 31)],
        discard=[
            card(MARNIES_MORGREM, 41),
            card(RARE_CANDY, 42),
            card(999, 43),
        ],
    )
    to_hand = selection(
        SelectContext.TO_HAND,
        [
            Option(OptionType.CARD, area=AreaType.DISCARD, index=0, playerIndex=0),
            Option(OptionType.CARD, area=AreaType.DISCARD, index=1, playerIndex=0),
            Option(OptionType.CARD, area=AreaType.DISCARD, index=2, playerIndex=0),
        ],
    )
    obs = observation(to_hand, me)
    candidates = grim_semantic_candidates(obs, [2])
    assert candidate_source_ids(obs, candidates) == {MARNIES_MORGREM, RARE_CANDY}

    evolve = selection(
        SelectContext.MAIN,
        [
            Option(OptionType.END),
            Option(
                OptionType.EVOLVE,
                area=AreaType.HAND,
                index=0,
                playerIndex=0,
                inPlayArea=AreaType.ACTIVE,
                inPlayIndex=0,
            ),
        ],
    )
    obs = observation(evolve, me)
    candidates = grim_semantic_candidates(obs, [0])
    assert any(
        candidate.action == (1,) and "grim_evolution_progress" in candidate.reason
        for candidate in candidates
    )


def test_munkidori_source_to_bench_and_attach_count_choices_are_proposed():
    me = player(
        active=[pokemon(MARNIES_GRIMMSNARL_EX, 31, hp=250, max_hp=320)],
        bench=[pokemon(MUNKIDORI, 32, hp=60, max_hp=110)],
    )
    remove = selection(
        SelectContext.REMOVE_DAMAGE_COUNTER,
        [
            Option(OptionType.CARD, area=AreaType.ACTIVE, index=0, playerIndex=0),
            Option(OptionType.CARD, area=AreaType.BENCH, index=0, playerIndex=0),
        ],
        effect=card(MUNKIDORI, 90),
    )
    obs = observation(remove, me)
    candidates = grim_semantic_candidates(obs, [0])
    assert any(candidate.action == (1,) for candidate in candidates)

    deck = [card(SNORUNT, 51), card(MUNKIDORI, 52), card(999, 53)]
    bench = selection(
        SelectContext.TO_BENCH,
        [
            Option(OptionType.CARD, area=AreaType.DECK, index=0, playerIndex=0),
            Option(OptionType.CARD, area=AreaType.DECK, index=1, playerIndex=0),
            Option(OptionType.CARD, area=AreaType.DECK, index=2, playerIndex=0),
        ],
        deck=deck,
    )
    obs = observation(bench, me)
    candidates = grim_semantic_candidates(obs, [2])
    assert candidate_source_ids(obs, candidates) == {SNORUNT, MUNKIDORI}

    energies = [card(DARK_ENERGY, 60 + index) for index in range(5)]
    attach = selection(
        SelectContext.ATTACH_TO,
        [
            Option(OptionType.CARD, area=AreaType.DECK, index=index, playerIndex=0)
            for index in range(5)
        ],
        minimum=0,
        maximum=5,
        effect=card(MARNIES_GRIMMSNARL_EX, 99),
        deck=energies,
    )
    obs = observation(attach, me)
    candidates = grim_semantic_candidates(obs, [])
    assert sorted(len(candidate.action) for candidate in candidates) == [0, 1, 2, 3, 4, 5]


class FixedController:
    def __init__(self, preferred: int, reason: str = "test"):
        self.preferred = preferred
        self.reason = reason

    def apply(self, _obs, ranked, desired):
        return [self.preferred, *[index for index in ranked if index != self.preferred]], desired, self.reason


def test_optional_controller_proposal_is_unioned_but_declines_are_filtered():
    me = player(hand=[card(999, 1), card(998, 2)])
    select = selection(
        SelectContext.DISCARD,
        [
            Option(OptionType.CARD, area=AreaType.HAND, index=0, playerIndex=0),
            Option(OptionType.CARD, area=AreaType.HAND, index=1, playerIndex=0),
        ],
    )
    obs = observation(select, me)
    candidates = grim_semantic_candidates(
        obs,
        [0],
        floor_controller=FixedController(1, "safe"),
        ranked=[0, 1],
        desired=1,
    )
    assert any(
        candidate.action == (1,) and candidate.reason == "floor_controller:safe"
        for candidate in candidates
    )

    main = selection(
        SelectContext.MAIN,
        [Option(OptionType.PLAY, index=0), Option(OptionType.END)],
    )
    obs = observation(main, player(hand=[card(SNORUNT, 3)]))
    candidates = grim_semantic_candidates(
        obs,
        [0],
        floor_controller=FixedController(1, "end"),
        ranked=[0, 1],
        desired=1,
    )
    assert all(candidate.action != (1,) for candidate in candidates)

    baseline_end = grim_semantic_candidates(obs, [1])
    assert baseline_end[0].action == (1,)
    assert baseline_end[0].is_baseline is True


def test_hidden_fields_do_not_change_public_semantic_proposals():
    me = player(hand=[card(SNORUNT, 11), card(MUNKIDORI, 12)])
    select = selection(
        SelectContext.MAIN,
        [
            Option(OptionType.END),
            Option(OptionType.PLAY, index=0),
            Option(OptionType.PLAY, index=1),
        ],
    )
    first = observation(
        select,
        me,
        player(hand=[card(700, 71, 1)], hidden_deck=[card(701, 72, 1)]),
    )
    second = observation(
        select,
        me,
        player(hand=[card(800, 81, 1)], hidden_deck=[card(801, 82, 1)]),
    )
    first.rating = 400
    second.rating = 1200
    first.submission_id = 1
    second.submission_id = 999
    first.outcome = "loss"
    second.outcome = "win"

    assert [candidate.key for candidate in grim_semantic_candidates(first, [0])] == [
        candidate.key for candidate in grim_semantic_candidates(second, [0])
    ]


def test_malformed_inputs_fail_closed_without_leaking_optional_failures():
    assert grim_semantic_candidates(None, [0]) == ()
    assert grim_semantic_candidates(NS(select=None, current=NS()), []) == ()

    obs = observation(
        selection(SelectContext.MAIN, [Option(OptionType.END)]),
        player(),
    )
    assert grim_semantic_candidates(obs, [1]) == ()
    assert grim_semantic_candidates(obs, [0, 0]) == ()
    assert grim_semantic_candidates(obs, [0], max_candidates=0) == ()

    class BrokenController:
        def apply(self, *_args, **_kwargs):
            raise RuntimeError("untrusted optional proposer")

    candidates = grim_semantic_candidates(
        obs,
        [0],
        floor_controller=BrokenController(),
        ranked=[0],
        desired=1,
    )
    assert len(candidates) == 1
    assert candidates[0].is_baseline is True
