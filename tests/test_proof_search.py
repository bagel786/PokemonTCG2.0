from __future__ import annotations

import copy
from types import SimpleNamespace as NS

import pytest

from cg.api import AreaType, EnergyType, Option, OptionType, SelectContext, SelectType

from ptcg_ai.card_ids import DARK_ENERGY, MARNIES_GRIMMSNARL_EX, MARNIES_IMPIDIMP, MARNIES_MORGREM
from ptcg_ai.proof_search import (
    OUTCOME_FIELDS,
    NativeCompleteTurnRunner,
    NativeOnePromptRunner,
    ProofSearchConfig,
    ProofSearchTimeout,
    SelectiveProofSearch,
    WorldOutcome,
    deterministic_world_seeds,
    public_state_digest,
    semantic_candidates,
)


def card(card_id, serial=1, player=0):
    return NS(id=card_id, serial=serial, playerIndex=player)


def pokemon(card_id, serial=1, *, player=0, hp=100, max_hp=100, energies=()):
    return NS(
        id=card_id,
        serial=serial,
        playerIndex=player,
        hp=hp,
        maxHp=max_hp,
        appearThisTurn=False,
        energies=list(energies),
        energyCards=[],
        tools=[],
        preEvolution=[],
    )


def player(*, hand=(), active=(), bench=(), discard=(), prize_count=6, deck_count=40):
    return NS(
        hand=list(hand),
        handCount=len(hand),
        active=list(active),
        bench=list(bench),
        discard=list(discard),
        prize=[None] * prize_count,
        deckCount=deck_count,
        benchMax=5,
        poisoned=False,
        burned=False,
        asleep=False,
        paralyzed=False,
        confused=False,
    )


def selection(options, *, context=SelectContext.MAIN, minimum=1, maximum=1, context_card=None):
    return NS(
        type=SelectType.MAIN,
        context=context,
        minCount=minimum,
        maxCount=maximum,
        remainDamageCounter=0,
        remainEnergyCost=0,
        option=list(options),
        deck=None,
        contextCard=context_card,
        effect=None,
    )


def observation(select, me=None, opponent=None, *, turn=5):
    me = me or player(active=[pokemon(MARNIES_IMPIDIMP)])
    opponent = opponent or player(active=[pokemon(MARNIES_IMPIDIMP, 101, player=1)])
    current = NS(
        turn=turn,
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
        players=[me, opponent],
    )
    return NS(select=select, current=current, logs=[])


def outcome(first, *, boundary=("opponent_turn", "0", "0")):
    return WorldOutcome((float(first),) + (0.0,) * (len(OUTCOME_FIELDS) - 1), boundary)


def attack_end_observation(*, reversed_options=False):
    options = [Option(OptionType.ATTACK, attackId=937), Option(OptionType.END)]
    if reversed_options:
        options.reverse()
    return observation(selection(options))


