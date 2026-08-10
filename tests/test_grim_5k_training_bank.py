from __future__ import annotations

import gzip
import json
from collections import defaultdict
from pathlib import Path

import pytest

from scripts import build_grim_5k_training_bank as bank


ALLOWED = 55323437
OTHER_ALLOWED = 55358290
UNKNOWN_EXACT_DECK = 99999999


def write_deck(path: Path, cards: list[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(map(str, cards)) + "\n", encoding="utf-8")


def write_replay(
    root: Path,
    submission_id: int,
    episode_id: int,
    deck0: list[int],
    deck1: list[int],
    *,
    first_player: int = 0,
    rewards: tuple[int, int] = (1, -1),
    teams: tuple[str, str] = ("opponent", "grim"),
    public: bool = True,
) -> Path:
    path = root / str(submission_id) / f"episode-{episode_id}-replay.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    current0 = {"firstPlayer": first_player, "yourIndex": 0, "result": -1}
    current1 = {"firstPlayer": first_player, "yourIndex": 1, "result": -1}
    select = {"minCount": 1, "maxCount": 1, "option": [{"type": 13}]}
    payload = {
        "public": public,
        "rewards": list(rewards),
        "info": {"EpisodeId": episode_id, "TeamNames": list(teams)},
        "steps": [
            [
                {"status": "ACTIVE", "action": deck0, "observation": {"current": current0}},
                {"status": "ACTIVE", "action": deck1, "observation": {"current": current1}},
            ],
            [
                {"status": "ACTIVE", "action": [0], "observation": {"current": current0, "select": select}},
                {"status": "INACTIVE", "action": [], "observation": {"current": current1}},
            ],
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def episode_row(
    episode_id: int,
    *,
    seat: int = 1,
    outcome: float = -1.0,
    opponent_team: str | None = "opponent",
    hero_rating: float | None = 810,
    opponent_rating: float | None = 720,
) -> dict:
    return {
        "episode_id": episode_id,
        "seat": seat,
        "outcome": outcome,
        "created_utc": "2026-08-08 10:00:00",
        "initial_rating": hero_rating,
        "opponent_initial_rating": opponent_rating,
        "opponent_team": opponent_team,
        "opponent_submission_id": 42,
    }


def submission(submission_id: int, expected: list[int], episodes: list[dict]) -> dict:
    return {
        "submission_id": submission_id,
        "policy_lineage": "frozen_d842_hash_proven" if submission_id in bank.HASH_PROVEN_D842 else "frozen_d842_documented",
        "deck_class": "exact_original_grim",
        "deck_canonical_sha256": bank.deck_hash(expected),
        "deck": expected,
        "rated_episodes": len(episodes),
        "episodes": episodes,
    }


def write_manifest(path: Path, expected: list[int], submissions: list[dict], **extra) -> Path:
    payload = {
        "expected_deck_canonical_sha256": bank.deck_hash(expected),
        "submissions": submissions,
        "download_errors": extra.pop("download_errors", []),
        **extra,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def read_split(output: Path, name: str) -> list[dict]:
    with gzip.open(output / f"{name}.jsonl.gz", "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def test_bank_strictly_filters_lineage_and_validates_public_replay_labels(tmp_path: Path) -> None:
    expected = list(range(1, 61))
    opponent = list(range(101, 161))
    deck_path = tmp_path / "expected.deck.csv"
    archetypes = tmp_path / "archetypes"
    write_deck(deck_path, expected)
    write_deck(archetypes / "mega_lucario_ex.deck.csv", opponent)
    replays = tmp_path / "replays"

    # Hero is seat 1, loses, and actually goes second.
    write_replay(replays, ALLOWED, 10, opponent, expected, first_player=0, rewards=(1, -1))
    # Explicitly private data must never enter even when every other label is valid.
    write_replay(replays, ALLOWED, 11, opponent, expected, first_player=1, rewards=(-1, 1), public=False)
    # Exact deck identity alone cannot admit an unknown policy submission.
    write_replay(replays, UNKNOWN_EXACT_DECK, 12, opponent, expected)

    eligible_rows = [
        episode_row(10),
        dict(episode_row(10)),  # exact duplicate inventory row
        episode_row(11, outcome=1.0),
        episode_row(13),  # deliberately missing partial download
    ]
    manifest_path = write_manifest(
        tmp_path / "manifest.partial.json",
        expected,
        [
            submission(ALLOWED, expected, eligible_rows),
            submission(UNKNOWN_EXACT_DECK, expected, [episode_row(12)]),
        ],
        download_errors=[{"submission_id": ALLOWED, "episode_id": 13, "error": "partial"}],
    )
    output = tmp_path / "bank"
    result = bank.build_bank(manifest_path, replays, output, deck_path, archetypes, "unit-test")

    assert result["bank_status"] == "partial"
    assert result["corpus_complete"] is False
    assert result["source_completeness"]["admitted_units"] == 1
    assert result["source_completeness"]["relevant_download_errors"] == 1
    assert result["rejections_by_reason"]["outside_strict_d842_lineage"] == 1
    assert result["rejections_by_reason"]["duplicate_manifest_unit"] == 1
    assert result["rejections_by_reason"]["not_public"] == 1
    assert result["rejections_by_reason"]["missing_replay"] == 1

    rows = sum((read_split(output, name) for name in bank.SPLIT_NAMES), [])
    assert len(rows) == 1
    row = rows[0]
    assert row["submission_id"] == ALLOWED
    assert row["actual_first_player"] == 0
    assert row["actual_order"] == "second"
    assert row["target"] == 0
    assert row["outcome"] == "loss"
    assert row["opponent_rating_bucket"] == "650-749"
    assert row["opponent_matchup"] == "mega_lucario_ex"
    assert row["opponent_matchup_evidence"] == "exact_signature"
    assert row["required_labels_complete"] is True
    assert row["public_source"] == "kaggle_competition_manifest"
    assert Path(output / "manifests" / f"{row['split']}.json").exists()


def test_missing_optional_ratings_are_labeled_not_dropped(tmp_path: Path) -> None:
    expected = list(range(1, 61))
    opponent = list(range(101, 161))
    deck_path = tmp_path / "deck.csv"
    write_deck(deck_path, expected)
    replays = tmp_path / "replays"
    write_replay(replays, ALLOWED, 20, opponent, expected, rewards=(1, -1))
    row = episode_row(20, hero_rating=None, opponent_rating=None)
    manifest_path = write_manifest(
        tmp_path / "manifest.partial.json", expected, [submission(ALLOWED, expected, [row])]
    )

    result = bank.build_bank(manifest_path, replays, tmp_path / "out", deck_path, tmp_path / "no-catalog")
    assert result["source_completeness"]["admitted_units"] == 1
    assert result["label_completeness"]["hero_rating"]["missing"] == 1
    assert result["label_completeness"]["opponent_rating"]["missing"] == 1
    output_row = sum((read_split(tmp_path / "out", name) for name in bank.SPLIT_NAMES), [])[0]
    assert output_row["hero_rating_bucket"] == "unknown"
    assert output_row["opponent_rating_bucket"] == "unknown"
    assert output_row["required_labels_complete"] is True


def test_deck_and_actual_order_mismatches_are_hard_rejections(tmp_path: Path) -> None:
    expected = list(range(1, 61))
    wrong = list(range(2, 62))
    opponent = list(range(101, 161))
    deck_path = tmp_path / "deck.csv"
    write_deck(deck_path, expected)
    replays = tmp_path / "replays"
    write_replay(replays, ALLOWED, 30, opponent, wrong)
    write_replay(replays, ALLOWED, 31, opponent, expected, first_player=0)
    write_replay(replays, ALLOWED, 32, opponent, expected, first_player=1, rewards=(-1, 1))
    rows = [
        episode_row(30),
        {**episode_row(31), "actual_order": "first"},  # seat 1 actually second
        episode_row(32, outcome=1.0),
    ]
    manifest_path = write_manifest(
        tmp_path / "manifest.partial.json", expected, [submission(ALLOWED, expected, rows)]
    )

    result = bank.build_bank(manifest_path, replays, tmp_path / "out", deck_path, tmp_path / "catalog")
    assert result["source_completeness"]["admitted_units"] == 1
    assert result["rejections_by_reason"]["hero_deck_mismatch"] == 1
    assert result["rejections_by_reason"]["actual_order_mismatch"] == 1


def minimal_unit(index: int, *, team: str | None = None) -> dict:
    buckets = bank.RATING_BUCKETS[:-1]
    return {
        "episode_id": str(index),
        "submission_id": ALLOWED if index % 2 else OTHER_ALLOWED,
        "hero_seat": index % 2,
        "actual_order": "first" if index % 2 else "second",
        "opponent_rating_bucket": buckets[index % len(buckets)],
        "opponent_team_normalized": team if team is not None else f"team-{index}",
    }


def test_split_is_deterministic_balanced_and_opponent_team_atomic() -> None:
    units = [minimal_unit(index) for index in range(120)]
    # These otherwise-unrelated episodes must form one connected atomic group.
    units[3]["opponent_team_normalized"] = "repeat-opponent"
    units[73]["opponent_team_normalized"] = "repeat-opponent"
    first, first_report = bank.assign_splits(units, "stable-seed")
    second, second_report = bank.assign_splits(list(reversed(units)), "stable-seed")

    assignment_a = {
        str(row["episode_id"]): row["split"]
        for rows in first.values() for row in rows
    }
    assignment_b = {
        str(row["episode_id"]): row["split"]
        for rows in second.values() for row in rows
    }
    assert assignment_a == assignment_b
    assert assignment_a["3"] == assignment_a["73"]
    counts = {name: len(rows) for name, rows in first.items()}
    assert abs(counts["development"] - 72) <= 2
    assert abs(counts["calibration"] - 24) <= 2
    assert abs(counts["untouched_holdout"] - 24) <= 2
    assert first_report == second_report
    assert first_report["actual_order_imbalance"]["max_absolute_share_error"] <= 0.05
    assert first_report["opponent_rating_imbalance"]["max_absolute_share_error"] <= 0.10


def test_same_episode_rows_cannot_cross_splits_even_with_different_opponent_teams() -> None:
    units = [minimal_unit(index) for index in range(20)]
    mirror_a = minimal_unit(500, team="owned-team-b")
    mirror_b = minimal_unit(501, team="owned-team-a")
    mirror_b["episode_id"] = mirror_a["episode_id"]
    mirror_b["submission_id"] = OTHER_ALLOWED
    mirror_b["hero_seat"] = 1 - mirror_a["hero_seat"]
    units.extend((mirror_a, mirror_b))
    splits, _ = bank.assign_splits(units, "mirror")
    mirror_rows = [
        row for rows in splits.values() for row in rows if row["episode_id"] == "500"
    ]
    assert len(mirror_rows) == 2
    assert len({row["split"] for row in mirror_rows}) == 1
    assert len({row["grouping_key"] for row in mirror_rows}) == 1


def test_build_outputs_are_byte_deterministic(tmp_path: Path) -> None:
    expected = list(range(1, 61))
    opponent = list(range(101, 161))
    deck_path = tmp_path / "deck.csv"
    write_deck(deck_path, expected)
    replays = tmp_path / "replays"
    rows = []
    for episode_id in range(100, 112):
        write_replay(
            replays,
            ALLOWED,
            episode_id,
            opponent,
            expected,
            first_player=episode_id % 2,
            rewards=(1, -1),
            teams=(f"opponent-{episode_id}", "grim"),
        )
        rows.append(episode_row(episode_id, opponent_team=f"opponent-{episode_id}"))
    manifest_path = write_manifest(
        tmp_path / "manifest.partial.json", expected, [submission(ALLOWED, expected, rows)]
    )
    out_a, out_b = tmp_path / "a", tmp_path / "b"
    result_a = bank.build_bank(manifest_path, replays, out_a, deck_path, tmp_path / "catalog", "same")
    result_b = bank.build_bank(manifest_path, replays, out_b, deck_path, tmp_path / "catalog", "same")

    assert result_a["bank_id"] == result_b["bank_id"]
    for split in bank.SPLIT_NAMES:
        assert bank.sha256_file(out_a / f"{split}.jsonl.gz") == bank.sha256_file(out_b / f"{split}.jsonl.gz")


def test_default_lineage_allowlist_is_not_description_based() -> None:
    expected_hash = bank.FROZEN_GRIM_DECK_CANONICAL_SHA256
    fake = {
        "submission_id": UNKNOWN_EXACT_DECK,
        "description": "frozen d842 exact 5k control",
        "deck_class": "exact_original_grim",
        "deck_canonical_sha256": expected_hash,
    }
    assert bank._submission_is_eligible(fake, expected_hash) == (False, "outside_strict_d842_lineage")
    allowed_but_wrong_deck = {
        "submission_id": ALLOWED,
        "policy_lineage": "frozen_d842_hash_proven",
        "deck_class": "exact_original_grim",
        "deck_canonical_sha256": "0" * 64,
    }
    assert bank._submission_is_eligible(allowed_but_wrong_deck, expected_hash) == (
        False,
        "submission_deck_hash_mismatch",
    )
