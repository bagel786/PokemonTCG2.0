from __future__ import annotations

import io
import json
import platform
import tarfile
from pathlib import Path

import pytest

from ptcg_ai.dipplin.cards import DECK_CSV_SHA256, DECK_ID, EXACT_DECK, deck_csv_bytes
from scripts import package_dipplin as packager


def test_cli_requires_an_explicit_policy_variant():
    with pytest.raises(SystemExit):
        packager.parse_args([])


def test_build_d0_is_direct_exact_minimal_and_deterministic(tmp_path: Path):
    output = tmp_path / "output"
    result = packager.build_package(variant="d0", output_dir=output)
    archive = output / "submission.tar.gz"
    manifest_path = output / "submission.manifest.json"

    assert archive.is_file()
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == result
    assert result["variant"] == "d0"
    assert result["runtime"]["family"] == "dedicated_dipplin"
    assert result["runtime"]["direct_entrypoint"] is True
    assert result["runtime"]["search_default"] is False
    assert result["runtime"]["learned_weights_included"] is False
    assert result["runtime"]["grim_runtime_included"] is False
    assert result["verification"]["deterministic_double_build"] is True
    assert result["verification"]["first_archive_sha256"] == result["verification"]["second_archive_sha256"]
    assert result["output"]["archive_sha256"] == packager.sha256_file(archive)
    assert result["verification"]["sterile_import"]["passed"] is True
    assert result["verification"]["sterile_import"]["command_flags"] == ["-I", "-B"]
    assert result["verification"]["sterile_import"]["agent_class"] == "DipplinCompetitionAgent"
    assert result["verification"]["sterile_import"]["agent_module"] == "ptcg_ai.dipplin.policy"
    assert result["verification"]["sterile_import"]["search_enabled"] is False
    assert result["verification"]["sterile_import"]["deck_card_count"] == 60

    stage = tmp_path / "stage"
    packager.safe_extract(archive, stage)
    assert (stage / "deck.csv").read_bytes() == deck_csv_bytes()
    assert packager.sha256_file(stage / "deck.csv") == DECK_CSV_SHA256.upper()
    assert (stage / "deck.csv").read_text(encoding="ascii").splitlines() == list(map(str, EXACT_DECK))
    assert result["deck"] == {
        "deck_id": DECK_ID,
        "card_count": 60,
        "deck_csv_sha256": DECK_CSV_SHA256.upper(),
        "newline_terminated": True,
    }

    main_source = (stage / "main.py").read_text(encoding="utf-8")
    assert "from ptcg_ai.dipplin.policy import DipplinCompetitionAgent" in main_source
    assert "from ptcg_ai import CompetitionAgent" not in main_source
    assert 'os.environ["PTCG_DIPPLIN_SEARCH"] = "0"' in main_source

    members = set(result["output"]["file_manifest"])
    expected = {
        "main.py",
        "deck.csv",
        "ptcg_ai/__init__.py",
        "ptcg_ai/safety.py",
        *(f"ptcg_ai/dipplin/{name}" for name in packager.D0_DIPPLIN_MODULES),
        *(f"cg/{name}" for name in packager.OFFICIAL_CG_SHA256),
    }
    assert members == expected
    assert "ptcg_ai/dipplin/search.py" not in members
    assert not any(name.endswith((".npz", ".npy", ".pyc", ".pyo")) for name in members)
    assert not any("__pycache__" in name or "grim" in name.lower() for name in members)
    assert packager.package_tree_sha256(stage) == result["output"]["extracted_tree_sha256"]
    assert packager.runtime_source_tree_sha256(stage)[0] == result["runtime"]["runtime_source_tree_sha256"]

    for name, expected_hash in packager.OFFICIAL_CG_SHA256.items():
        assert packager.sha256_file(stage / "cg" / name) == expected_hash
        assert result["engine"]["official_template_file_sha256"][name] == expected_hash
    assert result["engine"]["linux_amd64_member"] == "cg/libcg.so"
    assert result["engine"]["linux_amd64_sha256"] == packager.OFFICIAL_CG_SHA256["libcg.so"]

    structure = result["verification"]["archive_structure"]
    assert structure["regular_files_only"] is True
    assert structure["sorted_members"] is True
    assert structure["portable_member_names"] is True
    assert structure["normalized_tar_metadata"] is True
    assert structure["gzip_mtime_zero"] is True
    assert structure["gzip_filename_empty"] is True
    with tarfile.open(archive, "r:gz") as handle:
        assert [member.name for member in handle.getmembers()] == sorted(members)
        assert all(member.isfile() and member.mode == 0o644 and member.mtime == 0 for member in handle.getmembers())


def test_linux_amd64_gate_is_explicit_and_does_not_claim_a_game(tmp_path: Path):
    result = packager.build_package(variant="d0", name="host-gate", output_dir=tmp_path)
    gate = result["verification"]["linux_amd64_complete_game"]
    expected_eligible = platform.system() == "Linux" and platform.machine().lower() in {"x86_64", "amd64"}

    assert gate["required_for_release"] is True
    assert gate["host_system"] == platform.system()
    assert gate["host_machine"] == platform.machine()
    assert gate["eligible_build_host"] is expected_eligible
    assert gate["complete_game_attempted"] is False
    assert gate["complete_game_verified"] is False
    assert gate["status"] == "pending_external_complete_game"
    if not expected_eligible:
        assert "not Linux/amd64" in gate["reason"]


