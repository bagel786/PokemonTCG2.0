#!/usr/bin/env python3
"""Build a fail-closed, engine-independent Protocol Article review release.

The release is assembled in a clean staging directory from an exact allow-list.
Restricted engine material and raw traces are never copied.  Processed rows are
projected to the minimum fields needed to reaggregate the reported diagnostics,
and private case-study labels are replaced by stable neutral context labels.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


SCRIPT = Path(__file__).resolve()
FINAL = SCRIPT.parents[1]
ROOT = SCRIPT.parents[3]
PAPER = ROOT / "paper"
RELEASE = FINAL / "release"
TEMPLATES = FINAL / "release_templates"
PROTOCOL_COMMIT = "803257f102232763fc88d28c14b668f9b62eb277"
PROTOCOL_ID = "PEVL_PROSPECTIVE_PROTOCOL_20260824"

PINNED_INPUTS = {
    "historical_units": (PAPER / "data/ablation/canonical_ablation.csv", "eca841487814c50acccb7f885207e679b906179bb77e6818dfaa430af47e6fcc"),
    "preflight_summary": (PAPER / "data/pevl/trace_preflight_summary.json", "c6295f9f3981d346d0cbcb38327e575b560aaf0950bd52f52594cfb8f9cc56b3"),
    "stress_summary": (PAPER / "data/pevl/timed_search_stress_summary.json", "40b9f5e17a424742ad8a05739646fe56843b8f3a432b124bfc33f9aed1ab5a4b"),
    "factorial_summary": (PAPER / "data/pevl/factorial_summary.json", "c7df75c7ae0f76a007d866947ad5262242d86c0c90cb0c8631d201dedd023e59"),
    "factorial_units": (PAPER / "data/pevl/factorial/units.csv", "62fe1fc3657ccd783e4f068042f201ceae0d7fc02d694a8ee5943d3f5c52e3eb"),
    "synthetic_implementation": (PAPER / "release/synthetic/pevl_synthetic.py", "3b85d01c37bf522008b5fb1a20192ddfb1141db801b275093e0aa7f779bc3f86"),
    "synthetic_manifest": (PAPER / "synthetic/results/MANIFEST.sha256", "0a6eade794c4434275663315442a8e5528a8c3c602f42da5de3ecd0b34792621"),
    "synthetic_matrix": (PAPER / "synthetic/results/pevl_matrix.csv", "bb79fd2f4f70415948f659b3837b68371814da63a3942ab9bf672cc5e11ec465"),
    "synthetic_results": (PAPER / "synthetic/results/pevl_results.json", "d34a2ea1546a0a88e90a5ca58b49f1085edfcaf753f70ed49e0f04202e9ba6f9"),
    "synthetic_schema": (PAPER / "synthetic/results/pevl_results.schema.json", "d173b3255a19b985bf5d0c102b67bfebcddcec6911b38d18a77048b74f63aafb"),
    "protocol_fresh": (PAPER / "protocol/FRESH_CONFIRMATION_PROTOCOL.md", "deedad087ee8cc6b2863499ab5d3dcb6017b9b96f51bacf15bd74960bc31fa19"),
    "protocol_pevl": (PAPER / "protocol/PEVL_PROSPECTIVE_PROTOCOL.md", "8b9329b948a054fc7252b9c2662490890e0a8439ad852393c6e25f537c8b887e"),
    "protocol_representation": (PAPER / "protocol/REPRESENTATION_ABLATION_PROTOCOL.md", "b838a881061027a80d78acbca0958b050bec339ccb0f78f35681036832069e3f"),
}

PROTOCOLS = {
    "protocol_fresh": "FRESH_CONFIRMATION_PROTOCOL.md",
    "protocol_pevl": "PEVL_PROSPECTIVE_PROTOCOL.md",
    "protocol_representation": "REPRESENTATION_ABLATION_PROTOCOL.md",
}
TEMPLATE_FILES = {
    "docs/ADMISSION_DECISION_TABLE.md",
    "docs/PROTOCOL_DEVIATIONS.md",
    "docs/STAGE6_DECISION_RULES.md",
    "docs/WORKED_ADMISSION_EXAMPLE.md",
    "examples/example_evidence.json",
    "examples/evidence/candidate_agent.txt",
    "examples/evidence/candidate_trace.txt",
    "examples/evidence/condition.txt",
    "examples/evidence/configuration.json",
    "examples/evidence/control_agent.txt",
    "examples/evidence/control_trace_fresh.txt",
    "examples/evidence/control_trace_worker.txt",
    "examples/evidence/engine.txt",
    "examples/evidence/initial_state.txt",
    "examples/evidence/protocol.txt",
    "examples/evidence/runner.txt",
    "pevl_bench/__init__.py",
    "pevl_bench/__main__.py",
    "pevl_bench/admission.py",
    "pevl_bench/evidence.py",
    "pevl_bench/schema_subset.py",
    "pevl_bench/stage6_rules.py",
    "pevl_bench/synthetic_admission.py",
    "protocol/admission_rules.json",
    "protocol/admission_schema.json",
    "protocol/claim_classes.json",
    "protocol/evidence_bundle_schema.json",
    "protocol/stage6_source_audit_rules.json",
    "scripts/verify_release.py",
    "scripts/build_figures_tables.py",
    "tests/test_admission_hardening.py",
    "tests/test_release.py",
    "tests/test_stage6_rules.py",
}
SOURCE_DATA_FILES = {
    "artifact_identity.json",
    "equation_examples.json",
    "figure_1_distinctions.json",
    "figure_2_admission_flow.json",
    "figure_3_synthetic_matrix.csv",
    "figure_4_timed_search.csv",
    "figure_5_factorial.csv",
}
FIGURE_STEMS = {
    "figure_1_distinctions",
    "figure_2_admission_flow",
    "figure_3_synthetic_matrix",
    "figure_4_timed_search",
    "figure_5_factorial",
}
TABLE_FILES = {
    "table_1_prior_work.tex",
    "table_2_protocol_stages.tex",
    "table_3_prospective_results.tex",
    "table_4_factorial.tex",
}

CONTEXT_MAP = {
    "B0": "deterministic-1",
    "b0": "deterministic-1",
    "d842_runtime": "deterministic-2",
    "d842-runtime": "deterministic-2",
    "d842": "deterministic-2",
    "master_v1": "deterministic-3",
    "master-v1": "deterministic-3",
    "master": "deterministic-3",
    "replay_refresh": "deterministic-4",
    "replay-refresh": "deterministic-4",
    "replay": "deterministic-4",
    "alakazam_no_search": "deterministic-5",
    "Alakazam-no-search": "deterministic-5",
    "starmie": "timed-search-A",
    "dipplin": "timed-search-B",
}
IDENTIFIER_REPLACEMENTS = (
    (r"grim_d842_runtime", "deterministic-2"),
    (r"grim_replay_refresh", "deterministic-4"),
    (r"grim_master_v1", "deterministic-3"),
    (r"grim_b0", "deterministic-1"),
    (r"starmie_v2_boss_atk", "timed-search-A"),
    (r"alakazam_2_4a_no_search", "deterministic-5"),
    (r"alakazam_2_4a", "deterministic-5"),
    (r"alakazam_no_search", "deterministic-5"),
    (r"dipplin_d1", "timed-search-B"),
    (r"d842_runtime", "deterministic-2"),
    (r"d842-runtime", "deterministic-2"),
    (r"master_v1", "deterministic-3"),
    (r"master-v1", "deterministic-3"),
    (r"replay_refresh", "deterministic-4"),
    (r"replay-refresh", "deterministic-4"),
    (r"alakazam-no-search", "deterministic-5"),
    (r"starmie", "timed-search-A"),
    (r"dipplin", "timed-search-B"),
    (r"alakazam", "deterministic-5"),
    (r"(?<![A-Za-z0-9])d842(?![A-Za-z0-9])", "deterministic-2"),
    (r"(?<![A-Za-z0-9])B0(?![A-Za-z0-9])", "deterministic-1"),
    (r"(?<![A-Za-z0-9])Grim(?![A-Za-z0-9])", "restricted-team"),
    (r"Dreamer", "restricted-team-1"),
    (r"GrimmsnaRL", "restricted-team-2"),
    (r"Mint120", "restricted-team-3"),
    (r"TMTA", "restricted-team-4"),
    (r"lollipop947", "restricted-team-5"),
    (r"matsurih", "restricted-team-6"),
)
PROHIBITED_IDENTIFIERS = tuple(
    re.compile(pattern, re.IGNORECASE) for pattern, _ in IDENTIFIER_REPLACEMENTS
)
PROHIBITED_SUFFIXES = {
    ".dylib", ".dll", ".so", ".exe", ".npz", ".npy", ".pt", ".pth",
    ".onnx", ".pkl", ".pickle", ".joblib", ".tar", ".tgz", ".gz",
    ".zip", ".7z", ".rar", ".pyc", ".pyo", ".whl", ".egg", ".db",
    ".sqlite",
}
PROHIBITED_MAGIC = {
    b"\x7fELF": "ELF executable",
    b"MZ": "PE executable",
    b"\xca\xfe\xba\xbe": "Mach-O/universal binary",
    b"\xcf\xfa\xed\xfe": "Mach-O binary",
    b"\xfe\xed\xfa\xcf": "Mach-O binary",
    b"PK\x03\x04": "ZIP archive",
    b"\x1f\x8b": "gzip archive",
    b"\x93NUMPY": "NumPy binary",
}
LOCAL_ROOT_PATTERN = re.compile(rb"/(?:Users|home|root|private|tmp|var)/")
WINDOWS_ROOT_PATTERN = re.compile(rb"(?i)[A-Z]:[\\/](?:Users|home|root|private|tmp|var)[\\/]")
SECRET_PATTERNS = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]+"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
MANIFEST_LINE = re.compile(r"([0-9a-f]{64})  ([^\r\n]+)")


class ReleaseError(ValueError):
    """Raised when an input or staged file violates the release contract."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(observed: Any, expected: Any, label: str) -> None:
    if observed != expected:
        raise ReleaseError(f"{label}: expected {expected!r}, found {observed!r}")


