import gzip
import json

import pytest

from scripts.build_schema5_breakthrough_corpus import chronological_split, episode_balance, read_rows


def test_newest_twenty_percent_is_whole_episode_holdout():
    rows = [
        {"episode_id": str(episode), "seat": 0, "step": step}
        for episode in range(10)
        for step in range(3)
    ]
    train, holdout = chronological_split(rows)
    train_episodes = {row["episode_id"] for row in train}
    holdout_episodes = {row["episode_id"] for row in holdout}
    assert train_episodes.isdisjoint(holdout_episodes)
    assert holdout_episodes == {"8", "9"}


def test_episode_balancing_prevents_long_game_dominance():
    rows = [
        *({"episode_id": "short", "seat": 0, "step": index} for index in range(2)),
        *({"episode_id": "long", "seat": 0, "step": index} for index in range(8)),
    ]
    balanced = episode_balance(rows)
    totals = {
        episode: sum(row["sample_weight"] for row in balanced if row["episode_id"] == episode)
        for episode in ("short", "long")
    }
    assert totals["short"] == pytest.approx(totals["long"])


def test_schema4_rows_fail_closed(tmp_path):
    path = tmp_path / "rows.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps({"features": {"feature_version": 4}}) + "\n")
    with pytest.raises(ValueError, match="non-schema-5"):
        list(read_rows(path))