class FakeCompleteTurnBackend:
    """Small immutable-root search tree used to audit runner ownership rules."""

    def __init__(self, *, all_pending=False, better_index=0, never_complete=False, fail_release=False):
        self.all_pending = all_pending
        self.better_index = better_index
        self.never_complete = never_complete
        self.fail_release = fail_release
        self.failed_release = False
        self.next_id = 1
        self.created = []
        self.states = {}
        self.root_steps = {}
        self.continuation_steps = []
        self.release_attempts = []
        self.released = []
        self.ended = 0

    def _state(self, obs, *, kind, benefit=False, root_id=None):
        search_id = self.next_id
        self.next_id += 1
        state = NS(
            searchId=search_id,
            observation=obs,
            fake_kind=kind,
            fake_benefit=benefit,
            fake_root_id=search_id if root_id is None else root_id,
        )
        self.states[search_id] = state
        self.created.append(search_id)
        return state

    def begin(self, obs, determinization):
        assert isinstance(determinization, dict)
        root = self._state(obs, kind="root")
        self.root_steps[root.searchId] = []
        return root

    @staticmethod
    def _pending_obs(parent):
        pending = copy.deepcopy(parent)
        pending.select = selection(
            [Option(OptionType.YES), Option(OptionType.NO)],
            context=SelectContext.ACTIVATE,
        )
        return pending

    @staticmethod
    def _complete_obs(parent, benefit):
        completed = copy.deepcopy(parent)
        completed.current.yourIndex = 1
        completed.current.turn += 1
        completed.select = selection([Option(OptionType.END)])
        if benefit:
            completed.current.players[0].prize = [None] * 5
        return completed

    def step(self, search_id, action):
        parent = self.states[int(search_id)]
        action = tuple(map(int, action))
        if parent.fake_kind == "root":
            self.root_steps[parent.searchId].append(action)
            benefit = action == (self.better_index,)
            option_type = int(parent.observation.select.option[action[0]].type)
            pending = self.all_pending or option_type != int(OptionType.END)
            if pending:
                return self._state(
                    self._pending_obs(parent.observation),
                    kind="pending",
                    benefit=benefit,
                    root_id=parent.searchId,
                )
            return self._state(
                self._complete_obs(parent.observation, benefit),
                kind="complete",
                benefit=benefit,
                root_id=parent.searchId,
            )

        self.continuation_steps.append((parent.fake_root_id, action))
        if self.never_complete:
            return self._state(
                self._pending_obs(parent.observation),
                kind="pending",
                benefit=parent.fake_benefit,
                root_id=parent.fake_root_id,
            )
        return self._state(
            self._complete_obs(parent.observation, parent.fake_benefit),
            kind="complete",
            benefit=parent.fake_benefit,
            root_id=parent.fake_root_id,
        )

    def release(self, search_id):
        search_id = int(search_id)
        self.release_attempts.append(search_id)
        if self.fail_release and not self.failed_release:
            self.failed_release = True
            raise RuntimeError("release failed")
        self.released.append(search_id)

    def end(self):
        self.ended += 1


class SingleUseSelector:
    def __init__(self):
        self.calls = 0

    def choose(self, _obs):
        self.calls += 1
        if self.calls > 1:
            raise AssertionError("selector state leaked across branches")
        return [0]


def ignored_determinizer(_obs, _hero, _opponent, _rng):
    return {}


def test_semantic_candidates_are_index_permutation_invariant_and_keep_baseline_first():
    original = attack_end_observation()
    swapped = attack_end_observation(reversed_options=True)
    first = semantic_candidates(original, [1])
    second = semantic_candidates(swapped, [0])
    assert first[0].is_baseline and second[0].is_baseline
    assert first[0].action == (1,)
    assert second[0].action == (0,)
    assert {item.key for item in first} == {item.key for item in second}
    assert {item.reason for item in first} == {"d842_baseline", "attack_over_end"}


def test_candidate_generation_is_tactical_and_finds_readiness_attach_and_evolve():
    me = player(
        hand=[card(DARK_ENERGY), card(MARNIES_GRIMMSNARL_EX, 2)],
        active=[pokemon(MARNIES_MORGREM, energies=[EnergyType.DARKNESS])],
    )
    select = selection(
        [
            Option(OptionType.END),
            Option(
                OptionType.ATTACH,
                area=AreaType.HAND,
                index=0,
                inPlayArea=AreaType.ACTIVE,
                inPlayIndex=0,
            ),
            Option(
                OptionType.EVOLVE,
                area=AreaType.HAND,
                index=1,
                inPlayArea=AreaType.ACTIVE,
                inPlayIndex=0,
            ),
        ]
    )
    reasons = {item.reason for item in semantic_candidates(observation(select, me), [0])}
    assert "readiness_attach" in reasons
    # With one Darkness, evolving Morgrem to Grim does not create readiness.
    assert "readiness_evolve" not in reasons

    me.active[0].energies.append(EnergyType.DARKNESS)
    reasons = {item.reason for item in semantic_candidates(observation(select, me), [0])}
    assert "readiness_evolve" in reasons

    quiet = observation(selection([Option(OptionType.PLAY, index=0), Option(OptionType.END)]), me)
    assert len(semantic_candidates(quiet, [0])) == 1


def test_public_seed_is_deterministic_and_excludes_hidden_identities():
    select = selection([Option(OptionType.END)])
    first = observation(
        select,
        player(hand=[card(7)], active=[pokemon(MARNIES_IMPIDIMP)]),
        player(hand=[card(999, player=1)], active=[pokemon(MARNIES_IMPIDIMP, 10, player=1)]),
    )
    second = observation(
        select,
        player(hand=[card(1234)], active=[pokemon(MARNIES_IMPIDIMP)]),
        player(hand=[card(888, player=1)], active=[pokemon(MARNIES_IMPIDIMP, 10, player=1)]),
    )
    assert public_state_digest(first) == public_state_digest(second)
    config = ProofSearchConfig(worlds=4, min_strict_worlds=2)
    assert deterministic_world_seeds(first, config) == deterministic_world_seeds(second, config)
    assert len(set(deterministic_world_seeds(first, config))) == 4
    second.current.players[1].active[0].hp -= 10
    assert public_state_digest(first) != public_state_digest(second)


