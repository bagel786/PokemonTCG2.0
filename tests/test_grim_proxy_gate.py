from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

from cg.api import to_observation_class
from ptcg_ai.features import encode_observation
from ptcg_ai.model import NumpyPolicyModel
from scripts import evaluate_grim_proxy_gate as gate
from scripts.build_grim_policy_disagreements import semantic_action
from scripts.intersect_complete_turn_corrections import (
    expected_decision_id,
    expected_record_id,
    run as intersect,
    stable_json_id,
)
from training.lucario_data import deterministic_gzip_text, sha256_file


ROOT = Path(__file__).resolve().parents[1]
ANCHOR = ROOT / "artifacts" / "overnight_grim_20260730" / "grim_selected.npz"
SCHEMA3_ANCHOR = ROOT / "artifacts" / "recovery_schema3" / "d842_schema3_zero_init.npz"


def _card(card_id: int, serial: int, player: int = 0) -> dict:
    return {"id": card_id, "serial": serial, "playerIndex": player}


def _pokemon(card_id: int, serial: int) -> dict:
    return {
        "id": card_id,
        "serial": serial,
        "hp": 70,
        "maxHp": 70,
        "appearThisTurn": False,
        "energies": [],
        "energyCards": [],
        "tools": [],
        "preEvolution": [],
    }


def _player(hand: list[dict] | None, *, own: bool) -> dict:
    return {
        "active": [_pokemon(646, 3)] if own else [],
        "bench": [],
        "benchMax": 5,
        "deckCount": 45,
        "discard": [],
        "prize": [None] * 6,
        "handCount": len(hand or []) if own else 5,
        "hand": hand if own else None,
        "poisoned": False,
        "burned": False,
        "asleep": False,
        "paralyzed": False,
        "confused": False,
    }


def _observation(*, first_player: int = 0) -> dict:
    return {
        "select": {
            "type": 1,
            "context": 0,
            "minCount": 1,
            "maxCount": 1,
            "remainDamageCounter": 0,
            "remainEnergyCost": 0,
            "option": [
                {"type": 3, "area": 2, "index": 0, "playerIndex": 0},
                {"type": 3, "area": 2, "index": 1, "playerIndex": 0},
            ],
            "deck": None,
            "contextCard": None,
            "effect": None,
        },
        "logs": [],
        "current": {
            "turn": 3,
            "turnActionCount": 1,
            "yourIndex": 0,
            "firstPlayer": first_player,
            "supporterPlayed": False,
            "stadiumPlayed": False,
            "energyAttached": False,
            "retreated": False,
            "result": -1,
            "stadium": [],
            "looking": None,
            "players": [
                _player([_card(1079, 31), _card(1137, 43)], own=True),
                _player(None, own=False),
            ],
        },
        "search_begin_input": "synthetic-public-state",
    }


def _legacy_play_observation(*, first_player: int = 0) -> dict:
    """A public distinction that the frozen schema-3 trainer projects away."""

    observation = _observation(first_player=first_player)
    observation["select"]["type"] = 0
    observation["select"]["option"] = [
        {"type": 7, "index": 0},
        {"type": 7, "index": 1},
    ]
    return observation


def _runtime_choice(path: Path, observation: dict, version: int) -> list[int]:
    obs = to_observation_class(observation)
    return gate._runtime_action(NumpyPolicyModel(path), obs, encode_observation(obs, version))


def _hidden_rows(arrays: dict[str, np.ndarray], observation: dict) -> np.ndarray:
    features = encode_observation(to_observation_class(observation), 3)
    state_rows = arrays["state_embedding"][np.asarray(features.state_tokens, dtype=np.int64)]
    state = state_rows.sum(axis=0) / np.sqrt(max(1, len(state_rows)))
    global_vector = np.tanh(
        np.asarray(features.global_features, dtype=np.float32) @ arrays["global_w"]
        + arrays["global_b"]
    )
    shared = np.concatenate([state, global_vector])
    rows = []
    for option in features.options:
        numeric = np.tanh(
            np.asarray(option.numeric, dtype=np.float32) @ arrays["numeric_w"]
            + arrays["numeric_b"]
        )
        option_row = np.concatenate(
            [
                shared,
                arrays["card_embedding"][option.source_card],
                arrays["card_embedding"][option.target_card],
                arrays["attack_embedding"][option.attack_id],
                arrays["type_embedding"][option.option_type],
                arrays["context_embedding"][option.context],
                arrays["area_embedding"][option.area],
                arrays["area_embedding"][option.in_play_area],
                numeric,
            ]
        )
        rows.append(np.tanh(option_row @ arrays["option_w"] + arrays["option_b"]))
    return np.stack(rows)


