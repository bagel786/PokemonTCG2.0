from __future__ import annotations

import copy
import random
from types import SimpleNamespace

import pytest

import training.complete_turn_corrections as corrections
from cg.api import AreaType, OptionType, SelectContext, SelectType
from training.complete_turn_corrections import (
    CorrectionConfig,
    PublicMetricVector,
    assess_admission,
    compare_public_metrics,
    crn_seed,
    evaluate_complete_turn_correction,
    public_boundary_hash,
    public_metric_vector,
    resolve_semantic_action,
    semantic_action,
)


def card(card_id: int, serial: int, player: int = 0):
    return SimpleNamespace(id=card_id, serial=serial, playerIndex=player)


def pokemon(card_id: int, serial: int, player: int = 0, *, hp: int = 100, energy: int = 0):
    return SimpleNamespace(
        id=card_id,
        serial=serial,
        playerIndex=player,
        hp=hp,
        maxHp=100,
        appearThisTurn=False,
        energies=[7] * energy,
        energyCards=[card(7, serial * 100 + index, player) for index in range(energy)],
        tools=[],
        preEvolution=[],
    )


def player(index: int, *, hand=None, prizes: int = 6):
    return SimpleNamespace(
        active=[pokemon(646 if index == 0 else 999, 10 + index, index)],
        bench=[],
        benchMax=5,
        deckCount=50,
        discard=[],
        prize=[None] * prizes,
        handCount=len(hand or []),
        hand=hand if index == 0 else None,
        poisoned=False,
        burned=False,
        asleep=False,
        paralyzed=False,
        confused=False,
    )


def observation(options, *, hand=None, turn=1, your_index=0):
    state = SimpleNamespace(
        turn=turn,
        turnActionCount=0,
        yourIndex=your_index,
        firstPlayer=0,
        supporterPlayed=False,
        stadiumPlayed=False,
        energyAttached=False,
        retreated=False,
        result=-1,
        stadium=[],
        looking=None,
        players=[player(0, hand=hand), player(1)],
    )
    select = SimpleNamespace(
        type=SelectType.MAIN,
        context=SelectContext.MAIN,
        minCount=1,
        maxCount=1,
        remainDamageCounter=0,
        remainEnergyCost=0,
        option=options,
        deck=None,
        contextCard=None,
        effect=None,
    )
    return SimpleNamespace(current=state, select=select, logs=[], search_begin_input="opaque")


