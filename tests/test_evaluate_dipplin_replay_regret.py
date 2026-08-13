from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from cg.api import AreaType, OptionType, SelectContext, SelectType
from ptcg_ai.dipplin.cards import FESTIVAL, HILDA
from scripts import evaluate_dipplin_replay_regret as regret
from scripts.freeze_dipplin_replay_holdout import add_manifest_digest


def card(card_id: int, serial: int, player: int = 0):
    return SimpleNamespace(id=card_id, serial=serial, playerIndex=player)


def play_option(index: int):
    return SimpleNamespace(
        type=OptionType.PLAY,
        index=index,
        area=None,
        playerIndex=None,
        number=None,
        count=None,
        attackId=None,
        cardId=None,
        serial=None,
        specialConditionType=None,
        inPlayArea=None,
        inPlayIndex=None,
        toolIndex=None,
        energyIndex=None,
    )


def observation(
    hand,
    *,
    options=None,
    turn: int = 3,
    turn_action_count: int = 5,
    your_index: int = 0,
    deck_counts=(2, 2),
    prize_counts=(1, 1),
    opponent_hand_count: int = 2,
    opponent_active=None,
):
    players = [
        SimpleNamespace(
            hand=list(hand),
            handCount=len(hand),
            deckCount=deck_counts[0],
            prize=[None] * prize_counts[0],
            active=[card(42, 100, 0)],
            bench=[],
            discard=[],
        ),
        SimpleNamespace(
            hand=None,
            handCount=opponent_hand_count,
            deckCount=deck_counts[1],
            prize=[None] * prize_counts[1],
            active=[None] if opponent_active is None else [opponent_active],
            bench=[],
            discard=[],
        ),
    ]
    select = SimpleNamespace(
        type=SelectType.MAIN,
        context=SelectContext.MAIN,
        minCount=1,
        maxCount=1,
        option=list(options if options is not None else [play_option(i) for i in range(len(hand))]),
        contextCard=None,
        effect=None,
        deck=None,
    )
    current = SimpleNamespace(
        yourIndex=your_index,
        turn=turn,
        turnActionCount=turn_action_count,
        players=players,
        looking=None,
        stadium=[],
        result=-1,
    )
    return SimpleNamespace(current=current, select=select, logs=[], search_begin_input="opaque")


def full_frame(*, turn: int = 3, turn_action_count: int = 5) -> dict:
    return {
        "current": {
            "yourIndex": 0,
            "turn": turn,
            "turnActionCount": turn_action_count,
            "players": [
                {
                    "deck": [{"id": 101, "serial": 1}, {"id": 102, "serial": 2}],
                    "prize": [{"id": 103, "serial": 3}],
                    "hand": [{"id": 42, "serial": 100}],
                    "active": [{"id": 42, "serial": 100}],
                    "bench": [],
                    "discard": [],
                },
                {
                    "deck": [{"id": 201, "serial": 4}, {"id": 202, "serial": 5}],
                    "prize": [{"id": 203, "serial": 6}],
                    "hand": [{"id": 204, "serial": 7}, {"id": 205, "serial": 8}],
                    "active": [{"id": 206, "serial": 9}],
                    "bench": [],
                    "discard": [],
                },
            ],
        },
        "select": {
            "type": "Main",
            "context": "Main",
            "minCount": 1,
            "maxCount": 1,
            "option": [{"type": "Play", "index": 0}],
        },
    }


def frozen_manifest(tmp_path: Path, *, sealed: bool = False) -> tuple[Path, dict]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    split = "FINAL_HOLDOUT" if sealed else "VALIDATION"
    count = regret.EXPECTED_SPLIT_COUNTS[split]
    episodes = []
    for offset in range(count):
        episode_id = 7001 + offset
        replay_path = tmp_path / f"episode-{episode_id}-replay.json"
        replay_path.write_text(json.dumps({"id": episode_id, "steps": []}), encoding="utf-8")
        episodes.append({
            "episode_id": episode_id,
            "replay_cache_path": str(replay_path),
            "replay_sha256": hashlib.sha256(replay_path.read_bytes()).hexdigest(),
            "first_player_seat": 0,
            "expert_result": "win",
            "selection_contract_verified": True,
            "hero": {"seat": 0, "actual_order": "first"},
            "opponent": {"archetype": "Garchomp"},
        })
    payload = {
        "schema_version": 1,
        "dataset": regret.FROZEN_DATASET,
        "split": split,
        "sealed": sealed,
        "episode_count": count,
        "inspection_policy": {
            "metadata_only": True,
            "action_level_inspected": False,
            "replay_regret_executed": False,
            "individual_failure_inspection_permitted": not sealed,
        },
        "selection_provenance": {"selection_used_outcome": False},
        "provenance": {},
        "episodes": episodes,
    }
    signed = add_manifest_digest(payload)
    manifest_path = tmp_path / f"{split.casefold()}_manifest.json"
    manifest_path.write_text(json.dumps(signed), encoding="utf-8")
    return manifest_path, signed


def test_load_manifest_verifies_digest_replay_hash_and_sealed_contract(tmp_path: Path):
    path, signed = frozen_manifest(tmp_path)
    loaded = regret.load_manifest(path, require_pinned=False)
    assert loaded["split"] == "VALIDATION"
    assert loaded["episodes"][0]["episode_id"] == 7001

    tampered = copy.deepcopy(signed)
    tampered["episodes"][0]["expert_result"] = "loss"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(regret.RegretError, match="digest"):
        regret.load_manifest(path, require_pinned=False)

    path, signed = frozen_manifest(tmp_path / "wrong-hash")
    unsigned = {key: value for key, value in signed.items() if key != "manifest_payload_sha256"}
    unsigned["episodes"][0]["replay_sha256"] = "0" * 64
    path.write_text(json.dumps(add_manifest_digest(unsigned)), encoding="utf-8")
    with pytest.raises(regret.RegretError, match="replay.*sha|hash"):
        regret.load_manifest(path, require_pinned=False)