def _make_candidate(path: Path, observation: dict, target: int) -> None:
    with np.load(SCHEMA3_ANCHOR, allow_pickle=False) as loaded:
        arrays = {name: np.array(loaded[name], copy=True) for name in loaded.files}
    other = 1 - target
    hidden = _hidden_rows(arrays, observation)
    arrays["score_w"] = (
        100.0 * (hidden[target] - hidden[other])
    ).reshape(arrays["score_w"].shape).astype(arrays["score_w"].dtype)
    arrays["score_b"] = np.zeros_like(arrays["score_b"])
    np.savez_compressed(path, **arrays)
    assert _runtime_choice(path, observation, 3) == [target]


def _row(name: str, episode: str, split: str, order: str, observation: dict, label: int) -> dict:
    obs = to_observation_class(observation)
    baseline_action = _runtime_choice(ANCHOR, observation, 2)
    baseline_semantic = semantic_action(observation, baseline_action)
    candidate_semantic = semantic_action(observation, [label])
    assert baseline_semantic != candidate_semantic
    baseline_id = stable_json_id(baseline_semantic)
    candidate_id = stable_json_id(candidate_semantic)
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
    row = {
        "episode_id": episode,
        "team": "Larps",
        "seat": 0,
        "step": 1,
        "action": [label],
        "reward": -1.0,
        "features": encode_observation(obs, 2).to_json(),
        "observation": observation,
        "source": "complete_turn_multi_policy_correction",
        "split": split,
        "actual_order": order,
        "semantic_pair_id": semantic_pair_id,
        "semantic_action_pair_id": stable_json_id(
            {"baseline": baseline_semantic, "candidate": candidate_semantic}
        ),
        "candidate_semantic_id": candidate_id,
        "baseline_semantic_id": baseline_id,
        "proposers": ["floor_director_v1"],
        "correction": {
            "teacher": "equal_coverage_complete_current_turn_v1",
            "baseline": "frozen_d842",
            "baseline_model_sha256": gate.FROZEN_D842_MODEL_SHA256,
            "anchor_sha256": gate.FROZEN_D842_MODEL_SHA256,
            "anchor_behavior_sha256": gate.LEGACY_D842_BEHAVIOR_SHA256,
            "certification_repeat_count": 3,
            "certification_signature": stable_json_id({"certification": name}),
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
    row["decision_id"] = expected_decision_id(row)
    row["correction_record_id"] = expected_record_id(row)
    return row


def _write_pass(path: Path, rows: list[dict], split: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with deterministic_gzip_text(path) as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    manifest = {
        "input": str((path.parent / "synthetic-disagreements.jsonl.gz").resolve()),
        "input_sha256": "A" * 64,
        "output": str(path.resolve()),
        "output_sha256": sha256_file(path).upper(),
        "model": str(ANCHOR.resolve()),
        "model_sha256": gate.FROZEN_D842_MODEL_SHA256,
        "model_behavior_sha256": gate.LEGACY_D842_BEHAVIOR_SHA256,
        "hero_deck": str((path.parent / "deck.csv").resolve()),
        "hero_deck_canonical_sha256": gate.FROZEN_GRIM_DECK_CANONICAL_SHA256,
        "splits": [split],
        "sealed_holdout_used": split == "untouched_holdout",
        "shard_index": 0,
        "shard_count": 1,
        "selected_records": len(rows),
        "decision_boundaries_evaluated": len(rows),
        "certification_repeats": 3,
        "admitted_corrections": len(rows),
        "admitted_certification_signatures": {
            row["correction_record_id"]: row["correction"]["certification_signature"]
            for row in rows
        },
        "worker_exceptions": 0,
        "integrity_failures": 0,
        "passed": True,
        "config": {
            "worlds": 8,
            "certification_repeats": 3,
            "max_turn_steps": 64,
            "timeout_seconds": 30.0,
            "seed": 20260810,
            "manual_coin": True,
        },
    }
    path.with_suffix(".manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def _bank(tmp_path: Path, name: str, rows: list[dict], split: str) -> Path:
    first = _write_pass(tmp_path / name / "a" / "pass.jsonl.gz", rows, split)
    second = _write_pass(tmp_path / name / "b" / "pass.jsonl.gz", rows, split)
    output = tmp_path / name / "intersection.jsonl.gz"
    if split != "untouched_holdout":
        intersect([first, second], output)
    else:
        ordered = sorted(rows, key=lambda row: row["correction_record_id"])
        with deterministic_gzip_text(output) as handle:
            for row in ordered:
                handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
        passes = [gate._load_pass(path, split) for path in (first, second)]
        by_order = Counter(str(row["actual_order"]) for row in ordered)
        by_proposer = Counter(
            proposer for row in ordered for proposer in sorted(set(row["proposers"]))
        )
        manifest = {
            "schema_version": 1,
            "status": "complete",
            "source": "exact_multi_pass_complete_turn_intersection",
            "sealed_holdout_used": True,
            "inputs": [
                {
                    "file": str(pass_.path),
                    "sha256": pass_.sha256,
                    "manifest": str(pass_.manifest_path),
                    "manifest_sha256": pass_.manifest_sha256,
                    "rows": len(pass_.rows),
                }
                for pass_ in passes
            ],
            "provenance": gate._pass_provenance(passes[0]),
            "counts": {
                "input_passes": 2,
                "union_correction_records": len(ordered),
                "retained_corrections": len(ordered),
                "dropped_correction_records": 0,
                "input_rows": [len(ordered), len(ordered)],
            },
            "drop_reasons": {},
            "coverage": {
                "episodes": len({row["episode_id"] for row in ordered}),
                "decision_boundaries": len(ordered),
                "by_actual_order": dict(sorted(by_order.items())),
                "by_proposer": dict(sorted(by_proposer.items())),
            },
            "output": str(output.resolve()),
            "output_sha256": sha256_file(output).upper(),
        }
        output.with_suffix(".manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return output


def _candidate_manifest(path: Path, candidate: Path, training_bank: Path, episodes: int) -> Path:
    payload = {
        "qualified": True,
        "prototype": False,
        "dataset": {
            "anchor": str(SCHEMA3_ANCHOR.resolve()),
            "anchor_sha256": gate.LEGACY_D842_SCHEMA3_FILE_SHA256,
            "anchor_behavior_sha256": gate.LEGACY_D842_BEHAVIOR_SHA256,
            "corrections_sha256": sha256_file(training_bank).upper(),
            "unique_corrections": episodes,
            "correction_episode_groups": episodes,
            "split_unit": "episode_id across corrections and rehearsal",
            "rehearsal_labels": "recomputed from anchor; replay actions ignored",
        },
        "settings": {"trainable_modules": ["score", "count"]},
        "runs": [
            {
                "seed": 19,
                "qualified": True,
                "output": str(candidate.resolve()),
                "sha256": sha256_file(candidate).upper(),
                "anchor_sha256": gate.LEGACY_D842_SCHEMA3_FILE_SHA256,
                "trainable_parameters": ["score", "count"],
            }
        ],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def test_end_to_end_gate_is_semantic_deterministic_and_passes_synthetic_labels(tmp_path: Path):
    observation = _observation()
    baseline = _runtime_choice(ANCHOR, observation, 2)[0]
    target = 1 - baseline
    candidate = tmp_path / "candidate.npz"
    _make_candidate(candidate, observation, target)

    training_rows = [
        _row(f"train-{index}", f"train-{index}", "development", "second", observation, target)
        for index in range(2)
    ]
    projected_away = _legacy_play_observation()
    projected_away_target = 1 - _runtime_choice(ANCHOR, projected_away, 2)[0]
    training_rows.append(
        _row(
            "train-projected-away",
            "train-projected-away",
            "development",
            "first",
            projected_away,
            projected_away_target,
        )
    )
    evaluation_rows = [
        _row(
            f"eval-{index}",
            f"eval-{index}",
            "calibration",
            "first" if index % 2 == 0 else "second",
            observation,
            target,
        )
        for index in range(6)
    ]
    training_bank = _bank(tmp_path, "training", training_rows, "development")
    evaluation_bank = _bank(tmp_path, "evaluation", evaluation_rows, "calibration")
    candidate_manifest = _candidate_manifest(
        tmp_path / "training-manifest.json", candidate, training_bank, 2
    )

    first_path = tmp_path / "gate-a.json"
    second_path = tmp_path / "gate-b.json"
    first = gate.run(
        labels_path=evaluation_bank,
        training_labels_path=training_bank,
        anchor_path=ANCHOR,
        candidate_path=candidate,
        candidate_manifest_path=candidate_manifest,
        expected_split="calibration",
        output_path=first_path,
        bootstrap_samples=250,
    )
    second = gate.run(
        labels_path=evaluation_bank,
        training_labels_path=training_bank,
        anchor_path=ANCHOR,
        candidate_path=candidate,
        candidate_manifest_path=candidate_manifest,
        expected_split="calibration",
        output_path=second_path,
        bootstrap_samples=250,
    )

    assert first["passed"] is True
    assert first["strata"]["overall"]["candidate_minus_d842_points"] == 100.0
    assert first["strata"]["first"]["one_sided_95_lower_points"] == 100.0
    assert first["strata"]["second"]["one_sided_95_lower_points"] == 100.0
    assert first["audit"]["invalid_selections"] == 0
    assert first["audit"]["exceptions"] == []
    assert first["audit"]["training_execution_records"] == 3
    assert first["provenance"]["training_raw_certified_records"] == 3
    assert first["provenance"]["training_projected_corrections"] == 2
    assert first["provenance"]["training_projected_episodes"] == 2
    assert first["audit"]["decision_digest"] == first["audit"]["repeat_decision_digest"]
    assert first == second
    assert first_path.read_bytes() == second_path.read_bytes()


def test_candidate_manifest_rejects_raw_count_instead_of_exact_trainer_projection(
    tmp_path: Path,
):
    observation = _observation()
    target = 1 - _runtime_choice(ANCHOR, observation, 2)[0]
    candidate = tmp_path / "candidate.npz"
    _make_candidate(candidate, observation, target)

    projected_away = _legacy_play_observation()
    projected_away_target = 1 - _runtime_choice(ANCHOR, projected_away, 2)[0]
    training_rows = [
        _row("kept", "kept", "development", "second", observation, target),
        _row(
            "projected-away",
            "projected-away",
            "development",
            "first",
            projected_away,
            projected_away_target,
        ),
    ]
    training_bank_path = _bank(tmp_path, "training", training_rows, "development")
    training_bank = gate.load_certified_bank(
        training_bank_path, expected_split="development"
    )
    wrong_manifest = _candidate_manifest(
        tmp_path / "wrong-training-manifest.json",
        candidate,
        training_bank_path,
        len(training_rows),
    )

    with pytest.raises(ValueError, match="trainer-valid projection counts"):
        gate.verify_candidate_manifest(
            wrong_manifest,
            candidate_path=candidate,
            training_bank=training_bank,
        )


def test_cluster_bound_is_episode_atomic_and_deterministic():
    records = [
        {"episode_id": "large", "candidate_match": 1, "anchor_match": 0}
        for _ in range(20)
    ] + [{"episode_id": "small", "candidate_match": 0, "anchor_match": 1}]
    first = gate.clustered_lower_bound(records, samples=500, seed=17)
    second = gate.clustered_lower_bound(list(reversed(records)), samples=500, seed=17)
    assert first == second
    # Whole-cluster sampling can draw the small negative episode twice; a
    # decision-level bootstrap would almost never reach this lower tail.
    assert first == -1.0


def test_split_authorization_and_sealed_candidate_freeze_fail_closed(tmp_path: Path):
    kwargs = dict(
        labels_path=tmp_path / "missing-labels",
        training_labels_path=tmp_path / "missing-training",
        anchor_path=ANCHOR,
        candidate_path=tmp_path / "missing-candidate",
        candidate_manifest_path=tmp_path / "missing-manifest",
        output_path=tmp_path / "out.json",
    )
    with pytest.raises(ValueError, match="explicitly"):
        gate.run(expected_split="development", **kwargs)
    with pytest.raises(ValueError, match="passing calibration"):
        gate.run(expected_split="untouched_holdout", **kwargs)


def test_frozen_candidate_required_for_protected_evaluation(tmp_path: Path):
    observation = _observation()
    target = 1 - _runtime_choice(ANCHOR, observation, 2)[0]
    candidate = tmp_path / "candidate.npz"
    _make_candidate(candidate, observation, target)
    training_rows = [
        _row(f"train-{index}", f"train-{index}", "development", "second", observation, target)
        for index in range(2)
    ]
    calibration_rows = [
        _row(
            f"cal-{index}",
            f"cal-{index}",
            "calibration",
            "first" if index % 2 == 0 else "second",
            observation,
            target,
        )
        for index in range(4)
    ]
    sealed_rows = [
        _row(
            f"sealed-{index}",
            f"sealed-{index}",
            "untouched_holdout",
            "first" if index % 2 == 0 else "second",
            observation,
            target,
        )
        for index in range(4)
    ]
    training_bank = _bank(tmp_path, "training", training_rows, "development")
    calibration_bank = _bank(tmp_path, "calibration", calibration_rows, "calibration")
    sealed_bank = _bank(tmp_path, "sealed-bank", sealed_rows, "untouched_holdout")
    candidate_manifest = _candidate_manifest(
        tmp_path / "training-manifest.json", candidate, training_bank, len(training_rows)
    )
    calibration_report_path = tmp_path / "calibration-gate.json"
    calibration = gate.run(
        labels_path=calibration_bank,
        training_labels_path=training_bank,
        anchor_path=ANCHOR,
        candidate_path=candidate,
        candidate_manifest_path=candidate_manifest,
        expected_split="calibration",
        output_path=calibration_report_path,
        bootstrap_samples=100,
    )
    assert calibration["passed"] is True

    sealed = gate.run(
        labels_path=sealed_bank,
        training_labels_path=training_bank,
        anchor_path=ANCHOR,
        candidate_path=candidate,
        candidate_manifest_path=candidate_manifest,
        expected_split="untouched_holdout",
        calibration_gate_manifest=calibration_report_path,
        output_path=tmp_path / "sealed-gate.json",
        bootstrap_samples=100,
    )
    assert sealed["passed"] is True
    assert sealed["provenance"]["candidate_sha256"] == calibration["provenance"]["candidate_sha256"]
    assert sealed["provenance"]["frozen_calibration"]["manifest_digest_sha256"] == calibration[
        "manifest_digest_sha256"
    ]


def test_certification_validation_rejects_hidden_metadata_and_short_repeat():
    observation = _observation()
    baseline = _runtime_choice(ANCHOR, observation, 2)[0]
    row = _row("bad", "bad", "calibration", "first", observation, 1 - baseline)
    manifest = {"certification_repeats": 3, "config": {"worlds": 8}}
    hidden = json.loads(json.dumps(row))
    hidden["opponent_deck"] = [1] * 60
    with pytest.raises(ValueError, match="metadata is forbidden"):
        gate._validate_certified_row(hidden, manifest, "calibration")
    short = json.loads(json.dumps(row))
    short["correction"]["certification_repeat_count"] = 2
    with pytest.raises(ValueError, match="eight-world certification"):
        gate._validate_certified_row(short, manifest, "calibration")
