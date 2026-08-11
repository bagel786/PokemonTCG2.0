import gzip
import json
from pathlib import Path

import numpy as np
import pytest

from scripts.build_temporal_elite_schema3 import (
    DATES,
    build_temporal_elite_schema3,
    deck_digest,
    discover_local_lineage,
)
from training.lucario_data import deterministic_gzip_text, sha256_file


class FakeSchema3A2:
    feature_version = 3

    def predict(self, features):
        logits = np.arange(len(features.options), 0, -1, dtype=np.float32)
        return logits, np.zeros(10, dtype=np.float32), 0.0


def _option():
    return {
        "option_type": 1,
        "context": 0,
        "source_card": 0,
        "target_card": 0,
        "attack_id": 0,
        "area": 0,
        "in_play_area": 0,
        "numeric": [0.0] * 13,
    }


def _row(deck, *, date, episode, team, step=1, action=None, options=4, reward=1.0):
    return {
        "episode_id": episode,
        "seat": 0,
        "step": step,
        "team": team,
        "opponent_team": "opponent",
        "reward": reward,
        "outcome": "win" if reward > 0 else "loss",
        "deck": list(deck),
        "hero_deck_sha256": deck_digest(tuple(sorted(deck))),
        "action": [0] if action is None else action,
        "source": "kaggle_daily_complete",
        "source_date": date,
        "source_fingerprint": f"fingerprint-{episode}",
        "observation": {"large": "raw-only"},
        "features": {
            "feature_version": 3,
            "global": [0.0] * 118,
            "tokens": [0],
            "options": [_option() for _ in range(options)],
        },
    }


def _write_source(root: Path, date: str, rows: list[dict]) -> tuple[Path, Path]:
    shard = root / "shards" / f"{date}.jsonl.gz"
    manifest = root / "manifests" / f"{date}.json"
    shard.parent.mkdir(parents=True, exist_ok=True)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with deterministic_gzip_text(shard) as handle:
        for row in rows:
            handle.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")
    manifest.write_text(
        json.dumps({
            "status": "complete",
            "date": date,
            "feature_version": 3,
            "decision_count": len(rows),
            "output_sha256": sha256_file(shard),
            "archive_sha256": f"archive-{date}",
        }),
        encoding="utf-8",
    )
    return shard, manifest


def _fixture(tmp_path: Path):
    deck = tuple([7] * 60)
    deck_path = tmp_path / "deck.csv"
    deck_path.write_text("\n".join(map(str, deck)) + "\n", encoding="utf-8")
    ranking = tmp_path / "top100.txt"
    ranking.write_text("\n".join(f"Team{rank:03d}" for rank in range(1, 101)) + "\n", encoding="utf-8")
    a2 = tmp_path / "a2_schema2.npz"
    np.savez_compressed(
        a2,
        model_schema_version=np.asarray(2, dtype=np.int16),
        numeric_w=np.arange(24, dtype=np.float32).reshape(12, 2),
        marker=np.asarray([3.0], dtype=np.float32),
    )
    rows = {
        DATES[0]: [
            _row(deck, date=DATES[0], episode="train-a", team="Team002", step=1),
            _row(deck, date=DATES[0], episode="train-a", team="Team002", step=2),
            _row(deck, date=DATES[0], episode="excluded", team="Team001"),
            _row(deck, date=DATES[0], episode="loss", team="Team002", reward=0.0),
        ],
        DATES[1]: [
            _row(deck, date=DATES[1], episode="train-b", team="Team021", options=2),
        ],
        DATES[2]: [
            _row(deck, date=DATES[2], episode="hard", team="Team002", action=[0], options=4),
            _row(deck, date=DATES[2], episode="held", team="Team021", action=[1], options=2),
        ],
    }
    # An identical duplicate must be collapsed without dropping any unique step.
    rows[DATES[0]].append(dict(rows[DATES[0]][1]))
    source_root = tmp_path / "sources"
    sources = {date: _write_source(source_root, date, rows[date]) for date in DATES}
    return deck, deck_path, ranking, a2, rows, sources


