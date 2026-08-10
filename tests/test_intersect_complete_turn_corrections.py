import gzip
import json
from pathlib import Path

import pytest

import scripts.intersect_complete_turn_corrections as intersection
from scripts.intersect_complete_turn_corrections import (
    FROZEN_D842_MODEL_SHA256,
    FROZEN_GRIM_DECK_CANONICAL_SHA256,
    canonical_json,
    expected_decision_id,
    expected_record_id,
    load_pass,
    manifest_path_for,
    run,
    sha256_file,
    stable_json_id,
)
from training.lucario_data import deterministic_gzip_text


def make_row(
    name: str,
    *,
    episode: str | None = None,
    seat: int = 0,
    step: int = 1,
    order: str = "second",
    family: str | None = None,
) -> dict:
    observation = {"turn": 3, "select": {"minCount": 1, "maxCount": 1, "options": []}, "name": name}
    baseline_id = stable_json_id({"baseline": name})
    candidate_id = stable_json_id({"candidate": name})
    observation_id = stable_json_id(observation)
    semantic_pair_id = stable_json_id(
        {
            "observation_sha256": observation_id,
            "baseline_semantic_id": baseline_id,
            "candidate_semantic_id": candidate_id,
        }
    )
    worlds = [
        {
            "world_index": index,
            "seed": 100 + index,
            "baseline": [0.0, 0.0],
            "candidate": [1.0, 0.0],
            "lexicographic_comparison": 1,
            "baseline_steps": 2,
            "candidate_steps": 2,
        }
        for index in range(8)
    ]
    signature = stable_json_id({"certification": name})
    row = {
        "episode_id": episode or f"episode-{name}",
        "team": "Larps",
        "seat": seat,
        "step": step,
        "action": [1],
        "reward": -1.0,
        "features": {"feature_version": 2, "global": [], "options": []},
        "observation": observation,
        "source": "complete_turn_multi_policy_correction",
        "split": "development",
        "actual_order": order,
        "semantic_pair_id": semantic_pair_id,
        "semantic_action_pair_id": stable_json_id({"action-pair": name}),
        "candidate_semantic_id": candidate_id,
        "baseline_semantic_id": baseline_id,
        "proposers": ["floor_director_v1", "tempo"],
        "correction": {
            "teacher": "equal_coverage_complete_current_turn_v1",
            "baseline": "frozen_d842",
            "baseline_model_sha256": FROZEN_D842_MODEL_SHA256,
            "anchor_sha256": FROZEN_D842_MODEL_SHA256,
            "anchor_behavior_sha256": "B" * 64,
            "certification_repeat_count": 3,
            "certification_signature": signature,
            "decision": {
                "admitted": True,
                "reason": "admitted",
                "expected_worlds": 8,
                "covered_worlds": 8,
                "noninferior_worlds": 8,
                "strict_better_worlds": 8,
                "required_strict_worlds": 4,
            },
            "coverage": {"baseline": 8, "candidate": 8},
            "worlds": worlds,
            "errors": [],
            "coverage_complete": True,
            "all_worlds_nonnegative": True,
            "strict_better_worlds": 8,
            "per_world_comparisons": [1] * 8,
            "per_world_vectors": worlds,
            "public_boundary_hash": stable_json_id({"boundary": name}),
        },
    }
    if family is not None:
        row["family"] = family
    row["decision_id"] = expected_decision_id(row)
    row["correction_record_id"] = expected_record_id(row)
    return row


