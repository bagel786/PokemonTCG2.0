import gzip
import json
from types import SimpleNamespace

import scripts.mine_complete_turn_disagreements as miner
from scripts.mine_complete_turn_disagreements import (
    DEFAULT_MODEL,
    certification_signature,
    correction_output_row,
    decision_key,
    model_behavior_digest,
    row_priority,
    select_unique_corrections,
    select_rows,
    stable_key,
    stable_shard,
)


def row(name, *, split="development", outcome="win", order="first", proposers=()):
    return {
        "record_id": name,
        "episode_id": f"episode-{name}",
        "hero_seat": 0,
        "replay_step_t": 1,
        "observation_sha256": f"observation-{name}",
        "baseline_semantic_id": "baseline",
        "candidate_semantic_id": f"candidate-{name}",
        "split": split,
        "outcome": outcome,
        "actual_order": order,
        "proposers": list(proposers),
    }


def test_selection_refuses_holdout_and_is_deterministic_and_unique():
    rows = [row(str(index), outcome="loss" if index % 2 else "win") for index in range(20)]
    rows.append(dict(rows[0]))
    first = select_rows(
        rows,
        allowed_splits={"development"},
        shard_index=0,
        shard_count=2,
        max_records=5,
    )
    second = select_rows(
        reversed(rows),
        allowed_splits={"development"},
        shard_index=0,
        shard_count=2,
        max_records=5,
    )
    assert [stable_key(item) for item in first] == [stable_key(item) for item in second]
    assert len({stable_key(item) for item in first}) == len(first)

    try:
        select_rows(rows, allowed_splits={"untouched_holdout"}, shard_index=0, shard_count=1, max_records=0)
    except ValueError as exc:
        assert "holdout" in str(exc)
    else:
        raise AssertionError("untouched holdout was accepted")


def test_shards_partition_keys_and_priority_favors_second_losses_and_consensus():
    keys = [str(index) for index in range(100)]
    partitions = [{key for key in keys if stable_shard(key, 4) == shard} for shard in range(4)]
    assert set.union(*partitions) == set(keys)
    assert sum(map(len, partitions)) == len(keys)
    preferred = row("preferred", outcome="loss", order="second", proposers=("a", "b"))
    ordinary = row("ordinary", outcome="win", order="first", proposers=("a",))
    assert row_priority(preferred) < row_priority(ordinary)


def test_correction_row_records_complete_coverage_and_no_hidden_deck():
    source = {
        "episode_id": "1",
        "hero_seat": 1,
        "replay_step_t": 5,
        "candidate_action": [2],
        "features": {"feature_version": 2},
        "observation": {"select": {}},
        "split": "development",
        "actual_order": "second",
        "opponent_matchup": "mirror",
        "opponent_deck_canonical_sha256": "ABC",
        "semantic_pair_id": "PAIR",
        "semantic_action_pair_id": "GLOBAL-PAIR",
        "record_id": "RECORD",
        "candidate_semantic_id": "C",
        "baseline_semantic_id": "B",
        "proposers": ["tempo"],
        "target": 0,
    }
    worlds = [
        {
            "world_index": index,
            "seed": index,
            "baseline": [0] * 7,
            "candidate": [0, 1, 0, 0, 0, 0, 0],
            "lexicographic_comparison": 1,
            "baseline_steps": 2,
            "candidate_steps": 2,
        }
        for index in range(8)
    ]
    result = {
        "admitted": True,
        "worlds": worlds,
        "coverage": {"baseline": 8, "candidate": 8},
        "decision": {
            "admitted": True,
            "reason": "admitted",
            "expected_worlds": 8,
            "covered_worlds": 8,
            "noninferior_worlds": 8,
            "strict_better_worlds": 8,
            "required_strict_worlds": 4,
        },
        "boundary_hash": "BOUNDARY",
        "errors": [],
        "repeat_count": 3,
        "repeat_signature": "REPEAT-SIGNATURE",
        "repeat_signatures": ["REPEAT-SIGNATURE"] * 3,
    }
    output = correction_output_row(source, result, "D842", "BEHAVIOR")
    assert output["correction"]["coverage_complete"] is True
    assert output["correction"]["all_worlds_nonnegative"] is True
    assert output["correction"]["strict_better_worlds"] == 8
    assert output["correction"]["anchor_sha256"] == "D842"
    assert output["correction"]["anchor_behavior_sha256"] == "BEHAVIOR"
    assert output["correction"]["certification_repeat_count"] == 3
    assert output["correction"]["certification_signature"] == "REPEAT-SIGNATURE"
    assert output["correction"]["decision"]["admitted"] is True
    assert len(output["correction"]["worlds"]) == 8
    assert output["correction_record_id"] == "RECORD"
    assert output["semantic_pair_id"] == "PAIR"
    assert output["semantic_action_pair_id"] == "GLOBAL-PAIR"
    serialized = json.dumps(output).lower()
    assert "opponent_deck" not in serialized
    assert "opponent_matchup" not in serialized
    assert "opponent_archetype" not in serialized
    from training.train_correction_only import _certification_kind

    assert _certification_kind(
        output,
        anchor_file_sha256="D842",
        anchor_behavior_sha256="BEHAVIOR",
    ) == "complete_turn_v1"


