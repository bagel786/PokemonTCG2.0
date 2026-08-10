from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest

from scripts import build_grim_guardrail_candidate as builder


def test_real_reference_is_fully_hash_pinned(tmp_path: Path):
    stage = tmp_path / "reference"
    stage.mkdir()
    builder.safe_extract(builder.DEFAULT_BASE, stage)
    verified = builder.verify_frozen_tree(stage)
    assert verified["model_sha256"] == builder.FROZEN_MODEL_SHA256
    assert verified["raw_deck_sha256"] == builder.FROZEN_RAW_DECK_SHA256
    assert verified["canonical_deck_sha256"] == builder.FROZEN_CANONICAL_DECK_SHA256
    assert verified["engine_sha256"] == builder.FROZEN_ENGINE_HASHES
    assert verified["original_source_sha256"] == builder.FROZEN_SOURCE_HASHES


def test_stage_wires_exact_rank_count_and_only_search_disabled_narrow_runtime(tmp_path: Path):
    stage = tmp_path / "candidate"
    stage.mkdir()
    metadata = builder.stage_candidate(builder.DEFAULT_BASE, stage)
    model = (stage / "ptcg_ai/model.py").read_text(encoding="utf-8")
    agent = (stage / "ptcg_ai/agent.py").read_text(encoding="utf-8")

    assert "GrimRuntimePolicy(proof=SearchDisabledProof())" in model
    assert "runtime_policy.choose(obs, ranked, desired)" in model
    assert "baseline = sanitize_selection(obs.select, ranked, desired)" in model
    assert "except Exception:\n            return baseline" in model
    assert "self.policy.reset()" in agent
    assert "except Exception:\n                    pass" in agent
    assert "GrimFloorController" not in model
    assert metadata["runtime"]["native_search_enabled"] is False
    assert metadata["runtime"]["proof_component"] == "SearchDisabledProof"
    assert metadata["runtime"]["broad_floor_controller"] is False
    assert metadata["runtime"]["native_audit_terminal_branches"] == {
        "terminal": 0,
        "sampled": 100,
    }
    assert metadata["runtime"]["native_audit_deterministic_classifications"] is False
    assert set(metadata["runtime_source_sha256"]) == {
        f"ptcg_ai/{name}" for name in builder.RUNTIME_DEPENDENCIES
    }
    for relative, digest in metadata["runtime_source_sha256"].items():
        assert builder.sha256_file(stage / relative) == digest
    assert not any((stage / name).exists() for name in builder.FORBIDDEN_RUNTIME_FILES)
    assert builder.sha256_file(stage / "policy_weights.npz") == builder.FROZEN_MODEL_SHA256
    assert builder.sha256_file(stage / "deck.csv") == builder.FROZEN_RAW_DECK_SHA256
    for relative, digest in builder.FROZEN_ENGINE_HASHES.items():
        assert builder.sha256_file(stage / relative) == digest


def test_deck_handshake_falls_through_even_if_runtime_reset_raises(tmp_path: Path):
    stage = tmp_path / "candidate"
    stage.mkdir()
    builder.stage_candidate(builder.DEFAULT_BASE, stage)
    agent_source = (stage / "ptcg_ai/agent.py").read_text(encoding="utf-8")
    assert (
        "if hasattr(self.policy, \"reset\"):\n"
        "                try:\n"
        "                    self.policy.reset()\n"
        "                except Exception:\n"
        "                    pass\n"
        "            return list(self.deck)"
    ) in agent_source


def test_patch_refuses_an_ambiguous_or_non_pinned_model(tmp_path: Path):
    stage = tmp_path / "candidate"
    stage.mkdir()
    builder.safe_extract(builder.DEFAULT_BASE, stage)
    model = stage / "ptcg_ai/model.py"
    model.write_text(model.read_text(encoding="utf-8") + "\n# modified\n", encoding="utf-8")
    with pytest.raises(builder.BuildError, match="pinned hash mismatch"):
        builder.verify_frozen_tree(stage)


def test_safe_extract_refuses_parent_traversal(tmp_path: Path):
    archive = tmp_path / "unsafe.tar.gz"
    payload = b"escape"
    with tarfile.open(archive, "w:gz") as handle:
        info = tarfile.TarInfo("../escape.txt")
        info.size = len(payload)
        handle.addfile(info, io.BytesIO(payload))
    destination = tmp_path / "destination"
    destination.mkdir()
    with pytest.raises(builder.BuildError, match="unsafe archive member"):
        builder.safe_extract(archive, destination)
    assert not (tmp_path / "escape.txt").exists()


@pytest.mark.skipif(not __import__("sys").platform.startswith("win"), reason="Windows smoke only")
def test_build_is_byte_deterministic_cache_free_and_raw_source_smoked(tmp_path: Path):
    output = tmp_path / "output"
    result = builder.build_candidate(base_archive=builder.DEFAULT_BASE, output_dir=output)
    archive = output / builder.ARCHIVE_NAME
    extracted = output / builder.EXTRACTED_NAME
    manifest_path = output / builder.MANIFEST_NAME

    assert archive.is_file()
    assert extracted.is_dir()
    assert manifest_path.is_file()
    assert result["archive_sha256"] == builder.sha256_file(archive)
    assert result["verification"]["deterministic_double_build"] is True
    assert result["verification"]["first_archive_sha256"] == result["archive_sha256"]
    assert result["verification"]["second_archive_sha256"] == result["archive_sha256"]
    assert result["verification"]["fresh_extraction_count"] == 2
    assert result["verification"]["caches_excluded"] is True
    assert result["verification"]["raw_source_execution_without_file"] is True
    smoke = result["verification"]["windows_smoke"]
    assert smoke["passed"] is True
    assert smoke["handshake_reset"] is True
    assert smoke["handshake_reset_failure_fallthrough"] is True
    assert smoke["exact_rank_count_forwarding"] is True
    assert smoke["frozen_exception_fallback"] is True
    assert smoke["native_search_enabled"] is False

    measured = builder.package_file_hashes(extracted)
    assert measured == result["package_file_sha256"]
    assert builder.tree_digest(measured) == result["package_tree_sha256"]
    assert all("__pycache__" not in name for name in measured)
    assert all(not name.endswith((".pyc", ".pyo")) for name in measured)
    assert set(builder.FORBIDDEN_RUNTIME_FILES).isdisjoint(measured)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest == result
    assert manifest["build_constraints"] == {
        "temperature": 0,
        "model_retrained": False,
        "deck_changed": False,
        "games_run": False,
        "calibration_accessed": False,
        "linux_run": False,
        "upload_performed": False,
        "cloud_used": False,
    }

    with tarfile.open(archive, "r:gz") as handle:
        names = {member.name for member in handle.getmembers() if member.isfile()}
    assert names == set(measured)


def test_build_rejects_wrong_base_archive_before_creating_candidate(tmp_path: Path):
    fake = tmp_path / "fake.tar.gz"
    fake.write_bytes(b"not the pinned archive")
    output = tmp_path / "output"
    with pytest.raises(builder.BuildError, match="pinned base archive mismatch"):
        builder.build_candidate(base_archive=fake, output_dir=output)
    assert not (output / builder.ARCHIVE_NAME).exists()
