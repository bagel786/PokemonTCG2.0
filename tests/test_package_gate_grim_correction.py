from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from scripts import package_gate_grim_correction as gate


def _candidate_model(tmp_path: Path) -> Path:
    anchor = gate.ROOT / "artifacts/recovery_schema3/d842_schema3_zero_init.npz"
    with np.load(anchor, allow_pickle=False) as source:
        arrays = {name: np.array(source[name], copy=True) for name in source.files}
    arrays["score_b"][0] = np.float16(float(arrays["score_b"][0]) + 0.01)
    output = tmp_path / "candidate.npz"
    np.savez_compressed(output, **arrays)
    return output


def _training_manifest(tmp_path: Path, model: Path) -> Path:
    model_sha = gate.sha256_file(model)
    payload = {
        "qualified": True,
        "prototype": False,
        "dataset": {
            "unique_corrections": 250,
            "correction_episode_groups": 40,
            "split_unit": "episode_id across corrections and rehearsal",
            "rehearsal_labels": "recomputed from anchor; replay actions ignored",
            "anchor_sha256": gate.FROZEN_SCHEMA3_ANCHOR_SHA256,
            "anchor_behavior_sha256": gate.FROZEN_BEHAVIOR_SHA256,
            "corrections_sha256": "A" * 64,
            "rehearsal_sha256": "B" * 64,
            "certification_kinds": {"complete_turn_v1": 250},
        },
        "settings": {
            "seeds": [7],
            "epochs": 2,
            "learning_rate": 2e-5,
            "distill_weight": 4.0,
            "correction_weight": 8.0,
            "trainable_modules": ["score", "count"],
            "max_change_rate": 0.01,
            "min_correction_lift": 0.08,
        },
        "runs": [{
            "qualified": True,
            "seed": 7,
            "sha256": model_sha,
            "anchor_sha256": gate.FROZEN_SCHEMA3_ANCHOR_SHA256,
            "trainable_parameters": ["score.weight", "score.bias", "count.weight", "count.bias"],
            "artifact_audit": {
                "correction_lift": 0.12,
                "rehearsal_change_rate": 0.005,
                "correction_anchor_identity": 1.0,
                "rehearsal_anchor_identity": 1.0,
            },
        }],
    }
    output = tmp_path / "training_manifest.json"
    output.write_text(json.dumps(payload), encoding="utf-8")
    return output


def _cell(games: int, wins: int, *, errors: int = 0) -> dict:
    return {
        "games": games,
        "wins": wins,
        "draws": 0,
        "win_rate": wins / games,
        "one_sided_95_lower": gate.evaluate_forced_order.wilson_lower(wins, games),
        "hero_policy_errors": errors,
        "opponent_policy_errors": 0,
        "decisions": games * 20,
        "actual_order_accounting_complete": True,
    }


def _outcomes(games: int, wins: int) -> dict[int, int]:
    return {index: int(index < wins) for index in range(games)}


def test_real_reference_has_every_frozen_identity(tmp_path: Path) -> None:
    stage = tmp_path / "reference"
    stage.mkdir()
    gate._extract_archive(gate.DEFAULT_REFERENCE, stage)
    audit = gate.verify_frozen_reference(stage)
    assert audit["archive_sha256"] == gate.FROZEN_ARCHIVE_SHA256
    assert audit["model_sha256"] == gate.FROZEN_MODEL_SHA256
    assert audit["raw_deck_sha256"] == gate.FROZEN_RAW_DECK_SHA256
    assert audit["canonical_deck_sha256"] == gate.FROZEN_CANONICAL_DECK_SHA256
    assert audit["linux_engine_sha256"] == gate.FROZEN_LINUX_ENGINE_SHA256


def test_default_retention_paths_are_the_pinned_authentic_packages() -> None:
    observed = {
        name: gate.sha256_path(path).upper() for name, path in gate.DEFAULT_RETENTION.items()
    }
    assert observed == gate.EXPECTED_RETENTION_TREE_SHA256


def test_training_audit_binds_candidate_to_exact_d842_migration(tmp_path: Path) -> None:
    model = _candidate_model(tmp_path)
    manifest = _training_manifest(tmp_path, model)
    audit = gate.verify_training_audit(
        model,
        manifest,
        gate.DEFAULT_MIGRATION_AUDIT,
    )
    assert audit["qualified"]
    assert audit["anchor_source_sha256"] == gate.FROZEN_MODEL_SHA256
    assert audit["selected_run"]["model_sha256"] == gate.sha256_file(model)

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["dataset"].pop("anchor_behavior_sha256")
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(gate.GateError, match="behavior digest"):
        gate.verify_training_audit(model, manifest, gate.DEFAULT_MIGRATION_AUDIT)


