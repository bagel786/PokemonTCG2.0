from __future__ import annotations

import contextlib
import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_sealed_grim_holdout as sealed


DECK = [
    7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
    104, 104, 112, 112, 112, 112,
    646, 646, 646, 646, 647, 647, 647, 648, 648, 648,
    860, 860, 1079, 1079, 1079, 1080,
    1086, 1086, 1086, 1086, 1097, 1097, 1097, 1122,
    1137, 1152, 1152, 1152, 1152, 1182, 1182,
    1219, 1219, 1219, 1219, 1227, 1227, 1227, 1227,
    1231, 1259, 1259, 1259, 1259,
]


def _write_gzip(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.GzipFile(filename="", mode="wb", fileobj=path.open("wb"), mtime=0) as handle:
        for row in rows:
            handle.write((sealed.canonical_json(row) + "\n").encode())


def _unit(split: str, episode: str, *, atom: str | None = None) -> dict:
    return {
        "schema_version": 1,
        "unit_type": "whole_episode_team",
        "split": split,
        "episode_id": episode,
        "submission_id": 55323437,
        "hero_seat": 0,
        "grouping_key": f"group:{episode}",
        "grouping_atoms": [atom or f"episode:{episode}"],
        "required_labels_complete": True,
        "frozen_model_sha256": sealed.disagreements.FROZEN_MODEL_SHA256,
        "hero_deck_canonical_sha256": sealed.disagreements.FROZEN_DECK_CANONICAL_SHA256,
    }


def _make_bank(tmp_path: Path, rows_by_split: dict[str, list[dict]] | None = None) -> Path:
    root = tmp_path / "bank"
    rows_by_split = rows_by_split or {
        "development": [_unit("development", "dev")],
        "calibration": [_unit("calibration", "cal")],
        "untouched_holdout": [_unit("untouched_holdout", "final")],
    }
    split_values = {}
    for split in sealed.ALL_SPLITS:
        rows = rows_by_split[split]
        shard = root / f"{split}.jsonl.gz"
        _write_gzip(shard, rows)
        value = {
            "schema_version": 1,
            "split": split,
            "untouched": split == sealed.HOLDOUT_SPLIT,
            "training_use": (
                "forbidden_until_final_evaluation"
                if split == sealed.HOLDOUT_SPLIT
                else "allowed"
            ),
            "shard": shard.name,
            "shard_sha256": sealed.sha256_file(shard),
            "units": len(rows),
            "episodes": len({row["episode_id"] for row in rows}),
            "grouping_keys": len({row["grouping_key"] for row in rows}),
        }
        manifest_path = root / "manifests" / f"{split}.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
        split_values[split] = value
    manifest = {
        "schema_version": 1,
        "offline_only": True,
        "public_only": True,
        "split_unit": "whole_episode_team",
        "frozen_model_sha256": sealed.disagreements.FROZEN_MODEL_SHA256,
        "expected_deck_canonical_sha256": sealed.disagreements.FROZEN_DECK_CANONICAL_SHA256,
        "source_manifest_sha256": "A" * 64,
        "split_seed": "synthetic",
        "strict_lineage_allowlist": [55323437],
        "splits": split_values,
    }
    manifest["bank_id"] = sealed._bank_id(manifest)
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return root


def _proposer_metadata() -> list[dict]:
    return [
        {"name": name, "native_search_executed": False, "source_tree_sha256": f"{index:064X}"}
        for index, name in enumerate(sealed.FIXED_PROPOSER_NAMES, 1)
    ]


def test_bank_is_hash_bound_and_whole_episode_splits_are_disjoint(tmp_path):
    root = _make_bank(tmp_path)
    bank = sealed.inspect_hash_bound_bank(root)
    rows = sealed.load_and_verify_whole_episode_splits(bank)
    assert [row["episode_id"] for row in rows["untouched_holdout"]] == ["final"]

    overlap_root = _make_bank(
        tmp_path / "overlap",
        {
            "development": [_unit("development", "same")],
            "calibration": [_unit("calibration", "cal")],
            "untouched_holdout": [_unit("untouched_holdout", "same")],
        },
    )
    with pytest.raises(ValueError, match="episode leakage"):
        sealed.load_and_verify_whole_episode_splits(
            sealed.inspect_hash_bound_bank(overlap_root)
        )


def test_grouping_atom_leakage_is_rejected_even_with_distinct_episode_ids(tmp_path):
    root = _make_bank(
        tmp_path,
        {
            "development": [_unit("development", "dev", atom="opponent_team:x")],
            "calibration": [_unit("calibration", "cal")],
            "untouched_holdout": [
                _unit("untouched_holdout", "final", atom="opponent_team:x")
            ],
        },
    )
    with pytest.raises(ValueError, match="grouping-atom leakage"):
        sealed.load_and_verify_whole_episode_splits(sealed.inspect_hash_bound_bank(root))


def test_freeze_creation_is_self_hashed_and_immutable(tmp_path, monkeypatch):
    bank_root = _make_bank(tmp_path)
    candidate = tmp_path / "candidate.npz"
    candidate_manifest = tmp_path / "training.json"
    training = tmp_path / "training.jsonl.gz"
    training_manifest = sealed.manifest_path_for(training)
    anchor = tmp_path / "anchor.npz"
    calibration = tmp_path / "calibration.json"
    for path in (candidate, candidate_manifest, training, training_manifest, anchor, calibration):
        path.write_bytes(path.name.encode())

    training_bank = SimpleNamespace(
        path=training.resolve(),
        sha256=sealed.sha256_file(training),
        manifest_path=training_manifest.resolve(),
        manifest_sha256=sealed.sha256_file(training_manifest),
        rows=({"episode_id": "dev"},),
    )
    monkeypatch.setattr(sealed.proxy_gate, "load_certified_bank", lambda *a, **k: training_bank)
    monkeypatch.setattr(
        sealed.proxy_gate,
        "verify_candidate_manifest",
        lambda *a, **k: ({"sha256": sealed.sha256_file(candidate_manifest)}, anchor),
    )
    monkeypatch.setattr(
        sealed.proxy_gate,
        "verify_models",
        lambda *a, **k: {"candidate_sha256": sealed.sha256_file(candidate)},
    )
    monkeypatch.setattr(
        sealed.proxy_gate,
        "_verify_frozen_calibration",
        lambda *a, **k: {"manifest_digest_sha256": "C" * 64},
    )
    output = tmp_path / "freeze.json"
    result = sealed.create_candidate_freeze_manifest(
        candidate_path=candidate,
        candidate_training_manifest=candidate_manifest,
        training_labels=training,
        anchor_path=anchor,
        calibration_gate_manifest=calibration,
        bank_dir=bank_root,
        output_path=output,
        proposer_metadata=_proposer_metadata(),
    )
    assert result["status"] == "frozen"
    assert sealed._self_hashed(result)
    sealed.write_immutable_json(output, result)
    with pytest.raises(sealed.SealedHoldoutError, match="immutable"):
        sealed.write_immutable_json(output, {**result, "status": "changed"})

    candidate.write_bytes(b"changed")
    with pytest.raises(ValueError, match="candidate artifact"):
        sealed.verify_candidate_freeze_manifest(output, proposer_metadata=_proposer_metadata())


def _disagreement_row() -> dict:
    observation = {
        "current": {"yourIndex": 0},
        "select": {
            "minCount": 1,
            "maxCount": 1,
            "option": [{"type": 7, "index": 0}, {"type": 7, "index": 1}],
        },
    }
    baseline_semantic = {"selected_count": 1, "options": [{"type": 7, "source": None}]}
    candidate_semantic = {
        "selected_count": 1,
        "options": [{"type": 7, "source": {"card_id": 123}}],
    }
    observation_id = sealed.correction_miner._stable_json_id(observation)
    baseline_id = sealed.correction_miner._stable_json_id(baseline_semantic)
    candidate_id = sealed.correction_miner._stable_json_id(candidate_semantic)
    semantic_pair_id = sealed.correction_miner._stable_json_id(
        {
            "observation_sha256": observation_id,
            "baseline_semantic_id": baseline_id,
            "candidate_semantic_id": candidate_id,
        }
    )
    row = {
        "schema_version": 1,
        "record_type": "semantic_disagreement",
        "split": sealed.HOLDOUT_SPLIT,
        "episode_id": "final",
        "hero_seat": 0,
        "replay_step_t": 4,
        "observation": observation,
        "observation_sha256": observation_id,
        "features": {"feature_version": 2, "global": [], "options": []},
        "baseline_action": [0],
        "baseline_semantic": baseline_semantic,
        "baseline_semantic_id": baseline_id,
        "candidate_action": [1],
        "candidate_semantic": candidate_semantic,
        "candidate_semantic_id": candidate_id,
        "semantic_pair_id": semantic_pair_id,
        "semantic_action_pair_id": sealed.correction_miner._stable_json_id(
            {"baseline": baseline_semantic, "candidate": candidate_semantic}
        ),
        "opponent_deck": [1] * 60,
        "opponent_deck_canonical_sha256": sealed.correction_miner._stable_json_id(
            ",".join(["1"] * 60)
        ),
        "proposers": [sealed.FIXED_PROPOSER_NAMES[0]],
        "proposer_actions": {sealed.FIXED_PROPOSER_NAMES[0]: [1]},
        "actual_order": "second",
        "target": 0,
    }
    # The deck digest uses the comma payload directly, not canonical JSON.
    import hashlib

    row["opponent_deck_canonical_sha256"] = hashlib.sha256(
        ",".join(["1"] * 60).encode("ascii")
    ).hexdigest().upper()
    row["record_id"] = sealed.correction_miner._stable_json_id(
        {
            "split": sealed.HOLDOUT_SPLIT,
            "episode_id": "final",
            "hero_seat": 0,
            "replay_step_t": 4,
            "semantic_pair_id": semantic_pair_id,
        }
    )
    return row


def _admitted_result(row: dict) -> dict:
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
    signature = sealed.stable_json_id({"worlds": worlds})
    return {
        "key": row["record_id"],
        "admitted": True,
        "reason": "admitted",
        "baseline_action": [0],
        "candidate_action": [1],
        "decision": {
            "admitted": True,
            "reason": "admitted",
            "expected_worlds": 8,
            "covered_worlds": 8,
            "noninferior_worlds": 8,
            "strict_better_worlds": 8,
            "required_strict_worlds": 4,
        },
        "boundary_hash": "D" * 64,
        "coverage": {"baseline": 8, "candidate": 8},
        "worlds": worlds,
        "errors": [],
        "repeat_count": 3,
        "repeat_signature": signature,
        "repeat_signatures": [signature] * 3,
        "worker_error": None,
    }


def test_two_pass_sealed_intersection_and_hidden_metadata_rejection(tmp_path, monkeypatch):
    row = _disagreement_row()
    disagreement_path = tmp_path / "disagreements.jsonl.gz"
    _write_gzip(disagreement_path, [row])
    model = tmp_path / "model.npz"
    model.write_bytes(b"synthetic-model")
    model_hash = sealed.sha256_file(model)
    deck = tmp_path / "deck.csv"
    deck.write_text("\n".join(map(str, DECK)) + "\n")
    monkeypatch.setattr(sealed.correction_miner, "FROZEN_D842_MODEL_SHA256", model_hash)
    monkeypatch.setattr(sealed.proxy_gate, "FROZEN_D842_MODEL_SHA256", model_hash)
    monkeypatch.setattr(sealed.proxy_gate, "LEGACY_D842_BEHAVIOR_SHA256", "B" * 64)
    monkeypatch.setattr(
        sealed.correction_miner, "model_behavior_digest", lambda _path: "B" * 64
    )

    def evaluate(rows, *_args):
        return [(source, _admitted_result(source)) for source in rows]

    config = sealed.CorrectionConfig(worlds=8, seed=20260810)
    passes = [
        sealed.run_certification_pass(
            rows=[row],
            disagreement_path=disagreement_path,
            model_path=model,
            hero_deck_path=deck,
            output_path=tmp_path / f"pass-{ordinal}.jsonl.gz",
            config=config,
            certification_repeats=3,
            workers=1,
            pass_ordinal=ordinal,
            evaluation_runner=evaluate,
        )
        for ordinal in (1, 2)
    ]
    intersection = sealed.create_sealed_intersection(
        passes, tmp_path / "intersection.jsonl.gz"
    )
    assert intersection["sealed_holdout_used"] is True
    assert intersection["counts"]["input_passes"] == 2
    assert intersection["counts"]["retained_corrections"] == 1
    assert intersection["rows"][0]["split"] == sealed.HOLDOUT_SPLIT

    poisoned = json.loads(sealed.canonical_json(passes[1]))
    poisoned["rows"][0]["opponent_deck"] = [1] * 60
    with pytest.raises(ValueError, match="metadata is forbidden"):
        sealed.create_sealed_intersection(
            [passes[0], poisoned], tmp_path / "poisoned.jsonl.gz"
        )


def test_orchestrator_invokes_proxy_with_explicit_holdout_and_fixed_proposers(
    tmp_path, monkeypatch
):
    bank_root = _make_bank(tmp_path)
    bank = sealed.inspect_hash_bound_bank(bank_root)
    files = {}
    for name in ("freeze", "candidate", "training_manifest", "training", "anchor", "calibration"):
        path = tmp_path / name
        path.write_bytes(name.encode())
        files[name] = path
    metadata = _proposer_metadata()
    frozen = sealed.FrozenCandidate(
        manifest_path=files["freeze"],
        manifest_sha256=sealed.sha256_file(files["freeze"]),
        manifest_digest_sha256="F" * 64,
        candidate_path=files["candidate"],
        candidate_training_manifest=files["training_manifest"],
        training_labels=files["training"],
        anchor_path=files["anchor"],
        calibration_gate_manifest=files["calibration"],
        bank=bank,
        proposer_metadata=tuple(metadata),
    )
    monkeypatch.setattr(sealed, "fixed_proposer_metadata", lambda _specs: metadata)
    monkeypatch.setattr(
        sealed, "verify_candidate_freeze_manifest", lambda *a, **k: frozen
    )
    split_rows = {
        "development": [_unit("development", "dev")],
        "calibration": [_unit("calibration", "cal")],
        "untouched_holdout": [_unit("untouched_holdout", "final")],
    }
    monkeypatch.setattr(sealed, "load_and_verify_whole_episode_splits", lambda _bank: split_rows)

    class FakePolicy:
        def __init__(self, name, metadata):
            self.name = name
            self.metadata = metadata

    @contextlib.contextmanager
    def fake_baseline(_archive):
        yield FakePolicy("d842", {"name": "d842"})

    monkeypatch.setattr(sealed.disagreements, "frozen_baseline", fake_baseline)
    by_name = {item["name"]: item for item in metadata}
    monkeypatch.setattr(
        sealed.disagreements,
        "LoadedPackagePolicy",
        lambda spec: FakePolicy(spec.name, by_name[spec.name]),
    )
    seen = {}

    def fake_disagreements(**kwargs):
        assert tuple(item.name for item in kwargs["candidates"]) == sealed.FIXED_PROPOSER_NAMES
        assert kwargs["episode_rows"] == split_rows["untouched_holdout"]
        _write_gzip(kwargs["output_path"], [{"episode_id": "final"}])
        return {
            "rows": [{"episode_id": "final"}],
            "output": str(kwargs["output_path"].resolve()),
            "output_sha256": sealed.sha256_file(kwargs["output_path"]),
            "disagreement_rows": 1,
        }

    monkeypatch.setattr(sealed, "build_sealed_disagreements", fake_disagreements)

    def fake_pass(**kwargs):
        path = kwargs["output_path"]
        _write_gzip(path, [])
        manifest = sealed.manifest_path_for(path)
        manifest.write_text("{}\n")
        return {"output": str(path.resolve()), "rows": []}

    monkeypatch.setattr(sealed, "run_certification_pass", fake_pass)

    def fake_intersection(_passes, output_path):
        _write_gzip(Path(output_path), [])
        return {
            "output": str(Path(output_path).resolve()),
            "output_sha256": sealed.sha256_file(output_path),
            "rows": [{"episode_id": "final"}],
        }

    monkeypatch.setattr(sealed, "create_sealed_intersection", fake_intersection)

    def fake_proxy(**kwargs):
        seen.update(kwargs)
        report = {
            "passed": True,
            "expected_split": kwargs["expected_split"],
            "manifest_digest_sha256": "E" * 64,
        }
        Path(kwargs["output_path"]).write_text(json.dumps(report))
        return report

    result = sealed.run_sealed_holdout(
        candidate_freeze_manifest=files["freeze"],
        replay_root=tmp_path,
        reference_archive=tmp_path / "reference.tar.gz",
        search_model=tmp_path / "search.npz",
        hero_deck=tmp_path / "deck.csv",
        output_dir=tmp_path / "output",
        unseal_receipt=tmp_path / "unseal.json",
        workers=1,
        proxy_runner=fake_proxy,
    )
    assert result["passed"] is True
    assert result["proposals"]["candidate_generated"] is False
    assert seen["expected_split"] == "untouched_holdout"
    assert seen["candidate_path"] == files["candidate"]
    assert seen["calibration_gate_manifest"] == files["calibration"]
