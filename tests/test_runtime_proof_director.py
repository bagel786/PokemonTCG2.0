from __future__ import annotations

import copy
from types import SimpleNamespace as NS

import pytest

import ptcg_ai.runtime_proof_director as runtime
from cg.api import AreaType, LogType, Option, OptionType, SelectContext, SelectType
from ptcg_ai.proof_search import SemanticCandidate, semantic_action_key
from ptcg_ai.runtime_proof_director import (
    BranchEvidence,
    RuntimeProofConfig,
    RuntimeProofDirector,
    runtime_world_seeds,
)


HERO_DECK = [646, *([7] * 59)]


def card(card_id: int, serial: int, player: int = 0):
    return NS(id=card_id, serial=serial, playerIndex=player)


def pokemon(card_id: int, serial: int, player: int = 0):
    return NS(
        id=card_id,
        serial=serial,
        playerIndex=player,
        hp=70,
        maxHp=70,
        appearThisTurn=False,
        energies=[],
        energyCards=[],
        tools=[],
        preEvolution=[],
    )


def player(index: int):
    if index == 0:
        active = [pokemon(646, 1, 0)]
        hand = []
        deck_count = 53
    else:
        active = [pokemon(860, 101, 1)]
        hand = None
        deck_count = 40
    return NS(
        active=active,
        bench=[],
        benchMax=5,
        deckCount=deck_count,
        discard=[],
        prize=[None] * 6,
        handCount=0,
        hand=hand,
        poisoned=False,
        burned=False,
        asleep=False,
        paralyzed=False,
        confused=False,
    )


def selection(options):
    return NS(
        type=SelectType.MAIN,
        context=SelectContext.MAIN,
        minCount=1,
        maxCount=1,
        remainDamageCounter=0,
        remainEnergyCost=0,
        option=list(options),
        deck=None,
        contextCard=None,
        effect=None,
    )


def observation(options=None):
    options = options or [
        Option(OptionType.ATTACK, attackId=935),
        Option(OptionType.END),
    ]
    current = NS(
        turn=5,
        turnActionCount=0,
        yourIndex=0,
        firstPlayer=0,
        supporterPlayed=False,
        stadiumPlayed=False,
        energyAttached=False,
        retreated=False,
        result=-1,
        stadium=[],
        looking=None,
        players=[player(0), player(1)],
    )
    return NS(
        current=current,
        select=selection(options),
        logs=[],
        search_begin_input="opaque-native-root",
    )


class FakeBackend:
    def __init__(
        self,
        *,
        winners=(),
        winner_predicate=None,
        tainted=(),
        next_turn=(),
        inconsistent=(),
        fail_begin=False,
        fail_step=False,
        fail_release=False,
        fail_end=False,
    ):
        self.winners = {tuple(value) for value in winners}
        self.winner_predicate = winner_predicate
        self.tainted = {tuple(value) for value in tainted}
        self.next_turn = {tuple(value) for value in next_turn}
        self.inconsistent = {tuple(value) for value in inconsistent}
        self.fail_begin = fail_begin
        self.fail_step = fail_step
        self.fail_release = fail_release
        self.fail_end = fail_end
        self.failed_release = False
        self.next_id = 1
        self.roots = {}
        self.root_actions = {}
        self.created = []
        self.release_attempts = []
        self.ended = 0
        self.determinizations = []

    def _state(self, obs):
        state = NS(searchId=self.next_id, observation=obs)
        self.next_id += 1
        self.created.append(state.searchId)
        return state

    def begin(self, obs, determinization):
        if self.fail_begin:
            raise RuntimeError("begin failed")
        root = self._state(obs)
        self.roots[root.searchId] = obs
        self.root_actions[root.searchId] = []
        self.determinizations.append(copy.deepcopy(dict(determinization)))
        return root

    def step(self, search_id, action):
        if self.fail_step:
            raise RuntimeError("step failed")
        action = tuple(map(int, action))
        root = self.roots[int(search_id)]
        position = len(self.root_actions[int(search_id)])
        self.root_actions[int(search_id)].append(action)
        child = copy.deepcopy(root)
        winner = action in self.winners
        if self.winner_predicate is not None:
            winner = bool(self.winner_predicate(root, action))
        if winner:
            child.current.result = int(root.current.yourIndex)
        if action in self.next_turn:
            child.current.turn += 1
        if action in self.inconsistent:
            child.current.turnActionCount = position
        if action in self.tainted:
            child.logs = [NS(type=LogType.COIN, head=True, playerIndex=0)]
        return self._state(child)

    def release(self, search_id):
        self.release_attempts.append(int(search_id))
        if self.fail_release and not self.failed_release:
            self.failed_release = True
            raise RuntimeError("release failed")

    def end(self):
        self.ended += 1
        if self.fail_end:
            raise RuntimeError("end failed")