def reject_json_constant(value: str) -> None:
    raise ReleaseError(f"non-finite JSON constant prohibited: {value}")


def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ReleaseError(f"duplicate JSON key prohibited: {key}")
        value[key] = item
    return value


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=reject_json_constant,
        object_pairs_hook=reject_duplicate_pairs,
    )
    if not isinstance(value, dict):
        raise ReleaseError(f"JSON object required: {path}")
    return value


def validate_pinned_inputs() -> dict[str, dict[str, str]]:
    report: dict[str, dict[str, str]] = {}
    for label, (path, expected_hash) in PINNED_INPUTS.items():
        if not path.is_file() or path.is_symlink() or path.stat().st_nlink != 1:
            raise ReleaseError(f"regular single-link input required: {path}")
        if not path.resolve(strict=True).is_relative_to(ROOT.resolve(strict=True)):
            raise ReleaseError(f"input escapes repository: {path}")
        observed = sha256(path)
        require(observed, expected_hash, f"pinned input {label}")
        report[label] = {"role": label, "sha256": observed}
    return report


def context(value: str) -> str:
    try:
        return CONTEXT_MAP[value]
    except KeyError as exc:
        raise ReleaseError(f"unmapped restricted context identifier: {value!r}") from exc


def sanitize_text(value: str) -> str:
    sanitized = value.replace(str(ROOT), "repository")
    sanitized = re.sub(r"(?i)(?:file|vscode|ssh|sftp)://[^\s`\"']+", "restricted/path", sanitized)
    sanitized = re.sub(r"(?<![A-Za-z0-9])/(?:Users|home|root|private|tmp|var)/[^\s`\"']+", "restricted/path", sanitized)
    sanitized = re.sub(r"(?i)(?<![A-Za-z0-9])[A-Z]:[\\/][^\s`\"']+", "restricted/path", sanitized)
    sanitized = re.sub(
        r"(?<![A-Za-z0-9])(?:artifacts|vendor|training|paper/data)/[A-Za-z0-9_./-]+",
        "restricted/path",
        sanitized,
        flags=re.IGNORECASE,
    )
    for pattern, replacement in IDENTIFIER_REPLACEMENTS:
        sanitized = re.sub(pattern, replacement, sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"(?<![A-Za-z0-9])EXP23(?![A-Za-z0-9])", "intervention", sanitized)
    sanitized = re.sub(r"C0=A2\+Damage V0", "control", sanitized, flags=re.IGNORECASE)
    # The source protocol anticipated a public package.  This review candidate
    # has no confirmed redistribution authority, so its transcription must not
    # imply publication while that human/legal gate remains unresolved.
    sanitized = re.sub(r"\bthe public package\b", "the review package", sanitized, flags=re.IGNORECASE)
    return sanitized


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path: Path, fields: Iterable[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=tuple(fields), lineterminator="\n", extrasaction="raise")
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(output.getvalue(), encoding="utf-8")