def test_worldwise_dominance_proves_attack_and_uses_common_deterministic_worlds():
    obs = attack_end_observation()
    seen = []

    def runner(_obs, candidates, seed, _deadline, _opponent):
        seen.append((seed, tuple(item.key for item in candidates), candidates[0].is_baseline))
        return {
            item.key: outcome(1 if item.reason == "attack_over_end" else 0)
            for item in candidates
        }

    config = ProofSearchConfig(worlds=8, min_strict_worlds=4, timeout_seconds=1)
    result = SelectiveProofSearch(config=config, world_runner=runner).choose(obs, [1])
    assert result.status == "proved"
    assert result.action == [0]
    assert result.strict_worlds == 8
    assert all(value == 8 for value in result.coverage.values())
    assert [item[0] for item in seen] == list(deterministic_world_seeds(obs, config))
    assert all(item[1] == seen[0][1] and item[2] for item in seen)


def test_any_inferior_world_rejects_override_even_if_seven_worlds_are_better():
    obs = attack_end_observation()
    calls = 0

    def runner(_obs, candidates, _seed, _deadline, _opponent):
        nonlocal calls
        calls += 1
        attack_value = -1 if calls == 8 else 1
        return {
            item.key: outcome(attack_value if item.reason == "attack_over_end" else 0)
            for item in candidates
        }

    result = SelectiveProofSearch(
        config=ProofSearchConfig(timeout_seconds=1), world_runner=runner
    ).choose(obs, [1])
    assert result.status == "baseline"
    assert result.action == [1]
    assert result.reason == "no_worldwise_dominance"


def test_requires_configured_number_of_strict_worlds():
    obs = attack_end_observation()
    calls = 0

    def runner(_obs, candidates, _seed, _deadline, _opponent):
        nonlocal calls
        calls += 1
        attack_value = 1 if calls <= 3 else 0
        return {
            item.key: outcome(attack_value if item.reason == "attack_over_end" else 0)
            for item in candidates
        }

    result = SelectiveProofSearch(
        config=ProofSearchConfig(timeout_seconds=1), world_runner=runner
    ).choose(obs, [1])
    assert result.status == "baseline"
    assert result.reason == "insufficient_strict_worlds"
    assert result.strict_worlds == 3


def test_missing_candidate_or_unequal_semantic_boundary_abstains():
    obs = attack_end_observation()

    def incomplete(_obs, candidates, _seed, _deadline, _opponent):
        return {candidates[0].key: outcome(0)}

    result = SelectiveProofSearch(
        config=ProofSearchConfig(timeout_seconds=1), world_runner=incomplete
    ).choose(obs, [1])
    assert result.status == "abstained"
    assert result.action == [1]
    assert result.reason == "unequal_coverage_or_boundary"

    def unequal(_obs, candidates, _seed, _deadline, _opponent):
        return {
            item.key: outcome(
                1 if item.reason == "attack_over_end" else 0,
                boundary=("same_turn", "0", "0")
                if item.reason == "attack_over_end"
                else ("opponent_turn", "0", "0"),
            )
            for item in candidates
        }

    result = SelectiveProofSearch(
        config=ProofSearchConfig(timeout_seconds=1), world_runner=unequal
    ).choose(obs, [1])
    assert result.status == "abstained"
    assert result.action == [1]
    assert result.reason == "unequal_coverage_or_boundary"


