from __future__ import annotations

import json
import random
import time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from cg.api import AreaType, OptionType, SelectContext, SelectType, to_observation_class

from ptcg_ai.dipplin.cards import (
    APPLIN_DRAGON,
    APPLIN_GRASS,
    DIPPLIN,
    FESTIVAL,
    GRASS_ENERGY,
    HILDA,
    LILLIE,
    NIGHT_STRETCHER,
    POFFIN,
    POKE_PAD,
    SACRED_ASH,
    THWACKEY,
)
from ptcg_ai.dipplin.search import (
    D1Config,
    LOAD_BEARING_INDICES,
    METRIC_FIELDS,
    RootCandidate,
    _COMPILED_PUBLIC_DECKS,
    _AttackTrace,
    _Budget,
    _WorldRunner,
    _candidate_category,
    _continuity_proof_admissible,
    _continuity_root_causal,
    _strict_load_bearing,
    capture_semantic_selection,
    compatible_public_beliefs,
    determinize_public_world,
    generate_root_candidates,
    resolve_semantic_selection,
)
from ptcg_ai.dipplin.snapshot import PlanMemory, SemanticAction


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


def test_root_budget_keeps_hilda_and_lillie_as_distinct_opening_lines():
    hilda = SimpleNamespace(id=HILDA, serial=10, playerIndex=0)
    lillie = SimpleNamespace(id=LILLIE, serial=11, playerIndex=0)
    hero = SimpleNamespace(hand=[hilda, lillie], active=[], bench=[])
    opponent = SimpleNamespace(hand=[], active=[], bench=[])
    options = [
        SimpleNamespace(type=int(OptionType.ATTACK), attackId=115),
        SimpleNamespace(type=int(OptionType.PLAY), index=0),
        SimpleNamespace(type=int(OptionType.PLAY), index=1),
    ]
    obs = SimpleNamespace(
        current=SimpleNamespace(yourIndex=0, players=[hero, opponent], looking=[], stadium=[]),
        select=SimpleNamespace(
            type=int(SelectType.MAIN),
            context=int(SelectContext.MAIN),
            minCount=1,
            maxCount=1,
            option=options,
            deck=[],
            contextCard=None,
            effect=None,
        ),
    )

    candidates = generate_root_candidates(obs, [0], 4)
    selected = {
        options[candidate.original_action[0]].index
        for candidate in candidates[1:]
        if int(options[candidate.original_action[0]].type) == int(OptionType.PLAY)
    }

    assert selected == {0, 1}


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


def test_world_runner_plans_multiple_deterministic_actions_before_turn_end(monkeypatch):
    card = SimpleNamespace(id=FESTIVAL, serial=7, playerIndex=0)
    hero = SimpleNamespace(hand=[card], active=[], bench=[], discard=[], prize=[])
    opponent = SimpleNamespace(hand=[], active=[], bench=[], discard=[], prize=[])

    def select(options):
        return SimpleNamespace(
            type=int(SelectType.MAIN),
            context=int(SelectContext.MAIN),
            minCount=1,
            maxCount=1,
            option=options,
            deck=[],
            contextCard=None,
            effect=None,
        )

    root_option = SimpleNamespace(type=int(OptionType.PLAY), index=0)
    attack = SimpleNamespace(type=int(OptionType.ATTACK), attackId=115)
    end = SimpleNamespace(type=int(OptionType.END))

    def observation(turn, prompt, score=0):
        return SimpleNamespace(
            current=SimpleNamespace(
                turn=turn,
                yourIndex=0,
                result=-1,
                players=[hero, opponent],
                looking=[],
                stadium=[],
                score=score,
            ),
            select=prompt,
            logs=[],
        )

    root_obs = observation(5, select([root_option]))
    planning_obs = observation(5, select([attack, end]))
    good_leaf = observation(6, None, score=1)
    bad_leaf = observation(6, None, score=0)

    class Backend:
        def __init__(self):
            self.actions = []

        def begin(self, _obs, _determinization):
            return SimpleNamespace(searchId=1, observation=root_obs)

        def step(self, search_id, action):
            self.actions.append((search_id, tuple(action)))
            if search_id == 1:
                return SimpleNamespace(searchId=2, observation=planning_obs)
            if search_id == 2 and action == [0]:
                return SimpleNamespace(searchId=3, observation=good_leaf)
            if search_id == 2 and action == [1]:
                return SimpleNamespace(searchId=4, observation=bad_leaf)
            raise AssertionError((search_id, action))

        def release(self, _search_id):
            return None

        def end(self):
            return None

    class Planner:
        def propose(self, _obs, _snapshot, _memory):
            intent = SimpleNamespace(
                ranked_indices=(1,),
                desired_count=1,
                resolver="fake_d0",
                reason="end baseline",
            )
            return SimpleNamespace(intent=intent)

    monkeypatch.setattr(
        "ptcg_ai.dipplin.policy.semantic_final_action",
        lambda *_args, **_kwargs: SemanticAction(kind="TEST"),
    )
    monkeypatch.setattr(
        "ptcg_ai.dipplin.search.PlanSnapshot.from_observation",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "ptcg_ai.dipplin.search._advance_trace",
        lambda trace, *_args, **_kwargs: trace,
    )
    monkeypatch.setattr(
        "ptcg_ai.dipplin.search.completed_turn_metric",
        lambda _root, leaf, *_args: (float(leaf.current.score),) + (0.0,) * (len(METRIC_FIELDS) - 1),
    )

    now = time.monotonic()
    backend = Backend()
    runner = _WorldRunner(
        Planner(),
        backend,
        _Budget(now, now + 5, now + 5, 32, 32, time.monotonic),
        D1Config(max_candidates=3, max_plan_candidates=3),
    )
    root = RootCandidate(
        (0,),
        capture_semantic_selection(root_obs, [0]),
        "baseline",
        True,
    )

    outcomes = runner.run(root_obs, [root], {}, PlanMemory())

    assert outcomes[root.key][0] == 1.0
    assert (2, (0,)) in backend.actions
    assert (2, (1,)) in backend.actions
    assert runner.plan_branch_points == 1
    assert runner.plan_alternatives == 1