def build_historical(stage: Path) -> None:
    source = PINNED_INPUTS["historical_units"][0]
    with source.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    require(len(rows), 2_800, "historical source rows")
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[(context(row["opponent"]), row["actual_order"])].append(row)
    require(len(grouped), 14, "historical context/order strata")
    released: list[dict[str, Any]] = []
    outcome_mismatch = 0
    available_mismatch = 0
    for (neutral, order), subset in sorted(grouped.items()):
        subset.sort(key=lambda row: int(row["seed"]))
        require(len(subset), 200, f"historical stratum {neutral}/{order}")
        seeds = [int(row["seed"]) for row in subset]
        require(seeds, list(range(seeds[0], seeds[0] + 200)), f"historical seed schedule {neutral}/{order}")
        for index, row in enumerate(subset):
            outcomes = {
                (row["c1_c2_run_win"], row["c1_c2_run_draw"]),
                (row["c1_c3_run_win"], row["c1_c3_run_draw"]),
                (row["c1_c4_run_win"], row["c1_c4_run_draw"]),
            }
            available = {
                (row["c1_c2_run_win"], row["c1_c2_run_draw"], row["c1_c2_run_decisions"]),
                (row["c1_c3_run_win"], row["c1_c3_run_draw"], row["c1_c3_run_decisions"]),
                (row["c1_c4_run_win"], row["c1_c4_run_draw"], row["c1_c4_run_decisions"]),
            }
            outcome_identical = int(len(outcomes) == 1)
            available_identical = int(len(available) == 1)
            require(int(row["c1_outcome_records_identical"]), outcome_identical, "historical stored outcome flag")
            require(int(row["c1_serialized_records_identical"]), available_identical, "historical stored available-record flag")
            outcome_mismatch += 1 - outcome_identical
            available_mismatch += 1 - available_identical
            released.append({
                "context": neutral,
                "actual_order": order,
                "unit_index": index,
                "scheduled_seed": row["seed"],
                "physical_seat": row["physical_seat"],
                "control_repeat_1_win": row["c1_c2_run_win"],
                "control_repeat_1_draw": row["c1_c2_run_draw"],
                "control_repeat_1_decisions": row["c1_c2_run_decisions"],
                "control_repeat_2_win": row["c1_c3_run_win"],
                "control_repeat_2_draw": row["c1_c3_run_draw"],
                "control_repeat_2_decisions": row["c1_c3_run_decisions"],
                "control_repeat_3_win": row["c1_c4_run_win"],
                "control_repeat_3_draw": row["c1_c4_run_draw"],
                "control_repeat_3_decisions": row["c1_c4_run_decisions"],
                "outcome_record_identical": outcome_identical,
                "available_record_identical": available_identical,
            })
    require(outcome_mismatch, 210, "historical outcome-record mismatch count")
    require(available_mismatch, 458, "historical available-record mismatch count")
    fields = (
        "context", "actual_order", "unit_index", "scheduled_seed", "physical_seat",
        "control_repeat_1_win", "control_repeat_1_draw", "control_repeat_1_decisions",
        "control_repeat_2_win", "control_repeat_2_draw", "control_repeat_2_decisions",
        "control_repeat_3_win", "control_repeat_3_draw", "control_repeat_3_decisions",
        "outcome_record_identical", "available_record_identical",
    )
    write_csv(stage / "data/processed/historical_control_repetition.csv", fields, released)
    write_json(stage / "data/processed/historical_summary.json", {
        "analysis_unit": "recorded seed/context/order repeated-control unit",
        "available_record_fields": ["win", "draw", "decision_count"],
        "available_record_mismatches": available_mismatch,
        "contexts": 7,
        "orders": 2,
        "outcome_record_fields": ["win", "draw"],
        "outcome_record_mismatches": outcome_mismatch,
        "source_sha256": PINNED_INPUTS["historical_units"][1],
        "units": len(released),
        "warning": "These are available-record projections, not retained complete traces.",
    })


def build_preflight(stage: Path) -> None:
    summary = load_json(PINNED_INPUTS["preflight_summary"][0])
    require(summary.get("protocol_commit"), PROTOCOL_COMMIT, "preflight protocol commit")
    require(summary.get("status"), "PASS", "preflight status")
    source_rows = summary.get("rows")
    if not isinstance(source_rows, list):
        raise ReleaseError("preflight summary rows are missing")
    require(len(source_rows), 20, "preflight jobs")
    released: list[dict[str, Any]] = []
    job_rows: list[dict[str, Any]] = []
    for job in sorted(source_rows, key=lambda row: (str(row["arm"]), context(str(row["opponent"])))):
        relative = PurePosixPath(str(job["source"]))
        if relative.is_absolute() or ".." in relative.parts or relative.parts[:5] != ("paper", "data", "pevl", "preflight", "raw"):
            raise ReleaseError(f"unsafe preflight source path: {relative}")
        source_path = ROOT / relative
        require(sha256(source_path), job["source_sha256"], f"preflight raw-row hash {relative.name}")
        payload = load_json(source_path)
        require(payload.get("protocol_commit"), PROTOCOL_COMMIT, "preflight row protocol commit")
        require(payload.get("protocol_id"), PROTOCOL_ID, "preflight row protocol id")
        require(payload.get("passed"), True, "preflight raw-row status")
        runs = payload.get("runs")
        if not isinstance(runs, dict) or set(runs) != {"single_a", "single_b", "workers_8"}:
            raise ReleaseError(f"unexpected preflight execution profiles: {relative}")
        indexed: dict[str, dict[str, dict[str, Any]]] = {}
        for profile in ("single_a", "single_b", "workers_8"):
            profile_rows = runs[profile]
            if not isinstance(profile_rows, list) or len(profile_rows) != 50:
                raise ReleaseError(f"preflight profile must contain 50 rows: {relative}/{profile}")
            indexed[profile] = {str(row["task_id"]): row for row in profile_rows}
            require(len(indexed[profile]), 50, f"preflight task uniqueness {relative}/{profile}")
        require(set(indexed["single_a"]), set(indexed["single_b"]), "preflight repeat task set")
        require(set(indexed["single_a"]), set(indexed["workers_8"]), "preflight worker task set")
        for task_id in sorted(indexed["single_a"], key=lambda item: (item.split("-")[0], int(item.split("-")[1]))):
            profiles = [indexed[name][task_id] for name in ("single_a", "single_b", "workers_8")]
            for row in profiles:
                require(row.get("protocol_commit"), PROTOCOL_COMMIT, "preflight execution protocol commit")
                require(row.get("protocol_id"), PROTOCOL_ID, "preflight execution protocol id")
                require(row.get("task_id"), task_id, "preflight task identity")
            scheduled = {int(row["scheduled_seed"]) for row in profiles}
            boundary = {int(row["engine_seed_uint32"]) for row in profiles}
            seats = {int(row["physical_seat"]) for row in profiles}
            orders = {str(row["actual_order"]) for row in profiles}
            require(len(scheduled), 1, "preflight scheduled-seed parity")
            require(boundary, scheduled, "preflight engine-boundary seed")
            require(len(seats), 1, "preflight seat parity")
            require(len(orders), 1, "preflight order parity")
            digests = [str(row["trace_sha256"]) for row in profiles]
            byte_counts = [int(row["trace_bytes"]) for row in profiles]
            outcomes = [(int(row["win"]), int(row["draw"])) for row in profiles]
            errors = [int(row["hero_policy_errors"]) + int(row["opponent_policy_errors"]) for row in profiles]
            decisions = [int(row["decisions"]) for row in profiles]
            flags = {
                "trace_digest_identical": int(len(set(digests)) == 1),
                "trace_bytes_identical": int(len(set(byte_counts)) == 1),
                "outcome_identical": int(len(set(outcomes)) == 1),
                "error_identical": int(len(set(errors)) == 1),
                "decision_count_identical": int(len(set(decisions)) == 1),
            }
            flags["unit_identical"] = int(all(flags.values()))
            item: dict[str, Any] = {
                "arm": job["arm"],
                "context": context(str(job["opponent"])),
                "actual_order": next(iter(orders)),
                "unit_index": int(task_id.split("-")[1]),
                "scheduled_seed": next(iter(scheduled)),
                "engine_seed_uint32": next(iter(boundary)),
                "physical_seat": next(iter(seats)),
            }
            for label, row, error_count in zip(("repeat_1", "repeat_2", "worker_profile"), profiles, errors, strict=True):
                item.update({
                    f"{label}_trace_sha256": row["trace_sha256"],
                    f"{label}_trace_bytes": row["trace_bytes"],
                    f"{label}_win": row["win"],
                    f"{label}_draw": row["draw"],
                    f"{label}_decisions": row["decisions"],
                    f"{label}_policy_errors": error_count,
                })
            item.update(flags)
            released.append(item)
        job_rows.append({
            "arm": job["arm"],
            "context": context(str(job["opponent"])),
            "trajectory_units": job["trajectory_units"],
            "executions": job["executions"],
            "mismatch_units": job["mismatch_units"],
            "trace_mismatch_units": job["trace_mismatch_units"],
            "outcome_mismatch_units": job["outcome_mismatch_units"],
            "error_mismatch_units": job["error_mismatch_units"],
            "decision_count_mismatch_units": job["decision_count_mismatch_units"],
            "passed": job["passed"],
            "source_sha256": job["source_sha256"],
        })
    require(len(released), 1_000, "preflight released units")
    require(sum(1 - int(row["unit_identical"]) for row in released), 0, "preflight released mismatches")
    fields = (
        "arm", "context", "actual_order", "unit_index", "scheduled_seed", "engine_seed_uint32", "physical_seat",
        "repeat_1_trace_sha256", "repeat_1_trace_bytes", "repeat_1_win", "repeat_1_draw", "repeat_1_decisions", "repeat_1_policy_errors",
        "repeat_2_trace_sha256", "repeat_2_trace_bytes", "repeat_2_win", "repeat_2_draw", "repeat_2_decisions", "repeat_2_policy_errors",
        "worker_profile_trace_sha256", "worker_profile_trace_bytes", "worker_profile_win", "worker_profile_draw", "worker_profile_decisions", "worker_profile_policy_errors",
        "trace_digest_identical", "trace_bytes_identical", "outcome_identical", "error_identical", "decision_count_identical", "unit_identical",
    )
    write_csv(stage / "data/processed/preflight_units.csv", fields, released)
    allowed = {
        key: summary[key]
        for key in (
            "schema_version", "analysis_id", "protocol_commit", "status", "admission_decision",
            "arms", "opponents", "trajectory_units", "executions", "mismatch_units",
            "trace_mismatch_units", "outcome_mismatch_units", "error_mismatch_units",
            "decision_count_mismatch_units", "claim_boundary",
        )
    }
    allowed["rows"] = job_rows
    allowed["trace_projection"] = "SHA-256 digest and byte count of recorded public-observation-hash/action/terminal/outcome/error/decision streams"
    write_json(stage / "data/processed/preflight_summary.json", allowed)