def test_terminal_is_absorbing_but_runner_errors_and_timeouts_fall_through():
    obs = attack_end_observation()

    def terminal(_obs, candidates, _seed, _deadline, _opponent):
        return {
            item.key: outcome(
                1 if item.reason == "attack_over_end" else 0,
                boundary=("terminal",)
                if item.reason == "attack_over_end"
                else ("opponent_turn", "0", "0"),
            )
            for item in candidates
        }

    proved = SelectiveProofSearch(
        config=ProofSearchConfig(timeout_seconds=1), world_runner=terminal
    ).choose(obs, [1])
    assert proved.status == "proved"

    def broken(*_args):
        raise RuntimeError("engine failure")

    failed = SelectiveProofSearch(
        config=ProofSearchConfig(timeout_seconds=1), world_runner=broken
    ).choose(obs, [1])
    assert failed.status == "abstained"
    assert failed.action == [1]
    assert failed.reason == "world_error"

    def timed_out(*_args):
        raise ProofSearchTimeout("budget")

    failed = SelectiveProofSearch(
        config=ProofSearchConfig(timeout_seconds=1), world_runner=timed_out
    ).choose(obs, [1])
    assert failed.status == "abstained"
    assert failed.action == [1]
    assert failed.reason == "timeout"


def test_ready_promotion_targets_are_semantic_tactical_candidates():
    me = player(
        active=[pokemon(MARNIES_IMPIDIMP)],
        bench=[
            pokemon(MARNIES_IMPIDIMP, 2),
            pokemon(MARNIES_GRIMMSNARL_EX, 3, energies=[EnergyType.DARKNESS] * 2),
        ],
    )
    select = selection(
        [
            Option(OptionType.CARD, area=AreaType.BENCH, index=0, playerIndex=0),
            Option(OptionType.CARD, area=AreaType.BENCH, index=1, playerIndex=0),
        ],
        context=SelectContext.TO_ACTIVE,
    )
    candidates = semantic_candidates(observation(select, me), [0])
    assert [item.reason for item in candidates] == ["d842_baseline", "ready_promotion"]
    assert candidates[1].action == (1,)


def test_ready_retreat_and_opponent_ko_target_are_the_only_added_tactics():
    me = player(
        active=[pokemon(MARNIES_IMPIDIMP)],
        bench=[pokemon(MARNIES_GRIMMSNARL_EX, 2, energies=[EnergyType.DARKNESS] * 2)],
    )
    main = observation(selection([Option(OptionType.END), Option(OptionType.RETREAT)]), me)
    candidates = semantic_candidates(main, [0])
    assert [item.reason for item in candidates] == ["d842_baseline", "ready_retreat"]

    opponent = player(
        active=[pokemon(MARNIES_IMPIDIMP, 100, player=1)],
        bench=[
            pokemon(MARNIES_IMPIDIMP, 101, player=1),
            pokemon(MARNIES_GRIMMSNARL_EX, 102, player=1),
        ],
    )
    boss_target = selection(
        [
            Option(OptionType.CARD, area=AreaType.BENCH, index=0, playerIndex=1),
            Option(OptionType.CARD, area=AreaType.BENCH, index=1, playerIndex=1),
        ],
        context=SelectContext.SWITCH,
    )
    candidates = semantic_candidates(observation(boss_target, me, opponent), [0])
    assert [item.reason for item in candidates] == ["d842_baseline", "ko_target"]
    assert candidates[1].action == (1,)


def test_complete_turn_mode_resolves_multi_prompt_siblings_from_one_root():
    obs = attack_end_observation()
    backend = FakeCompleteTurnBackend(better_index=0)
    selectors = []

    def factory():
        selector = SingleUseSelector()
        selectors.append(selector)
        return selector

    search = SelectiveProofSearch(
        hero_deck=[7] * 60,
        config=ProofSearchConfig(worlds=2, min_strict_worlds=1, timeout_seconds=1),
        native_mode="complete_turn",
        continuation_selector_factory=factory,
        native_backend=backend,
        determinizer=ignored_determinizer,
    )
    assert isinstance(search.world_runner, NativeCompleteTurnRunner)
    result = search.choose(obs, [1], opponent_deck=[7] * 60)
    assert result.status == "proved"
    assert result.action == [0]
    # One common root per world; both d842 baseline and alternative are siblings.
    assert len(backend.root_steps) == 2
    assert all(actions == [(1,), (0,)] for actions in backend.root_steps.values())
    # A fresh selector exists even for the END branch, but only ATTACK needs it.
    assert len(selectors) == 4
    assert [selector.calls for selector in selectors] == [0, 1, 0, 1]
    assert set(backend.created) == set(backend.release_attempts)
    assert backend.ended == 2

    diagnostic = SelectiveProofSearch(hero_deck=[7] * 60)
    assert isinstance(diagnostic.world_runner, NativeOnePromptRunner)