def director(backend, **config):
    values = dict(timeout_seconds=1.0)
    values.update(config)
    return RuntimeProofDirector(HERO_DECK, config=RuntimeProofConfig(**values), backend=backend)


def test_unique_immediate_win_overrides_and_cleans_every_native_state_once():
    backend = FakeBackend(winners=[(0,)])
    proof = director(backend)
    assert proof.choose(observation(), [1]) == [0]
    assert len(backend.root_actions) == 4  # two worlds, forward and reverse
    assert list(backend.root_actions.values()) == [
        [(1,), (0,)],
        [(0,), (1,)],
        [(1,), (0,)],
        [(0,), (1,)],
    ]
    assert len(backend.created) == 12
    assert sorted(backend.created) == sorted(backend.release_attempts)
    assert len(backend.release_attempts) == len(set(backend.release_attempts))
    assert backend.ended == 4
    assert proof.telemetry["overrides"] == 1
    assert proof.telemetry["last"]["coverage"] == 8


@pytest.mark.parametrize(
    ("backend", "reason"),
    [
        (FakeBackend(fail_begin=True), "runtime_error"),
        (FakeBackend(fail_step=True), "runtime_error"),
        (FakeBackend(winners=[(0,)], fail_release=True), "cleanup_error"),
        (FakeBackend(winners=[(0,)], fail_end=True), "cleanup_error"),
    ],
)
def test_every_native_error_returns_the_exact_baseline_and_runs_cleanup(backend, reason):
    baseline = [1]
    proof = director(backend)
    result = proof.choose(observation(), baseline)
    assert result == baseline
    assert proof.telemetry["last"]["reason"] == reason
    assert backend.ended >= 1
    if not backend.fail_begin:
        assert set(backend.created) == set(backend.release_attempts)


def test_timeout_and_preflight_budget_exhaustion_are_fail_closed():
    timeout_backend = FakeBackend(winners=[(0,)])
    timeout = director(timeout_backend, timeout_seconds=1e-12)
    assert timeout.choose(observation(), [1]) == [1]
    assert timeout.telemetry["last"]["reason"] == "timeout"
    assert timeout_backend.ended == 0  # deadline expired before search_begin

    budget_backend = FakeBackend(winners=[(0,)])
    budget = director(budget_backend, max_native_steps_per_game=7)
    assert budget.choose(observation(), [1]) == [1]
    assert budget.telemetry["last"]["reason"] == "budget_exhausted"
    assert budget_backend.created == []
    assert budget.telemetry["budget"]["native_steps_used"] == 0


def test_nonterminal_next_turn_tainted_and_ambiguous_results_never_override():
    cases = [
        (FakeBackend(), "no_same_turn_terminal_win"),
        (FakeBackend(winners=[(0,)], next_turn=[(0,)]), "no_same_turn_terminal_win"),
        (FakeBackend(winners=[(0,)], tainted=[(0,)]), "terminal_winner_tainted"),
    ]
    for backend, reason in cases:
        proof = director(backend)
        assert proof.choose(observation(), [1]) == [1]
        assert proof.telemetry["last"]["reason"] == reason

    ambiguous_obs = observation(
        [
            Option(OptionType.ATTACK, attackId=935),
            Option(OptionType.ATTACK, attackId=1239),
            Option(OptionType.END),
        ]
    )
    ambiguous = director(FakeBackend(winners=[(0,), (1,)]))
    assert ambiguous.choose(ambiguous_obs, [2]) == [2]
    assert ambiguous.telemetry["last"]["reason"] == "ambiguous_terminal_winner"


def test_baseline_terminal_win_and_forward_reverse_disagreement_preserve_baseline():
    already_wins = director(FakeBackend(winners=[(0,), (1,)]))
    assert already_wins.choose(observation(), [1]) == [1]
    assert already_wins.telemetry["last"]["reason"] == "baseline_already_terminal_win"

    inconsistent = director(FakeBackend(winners=[(0,)], inconsistent=[(0,)]))
    assert inconsistent.choose(observation(), [1]) == [1]
    assert inconsistent.telemetry["last"]["reason"] == "order_inconsistent"