def _card(card_id: int, *, serial: int = 0):
    return SimpleNamespace(id=card_id, serial=serial)


def _continuity_obs(option: object) -> SimpleNamespace:
    hero = SimpleNamespace(
        hand=[_card(GRASS_ENERGY), _card(DIPPLIN), _card(POFFIN), _card(FESTIVAL), _card(LILLIE)],
        active=[_card(DIPPLIN, serial=7)],
        bench=[_card(APPLIN_GRASS, serial=8)],
    )
    opponent = SimpleNamespace(hand=[], active=[_card(DIPPLIN, serial=99)], bench=[])
    return SimpleNamespace(
        current=SimpleNamespace(
            yourIndex=0,
            players=[hero, opponent],
            looking=[],
            stadium=[],
        ),
        select=SimpleNamespace(
            type=int(SelectType.MAIN),
            context=int(SelectContext.MAIN),
            minCount=1,
            maxCount=1,
            option=[option],
            deck=[],
            contextCard=None,
            effect=None,
        ),
    )


def _hand_option(option_type: int, *, in_play_area: int, in_play_index: int = 0, index: int = 0):
    return SimpleNamespace(
        type=option_type,
        index=index,
        area=int(AreaType.HAND),
        playerIndex=0,
        inPlayArea=in_play_area,
        inPlayIndex=in_play_index,
        attackId=-1,
    )


def test_continuity_root_causal_energy_to_bench_replacement():
    option = _hand_option(int(OptionType.ATTACH), in_play_area=int(AreaType.BENCH))
    candidate = RootCandidate((0,), object(), "replacement")
    assert _continuity_root_causal(_continuity_obs(option), candidate)


def test_continuity_root_causal_rejects_current_attacker_energy():
    option = _hand_option(int(OptionType.ATTACH), in_play_area=int(AreaType.ACTIVE))
    candidate = RootCandidate((0,), object(), "replacement")
    assert not _continuity_root_causal(_continuity_obs(option), candidate)


def test_continuity_root_causal_bench_evolution():
    option = _hand_option(int(OptionType.EVOLVE), in_play_area=int(AreaType.BENCH), index=1)
    candidate = RootCandidate((0,), object(), "replacement")
    assert _continuity_root_causal(_continuity_obs(option), candidate)


def test_continuity_root_causal_rejects_stadium_and_generic_draw():
    festival = _hand_option(int(OptionType.PLAY), in_play_area=int(AreaType.STADIUM), index=3)
    lillie = _hand_option(int(OptionType.PLAY), in_play_area=int(AreaType.BENCH), index=4)
    assert not _continuity_root_causal(_continuity_obs(festival), RootCandidate((0,), object(), "enable"))
    assert not _continuity_root_causal(_continuity_obs(lillie), RootCandidate((0,), object(), "replacement"))


