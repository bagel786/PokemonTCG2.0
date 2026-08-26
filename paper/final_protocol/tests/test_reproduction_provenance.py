from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


FINAL = Path(__file__).resolve().parents[1]
SCRIPTS = FINAL / "scripts"
sys.path.insert(0, str(SCRIPTS))

import reproduce_all as reproduction  # noqa: E402
import verify_reproduction_report as verifier  # noqa: E402


REPORT_RELATIVE = Path("paper/final_protocol/REPRODUCTION_REPORT.json")
SIDECAR_RELATIVE = Path("paper/final_protocol/REPRODUCTION_REPORT.sha256")
SUBJECT_RELATIVE = Path("paper/final_protocol/main.tex")


def _git(repo: Path, *arguments: str) -> str:
    environment = os.environ.copy()
    for name in (
        "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    ):
        environment.pop(name, None)
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    completed = subprocess.run(
        ["git", *arguments], cwd=repo, env=environment, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(f"git {' '.join(arguments)} failed: {completed.stderr}")
    return completed.stdout.strip()


def _new_repository(tmp_path: Path, name: str) -> tuple[Path, dict[str, object]]:
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Provenance Test")
    _git(repo, "config", "user.email", "provenance@example.invalid")
    _git(repo, "config", "core.autocrlf", "false")
    subject = repo / SUBJECT_RELATIVE
    subject.parent.mkdir(parents=True)
    subject.write_text("subject\n", encoding="utf-8")
    _git(repo, "add", "--", SUBJECT_RELATIVE.as_posix())
    _git(repo, "commit", "-q", "-m", "subject S")
    identity = reproduction.repository_identity(
        root=repo, report_envelope_paths=reproduction.REPORT_ENVELOPE_PATHS,
    )
    return repo, identity


def _write_envelope(repo: Path) -> tuple[Path, Path]:
    report = repo / REPORT_RELATIVE
    sidecar = repo / SIDECAR_RELATIVE
    report.parent.mkdir(parents=True, exist_ok=True)
    payload = b"{}\n"
    report.write_bytes(payload)
    sidecar.write_text(
        f"{hashlib.sha256(payload).hexdigest()}  {REPORT_RELATIVE.name}\n",
        encoding="ascii",
    )
    # Machine-finalization aggregate: minimal structurally valid record bound to
    # the synthetic subject/report digests, derived from the shared constant.
    machine_relative = Path("paper/final_protocol/REPRODUCTION_REPORT_MACHINE_FINAL.json")
    machine_sidecar_relative = Path("paper/final_protocol/REPRODUCTION_REPORT_MACHINE_FINAL.sha256")
    identity = verifier.repository_identity(
        root=repo,
        report_envelope_paths=reproduction.REPORT_ENVELOPE_PATHS,
    )
    machine_payload = {
        "canonical_report_sha256": hashlib.sha256(payload).hexdigest(),
        "generated_by": "scripts/machine_finalize.py (test fixture)",
        "human_gate": {
            "overall_submission_status": "NOT_READY_DO_NOT_SUBMIT_UNTIL_HUMAN_CLOSEOUT_COMPLETE",
        },
        "schema_version": "machine-final-reproduction-report-v1",
        "status": "PASS",
        "subject_head_commit": identity["head_commit"],
    }
    serialized = json.dumps(machine_payload, indent=2, sort_keys=True) + "\n"
    machine = repo / machine_relative
    machine.write_text(serialized, encoding="utf-8")
    (repo / machine_sidecar_relative).write_text(
        f"{hashlib.sha256(serialized.encode('utf-8')).hexdigest()}  {machine_relative.name}\n",
        encoding="ascii",
    )
    return report, sidecar


def _commit_envelope(repo: Path, *, extra: bool = False) -> tuple[Path, Path]:
    report, sidecar = _write_envelope(repo)
    paths = sorted(reproduction.REPORT_ENVELOPE_PATHS)
    if extra:
        extra_path = repo / "unexpected.txt"
        extra_path.write_text("unexpected\n", encoding="utf-8")
        paths.append("unexpected.txt")
    _git(repo, "add", "--", *paths)
    _git(repo, "commit", "-q", "-m", "report envelope E")
    return report, sidecar


def _verify_boundary(repo: Path, reported: dict[str, object]) -> None:
    verifier.verify_repository_identity_boundary(
        reported,
        root=repo,
        report_path=repo / REPORT_RELATIVE,
        sidecar_path=repo / SIDECAR_RELATIVE,
    )


def test_canonical_json_and_record_digest_are_deterministic() -> None:
    first = reproduction.canonical_json_bytes({"z": 1, "a": [3, 2]})
    second = reproduction.canonical_json_bytes({"a": [3, 2], "z": 1})
    assert first == second == b'{\n  "a": [\n    3,\n    2\n  ],\n  "z": 1\n}\n'
    with pytest.raises(ValueError):
        reproduction.canonical_json_bytes({"bad": float("nan")})
    records = [
        {"path": "b", "size_bytes": 2, "sha256": "b" * 64},
        {"path": "a", "size_bytes": 1, "sha256": "a" * 64},
    ]
    assert reproduction.records_digest(records) == reproduction.records_digest(reversed(records))


def test_report_and_sidecar_are_excluded_from_subject_without_broad_exclusion() -> None:
    assert reproduction._subject_excluded(reproduction.REPORT)
    assert reproduction._subject_excluded(reproduction.REPORT_SIDECAR)
    assert reproduction._subject_excluded(reproduction.FINAL / "main.log")
    assert not reproduction._subject_excluded(reproduction.FINAL / "main.tex")
    assert not reproduction._subject_excluded(reproduction.FINAL / "reviews/reviewer_a.json")


def test_generated_drift_allowlist_is_explicit_and_protected_diff_is_exact() -> None:
    assert reproduction.is_generated_path("paper/final_protocol/source_data/a.json")
    assert reproduction.is_generated_path("paper/final_protocol/main.pdf")
    assert not reproduction.is_generated_path("paper/final_protocol/main.tex")
    assert not reproduction.is_generated_path("paper/final_protocol/scripts/reproduce_all.py")
    before = {"a": "0" * 64, "b": "1" * 64}
    after = {"a": "0" * 64, "b": "2" * 64, "c": "3" * 64}
    assert reproduction.changed_snapshot_paths(before, after) == ["b", "c"]
    assert reproduction.snapshot_digest(before) != reproduction.snapshot_digest(after)


def test_sidecar_parser_is_fail_closed() -> None:
    digest = hashlib.sha256(b"report").hexdigest()
    assert verifier.parse_sidecar(f"{digest}  REPRODUCTION_REPORT.json\n", "REPRODUCTION_REPORT.json") == digest
    for invalid in (
        f"{digest.upper()}  REPRODUCTION_REPORT.json\n",
        f"{digest} REPRODUCTION_REPORT.json\n",
        f"{digest}  other.json\n",
        f"{digest}  REPRODUCTION_REPORT.json",
    ):
        with pytest.raises(ValueError):
            verifier.parse_sidecar(invalid, "REPRODUCTION_REPORT.json")


def test_environment_boundary_and_direct_versions_are_exact() -> None:
    record = reproduction.environment_record()
    assert record["direct_declared_packages"] == {
        "matplotlib": "3.10.5", "numpy": "2.4.6", "pytest": "9.1.1",
    }
    assert record["observed_direct_packages"] == record["direct_declared_packages"]
    assert record["direct_package_versions_match"] is True
    assert record["conda_direct_declarations"] == {
        "python": "3.11.5", "matplotlib": "3.10.5", "numpy": "2.4.6", "pytest": "9.1.1",
    }
    assert record["conda_direct_versions_match_observed"] is True
    boundary = record["environment_boundary"]
    clean_record = FINAL / "CLEAN_ENV_REPRODUCTION.json"
    if clean_record.is_file():
        clean = json.loads(clean_record.read_text(encoding="utf-8"))
        passed = clean.get("status") == "PASS"
        assert boundary["fresh_environment_created"] == (passed and bool(clean.get("environment_created")))
        assert boundary["fresh_environment_verified"] == (passed and bool(clean.get("verification", {}).get("tests_passed")))
        assert boundary["transitive_environment_locked"] is False
        assert boundary["transitive_environment_snapshot_recorded"] == (
            passed and bool(clean.get("transitive_freeze"))
        )
        if boundary["fresh_environment_created"]:
            summary = boundary["clean_environment_summary"]
            assert summary["record_sha256"] == reproduction.sha256(clean_record)
            assert summary["record_size_bytes"] == clean_record.stat().st_size
            assert summary["python_version"] == record["python"]["version"]
            assert summary["direct_packages"] == record["observed_direct_packages"]
    else:
        assert boundary["fresh_environment_created"] is False
        assert boundary["fresh_environment_verified"] is False
        assert boundary["transitive_environment_locked"] is False
        assert boundary["transitive_environment_snapshot_recorded"] is False
    assert record["tools"]["tectonic"]["version_output"]
    assert record["tools"]["pdftoppm"]["version_output"]
    assert record["operating_system"]["system"]
    assert record["architecture"]["machine"]
    repository = reproduction.repository_identity()
    assert len(repository["head_commit"]) == 40
    assert len(repository["head_tree"]) == 40
    assert len(repository["tracked_dirty_pathname_digest"]) == 64
    assert len(repository["untracked_non_envelope_pathname_digest"]) == 64
    assert len(repository["non_envelope_dirty_pathname_digest"]) == 64
    assert isinstance(repository["tracked_worktree_clean"], bool)
    assert isinstance(repository["non_envelope_worktree_clean"], bool)


def test_profile_binds_every_targeted_test_and_required_inventory_group() -> None:
    commands = reproduction.reproduction_commands(sys.executable)
    pytest_commands = [command for command, _, cwd in commands if command[:3] == [sys.executable, "-m", "pytest"] and cwd == reproduction.ROOT]
    assert len(pytest_commands) == 1
    assert set(reproduction.TARGETED_TESTS) <= set(pytest_commands[0])
    inventory = reproduction.provenance_inventory()
    assert inventory["missing"] == []
    assert set(inventory["groups"]) == {
        "invoked_scripts_and_modules", "targeted_tests", "dependency_declarations",
        "schemas_and_rules", "manifests",
    }
    assert inventory["unique_file_count"] > len(reproduction.TARGETED_TESTS)
    assert len(inventory["sha256"]) == 64
    pre_review = verifier.expected_command_records(pre_review=True)
    final = verifier.expected_command_records(pre_review=False)
    assert len(final) == len(pre_review) + 1
    assert "aggregate_desk_reviews.py" not in json.dumps(pre_review)
    assert "aggregate_desk_reviews.py" in json.dumps(final)
    assert all(record["result"] == "PASS" and record["returncode"] == 0 for record in final)


@pytest.mark.parametrize("detached", [False, True])
def test_final_direct_envelope_commit_is_accepted_on_branch_or_detached(
    tmp_path: Path, detached: bool,
) -> None:
    repo, subject_identity = _new_repository(tmp_path, f"success-{detached}")
    _commit_envelope(repo)
    if detached:
        _git(repo, "checkout", "--detach", "-q")
    _verify_boundary(repo, subject_identity)


@pytest.mark.parametrize(
    "scenario",
    [
        "exact_subject", "only_report", "only_sidecar", "extra_path", "empty_child",
        "non_direct", "merge_child", "fake_parent_message",
    ],
)
def test_final_boundary_rejects_incomplete_or_wrong_topology(
    tmp_path: Path, scenario: str,
) -> None:
    repo, subject_identity = _new_repository(tmp_path, scenario)
    if scenario == "exact_subject":
        _write_envelope(repo)
    elif scenario == "only_report":
        report, _ = _write_envelope(repo)
        _git(repo, "add", "--", report.relative_to(repo).as_posix())
        _git(repo, "commit", "-q", "-m", "report only")
    elif scenario == "only_sidecar":
        _, sidecar = _write_envelope(repo)
        _git(repo, "add", "--", sidecar.relative_to(repo).as_posix())
        _git(repo, "commit", "-q", "-m", "sidecar only")
    elif scenario == "extra_path":
        _commit_envelope(repo, extra=True)
    elif scenario == "empty_child":
        _write_envelope(repo)
        _git(repo, "commit", "--allow-empty", "-q", "-m", "empty child")
    elif scenario == "non_direct":
        _git(repo, "commit", "--allow-empty", "-q", "-m", "intermediate")
        _commit_envelope(repo)
    elif scenario == "merge_child":
        _commit_envelope(repo)
        subject_head = str(subject_identity["head_commit"])
        envelope_head = _git(repo, "rev-parse", "HEAD")
        tree = _git(repo, "rev-parse", "HEAD^{tree}")
        merge = _git(
            repo, "commit-tree", tree, "-p", subject_head, "-p", envelope_head,
            "-m", "synthetic merge",
        )
        _git(repo, "reset", "--hard", "-q", merge)
    elif scenario == "fake_parent_message":
        _commit_envelope(repo)
        tree = _git(repo, "rev-parse", "HEAD^{tree}")
        root_commit = _git(
            repo, "commit-tree", tree, "-m", f"parent {subject_identity['head_commit']}",
        )
        _git(repo, "reset", "--hard", "-q", root_commit)
    with pytest.raises(ValueError):
        _verify_boundary(repo, subject_identity)


@pytest.mark.parametrize(
    "scenario",
    [
        "unstaged_envelope", "staged_envelope", "untracked_envelope",
        "dirty_non_envelope", "untracked_non_envelope", "assume_unchanged_envelope",
        "assume_unchanged_non_envelope",
    ],
)
def test_final_boundary_rejects_index_and_worktree_bypasses(
    tmp_path: Path, scenario: str,
) -> None:
    repo, subject_identity = _new_repository(tmp_path, scenario)
    report, _ = _commit_envelope(repo)
    if scenario == "unstaged_envelope":
        report.write_text("tampered\n", encoding="utf-8")
    elif scenario == "staged_envelope":
        committed = report.read_bytes()
        report.write_text("tampered\n", encoding="utf-8")
        _git(repo, "add", "--", REPORT_RELATIVE.as_posix())
        report.write_bytes(committed)
    elif scenario == "untracked_envelope":
        _git(repo, "rm", "--cached", "-q", "--", REPORT_RELATIVE.as_posix())
    elif scenario == "dirty_non_envelope":
        (repo / SUBJECT_RELATIVE).write_text("dirty\n", encoding="utf-8")
    elif scenario == "untracked_non_envelope":
        (repo / "untracked.txt").write_text("untracked\n", encoding="utf-8")
    elif scenario == "assume_unchanged_envelope":
        _git(repo, "update-index", "--assume-unchanged", "--", REPORT_RELATIVE.as_posix())
        report.write_text("hidden tamper\n", encoding="utf-8")
    elif scenario == "assume_unchanged_non_envelope":
        _git(repo, "update-index", "--assume-unchanged", "--", SUBJECT_RELATIVE.as_posix())
        (repo / SUBJECT_RELATIVE).write_text("hidden subject tamper\n", encoding="utf-8")
    with pytest.raises(ValueError):
        _verify_boundary(repo, subject_identity)


@pytest.mark.parametrize("scenario", ["abbreviated", "revision_expression", "wrong_tree", "dirty_subject"])
def test_final_boundary_rejects_noncanonical_or_dirty_subject_identity(
    tmp_path: Path, scenario: str,
) -> None:
    repo, subject_identity = _new_repository(tmp_path, scenario)
    if scenario == "dirty_subject":
        subject = repo / SUBJECT_RELATIVE
        subject.write_text("dirty subject\n", encoding="utf-8")
        subject_identity = reproduction.repository_identity(
            root=repo, report_envelope_paths=reproduction.REPORT_ENVELOPE_PATHS,
        )
        subject.write_text("subject\n", encoding="utf-8")
    _commit_envelope(repo)
    if scenario == "abbreviated":
        subject_identity["head_commit"] = str(subject_identity["head_commit"])[:12]
    elif scenario == "revision_expression":
        subject_identity["head_commit"] = "HEAD^"
    elif scenario == "wrong_tree":
        subject_identity["head_tree"] = "0" * 40
    with pytest.raises(ValueError):
        _verify_boundary(repo, subject_identity)


def test_final_boundary_rejects_alternate_paths_and_symlink_tree_entries(tmp_path: Path) -> None:
    repo, subject_identity = _new_repository(tmp_path, "symlink")
    target = repo / "report-target.json"
    target.write_text("{}\n", encoding="utf-8")
    _git(repo, "add", "--", "report-target.json")
    _git(repo, "commit", "-q", "-m", "subject target")
    subject_identity = reproduction.repository_identity(
        root=repo, report_envelope_paths=reproduction.REPORT_ENVELOPE_PATHS,
    )
    report = repo / REPORT_RELATIVE
    report.parent.mkdir(parents=True, exist_ok=True)
    report.symlink_to(os.path.relpath(target, report.parent))
    sidecar = repo / SIDECAR_RELATIVE
    sidecar.write_text(f"{'0' * 64}  {REPORT_RELATIVE.name}\n", encoding="ascii")
    _git(repo, "add", "--", REPORT_RELATIVE.as_posix(), SIDECAR_RELATIVE.as_posix())
    _git(repo, "commit", "-q", "-m", "symlink envelope")
    with pytest.raises(ValueError):
        _verify_boundary(repo, subject_identity)
    with pytest.raises(ValueError, match="canonical repository report path"):
        verifier.verify_repository_identity_boundary(
            subject_identity,
            root=repo,
            report_path=repo / "alternate-report.json",
            sidecar_path=sidecar,
        )


def test_reproduction_subject_gate_requires_clean_unchanged_commit(tmp_path: Path) -> None:
    repo, start = _new_repository(tmp_path, "reproduction-gate")
    reproduction.require_clean_reproduction_subject(start, phase="test start")
    reproduction.require_unchanged_reproduction_subject(start, start)

    (repo / "new-untracked.txt").write_text("dirty\n", encoding="utf-8")
    dirty = reproduction.repository_identity(
        root=repo, report_envelope_paths=reproduction.REPORT_ENVELOPE_PATHS,
    )
    with pytest.raises(RuntimeError):
        reproduction.require_clean_reproduction_subject(dirty, phase="test start")
    (repo / "new-untracked.txt").unlink()

    _git(repo, "commit", "--allow-empty", "-q", "-m", "changed HEAD")
    changed_head = reproduction.repository_identity(
        root=repo, report_envelope_paths=reproduction.REPORT_ENVELOPE_PATHS,
    )
    with pytest.raises(RuntimeError):
        reproduction.require_unchanged_reproduction_subject(start, changed_head)
