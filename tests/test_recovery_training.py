import gzip
import json
from collections import deque

from training.lucario_data import deterministic_gzip_text
from training.mine_recovery_corrections import select_stratified_recent
from training.train_recovery_candidates import assemble_family_data


def _row(episode_id: str, reward: float = 1.0) -> dict:
    return {
        "episode_id": episode_id,
        "seat": 0,
        "step": 0,
        "reward": reward,
        "features": {"feature_version": 3},
        "observation": {"large": [1, 2, 3]},
    }


def test_recovery_assembly_retains_only_most_recent_winners(tmp_path):
    corrected = tmp_path / "train.jsonl.gz"
    with deterministic_gzip_text(corrected) as handle:
        for episode_id in ("old", "middle", "recent"):
            handle.write(json.dumps(_row(episode_id)) + "\n")

    corrections = tmp_path / "corrections.jsonl.gz"
    with deterministic_gzip_text(corrections) as handle:
        handle.write(json.dumps(_row("correction", reward=-1.0)) + "\n")

    outputs = assemble_family_data(
        corrected,
        tmp_path / "legacy",
        corrections,
        tmp_path / "output",
        recent_winner_cap=2,
    )

    with gzip.open(outputs["b1"], "rt", encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle]
        episode_ids = {row["episode_id"] for row in rows}
    manifest = json.loads((tmp_path / "output" / "assembly_manifest.json").read_text())

    assert episode_ids == {"middle", "recent"}
    assert manifest["total_winning_decisions_scanned"] == 3
    assert manifest["recent_winning_decisions"] == 2
    assert manifest["recent_winner_cap"] == 2
    assert manifest["recent_winners_truncated"] is True
    assert manifest["total_legacy_candidates_scanned"] == 0
    assert manifest["legacy_candidates_truncated"] is False
    assert manifest["configured_legacy_rehearsal_cap"] == 20_000
    assert all("observation" not in row for row in rows)
    assert manifest["max_replays_per_correction"] == 32


def test_correction_selection_stratifies_latest_days_seats_and_archetypes():
    buckets = {
        ("2026-08-05", 0, "lucario"): deque([{"id": "a1"}, {"id": "a2"}]),
        ("2026-08-05", 1, "lucario"): deque([{"id": "b1"}, {"id": "b2"}]),
        ("2026-08-04", 0, "crustle"): deque([{"id": "c1"}, {"id": "c2"}]),
        ("2026-08-03", 1, "bellibolt"): deque([{"id": "old"}]),
    }

    selected = select_stratified_recent(buckets, max_rows=4, recent_days=2)

    assert {row["id"] for row in selected[:3]} == {"a1", "b1", "c1"}
    assert all(row["id"] != "old" for row in selected)