def write_pass(path: Path, rows: list[dict], *, manifest_updates: dict | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with deterministic_gzip_text(path) as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")
    manifest = {
        "input": str((path.parent / "disagreements.jsonl.gz").resolve()),
        "input_sha256": "A" * 64,
        "output": str(path.resolve()),
        "output_sha256": sha256_file(path),
        "model": str((path.parent / "d842.npz").resolve()),
        "model_sha256": FROZEN_D842_MODEL_SHA256,
        "model_behavior_sha256": "B" * 64,
        "hero_deck": str((path.parent / "deck.csv").resolve()),
        "hero_deck_canonical_sha256": FROZEN_GRIM_DECK_CANONICAL_SHA256,
        "splits": ["development"],
        "sealed_holdout_used": False,
        "shard_index": 0,
        "shard_count": 1,
        "selected_records": 20,
        "decision_boundaries_evaluated": 18,
        "certification_repeats": 3,
        "admitted_corrections": len(rows),
        "admitted_certification_signatures": {
            row["correction_record_id"]: row["correction"]["certification_signature"] for row in rows
        },
        "worker_exceptions": 0,
        "integrity_failures": 0,
        "passed": True,
        "config": {
            "worlds": 8,
            "max_turn_steps": 64,
            "timeout_seconds": 30.0,
            "seed": 20260810,
            "manual_coin": True,
        },
    }
    if manifest_updates:
        for key, value in manifest_updates.items():
            if key.startswith("config."):
                manifest["config"][key.split(".", 1)[1]] = value
            else:
                manifest[key] = value
    manifest_path_for(path).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return path


def test_exact_intersection_is_deterministic_and_reports_coverage_and_drops(tmp_path):
    common = make_row("common", family="setup")
    missing = make_row("missing")
    unstable_a = make_row("unstable")
    unstable_b = json.loads(canonical_json(unstable_a))
    unstable_b["correction"]["certification_signature"] = stable_json_id("different-run")
    alternate_a = make_row("alternate-a", episode="alternate", step=7)
    alternate_b = make_row("alternate-b", episode="alternate", step=7)

    first = write_pass(tmp_path / "pass-a.jsonl.gz", [common, missing, unstable_a, alternate_a])
    second = write_pass(tmp_path / "pass-b.jsonl.gz", [alternate_b, unstable_b, common])
    output_a = tmp_path / "intersection-a.jsonl.gz"
    output_b = tmp_path / "intersection-b.jsonl.gz"
    manifest_a = run([first, second], output_a)
    manifest_b = run([second, first], output_b)

    assert output_a.read_bytes() == output_b.read_bytes()
    with gzip.open(output_a, "rt", encoding="utf-8") as handle:
        assert [json.loads(line) for line in handle] == [common]
    assert manifest_a["counts"] == {
        "input_passes": 2,
        "union_correction_records": 5,
        "retained_corrections": 1,
        "dropped_correction_records": 4,
        "input_rows": [4, 3],
    }
    assert manifest_a["drop_reasons"] == {
        "certification_payload_or_signature_mismatch": 1,
        "decision_label_mismatch": 2,
        "not_present_in_every_pass": 1,
    }
    assert manifest_a["coverage"] == {
        "episodes": 1,
        "decision_boundaries": 1,
        "by_actual_order": {"second": 1},
        "by_proposer": {"floor_director_v1": 1, "tempo": 1},
        "by_family": {"setup": 1},
    }
    assert manifest_a["sealed_holdout_used"] is False
    assert manifest_a["output_sha256"] == sha256_file(output_a)
    assert manifest_b["counts"] == manifest_a["counts"]


@pytest.mark.parametrize(
    "update",
    [
        {"input_sha256": "C" * 64},
        {"model_sha256": "C" * 64},
        {"hero_deck_canonical_sha256": "C" * 64},
        {"config.worlds": 7},
        {"certification_repeats": 4},
        {"config.seed": 99},
    ],
)
def test_source_model_deck_world_repeat_and_config_mismatch_fail_closed(tmp_path, update):
    row = make_row("same")
    first = write_pass(tmp_path / "a" / "pass.jsonl.gz", [row])
    second = write_pass(tmp_path / "b" / "pass.jsonl.gz", [row], manifest_updates=update)
    with pytest.raises(ValueError):
        run([first, second], tmp_path / "out.jsonl.gz")
    assert not (tmp_path / "out.jsonl.gz").exists()


def test_same_record_with_semantic_provenance_mismatch_fails_closed(tmp_path):
    first_row = make_row("same")
    second_row = json.loads(canonical_json(first_row))
    second_row["actual_order"] = "first"
    first = write_pass(tmp_path / "a" / "pass.jsonl.gz", [first_row])
    second = write_pass(tmp_path / "b" / "pass.jsonl.gz", [second_row])
    with pytest.raises(ValueError, match="semantic provenance mismatch"):
        run([first, second], tmp_path / "out.jsonl.gz")


def test_duplicate_episode_seat_step_is_refused_within_a_pass(tmp_path):
    first = make_row("first", episode="episode", seat=1, step=9)
    second = make_row("second", episode="episode", seat=1, step=9)
    path = write_pass(tmp_path / "duplicates.jsonl.gz", [first, second])
    with pytest.raises(ValueError, match="multiple labels for episode-seat-step"):
        load_pass(path)


def test_hidden_metadata_and_holdout_paths_are_refused(tmp_path):
    hidden = make_row("hidden")
    hidden["opponent_deck"] = [1] * 60
    hidden_path = write_pass(tmp_path / "hidden.jsonl.gz", [hidden])
    with pytest.raises(ValueError, match="metadata is forbidden"):
        load_pass(hidden_path)

    with pytest.raises(ValueError, match="holdout"):
        load_pass(tmp_path / "sealed_holdout.jsonl.gz")


def test_manifest_signature_map_and_output_hash_are_verified(tmp_path):
    row = make_row("integrity")
    bad_signatures = write_pass(
        tmp_path / "bad-signatures.jsonl.gz",
        [row],
        manifest_updates={"admitted_certification_signatures": {}},
    )
    with pytest.raises(ValueError, match="signature map"):
        load_pass(bad_signatures)

    bad_hash = write_pass(
        tmp_path / "bad-hash.jsonl.gz",
        [row],
        manifest_updates={"output_sha256": "0" * 64},
    )
    with pytest.raises(ValueError, match="integrity checks"):
        load_pass(bad_hash)