def _read(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def test_temporal_builder_is_deduplicated_atomic_and_reproducible(tmp_path):
    _deck, deck_path, ranking, a2, _rows, sources = _fixture(tmp_path)
    output = tmp_path / "output"
    arguments = dict(
        sources=sources,
        ranking_path=ranking,
        deck_path=deck_path,
        a2_path=a2,
        output_dir=output,
        excluded_lineage={"Team001": {"basis": "test-local evidence"}},
        verify_frozen=False,
        model=FakeSchema3A2(),
    )
    first = build_temporal_elite_schema3(**arguments)
    first_hashes = {name: value["sha256"] for name, value in first["outputs"].items()}

    assert first["outputs"]["train"]["rows"] == 3
    assert first["outputs"]["holdout"]["rows"] == 2
    assert first["outputs"]["hard_holdout"]["rows"] == 1
    assert first["audit"]["selected_identical_duplicates_skipped"] == 1
    assert first["leakage"]["train_heldout_episode_overlap"] == []
    assert first["audit"]["whole_episode_seat_trajectories_verified"] is True
    assert first["inputs"]["a2_anchor"]["behavior_digest_equal"] is True

    train = _read(output / "train_winners_aug4_aug5_rank1_100.jsonl.gz")
    heldout = _read(output / "holdout_winners_aug6_rank1_100.jsonl.gz")
    hard = _read(output / "holdout_winners_aug6_rank1_20.jsonl.gz")
    assert {row["episode_id"] for row in train} == {"train-a", "train-b"}
    assert all(row["split"] == "train" and "observation" not in row for row in train)
    assert all(row["split"] == "temporal_holdout" for row in heldout)
    assert [row["episode_id"] for row in hard] == ["hard"]

    metrics = json.loads((output / "a2_holdout_metrics.json").read_text(encoding="utf-8"))
    overall = metrics["heldout_aug6_rank1_100"]["overall"]
    assert overall["single_index_top1"]["rate"] == 0.5
    assert overall["single_index_top3"]["rate"] == 1.0
    assert overall["single_meaningful_top3_options_ge4"]["total"] == 1
    assert set(metrics["heldout_aug6_rank1_100"]["by_option_count"]) == {"2", "4"}
    assert [row["aug4_rank"] for row in metrics["heldout_aug6_rank1_100"]["by_team"].values()] == [2, 21]

    second = build_temporal_elite_schema3(**arguments)
    assert {name: value["sha256"] for name, value in second["outputs"].items()} == first_hashes


@pytest.mark.parametrize("failure", ["schema", "deck"])
def test_schema_or_deck_mismatch_fails_closed(tmp_path, failure):
    deck, deck_path, ranking, a2, rows, _sources = _fixture(tmp_path)
    if failure == "schema":
        rows[DATES[0]][0]["features"]["feature_version"] = 2
    else:
        rows[DATES[0]][0]["deck"][0] = 8
    source_root = tmp_path / "bad-sources"
    sources = {date: _write_source(source_root, date, rows[date]) for date in DATES}
    with pytest.raises(ValueError, match="schema 3|deck mismatch"):
        build_temporal_elite_schema3(
            sources=sources,
            ranking_path=ranking,
            deck_path=deck_path,
            a2_path=a2,
            output_dir=tmp_path / "bad-output",
            verify_frozen=False,
            model=FakeSchema3A2(),
        )


def test_temporal_episode_overlap_fails_closed(tmp_path):
    _deck, deck_path, ranking, a2, rows, _sources = _fixture(tmp_path)
    rows[DATES[2]][0]["episode_id"] = "train-a"
    source_root = tmp_path / "overlap-sources"
    sources = {date: _write_source(source_root, date, rows[date]) for date in DATES}
    with pytest.raises(ValueError, match="episode overlap"):
        build_temporal_elite_schema3(
            sources=sources,
            ranking_path=ranking,
            deck_path=deck_path,
            a2_path=a2,
            output_dir=tmp_path / "overlap-output",
            verify_frozen=False,
            model=FakeSchema3A2(),
        )


def test_conflicting_duplicate_coordinate_fails_closed(tmp_path):
    _deck, deck_path, ranking, a2, rows, _sources = _fixture(tmp_path)
    conflict = dict(rows[DATES[0]][0])
    conflict["action"] = [1]
    rows[DATES[0]].append(conflict)
    source_root = tmp_path / "conflict-sources"
    sources = {date: _write_source(source_root, date, rows[date]) for date in DATES}
    with pytest.raises(ValueError, match="conflicting duplicate"):
        build_temporal_elite_schema3(
            sources=sources,
            ranking_path=ranking,
            deck_path=deck_path,
            a2_path=a2,
            output_dir=tmp_path / "conflict-output",
            verify_frozen=False,
            model=FakeSchema3A2(),
        )


def test_local_lineage_is_evidence_backed_not_guessed():
    lineage = discover_local_lineage()
    assert "Larps" in lineage
    assert lineage["Larps"]["leaderboard_rank"] == 585
    assert lineage["Larps"]["local_label_source_sha256"]