def test_state_bound_keys_do_not_collapse_global_action_pairs_and_one_label_is_selected():
    first = {
        **row("record-a"),
        "episode_id": "a",
        "hero_seat": 0,
        "replay_step_t": 7,
        "observation_sha256": "OBS-A",
        "candidate_semantic_id": "C1",
    }
    second = {
        **first,
        "record_id": "record-b",
        "episode_id": "b",
        "observation_sha256": "OBS-B",
    }
    assert stable_key(first) != stable_key(second)
    assert decision_key(first) != decision_key(second)

    alternative = {**first, "record_id": "record-c", "candidate_semantic_id": "C2", "proposers": ["a", "b"]}
    base_result = {
        "admitted": True,
        "decision": {"strict_better_worlds": 4},
        "worlds": [{"candidate": [0, 1, 0, 0, 0, 0, 0]} for _ in range(8)],
    }
    stronger = {
        **base_result,
        "decision": {"strict_better_worlds": 8},
        "worlds": [{"candidate": [0, 2, 0, 0, 0, 0, 0]} for _ in range(8)],
    }
    selected, ambiguous = select_unique_corrections([(first, base_result), (alternative, stronger)])
    assert ambiguous == 1
    assert selected == [(alternative, stronger)]


def test_decision_candidates_are_shard_and_limit_atomic():
    first = row("candidate-a")
    second = {
        **row("candidate-b"),
        "episode_id": first["episode_id"],
        "hero_seat": first["hero_seat"],
        "replay_step_t": first["replay_step_t"],
        "observation_sha256": first["observation_sha256"],
    }
    shard = stable_shard(decision_key(first), 5)
    assert stable_shard(decision_key(second), 5) == shard
    selected = select_rows(
        [first, second],
        allowed_splits={"development"},
        shard_index=shard,
        shard_count=5,
        max_records=1,
    )
    assert selected == []
    selected = select_rows(
        [first, second],
        allowed_splits={"development"},
        shard_index=shard,
        shard_count=5,
        max_records=2,
    )
    assert {stable_key(item) for item in selected} == {stable_key(first), stable_key(second)}


def test_conflicting_duplicate_record_is_rejected():
    first = row("duplicate")
    conflict = {**first, "candidate_action": [7]}
    try:
        select_rows(
            [first, conflict],
            allowed_splits={"development"},
            shard_index=0,
            shard_count=1,
            max_records=0,
        )
    except ValueError as exc:
        assert "conflicting duplicate" in str(exc)
    else:
        raise AssertionError("conflicting duplicate record was silently accepted")


class _Vector:
    def __init__(self, value):
        self.value = value

    def values(self):
        return (self.value, 0, 0, 0, 0, 0, 0)


def _fake_evaluation(value):
    decision = {
        "admitted": True,
        "reason": "admitted",
        "expected_worlds": 8,
        "covered_worlds": 8,
        "noninferior_worlds": 8,
        "strict_better_worlds": 8,
        "required_strict_worlds": 4,
    }
    worlds = tuple(
        SimpleNamespace(
            world_index=index,
            seed=index,
            baseline=_Vector(0),
            candidate=_Vector(value),
            baseline_steps=2,
            candidate_steps=2,
        )
        for index in range(8)
    )
    return SimpleNamespace(
        admitted=True,
        reason="admitted",
        boundary_hash="BOUNDARY",
        coverage={"baseline": 8, "candidate": 8},
        worlds=worlds,
        errors=(),
        to_dict=lambda: {
            "baseline_action": {"options": ["baseline"]},
            "candidate_action": {"options": ["candidate"]},
            "decision": decision,
        },
    )


def test_identical_repeat_signatures_are_required(monkeypatch):
    monkeypatch.setattr(miner, "_WORKER_MODEL", object())
    monkeypatch.setattr(miner, "_WORKER_CONFIG", object())
    monkeypatch.setattr(miner, "_WORKER_HERO_DECK", tuple(range(60)))
    monkeypatch.setattr(miner, "_WORKER_REPEATS", 3)
    monkeypatch.setattr(miner, "to_observation_class", lambda _raw: object())
    monkeypatch.setattr(miner, "d842_action", lambda _model, _obs: [0])
    calls = iter((_fake_evaluation(1), _fake_evaluation(2), _fake_evaluation(1)))
    monkeypatch.setattr(miner, "evaluate_complete_turn_correction", lambda *_args, **_kwargs: next(calls))
    source = {
        **row("repeat"),
        "observation": {},
        "baseline_action": [0],
        "candidate_action": [1],
        "opponent_deck": list(range(60)),
    }
    result = miner.evaluate_row(source)
    assert result["admitted"] is False
    assert result["reason"] == "nondeterministic_repeats"
    assert len(set(result["repeat_signatures"])) == 2

    stable = _fake_evaluation(1)
    monkeypatch.setattr(
        miner,
        "evaluate_complete_turn_correction",
        lambda *_args, **_kwargs: stable,
    )
    result = miner.evaluate_row(source)
    assert result["admitted"] is True
    assert result["repeat_count"] == 3
    assert len(set(result["repeat_signatures"])) == 1
    assert result["repeat_signature"] == certification_signature(miner._evaluation_payload(stable))


def test_behavior_digest_matches_trainer_contract_and_gzip_is_deterministic(tmp_path):
    from training.train_correction_only import model_behavior_digest as trainer_digest

    assert model_behavior_digest(DEFAULT_MODEL) == trainer_digest(DEFAULT_MODEL)
    payload = json.dumps({"z": 1, "a": [2, 3]}, sort_keys=True, separators=(",", ":")) + "\n"
    outputs = []
    for name in ("a.jsonl.gz", "b.jsonl.gz"):
        path = tmp_path / name
        with miner.deterministic_gzip_text(path) as handle:
            handle.write(payload)
        outputs.append(path.read_bytes())
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            assert handle.read() == payload
    assert outputs[0] == outputs[1]