def test_load_manifest_rejects_a_final_holdout_that_is_not_sealed(tmp_path: Path):
    path, signed = frozen_manifest(tmp_path, sealed=True)
    unsigned = {key: value for key, value in signed.items() if key != "manifest_payload_sha256"}
    unsigned["sealed"] = False
    path.write_text(json.dumps(add_manifest_digest(unsigned)), encoding="utf-8")
    with pytest.raises(regret.RegretError, match="sealed|FINAL_HOLDOUT"):
        regret.load_manifest(path, require_pinned=False)


def test_replay_is_parsed_from_the_same_bytes_whose_hash_was_verified(tmp_path: Path):
    replay_path = tmp_path / "replay.json"
    replay_path.write_text('{"id":1,"steps":[]}', encoding="utf-8")
    expected = regret._sha256(replay_path)
    assert regret._load_json_replay(replay_path, expected_sha256=expected)["id"] == 1

    replay_path.write_text('{"id":2,"steps":[]}', encoding="utf-8")
    with pytest.raises(regret.RegretError, match="changed|verification"):
        regret._load_json_replay(replay_path, expected_sha256=expected)


@pytest.mark.parametrize("split", ["VALIDATION", "FINAL_HOLDOUT"])
def test_real_frozen_manifest_matches_exact_pin_without_opening_replays(monkeypatch, split):
    pinned = regret.PINNED_MANIFESTS[split]
    manifest_path = Path(pinned["path"])
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    replay_hashes = {
        Path(row["replay_cache_path"]).name: row["replay_sha256"].upper()
        for row in payload["episodes"]
    }
    original_sha256 = regret._sha256

    monkeypatch.setattr(
        regret,
        "_resolve_replay_path",
        lambda raw, _manifest_path: Path(str(raw)),
    )
    def metadata_only_hash(path):
        replay_hash = replay_hashes.get(Path(path).name)
        return replay_hash if replay_hash is not None else original_sha256(Path(path))

    monkeypatch.setattr(regret, "_sha256", metadata_only_hash)

    loaded = regret.load_manifest(manifest_path)

    assert loaded["dataset"] == regret.FROZEN_DATASET
    assert loaded["episode_count"] == regret.EXPECTED_SPLIT_COUNTS[split]


def test_verify_incumbent_matches_exact_archive_manifest_and_tree_pins():
    incumbent = regret.verify_incumbent()

    assert incumbent["archive_sha256"] == regret.PINNED_S1_ARCHIVE_SHA256
    assert incumbent["manifest_sha256"] == regret.PINNED_S1_MANIFEST_SHA256
    assert incumbent["validation_result_sha256"] == regret.PINNED_S1_VALIDATION_OUTPUT_SHA256
    assert incumbent["paired_record_count"] == 1145
    # The live checkout is S2.  Baseline verification must not demand that it
    # be rolled back to the old S1 source tree.
    s1_manifest = json.loads(regret.DEFAULT_INCUMBENT_MANIFEST.read_text(encoding="utf-8"))
    old_search_hash = s1_manifest["output"]["file_manifest"]["ptcg_ai/dipplin/search.py"]["sha256"]
    assert regret._sha256(regret.ROOT / "ptcg_ai/dipplin/search.py") != old_search_hash


def test_verify_s2_candidate_matches_exact_package_and_all_local_sources():
    candidate = regret.verify_s2_candidate()

    assert candidate["archive_sha256"] == regret.PINNED_S2_ARCHIVE_SHA256
    assert candidate["manifest_sha256"] == regret.PINNED_S2_MANIFEST_SHA256
    assert candidate["extracted_tree_sha256"] == regret.PINNED_S2_EXTRACTED_TREE_SHA256
    assert candidate["runtime_source_tree_sha256"] == regret.PINNED_S2_RUNTIME_TREE_SHA256
    assert candidate["configuration"]["s2"] is True
    assert candidate["configuration"]["search_worlds"] == 2
    assert "ptcg_ai/dipplin/search.py" in candidate["source_sha256"]


def test_strategic_sample_is_seeded_priority_preserving_and_capped_per_episode():
    rows = []
    for episode in (11, 12):
        rows.extend(
            [
                {
                    "record_id": f"{episode}-critical",
                    "episode_id": episode,
                    "step": 20,
                    "strategic_priority": 100,
                    "decision_family": "first_productive_attack",
                },
                {
                    "record_id": f"{episode}-recovery",
                    "episode_id": episode,
                    "step": 30,
                    "strategic_priority": 90,
                    "decision_family": "recovery",
                },
                {
                    "record_id": f"{episode}-trivial-a",
                    "episode_id": episode,
                    "step": 40,
                    "strategic_priority": 0,
                    "decision_family": "routine_play_basic",
                },
                {
                    "record_id": f"{episode}-trivial-b",
                    "episode_id": episode,
                    "step": 41,
                    "strategic_priority": 0,
                    "decision_family": "routine_play_basic",
                },
            ]
        )

    selected = regret.strategic_sample(rows, cap_per_episode=2, seed=20260813)
    repeated = regret.strategic_sample(list(reversed(rows)), cap_per_episode=2, seed=20260813)
    assert selected == repeated
    assert len(selected) == 4
    assert {row["record_id"] for row in selected} == {
        "11-critical",
        "11-recovery",
        "12-critical",
        "12-recovery",
    }
    assert all(
        sum(row["episode_id"] == episode for row in selected) <= 2
        for episode in (11, 12)
    )
    with pytest.raises((regret.RegretError, ValueError), match="cap"):
        regret.strategic_sample(rows, cap_per_episode=0, seed=1)


