from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

import scripts.build_floor_correction_corpus as floor
from scripts.build_grim_policy_disagreements import semantic_action
from scripts.intersect_complete_turn_corrections import canonical_json, stable_json_id
from training.lucario_data import deterministic_gzip_text


def _card(card_id: int, serial: int) -> dict:
    return {
        "id": card_id,
        "serial": serial,
        "playerIndex": 0,
        "hp": 100,
        "maxHp": 100,
        "appearThisTurn": False,
        "energies": [],
        "energyCards": [],
        "tools": [],
        "preEvolution": [],
    }


def _observation(name: str, family: str) -> dict:
    card_id = {
        "conversion_recovery": 646,
        "setup_bench": 646,
        "energy": 7,
        "attack_target": 648,
        "prize_counters": 1182,
        "retreat": 648,
    }[family]
    candidate_option = {
        "conversion_recovery": {"type": 9, "area": 4, "index": 0},
        "setup_bench": {"type": 7, "index": 0},
        "energy": {"type": 8, "area": 2, "index": 0, "inPlayArea": 4, "inPlayIndex": 0},
        "attack_target": {"type": 13, "area": 4, "index": 0, "attackId": 937},
        "prize_counters": {"type": 7, "index": 0},
        "retreat": {"type": 12, "area": 4, "index": 0},
    }[family]
    active_id = {
        "conversion_recovery": 646,
        "setup_bench": 648,
        "energy": 112,
        "attack_target": 648,
        "prize_counters": 648,
        "retreat": 860,
    }[family]
    hand_id = card_id if family in {"setup_bench", "energy", "prize_counters"} else 646
    return {
        "name": name,
        "current": {
            "yourIndex": 0,
            "firstPlayer": 0,
            "turn": 3,
            "players": [
                {
                    "hand": [_card(hand_id, 10)],
                    "discard": [],
                    "active": [_card(active_id, 20)],
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
            "option": [{"type": 14}, candidate_option],
            "deck": None,
            "contextCard": None,
            "effect": None,
        },
    }


def _disagreement(
    name: str,
    family: str,
    *,
    episode: str,
    step: int,
    order: str,
    outcome: str,
    matchup: str,
) -> dict:
    observation = _observation(name, family)
    observation["current"]["firstPlayer"] = 1 if order == "second" else 0
    baseline_action = [0]
    candidate_action = [1]
    baseline_semantic = semantic_action(observation, baseline_action)
    candidate_semantic = semantic_action(observation, candidate_action)
    observation_id = stable_json_id(observation)
    baseline_id = stable_json_id(baseline_semantic)
    candidate_id = stable_json_id(candidate_semantic)
    pair_id = stable_json_id(
        {
            "observation_sha256": observation_id,
            "baseline_semantic_id": baseline_id,
            "candidate_semantic_id": candidate_id,
        }
    )
    action_pair_id = stable_json_id(
        {"baseline": baseline_semantic, "candidate": candidate_semantic}
    )
    record_id = stable_json_id(
        {
            "split": "development",
            "episode_id": episode,
            "hero_seat": 0,
            "replay_step_t": step,
            "semantic_pair_id": pair_id,
        }
    )
    target = int(outcome == "win")
    return {
        "schema_version": 1,
        "record_type": "semantic_disagreement",
        "record_id": record_id,
        "split": "development",
        "episode_id": episode,
        "submission_id": 55323437,
        "hero_seat": 0,
        "replay_step_t": step,
        "historical_action_step_t_plus_1": step + 1,
        "actual_first_player": 1 if order == "second" else 0,
        "actual_order": order,
        "opponent_matchup": matchup,
        "opponent_rating_bucket": "sub_850",
        "opponent_team": "aggregate-only-source",
        "opponent_submission_id": 1,
        "outcome": outcome,
        "target": target,
        "opponent_deck": list(range(60)),
        "opponent_deck_canonical_sha256": "9" * 64,
        "observation": observation,
        "observation_sha256": observation_id,
        "features": {"feature_version": 2, "global": [float(step)], "options": []},
        "historical_action": baseline_action,
        "historical_semantic": baseline_semantic,
        "historical_agrees_with_baseline": True,
        "historical_semantically_agrees_with_baseline": True,
        "baseline_action": baseline_action,
        "baseline_semantic": baseline_semantic,
        "baseline_semantic_id": baseline_id,
        "candidate_action": candidate_action,
        "candidate_semantic": candidate_semantic,
        "candidate_semantic_id": candidate_id,
        "proposers": ["floor_director_v1"],
        "proposer_actions": {"floor_director_v1": candidate_action},
        "semantic_pair_id": pair_id,
        "semantic_action_pair_id": action_pair_id,
    }


def _correction(source: dict) -> dict:
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
    decision_id = stable_json_id(
        {
            "episode": source["episode_id"],
            "seat": source["hero_seat"],
            "step": source["replay_step_t"],
        }
    )
    return {
        "episode_id": source["episode_id"],
        "team": "Larps",
        "seat": source["hero_seat"],
        "step": source["replay_step_t"],
        "action": source["candidate_action"],
        "reward": float(source["target"]),
        "features": source["features"],
        "observation": source["observation"],
        "source": "complete_turn_multi_policy_correction",
        "split": "development",
        "actual_order": source["actual_order"],
        "correction_record_id": source["record_id"],
        "decision_id": decision_id,
        "semantic_pair_id": source["semantic_pair_id"],
        "semantic_action_pair_id": source["semantic_action_pair_id"],
        "candidate_semantic_id": source["candidate_semantic_id"],
        "baseline_semantic_id": source["baseline_semantic_id"],
        "proposers": source["proposers"],
        "correction": {
            "teacher": "equal_coverage_complete_current_turn_v1",
            "baseline": "frozen_d842",
            "baseline_model_sha256": floor.FROZEN_D842_MODEL_SHA256,
            "anchor_sha256": floor.FROZEN_D842_MODEL_SHA256,
            "anchor_behavior_sha256": "B" * 64,
            "certification_repeat_count": 3,
            "certification_signature": stable_json_id({"signature": source["record_id"]}),
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
            "public_boundary_hash": stable_json_id({"boundary": source["record_id"]}),
        },
    }


def _write_gzip(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with deterministic_gzip_text(path) as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")


def _write_sources(tmp_path: Path, disagreement_rows: list[dict], corrections: list[dict]):
    bank = tmp_path / "bank" / "disagreements.jsonl.gz"
    _write_gzip(bank, disagreement_rows)
    bank_manifest = {
        "schema_version": 1,
        "status": "complete",
        "allowed_input_splits": ["development", "calibration"],
        "holdout_read": False,
        "alignment": "observation_t_to_same_seat_action_t_plus_1",
        "semantic_deduplication": "observation_sha256_plus_candidate_semantic_id",
        "native_search_executed": False,
        "episodes": len({row["episode_id"] for row in disagreement_rows}),
        "decisions": len(disagreement_rows),
        "disagreement_rows": len(disagreement_rows),
        "rows_by_split": {"development": len(disagreement_rows)},
        "rows_by_proposer": {"floor_director_v1": len(disagreement_rows)},
        "historical_exact_agreement": len(disagreement_rows),
        "historical_semantic_agreement": len(disagreement_rows),
        "strict_historical": True,
        "strict_historical_criterion": "semantic_action_identity_not_temporary_option_index",
        "baseline": {
            "model_sha256": floor.FROZEN_D842_MODEL_SHA256,
            "deck_canonical_sha256": floor.FROZEN_GRIM_DECK_CANONICAL_SHA256,
            "reference_archive_sha256": floor.FROZEN_ARCHIVE_SHA256,
        },
        "candidates": [
            {
                "name": "floor_director_v1",
                "deck_canonical_sha256": floor.FROZEN_GRIM_DECK_CANONICAL_SHA256,
                "native_search_executed": False,
            }
        ],
        "output_file": bank.name,
        "output_sha256": floor.sha256_file(bank),
        "episode_metrics": {},
    }
    bank_manifest_path = bank.with_name("manifest.json")
    bank_manifest_path.write_text(canonical_json(bank_manifest) + "\n", encoding="utf-8")

    intersection = tmp_path / "certified" / "intersection.jsonl.gz"
    corrections = sorted(corrections, key=lambda row: row["correction_record_id"])
    _write_gzip(intersection, corrections)
    correction_episodes = {row["episode_id"] for row in corrections}
    order_counts = {
        order: sum(row["actual_order"] == order for row in corrections)
        for order in ("first", "second")
        if any(row["actual_order"] == order for row in corrections)
    }
    intersection_manifest = {
        "schema_version": 1,
        "status": "complete",
        "passed": True,
        "source": "exact_multi_pass_complete_turn_intersection",
        "sealed_holdout_used": False,
        "inputs": [
            {
                "file": str(tmp_path / "pass-a.jsonl.gz"),
                "sha256": "1" * 64,
                "manifest": str(tmp_path / "pass-a.jsonl.manifest.json"),
                "manifest_sha256": "2" * 64,
                "rows": len(corrections),
            },
            {
                "file": str(tmp_path / "pass-b.jsonl.gz"),
                "sha256": "3" * 64,
                "manifest": str(tmp_path / "pass-b.jsonl.manifest.json"),
                "manifest_sha256": "4" * 64,
                "rows": len(corrections),
            },
        ],
        "provenance": {
            "source_input_sha256": floor.sha256_file(bank),
            "model_sha256": floor.FROZEN_D842_MODEL_SHA256,
            "model_behavior_sha256": "B" * 64,
            "hero_deck_canonical_sha256": floor.FROZEN_GRIM_DECK_CANONICAL_SHA256,
            "splits": ["development"],
            "shard_index": 0,
            "shard_count": 1,
            "selected_records": len(corrections),
            "decision_boundaries_evaluated": len(corrections),
            "certification_repeats": 3,
            "config": {"worlds": 8, "seed": 7},
        },
        "counts": {
            "input_passes": 2,
            "union_correction_records": len(corrections),
            "retained_corrections": len(corrections),
            "dropped_correction_records": 0,
            "input_rows": [len(corrections), len(corrections)],
        },
        "drop_reasons": {},
        "coverage": {
            "episodes": len(correction_episodes),
            "decision_boundaries": len(corrections),
            "by_actual_order": order_counts,
            "by_proposer": {"floor_director_v1": len(corrections)},
        },
        "output": str(intersection.resolve()),
        "output_sha256": floor.sha256_file(intersection),
    }
    intersection_manifest_path = floor.intersection_manifest_path(intersection)
    intersection_manifest_path.write_text(
        json.dumps(intersection_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return bank, bank_manifest_path, intersection, intersection_manifest_path


def _fixture_rows():
    specs = [
        ("loss-conversion", "conversion_recovery", "loss-first", 1, "first", "loss", "mirror"),
        ("loss-setup", "setup_bench", "loss-first", 2, "first", "loss", "mirror"),
        ("loss-prize", "prize_counters", "loss-first", 3, "first", "loss", "mirror"),
        ("second-energy", "energy", "win-second", 1, "second", "win", "fast_pressure"),
        ("second-attack", "attack_target", "win-second", 2, "second", "win", "fast_pressure"),
        ("second-retreat", "retreat", "win-second", 3, "second", "win", "fast_pressure"),
        ("excluded", "setup_bench", "win-first", 1, "first", "win", "wall"),
    ]
    disagreements = [
        _disagreement(
            name,
            family,
            episode=episode,
            step=step,
            order=order,
            outcome=outcome,
            matchup=matchup,
        )
        for name, family, episode, step, order, outcome, matchup in specs
    ]
    return disagreements, [_correction(row) for row in disagreements]


def test_episode_atomic_floor_selection_is_canonical_deterministic_and_sanitized(tmp_path):
    disagreements, corrections = _fixture_rows()
    bank, bank_manifest, intersection, intersection_manifest = _write_sources(
        tmp_path, disagreements, corrections
    )
    first_output = tmp_path / "out-a" / "floor.jsonl.gz"
    second_output = tmp_path / "out-b" / "floor.jsonl.gz"
    kwargs = {
        "intersection_manifest": intersection_manifest,
        "disagreements_manifest": bank_manifest,
        "minimum_corrections": 6,
        "minimum_episodes": 2,
    }
    first = floor.run(intersection, bank, first_output, **kwargs)
    second = floor.run(intersection, bank, second_output, **kwargs)

    assert first_output.read_bytes() == second_output.read_bytes()
    with gzip.open(first_output, "rt", encoding="utf-8") as handle:
        output_lines = handle.readlines()
    expected_rows = sorted(
        [row for row in corrections if row["episode_id"] != "win-first"],
        key=lambda row: row["correction_record_id"],
    )
    assert output_lines == [canonical_json(row) + "\n" for row in expected_rows]
    assert all("opponent_matchup" not in line and "opponent_deck" not in line for line in output_lines)
    assert first["selection"]["retained_corrections"] == 6
    assert first["selection"]["retained_episodes"] == 2
    assert first["selection"]["excluded_corrections"] == 1
    assert first["coverage"]["episodes_by_actual_order"] == {"first": 1, "second": 1}
    assert first["coverage"]["by_action_family"] == {
        "conversion_recovery": 1,
        "setup_bench": 1,
        "energy": 1,
        "attack_target": 1,
        "prize_counters": 1,
        "retreat": 1,
        "other": 0,
    }
    assert first["coverage"]["by_matchup_category"] == {"fast_pressure": 3, "mirror": 3}
    assert first["calibration_rows_used"] == 0
    assert first["source_bindings"]["intersection_sha256"] == floor.sha256_file(intersection)
    assert first["source_bindings"]["semantic_disagreements_sha256"] == floor.sha256_file(bank)
    assert second["output_sha256"] == first["output_sha256"]


def test_default_strength_gates_fail_before_writing_and_report_exact_counts(tmp_path):
    disagreements, corrections = _fixture_rows()
    bank, bank_manifest, intersection, intersection_manifest = _write_sources(
        tmp_path, disagreements, corrections
    )
    output = tmp_path / "out" / "floor.jsonl.gz"
    with pytest.raises(floor.CoverageGateError) as caught:
        floor.run(
            intersection,
            bank,
            output,
            intersection_manifest=intersection_manifest,
            disagreements_manifest=bank_manifest,
        )
    assert not output.exists()
    assert caught.value.report["selection"]["retained_corrections"] == 6
    assert caught.value.report["selection"]["retained_episodes"] == 2
    assert "corrections:6<250" in caught.value.report["failed_gates"]
    assert "episodes:2<30" in caught.value.report["failed_gates"]


def test_family_minima_are_configurable_but_every_exact_count_is_reported(tmp_path):
    disagreements, corrections = _fixture_rows()
    keep = [row for row in corrections if row["correction_record_id"] != disagreements[5]["record_id"]]
    bank, bank_manifest, intersection, intersection_manifest = _write_sources(tmp_path, disagreements, keep)
    output = tmp_path / "out" / "floor.jsonl.gz"
    with pytest.raises(floor.CoverageGateError) as caught:
        floor.run(
            intersection,
            bank,
            output,
            intersection_manifest=intersection_manifest,
            disagreements_manifest=bank_manifest,
            minimum_corrections=5,
            minimum_episodes=2,
        )
    assert caught.value.report["coverage"]["by_action_family"]["retreat"] == 0
    assert "action_family.retreat:0<1" in caught.value.report["failed_gates"]

    manifest = floor.run(
        intersection,
        bank,
        output,
        intersection_manifest=intersection_manifest,
        disagreements_manifest=bank_manifest,
        minimum_corrections=5,
        minimum_episodes=2,
        family_minima={"retreat": 0},
    )
    assert manifest["coverage"]["by_action_family"]["retreat"] == 0
    assert manifest["thresholds"]["minimum_by_action_family"]["retreat"] == 0


def test_hash_and_development_only_provenance_fail_closed(tmp_path):
    disagreements, corrections = _fixture_rows()
    bank, bank_manifest, intersection, intersection_manifest = _write_sources(
        tmp_path, disagreements, corrections
    )
    manifest = json.loads(intersection_manifest.read_text(encoding="utf-8"))
    manifest["provenance"]["splits"] = ["development", "calibration"]
    intersection_manifest.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="provenance"):
        floor.run(
            intersection,
            bank,
            tmp_path / "out.jsonl.gz",
            intersection_manifest=intersection_manifest,
            disagreements_manifest=bank_manifest,
            minimum_corrections=0,
            minimum_episodes=0,
        )

    # Restore the split and corrupt the bound semantic-bank hash.
    manifest["provenance"]["splits"] = ["development"]
    manifest["provenance"]["source_input_sha256"] = "0" * 64
    intersection_manifest.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="provenance"):
        floor.run(
            intersection,
            bank,
            tmp_path / "out.jsonl.gz",
            intersection_manifest=intersection_manifest,
            disagreements_manifest=bank_manifest,
            minimum_corrections=0,
            minimum_episodes=0,
        )


def test_hidden_metadata_and_one_label_per_decision_are_rejected(tmp_path):
    disagreements, corrections = _fixture_rows()
    hidden = json.loads(canonical_json(corrections[0]))
    hidden["opponent_matchup"] = "mirror"
    bank, bank_manifest, intersection, intersection_manifest = _write_sources(
        tmp_path / "hidden", disagreements, [hidden]
    )
    with pytest.raises(ValueError, match="metadata is forbidden"):
        floor.run(
            intersection,
            bank,
            tmp_path / "hidden" / "out.jsonl.gz",
            intersection_manifest=intersection_manifest,
            disagreements_manifest=bank_manifest,
            minimum_corrections=0,
            minimum_episodes=0,
        )

    duplicate = json.loads(canonical_json(corrections[0]))
    duplicate["candidate_semantic_id"] = "F" * 64
    duplicate["semantic_pair_id"] = stable_json_id(
        {
            "observation_sha256": stable_json_id(duplicate["observation"]),
            "baseline_semantic_id": duplicate["baseline_semantic_id"],
            "candidate_semantic_id": duplicate["candidate_semantic_id"],
        }
    )
    duplicate["correction_record_id"] = stable_json_id(
        {
            "split": "development",
            "episode_id": duplicate["episode_id"],
            "hero_seat": duplicate["seat"],
            "replay_step_t": duplicate["step"],
            "semantic_pair_id": duplicate["semantic_pair_id"],
        }
    )
    bank, bank_manifest, intersection, intersection_manifest = _write_sources(
        tmp_path / "duplicate", disagreements, [corrections[0], duplicate]
    )
    with pytest.raises(ValueError, match="multiple certified labels"):
        floor.run(
            intersection,
            bank,
            tmp_path / "duplicate" / "out.jsonl.gz",
            intersection_manifest=intersection_manifest,
            disagreements_manifest=bank_manifest,
            minimum_corrections=0,
            minimum_episodes=0,
        )


def test_correction_disagreement_semantic_provenance_mismatch_is_rejected(tmp_path):
    disagreements, corrections = _fixture_rows()
    tampered = json.loads(canonical_json(corrections[0]))
    tampered["features"] = {"feature_version": 2, "global": [999.0], "options": []}
    bank, bank_manifest, intersection, intersection_manifest = _write_sources(
        tmp_path, disagreements, [tampered]
    )
    with pytest.raises(ValueError, match="provenance mismatch"):
        floor.run(
            intersection,
            bank,
            tmp_path / "out.jsonl.gz",
            intersection_manifest=intersection_manifest,
            disagreements_manifest=bank_manifest,
            minimum_corrections=0,
            minimum_episodes=0,
            family_minima={family: 0 for family in floor.REQUIRED_ACTION_FAMILIES},
        )