def test_build_is_double_deterministic_and_pending_without_linux_smoke(tmp_path: Path) -> None:
    model = _candidate_model(tmp_path)
    manifest = _training_manifest(tmp_path, model)
    output = tmp_path / "package"
    result = gate.build_candidate(
        candidate_model=model,
        training_manifest=manifest,
        migration_manifest=gate.DEFAULT_MIGRATION_AUDIT,
        output_dir=output,
        allow_pending_linux_smoke=True,
    )
    assert result["qualified_for_evaluation"] is False
    assert result["build_audit"]["deterministic_double_build"] is True
    assert result["build_audit"]["only_policy_weights_replaced"] is True
    assert result["build_audit"]["portable_raw_source_without_file"]["raw_source_without_file"] is True
    assert (output / "grim_correction_candidate.tar.gz").is_file()
    assert (output / "development_build_manifest.json").is_file()
    assert not (output / "package_manifest.json").exists()


def test_bound_linux_report_rejects_wrong_archive(tmp_path: Path) -> None:
    archive = tmp_path / "candidate.tar.gz"
    archive.write_bytes(b"candidate")
    report = {
        "passed": True,
        "platform": "linux",
        "games": 4,
        "decisions": 12,
        "policy_errors": 0,
        "invalid_actions": 0,
        "deterministic_duplicate_decisions": True,
        "raw_source_without_file": True,
        "archive_sha256": "0" * 64,
        "model_sha256": "A" * 64,
        "raw_deck_sha256": gate.FROZEN_RAW_DECK_SHA256,
        "canonical_deck_sha256": gate.FROZEN_CANONICAL_DECK_SHA256,
        "linux_engine_sha256": gate.FROZEN_LINUX_ENGINE_SHA256,
    }
    with pytest.raises(gate.GateError, match="package binding"):
        gate.verify_linux_smoke_report(report, archive, "A" * 64)


def test_direct_gate_requires_both_orders_not_only_aggregate() -> None:
    passing = gate.direct_strength_gate(_cell(5_000, 2_800), _cell(5_000, 2_600))
    assert passing["passed"]
    hidden_regression = gate.direct_strength_gate(_cell(5_000, 3_000), _cell(5_000, 2_400))
    assert hidden_regression["aggregate"]["win_rate"] == pytest.approx(0.54)
    assert not hidden_regression["checks"]["second_order_no_regression"]
    assert not hidden_regression["passed"]


def test_retention_gate_uses_bound_and_per_opponent_veto() -> None:
    summaries = {}
    outcomes = {}
    for name in gate.DEFAULT_RETENTION:
        summaries[name] = {
            "candidate": {"first": _cell(100, 60), "second": _cell(100, 60)},
            "control": {"first": _cell(100, 50), "second": _cell(100, 50)},
        }
        outcomes[name] = {
            "candidate": {"first": _outcomes(100, 60), "second": _outcomes(100, 60)},
            "control": {"first": _outcomes(100, 50), "second": _outcomes(100, 50)},
        }
    passing = gate.retention_gate(summaries, outcomes)
    assert passing["passed"]
    assert passing["aggregate"]["rng_provenance"]["native_engine_deals_paired"] is False

    summaries["master_v1"] = {
        "candidate": {"first": _cell(100, 45), "second": _cell(100, 45)},
        "control": {"first": _cell(100, 50), "second": _cell(100, 50)},
    }
    outcomes["master_v1"] = {
        "candidate": {"first": _outcomes(100, 45), "second": _outcomes(100, 45)},
        "control": {"first": _outcomes(100, 50), "second": _outcomes(100, 50)},
    }
    vetoed = gate.retention_gate(summaries, outcomes)
    assert not vetoed["opponents"]["master_v1"]["no_regression_over_3_points"]
    assert not vetoed["passed"]


def test_schedule_is_balanced_and_arm_paired(tmp_path: Path) -> None:
    retention = {name: tmp_path / name for name in gate.DEFAULT_RETENTION}
    schedule, metadata = gate.build_evaluation_schedule(
        candidate=tmp_path / "candidate",
        control=tmp_path / "control",
        retention=retention,
        direct_games=4,
        retention_games=4,
        seed=17,
        max_decisions=200,
    )
    assert metadata["direct:first"]["games"] == 2
    for name in retention:
        candidate = metadata[f"retention:{name}:second:candidate"]
        control = metadata[f"retention:{name}:second:control"]
        assert candidate["games"] == control["games"] == 2
        assert candidate["seed"] == control["seed"]

    def fake(spec):
        cell, index, _hero, _opponent, order, _seed, _cap = spec
        return cell, index, {
            "win": index % 2,
            "draw": 0,
            "physical_seat": index % 2,
            "actual_order": order,
            "hero_errors": 0,
            "opponent_errors": 0,
            "decisions": 20,
        }

    rows = gate.execute_schedule(schedule, workers=3, runner=fake)
    assert set(rows) == set(metadata)
    for cell in metadata:
        summary, _ = gate._summarize_cell(rows[cell], metadata[cell])
        assert summary["physical_seats"]["0"]["games"] == 1
        assert summary["physical_seats"]["1"]["games"] == 1


def test_immutable_manifest_refuses_mutation(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    gate.write_immutable_json(path, {"qualified": False})
    gate.write_immutable_json(path, {"qualified": False})
    with pytest.raises(gate.GateError, match="immutable"):
        gate.write_immutable_json(path, {"qualified": True})
