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
    replay_path = tmp_path / "episode-7001-replay.json"
    replay_path.write_text(json.dumps({"id": 7001, "steps": []}), encoding="utf-8")
    replay_sha256 = hashlib.sha256(replay_path.read_bytes()).hexdigest()
    split = "FINAL_HOLDOUT" if sealed else "VALIDATION"
    payload = {
        "schema_version": 1,
        "dataset": "dipplin_replay_eval",
        "split": split,
        "sealed": sealed,
        "episode_count": 1,
        "inspection_policy": {
            "metadata_only": True,
            "action_level_inspected": False,
            "replay_regret_executed": False,
            "individual_failure_inspection_permitted": not sealed,
        },
        "selection_provenance": {"selection_used_outcome": False},
        "provenance": {},
        "episodes": [
            {
                "episode_id": 7001,
                "replay_cache_path": str(replay_path),
                "replay_sha256": replay_sha256,
                "first_player_seat": 0,
                "expert_result": "win",
                "selection_contract_verified": True,
                "hero": {"seat": 0, "actual_order": "first"},
                "opponent": {"archetype": "Garchomp"},
            }
        ],
    }
    signed = add_manifest_digest(payload)
    manifest_path = tmp_path / f"{split.casefold()}_manifest.json"
    manifest_path.write_text(json.dumps(signed), encoding="utf-8")
    return manifest_path, signed


def test_load_manifest_verifies_digest_replay_hash_and_sealed_contract(tmp_path: Path):
    path, signed = frozen_manifest(tmp_path)
    loaded = regret.load_manifest(path)
    assert loaded["split"] == "VALIDATION"
    assert loaded["episodes"][0]["episode_id"] == 7001

    tampered = copy.deepcopy(signed)
    tampered["episodes"][0]["expert_result"] = "loss"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(regret.RegretError, match="digest"):
        regret.load_manifest(path)

    path, signed = frozen_manifest(tmp_path / "wrong-hash")
    unsigned = {key: value for key, value in signed.items() if key != "manifest_payload_sha256"}
    unsigned["episodes"][0]["replay_sha256"] = "0" * 64
    path.write_text(json.dumps(add_manifest_digest(unsigned)), encoding="utf-8")
    with pytest.raises(regret.RegretError, match="replay.*sha|hash"):
        regret.load_manifest(path)


def test_load_manifest_rejects_a_final_holdout_that_is_not_sealed(tmp_path: Path):
    path, signed = frozen_manifest(tmp_path, sealed=True)
    unsigned = {key: value for key, value in signed.items() if key != "manifest_payload_sha256"}
    unsigned["sealed"] = False
    path.write_text(json.dumps(add_manifest_digest(unsigned)), encoding="utf-8")
    with pytest.raises(regret.RegretError, match="sealed|FINAL_HOLDOUT"):
        regret.load_manifest(path)


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

    assert priority >= 55


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


def test_chronological_s1_forces_frozen_search_and_opening_configuration():
    policy = regret.ChronologicalS1()

    assert policy.planner.go_first is True
    assert policy.planner.second_opening_v2 is True
    assert policy.planner.resolver.second_opening_v2 is True
    assert policy.planner.route_v2_enabled is False
    assert policy.search.config.worlds == 2


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
