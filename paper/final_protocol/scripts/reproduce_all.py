#!/usr/bin/env python3
"""Rebuild and verify the final Protocol Article without running the game engine.

The workflow consumes retained acquisition artifacts and immutable raw rows. It
regenerates derived audits, summaries, manuscript artifacts, and the sanitized
review package. Its canonical report has no wall-clock times or command
durations, binds the scripts/tests/schemas/manifests it invokes, and preserves
the unresolved human and redistribution-rights gate.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import sysconfig
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCRIPT = Path(__file__).resolve()
FINAL = SCRIPT.parents[1]
ROOT = SCRIPT.parents[3]
REPORT = FINAL / "REPRODUCTION_REPORT.json"
REPORT_SIDECAR = FINAL / "REPRODUCTION_REPORT.sha256"
MACHINE_FINAL_REPORT = FINAL / "REPRODUCTION_REPORT_MACHINE_FINAL.json"
MACHINE_FINAL_SIDECAR = FINAL / "REPRODUCTION_REPORT_MACHINE_FINAL.sha256"
# The self-excluded envelope now carries both the canonical technical report
# and the machine-finalization aggregate written after the run by
# scripts/machine_finalize.py. Commit E's tree delta must be exactly this set.
REPORT_ENVELOPE_PATHS = frozenset(
    {
        str(REPORT.relative_to(ROOT)),
        str(REPORT_SIDECAR.relative_to(ROOT)),
        str(MACHINE_FINAL_REPORT.relative_to(ROOT)),
        str(MACHINE_FINAL_SIDECAR.relative_to(ROOT)),
    }
)
VISUAL_AUDIT = FINAL / "supplement/PDF_VISUAL_AUDIT.json"
PROTOCOL_COMMIT = "803257f102232763fc88d28c14b668f9b62eb277"
TITLE = "A Protocol for Validating Pairing Assumptions in Seed-Matched Evaluations of Black-Box Game-Playing Agents"
SOURCE_DATE_EPOCH = "1787529600"
DIRECT_REQUIREMENTS = FINAL / "release/requirements-lock.txt"
CONDA_ENVIRONMENT = FINAL / "release/environment.yml"

TARGETED_TESTS = (
    "tests/test_analyze_pevl.py",
    "tests/test_build_pevl_artifacts.py",
    "tests/test_build_pevl_result_macros.py",
    "tests/test_build_release_pevl.py",
    "tests/test_pevl_synthetic.py",
    "tests/test_seed_namespace_audit.py",
    "tests/test_stochastic_source_audit.py",
    "tests/test_verify_pevl_release.py",
    "paper/final_protocol/tests/test_equations.py",
    "paper/final_protocol/tests/test_claim_ledger.py",
    "paper/final_protocol/tests/test_desk_reviews.py",
    "paper/final_protocol/tests/test_independent_statistics.py",
    "paper/final_protocol/tests/test_research_audits.py",
    "paper/final_protocol/tests/test_protocol_reporting_provenance.py",
    "paper/final_protocol/tests/test_reproduction_provenance.py",
)

INVOKED_SCRIPTS = (
    "paper/final_protocol/scripts/reproduce_all.py",
    "paper/final_protocol/scripts/verify_reproduction_report.py",
    "paper/final_protocol/scripts/verify_starting_state.py",
    "paper/scripts/audit_seed_namespace.py",
    "paper/scripts/audit_stochastic_sources.py",
    "paper/scripts/analyze_pevl.py",
    "paper/final_protocol/scripts/verify_statistics.py",
    "paper/final_protocol/scripts/independent_statistics_audit.py",
    "paper/final_protocol/scripts/build_final_artifacts.py",
    "paper/final_protocol/scripts/recalculate_equation_examples.py",
    "paper/final_protocol/scripts/audit_readability.py",
    "paper/final_protocol/scripts/verify_research_audits.py",
    "paper/final_protocol/scripts/build_claim_ledger.py",
    "paper/final_protocol/scripts/build_final_release.py",
    "paper/final_protocol/scripts/audit_contradictions.py",
    "paper/final_protocol/scripts/aggregate_desk_reviews.py",
    "paper/final_protocol/release/scripts/verify_release.py",
    "paper/final_protocol/release/pevl_bench/__main__.py",
    "paper/final_protocol/release/pevl_bench/admission.py",
    "paper/final_protocol/release/pevl_bench/evidence.py",
    "paper/final_protocol/release/pevl_bench/schema_subset.py",
    "paper/final_protocol/release/pevl_bench/synthetic.py",
    "paper/final_protocol/release/pevl_bench/synthetic_admission.py",
)

# Existing edits elsewhere are tolerated at baseline but must remain byte-
# identical during the run. Only these tracked outputs may be regenerated.
GENERATED_PREFIXES = (
    "paper/final_protocol/figures/",
    "paper/final_protocol/tables/",
    "paper/final_protocol/source_data/",
    "paper/final_protocol/release/",
)
GENERATED_PATHS = (
    "paper/data/seed_namespace_audit.json",
    "paper/data/stochastic_source_audit.json",
    "paper/data/pevl/summary.json",
    "paper/data/pevl/trace_preflight_summary.json",
    "paper/data/pevl/timed_search_stress_summary.json",
    "paper/data/pevl/factorial_summary.json",
    "paper/data/pevl/factorial/units.csv",
    "paper/final_protocol/claim_ledger.csv",
    "paper/final_protocol/results_macros.tex",
    "paper/final_protocol/cover_letter.md",
    "paper/final_protocol/main.pdf",
    "paper/final_protocol/main.log",
    "paper/final_protocol/READABILITY_AUDIT.json",
    "paper/final_protocol/CONTRADICTION_AUDIT.json",
    "paper/final_protocol/DESK_REVIEW_SIMULATION_V2.json",
    "paper/final_protocol/REPRODUCTION_REPORT.json",
    "paper/final_protocol/REPRODUCTION_REPORT.sha256",
)
TRANSIENT_SUFFIXES = (".aux", ".blg", ".log", ".out", ".synctex.gz", ".pyc")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def strict_json(path: Path) -> Any:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant: {value}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=reject_constant,
        object_pairs_hook=reject_duplicates,
    )


def write_report(report: dict[str, Any]) -> None:
    """Bind every report state to a lowercase SHA-256 sidecar."""
    for path in (REPORT, REPORT_SIDECAR):
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise RuntimeError(f"refusing to replace non-regular report-envelope path: {path.relative_to(ROOT)}")
    payload = canonical_json_bytes(report)
    REPORT.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    REPORT_SIDECAR.write_text(f"{digest}  {REPORT.name}\n", encoding="ascii")


def clean_output(value: str) -> str:
    """Retain deterministic failure diagnostics without checkout/timing noise."""
    text = value.replace(str(ROOT), "<repo>")
    text = re.sub(r"\b\d+(?:\.\d+)?s\b", "<elapsed>", text)
    text = re.sub(r"/var/folders/[^\s]+", "<temporary-path>", text)
    return "\n".join(text.splitlines()[-40:])


def display_command(command: list[str]) -> list[str]:
    return [item.replace(str(ROOT), "<repo>") for item in command]


def run(command: list[str], purpose: str, *, cwd: Path = ROOT, timeout: int = 900) -> dict[str, Any]:
    completed = subprocess.run(
        command, cwd=cwd, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, timeout=timeout, check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "SOURCE_DATE_EPOCH": SOURCE_DATE_EPOCH},
    )
    record: dict[str, Any] = {
        "purpose": purpose,
        "command": display_command(command),
        "cwd": str(cwd.relative_to(ROOT)) if cwd != ROOT else ".",
        "returncode": completed.returncode,
        "result": "PASS" if completed.returncode == 0 else "FAIL",
    }
    if completed.returncode != 0:
        record["output_tail"] = clean_output(completed.stdout)
        raise RuntimeError(json.dumps(record, sort_keys=True, allow_nan=False))
    return record


def file_record(path: Path) -> dict[str, Any]:
    return {"path": str(path.relative_to(ROOT)), "size_bytes": path.stat().st_size, "sha256": sha256(path)}


def records_digest(records: Iterable[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for record in sorted(records, key=lambda item: str(item["path"])):
        digest.update(str(record["path"]).encode())
        digest.update(b"\0")
        digest.update(str(record["size_bytes"]).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(record["sha256"]).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def is_generated_path(relative_path: str) -> bool:
    value = relative_path.replace(os.sep, "/")
    return value in GENERATED_PATHS or any(value.startswith(prefix) for prefix in GENERATED_PREFIXES)


def git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in (
        "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR",
    ):
        environment.pop(name, None)
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    return environment


def git_tracked_paths() -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT,
        env=git_environment(),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git ls-files failed: {clean_output(completed.stderr.decode(errors='replace'))}")
    return sorted(item.decode() for item in completed.stdout.split(b"\0") if item)


def _git_text(arguments: list[str]) -> str:
    return _git_text_at(ROOT, arguments)


def _pathname_digest(paths: Iterable[bytes]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path)
        digest.update(b"\n")
    return digest.hexdigest()


def repository_identity(
    *, root: Path = ROOT, report_envelope_paths: frozenset[str] = REPORT_ENVELOPE_PATHS,
) -> dict[str, Any]:
    root = root.resolve()
    discovered_root = Path(_git_text_at(root, ["rev-parse", "--show-toplevel"])).resolve()
    if discovered_root != root:
        raise RuntimeError(f"Git worktree root differs from the intended repository root: {discovered_root}")
    tracked_dirty = subprocess.run(
        [
            "git", "diff", "--name-only", "--no-ext-diff", "--no-textconv",
            "--ignore-submodules=none", "-z", "HEAD", "--",
        ], cwd=root,
        env=git_environment(),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if tracked_dirty.returncode != 0:
        raise RuntimeError(f"git diff failed: {clean_output(tracked_dirty.stderr.decode(errors='replace'))}")
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=root,
        env=git_environment(),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if untracked.returncode != 0:
        raise RuntimeError(f"git ls-files failed: {clean_output(untracked.stderr.decode(errors='replace'))}")

    def non_envelope(raw: bytes) -> bool:
        return raw.decode("utf-8", errors="surrogateescape") not in report_envelope_paths

    index_flags = subprocess.run(
        ["git", "ls-files", "-v", "-z"], cwd=root,
        env=git_environment(),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if index_flags.returncode != 0:
        raise RuntimeError(f"git ls-files -v failed: {clean_output(index_flags.stderr.decode(errors='replace'))}")
    flagged_paths: list[bytes] = []
    for entry in index_flags.stdout.split(b"\0"):
        if not entry:
            continue
        if len(entry) < 3 or entry[1:2] != b" ":
            raise RuntimeError("git ls-files -v returned a malformed record")
        path = entry[2:]
        if entry[:1] != b"H" and non_envelope(path):
            flagged_paths.append(path)
    tracked_dirty_paths = sorted(set(
        item
        for item in tracked_dirty.stdout.split(b"\0")
        if item and non_envelope(item)
    ) | set(flagged_paths))
    untracked_paths = sorted(
        item
        for item in untracked.stdout.split(b"\0")
        if item and non_envelope(item)
    )
    non_envelope_paths = sorted(set(tracked_dirty_paths) | set(untracked_paths))
    branch = subprocess.run(
        ["git", "symbolic-ref", "--quiet", "--short", "HEAD"], cwd=root,
        env=git_environment(),
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    return {
        "head_commit": _git_text_at(root, ["rev-parse", "HEAD"]),
        "head_tree": _git_text_at(root, ["rev-parse", "HEAD^{tree}"]),
        "branch": branch.stdout.strip() if branch.returncode == 0 else None,
        "tracked_worktree_clean": not tracked_dirty_paths,
        "tracked_dirty_path_count": len(tracked_dirty_paths),
        "tracked_dirty_pathname_digest": _pathname_digest(tracked_dirty_paths),
        "untracked_non_envelope_path_count": len(untracked_paths),
        "untracked_non_envelope_pathname_digest": _pathname_digest(untracked_paths),
        "non_envelope_worktree_clean": not non_envelope_paths,
        "non_envelope_dirty_path_count": len(non_envelope_paths),
        "non_envelope_dirty_pathname_digest": _pathname_digest(non_envelope_paths),
        "report_envelope_paths_excluded_from_cleanliness": sorted(report_envelope_paths),
        "boundary": (
            "HEAD/tree identify clean reproduced subject commit S; branch is informational only. "
            "The final verifier requires current HEAD E to be S's sole direct child, with exactly the "
            "self-excluded canonical report and sidecar as E's committed tree delta."
        ),
    }


def _git_text_at(root: Path, arguments: list[str]) -> str:
    completed = subprocess.run(
        ["git", *arguments], cwd=root, text=True,
        env=git_environment(),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git {' '.join(arguments)} failed: {clean_output(completed.stderr)}")
    return completed.stdout.strip()


def require_clean_reproduction_subject(identity: dict[str, Any], *, phase: str) -> None:
    if (
        identity.get("tracked_worktree_clean") is not True
        or identity.get("tracked_dirty_path_count") != 0
        or identity.get("untracked_non_envelope_path_count") != 0
        or identity.get("non_envelope_worktree_clean") is not True
        or identity.get("non_envelope_dirty_path_count") != 0
    ):
        raise RuntimeError(f"{phase} requires a clean worktree outside the report envelope")


def require_unchanged_reproduction_subject(start: dict[str, Any], end: dict[str, Any]) -> None:
    require_clean_reproduction_subject(end, phase="reproduction end")
    if end.get("head_commit") != start.get("head_commit") or end.get("head_tree") != start.get("head_tree"):
        raise RuntimeError("reproduction changed the subject HEAD or tree")


def protected_tracked_snapshot() -> dict[str, str]:
    """Hash every tracked file outside the generated-output allowlist."""
    result: dict[str, str] = {}
    for relative_path in git_tracked_paths():
        if is_generated_path(relative_path):
            continue
        path = ROOT / relative_path
        result[relative_path] = sha256(path) if path.is_file() else "MISSING"
    return result


def snapshot_digest(snapshot: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for path, value in sorted(snapshot.items()):
        digest.update(path.encode())
        digest.update(b"\0")
        digest.update(value.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def changed_snapshot_paths(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))


def _subject_excluded(path: Path) -> bool:
    if path in {REPORT, REPORT_SIDECAR, MACHINE_FINAL_REPORT, MACHINE_FINAL_SIDECAR}:
        return True
    relative = path.relative_to(ROOT).as_posix()
    if {"__pycache__", ".pytest_cache"} & set(path.parts):
        return True
    return relative.endswith(TRANSIENT_SUFFIXES) or path.name == ".DS_Store"


def subject_paths() -> list[Path]:
    """Return the canonical article subject, including final reviewer bytes.

    Review files are hashed but never parsed here. The report and sidecar are
    excluded to avoid self-reference; compiler/cache transients are not package
    subjects.
    """
    paths: set[Path] = set()
    roots = (
        FINAL,
        ROOT / "paper/protocol",
        ROOT / "paper/data/ablation",
        ROOT / "paper/data/fresh_confirmation/raw",
        ROOT / "paper/data/pevl",
        ROOT / "paper/synthetic",
    )
    for directory in roots:
        if directory.is_dir():
            paths.update(path for path in directory.rglob("*") if path.is_file())
    for relative_path in set(INVOKED_SCRIPTS) | set(TARGETED_TESTS):
        path = ROOT / relative_path
        if path.is_file():
            paths.add(path)
    return sorted(path for path in paths if not _subject_excluded(path))


def canonical_subject() -> dict[str, Any]:
    records = [file_record(path) for path in subject_paths()]
    return {
        "algorithm": "SHA-256 over sorted UTF-8 path, NUL, decimal size, NUL, lowercase file SHA-256, LF records",
        "scope": "Final article/release tree, final reviewer bytes, retained protocol/data/synthetic inputs, and invoked scripts/tests",
        "excluded": [
            str(REPORT.relative_to(ROOT)),
            str(REPORT_SIDECAR.relative_to(ROOT)),
            "compiler/cache transients (*.aux, *.blg, *.log, *.out, *.synctex.gz, *.pyc, __pycache__, .pytest_cache)",
        ],
        "file_count": len(records),
        "sha256": records_digest(records),
    }


def _version_command(command: list[str]) -> tuple[str, str]:
    completed = subprocess.run(
        command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"version command failed: {' '.join(command)}: {clean_output(completed.stdout)}")
    output = "\n".join(line.rstrip() for line in completed.stdout.strip().splitlines())
    return output, str(Path(shutil.which(command[0]) or command[0]).resolve())


def tool_record(name: str, command: list[str]) -> dict[str, Any]:
    version, executable = _version_command(command)
    path = Path(executable)
    return {
        "name": name, "version_output": version, "executable": executable,
        "executable_sha256": sha256(path) if path.is_file() else None,
    }


def parse_direct_requirements(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s]+)", line)
        if not match:
            raise RuntimeError(f"unsupported direct requirement declaration: {line}")
        result[match.group(1).lower()] = match.group(2)
    return result


def parse_conda_declarations(path: Path) -> dict[str, str]:
    """Parse the deliberately simple direct dependency lines in environment.yml."""
    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"\s*-\s+([A-Za-z0-9_.-]+)=([^=\s]+)\s*", raw)
        if match:
            result[match.group(1).lower()] = match.group(2)
    return result


def environment_record() -> dict[str, Any]:
    if not DIRECT_REQUIREMENTS.is_file() or not CONDA_ENVIRONMENT.is_file():
        raise RuntimeError("release dependency declarations are missing")
    declared = parse_direct_requirements(DIRECT_REQUIREMENTS)
    observed = {name: importlib.metadata.version(name) for name in sorted(declared)}
    conda_declared = parse_conda_declarations(CONDA_ENVIRONMENT)
    expected_conda = {"python": platform.python_version(), **observed}
    clean_env_path = FINAL / "CLEAN_ENV_REPRODUCTION.json"
    fresh_created = False
    fresh_verified = False
    transitive_snapshot_recorded = False
    clean_env_summary: dict[str, Any] = None
    if clean_env_path.is_file():
        try:
            clean_env = json.loads(clean_env_path.read_text(encoding="utf-8"))
        except ValueError:
            clean_env = None
        if isinstance(clean_env, dict) and clean_env.get("status") == "PASS":
            clean_python = str(clean_env.get("python", {}).get("version", ""))
            clean_direct = {
                str(name): str(version)
                for name, version in clean_env.get("direct_packages", {}).items()
            }
            if clean_python == platform.python_version() and clean_direct == observed:
                fresh_created = bool(clean_env.get("environment_created"))
                fresh_verified = bool(clean_env.get("verification", {}).get("tests_passed"))
                transitive_snapshot_recorded = bool(clean_env.get("transitive_freeze"))
                clean_env_summary = {
                    "record": "CLEAN_ENV_REPRODUCTION.json",
                    "record_sha256": sha256(clean_env_path),
                    "record_size_bytes": clean_env_path.stat().st_size,
                    "python_version": clean_python,
                    "direct_packages": clean_direct,
                    "transitive_freeze_packages": clean_env.get("transitive_freeze"),
                    "created": fresh_created,
                    "verified": fresh_verified,
                }
    return {
        "python": {
            "version": platform.python_version(), "version_full": sys.version,
            "implementation": platform.python_implementation(),
            "executable": str(Path(sys.executable).resolve()),
            "executable_sha256": sha256(Path(sys.executable).resolve()),
            "compiler": platform.python_compiler(), "byte_order": sys.byteorder,
            "pointer_bits": struct.calcsize("P") * 8,
        },
        "direct_declared_packages": declared,
        "observed_direct_packages": observed,
        "direct_package_versions_match": observed == declared,
        "conda_direct_declarations": conda_declared,
        "conda_direct_versions_match_observed": conda_declared == expected_conda,
        "dependency_declarations": [file_record(DIRECT_REQUIREMENTS), file_record(CONDA_ENVIRONMENT)],
        "environment_boundary": {
            "requirements_lock_semantics": "requirements-lock.txt declares three direct packages only; it is not a transitive lock.",
            "transitive_environment_locked": False,
            "transitive_environment_snapshot_recorded": transitive_snapshot_recorded,
            "fresh_environment_created": fresh_created,
            "fresh_environment_verified": fresh_verified,
            "clean_environment_summary": clean_env_summary,
            "observation_scope": "Commands execute in the active workspace environment; exact observed versions and tool binaries are recorded.",
        },
        "tools": {
            "tectonic": tool_record("Tectonic", ["tectonic", "--version"]),
            "pdftoppm": tool_record("Poppler pdftoppm", ["pdftoppm", "-v"]),
            "pdfinfo": tool_record("Poppler pdfinfo", ["pdfinfo", "-v"]),
            "pdftotext": tool_record("Poppler pdftotext", ["pdftotext", "-v"]),
        },
        "operating_system": {
            "system": platform.system(), "release": platform.release(),
            "version": platform.version(), "platform": platform.platform(),
            "mac_version": platform.mac_ver()[0],
        },
        "architecture": {
            "machine": platform.machine(), "processor": platform.processor(),
            "python_architecture": list(platform.architecture()),
            "sysconfig_platform": sysconfig.get_platform(),
        },
    }


def provenance_inventory() -> dict[str, Any]:
    groups: dict[str, list[Path]] = {
        "invoked_scripts_and_modules": [ROOT / path for path in INVOKED_SCRIPTS],
        "targeted_tests": [ROOT / path for path in TARGETED_TESTS] + [FINAL / "release/tests/test_release.py"],
        "dependency_declarations": [DIRECT_REQUIREMENTS, CONDA_ENVIRONMENT],
        "schemas_and_rules": sorted(set(
            list((FINAL / "release/protocol").glob("*.json"))
            + list((FINAL / "release_templates/protocol").glob("*.json"))
            + list((FINAL / "release").glob("**/*schema*.json"))
            + [FINAL / "release/examples/example_evidence.json"]
        )),
        "manifests": sorted((FINAL / "release").glob("**/MANIFEST.sha256")),
    }
    missing = sorted(
        str(path.relative_to(ROOT)) for paths in groups.values()
        for path in paths if not path.is_file()
    )
    if missing:
        raise RuntimeError("provenance inventory is missing files: " + ", ".join(missing))
    records_by_group = {
        role: [file_record(path) for path in sorted(set(paths))]
        for role, paths in groups.items()
    }
    unique = {record["path"]: record for records in records_by_group.values() for record in records}
    return {
        "groups": records_by_group, "unique_file_count": len(unique),
        "sha256": records_digest(unique.values()), "missing": [],
    }


def key_outputs() -> dict[str, dict[str, Any]]:
    paths = {
        "manuscript_pdf": FINAL / "main.pdf",
        "claim_ledger": FINAL / "claim_ledger.csv",
        "claim_scope_audit": FINAL / "source_data/claim_scope_audit.json",
        "results_macros": FINAL / "results_macros.tex",
        "contradiction_audit": FINAL / "CONTRADICTION_AUDIT.json",
        "desk_review_simulation": FINAL / "DESK_REVIEW_SIMULATION_V2.json",
        "novelty_matrix": FINAL / "NOVELTY_MATRIX.csv",
        "reference_audit": FINAL / "REFERENCE_AUDIT.csv",
        "readability_audit": FINAL / "READABILITY_AUDIT.json",
        "release_manifest": FINAL / "release/MANIFEST.sha256",
        "statistics_verification": FINAL / "source_data/statistics_verification.json",
        "independent_statistics_verification": FINAL / "source_data/independent_statistics_verification.json",
        "artifact_build": FINAL / "source_data/build_report.json",
        "pdf_visual_audit": VISUAL_AUDIT,
    }
    return {
        role: {
            "path": str(path.relative_to(ROOT)), "exists": path.is_file(),
            "size_bytes": path.stat().st_size if path.is_file() else None,
            "sha256": sha256(path) if path.is_file() else None,
        }
        for role, path in paths.items()
    }


def render_and_validate_pdf() -> dict[str, Any]:
    """Render every PDF page and bind a recorded visual inspection to final bytes."""
    if shutil.which("pdftoppm") is None or shutil.which("pdfinfo") is None:
        raise RuntimeError("pdftoppm and pdfinfo are required for the all-page visual audit")
    if not VISUAL_AUDIT.is_file():
        raise RuntimeError(f"missing PDF visual-inspection attestation: {VISUAL_AUDIT}")
    try:
        attestation = strict_json(VISUAL_AUDIT)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"invalid PDF visual-inspection attestation: {exc}") from exc
    if not isinstance(attestation, dict) or attestation.get("status") != "PASS":
        raise RuntimeError("PDF visual-inspection attestation must have status PASS")
    source_hash = sha256(FINAL / "main.tex")
    pdf_hash = sha256(FINAL / "main.pdf")
    if attestation.get("manuscript_source_sha256") != source_hash:
        raise RuntimeError("PDF visual-inspection attestation is stale for main.tex")
    if attestation.get("manuscript_pdf_sha256") != pdf_hash:
        raise RuntimeError("PDF visual-inspection attestation is stale for main.pdf")

    info = subprocess.run(
        ["pdfinfo", "main.pdf"], cwd=FINAL, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )
    if info.returncode != 0:
        raise RuntimeError(f"pdfinfo failed: {clean_output(info.stdout)}")
    match = re.search(r"^Pages:\s+(\d+)\s*$", info.stdout, flags=re.MULTILINE)
    if not match:
        raise RuntimeError("pdfinfo did not report a page count")
    expected_pages = int(match.group(1))
    if expected_pages <= 0 or attestation.get("page_count") != expected_pages:
        raise RuntimeError("PDF visual-inspection attestation page count is stale")
    if attestation.get("inspected_pages") != list(range(1, expected_pages + 1)):
        raise RuntimeError("PDF visual-inspection attestation must enumerate every page")
    inspected_page_hashes = attestation.get("inspected_page_png_sha256")
    if (
        not isinstance(inspected_page_hashes, list)
        or len(inspected_page_hashes) != expected_pages
        or any(not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None for value in inspected_page_hashes)
    ):
        raise RuntimeError("PDF visual-inspection attestation must bind every inspected page hash")
    checklist = attestation.get("checklist")
    if not isinstance(checklist, dict) or not checklist or not all(value is True for value in checklist.values()):
        raise RuntimeError("PDF visual-inspection checklist is incomplete")

    with tempfile.TemporaryDirectory(prefix="final-protocol-render-") as directory:
        prefix = Path(directory) / "page"
        rendered = subprocess.run(
            ["pdftoppm", "-r", "150", "-png", "main.pdf", str(prefix)],
            cwd=FINAL, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            check=False, env={**os.environ, "SOURCE_DATE_EPOCH": SOURCE_DATE_EPOCH},
        )
        if rendered.returncode != 0:
            raise RuntimeError(f"pdftoppm failed: {clean_output(rendered.stdout)}")
        pages = sorted(Path(directory).glob("page-*.png"), key=lambda path: int(path.stem.rsplit("-", 1)[1]))
        if len(pages) != expected_pages:
            raise RuntimeError(f"rendered {len(pages)} pages; expected {expected_pages}")
        page_records = []
        for index, path in enumerate(pages, 1):
            data = path.read_bytes()
            if len(data) < 33 or not data.startswith(b"\x89PNG\r\n\x1a\n") or data[12:16] != b"IHDR":
                raise RuntimeError(f"invalid rendered PNG for page {index}")
            width = int.from_bytes(data[16:20], "big")
            height = int.from_bytes(data[20:24], "big")
            if width < 900 or height < 900:
                raise RuntimeError(f"rendered page {index} is unexpectedly small: {width}x{height}")
            page_hash = sha256(path)
            if page_hash != inspected_page_hashes[index - 1]:
                raise RuntimeError(f"rendered page {index} differs from the visually inspected page")
            page_records.append({"page": index, "width_pixels": width, "height_pixels": height, "sha256": page_hash})
    return {
        "status": "PASS",
        "method": "Every page rendered at 150 dpi; PNG structure/dimensions checked; a PDF-bound checklist records human visual inspection.",
        "attestation": str(VISUAL_AUDIT.relative_to(ROOT)), "attestation_sha256": sha256(VISUAL_AUDIT),
        "manuscript_source_sha256": source_hash, "manuscript_pdf_sha256": pdf_hash,
        "page_count": expected_pages, "rendered_pages": page_records,
    }


def validate_final_audits(*, require_desk_reviews: bool = True) -> None:
    contradiction = strict_json(FINAL / "CONTRADICTION_AUDIT.json")
    summary = contradiction.get("summary", {})
    if summary.get("contradictions") != 0 or summary.get("machine_verification_blockers") != 0:
        raise RuntimeError("final contradiction audit retains a factual or machine blocker")
    if summary.get("factual_consistency_status") != "PASS" or summary.get("machine_verification_status") != "PASS":
        raise RuntimeError("final contradiction audit did not pass factual and machine checks")
    if not require_desk_reviews:
        return
    desk_review = strict_json(FINAL / "DESK_REVIEW_SIMULATION_V2.json")
    if desk_review.get("status") != "PASS" or desk_review.get("review_count") != 5:
        raise RuntimeError("five-review closeout desk simulation is missing or invalid")
    if desk_review.get("SCIENTIFIC_DESK_GATE", {}).get("result") != "PASS_SCIENTIFICALLY_SEND_TO_REVIEW":
        raise RuntimeError("scientific desk gate did not pass")
    if desk_review.get("SUBMISSION_COMPLETENESS_GATE", {}).get("result") != "BLOCKED_PENDING_HUMAN_ACTIONS":
        raise RuntimeError("desk review did not preserve the human-completeness gate")
    combined = desk_review.get("combined_decision", {})
    if combined.get("overall_submission_status") != "NOT_READY_DO_NOT_SUBMIT_UNTIL_HUMAN_CLOSEOUT_COMPLETE":
        raise RuntimeError("desk review decision must remain fail closed")


def reproduction_commands(python: str) -> list[tuple[list[str], str, Path]]:
    return [
        ([python, "paper/final_protocol/scripts/verify_starting_state.py"], "verify frozen starting-state record and source identities", ROOT),
        (["git", "merge-base", "--is-ancestor", PROTOCOL_COMMIT, "HEAD"], "verify frozen protocol ancestry", ROOT),
        ([python, "paper/scripts/audit_seed_namespace.py"], "rebuild observable boundary-seed namespace audit", ROOT),
        ([python, "paper/scripts/audit_stochastic_sources.py"], "rebuild bounded stochastic-source pattern audit", ROOT),
        ([python, "paper/scripts/analyze_pevl.py"], "rebuild canonical PEVL summaries and factorial units from retained acquisition artifacts", ROOT),
        ([python, "paper/final_protocol/scripts/verify_statistics.py"], "independently verify raw-source hashes, schedules, audits, reaggregation, and statistics", ROOT),
        ([python, "paper/final_protocol/scripts/independent_statistics_audit.py", "--check"], "recalculate all central statistics independently from retained raw rows", ROOT),
        ([python, "paper/final_protocol/scripts/build_final_artifacts.py"], "rebuild generated macros, tables, figures, and source data", ROOT),
        ([python, "paper/final_protocol/scripts/recalculate_equation_examples.py"], "recalculate independent equation examples", ROOT),
        ([python, "paper/final_protocol/scripts/audit_readability.py"], "run mechanical sentence, acronym, repetition, number, terminology, and paragraph-purpose checks", ROOT),
        ([python, "paper/final_protocol/scripts/verify_research_audits.py"], "verify novelty, reference, title-collision, and APS desk-fit audits", ROOT),
        ([python, "paper/final_protocol/scripts/build_claim_ledger.py"], "rebuild exhaustive sentence-level claim ledger and scope audit", ROOT),
        ([python, "-m", "pytest", "-q", *TARGETED_TESTS], "run targeted analyzer, audit, synthetic, release, equation, claim-scope, and provenance tests", ROOT),
        ([python, "paper/final_protocol/scripts/build_final_release.py"], "build sanitized engine-free review package", ROOT),
        ([python, "-m", "pevl_bench", "generate"], "regenerate synthetic conformance outputs through the review-package interface", FINAL / "release"),
        ([python, "-m", "pevl_bench", "verify"], "verify synthetic conformance outputs through the review-package interface", FINAL / "release"),
        ([python, "-m", "pevl_bench", "admit", "examples/example_evidence.json"], "evaluate worked admission evidence through the review-package interface", FINAL / "release"),
        ([python, "-m", "pevl_bench", "explain", "examples/example_evidence.json"], "explain the blocking gate and redesign for the worked example", FINAL / "release"),
        ([python, "-m", "pevl_bench", "report", "--json"], "summarize processed evidence through the review-package interface", FINAL / "release"),
        ([python, "-m", "pevl_bench", "report", "--decision-table"], "regenerate the human-readable admission decision table", FINAL / "release"),
        ([python, "-m", "pytest", "-q", "tests/test_release.py"], "run engine-independent release tests", FINAL / "release"),
        ([python, "scripts/verify_release.py"], "verify release manifest and reaggregate processed rows", FINAL / "release"),
        (["tectonic", "main.tex"], "compile current REVTeX manuscript without retaining transient logs", FINAL),
    ]


def base_report(*, pre_review: bool, subject_identity: dict[str, Any] | None = None) -> dict[str, Any]:
    deterministic_time = datetime.fromtimestamp(int(SOURCE_DATE_EPOCH), tz=timezone.utc).isoformat()
    return {
        "schema_version": 2, "status": "RUNNING", "title": TITLE,
        "article_type": "APS Open Science Protocol Article", "protocol_commit": PROTOCOL_COMMIT,
        "generated_at_utc": deterministic_time,
        "timestamp_basis": "SOURCE_DATE_EPOCH; this is a deterministic build timestamp, not wall-clock execution time.",
        "review_phase": "PRE_REVIEW" if pre_review else "FINAL_FIVE_REVIEW",
        "scope": "Derived-artifact reproduction only; no restricted-engine execution and no new policy experiment.",
        "environment": environment_record(),
        "repository_identity": subject_identity if subject_identity is not None else repository_identity(),
        "commands": [], "outputs": {},
        "readiness_decision": "NOT_READY_DO_NOT_SUBMIT", "submission_ready": False,
        "rights_and_human_gate": {
            "status": "FAIL_OPEN_BLOCKERS", "rights_and_license_resolved": False,
            "human_signoffs_complete": False,
            "effect_on_submission": "Blocks redistribution and submission regardless of technical reproduction PASS.",
        },
        "limitations": [
            "The restricted game engine and private acquisition materials are not rerun.",
            "The command verifies retained canonical artifacts and reproduces synthetic and processed analyses.",
            "The active environment is observed exactly but was not created fresh; direct dependency declarations are not a transitive lock.",
            "Rights, licensing, DOI, human metadata, author comprehension, and author approval remain open blockers.",
        ],
        "report_determinism": {
            "canonical_serialization": "UTF-8 JSON, sorted keys, two-space indentation, no non-finite values, one trailing LF",
            "wall_clock_fields_or_durations_recorded": False, "source_date_epoch": SOURCE_DATE_EPOCH,
            "report_and_sidecar_excluded_from_subject_digest": True,
        },
        "read_only_verifier": {
            "path": "paper/final_protocol/scripts/verify_reproduction_report.py",
            "command": [sys.executable, "paper/final_protocol/scripts/verify_reproduction_report.py"],
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pre-review", action="store_true", help="Run technical/PDF workflow before all five final review files exist.")
    args = parser.parse_args(argv)
    try:
        subject_identity = repository_identity()
        require_clean_reproduction_subject(subject_identity, phase="reproduction start")
        report = base_report(pre_review=args.pre_review, subject_identity=subject_identity)
        before = protected_tracked_snapshot()
    except (RuntimeError, OSError, ValueError, importlib.metadata.PackageNotFoundError) as exc:
        report = {
            "schema_version": 2,
            "status": "FAIL",
            "technical_reproduction_status": "FAIL",
            "title": TITLE,
            "generated_at_utc": datetime.fromtimestamp(int(SOURCE_DATE_EPOCH), tz=timezone.utc).isoformat(),
            "timestamp_basis": "SOURCE_DATE_EPOCH; deterministic failure-report timestamp.",
            "review_phase": "PRE_REVIEW" if args.pre_review else "FINAL_FIVE_REVIEW",
            "readiness_decision": "NOT_READY_DO_NOT_SUBMIT",
            "submission_ready": False,
            "rights_and_human_gate": {
                "status": "FAIL_OPEN_BLOCKERS",
                "rights_and_license_resolved": False,
                "human_signoffs_complete": False,
            },
            "startup_error": clean_output(str(exc)),
        }
        write_report(report)
        print(json.dumps({"status": "FAIL", "report": str(REPORT.relative_to(ROOT))}, sort_keys=True))
        return 1
    report["tracked_drift"] = {
        "status": "RUNNING",
        "policy": (
            "Protected tracked files remain byte-identical during the run, and the final Git gate requires "
            "every non-envelope tracked or untracked path to match subject commit S."
        ),
        "baseline_semantics": "The run starts from a clean subject; only the report and sidecar may differ from HEAD at completion.",
        "generated_output_prefixes": list(GENERATED_PREFIXES),
        "generated_output_paths": list(GENERATED_PATHS),
        "protected_file_count_before": len(before),
        "protected_snapshot_sha256_before": snapshot_digest(before),
    }
    write_report(report)
    python = sys.executable
    try:
        if shutil.which("tectonic") is None:
            raise RuntimeError("tectonic is required to compile the manuscript")
        for command, purpose, cwd in reproduction_commands(python):
            report["commands"].append(run(command, purpose, cwd=cwd))
            write_report(report)

        extracted = subprocess.run(
            ["pdftotext", "main.pdf", "-"], cwd=FINAL, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
        normalized_pdf_text = " ".join(extracted.stdout.split())
        if extracted.returncode != 0 or TITLE not in normalized_pdf_text:
            raise RuntimeError("compiled PDF title does not match the Protocol Article")
        report["commands"].append({
            "purpose": "extract compiled PDF text for identity check", "command": ["pdftotext", "main.pdf", "-"],
            "cwd": str(FINAL.relative_to(ROOT)), "returncode": 0, "result": "PASS",
        })
        manuscript_source = (FINAL / "main.tex").read_text(encoding="utf-8")
        abstract_source = manuscript_source.split("\\begin{abstract}", 1)[1].split("\\end{abstract}", 1)[0]
        abstract_plain = re.sub(r"\\[A-Za-z]+(?:\{\})?", " ", abstract_source)
        abstract_plain = re.sub(r"[{}]", " ", abstract_plain)
        report["word_count"] = {
            "compiled_pdf_text_including_references": len(normalized_pdf_text.split()),
            "abstract_source_words_approximate": len(re.findall(r"[A-Za-z0-9]+(?:[-–][A-Za-z0-9]+)*", abstract_plain)),
            "method": "whitespace words from pdftotext; approximate regex words from the unexpanded TeX abstract",
        }
        report["visual_audit"] = render_and_validate_pdf()

        # The contradiction audit checks this provisional technical PASS. Each
        # write is sidecar-bound and excluded from the canonical subject digest.
        report["status"] = "PASS"
        report["outputs"] = key_outputs()
        write_report(report)
        final_commands: list[tuple[list[str], str]] = [
            ([python, "paper/final_protocol/scripts/audit_contradictions.py"], "run cross-file contradiction and claim-scope audit"),
        ]
        if not args.pre_review:
            final_commands.append(([python, "paper/final_protocol/scripts/aggregate_desk_reviews.py"], "validate and aggregate five independent closeout desk reviews"))
        for command, purpose in final_commands:
            report["commands"].append(run(command, purpose, cwd=ROOT))
            write_report(report)
        validate_final_audits(require_desk_reviews=not args.pre_review)

        after = protected_tracked_snapshot()
        unexpected = changed_snapshot_paths(before, after)
        if unexpected:
            raise RuntimeError("unexpected tracked-file drift: " + ", ".join(unexpected))
        report["tracked_drift"].update({
            "status": "PASS", "protected_file_count_after": len(after),
            "protected_snapshot_sha256_after": snapshot_digest(after), "unexpected_changes": [],
        })
        report["environment"] = environment_record()
        if (
            report["environment"]["direct_package_versions_match"] is not True
            or report["environment"]["conda_direct_versions_match_observed"] is not True
        ):
            raise RuntimeError("observed Python/direct package versions differ from their declarations")
        report["provenance_inventory"] = provenance_inventory()
        report["canonical_subject"] = canonical_subject()
        report["outputs"] = key_outputs()
        missing_outputs = sorted(role for role, item in report["outputs"].items() if not item["exists"])
        if args.pre_review:
            missing_outputs = [role for role in missing_outputs if role != "desk_review_simulation"]
        if missing_outputs:
            raise RuntimeError("missing key outputs: " + ", ".join(missing_outputs))
        end_identity = repository_identity()
        require_unchanged_reproduction_subject(subject_identity, end_identity)
        report["status"] = "PASS"
        report["technical_reproduction_status"] = "PASS"
        report["desk_review_status"] = "PENDING_INDEPENDENT_REVIEWS" if args.pre_review else "VALIDATED_FIVE_FINAL_REVIEWS"
        write_report(report)
    except (
        RuntimeError, subprocess.TimeoutExpired, OSError, ValueError,
        importlib.metadata.PackageNotFoundError,
    ) as exc:
        report["status"] = "FAIL"
        report["technical_reproduction_status"] = "FAIL"
        report["error"] = clean_output(str(exc))
        report["outputs"] = key_outputs()
        try:
            after = protected_tracked_snapshot()
            changed = changed_snapshot_paths(before, after)
            report["tracked_drift"].update({
                "status": "FAIL" if changed else "PASS", "protected_file_count_after": len(after),
                "protected_snapshot_sha256_after": snapshot_digest(after), "unexpected_changes": changed,
            })
        except (RuntimeError, OSError) as drift_exc:
            report["tracked_drift"]["status"] = "UNVERIFIED"
            report["tracked_drift"]["verification_error"] = clean_output(str(drift_exc))
        write_report(report)
        print(json.dumps({"status": "FAIL", "report": str(REPORT.relative_to(ROOT))}, sort_keys=True))
        return 1

    print(json.dumps({
        "status": "PASS", "readiness_decision": "NOT_READY_DO_NOT_SUBMIT",
        "report": str(REPORT.relative_to(ROOT)), "sidecar": str(REPORT_SIDECAR.relative_to(ROOT)),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
