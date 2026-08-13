from __future__ import annotations

import json
import tarfile
from pathlib import Path

import pytest

from ptcg_ai.dipplin.cards import DECK_CSV_SHA256, DECK_ID, EXACT_DECK, deck_csv_bytes
from scripts import package_dipplin as audited
from scripts import package_dipplin_s2 as packager


def test_s2_cli_and_output_defaults_are_dedicated():
    args = packager.parse_args([])
    assert args.name == "submission"
    assert args.output_dir is None
    assert packager.DEFAULT_OUTPUT_DIR == packager.ROOT / "artifacts" / "dipplin_s2"
    assert packager.S2_DIPPLIN_MODULES == audited.D1_DIPPLIN_MODULES
    assert "search.py" in packager.S2_DIPPLIN_MODULES


def test_s2_entrypoint_pins_every_control_before_policy_import():
    source = packager._entrypoint_bytes().decode("utf-8")
    expected = {
        "PTCG_DIPPLIN_SEARCH": "1",
        "PTCG_DIPPLIN_SECOND_OPENING_V2": "1",
        "PTCG_DIPPLIN_S2": "1",
        "PTCG_DIPPLIN_GO_FIRST": "1",
        "PTCG_DIPPLIN_ROUTE_V2": "0",
        "PTCG_DIPPLIN_WORLDS": "2",
    }
    import_offset = source.index(
        "from ptcg_ai.dipplin.policy import DipplinCompetitionAgent"
    )
    for name, value in expected.items():
        assignment = f'os.environ["{name}"] = "{value}"'
        assert assignment in source
        assert source.index(assignment) < import_offset
    assert "from ptcg_ai import CompetitionAgent" not in source


def test_s2_stage_is_exact_d1_allowlist_with_source_and_tree_manifests(
    tmp_path: Path,
):
    stage = tmp_path / "stage"
    result = packager.stage_package(stage)
    expected_members = {
        "main.py",
        "deck.csv",
        "ptcg_ai/__init__.py",
        "ptcg_ai/safety.py",
        *(f"ptcg_ai/dipplin/{name}" for name in audited.D1_DIPPLIN_MODULES),
        *(f"cg/{name}" for name in audited.OFFICIAL_CG_SHA256),
    }
    assert result["variant"] == "s2"
    assert set(result["file_manifest"]) == expected_members
    assert set(result["source_file_manifest"]) == expected_members
    assert result["member_count"] == len(expected_members) == 23
    assert result["module_allowlist"] == sorted(audited.D1_DIPPLIN_MODULES)
    assert result["extracted_tree_sha256"] == packager.package_tree_sha256(stage)
    runtime_hash, runtime_members = packager.runtime_source_tree_sha256(stage)
    assert result["runtime_source_tree_sha256"] == runtime_hash
    assert result["runtime_source_members"] == runtime_members

    for relative, staged in result["file_manifest"].items():
        source = result["source_file_manifest"][relative]
        assert source["bytes"] == staged["bytes"]
        assert source["sha256"] == staged["sha256"]
        assert not Path(source["origin"]).is_absolute()
    assert result["source_file_manifest"]["main.py"]["origin"] == (
        "generated:s2_entrypoint"
    )
    assert result["source_file_manifest"]["deck.csv"]["origin"] == (
        "generated:audited_exact_deck"
    )
    assert result["source_file_manifest"]["ptcg_ai/dipplin/search.py"][
        "origin"
    ] == "ptcg_ai/dipplin/search.py"
    assert (stage / "deck.csv").read_bytes() == deck_csv_bytes()
    assert not any(
        "__pycache__" in name or name.endswith((".pyc", ".pyo"))
        for name in result["file_manifest"]
    )


def test_s2_stage_fails_closed_if_current_source_loses_its_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        packager,
        "S2_SOURCE_MARKERS",
        {"policy.py": ("S2_MARKER_THAT_MUST_NOT_EXIST",)},
    )
    with pytest.raises(packager.PackageError, match="S2 source gate is missing"):
        packager.stage_package(tmp_path / "stage")


