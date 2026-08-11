from __future__ import annotations

from pathlib import Path

import pytest

from scripts import package_a2_finalist as a2
from scripts import package_a2_outcome_order as package


def test_require_schema2_rejects_temporal_model(monkeypatch, tmp_path: Path):
    model = tmp_path / "model.npz"
    model.write_bytes(b"fixture")
    monkeypatch.setattr(package.a2, "validate_model", lambda _path: {"model_schema_version": 3})

    with pytest.raises(a2.PackageError, match="must use schema 2"):
        package.require_schema2(model)


def test_build_is_deterministic_and_preserves_exact_a2_fallback(tmp_path: Path):
    source = a2.DEFAULT_SOURCE_ARCHIVE
    with pytest.MonkeyPatch.context() as monkeypatch:
        extracted = tmp_path / "source"
        a2.safe_extract(source, extracted)
    exact_model = extracted / a2.MODEL_MEMBER

    result = package.build_package(
        first_model=exact_model,
        second_model=exact_model,
        name="schema2_fixture",
        output_dir=tmp_path / "output",
        source_archive=source,
    )

    assert result["status"] == "packaged_unverified_by_gameplay"
    assert result["models"]["first"]["model_schema_version"] == 2
    assert result["models"]["second"]["model_schema_version"] == 2
    assert result["routing"]["pre_latch_policy"] == "byte-exact authentic A2"
    assert result["routing"]["candidate_failure_fallback"] == "byte-exact authentic A2"
    assert result["routing"]["runtime_controls"] == a2.RUNTIME_CONTROLS
    assert result["routing"]["altered_source_members"] == ["main.py"]
    assert result["verification"]["first_archive_sha256"] == result["verification"]["second_archive_sha256"]
    assert result["verification"]["sterile_init_smoke"]["passed"] is True
    assert result["deployment"] == {
        "games_run": False,
        "gameplay_promoted": False,
        "uploaded": False,
        "cloud_started": False,
    }

    archive = Path(result["output"]["archive"])
    unpacked = tmp_path / "unpacked"
    a2.safe_extract(archive, unpacked)
    assert a2.sha256_file(unpacked / a2.MODEL_MEMBER) == a2.FROZEN_SOURCE_MODEL_SHA256
    assert a2.sha256_file(unpacked / "policy_first.npz") == a2.FROZEN_SOURCE_MODEL_SHA256
    assert a2.sha256_file(unpacked / "policy_second.npz") == a2.FROZEN_SOURCE_MODEL_SHA256
    assert (unpacked / "ptcg_ai" / "a2_outcome_order_router.py").is_file()
