import gzip
import json
from pathlib import Path

import numpy as np
import pytest

from scripts.build_elite_refresh_data import (
    MetricBucket,
    assign_top20_episode_splits,
    build_elite_refresh,
    repair_weight_class,
    validate_row,
)
from training.lucario_data import deterministic_gzip_text, sha256_file


class FakeA2:
    feature_version = 2

    def predict(self, features):
        logits = np.arange(len(features.options), 0, -1, dtype=np.float32)
        return logits, np.zeros(8, dtype=np.float32), 0.0


def option():
    return {
        "option_type": 1,
        "context": 1,
        "source_card": 0,
        "target_card": 0,
        "attack_id": 0,
        "area": 0,
        "in_play_area": 0,
        "numeric": [],
    }


def decision(deck, *, episode, team, step=0, action=None):
    return {
        "episode_id": episode,
        "seat": 0,
        "step": step,
        "team": team,
        "reward": 1.0,
        "deck": list(deck),
        "action": [0] if action is None else action,
        "features": {
            "feature_version": 2,
            "global": [],
            "tokens": [],
            "options": [option(), option(), option(), option()],
        },
    }


def read_rows(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def test_repair_weights_match_the_three_specified_classes():
    ranked = [0, 1, 2, 3]
    assert repair_weight_class([0], ranked) == ("baseline_top1_correct", 0.5)
    assert repair_weight_class([2], ranked) == ("label_in_top3_not_top1", 3.0)
    assert repair_weight_class([3], ranked) == ("outside_top3_or_multi", 1.0)
    assert repair_weight_class([0, 1], ranked) == ("outside_top3_or_multi", 1.0)


def test_episode_split_is_exact_deterministic_and_order_independent():
    episodes = [f"episode-{index}" for index in range(11)]
    first = assign_top20_episode_splits(episodes, seed=17)
    second = assign_top20_episode_splits(reversed(episodes), seed=17)
    assert first == second
    assert list(first.values()).count("holdout") == 2
    assert list(first.values()).count("train") == 9


def test_metrics_report_the_eligible_four_option_slice():
    metrics = MetricBucket()
    metrics.update([0], [0, 1, 2, 3], 4)
    metrics.update([2], [0, 1, 2, 3], 4)
    metrics.update([0], [1, 0], 2)
    metrics.update([0, 1], [], 4)
    result = metrics.finalize()
    assert result["top1_rate"] == pytest.approx(1 / 3)
    assert result["top3_rate"] == 1.0
    assert result["eligible_options_ge4"] == {
        "single_action": 2,
        "top1_count": 1,
        "top3_count": 2,
        "top1_rate": 0.5,
        "top3_rate": 1.0,
    }


def test_exact_deck_and_feature_schema_fail_closed():
    deck = tuple([7] * 60)
    row = decision(deck, episode="one", team="Team001")
    validate_row(row, deck, line_number=1)
    row["deck"][0] = 8
    with pytest.raises(ValueError, match="exact Grim deck"):
        validate_row(row, deck, line_number=1)


def test_builder_outputs_deduplicated_weighted_and_reproducible_views(tmp_path):
    deck = tuple([7] * 60)
    deck_path = tmp_path / "deck.csv"
    deck_path.write_text("\n".join(map(str, deck)) + "\n", encoding="utf-8")
    ranks_path = tmp_path / "ranks.txt"
    ranks_path.write_text(
        "\n".join(f"Team{rank:03d}" for rank in range(1, 101)) + "\n",
        encoding="utf-8",
    )
    a2_path = tmp_path / "a2.npz"
    a2_path.write_bytes(b"test-only-fake-a2")
    input_path = tmp_path / "input.jsonl.gz"
    rows = [
        decision(deck, episode=f"top-{index}", team="Team001")
        for index in range(5)
    ]
    rows.extend([
        decision(deck, episode="rank21", team="Team021", step=0, action=[0]),
        decision(deck, episode="rank21", team="Team021", step=1, action=[1]),
        decision(deck, episode="rank21", team="Team021", step=2, action=[3]),
        decision(deck, episode="rank21", team="Team021", step=3, action=[0, 1]),
    ])
    rows.append(dict(rows[-1]))
    with deterministic_gzip_text(input_path) as handle:
        for row in rows:
            handle.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")

    output_dir = tmp_path / "out"
    arguments = dict(
        input_path=input_path,
        team_ranks_path=ranks_path,
        deck_path=deck_path,
        a2_path=a2_path,
        a2_archive_path=tmp_path / "absent.tar.gz",
        output_dir=output_dir,
        seed=9,
        verify_a2=False,
        model=FakeA2(),
    )
    manifest = build_elite_refresh(**arguments)

    assert manifest["counts"]["unique_selected_rows"] == 9
    assert manifest["counts"]["identical_duplicate_rows_skipped"] == 1
    assert manifest["outputs"]["rank1_20_identity_validation"]["rows"] == 5
    assert manifest["outputs"]["rank1_20_episode_train"]["rows"] == 4
    assert manifest["outputs"]["rank1_20_episode_holdout"]["rows"] == 1
    assert manifest["outputs"]["rank21_100_train"]["rows"] == 4
    assert manifest["outputs"]["rank1_100_episode_train_rehearsal"]["rows"] == 8
    assert manifest["outputs"]["rank1_100_episode_train_rehearsal"]["weight_sum"] == 5.0
    assert manifest["rules"]["rank21_100_rehearsal_multiplier"] == 0.25
    assert manifest["outputs"]["rank21_100_top3_repair_train"]["weight_sum"] == 5.5
    repair_rows = read_rows(output_dir / "rank21_100_top3_repair_train.jsonl.gz")
    assert [row["sample_weight"] for row in repair_rows] == [0.5, 3.0, 1.0, 1.0]

    first_hashes = {
        name: sha256_file(output_dir / row["path"].split("/")[-1])
        for name, row in manifest["outputs"].items()
    }
    second = build_elite_refresh(**arguments)
    assert {name: row["sha256"] for name, row in second["outputs"].items()} == first_hashes
    assert not set(second["top20_episode_split"]["train_episode_ids"]) & set(
        second["top20_episode_split"]["holdout_episode_ids"]
    )
