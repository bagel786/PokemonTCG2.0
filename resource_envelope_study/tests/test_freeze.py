from __future__ import annotations

from pathlib import Path

import pytest

from resource_envelope_study.canonical import hash_file
from resource_envelope_study.freeze import (
    ARTIFACT_BINDINGS,
    TOP_LEVEL_BINDINGS,
    validate_freeze_manifest,
)


def _frozen_manifest(root: Path) -> dict:
    frozen_dir = root / "resource_envelope_study" / "frozen-test-inputs"
    frozen_dir.mkdir(parents=True)
    entries: dict[str, dict] = {}
    for logical_id, role in [
        *TOP_LEVEL_BINDINGS.values(),
        *ARTIFACT_BINDINGS.values(),
    ]:
        if logical_id in entries:
            assert entries[logical_id]["role"] == role
            continue
        path = frozen_dir / f"{logical_id}.bin"
        path.write_bytes(f"locked:{logical_id}\n".encode())
        entries[logical_id] = {
            "logical_id": logical_id,
            "path": path.relative_to(root).as_posix(),
            "sha256": hash_file(path),
            "role": role,
        }
    by_id = {entry["logical_id"]: entry for entry in entries.values()}
    artifact_hashes = {
        key: by_id[logical_id]["sha256"]
        for key, (logical_id, _role) in ARTIFACT_BINDINGS.items()
    }
    return {
        "schema_version": "freeze-manifest-1.0.0",
        "status": "FROZEN",
        "base_commit": "a" * 40,
        "branch": "paper/resource-envelope-search-20260826",
        "protocol_commit": "b" * 40,
        "human_approval": None,
        "final_acquisition_authorized": False,
        "unresolved": [],
        **{
            field: by_id[logical_id]["sha256"]
            for field, (logical_id, _role) in TOP_LEVEL_BINDINGS.items()
        },
        "artifact_hashes": artifact_hashes,
        "inventory": {
            "frozen_inputs": list(entries.values()),
            "expected_outputs": [
                {
                    "logical_id": "final-analysis-summary",
                    "path": "resource_envelope_study/runs/final/analysis-summary.json",
                    "schema_version": "analysis-summary-1.0.0",
                    "producer": "resource_envelope_study.analysis",
                    "phase": "final",
                    "cardinality": 1,
                }
            ],
        },
        "note": "test fixture",
    }


def _entry(manifest: dict, logical_id: str) -> dict:
    return next(
        item
        for item in manifest["inventory"]["frozen_inputs"]
        if item["logical_id"] == logical_id
    )


def test_placeholder_is_inert() -> None:
    placeholder = {
        "schema_version": "freeze-manifest-1.0.0",
        "status": "NOT_FROZEN",
        "final_acquisition_authorized": False,
    }
    assert validate_freeze_manifest(placeholder)["status"] == "NOT_FROZEN"
    with pytest.raises(RuntimeError, match="not FROZEN"):
        validate_freeze_manifest(placeholder, require_final_authorized=True)


def test_frozen_inventory_verifies_files_and_cannot_hash_itself(tmp_path: Path) -> None:
    manifest = _frozen_manifest(tmp_path)
    freeze_path = tmp_path / "resource_envelope_study" / "FREEZE_MANIFEST.json"
    validate_freeze_manifest(
        manifest,
        repository_root=tmp_path,
        freeze_manifest_path=freeze_path,
        verify_files=True,
    )
    _entry(manifest, "source.analysis")["path"] = (
        "resource_envelope_study/FREEZE_MANIFEST.json"
    )
    with pytest.raises(ValueError, match="may not hash itself"):
        validate_freeze_manifest(
            manifest,
            repository_root=tmp_path,
            freeze_manifest_path=freeze_path,
            verify_files=True,
        )


def test_frozen_inventory_rejects_changed_input(tmp_path: Path) -> None:
    manifest = _frozen_manifest(tmp_path)
    analysis_entry = _entry(manifest, "source.analysis")
    (tmp_path / analysis_entry["path"]).write_bytes(b"changed\n")
    with pytest.raises(RuntimeError, match="hash mismatch"):
        validate_freeze_manifest(
            manifest,
            repository_root=tmp_path,
            freeze_manifest_path=(
                tmp_path / "resource_envelope_study" / "FREEZE_MANIFEST.json"
            ),
            verify_files=True,
        )


def test_digest_cannot_impersonate_another_logical_role(tmp_path: Path) -> None:
    manifest = _frozen_manifest(tmp_path)
    manifest["final_manifest_sha256"] = manifest["pilot_manifest_sha256"]
    with pytest.raises(ValueError, match="bound inventory path"):
        validate_freeze_manifest(manifest)


def test_expected_output_must_stay_below_runs_directory(tmp_path: Path) -> None:
    manifest = _frozen_manifest(tmp_path)
    manifest["inventory"]["expected_outputs"][0]["path"] = (
        "resource_envelope_study/analysis.py"
    )
    with pytest.raises(ValueError, match="must be a file below"):
        validate_freeze_manifest(manifest)


def test_final_authorization_is_structured_and_temporally_bound(tmp_path: Path) -> None:
    manifest = _frozen_manifest(tmp_path)
    manifest["final_acquisition_authorized"] = True
    manifest["human_approval"] = {
        "approved": True,
        "phase": "final",
        "protocol_commit": "c" * 40,
        "approval_commit": "d" * 40,
        "approval_id": "human-approval-test",
        "attestation_path": "resource_envelope_study/authorizations/final.json",
        "attestation_sha256": "e" * 64,
    }
    with pytest.raises(ValueError, match="does not name"):
        validate_freeze_manifest(manifest, require_final_authorized=True)
    manifest["human_approval"]["protocol_commit"] = "b" * 40
    assert validate_freeze_manifest(
        manifest, require_final_authorized=True
    )["final_acquisition_authorized"] is True
    manifest["human_approval"]["approval_commit"] = "b" * 40
    with pytest.raises(ValueError, match="must occur after"):
        validate_freeze_manifest(manifest, require_final_authorized=True)


def test_integer_one_cannot_authorize_final_acquisition(tmp_path: Path) -> None:
    manifest = _frozen_manifest(tmp_path)
    manifest["final_acquisition_authorized"] = 1
    with pytest.raises(ValueError, match="must be boolean"):
        validate_freeze_manifest(manifest)