def build_stress(stage: Path) -> None:
    source = load_json(PINNED_INPUTS["stress_summary"][0])
    remediated = load_json(FINAL / "source_data/processed_stress.json")
    require(source.get("protocol_commit"), PROTOCOL_COMMIT, "stress protocol commit")
    require(source.get("status"), "TRACE_DIVERGENCE", "stress status")
    require(remediated.get("protocol_commit"), PROTOCOL_COMMIT, "remediated stress protocol commit")
    require(remediated.get("status"), "TRACE_DIVERGENCE", "remediated stress status")
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    rows = source.get("cluster_rows")
    if not isinstance(rows, list):
        raise ReleaseError("stress cluster rows are missing")
    for row in rows:
        grouped[(context(str(row["opponent"])), str(row["actual_order"]))].append(row)
    released_rows: list[dict[str, Any]] = []
    for (neutral, order), subset in sorted(grouped.items()):
        subset.sort(key=lambda row: int(row["scheduled_seed"]))
        require(len(subset), 50, f"stress stratum {neutral}/{order}")
        for index, row in enumerate(subset):
            released_rows.append({
                "context": neutral,
                "actual_order": order,
                "cluster_index": index,
                "trace_disagreement": bool(row["trace_disagreement"]),
                "outcome_disagreement": bool(row["outcome_disagreement"]),
                "decision_count_disagreement": bool(row["decision_count_disagreement"]),
                "error_disagreement": bool(row["error_disagreement"]),
                "policy_error_present": bool(row["policy_error_present"]),
            })
    for key in (
        "clusters", "executions", "trace_disagreement_clusters",
        "outcome_disagreement_clusters", "decision_count_disagreement_clusters",
        "error_disagreement_clusters", "policy_error_present_clusters",
    ):
        require(remediated[key], source[key], f"remediated stress {key}")
    require(
        set(remediated["strata"]),
        {f"{context(key.split('/', 1)[0])}/{key.split('/', 1)[1]}" for key in source["strata"]},
        "remediated stress strata",
    )
    allowed = {key: value for key, value in remediated.items() if key != "cluster_rows"}
    allowed["cluster_rows"] = released_rows
    allowed["trace_payloads_included"] = False
    actor_counts = source.get("first_divergence_actor_counts")
    if not isinstance(actor_counts, dict) or not actor_counts:
        raise ReleaseError("stress first-divergence actor counts are missing from retained evidence")
    source_timing = source.get("timing")
    if not isinstance(source_timing, dict) or not source_timing:
        raise ReleaseError("stress timing summaries are missing from retained evidence")
    neutral_timing: dict[str, Any] = {}
    for opponent_raw, profiles in sorted(source_timing.items()):
        if not isinstance(profiles, dict):
            raise ReleaseError("stress timing profile group is malformed")
        neutral_timing[context(str(opponent_raw))] = {
            profile: dict(values) for profile, values in sorted(profiles.items())
        }
    total_actor_observations = sum(
        int(count) for count in actor_counts.values() if isinstance(count, (int, float)) and not isinstance(count, bool)
    )
    require(total_actor_observations, int(remediated["trace_disagreement_clusters"]),
            "actor-count observations equal trace-disagreement clusters")
    allowed["first_divergence_actor_counts_included"] = True
    allowed["first_divergence_actor_counts"] = {key: int(value) for key, value in sorted(actor_counts.items())}
    allowed["first_divergence_position_included"] = False
    allowed["first_divergence_position_reason"] = (
        "First-divergence positions were never recorded in the retained artifacts; only acting-side "
        "counts at first divergence were summarized. Raw trace payloads are restricted and are not "
        "redistributed, so independent position-level localization remains impossible."
    )
    allowed["timing_summaries_included"] = True
    allowed["timing_summaries"] = neutral_timing
    allowed["recovered_secondary_outputs_provenance"] = {
        "source_role": "stress_summary",
        "source_sha256": PINNED_INPUTS["stress_summary"][1],
        "note": (
            "Acting-side counts at first divergence and per-profile wall-clock timing summaries were "
            "recovered from the hash-pinned retained stress summary; they are processed aggregates of "
            "the author's own acquisition runs."
        ),
    }
    allowed["protocol_deviation_status"] = "PENDING_HUMAN_SIGNOFF_UNSIGNED_POSITIONS_UNRECOVERED"
    sensitivity = allowed.get("fixed_composition_reweighting_sensitivity")
    if not isinstance(sensitivity, dict):
        raise ReleaseError("stress fixed-composition sensitivity is missing")
    sensitivity = dict(sensitivity)
    sensitivity["role"] = (
        "post-acquisition fixed-composition descriptive sensitivity applied to the pooled "
        "resampling computation prespecified in the frozen plan"
    )
    allowed["fixed_composition_reweighting_sensitivity"] = sensitivity
    write_json(stage / "data/processed/timed_search_stress.json", allowed)