def test_actual_second_setup_disagreement_has_nontrivial_sampling_priority():
    obs = observation(
        [card(42, 1001), card(89, 1002)],
        options=[play_option(0), play_option(1)],
        turn=0,
    )
    obs.current.firstPlayer = 0
    obs.select.type = SelectType.CARD
    obs.select.context = SelectContext.SETUP_ACTIVE_POKEMON
    shadow = SimpleNamespace(proposal=None, working_memory=SimpleNamespace())

    priority = regret._strategic_priority(obs, shadow, "setup", 0, "second")

    assert priority >= 85


def test_strategic_sample_reserves_actual_second_setup_under_a_small_cap():
    rows = [
        {
            "record_id": "setup",
            "episode_id": 17,
            "step": 2,
            "strategic_priority": 55,
            "decision_family": "setup",
            "actual_order": "second",
            "semantic_equivalent": False,
        },
        {
            "record_id": "attack",
            "episode_id": 17,
            "step": 20,
            "strategic_priority": 125,
            "decision_family": "first_productive_attack",
            "actual_order": "second",
        },
        {
            "record_id": "festival",
            "episode_id": 17,
            "step": 21,
            "strategic_priority": 130,
            "decision_family": "festival_second_attack",
            "actual_order": "second",
        },
    ]

    sampled = regret.strategic_sample(rows, cap_per_episode=2, seed=1)

    assert {row["record_id"] for row in sampled} == {"setup", "festival"}


def test_duplicate_copies_are_semantically_equal_but_applin_prints_remain_distinct():
    obs = observation(
        [card(42, 1001), card(42, 1002), card(92, 1003)],
        options=[play_option(0), play_option(1), play_option(2)],
    )

    first_copy = regret.semantic_action_key(obs, [0])
    second_copy = regret.semantic_action_key(obs, [1])
    other_applin = regret.semantic_action_key(obs, [2])
    assert first_copy == second_copy
    assert first_copy != other_applin
    assert regret.semantic_actions_equivalent(obs, [0], [1])
    assert not regret.semantic_actions_equivalent(obs, [0], [2])


def test_strategic_ties_prefer_disagreements_to_semantic_matches():
    rows = [
        {
            "record_id": "agreement",
            "episode_id": 9,
            "step": 2,
            "strategic_priority": 50,
            "decision_family": "setup",
            "semantic_equivalent": True,
        },
        {
            "record_id": "disagreement",
            "episode_id": 9,
            "step": 3,
            "strategic_priority": 50,
            "decision_family": "setup",
            "semantic_equivalent": False,
        },
    ]

    selected = regret.strategic_sample(rows, cap_per_episode=1, seed=11)

    assert selected[0]["record_id"] == "disagreement"


@pytest.mark.parametrize(
    ("expert", "agent", "expected"),
    [
        ([(1, 2, 3), (1, 2, 3)], [(1, 2, 3), (1, 2, 3)], "EQUIVALENT"),
        ([(0, 2, 3), (0, 2, 3)], [(0, 3, 3), (1, 2, 3)], "AGENT_DOMINATES"),
        ([(0, 3, 3), (1, 2, 3)], [(0, 2, 3), (0, 2, 3)], "EXPERT_DOMINATES"),
        ([(0, 2, 4), (1, 1, 3)], [(0, 3, 3), (0, 2, 3)], "INCOMPARABLE"),
        ([(0, 3)], [(1, 2)], "INCOMPARABLE"),
    ],
)
def test_componentwise_labels_across_all_valid_worlds(expert, agent, expected):
    assert regret.componentwise_label(expert, agent) == expected


def test_componentwise_label_fails_closed_on_bad_or_unequal_world_coverage():
    assert regret.componentwise_label([(1, 2)], []) == "UNCERTIFIABLE"
    assert regret.componentwise_label([(1, 2)], [(1, 2), (1, 2)]) == "UNCERTIFIABLE"
    assert regret.componentwise_label([(1, float("nan"))], [(2, 3)]) == "UNCERTIFIABLE"
    assert regret.componentwise_label([(1, 2)], [(1,)]) == "UNCERTIFIABLE"


def test_visualizer_alignment_uses_t_minus_one_and_rejects_mismatches():
    older = full_frame(turn=2, turn_action_count=8)
    aligned = full_frame(turn=3, turn_action_count=5)
    replay = {
        "steps": [
            [{"visualize": [older, aligned]}],
            [{"observation": {}}],
            [{"observation": {}}],
        ]
    }
    obs = observation([card(42, 100)], turn=3, turn_action_count=5)
    assert regret.aligned_visualizer_frame(replay, 2, obs) is aligned

    mismatched = copy.deepcopy(obs)
    mismatched.current.turnActionCount = 6
    with pytest.raises(regret.RegretError, match="align|turnActionCount"):
        regret.aligned_visualizer_frame(replay, 2, mismatched)
    with pytest.raises(regret.RegretError, match="visual|step|align"):
        regret.aligned_visualizer_frame(replay, 0, obs)

    wrong_select = copy.deepcopy(aligned)
    wrong_select["select"]["context"] = "SetupBenchPokemon"
    replay["steps"][0][0]["visualize"][1] = wrong_select
    with pytest.raises(regret.RegretError, match="select context"):
        regret.aligned_visualizer_frame(replay, 2, obs)


def test_validate_exact_hidden_preserves_order_and_checks_public_zone_counts():
    obs = observation([card(42, 100)], opponent_active=None)
    hidden = regret.validate_exact_hidden(obs, full_frame())
    assert hidden["your_deck"] == [101, 102]
    assert hidden["your_prize"] == [103]
    assert hidden["opponent_deck"] == [201, 202]
    assert hidden["opponent_prize"] == [203]
    assert hidden["opponent_hand"] == [204, 205]
    assert hidden["opponent_active"] == [206]

    wrong_count = copy.deepcopy(obs)
    wrong_count.current.players[0].deckCount = 3
    with pytest.raises(regret.RegretError, match="deck|count"):
        regret.validate_exact_hidden(wrong_count, full_frame())

    visible_mismatch = observation(
        [card(42, 100)],
        opponent_active=card(999, 55, 1),
    )
    with pytest.raises(regret.RegretError, match="active|public|identity"):
        regret.validate_exact_hidden(visible_mismatch, full_frame())


