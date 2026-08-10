from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_grim_policy_disagreements.py"
SPEC = importlib.util.spec_from_file_location("build_grim_policy_disagreements", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


DECK = [
    7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
    104, 104, 112, 112, 112, 112,
    646, 646, 646, 646, 647, 647, 647, 648, 648, 648,
    860, 860, 1079, 1079, 1079, 1080,
    1086, 1086, 1086, 1086, 1097, 1097, 1097, 1122,
    1137, 1152, 1152, 1152, 1152, 1182, 1182,
    1219, 1219, 1219, 1219, 1227, 1227, 1227, 1227,
    1231, 1259, 1259, 1259, 1259,
]
assert len(DECK) == 60
assert mod.deck_hash(DECK) == mod.FROZEN_DECK_CANONICAL_SHA256


class FakePolicy:
    def __init__(self, name, decision):
        self.name = name
        self.decision = decision
        self.metadata = {"name": name, "fake": True}
        self.calls = []
        self.resets = 0

    def act(self, observation):
        if observation.get("select") is None:
            self.resets += 1
            self.calls.append("handshake")
            return list(DECK)
        self.calls.append(observation["marker"])
        return list(self.decision(observation) if callable(self.decision) else self.decision)

    def features(self, observation):
        return {"marker": observation["marker"], "feature_version": 2}


def card(card_id, serial, *, hp=None):
    value = {"id": card_id, "serial": serial, "playerIndex": 0}
    if hp is not None:
        value.update({
            "hp": hp,
            "maxHp": hp,
            "appearThisTurn": False,
            "energies": [],
            "energyCards": [],
            "tools": [],
            "preEvolution": [],
        })
    return value


def decision_observation(marker="decision-1"):
    return {
        "marker": marker,
        "current": {
            "yourIndex": 0,
            "firstPlayer": 0,
            "turn": 1,
            "players": [
                {
                    "hand": [card(100, 1), card(200, 2), card(200, 3)],
                    "discard": [],
                    "active": [card(646, 5, hp=70)],
                    "bench": [],
                    "prize": [None] * 6,
                },
                {"hand": None, "discard": [], "active": [], "bench": [], "prize": [None] * 6},
            ],
            "stadium": [],
            "looking": [],
        },
        "select": {
            "type": 0,
            "context": 0,
            "minCount": 1,
            "maxCount": 1,
            "option": [
                {"type": 7, "index": 0},
                {"type": 7, "index": 1},
                {"type": 7, "index": 2},
            ],
            "deck": None,
            "contextCard": None,
            "effect": None,
        },
    }


def fake_replay():
    handshake = {"select": None, "current": {"yourIndex": 0}}
    idle = {"select": None, "current": {"yourIndex": 1}}
    return {
        "steps": [
            [
                {"status": "ACTIVE", "action": [], "observation": handshake},
                {"status": "ACTIVE", "action": [], "observation": idle},
            ],
            [
                {"status": "ACTIVE", "action": list(DECK), "observation": decision_observation()},
                {"status": "INACTIVE", "action": list(reversed(DECK)), "observation": idle},
            ],
            [
                {"status": "DONE", "action": [0], "observation": decision_observation("after")},
                {"status": "DONE", "action": [], "observation": idle},
            ],
        ]
    }


def fake_episode(split="development"):
    return {
        "split": split,
        "episode_id": "42",
        "submission_id": 55323437,
        "hero_seat": 0,
        "actual_order": "first",
        "opponent_matchup": "other",
        "outcome": "win",
        "target": 1,
        "opponent_deck_canonical_sha256": mod.deck_hash(list(reversed(DECK))),
    }


def test_observation_t_uses_action_t_plus_1_and_groups_semantic_proposers():
    baseline = FakePolicy("d842", [0])
    candidate_a = FakePolicy("a", [1])
    candidate_b = FakePolicy("b", [2])  # duplicate card: different index, same semantic action

    rows, metrics = mod.mine_episode(
        fake_episode(), fake_replay(), baseline, [candidate_b, candidate_a]
    )

    assert metrics["decisions"] == 1
    assert len(rows) == 1
    row = rows[0]
    assert row["replay_step_t"] == 1
    assert row["historical_action_step_t_plus_1"] == 2
    assert row["historical_action"] == [0]
    assert row["historical_agrees_with_baseline"] is True
    assert row["observation"]["marker"] == "decision-1"
    assert row["features"] == {"marker": "decision-1", "feature_version": 2}
    assert row["proposers"] == ["a", "b"]
    assert row["proposer_actions"] == {"a": [1], "b": [2]}
    assert row["candidate_semantic"]["options"][0]["source"]["card_id"] == 200
    assert row["record_id"]
    assert row["semantic_pair_id"]
    assert row["semantic_action_pair_id"]
    assert row["semantic_pair_id"] != row["semantic_action_pair_id"]
    assert baseline.calls == ["handshake", "decision-1"]
    assert candidate_a.resets == candidate_b.resets == 1


def test_semantic_identity_ignores_option_and_hand_positions():
    obs_a = decision_observation()
    obs_b = decision_observation()
    obs_b["current"]["players"][0]["hand"] = [card(200, 99), card(100, 88)]
    obs_b["select"]["option"] = [{"type": 7, "index": 0}, {"type": 7, "index": 1}]

    semantic_a = mod.semantic_action(obs_a, [1])
    semantic_b = mod.semantic_action(obs_b, [0])

    assert semantic_a == semantic_b
    encoded = json.dumps(semantic_a, sort_keys=True)
    assert '"index"' not in encoded
    assert '"serial"' not in encoded


def test_record_id_keeps_same_semantic_pair_distinct_across_episodes():
    baseline = FakePolicy("d842", [0])
    candidate = FakePolicy("a", [1])
    first, _ = mod.mine_episode(fake_episode(), fake_replay(), baseline, [candidate])
    other_episode = fake_episode()
    other_episode["episode_id"] = "43"
    second, _ = mod.mine_episode(other_episode, fake_replay(), baseline, [candidate])

    assert first[0]["semantic_action_pair_id"] == second[0]["semantic_action_pair_id"]
    assert first[0]["semantic_pair_id"] == second[0]["semantic_pair_id"]
    assert first[0]["record_id"] != second[0]["record_id"]


def test_invalid_policy_action_fails_closed():
    baseline = FakePolicy("d842", [0])
    bad = FakePolicy("bad", [999])
    with pytest.raises(ValueError, match="invalid option index"):
        mod.mine_episode(fake_episode(), fake_replay(), baseline, [bad])


def test_holdout_is_hard_refused(tmp_path):
    with pytest.raises(ValueError, match="hard-protected"):
        mod.load_split_rows(tmp_path, ["untouched_holdout"])

    baseline = FakePolicy("d842", [0])
    with pytest.raises(ValueError, match="refusing protected"):
        mod.build_bank(
            [fake_episode("untouched_holdout")],
            tmp_path,
            tmp_path / "out.jsonl.gz",
            baseline,
            [],
        )


def test_deterministic_gzip_has_identical_bytes(tmp_path):
    rows = [{"z": 1, "a": [3, 2, 1]}, {"unicode": "Pokémon"}]
    first = tmp_path / "first.jsonl.gz"
    second = tmp_path / "second.jsonl.gz"

    first_sha = mod.deterministic_gzip_jsonl(first, rows)
    second_sha = mod.deterministic_gzip_jsonl(second, rows)

    assert first.read_bytes() == second.read_bytes()
    assert first_sha == second_sha == hashlib.sha256(first.read_bytes()).hexdigest().upper()
    with gzip.open(first, "rt", encoding="utf-8") as handle:
        assert [json.loads(line) for line in handle] == rows


def test_complete_fake_build_is_byte_deterministic(tmp_path):
    replay_root = tmp_path / "replays"
    replay_root.mkdir()
    replay_path = replay_root / "episode.json"
    replay_path.write_text(json.dumps(fake_replay()), encoding="utf-8")
    episode = fake_episode()
    episode.update({
        "replay_path": replay_path.name,
        "replay_sha256": mod.sha256_file(replay_path),
    })
    baseline = FakePolicy("d842", [0])
    candidates = [FakePolicy("a", [1]), FakePolicy("b", [2])]
    output = tmp_path / "output" / "disagreements.jsonl.gz"

    first = mod.build_bank(episode_rows=[episode], replay_root=replay_root, output_path=output,
                           baseline=baseline, candidates=candidates)
    first_bytes = output.read_bytes()
    second = mod.build_bank(episode_rows=[episode], replay_root=replay_root, output_path=output,
                            baseline=baseline, candidates=candidates)

    assert output.read_bytes() == first_bytes
    assert first["output_sha256"] == second["output_sha256"]
    assert first["historical_exact_agreement"] == second["historical_exact_agreement"] == 1


def test_direct_holdout_row_in_development_shard_is_rejected(tmp_path):
    bank = tmp_path / "bank"
    bank.mkdir()
    row = fake_episode("untouched_holdout")
    row.update({
        "frozen_model_sha256": mod.FROZEN_MODEL_SHA256,
        "hero_deck_canonical_sha256": mod.FROZEN_DECK_CANONICAL_SHA256,
    })
    with gzip.open(bank / "development.jsonl.gz", "wt", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")

    with pytest.raises(ValueError, match="row split"):
        mod.load_split_rows(bank, ["development"])