def build_factorial(stage: Path) -> None:
    summary = load_json(PINNED_INPUTS["factorial_summary"][0])
    remediated = load_json(FINAL / "source_data/processed_factorial.json")
    require(summary.get("protocol_commit"), PROTOCOL_COMMIT, "factorial protocol commit")
    require(summary.get("status"), "ADMITTED_SEED_MATCHED", "factorial status")
    require(remediated.get("protocol_commit"), PROTOCOL_COMMIT, "remediated factorial protocol commit")
    with PINNED_INPUTS["factorial_units"][0].open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        source_fields = tuple(reader.fieldnames or ())
    expected_source_fields = (
        "opponent", "actual_order", "pair_index", "scheduled_seed", "engine_seed_uint32", "physical_seat",
        "c1_win", "c2_win", "c3_win", "c4_win", "c1_draw", "c2_draw", "c3_draw", "c4_draw",
        "c1_decisions", "c2_decisions", "c3_decisions", "c4_decisions",
    )
    require(source_fields, expected_source_fields, "factorial source schema")
    require(len(rows), 2_000, "factorial source units")
    fields = ("context",) + expected_source_fields[1:]
    released = [{"context": context(row["opponent"]), **{key: row[key] for key in expected_source_fields[1:]}} for row in rows]
    write_csv(stage / "data/processed/factorial_units.csv", fields, released)
    for key in ("units", "games", "control_mismatch_units", "cell_win_rates"):
        require(remediated[key], summary[key], f"remediated factorial {key}")
    allowed = dict(remediated)
    allowed["raw_traces_included"] = False
    allowed["legacy_acquisition_status"] = summary.get("status")
    allowed["legacy_acquisition_status_meaning"] = (
        "Frozen-plan binary acquisition status recorded at acquisition time; it is not an "
        "inferential or reporting claim."
    )
    allowed["final_reporting_status"] = "ADMITTED_FIXED_BATTERY_DESCRIPTIVE"
    allowed["final_reporting_status_reason"] = (
        "Post-acquisition conservative reporting: only a fixed-battery descriptive seed-indexed "
        "contrast and empirical reweighting sensitivity are admitted; no population effect, "
        "trace-parity, event-aligned, counterfactual, or full-CRN wording is authorized."
    )
    allowed["mcnemar_recalculation_included"] = False
    allowed["mcnemar_recalculation_reason"] = (
        "The arithmetic was checked separately but is omitted because its reference-distribution assumptions "
        "are not established and no McNemar inference is displayed in the manuscript."
    )
    write_json(stage / "data/processed/factorial_summary.json", allowed)


def copy_static_inputs(stage: Path) -> None:
    for relative in sorted(TEMPLATE_FILES):
        source = TEMPLATES / relative
        if not source.is_file() or source.is_symlink():
            raise ReleaseError(f"release template missing: {source}")
        destination = stage / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    shutil.copyfile(PINNED_INPUTS["synthetic_implementation"][0], stage / "pevl_bench/synthetic.py")
    synthetic_destinations = {
        "synthetic_manifest": "MANIFEST.sha256",
        "synthetic_matrix": "pevl_matrix.csv",
        "synthetic_results": "pevl_results.json",
        "synthetic_schema": "pevl_results.schema.json",
    }
    for label, destination_name in synthetic_destinations.items():
        destination = stage / "pevl_bench/results" / destination_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PINNED_INPUTS[label][0], destination)
    for label, destination_name in PROTOCOLS.items():
        source_text = PINNED_INPUTS[label][0].read_text(encoding="utf-8")
        banner = (
            "> **Review-package transcription.** Restricted labels and local paths are neutralized. "
            "The statistical plan and identifiers are preserved, but these bytes are not the frozen source artifact. "
            "The original finite-population paired-bootstrap interval and secondary exact-McNemar language remains visible "
            "below and records the frozen case-study plan. The current Level-6 fixed-battery descriptive-only restriction "
            "is a later, post-acquisition conservative reporting rule: it is not frozen provenance and is not evidence that "
            "the claim taxonomy was prospectively validated. Future adopters must freeze that taxonomy and its uncertainty "
            "rules before acquisition. "
            "Statements about noninspection are protocol conditions; Git proves commit ordering, not when a human inspected uncommitted files. "
            "Historical statements below about package contents are not current availability claims: the package actually distributed is defined "
            "by the release manifest, README, processed metadata, and PROTOCOL_DEVIATIONS.md. Acting-side first-divergence counts and timing "
            "summaries were recovered from hash-pinned retained evidence and are included as processed aggregates; first-divergence positions "
            "were never recorded and raw trace payloads remain restricted.\n\n"
        )
        destination = stage / "docs/protocols" / destination_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(banner + sanitize_text(source_text), encoding="utf-8")
    for name in sorted(SOURCE_DATA_FILES):
        source = FINAL / "source_data" / name
        if not source.is_file() or source.is_symlink():
            raise ReleaseError(f"required source-data file missing: {source}")
        destination = stage / "source_data" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if name == "figure_2_admission_flow.json":
            payload = load_json(source)
            original_action = payload.get("success_action")
            if original_action != "apply the evidence-to-claim rule with its provenance stated":
                raise ReleaseError("source figure-2 provenance wording changed unexpectedly")
            payload["success_action"] = "apply the current post-acquisition map"
            write_json(destination, payload)
        else:
            shutil.copyfile(source, destination)
    (stage / "generated").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FINAL / "results_macros.tex", stage / "generated/results_macros.tex")
    shutil.copyfile(FINAL / "tests/test_equations.py", stage / "tests/test_equations.py")


