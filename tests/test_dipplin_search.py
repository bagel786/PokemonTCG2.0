from __future__ import annotations

import json
import random
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from cg.api import AreaType, OptionType, SelectContext, SelectType, to_observation_class

from ptcg_ai.dipplin.cards import APPLIN_DRAGON, FESTIVAL
from ptcg_ai.dipplin.search import (
    LOAD_BEARING_INDICES,
    METRIC_FIELDS,
    _COMPILED_PUBLIC_DECKS,
    _candidate_category,
    _strict_load_bearing,
    capture_semantic_selection,
    compatible_public_beliefs,
    determinize_public_world,
    resolve_semantic_selection,
)


FIXTURES = Path(__file__).resolve().parents[1] / "artifacts" / "dipplin_prompt_audit"


def _fixture(name: str):
    raw = json.loads((FIXTURES / f"{name}.json").read_text())["observation"]
    return raw, to_observation_class(raw)


def test_packaged_public_beliefs_are_diverse_complete_decks():
    assert len(_COMPILED_PUBLIC_DECKS) == 30
    assert len({deck_id for deck_id, _cards in _COMPILED_PUBLIC_DECKS}) == 30
    assert all(len(cards) == 60 for _deck_id, cards in _COMPILED_PUBLIC_DECKS)


def test_only_completed_tactical_gains_can_create_an_override():
    baseline = [0.0] * len(METRIC_FIELDS)
    festival_only = baseline.copy()
    festival_only[METRIC_FIELDS.index("festival_active")] = 1.0
    readiness_only = baseline.copy()
    readiness_only[METRIC_FIELDS.index("replacement_attacker_ready")] = 1.0
    prize = baseline.copy()
    prize[METRIC_FIELDS.index("prizes_taken_this_turn")] = 1.0

    assert LOAD_BEARING_INDICES == frozenset(range(5))
    assert not _strict_load_bearing(festival_only, baseline)
    assert not _strict_load_bearing(readiness_only, baseline)
    assert _strict_load_bearing(prize, baseline)


def test_basic_bench_play_is_a_general_damage_candidate():
    basic = SimpleNamespace(id=APPLIN_DRAGON)
    hero = SimpleNamespace(hand=[basic], active=[], bench=[])
    opponent = SimpleNamespace(hand=[], active=[], bench=[])
    option = SimpleNamespace(
        type=int(OptionType.PLAY),
        index=0,
        inPlayArea=int(AreaType.BENCH),
        inPlayIndex=0,
        attackId=-1,
    )
    attack = SimpleNamespace(type=int(OptionType.ATTACK), attackId=115)
    obs = SimpleNamespace(
        current=SimpleNamespace(yourIndex=0, players=[hero, opponent], looking=[], stadium=[]),
        select=SimpleNamespace(
            type=int(SelectType.MAIN),
            context=int(SelectContext.MAIN),
            option=[option, attack],
            deck=[],
        ),
    )

    category, score = _candidate_category(obs, option)

    assert category == "prize"
    assert score[0] > 0


def test_festival_setup_is_not_itself_a_tactical_proof():
    baseline = [0.0] * len(METRIC_FIELDS)
    festival = baseline.copy()
    festival[METRIC_FIELDS.index("festival_active")] = 1.0
    assert not _strict_load_bearing(festival, baseline)


def test_semantic_root_action_survives_option_reordering():
    raw, obs = _fixture("main_do_the_wave")
    original = next(
        index
        for index, option in enumerate(obs.select.option)
        if int(getattr(option, "attackId", None) or -1) == 115
    )
    semantic = capture_semantic_selection(obs, [original])
    reordered = deepcopy(raw)
    reordered["select"]["option"].reverse()
    reordered_obs = to_observation_class(reordered)

    remapped = resolve_semantic_selection(reordered_obs, semantic)

    assert remapped is not None
    assert int(reordered_obs.select.option[remapped[0]].attackId) == 115


def test_public_determinization_has_exact_hidden_zone_counts():
    _raw, obs = _fixture("main_do_the_wave")
    beliefs = compatible_public_beliefs(obs)
    assert len(beliefs) >= 2

    first = determinize_public_world(obs, beliefs[0][1], random.Random(17))
    second = determinize_public_world(obs, beliefs[0][1], random.Random(17))

    assert first == second
    hero = obs.current.players[obs.current.yourIndex]
    opponent = obs.current.players[1 - obs.current.yourIndex]
    assert len(first["your_deck"]) == int(hero.deckCount)
    assert len(first["opponent_deck"]) == int(opponent.deckCount)
    assert len(first["opponent_hand"]) == int(opponent.handCount)
    assert len(first["your_prize"]) == len(hero.prize)
    assert len(first["opponent_prize"]) == len(opponent.prize)