def test_continuity_root_causal_search_and_recover_cards():
    # _continuity_obs builds hand = [GRASS_ENERGY, DIPPLIN, POFFIN, FESTIVAL, LILLIE].
    for index, expected in ((2, True), (3, False), (4, False)):
        option = _hand_option(int(OptionType.PLAY), in_play_area=int(AreaType.BENCH), index=index)
        obs = _continuity_obs(option)
        assert _continuity_root_causal(obs, RootCandidate((0,), object(), "replacement")) is expected


def test_continuity_proof_admits_ready_replacement_when_tactical_equal():
    option = _hand_option(int(OptionType.ATTACH), in_play_area=int(AreaType.BENCH))
    obs = _continuity_obs(option)
    candidate = RootCandidate((0,), object(), "replacement")
    baseline_worlds = []
    candidate_worlds = []
    for _world in range(2):
        baseline = [0.0] * len(METRIC_FIELDS)
        cand_vec = [0.0] * len(METRIC_FIELDS)
        cand_vec[METRIC_FIELDS.index("replacement_attacker_ready")] = 1.0
        cand_vec[METRIC_FIELDS.index("current_attacker_ready")] = 1.0
        cand_vec[METRIC_FIELDS.index("festival_active")] = 1.0
        cand_vec[METRIC_FIELDS.index("remaining_core_attacker_resources")] = 3.0
        baseline_worlds.append(baseline)
        candidate_worlds.append(cand_vec)
    assert _continuity_proof_admissible(candidate, obs, candidate_worlds, baseline_worlds)


def test_continuity_proof_rejects_when_baseline_already_ready():
    option = _hand_option(int(OptionType.ATTACH), in_play_area=int(AreaType.BENCH))
    obs = _continuity_obs(option)
    candidate = RootCandidate((0,), object(), "replacement")
    baseline = [0.0] * len(METRIC_FIELDS)
    baseline[METRIC_FIELDS.index("replacement_attacker_ready")] = 1.0
    candidate_vec = baseline.copy()
    candidate_vec[METRIC_FIELDS.index("remaining_core_attacker_resources")] = 3.0
    assert not _continuity_proof_admissible(candidate, obs, [candidate_vec], [baseline])


def test_continuity_proof_rejects_tactical_prize_gain():
    option = _hand_option(int(OptionType.ATTACH), in_play_area=int(AreaType.BENCH))
    obs = _continuity_obs(option)
    candidate = RootCandidate((0,), object(), "replacement")
    baseline = [0.0] * len(METRIC_FIELDS)
    candidate_vec = [0.0] * len(METRIC_FIELDS)
    candidate_vec[METRIC_FIELDS.index("prizes_taken_this_turn")] = 1.0
    candidate_vec[METRIC_FIELDS.index("replacement_attacker_ready")] = 1.0
    assert not _continuity_proof_admissible(candidate, obs, [candidate_vec], [baseline])


def test_continuity_proof_rejects_world_disagreement():
    option = _hand_option(int(OptionType.ATTACH), in_play_area=int(AreaType.BENCH))
    obs = _continuity_obs(option)
    candidate = RootCandidate((0,), object(), "replacement")
    baseline_worlds = [[0.0] * len(METRIC_FIELDS), [0.0] * len(METRIC_FIELDS)]
    candidate_worlds = []
    for world in range(2):
        vec = [0.0] * len(METRIC_FIELDS)
        if world == 0:
            vec[METRIC_FIELDS.index("replacement_attacker_ready")] = 1.0
        candidate_worlds.append(vec)
    assert not _continuity_proof_admissible(candidate, obs, candidate_worlds, baseline_worlds)


def test_continuity_proof_rejects_fragile_bench_regression():
    option = _hand_option(int(OptionType.ATTACH), in_play_area=int(AreaType.BENCH))
    obs = _continuity_obs(option)
    candidate = RootCandidate((0,), object(), "replacement")
    baseline = [0.0] * len(METRIC_FIELDS)
    candidate_vec = [0.0] * len(METRIC_FIELDS)
    candidate_vec[METRIC_FIELDS.index("replacement_attacker_ready")] = 1.0
    candidate_vec[METRIC_FIELDS.index("avoid_exposed_fragile_bench")] = -1.0
    assert not _continuity_proof_admissible(candidate, obs, [candidate_vec], [baseline])