def write_metadata(stage: Path, input_report: dict[str, dict[str, str]]) -> None:
    readme = """# Pairing-assumption validation protocol: review and reproducibility package

This engine-independent package accompanies the Protocol Article **“A Protocol
for Validating Pairing Assumptions in Seed-Matched Evaluations of Black-Box
Game-Playing Agents.”** It contains the synthetic conformance implementation, expected
fixtures, neutralized processed diagnostics, processed factorial rows, sanitized
protocol transcriptions, analysis checks, figure/table code, tests, hashes, and
source data. It does not contain the restricted game engine or source, engine
binaries, third-party opponent packages, game assets or metadata, policy
packages, private observations, raw restricted traces, credentials, or archives.

## Quick start

Clean-environment verification passed: a fresh virtual environment built from
`requirements-lock.txt` (Python 3.11.5, NumPy 2.4.6, Matplotlib 3.10.5,
pytest 9.1.1) ran every command below successfully; see
`CLEAN_ENV_REPRODUCTION.json` in the article repository for the recorded
transitive freeze, platform scope, and commands.

For a new conda environment:

```bash
conda env create --file environment.yml
conda activate trace-validation-review
python -B scripts/verify_release.py
python -B -m pytest -q -p no:cacheprovider
```

For a new virtual environment created outside this exact-tree release directory:

```bash
python3 -m venv ../trace-validation-review-venv
source ../trace-validation-review-venv/bin/activate
python -m pip install --requirement requirements-lock.txt
python -B scripts/verify_release.py
python -B -m pytest -q -p no:cacheprovider
```

`requirements-lock.txt` and `environment.yml` pin the directly requested
packages only; neither is a transitive dependency lock. The recorded clean run
observed the transitive versions listed in `CLEAN_ENV_REPRODUCTION.json`
(contourpy 1.3.3, cycler 0.12.1, fonttools 4.63.0, iniconfig 2.3.0,
kiwisolver 1.5.0, packaging 26.3, pillow 12.3.0, pluggy 1.6.0,
Pygments 2.21.0, pyparsing 3.3.2, python-dateutil 2.9.0.post0, six 1.17.0)
on macOS arm64 with CPython 3.11.5; universal cross-platform portability is
not claimed.

From this directory:

```bash
python -B -m pevl_bench generate
python -B -m pevl_bench verify
python -B -m pevl_bench admit examples/example_evidence.json
python -B -m pevl_bench explain examples/example_evidence.json
python -B -m pevl_bench report
python -B -m pevl_bench report --decision-table
python -B scripts/verify_release.py
python -B scripts/build_figures_tables.py
python -B -m pytest -q -p no:cacheprovider
```

When this directory is used inside the complete repository checkout, run the
full article-level rebuild from the repository root:

```bash
python -B paper/final_protocol/scripts/reproduce_all.py
```

`generate` deterministically recreates the four synthetic fixture files in
`pevl_bench/results/` and the two synthetic-admission adapter files in
`pevl_bench/admission_results/`; `verify` compares those bytes with the executable
models and executes the bundled JSON Schema through the checked standard-library
validator. `admit` accepts only the closed file-bound record-bundle
schema, checks its canonical evidence hash, verifies every declared bundle-relative
regular single-link artifact and trace file against its SHA-256 (and trace byte
count), derives gate states, and then invokes the common classifier. This verifies
declared bytes and internal record consistency; scientific roles and provenance
still require an external trust anchor. `classify-trusted` remains available for explicitly
prevalidated state files, but its output clearly records that it did not verify
scientific evidence. `explain` identifies the blocking gate, wording boundary,
and required redesign; and `report` prints the retained headline diagnostics or
the generated admission decision table. `verify_release.py`
independently reaggregates 2,800 historical repeated-control units, 1,000
deterministic preflight units (3,000 executions), 200 timed-search clusters, and
2,000 factorial units, including the 100,000-draw computations prespecified as
paired bootstrap procedures. Under the later reporting restriction, those
quantiles are labeled empirical reweighting sensitivities: they describe the
retained fixed batteries and are not population confidence intervals.

## Frozen plan and current reporting restriction

The frozen case-study protocols prespecified finite-population paired percentile
bootstrap intervals and secondary exact two-sided McNemar inference. That
original language remains visible in `docs/protocols/`. The bundled Level-6
fixed-battery descriptive-only taxonomy is a later, post-acquisition conservative
reporting restriction. It is not part of the frozen provenance and is not
evidence of prospective validation. Future adopters must freeze the taxonomy,
gate-to-claim mapping, estimands, and uncertainty rules before data acquisition.

## Evidence boundary

The historical CSV retains only the three available control records (win, draw,
and decision count), not complete traces. The preflight CSV retains trace digests
and byte counts plus outcome/error/decision summaries, not raw observations or
opaque search state. The stress file retains cluster-level disagreement flags,
recovered acting-side first-divergence counts, and per-profile wall-clock timing
aggregates; it contains no raw trace lines. The factorial CSV retains schedule,
outcome, and decision-count fields; trace digests were not captured for that
acquisition. Neutral context labels are stable within this package but are not
external entity identifiers.

The frozen stress protocol also promised first-divergence positions and actors
and timing summaries. Acting-side first-divergence counts (all 99 disagreeing
clusters localized to the opponent side) and timing aggregates were recovered
from hash-pinned retained evidence and are included as processed aggregates with
their source digest recorded; their public redistribution still awaits explicit
human approval. First-divergence positions were never recorded in any retained
artifact, and raw trace payloads remain restricted, so position-level
localization cannot be verified from this package and no position-level claim
is made. The omitted positions do not change the primary complete-trace digest
mismatch count; the omission remains a reporting/access deviation pending human
signoff; see `docs/PROTOCOL_DEVIATIONS.md`.

## Integrity and status

`MANIFEST.sha256` covers every staged payload except itself. The release
builder rejects extra files, links, executable/archive formats, local absolute
paths, secret-like assignments, and known private identifiers. The runtime
manifest checker requires the exact manifest tree and rejects caches, `.pyc` or
`.pyo` files, links, and every other extra entry. Running it without an external
pin establishes internal consistency only and says so in its JSON report. If an
independently recorded manifest digest is available, pass it with
`--expected-manifest-sha256` to bind verification to that external trust anchor.

This is a local review candidate, not an authorized archive deposit or public
release.
Human author metadata, ownership, and license remain unconfirmed. Consequently
no DOI is supplied and `LICENSE` grants no permission. Do not cite the incomplete
`CITATION.cff` as final metadata.
"""
    (stage / "README.md").write_text(readme, encoding="utf-8")
    (stage / "LICENSE").write_text(
        "NO LICENSE GRANTED\n\n"
        "Ownership and release authority have not been confirmed by the human author.\n"
        "No copyright license, patent license, data license, or redistribution\n"
        "permission is granted by inclusion in this review package. This file must be\n"
        "replaced with an author-approved license before public distribution.\n",
        encoding="utf-8",
    )
    (stage / "THIRD_PARTY_NOTICES.md").write_text(
        "# Third-party notices\n\n"
        "No restricted engine code or binary, third-party opponent package, game asset,\n"
        "game metadata, private observation, or raw restricted trace is included. The\n"
        "synthetic implementation uses the Python standard library. Included analysis\n"
        "and figure scripts require NumPy and Matplotlib; tests use pytest. Those\n"
        "dependencies are not vendored and retain their respective upstream licenses.\n"
        "The neutralized processed rows are factual outputs whose ownership and release\n"
        "authority still require human confirmation.\n",
        encoding="utf-8",
    )
    (stage / "CITATION.cff").write_text(
        "cff-version: 1.2.0\n"
        "message: >-\n"
        "  Human author metadata is not supplied; do not treat this review metadata as a final citation.\n"
        "title: >-\n"
        "  A Protocol for Validating Pairing Assumptions in Seed-Matched Evaluations of Black-Box Game-Playing Agents\n"
        "type: dataset\n"
        "version: review-candidate-2026-08-24\n"
        "abstract: >-\n"
        "  Synthetic conformance fixtures, processed diagnostics, analysis code, and source data for a trace-based validation protocol.\n"
        "keywords:\n"
        "  - common random numbers\n"
        "  - reproducibility\n"
        "  - simulation validation\n"
        "  - trace testing\n",
        encoding="utf-8",
    )
    write_json(stage / "RELEASE_STATUS.json", {
        "article_type": "APS Open Science Protocol Article",
        "citation_metadata": "INCOMPLETE_HUMAN_AUTHOR_METADATA",
        "doi": None,
        "license": "NO_LICENSE_GRANTED_PENDING_HUMAN_CONFIRMATION",
        "machine_verification_scope": "technical internal consistency only; not human, legal, licensing, archival, or publication readiness",
        "clean_environment_build_evidenced": True,
        "clean_environment_evidence": "CLEAN_ENV_REPRODUCTION.json (article repository): fresh venv, 60 release tests passed, manifest verification PASS",
        "environment_spec_scope": "direct_packages_only_with_recorded_transitive_snapshot",
        "protocol_commit": PROTOCOL_COMMIT,
        "release_status": "BUILT_FOR_REVIEW_NOT_AUTHORIZED_FOR_PUBLICATION",
        "restricted_material_included": False,
        "source_inputs": input_report,
        "title": "A Protocol for Validating Pairing Assumptions in Seed-Matched Evaluations of Black-Box Game-Playing Agents",
    })
    python_version = ".".join(str(value) for value in sys.version_info[:3])
    versions = {
        name: importlib.metadata.version(name)
        for name in ("numpy", "matplotlib", "pytest")
    }
    (stage / "requirements-lock.txt").write_text(
        "# Direct package snapshot only; not a transitive dependency lock.\n"
        + "".join(f"{name}=={versions[name]}\n" for name in ("numpy", "matplotlib", "pytest")),
        encoding="utf-8",
    )
    (stage / "environment.yml").write_text(
        "# Direct package snapshot only; not a transitive dependency lock.\n"
        "name: trace-validation-review\n"
        "channels:\n  - conda-forge\n"
        "dependencies:\n"
        f"  - python={python_version}\n"
        f"  - numpy={versions['numpy']}\n"
        f"  - matplotlib={versions['matplotlib']}\n"
        f"  - pytest={versions['pytest']}\n",
        encoding="utf-8",
    )