def test_normal_last_prize_motion_is_allowed_but_deck_motion_is_tainted():
    class PrizeBackend(FakeBackend):
        def __init__(self, hidden_area):
            super().__init__(winners=[(0,)])
            self.hidden_area = hidden_area

        def step(self, search_id, action):
            state = super().step(search_id, action)
            if tuple(action) == (0,):
                if self.hidden_area == AreaType.PRIZE:
                    state.observation.current.players[0].prize = []
                state.observation.logs = [
                    NS(
                        type=LogType.MOVE_CARD,
                        playerIndex=0,
                        fromArea=self.hidden_area,
                        toArea=AreaType.HAND,
                    )
                ]
            return state

    prize = director(PrizeBackend(AreaType.PRIZE))
    assert prize.choose(observation(), [1]) == [0]

    deck = director(PrizeBackend(AreaType.DECK))
    assert deck.choose(observation(), [1]) == [1]
    assert deck.telemetry["last"]["reason"] == "terminal_winner_tainted"


def test_engine_filled_child_prize_ids_do_not_taint_unchanged_counts():
    root = observation()
    child = copy.deepcopy(root)
    child.current.result = 0
    child.current.players[0].prize = [card(7, 700 + index, 0) for index in range(6)]
    child.current.players[1].prize = [card(3, 800 + index, 1) for index in range(6)]
    evidence = runtime._branch_evidence(root, child, 0)
    assert evidence.same_turn
    assert not evidence.tainted


def test_nonterminal_prize_count_or_movement_remains_tainted():
    root = observation()
    changed = copy.deepcopy(root)
    changed.current.players[0].prize = [card(7, 700 + index, 0) for index in range(5)]
    assert runtime._branch_evidence(root, changed, 0).tainted

    moved = copy.deepcopy(root)
    moved.current.players[0].prize = [card(7, 700 + index, 0) for index in range(6)]
    moved.current.players[1].prize = [card(3, 800 + index, 1) for index in range(6)]
    moved.logs = [
        NS(
            type=LogType.MOVE_CARD,
            playerIndex=0,
            fromArea=AreaType.PRIZE,
            toArea=AreaType.HAND,
        )
    ]
    assert runtime._branch_evidence(root, moved, 0).tainted


def test_public_seeds_and_opponent_sentinels_ignore_illicit_hidden_metadata():
    first = observation()
    second = copy.deepcopy(first)
    first.rating = 400
    second.rating = 1900
    first.submission_id = "A"
    second.submission_id = "B"
    first.current.players[1].hand = [card(999, 500, 1)]
    second.current.players[1].hand = [card(1234, 501, 1)]
    config = RuntimeProofConfig(timeout_seconds=1)
    assert runtime_world_seeds(first, config) == runtime_world_seeds(second, config)

    seed = runtime_world_seeds(first, config)[0]
    first_world = runtime._public_determinization(
        first, HERO_DECK, seed=seed, world_index=0
    )
    second_world = runtime._public_determinization(
        second, HERO_DECK, seed=seed, world_index=0
    )
    assert first_world == second_world
    alternate_world = runtime._public_determinization(
        first, HERO_DECK, seed=seed, world_index=1
    )
    assert first_world["opponent_deck"] != alternate_world["opponent_deck"]
    assert first_world["opponent_hand"] == alternate_world["opponent_hand"] == []


def test_candidate_filter_is_narrow_bounded_and_rejects_nullified_attacks(monkeypatch):
    obs = observation(
        [
            Option(OptionType.ATTACK, attackId=935),
            Option(OptionType.ATTACK, attackId=1239),
            Option(OptionType.END),
        ]
    )

    def fake_candidates(current, baseline, *, max_candidates):
        assert max_candidates == 32
        values = [
            SemanticCandidate(
                tuple(baseline), semantic_action_key(current, baseline), "d842_baseline", True
            )
        ]
        for index, reason in ((0, "attack_over_end"), (1, "attack_choice"), (2, "ready_retreat")):
            action = (index,)
            values.append(
                SemanticCandidate(action, semantic_action_key(current, action), reason, False)
            )
        return tuple(values)

    monkeypatch.setattr(runtime, "semantic_candidates", fake_candidates)
    monkeypatch.setattr(runtime, "attack_nullified", lambda _obs, option: option.attackId == 1239)
    candidates = runtime._candidate_set(obs, (2,), RuntimeProofConfig(timeout_seconds=1))
    assert [candidate.reason for candidate in candidates] == [
        "d842_baseline",
        "attack_over_end",
    ]