def test_temp_s2_build_is_minimal_deterministic_sterile_and_hash_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # Poison the parent environment.  Both the generated main.py and sterile
    # smoke must prove the packaged controls are independent of these values.
    monkeypatch.setenv("PTCG_DIPPLIN_SEARCH", "0")
    monkeypatch.setenv("PTCG_DIPPLIN_SECOND_OPENING_V2", "0")
    monkeypatch.setenv("PTCG_DIPPLIN_S2", "0")
    monkeypatch.setenv("PTCG_DIPPLIN_GO_FIRST", "0")
    monkeypatch.setenv("PTCG_DIPPLIN_ROUTE_V2", "1")
    monkeypatch.setenv("PTCG_DIPPLIN_WORLDS", "4")

    output = tmp_path / "s2-output"
    result = packager.build_package(output_dir=output)
    archive = output / "submission.tar.gz"
    manifest_path = output / "submission.manifest.json"
    assert archive.is_file()
    assert manifest_path.is_file()
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == result

    assert result["schema"] == "dipplin-s2-package-manifest-v1"
    assert result["variant"] == "s2"
    assert result["runtime"]["module_allowlist"] == sorted(
        audited.D1_DIPPLIN_MODULES
    )
    assert result["runtime"]["evaluated_configuration"] == {
        "search": True,
        "second_opening_v2": True,
        "s2": True,
        "go_first": True,
        "route_v2": False,
        "search_worlds": 2,
    }
    assert result["runtime"]["learned_weights_included"] is False
    assert result["runtime"]["grim_runtime_included"] is False
    assert result["deck"] == {
        "deck_id": DECK_ID,
        "card_count": len(EXACT_DECK),
        "deck_csv_sha256": DECK_CSV_SHA256.upper(),
        "newline_terminated": True,
    }

    verification = result["verification"]
    assert verification["fresh_stage_count"] == 2
    assert verification["fresh_stage_manifests_identical"] is True
    assert verification["deterministic_double_build"] is True
    assert verification["byte_identical_double_build"] is True
    assert verification["first_archive_sha256"] == (
        verification["second_archive_sha256"]
    )
    assert result["output"]["archive_sha256"] == packager.sha256_file(archive)
    assert verification["verified_extracted_tree_sha256"] == result["output"][
        "extracted_tree_sha256"
    ]
    assert verification["verified_runtime_source_tree_sha256"] == result[
        "runtime"
    ]["runtime_source_tree_sha256"]
    assert verification["verified_file_manifest"] == result["output"][
        "file_manifest"
    ]

    smoke = verification["sterile_import"]
    assert smoke["passed"] is True
    assert smoke["command_flags"] == ["-I", "-B"]
    assert smoke["opposite_inherited_controls_overridden"] is True
    assert smoke["cache_free_after_import"] is True
    assert smoke["package_files_unchanged_after_import"] is True
    assert smoke["search_enabled"] is True
    assert smoke["second_opening_v2"] is True
    assert smoke["s2_enabled"] is True
    assert smoke["search_controller_s2_enabled"] is True
    assert smoke["go_first"] is True
    assert smoke["route_v2_enabled"] is False
    assert smoke["search_worlds"] == 2

    members = set(result["output"]["file_manifest"])
    assert members == set(result["source"]["source_file_manifest"])
    assert result["output"]["member_count"] == 23
    structure = verification["archive_structure"]
    assert structure["regular_files_only"] is True
    assert structure["sorted_members"] is True
    assert structure["portable_member_names"] is True
    assert structure["normalized_tar_metadata"] is True
    assert structure["gzip_mtime_zero"] is True
    assert structure["gzip_filename_empty"] is True
    with tarfile.open(archive, "r:gz") as handle:
        archive_members = handle.getmembers()
        assert [member.name for member in archive_members] == sorted(members)
        assert all(
            member.isfile() and member.mode == 0o644 and member.mtime == 0
            for member in archive_members
        )

    extracted = tmp_path / "extracted"
    packager.safe_extract(archive, extracted)
    assert packager.package_file_manifest(extracted) == result["output"][
        "file_manifest"
    ]
    assert packager.package_tree_sha256(extracted) == result["output"][
        "extracted_tree_sha256"
    ]
    assert packager.runtime_source_tree_sha256(extracted)[0] == result["runtime"][
        "runtime_source_tree_sha256"
    ]
    assert (extracted / "deck.csv").read_bytes() == deck_csv_bytes()
    for name, expected_hash in audited.OFFICIAL_CG_SHA256.items():
        assert packager.sha256_file(extracted / "cg" / name) == expected_hash
        assert result["engine"]["official_template_file_sha256"][name] == (
            expected_hash
        )
    assert result["engine"]["linux_amd64_sha256"] == (
        audited.OFFICIAL_CG_SHA256["libcg.so"]
    )
    assert result["deployment"] == {
        "games_run_by_packager": False,
        "uploaded": False,
        "cloud_started": False,
    }