def expected_files(include_manifest: bool) -> set[str]:
    files = {
        "README.md", "LICENSE", "CITATION.cff", "THIRD_PARTY_NOTICES.md",
        "RELEASE_STATUS.json", "requirements-lock.txt", "environment.yml",
        "generated/results_macros.tex",
        "pevl_bench/synthetic.py", "tests/test_equations.py",
        "data/processed/historical_control_repetition.csv",
        "data/processed/historical_summary.json",
        "data/processed/preflight_units.csv",
        "data/processed/preflight_summary.json",
        "data/processed/timed_search_stress.json",
        "data/processed/factorial_units.csv",
        "data/processed/factorial_summary.json",
    }
    files.update(TEMPLATE_FILES)
    files.update(f"pevl_bench/results/{name}" for name in ("MANIFEST.sha256", "pevl_matrix.csv", "pevl_results.json", "pevl_results.schema.json"))
    files.update(
        f"pevl_bench/admission_results/{name}"
        for name in ("MANIFEST.sha256", "synthetic_admission_decisions.json")
    )
    files.update(f"docs/protocols/{name}" for name in PROTOCOLS.values())
    files.update(f"source_data/{name}" for name in SOURCE_DATA_FILES)
    files.update(f"figures/{stem}.{suffix}" for stem in FIGURE_STEMS for suffix in ("pdf", "png"))
    files.update(f"tables/{name}" for name in TABLE_FILES)
    if include_manifest:
        files.add("MANIFEST.sha256")
    return files


def inspect_tree(root: Path) -> set[str]:
    files: set[str] = set()
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ReleaseError(f"symlink prohibited in release: {relative}")
        if path.is_file():
            if path.stat().st_nlink != 1:
                raise ReleaseError(f"hard-linked file prohibited in release: {relative}")
            files.add(relative)
        elif not path.is_dir():
            raise ReleaseError(f"special filesystem object prohibited: {relative}")
    return files


def validate_exact_tree(root: Path, expected: set[str]) -> None:
    actual = inspect_tree(root)
    actual_directories = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_dir() and not path.is_symlink()
    }
    expected_directories = {
        parent.as_posix()
        for relative in expected
        for parent in PurePosixPath(relative).parents
        if parent.as_posix() != "."
    }
    if actual != expected or actual_directories != expected_directories:
        raise ReleaseError(
            "release allow-list mismatch: "
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}, "
            f"missing_directories={sorted(expected_directories - actual_directories)}, "
            f"extra_directories={sorted(actual_directories - expected_directories)}"
        )


