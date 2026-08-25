#!/usr/bin/env python3
"""Read-only verification of the canonical reproduction report and sidecar."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

from reproduce_all import (
    FINAL,
    REPORT,
    REPORT_SIDECAR,
    REPORT_ENVELOPE_PATHS,
    ROOT,
    canonical_json_bytes,
    canonical_subject,
    display_command,
    environment_record,
    git_environment,
    key_outputs,
    protected_tracked_snapshot,
    provenance_inventory,
    records_digest,
    repository_identity,
    reproduction_commands,
    sha256,
    snapshot_digest,
    strict_json,
)


SIDECAR_PATTERN = re.compile(r"^([0-9a-f]{64})  ([^\r\n]+)\n$")
OID_PATTERN = re.compile(r"^[0-9a-f]+$")
CANONICAL_REPORT_RELATIVE = REPORT.relative_to(ROOT)
CANONICAL_SIDECAR_RELATIVE = REPORT_SIDECAR.relative_to(ROOT)
REPOSITORY_IDENTITY_KEYS = {
    "head_commit",
    "head_tree",
    "branch",
    "tracked_worktree_clean",
    "tracked_dirty_path_count",
    "tracked_dirty_pathname_digest",
    "untracked_non_envelope_path_count",
    "untracked_non_envelope_pathname_digest",
    "non_envelope_worktree_clean",
    "non_envelope_dirty_path_count",
    "non_envelope_dirty_pathname_digest",
    "report_envelope_paths_excluded_from_cleanliness",
    "boundary",
}


def parse_sidecar(text: str, expected_name: str) -> str:
    match = SIDECAR_PATTERN.fullmatch(text)
    if not match:
        raise ValueError("sidecar must be '<lowercase SHA-256><two spaces><filename><LF>'")
    if match.group(2) != expected_name:
        raise ValueError(f"sidecar names {match.group(2)!r}; expected {expected_name!r}")
    return match.group(1)


def _lexical_absolute(path: Path) -> Path:
    """Normalize dot segments without following a possibly hostile symlink."""
    return Path(os.path.abspath(os.fspath(path)))


def _canonical_envelope_paths(
    *, root: Path, report_path: Path, sidecar_path: Path,
) -> tuple[Path, Path]:
    expected_report = _lexical_absolute(root / CANONICAL_REPORT_RELATIVE)
    expected_sidecar = _lexical_absolute(root / CANONICAL_SIDECAR_RELATIVE)
    if _lexical_absolute(report_path) != expected_report:
        raise ValueError("only the canonical repository report path may be verified")
    if _lexical_absolute(sidecar_path) != expected_sidecar:
        raise ValueError("only the canonical repository sidecar path may be verified")
    return expected_report, expected_sidecar


def _require_regular_non_symlink(path: Path, *, label: str) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as exc:
        raise ValueError(f"canonical {label} is missing") from exc
    if path.is_symlink() or not stat.S_ISREG(mode):
        raise ValueError(f"canonical {label} must be a regular non-symlink file")


def _git_bytes(root: Path, arguments: list[str]) -> bytes:
    completed = subprocess.run(
        ["git", *arguments], cwd=root,
        env=git_environment(),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode(errors="replace").strip()
        raise ValueError(f"git {' '.join(arguments)} failed: {detail}")
    return completed.stdout


def _canonical_commit_oid(root: Path, value: Any) -> str:
    if not isinstance(value, str) or not OID_PATTERN.fullmatch(value):
        raise ValueError("reported subject commit is not a lowercase hexadecimal object ID")
    resolved = _git_bytes(root, ["rev-parse", "--verify", f"{value}^{{commit}}"])
    canonical = resolved.decode("ascii").strip()
    if canonical != value:
        raise ValueError("reported subject commit is not a canonical full commit object ID")
    return canonical


def _require_clean_identity(identity: dict[str, Any], *, label: str) -> None:
    if (
        identity.get("tracked_worktree_clean") is not True
        or identity.get("tracked_dirty_path_count") != 0
        or identity.get("untracked_non_envelope_path_count") != 0
        or identity.get("non_envelope_worktree_clean") is not True
        or identity.get("non_envelope_dirty_path_count") != 0
    ):
        raise ValueError(f"{label} is not clean outside the report envelope")


def _verify_committed_envelope_file(
    *, root: Path, head: str, relative_path: str, path: Path, label: str,
) -> None:
    _require_regular_non_symlink(path, label=label)
    raw_entry = _git_bytes(root, ["ls-tree", "-z", head, "--", relative_path])
    entries = [entry for entry in raw_entry.split(b"\0") if entry]
    if len(entries) != 1 or b"\t" not in entries[0]:
        raise ValueError(f"canonical {label} is not tracked exactly once at report commit E")
    metadata, recorded_path = entries[0].split(b"\t", 1)
    fields = metadata.decode("ascii").split()
    if len(fields) != 3 or fields[0] not in {"100644", "100755"} or fields[1] != "blob":
        raise ValueError(f"canonical {label} does not have a regular-file Git mode at report commit E")
    if recorded_path.decode("utf-8", errors="surrogateescape") != relative_path:
        raise ValueError(f"canonical {label} tree entry has the wrong path")
    mode, _, blob_oid = fields
    raw_index = _git_bytes(root, ["ls-files", "--stage", "-z", "--", relative_path])
    expected_index = f"{mode} {blob_oid} 0\t{relative_path}".encode()
    index_entries = [entry for entry in raw_index.split(b"\0") if entry]
    if index_entries != [expected_index]:
        raise ValueError(f"canonical {label} index entry differs from report commit E")
    committed = _git_bytes(root, ["cat-file", "blob", blob_oid])
    if path.read_bytes() != committed:
        raise ValueError(f"canonical {label} worktree bytes differ from report commit E")


def _safe_bound_path(value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe bound path: {value}")
    path = ROOT / relative
    try:
        path.resolve().relative_to(ROOT.resolve())
    except ValueError as exc:
        raise ValueError(f"bound path escapes repository: {value}") from exc
    return path


def verify_file_record(record: dict[str, Any]) -> None:
    if set(record) != {"path", "size_bytes", "sha256"}:
        raise ValueError(f"invalid file-record keys for {record.get('path', '<unknown>')}")
    path = _safe_bound_path(str(record["path"]))
    if not path.is_file():
        raise ValueError(f"bound file missing: {record['path']}")
    if path.stat().st_size != record["size_bytes"]:
        raise ValueError(f"bound file size changed: {record['path']}")
    if sha256(path) != record["sha256"]:
        raise ValueError(f"bound file hash changed: {record['path']}")


def verify_inventory(inventory: dict[str, Any]) -> None:
    groups = inventory.get("groups")
    if not isinstance(groups, dict):
        raise ValueError("provenance inventory groups are missing")
    required_groups = {
        "invoked_scripts_and_modules", "targeted_tests", "dependency_declarations",
        "schemas_and_rules", "manifests",
    }
    if set(groups) != required_groups:
        raise ValueError("provenance inventory groups differ from the required groups")
    unique: dict[str, dict[str, Any]] = {}
    for role, records in groups.items():
        if not isinstance(records, list) or not records:
            raise ValueError(f"provenance group is empty: {role}")
        for record in records:
            if not isinstance(record, dict):
                raise ValueError(f"non-object file record in provenance group: {role}")
            verify_file_record(record)
            previous = unique.setdefault(str(record["path"]), record)
            if previous != record:
                raise ValueError(f"conflicting duplicate provenance record: {record['path']}")
    if inventory.get("missing") != []:
        raise ValueError("provenance inventory reports missing inputs")
    if inventory.get("unique_file_count") != len(unique):
        raise ValueError("provenance unique-file count is stale")
    if inventory.get("sha256") != records_digest(unique.values()):
        raise ValueError("provenance inventory digest is stale")
    required_paths = {
        "paper/final_protocol/scripts/reproduce_all.py",
        "paper/final_protocol/scripts/verify_reproduction_report.py",
        "paper/final_protocol/release/MANIFEST.sha256",
        "paper/final_protocol/release/requirements-lock.txt",
        "paper/final_protocol/release/environment.yml",
    }
    if not required_paths <= set(unique):
        raise ValueError("provenance inventory omits a reproduction, manifest, or dependency file")


def verify_outputs(outputs: dict[str, Any], *, pre_review: bool) -> None:
    if not isinstance(outputs, dict) or not outputs:
        raise ValueError("key outputs are absent")
    required = {
        "manuscript_pdf", "claim_ledger", "claim_scope_audit", "results_macros",
        "contradiction_audit", "novelty_matrix", "reference_audit", "readability_audit",
        "release_manifest", "statistics_verification", "independent_statistics_verification",
        "artifact_build", "pdf_visual_audit",
    }
    if not pre_review:
        required.add("desk_review_simulation")
    if not required <= set(outputs):
        raise ValueError("report omits required key-output records")
    for role in sorted(required):
        record = outputs[role]
        if record.get("exists") is not True:
            raise ValueError(f"required output is not present: {role}")
        path = _safe_bound_path(str(record.get("path", "")))
        if not path.is_file() or path.stat().st_size != record.get("size_bytes"):
            raise ValueError(f"required output size is stale: {role}")
        if sha256(path) != record.get("sha256"):
            raise ValueError(f"required output hash is stale: {role}")


def expected_command_records(*, pre_review: bool) -> list[dict[str, Any]]:
    records = [
        {
            "purpose": purpose,
            "command": display_command(command),
            "cwd": str(cwd.relative_to(ROOT)) if cwd != ROOT else ".",
            "returncode": 0,
            "result": "PASS",
        }
        for command, purpose, cwd in reproduction_commands(sys.executable)
    ]
    records.append({
        "purpose": "extract compiled PDF text for identity check",
        "command": ["pdftotext", "main.pdf", "-"],
        "cwd": str(FINAL.relative_to(ROOT)),
        "returncode": 0,
        "result": "PASS",
    })
    records.append({
        "purpose": "run cross-file contradiction and claim-scope audit",
        "command": display_command([sys.executable, "paper/final_protocol/scripts/audit_contradictions.py"]),
        "cwd": ".",
        "returncode": 0,
        "result": "PASS",
    })
    if not pre_review:
        records.append({
            "purpose": "validate and aggregate five independent closeout desk reviews",
            "command": display_command([sys.executable, "paper/final_protocol/scripts/aggregate_desk_reviews.py"]),
            "cwd": ".",
            "returncode": 0,
            "result": "PASS",
        })
    return records


def verify_repository_identity_boundary(
    reported: dict[str, Any], *, root: Path = ROOT,
    report_path: Path = REPORT, sidecar_path: Path = REPORT_SIDECAR,
) -> None:
    """Verify final committed S-to-E provenance; exact-S worktrees are not final."""

    report_path, sidecar_path = _canonical_envelope_paths(
        root=root, report_path=report_path, sidecar_path=sidecar_path,
    )
    current = repository_identity(root=root, report_envelope_paths=REPORT_ENVELOPE_PATHS)
    if not isinstance(reported, dict) or set(reported) != REPOSITORY_IDENTITY_KEYS or set(current) != REPOSITORY_IDENTITY_KEYS:
        raise ValueError("repository identity schema differs")
    _require_clean_identity(reported, label="reported subject S")
    _require_clean_identity(current, label="current report commit E")
    for field in (
        "tracked_dirty_pathname_digest",
        "untracked_non_envelope_pathname_digest",
        "non_envelope_dirty_pathname_digest",
        "report_envelope_paths_excluded_from_cleanliness",
        "boundary",
    ):
        if reported[field] != current[field]:
            raise ValueError(f"repository identity field differs: {field}")
    subject_head = _canonical_commit_oid(root, reported["head_commit"])
    subject_tree = _git_bytes(root, ["rev-parse", "--verify", f"{subject_head}^{{tree}}"])
    if subject_tree.decode("ascii").strip() != reported["head_tree"]:
        raise ValueError("reported subject HEAD/tree pair is invalid")
    current_head = _canonical_commit_oid(root, current["head_commit"])
    raw_commit = _git_bytes(root, ["cat-file", "commit", current_head])
    commit_headers = raw_commit.split(b"\n\n", 1)[0].splitlines()
    parents = [line.split(b" ", 1)[1].decode("ascii") for line in commit_headers if line.startswith(b"parent ")]
    if parents != [subject_head]:
        raise ValueError("current report commit E must have reproduced subject S as its sole direct parent")
    changed = _git_bytes(
        root,
        [
            "diff-tree", "--no-commit-id", "--name-only", "--no-renames", "-r", "-z",
            subject_head, current_head, "--",
        ],
    )
    paths = {item.decode("utf-8", errors="surrogateescape") for item in changed.split(b"\0") if item}
    if paths != REPORT_ENVELOPE_PATHS:
        raise ValueError(
            "report commit E tree delta must contain exactly both canonical envelope paths; got: "
            + ", ".join(sorted(paths))
        )
    _verify_committed_envelope_file(
        root=root, head=current_head,
        relative_path=CANONICAL_REPORT_RELATIVE.as_posix(), path=report_path, label="report",
    )
    _verify_committed_envelope_file(
        root=root, head=current_head,
        relative_path=CANONICAL_SIDECAR_RELATIVE.as_posix(), path=sidecar_path, label="sidecar",
    )


def verify(report_path: Path = REPORT, sidecar_path: Path = REPORT_SIDECAR) -> dict[str, Any]:
    """Verify the final committed report envelope without writing files."""
    report_path, sidecar_path = _canonical_envelope_paths(
        root=ROOT, report_path=report_path, sidecar_path=sidecar_path,
    )
    _require_regular_non_symlink(report_path, label="report")
    _require_regular_non_symlink(sidecar_path, label="sidecar")
    raw = report_path.read_bytes()
    sidecar_digest = parse_sidecar(sidecar_path.read_text(encoding="ascii"), report_path.name)
    actual_digest = sha256(report_path)
    if sidecar_digest != actual_digest:
        raise ValueError("report SHA-256 does not match its sidecar")
    report = strict_json(report_path)
    if not isinstance(report, dict) or canonical_json_bytes(report) != raw:
        raise ValueError("report is not strict canonical JSON")
    if report.get("schema_version") != 2 or report.get("status") != "PASS":
        raise ValueError("reproduction report is not a schema-v2 PASS")
    if report.get("technical_reproduction_status") != "PASS":
        raise ValueError("technical reproduction status is not PASS")
    if report.get("readiness_decision") != "NOT_READY_DO_NOT_SUBMIT" or report.get("submission_ready") is not False:
        raise ValueError("report does not preserve the NOT_READY decision")
    gate = report.get("rights_and_human_gate", {})
    if gate.get("status") != "FAIL_OPEN_BLOCKERS":
        raise ValueError("rights/human gate is not fail closed")
    if gate.get("rights_and_license_resolved") is not False or gate.get("human_signoffs_complete") is not False:
        raise ValueError("report prematurely resolves a rights or human blocker")
    boundary = report.get("environment", {}).get("environment_boundary", {})
    if boundary.get("transitive_environment_locked") is not False:
        raise ValueError("report misrepresents the direct dependency declaration as transitive")
    if boundary.get("fresh_environment_created") is not False or boundary.get("fresh_environment_verified") is not False:
        raise ValueError("report misrepresents the active environment as fresh")
    if report.get("environment") != environment_record():
        raise ValueError("observed Python/package/tool/OS environment differs from the report")
    verify_repository_identity_boundary(
        report.get("repository_identity", {}),
        root=ROOT, report_path=report_path, sidecar_path=sidecar_path,
    )

    if report.get("review_phase") not in {"PRE_REVIEW", "FINAL_FIVE_REVIEW"}:
        raise ValueError("unknown review phase")
    pre_review = report.get("review_phase") == "PRE_REVIEW"
    expected_review_status = "PENDING_INDEPENDENT_REVIEWS" if pre_review else "VALIDATED_FIVE_FINAL_REVIEWS"
    if report.get("desk_review_status") != expected_review_status:
        raise ValueError("desk-review phase/status is inconsistent")
    if report.get("commands") != expected_command_records(pre_review=pre_review):
        raise ValueError("recorded command profile is incomplete, reordered, or non-passing")
    verify_inventory(report.get("provenance_inventory", {}))
    if report.get("provenance_inventory") != provenance_inventory():
        raise ValueError("current script/test/schema/manifest inventory differs from the report")
    verify_outputs(report.get("outputs", {}), pre_review=pre_review)
    if report.get("outputs") != key_outputs():
        raise ValueError("current key-output inventory differs from the report")
    if report.get("canonical_subject") != canonical_subject():
        raise ValueError("canonical subject digest or scope is stale")
    tracked = report.get("tracked_drift", {})
    current_snapshot = protected_tracked_snapshot()
    if tracked.get("status") != "PASS" or tracked.get("unexpected_changes") != []:
        raise ValueError("tracked-drift gate is not PASS")
    if tracked.get("protected_file_count_after") != len(current_snapshot):
        raise ValueError("protected tracked-file count changed")
    if tracked.get("protected_snapshot_sha256_after") != snapshot_digest(current_snapshot):
        raise ValueError("protected tracked-file snapshot changed")
    if tracked.get("protected_snapshot_sha256_before") != tracked.get("protected_snapshot_sha256_after"):
        raise ValueError("protected tracked files drifted during reproduction")
    return {
        "status": "PASS",
        "provenance_mode": "FINAL_COMMITTED_S_TO_E_REPORT_ENVELOPE",
        "report_sha256": actual_digest,
        "canonical_subject_sha256": report["canonical_subject"]["sha256"],
        "readiness_decision": "NOT_READY_DO_NOT_SUBMIT",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=REPORT, help="Must be the canonical repository report path.")
    parser.add_argument("--sidecar", type=Path, default=REPORT_SIDECAR, help="Must be the canonical repository sidecar path.")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = verify(args.report, args.sidecar)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        if not args.quiet:
            print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
        return 1
    if not args.quiet:
        print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