def test_complete_turn_uses_fresh_stateful_selector_for_every_pending_branch():
    me = player(active=[pokemon(MARNIES_GRIMMSNARL_EX, energies=[EnergyType.DARKNESS] * 2)])
    opponent = player(
        active=[pokemon(MARNIES_IMPIDIMP, 100, player=1)],
        bench=[
            pokemon(MARNIES_IMPIDIMP, 101, player=1),
            pokemon(MARNIES_GRIMMSNARL_EX, 102, player=1),
        ],
    )
    target = selection(
        [
            Option(OptionType.CARD, area=AreaType.BENCH, index=0, playerIndex=1),
            Option(OptionType.CARD, area=AreaType.BENCH, index=1, playerIndex=1),
        ],
        context=SelectContext.DAMAGE,
    )
    obs = observation(target, me, opponent)
    backend = FakeCompleteTurnBackend(all_pending=True, better_index=1)
    selectors = []

    def factory():
        selector = SingleUseSelector()
        selectors.append(selector)
        return selector

    result = SelectiveProofSearch(
        hero_deck=[7] * 60,
        config=ProofSearchConfig(worlds=1, min_strict_worlds=1, timeout_seconds=1),
        native_mode="complete_turn",
        continuation_selector_factory=factory,
        native_backend=backend,
        determinizer=ignored_determinizer,
    ).choose(obs, [0], opponent_deck=[7] * 60)
    assert result.status == "proved"
    assert result.action == [1]
    assert len(selectors) == 2
    assert [selector.calls for selector in selectors] == [1, 1]
    assert backend.continuation_steps == [
        (next(iter(backend.root_steps)), (0,)),
        (next(iter(backend.root_steps)), (0,)),
    ]


def test_complete_turn_truncation_abstains_and_releases_every_created_state():
    obs = attack_end_observation()
    backend = FakeCompleteTurnBackend(all_pending=True, never_complete=True)
    result = SelectiveProofSearch(
        hero_deck=[7] * 60,
        config=ProofSearchConfig(worlds=1, min_strict_worlds=1, timeout_seconds=1),
        native_mode="complete_turn",
        continuation_selector_factory=lambda: (lambda _obs: [0]),
        max_turn_steps=2,
        native_backend=backend,
        determinizer=ignored_determinizer,
    ).choose(obs, [1], opponent_deck=[7] * 60)
    assert result.status == "abstained"
    assert result.action == [1]
    assert "truncation" in result.errors[0]
    assert set(backend.created) == set(backend.release_attempts)
    assert backend.ended == 1


@pytest.mark.parametrize(
    ("failure", "expected_reason"),
    [
        (ProofSearchTimeout("selector deadline"), "timeout"),
        (RuntimeError("selector defect"), "world_error"),
    ],
)
def test_complete_turn_selector_failure_is_fail_closed_and_cleans_up(failure, expected_reason):
    obs = attack_end_observation()
    backend = FakeCompleteTurnBackend(all_pending=True)

    def factory():
        def select(_obs):
            raise failure

        return select

    result = SelectiveProofSearch(
        hero_deck=[7] * 60,
        config=ProofSearchConfig(worlds=1, min_strict_worlds=1, timeout_seconds=1),
        native_mode="complete_turn",
        continuation_selector_factory=factory,
        native_backend=backend,
        determinizer=ignored_determinizer,
    ).choose(obs, [1], opponent_deck=[7] * 60)
    assert result.status == "abstained"
    assert result.action == [1]
    assert result.reason == expected_reason
    assert set(backend.created) == set(backend.release_attempts)
    assert backend.ended == 1


def test_complete_turn_cleanup_error_invalidates_an_otherwise_complete_proof():
    obs = attack_end_observation()
    backend = FakeCompleteTurnBackend(better_index=0, fail_release=True)
    result = SelectiveProofSearch(
        hero_deck=[7] * 60,
        config=ProofSearchConfig(worlds=1, min_strict_worlds=1, timeout_seconds=1),
        native_mode="complete_turn",
        continuation_selector_factory=lambda: (lambda _obs: [0]),
        native_backend=backend,
        determinizer=ignored_determinizer,
    ).choose(obs, [1], opponent_deck=[7] * 60)
    assert result.status == "abstained"
    assert result.action == [1]
    assert result.reason == "unequal_coverage_or_boundary"
    assert "release failed" in result.errors[0]
    assert set(backend.created) == set(backend.release_attempts)
    assert backend.ended == 1