def scan_release(root: Path) -> dict[str, Any]:
    problems: list[str] = []
    for relative in sorted(inspect_tree(root)):
        path = root / relative
        data = path.read_bytes()
        suffix = path.suffix.lower()
        if suffix in PROHIBITED_SUFFIXES:
            problems.append(f"prohibited suffix: {relative}")
        for magic, label in PROHIBITED_MAGIC.items():
            if data.startswith(magic):
                problems.append(f"prohibited {label}: {relative}")
        if suffix == ".pdf":
            if len(data) < 100 or not data.startswith(b"%PDF-") or b"%%EOF" not in data[-1024:]:
                problems.append(f"invalid PDF: {relative}")
            if LOCAL_ROOT_PATTERN.search(data) or WINDOWS_ROOT_PATTERN.search(data):
                problems.append(f"local absolute path in PDF: {relative}")
            continue
        if suffix == ".png":
            if len(data) < 32 or not data.startswith(b"\x89PNG\r\n\x1a\n") or not data.endswith(b"\x00\x00\x00\x00IEND\xaeB`\x82"):
                problems.append(f"invalid PNG: {relative}")
            if LOCAL_ROOT_PATTERN.search(data) or WINDOWS_ROOT_PATTERN.search(data):
                problems.append(f"local absolute path in PNG: {relative}")
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            problems.append(f"non-UTF-8 text payload: {relative}")
            continue
        searchable = relative + "\n" + text
        if LOCAL_ROOT_PATTERN.search(searchable.encode()) or WINDOWS_ROOT_PATTERN.search(searchable.encode()):
            problems.append(f"local absolute path: {relative}")
        for pattern in PROHIBITED_IDENTIFIERS:
            if pattern.search(searchable):
                problems.append(f"private identifier {pattern.pattern!r}: {relative}")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                problems.append(f"secret-like assignment: {relative}")
    if problems:
        raise ReleaseError("release scan failed:\n" + "\n".join(sorted(set(problems))))
    return {"files_scanned": len(inspect_tree(root)), "problems": 0}


def write_manifest(root: Path) -> None:
    expected = expected_files(False)
    validate_exact_tree(root, expected)
    rows = [f"{sha256(root / relative)}  {relative}" for relative in sorted(expected)]
    (root / "MANIFEST.sha256").write_text("\n".join(rows) + "\n", encoding="utf-8")


def verify_manifest(root: Path) -> dict[str, Any]:
    validate_exact_tree(root, expected_files(True))
    entries: dict[str, str] = {}
    for number, line in enumerate((root / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines(), 1):
        match = MANIFEST_LINE.fullmatch(line)
        if not match:
            raise ReleaseError(f"malformed manifest line {number}")
        digest, relative = match.groups()
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts or relative != pure.as_posix() or relative in entries:
            raise ReleaseError(f"unsafe or duplicate manifest path on line {number}: {relative!r}")
        entries[relative] = digest
    require(set(entries), expected_files(False), "manifest entry set")
    for relative, digest in entries.items():
        require(sha256(root / relative), digest, f"manifest digest {relative}")
    return {"entries": len(entries), "files_including_manifest": len(entries) + 1}


def capture_hashes(root: Path, paths: Iterable[str]) -> dict[str, str]:
    return {relative: sha256(root / relative) for relative in paths}


def require_unchanged(root: Path, before: dict[str, str], label: str) -> None:
    after = capture_hashes(root, before)
    require(after, before, label)


def purge_runtime_caches(root: Path) -> None:
    for path in sorted(root.rglob("__pycache__"), reverse=True):
        if path.is_symlink():
            raise ReleaseError(f"symlinked Python cache: {path}")
        shutil.rmtree(path)
    cache = root / ".pytest_cache"
    if cache.exists():
        if cache.is_symlink() or not cache.is_dir():
            raise ReleaseError("unexpected pytest cache object")
        shutil.rmtree(cache)


def run_stage_checks(stage: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["SOURCE_DATE_EPOCH"] = "1787529600"
    with tempfile.TemporaryDirectory(prefix="final-protocol-mpl-") as mpldir:
        env["MPLCONFIGDIR"] = mpldir
        subprocess.run([sys.executable, "-B", "scripts/build_figures_tables.py"], cwd=stage, env=env, check=True)
        generated = {relative for relative in expected_files(False) if relative.startswith(("figures/", "tables/"))}
        first = capture_hashes(stage, generated)
        subprocess.run([sys.executable, "-B", "scripts/build_figures_tables.py"], cwd=stage, env=env, check=True)
        require_unchanged(stage, first, "figure/table generation is not byte-deterministic")
    subprocess.run([sys.executable, "-B", "-m", "pevl_bench", "generate"], cwd=stage, env=env, check=True)
    subprocess.run([sys.executable, "-B", "-m", "pevl_bench", "verify"], cwd=stage, env=env, check=True)
    subprocess.run([sys.executable, "-B", "-m", "pevl_bench", "report", "--json"], cwd=stage, env=env, check=True)
    subprocess.run([sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=stage, env=env, check=True)
    purge_runtime_caches(stage)
    validate_exact_tree(stage, expected_files(False))
    scan = scan_release(stage)
    write_manifest(stage)
    manifest = verify_manifest(stage)
    protected = capture_hashes(stage, expected_files(True))
    stage_manifest_sha256 = sha256(stage / "MANIFEST.sha256")
    verified = subprocess.run(
        [
            sys.executable,
            "-B",
            "scripts/verify_release.py",
            "--expected-manifest-sha256",
            stage_manifest_sha256,
        ],
        cwd=stage,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    verifier_report = json.loads(verified.stdout)
    require(verifier_report.get("status"), "PASS", "release verifier status")
    require(
        verifier_report.get("manifest", {}).get("manifest_sha256"),
        stage_manifest_sha256,
        "release verifier manifest provenance",
    )
    purge_runtime_caches(stage)
    require_unchanged(stage, protected, "release verifier modified protected files")
    validate_exact_tree(stage, expected_files(True))
    scan_release(stage)
    return {
        "manifest": {**manifest, "sha256": stage_manifest_sha256},
        "scan": scan,
        "verification_provenance": {
            "release_verifier_status": verifier_report["status"],
            "release_verifier_manifest_trust": verifier_report["manifest"]["trust_anchor"],
            "protocol_bundle_sha256": verifier_report["admission"]["protocol_bundle_sha256"],
            "synthetic_json_schema": verifier_report["synthetic"]["json_schema"],
        },
    }


def publish(stage: Path) -> str:
    if RELEASE.is_symlink() or (RELEASE.exists() and not RELEASE.is_dir()):
        raise ReleaseError(f"release target must be a directory or absent: {RELEASE}")
    backup = FINAL / f".release-backup-{os.getpid()}"
    if backup.exists():
        raise ReleaseError(f"refusing to overwrite backup path: {backup}")
    moved_old = False
    try:
        if RELEASE.exists():
            RELEASE.rename(backup)
            moved_old = True
        stage.rename(RELEASE)
    except Exception:
        if moved_old and backup.exists() and not RELEASE.exists():
            backup.rename(RELEASE)
        raise
    if moved_old:
        shutil.rmtree(backup)
    return "staged validation followed by directory replacement"


def main() -> int:
    input_report = validate_pinned_inputs()
    stage = Path(tempfile.mkdtemp(prefix=".final-release-stage-", dir=FINAL))
    try:
        copy_static_inputs(stage)
        build_historical(stage)
        build_preflight(stage)
        build_stress(stage)
        build_factorial(stage)
        write_metadata(stage, input_report)
        report = run_stage_checks(stage)
        manifest_sha = sha256(stage / "MANIFEST.sha256")
        publication = publish(stage)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    print(json.dumps({
        "status": "PASS",
        "release": "paper/final_protocol/release",
        "manifest_sha256": manifest_sha,
        "publication": publication,
        **report,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