def test_rng_or_deck_touch_detects_stochastic_cards_and_fails_closed_on_bad_action():
    obs = observation(
        [card(FESTIVAL, 1), card(HILDA, 2)],
        options=[play_option(0), play_option(1)],
    )
    assert not regret.rng_or_deck_touch(obs, [0])
    assert regret.rng_or_deck_touch(obs, [1])

    coin_prompt = copy.deepcopy(obs)
    coin_prompt.select.context = SelectContext.COIN_HEAD
    assert regret.rng_or_deck_touch(coin_prompt, [])
    with pytest.raises(regret.RegretError, match="action|index"):
        regret.rng_or_deck_touch(obs, [99])


def test_chronological_candidate_explicitly_enables_frozen_s2_configuration():
    policy = regret.ChronologicalCandidate(candidate="s2", s2_enabled=True)

    assert policy.planner.go_first is True
    assert policy.planner.second_opening_v2 is True
    assert policy.planner.resolver.second_opening_v2 is True
    assert policy.planner.route_v2_enabled is False
    assert policy.search.config.worlds == 2
    assert policy.search.s2_enabled is True


def test_lazy_proposal_repeat_skips_only_no_search_rows(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("no repeat policy should be constructed")

    monkeypatch.setattr(regret, "ChronologicalCandidate", forbidden)
    deterministic = regret.certify_sampled_proposal(
        {
            "semantic_equivalent": False,
            "proposal_error": None,
            "candidate_search_started": False,
        },
        proposal_repeats=3,
    )

    assert deterministic["candidate_proposal_repeats"] == 1
    assert deterministic["candidate_proposal_repeat_mode"] == "deterministic_no_native_search"


def test_lazy_proposal_repeat_restores_exact_pre_prompt_checkpoint(monkeypatch):
    obs = observation(
        [card(42, 1001), card(92, 1002)],
        options=[play_option(0), play_option(1)],
    )
    pre_memory = regret.PlanMemory(global_turn=7)
    calls = []

    class FakeRepeatPolicy:
        def __init__(self, *_args, **_kwargs):
            self.memory = regret.PlanMemory()
            self.search = SimpleNamespace(searches_this_game=0)
            self.telemetry = regret.Telemetry()

        def propose(self, raw, repeated_obs):
            calls.append(
                (
                    raw["marker"],
                    repeated_obs is obs,
                    self.memory.global_turn,
                    self.search.searches_this_game,
                )
            )
            self.search.searches_this_game += 1
            return regret.ShadowProposal(
                [1],
                self.memory.clone(),
                SimpleNamespace(),
                None,
            )

    monkeypatch.setattr(regret, "ChronologicalCandidate", FakeRepeatPolicy)
    result = regret.certify_sampled_proposal(
        {
            "semantic_equivalent": True,
            "proposal_error": None,
            "candidate_search_started": True,
            "agent_action": [1],
            "_obs": obs,
            "_raw_observation": {"marker": "root"},
            "_pre_prompt_memory": pre_memory,
            "_pre_searches_this_game": 4,
            "_post_searches_this_game": 5,
        },
        proposal_repeats=3,
    )

    assert calls == [
        ("root", True, 7, 4),
        ("root", True, 7, 4),
    ]
    assert result["proposal_error"] is None
    assert result["candidate_proposal_repeats"] == 3
    assert result["candidate_proposal_repeat_mode"] == "lazy_checkpoint_replay"


def test_lazy_proposal_repeat_fails_closed_on_unstable_action(monkeypatch):
    obs = observation(
        [card(42, 1001), card(92, 1002)],
        options=[play_option(0), play_option(1)],
    )

    class UnstablePolicy:
        def __init__(self, *_args, **_kwargs):
            self.memory = regret.PlanMemory()
            self.search = SimpleNamespace(searches_this_game=0)
            self.telemetry = regret.Telemetry()

        def propose(self, _raw, _obs):
            self.search.searches_this_game += 1
            return regret.ShadowProposal(
                [0],
                self.memory.clone(),
                SimpleNamespace(),
                None,
            )

    monkeypatch.setattr(regret, "ChronologicalCandidate", UnstablePolicy)
    result = regret.certify_sampled_proposal(
        {
            "semantic_equivalent": False,
            "proposal_error": None,
            "candidate_search_started": True,
            "agent_action": [1],
            "_obs": obs,
            "_raw_observation": {},
            "_pre_prompt_memory": regret.PlanMemory(),
            "_pre_searches_this_game": 2,
            "_post_searches_this_game": 3,
        },
        proposal_repeats=2,
    )

    assert result["proposal_error"] == "candidate_action_unstable"


def test_lazy_proposal_repeat_fails_closed_on_search_progression_change(monkeypatch):
    obs = observation(
        [card(42, 1001), card(92, 1002)],
        options=[play_option(0), play_option(1)],
    )

    class WrongProgressionPolicy:
        def __init__(self, *_args, **_kwargs):
            self.memory = regret.PlanMemory()
            self.search = SimpleNamespace(searches_this_game=0)
            self.telemetry = regret.Telemetry()

        def propose(self, _raw, _obs):
            # A repeated controller which does not enter the same D1 gate is not
            # an identical reconstruction, even if its action happens to match.
            return regret.ShadowProposal(
                [1],
                self.memory.clone(),
                SimpleNamespace(),
                None,
            )

    monkeypatch.setattr(regret, "ChronologicalCandidate", WrongProgressionPolicy)
    result = regret.certify_sampled_proposal(
        {
            "semantic_equivalent": False,
            "proposal_error": None,
            "candidate_search_started": True,
            "agent_action": [1],
            "_obs": obs,
            "_raw_observation": {},
            "_pre_prompt_memory": regret.PlanMemory(),
            "_pre_searches_this_game": 2,
            "_post_searches_this_game": 3,
        },
        proposal_repeats=2,
    )

    assert result["proposal_error"] == "candidate_repeat_search_progression_error"


def test_lazy_proposal_repeat_requires_same_s2_override_telemetry(monkeypatch):
    obs = observation(
        [card(42, 1001), card(92, 1002)],
        options=[play_option(0), play_option(1)],
    )

    class MissingS2Override:
        def __init__(self, *_args, **_kwargs):
            self.memory = regret.PlanMemory()
            self.search = SimpleNamespace(searches_this_game=0)
            self.telemetry = regret.Telemetry()

        def propose(self, _raw, _obs):
            self.search.searches_this_game += 1
            return regret.ShadowProposal([1], self.memory.clone(), SimpleNamespace(), None)

    monkeypatch.setattr(regret, "ChronologicalCandidate", MissingS2Override)
    result = regret.certify_sampled_proposal(
        {
            "proposal_error": None,
            "candidate_search_started": True,
            "agent_action": [1],
            "s2_pre_attack_sequence_proof_overrides_delta": 1,
            "_obs": obs,
            "_raw_observation": {},
            "_pre_prompt_memory": regret.PlanMemory(),
            "_pre_searches_this_game": 2,
            "_post_searches_this_game": 3,
        },
        proposal_repeats=2,
    )

    assert result["proposal_error"] == "candidate_repeat_s2_telemetry_mismatch"


def test_deterministic_disagreement_uses_fresh_alternating_arm_calls(monkeypatch):
    obs = observation(
        [card(42, 1001), card(92, 1002)],
        options=[play_option(0), play_option(1)],
    )
    frame = full_frame()
    frame["current"]["players"][0]["hand"] = [
        {"id": 42, "serial": 1001},
        {"id": 92, "serial": 1002},
    ]
    frame["select"]["option"] = [
        {"type": "Play", "index": 0},
        {"type": "Play", "index": 1},
    ]
    replay = {"steps": [[{"visualize": [frame]}], [{"observation": {}}]]}
    calls = []

    def branch_metric(_obs, action, _hidden, _memory, _planner, *, category):
        calls.append((tuple(action), category))
        value = 1.0 if category.endswith("agent") else 0.0
        return (value,) * len(regret.METRIC_FIELDS)

    monkeypatch.setattr(regret, "_branch_metric", branch_metric)
    row = {
        "episode_id": 1,
        "step": 1,
        "expert_action": [0],
        "agent_action": [1],
        "semantic_equivalent": False,
        "proposal_error": None,
        "_obs": obs,
        "_memory": SimpleNamespace(),
    }

    result = regret.evaluate_candidate(row, replay, repeat_passes=2)

    assert result["classification"] == "AGENT_DOMINATES"
    assert calls == [
        ((0,), "replay_regret_expert"),
        ((1,), "replay_regret_agent"),
        ((1,), "replay_regret_agent"),
        ((0,), "replay_regret_expert"),
    ]
    assert result["repeat_passes"] == 2


def _classification_rows() -> list[dict]:
    rows = []
    for step in range(100):
        rows.append(
            {
                "episode_id": "episode-many",
                "step": step,
                "classification": "EXPERT_DOMINATES",
                "decision_family": "routine",
                "private_marker": f"many-secret-{step}",
            }
        )
    rows.append(
        {
            "episode_id": "episode-one",
            "step": 7,
            "classification": "AGENT_DOMINATES",
            "decision_family": "recovery",
            "private_marker": "one-secret",
        }
    )
    return rows


def test_aggregate_results_uses_episode_level_rates_and_seeded_cluster_bootstrap():
    rows = _classification_rows()
    first = regret.aggregate_results(rows, bootstrap_samples=500, seed=731)
    second = regret.aggregate_results(list(reversed(rows)), bootstrap_samples=500, seed=731)
    assert first == second
    assert first["episode_count"] == 2
    assert first["decision_count"] == 101
    assert first["classification_counts"]["EXPERT_DOMINATES"] == 100
    # One episode is all expert-dominates and one is all agent-dominates.  The
    # episode, rather than its number of sampled decisions, is the analysis unit.
    assert first["episode_rates"]["EXPERT_DOMINATES"] == pytest.approx(0.5)
    assert first["episode_rates"]["AGENT_DOMINATES"] == pytest.approx(0.5)
    interval = first["episode_bootstrap_95"]["EXPERT_DOMINATES"]
    assert len(interval) == 2
    assert 0.0 <= interval[0] <= interval[1] <= 1.0

    with pytest.raises((regret.RegretError, ValueError), match="bootstrap"):
        regret.aggregate_results(rows, bootstrap_samples=0, seed=1)


def _contains_key(value, forbidden: set[str]) -> bool:
    if isinstance(value, dict):
        return any(key in forbidden or _contains_key(child, forbidden) for key, child in value.items())
    if isinstance(value, list):
        return any(_contains_key(child, forbidden) for child in value)
    return False


def test_sealed_output_is_aggregate_only_and_suppresses_episode_and_decision_details(tmp_path: Path):
    _, validation_manifest = frozen_manifest(tmp_path / "validation", sealed=False)
    _, holdout_manifest = frozen_manifest(tmp_path / "holdout", sealed=True)
    rows = _classification_rows()

    open_output = regret.build_output(validation_manifest, rows, sealed=False)
    assert "episode-many" in json.dumps(open_output)
    assert "many-secret-0" in json.dumps(open_output)

    sealed_output = regret.build_output(holdout_manifest, rows, sealed=True)
    encoded = json.dumps(sealed_output, sort_keys=True)
    assert sealed_output["sealed"] is True
    assert sealed_output["aggregate"]["episode_count"] == 2
    assert "episode-many" not in encoded
    assert "episode-one" not in encoded
    assert "private_marker" not in encoded
    assert "many-secret" not in encoded
    assert "one-secret" not in encoded
    assert "by_actual_order" not in sealed_output["aggregate"]
    assert "by_opponent_archetype" not in sealed_output["aggregate"]
    assert "by_decision_family" not in sealed_output["aggregate"]
    assert not _contains_key(
        sealed_output,
        {
            "rows",
            "decisions",
            "decision_rows",
            "decision_details",
            "per_episode",
            "episodes",
            "episode_details",
            "episode_labels",
        },
    )


def test_sealed_contract_is_canonical_and_receipt_is_one_shot(tmp_path: Path):
    args = SimpleNamespace(
        manifest=regret.DEFAULT_FINAL_HOLDOUT_MANIFEST,
        output=regret.DEFAULT_SEALED_OUTPUT,
        candidate="s2",
        incumbent_manifest=regret.DEFAULT_INCUMBENT_MANIFEST,
        candidate_manifest=regret.DEFAULT_CANDIDATE_MANIFEST,
        qualification=regret.DEFAULT_S2_QUALIFICATION,
        max_episodes=None,
        **regret.FROZEN_SEALED_PARAMETERS,
    )
    manifest = {
        "split": "FINAL_HOLDOUT",
        "sealed": True,
        "manifest_payload_sha256": regret.PINNED_MANIFESTS["FINAL_HOLDOUT"]["payload_sha256"],
    }
    qualification = {
        "status": "QUALIFIED",
        "file_sha256": "A" * 64,
        "payload_sha256": "B" * 64,
        "candidate_validation_sha256": "C" * 64,
    }
    regret.validate_sealed_run_contract(args, manifest, qualification)

    changed = copy.copy(args)
    changed.bootstrap_samples -= 1
    with pytest.raises(regret.RegretError, match="parameters"):
        regret.validate_sealed_run_contract(changed, manifest, qualification)

    output_path = tmp_path / "aggregate.json"
    receipt_args = copy.copy(args)
    receipt_args.output = output_path
    receipt_path = tmp_path / "sealed-receipt.json"
    receipt = regret.claim_sealed_run(receipt_path, manifest, receipt_args, qualification)
    assert receipt["status"] == "ACTION_INSPECTION_CLAIMED"
    assert receipt["evaluator_sha256"]
    assert receipt["evaluator_git_blob_sha1"]
    with pytest.raises(regret.RegretError, match="already|claimed"):
        regret.claim_sealed_run(receipt_path, manifest, receipt_args, qualification)

    output_path.write_text('{"sealed":true}\n', encoding="utf-8")
    regret.complete_sealed_run(receipt_path, receipt, output_path)
    completed = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert completed["status"] == "COMPLETE"
    assert completed["aggregate_output_sha256"] == regret._sha256(output_path)


def test_active_hero_actor_must_match_manifest_seat(monkeypatch):
    fake_obs = observation([card(42, 100)], your_index=1)
    fake_obs.current.firstPlayer = 0
    monkeypatch.setattr(regret, "to_observation_class", lambda _raw: fake_obs)
    replay = {
        "steps": [
            [
                {
                    "status": "ACTIVE",
                    "observation": {"current": {}, "select": {}},
                }
            ],
            [{"action": [0]}],
        ]
    }
    meta = {
        "episode_id": 7,
        "hero": {"seat": 0, "actual_order": "first"},
        "opponent": {"archetype": "other"},
    }

    with pytest.raises(regret.RegretError, match="actor.*seat"):
        regret.reconstruct_episode_candidates(replay, meta, proposal_repeats=2)


def test_evaluate_manifest_requires_every_episode_to_contribute(monkeypatch):
    monkeypatch.setattr(regret, "_load_json_replay", lambda _path, **_kwargs: {"id": 9})
    monkeypatch.setattr(regret, "reconstruct_episode_candidates", lambda *_args, **_kwargs: [])
    manifest = {
        "episodes": [
            {"episode_id": 9, "replay_cache_path": "unused.json"},
        ]
    }

    with pytest.raises(regret.RegretError, match="no sampled useful decision"):
        regret.evaluate_manifest(
            manifest,
            cap_per_episode=2,
            sample_seed=1,
            repeat_passes=2,
            proposal_repeats=2,
        )


def test_official_validation_contract_is_candidate_pinned_full_and_frozen():
    args = SimpleNamespace(
        manifest=regret.PINNED_MANIFESTS["VALIDATION"]["path"],
        output=regret.DEFAULT_S2_VALIDATION_OUTPUT,
        candidate="s2",
        incumbent_manifest=regret.DEFAULT_INCUMBENT_MANIFEST,
        candidate_manifest=regret.DEFAULT_CANDIDATE_MANIFEST,
        qualification=regret.DEFAULT_S2_QUALIFICATION,
        sealed=False,
        max_episodes=None,
        **regret.FROZEN_SEALED_PARAMETERS,
    )
    manifest = {"split": "VALIDATION", "sealed": False, "episode_count": 50}

    regret.validate_validation_run_contract(args, manifest)
    changed = copy.copy(args)
    changed.output = Path("not-canonical.json")
    with pytest.raises(regret.RegretError, match="canonical output"):
        regret.validate_validation_run_contract(changed, manifest)
    changed = copy.copy(args)
    changed.proposal_repeats -= 1
    with pytest.raises(regret.RegretError, match="parameters"):
        regret.validate_validation_run_contract(changed, manifest)


def test_cli_requires_explicit_s2_candidate(tmp_path: Path):
    with pytest.raises(SystemExit):
        regret.parse_args(["--replay", "unused.json", "--output", str(tmp_path / "out.json")])
    args = regret.parse_args(
        [
            "--candidate",
            "s2",
            "--replay",
            "unused.json",
            "--output",
            str(tmp_path / "out.json"),
        ]
    )
    assert args.candidate == "s2"


def test_diagnostics_cannot_overwrite_frozen_outputs():
    args = SimpleNamespace(output=regret.DEFAULT_S2_VALIDATION_OUTPUT, sealed=False)
    with pytest.raises(regret.RegretError, match="reserved"):
        regret.validate_diagnostic_run_contract(args)
    args = SimpleNamespace(output=Path("diagnostic.json"), sealed=True)
    with pytest.raises(regret.RegretError, match="sealed"):
        regret.validate_diagnostic_run_contract(args)


def _dual_set_fixture():
    primary_ids = [f"primary-{index:04d}" for index in range(regret.PINNED_S1_PRIMARY_RECORD_COUNT)]
    rows = [
        {
            "record_id": record_id,
            "episode_id": index % 50 + 1,
            "step": index,
            "candidate_variant": "s2",
            "candidate_s2_enabled": True,
            "s2_override_telemetry_trustworthy": True,
            "s2_pre_attack_sequence_proof_overrides_delta": 0,
            "semantic_equivalent": True,
            "proposal_error": None,
        }
        for index, record_id in enumerate(primary_ids)
    ]
    rows.extend(
        [
            {
                "record_id": "outside-s2-disagreement",
                "episode_id": 1,
                "step": 2001,
                "candidate_variant": "s2",
                "candidate_s2_enabled": True,
                "s2_override_telemetry_trustworthy": True,
                "s2_pre_attack_sequence_proof_overrides_delta": 1,
                "semantic_equivalent": False,
                "proposal_error": None,
            },
            {
                "record_id": "outside-s2-expert-equivalent",
                "episode_id": 2,
                "step": 2002,
                "candidate_variant": "s2",
                "candidate_s2_enabled": True,
                "s2_override_telemetry_trustworthy": True,
                "s2_pre_attack_sequence_proof_overrides_delta": 1,
                "semantic_equivalent": True,
                "proposal_error": None,
            },
            {
                "record_id": "outside-non-s2-disagreement",
                "episode_id": 3,
                "step": 2003,
                "candidate_variant": "s2",
                "candidate_s2_enabled": True,
                "s2_override_telemetry_trustworthy": True,
                "s2_pre_attack_sequence_proof_overrides_delta": 0,
                "semantic_equivalent": False,
                "proposal_error": None,
            },
        ]
    )
    manifest = {
        "split": "VALIDATION",
        "sealed": False,
        "episode_count": 50,
        "episodes": [{"episode_id": episode_id} for episode_id in range(1, 51)],
    }
    replay_cache = {episode_id: {} for episode_id in range(1, 51)}
    return primary_ids, rows, manifest, replay_cache


def test_dual_sets_preserve_frozen_order_and_exhaustively_isolate_s2_disagreements(monkeypatch):
    primary_ids, rows, manifest, replay_cache = _dual_set_fixture()
    monkeypatch.setattr(
        regret,
        "_collect_manifest_candidates",
        lambda *_args, **_kwargs: (rows, replay_cache, manifest["episodes"]),
    )
    monkeypatch.setattr(
        regret,
        "certify_sampled_proposal",
        lambda row, **_kwargs: dict(row),
    )

    def fake_evaluate(row, _replay, **_kwargs):
        result = dict(row)
        result["classification"] = "EQUIVALENT"
        return result

    monkeypatch.setattr(regret, "evaluate_candidate", fake_evaluate)
    evaluation = regret.evaluate_s2_validation_dual_sets(
        manifest,
        primary_ids,
        repeat_passes=2,
        proposal_repeats=3,
    )

    assert [row["record_id"] for row in evaluation["paired_primary"]] == primary_ids
    assert [row["record_id"] for row in evaluation["s2_exploratory"]] == [
        "outside-s2-disagreement"
    ]
    counts = evaluation["universe_counts"]
    assert counts["useful_prompt_count"] == 1148
    assert counts["out_of_primary_s2_override_prompt_count"] == 2
    assert counts["out_of_primary_s2_override_expert_equivalent_count"] == 1
    assert counts["out_of_primary_s2_override_disagreement_count"] == 1

    def fake_aggregate(result_rows, **_kwargs):
        episode_count = len({row.get("episode_id") for row in result_rows})
        return {
            "episode_count": episode_count,
            "decision_count": len(result_rows),
            "classification_counts": {label: 0 for label in regret.CLASSIFICATIONS},
            "decision_rates": {label: 0.0 for label in regret.CLASSIFICATIONS},
            "episode_rates": {label: 0.0 for label in regret.CLASSIFICATIONS},
            "episode_bootstrap_95": {label: [0.0, 0.0] for label in regret.CLASSIFICATIONS},
            "expert_dominates_rate": 0.0,
            "agent_dominates_rate": 0.0,
        }

    monkeypatch.setattr(regret, "aggregate_results", fake_aggregate)
    baseline = {
        "_paired_record_ids": primary_ids,
        "paired_record_id_sequence_sha256": regret._object_sha256(primary_ids),
    }
    output = regret.build_s2_validation_output(
        manifest,
        evaluation,
        bootstrap_samples=regret.FROZEN_SEALED_PARAMETERS["bootstrap_samples"],
        seed=regret.FROZEN_SEALED_PARAMETERS["sample_seed"],
        baseline=baseline,
        candidate={"variant": "s2"},
    )
    assert output["aggregate_alias"] == "evaluation_sets.paired_primary.aggregate"
    assert output["aggregate"] == output["evaluation_sets"]["paired_primary"]["aggregate"]
    assert output["evaluation_sets"]["s2_exploratory"]["safety_veto_only"] is True
    assert output["evaluation_sets"]["s2_exploratory"]["eligible_for_efficacy_rate"] is False
    assert "combined_rate" not in output
    assert output["combined_rate_permitted"] is False


def test_dual_set_exploratory_hard_ceiling_fails_closed(monkeypatch):
    primary_ids, rows, manifest, replay_cache = _dual_set_fixture()
    extra = copy.deepcopy(rows[-3])
    extra["record_id"] = "outside-s2-disagreement-2"
    rows.append(extra)
    monkeypatch.setattr(
        regret,
        "_collect_manifest_candidates",
        lambda *_args, **_kwargs: (rows, replay_cache, manifest["episodes"]),
    )

    with pytest.raises(regret.RegretError, match="ceiling"):
        regret.evaluate_s2_validation_dual_sets(
            manifest,
            primary_ids,
            repeat_passes=2,
            proposal_repeats=3,
            exploratory_hard_ceiling=1,
        )


def test_qualification_verifier_is_disabled_until_canonical_file_exists():
    assert regret.DEFAULT_S2_QUALIFICATION == (
        regret.ROOT / "data/dipplin_replay_eval/frozen/s2_qualification.json"
    )
    assert not regret.DEFAULT_S2_QUALIFICATION.exists()
    with pytest.raises(regret.RegretError, match="absent|disabled"):
        regret.verify_s2_qualification()


def test_qualification_verifier_binds_validation_package_and_evaluator(tmp_path: Path, monkeypatch):
    validation_path = tmp_path / "validation_regret_s2.json"
    frozen_s1 = regret.verify_frozen_s1_provenance()
    validation = {
        "schema": regret.SCHEMA,
        "split": "VALIDATION",
        "sealed": False,
        "candidate_variant": "s2",
        "baseline_incumbent_s1": {
            "validation_result_sha256": regret.PINNED_S1_VALIDATION_OUTPUT_SHA256,
        },
        "evaluated_candidate": {
            "archive_sha256": regret.PINNED_S2_ARCHIVE_SHA256,
            "manifest_sha256": regret.PINNED_S2_MANIFEST_SHA256,
            "extracted_tree_sha256": regret.PINNED_S2_EXTRACTED_TREE_SHA256,
            "runtime_source_tree_sha256": regret.PINNED_S2_RUNTIME_TREE_SHA256,
        },
        "run_contract": {
            "evaluator": regret._evaluator_provenance(),
            "parameters": regret.FROZEN_SEALED_PARAMETERS,
            "validation_manifest_file_sha256": regret.PINNED_MANIFESTS["VALIDATION"][
                "file_sha256"
            ],
            "validation_manifest_payload_sha256": regret.PINNED_MANIFESTS["VALIDATION"][
                "payload_sha256"
            ],
        },
        "aggregate_alias": "evaluation_sets.paired_primary.aggregate",
        "aggregate": {"decision_count": regret.PINNED_S1_PRIMARY_RECORD_COUNT},
        "evaluation_sets": {
            "paired_primary": {
                "aggregate": {"decision_count": regret.PINNED_S1_PRIMARY_RECORD_COUNT},
                "decision_rows": [
                    {"record_id": record_id}
                    for record_id in frozen_s1["_paired_record_ids"]
                ],
            },
            "s2_exploratory": {
                "safety_veto_only": True,
                "eligible_for_efficacy_rate": False,
                "decision_rows": [],
            },
        },
        "universe_counts": {
            "s2_exploratory_record_count": 0,
            "out_of_primary_s2_override_disagreement_count": 0,
        },
        "combined_rate_permitted": False,
    }
    validation_path.write_text(json.dumps(validation, sort_keys=True), encoding="utf-8")
    evaluator = Path(regret.__file__).resolve()
    qualification_path = tmp_path / "s2_qualification.json"
    qualification = {
        "schema": regret.QUALIFICATION_SCHEMA,
        "status": "QUALIFIED",
        "candidate": "s2",
        "qualification_rule": "paired_primary_with_exploratory_safety_veto_v1",
        "baseline_s1_validation_sha256": regret.PINNED_S1_VALIDATION_OUTPUT_SHA256,
        "candidate_validation": {
            "path": str(validation_path.resolve()),
            "sha256": regret._sha256(validation_path),
        },
        "candidate_package": {
            "archive_sha256": regret.PINNED_S2_ARCHIVE_SHA256,
            "manifest_sha256": regret.PINNED_S2_MANIFEST_SHA256,
            "extracted_tree_sha256": regret.PINNED_S2_EXTRACTED_TREE_SHA256,
            "runtime_source_tree_sha256": regret.PINNED_S2_RUNTIME_TREE_SHA256,
        },
        "evaluator": {
            "path": str(evaluator.relative_to(regret.ROOT)),
            "sha256": regret._sha256(evaluator),
            "git_blob_sha1": regret._git_blob_sha1(evaluator),
        },
    }
    qualification["qualification_payload_sha256"] = regret._qualification_payload_sha256(
        qualification
    )
    qualification_path.write_text(json.dumps(qualification, sort_keys=True), encoding="utf-8")
    monkeypatch.setattr(regret, "DEFAULT_S2_QUALIFICATION", qualification_path)
    monkeypatch.setattr(regret, "DEFAULT_S2_VALIDATION_OUTPUT", validation_path)
    monkeypatch.setattr(regret, "QUALIFIED_S2_VALIDATION_PATH", str(validation_path.resolve()))

    verified = regret.verify_s2_qualification(qualification_path)

    assert verified["status"] == "QUALIFIED"
    assert verified["file_sha256"] == regret._sha256(qualification_path)
    assert verified["candidate_validation_sha256"] == regret._sha256(validation_path)