def test_candidate_semantics_redact_own_hand_while_determinization_uses_it(monkeypatch):
    obs = observation()
    obs.current.players[0].hand = [card(7, 2, 0)]
    obs.current.players[0].handCount = 1
    obs.current.players[0].deckCount = 52
    original = runtime.semantic_candidates
    observed = {}

    def audited_candidates(semantic_obs, baseline, *, max_candidates):
        observed["hero_hand"] = semantic_obs.current.players[0].hand
        observed["opponent_hand"] = semantic_obs.current.players[1].hand
        observed["prizes"] = [
            list(player_state.prize) for player_state in semantic_obs.current.players
        ]
        observed["context"] = semantic_obs.select.contextCard
        observed["effect"] = semantic_obs.select.effect
        return original(semantic_obs, baseline, max_candidates=max_candidates)

    monkeypatch.setattr(runtime, "semantic_candidates", audited_candidates)
    candidates = runtime._candidate_set(obs, (1,), RuntimeProofConfig(timeout_seconds=1))
    assert len(candidates) == 2
    assert observed == {
        "hero_hand": [],
        "opponent_hand": None,
        "prizes": [[None] * 6, [None] * 6],
        "context": None,
        "effect": None,
    }

    seed = runtime_world_seeds(obs, RuntimeProofConfig(timeout_seconds=1))[0]
    information_set = runtime._public_determinization(
        obs, HERO_DECK, seed=seed, world_index=0
    )
    assert len(information_set["your_deck"]) == 52
    assert len(information_set["your_prize"]) == 6
    assert information_set["your_deck"].count(7) == 52


def test_option_indices_are_resolved_fresh_on_every_prompt_and_reset_clears_budgets():
    def attack_wins(root, action):
        return int(root.select.option[action[0]].type) == int(OptionType.ATTACK)

    backend = FakeBackend(winner_predicate=attack_wins)
    proof = director(backend)
    assert proof.choose(observation(), [1]) == [0]
    reordered = observation(
        [Option(OptionType.END), Option(OptionType.ATTACK, attackId=935)]
    )
    assert proof.choose(reordered, [0]) == [1]
    assert not any("candidate" in name or "action" in name for name in proof.__dict__)
    assert proof.telemetry["budget"]["search_calls_used"] == 2
    proof.reset()
    assert proof.telemetry["budget"]["search_calls_used"] == 0
    assert proof.telemetry["last"]["status"] == "reset"


def test_missing_payload_invalid_baseline_and_information_set_error_are_exact_fallthroughs():
    obs = observation()
    obs.search_begin_input = None
    proof = director(FakeBackend(winners=[(0,)]))
    assert proof.choose(obs, [1]) == [1]
    assert proof.telemetry["last"]["reason"] == "missing_search_payload"

    invalid = director(FakeBackend(winners=[(0,)]))
    assert invalid.choose(observation(), [99]) == [99]
    assert invalid.telemetry["last"]["reason"] == "invalid_input"

    looking_obs = observation()
    looking_obs.current.looking = []
    hidden = director(FakeBackend(winners=[(0,)]))
    assert hidden.choose(looking_obs, [1]) == [1]
    assert hidden.telemetry["last"]["reason"] == "information_set_error"


@pytest.mark.parametrize("player_index", [0, 1])
def test_identified_prize_on_either_side_fails_closed_before_native_search(player_index):
    obs = observation()
    obs.current.players[player_index].prize[0] = card(
        7 if player_index == 0 else 3,
        900 + player_index,
        player_index,
    )
    backend = FakeBackend(winners=[(0,)])
    proof = director(backend)
    assert proof.choose(obs, [1]) == [1]
    assert proof.telemetry["last"]["reason"] == "information_set_error"
    assert backend.created == []


def test_incomplete_equal_coverage_abstains(monkeypatch):
    proof = director(FakeBackend(winners=[(0,)]))
    calls = 0

    def incomplete(_obs, ordered, _determinization, _deadline):
        nonlocal calls
        calls += 1
        branch = BranchEvidence(-1, False, False, "same")
        if calls == 1:
            return {ordered[0].key: branch}
        return {candidate.key: branch for candidate in ordered}

    monkeypatch.setattr(proof, "_evaluate_root", incomplete)
    assert proof.choose(observation(), [1]) == [1]
    assert proof.telemetry["last"]["reason"] == "incomplete_coverage"