@pytest.mark.parametrize(
    ("member_name", "message"),
    [
        ("../escape.txt", "unsafe tar member"),
        ("ptcg_ai/__pycache__/policy.pyc", "cache tar member"),
        ("cg\\libcg.so", "unsafe tar member"),
        ("CON.txt", "Windows-incompatible tar member"),
    ],
)
def test_safe_extract_rejects_unsafe_cache_and_nonportable_members(
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
    with pytest.raises(packager.PackageError, match=message):
        packager.safe_extract(archive, tmp_path / "destination")
    assert not (tmp_path / "escape.txt").exists()


def test_safe_extract_rejects_duplicates_and_links(tmp_path: Path):
    duplicate = tmp_path / "duplicate.tar.gz"
    with tarfile.open(duplicate, "w:gz") as handle:
        for payload in (b"one", b"two"):
            info = tarfile.TarInfo("main.py")
            info.size = len(payload)
            handle.addfile(info, io.BytesIO(payload))
    with pytest.raises(packager.PackageError, match="duplicate tar member"):
        packager.safe_extract(duplicate, tmp_path / "duplicate-output")

    linked = tmp_path / "linked.tar.gz"
    with tarfile.open(linked, "w:gz") as handle:
        info = tarfile.TarInfo("main.py")
        info.type = tarfile.SYMTYPE
        info.linkname = "../outside.py"
        handle.addfile(info)
    with pytest.raises(packager.PackageError, match="unsupported tar member type"):
        packager.safe_extract(linked, tmp_path / "linked-output")


def test_deterministic_tar_rejects_source_symlinks_and_caches(tmp_path: Path):
    cache_stage = tmp_path / "cache-stage"
    cache_path = cache_stage / "ptcg_ai" / "__pycache__" / "policy.pyc"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_bytes(b"cache")
    with pytest.raises(packager.PackageError, match="cache tree member"):
        packager.deterministic_tar(cache_stage, tmp_path / "cache.tar.gz")

    link_stage = tmp_path / "link-stage"
    link_stage.mkdir()
    target = tmp_path / "target.py"
    target.write_text("pass\n", encoding="utf-8")
    (link_stage / "main.py").symlink_to(target)
    with pytest.raises(packager.PackageError, match="symlink is forbidden"):
        packager.deterministic_tar(link_stage, tmp_path / "link.tar.gz")


def test_d1_entrypoint_forces_evaluated_search_without_s1():
    source = packager._entrypoint_bytes("d1").decode("utf-8")
    assert 'os.environ["PTCG_DIPPLIN_SEARCH"] = "1"' in source
    assert 'os.environ["PTCG_DIPPLIN_SECOND_OPENING_V2"] = "0"' in source
    assert "from ptcg_ai.dipplin.policy import DipplinCompetitionAgent" in source
    assert "from ptcg_ai import CompetitionAgent" not in source


def test_s1_entrypoint_forces_the_evaluated_search_and_second_opening_mode(tmp_path: Path):
    source = packager._entrypoint_bytes("s1").decode("utf-8")
    assert 'os.environ["PTCG_DIPPLIN_SEARCH"] = "1"' in source
    assert 'os.environ["PTCG_DIPPLIN_SECOND_OPENING_V2"] = "1"' in source

    result = packager.build_package(variant="s1", output_dir=tmp_path / "s1")
    smoke = result["verification"]["sterile_import"]
    assert result["variant"] == "s1"
    assert result["runtime"]["search_default"] is True
    assert result["runtime"]["second_opening_v2_default"] is True
    assert result["runtime"]["entrypoint_forces_evaluated_mode"] is True
    assert smoke["search_enabled"] is True
    assert smoke["second_opening_v2"] is True
    assert smoke["go_first"] is True
    assert smoke["route_v2_enabled"] is False
    assert smoke["search_worlds"] == 2


def test_packager_uses_synced_competition_engine_not_divergent_freshstart_copy():
    assert packager.OFFICIAL_CG_ROOT == packager.ROOT / "vendor" / "cg"
    assert packager.OFFICIAL_CG_SHA256["libcg.so"] == (
        "D16244A3157FC55C3314F08DCC7C5179168697D78C105B95C7DEBD556B764BB7"
    )
    divergent = packager.ROOT / "freshstart" / "submission_template" / "cg" / "libcg.so"
    assert packager.sha256_file(divergent) != packager.OFFICIAL_CG_SHA256["libcg.so"]


@pytest.mark.parametrize("name", ["../submission", "CON", "bad:name", "."])
def test_package_name_is_fail_closed(name: str, tmp_path: Path):
    with pytest.raises(packager.PackageError):
        packager.build_package(variant="d0", name=name, output_dir=tmp_path / "output")