def option(option_type, **kwargs):
    defaults = dict(
        number=None,
        area=None,
        index=None,
        playerIndex=None,
        toolIndex=None,
        energyIndex=None,
        count=None,
        inPlayArea=None,
        inPlayIndex=None,
        attackId=None,
        cardId=None,
        serial=None,
        specialConditionType=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(type=option_type, **defaults)


def vector(*values):
    return PublicMetricVector(*map(float, values))


def test_semantic_action_survives_hand_and_option_reordering():
    a, b = card(100, 1000), card(200, 2000)
    first = observation(
        [option(OptionType.PLAY, index=0), option(OptionType.PLAY, index=1)],
        hand=[a, b],
    )
    captured = semantic_action(first, [1])

    reordered = observation(
        [option(OptionType.PLAY, index=0), option(OptionType.PLAY, index=1)],
        hand=[b, a],
    )
    assert semantic_action(reordered, [0]) == captured
    assert resolve_semantic_action(reordered, captured) == [0]
    assert public_boundary_hash(first) == public_boundary_hash(reordered)
    assert "index" not in captured.options[0].payload
    assert captured.options[0].payload["source"] == {"id": 200, "serial": 2000, "player_index": 0}


def test_unresolvable_positional_option_fails_closed():
    obs = observation([option(OptionType.PLAY, index=9)], hand=[card(100, 1)])
    with pytest.raises(corrections.SemanticBoundaryError):
        semantic_action(obs, [0])
    with pytest.raises(corrections.SemanticBoundaryError):
        public_boundary_hash(obs)


def test_crn_seeds_are_reproducible_and_world_specific():
    boundary = "AB" * 32
    first = [crn_seed(19, boundary, index) for index in range(8)]
    second = [crn_seed(19, boundary.lower(), index) for index in range(8)]
    assert first == second
    assert len(set(first)) == 8
    assert first != [crn_seed(20, boundary, index) for index in range(8)]


def test_admission_requires_all_worlds_noninferior_and_half_strictly_better():
    base = {index: vector(0, 0, 0, 0, 0, 0, 0) for index in range(8)}
    candidate = {
        index: vector(0, 1 if index < 4 else 0, 0, 0, 0, 0, 0)
        for index in range(8)
    }
    decision = assess_admission(base, candidate, 8)
    assert decision.admitted
    assert decision.noninferior_worlds == 8
    assert decision.strict_better_worlds == 4


def test_one_regressing_world_rejects_even_when_seven_are_better():
    base = {index: vector(0, 0, 0, 0, 0, 0, 0) for index in range(8)}
    candidate = {index: vector(0, 1, 0, 0, 0, 0, 0) for index in range(8)}
    candidate[6] = vector(0, -1, 99, 99, 99, 99, 99)
    decision = assess_admission(base, candidate, 8)
    assert not decision.admitted
    assert decision.reason == "regression_in_world:6"


def test_admission_rejects_insufficient_strict_worlds_and_unequal_coverage():
    base = {index: vector(0, 0, 0, 0, 0, 0, 0) for index in range(8)}
    only_three = {
        index: vector(0, int(index < 3), 0, 0, 0, 0, 0)
        for index in range(8)
    }
    assert assess_admission(base, only_three, 8).reason == "strict_improvement_below_half"
    partial = dict(only_three)
    partial.pop(7)
    unequal = assess_admission(base, partial, 8)
    assert not unequal.admitted
    assert unequal.reason == "incomplete_or_unequal_coverage"
    assert unequal.covered_worlds == 7


def test_metric_comparison_is_named_public_lexicographic_not_scalarized():
    # A terminal win is better even when every lower-priority component is worse.
    win = vector(1, -100, -100, -100, -100, -100, -100)
    ongoing = vector(0, 100, 100, 100, 100, 100, 100)
    assert compare_public_metrics(win, ongoing) == 1
    with pytest.raises(ValueError):
        compare_public_metrics(vector(float("nan"), 0, 0, 0, 0, 0, 0), ongoing)


def test_public_metric_does_not_change_with_hidden_hand_identity():
    initial = observation([], hand=[]).current
    first = copy.deepcopy(initial)
    second = copy.deepcopy(initial)
    first.players[1].hand = [card(111, 9001, 1)]
    second.players[1].hand = [card(222, 9002, 1)]
    first.players[1].handCount = second.players[1].handCount = 1
    assert public_metric_vector(initial, first, 0) == public_metric_vector(initial, second, 0)


class FakeEngine:
    def __init__(
        self,
        root_observation,
        *,
        candidate_incomplete=False,
        candidate_error=None,
        release_error=False,
    ):
        self.root_observation = root_observation
        self.candidate_incomplete = candidate_incomplete
        self.candidate_error = candidate_error
        self.release_error = release_error
        self.next_id = 100
        self.roots = set()
        self.released = []
        self.end_calls = 0
        self.manual_coin = []

    def begin(self, obs, **kwargs):
        self.next_id += 1
        search_id = self.next_id
        self.roots.add(search_id)
        self.manual_coin.append(kwargs.get("manual_coin"))
        return SimpleNamespace(searchId=search_id, observation=obs)

    def step(self, search_id, action):
        if search_id in self.roots:
            if action == [1] and self.candidate_error is not None:
                raise self.candidate_error
            state = copy.deepcopy(self.root_observation.current)
            if action == [1] and not self.candidate_incomplete:
                state.players[0].prize.pop()
            if not self.candidate_incomplete or action == [0]:
                state.turn = 2
                state.yourIndex = 1
                next_select = None
            else:
                next_select = self.root_observation.select
            self.next_id += 1
            return SimpleNamespace(
                searchId=self.next_id,
                observation=SimpleNamespace(current=state, select=next_select, logs=[]),
            )
        # An incomplete candidate remains on the same turn forever.
        self.next_id += 1
        return SimpleNamespace(
            searchId=self.next_id,
            observation=SimpleNamespace(
                current=copy.deepcopy(self.root_observation.current),
                select=self.root_observation.select,
                logs=[],
            ),
        )

    def release(self, search_id):
        self.released.append(search_id)
        if self.release_error:
            raise RuntimeError("release boom")

    def end(self):
        self.end_calls += 1


def _run_fake(monkeypatch, engine, *, worlds=8, max_turn_steps=4, timeout=30.0):
    monkeypatch.setattr(corrections, "search_begin", engine.begin)
    monkeypatch.setattr(corrections, "search_step", engine.step)
    monkeypatch.setattr(corrections, "search_release", engine.release)
    monkeypatch.setattr(corrections, "search_end", engine.end)
    rng_samples = []

    def determinizer(obs, hero, opponent, rng):
        rng_samples.append(rng.getrandbits(64))
        return {}

    result = evaluate_complete_turn_correction(
        engine.root_observation,
        [0],
        [1],
        [1] * 60,
        [2] * 60,
        lambda: (lambda obs: [0]),
        config=CorrectionConfig(
            worlds=worlds,
            max_turn_steps=max_turn_steps,
            timeout_seconds=timeout,
            seed=77,
        ),
        determinizer=determinizer,
    )
    return result, rng_samples


def attack_observation():
    return observation(
        [
            option(OptionType.ATTACK, attackId=11),
            option(OptionType.ATTACK, attackId=22),
        ],
        hand=[],
    )


def test_oracle_uses_one_crn_root_per_world_and_complete_equal_coverage(monkeypatch):
    obs = attack_observation()
    engine = FakeEngine(obs)
    result, rng_samples = _run_fake(monkeypatch, engine)
    assert result.admitted
    assert result.coverage == {"baseline": 8, "candidate": 8}
    assert len(result.worlds) == 8
    assert all(world.baseline_steps == world.candidate_steps == 1 for world in result.worlds)
    assert engine.end_calls == 8
    assert engine.manual_coin == [True] * 8
    expected_samples = [
        random.Random(crn_seed(77, result.boundary_hash, index)).getrandbits(64)
        for index in range(8)
    ]
    assert rng_samples == expected_samples
    assert all(
        world.candidate.prizes == world.baseline.prizes + 1
        for world in result.worlds
    )


def test_engine_error_rejects_without_neutral_or_partial_world_score(monkeypatch):
    obs = attack_observation()
    engine = FakeEngine(obs, candidate_error=RuntimeError("native boom"))
    result, _ = _run_fake(monkeypatch, engine)
    assert not result.admitted
    assert result.reason == "engine_error"
    assert result.coverage == {"baseline": 0, "candidate": 0}
    assert result.worlds == ()
    assert "native boom" in result.errors[0]
    assert engine.end_calls == 1
    assert engine.released  # baseline branch and root are both cleaned up


def test_timeout_rejects_without_neutral_score(monkeypatch):
    obs = attack_observation()
    engine = FakeEngine(obs, candidate_error=TimeoutError("world deadline"))
    result, _ = _run_fake(monkeypatch, engine)
    assert not result.admitted
    assert result.reason == "timeout"
    assert result.coverage == {"baseline": 0, "candidate": 0}


def test_turn_truncation_is_incomplete_and_rejected(monkeypatch):
    obs = attack_observation()
    engine = FakeEngine(obs, candidate_incomplete=True)
    result, _ = _run_fake(monkeypatch, engine, max_turn_steps=2)
    assert not result.admitted
    assert result.reason == "incomplete_turn"
    assert result.coverage == {"baseline": 0, "candidate": 0}
    assert "did not complete" in result.errors[0]


def test_native_cleanup_error_rejects_certification(monkeypatch):
    obs = attack_observation()
    engine = FakeEngine(obs, release_error=True)
    result, _ = _run_fake(monkeypatch, engine)
    assert not result.admitted
    assert result.reason == "engine_cleanup_error"
    assert result.coverage == {"baseline": 0, "candidate": 0}
    assert engine.end_calls == 1


def test_identical_semantic_actions_never_start_search(monkeypatch):
    obs = attack_observation()
    engine = FakeEngine(obs)
    monkeypatch.setattr(corrections, "search_begin", lambda *args, **kwargs: pytest.fail("search called"))
    result = evaluate_complete_turn_correction(
        obs,
        [0],
        [0],
        [1] * 60,
        [2] * 60,
        lambda: (lambda current: [0]),
    )
    assert not result.admitted
    assert result.reason == "same_semantic_action"
