from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from scripts import build_temporal_order_subsets as subsets


def _row(episode: str, seat: int, step: int, first_flag: int, turn: float, context: int) -> dict:
    return {
        "episode_id": episode,
        "seat": seat,
        "step": step,
        "split": "train",
        "features": {
            "feature_version": 3,
            "global": [turn, 0.0, float(seat), float(first_flag)],
            "tokens": [0],
            "options": [{
                "option_type": 1,
                "context": context,
                "source_card": 0,
                "target_card": 0,
                "attack_id": 0,
                "area": 0,
                "in_play_area": 0,
                "numeric": [0.0] * 13,
            }],
        },
        "action": [0],
        "deck": [7] * 60,
        "reward": 1.0,
    }


def _write(path: Path, rows: list[dict]) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def test_scan_assigns_whole_units_and_documents_only_prelatch_zero(tmp_path: Path):
    path = tmp_path / "rows.jsonl.gz"
    rows = [
        _row("first", 1, 0, 0, 0.0, subsets.IS_FIRST_CONTEXT),
        _row("first", 1, 1, 1, 0.0, 2),
        _row("first", 1, 2, 1, 0.01, 0),
        _row("second", 0, 0, 0, 0.0, 2),
        _row("second", 0, 1, 0, 0.01, 0),
    ]
    _write(path, rows)
    orders, audit, coordinates = subsets.scan_source(path, "train")

    assert orders == {("first", 1): "first", ("second", 0): "second"}
    assert audit["first_rows"] == 3
    assert audit["second_rows"] == 2
    assert audit["pre_latch_rows"] == 1
    assert audit["pre_latch_contexts"] == {"41": 1}
    assert audit["source_seat_matches_encoded_your_index"] == 5
    assert len(coordinates) == 5

    first = tmp_path / "first.jsonl.gz"
    second = tmp_path / "second.jsonl.gz"
    output = subsets.write_subsets(path, orders, {"first": first, "second": second})
    assert output["first"]["rows"] == 3
    assert output["second"]["rows"] == 2
    with gzip.open(first, "rt", encoding="utf-8") as handle:
        written = [json.loads(line) for line in handle]
    assert {row["actual_order"] for row in written} == {"first"}
    assert all(row["actual_order_assignment"].startswith("whole_episode_seat") for row in written)


def test_scan_rejects_source_seat_mismatch(tmp_path: Path):
    path = tmp_path / "bad-seat.jsonl.gz"
    row = _row("episode", 0, 0, 0, 0.01, 0)
    row["features"]["global"][2] = 1.0
    _write(path, [row])
    with pytest.raises(subsets.SubsetError, match="source seat/encoded yourIndex mismatch"):
        subsets.scan_source(path, "train")


def test_scan_rejects_non_prelatch_zero_in_first_unit(tmp_path: Path):
    path = tmp_path / "bad-zero.jsonl.gz"
    _write(path, [
        _row("episode", 0, 0, 0, 0.0, 2),
        _row("episode", 0, 1, 1, 0.01, 0),
    ])
    with pytest.raises(subsets.SubsetError, match="non-pre-latch zero"):
        subsets.scan_source(path, "train")


def test_scan_rejects_unlatched_second_only_unit(tmp_path: Path):
    path = tmp_path / "unlatched.jsonl.gz"
    _write(path, [_row("episode", 0, 0, 0, 0.0, 2)])
    with pytest.raises(subsets.SubsetError, match="no post-latch turn evidence"):
        subsets.scan_source(path, "train")
