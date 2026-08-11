from __future__ import annotations

import io
import json
import tarfile
import zipfile
from pathlib import Path

import numpy as np
import pytest

from scripts import package_a2_finalist as packager


@pytest.fixture(scope="module")
def source_model(tmp_path_factory: pytest.TempPathFactory) -> Path:
    stage = tmp_path_factory.mktemp("a2-finalist-source")
    packager.safe_extract(packager.DEFAULT_SOURCE_ARCHIVE, stage)
    verified = packager.verify_source_runtime(stage)
    assert verified["extracted_tree_sha256"] == packager.FROZEN_SOURCE_TREE_SHA256
    assert verified["runtime_source_tree_sha256"] == packager.FROZEN_RUNTIME_SOURCE_TREE_SHA256
    return stage / packager.MODEL_MEMBER


def _write_variant(source: Path, destination: Path, schema: int) -> Path:
    with np.load(source, allow_pickle=False) as loaded:
        arrays = {name: np.asarray(loaded[name]).copy() for name in loaded.files}
    arrays["score_b"] = arrays["score_b"].copy()
    arrays["score_b"][0] += np.asarray(0.125, dtype=arrays["score_b"].dtype)
    if schema == 3:
        numeric = arrays["numeric_w"]
        arrays["numeric_w"] = np.vstack(
            [numeric, np.zeros((1, numeric.shape[1]), dtype=numeric.dtype)]
        )
    arrays["model_schema_version"] = np.asarray(schema, dtype=np.int16)
    np.savez(destination, **arrays)
    return destination


@pytest.mark.parametrize("schema", [2, 3])
def test_build_clones_a2_replaces_only_model_and_smokes_schema(
    tmp_path: Path,
    source_model: Path,
    schema: int,
):
    candidate = _write_variant(source_model, tmp_path / f"schema{schema}.npz", schema)
    output = tmp_path / "output"
    result = packager.build_finalist(
        candidate_model=candidate,
        name=f"finalist_schema{schema}",
        output_dir=output,
    )
    archive = output / f"finalist_schema{schema}.tar.gz"
    manifest_path = output / f"finalist_schema{schema}.manifest.json"

    assert archive.is_file()
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == result
    assert result["candidate_model"]["model_schema_version"] == schema
    assert result["output"]["archive_sha256"] == packager.sha256_file(archive)
    assert result["source_runtime"]["archive_sha256"] == packager.FROZEN_SOURCE_ARCHIVE_SHA256
    assert result["source_runtime"]["runtime_source_tree_sha256"] == packager.FROZEN_RUNTIME_SOURCE_TREE_SHA256
    assert result["source_runtime"]["deck"]["card_count"] == 60
    assert result["runtime"]["runtime_controls"] == packager.RUNTIME_CONTROLS
    assert result["runtime"]["altered_source_members"] == [packager.MODEL_MEMBER]
    assert result["runtime"]["only_policy_weights_replaced"] is True
    assert result["verification"]["deterministic_tar"] is True
    assert result["verification"]["first_archive_sha256"] == result["verification"]["second_archive_sha256"]
    assert result["verification"]["sterile_init_smoke"]["passed"] is True
    assert result["verification"]["sterile_init_smoke"]["deck_card_count"] == 60
    assert result["verification"]["sterile_init_smoke"]["model_schema_version"] == schema
    assert result["deployment"] == {
        "games_run": False,
        "uploaded": False,
        "cloud_started": False,
    }

    source_stage = tmp_path / "source-stage"
    output_stage = tmp_path / "output-stage"
    packager.safe_extract(packager.DEFAULT_SOURCE_ARCHIVE, source_stage)
    packager.safe_extract(archive, output_stage)
    source_hashes = packager.package_file_hashes(source_stage)
    output_hashes = packager.package_file_hashes(output_stage)
    assert set(source_hashes) == set(output_hashes)
    assert [name for name in source_hashes if source_hashes[name] != output_hashes[name]] == [
        packager.MODEL_MEMBER
    ]
    assert packager.sha256_file(output_stage / packager.MODEL_MEMBER) == packager.sha256_file(candidate)
    assert packager.runtime_source_tree_sha256(output_stage)[0] == packager.FROZEN_RUNTIME_SOURCE_TREE_SHA256
    assert not any("__pycache__" in path.parts or path.suffix == ".pyc" for path in output_stage.rglob("*"))


@pytest.mark.parametrize(
    ("member_name", "message"),
    [
        ("../escape.txt", "unsafe tar member"),
        ("ptcg_ai/__pycache__/model.pyc", "cache tar member"),
    ],
)
def test_safe_extract_rejects_traversal_and_caches(
    tmp_path: Path,
    member_name: str,
    message: str,
):
    archive = tmp_path / "unsafe.tar.gz"
    payload = b"bad"
    with tarfile.open(archive, "w:gz") as handle:
        info = tarfile.TarInfo(member_name)
        info.size = len(payload)
        handle.addfile(info, io.BytesIO(payload))
    destination = tmp_path / "destination"
    with pytest.raises(packager.PackageError, match=message):
        packager.safe_extract(archive, destination)
    assert not (tmp_path / "escape.txt").exists()


def test_model_validation_rejects_npz_path_traversal(tmp_path: Path):
    candidate = tmp_path / "unsafe.npz"
    with zipfile.ZipFile(candidate, "w") as archive:
        archive.writestr("../model_schema_version.npy", b"not-an-array")
    with pytest.raises(packager.PackageError, match="unsafe npz member"):
        packager.validate_model(candidate)


def test_model_validation_rejects_unsupported_schema(tmp_path: Path, source_model: Path):
    candidate = _write_variant(source_model, tmp_path / "schema1.npz", 1)
    with pytest.raises(packager.PackageError, match="schema 2 or 3"):
        packager.validate_model(candidate)


def test_build_rejects_non_pinned_source_and_unsafe_name(tmp_path: Path, source_model: Path):
    fake_source = tmp_path / "fake.tar.gz"
    fake_source.write_bytes(b"not the authentic A2 archive")
    with pytest.raises(packager.PackageError, match="source archive mismatch"):
        packager.build_finalist(
            candidate_model=source_model,
            name="candidate",
            output_dir=tmp_path / "wrong-source-output",
            source_archive=fake_source,
        )
    with pytest.raises(packager.PackageError, match="invalid finalist name"):
        packager.build_finalist(
            candidate_model=source_model,
            name="../candidate",
            output_dir=tmp_path / "unsafe-name-output",
        )
