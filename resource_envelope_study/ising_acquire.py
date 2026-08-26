"""Bounded, paired-batch acquisition for the open Ising companion arm.

This module never provisions or starts cloud resources.  Pilot/final execution
requires an already-authorized Azure Linux host, then reuses the study's
``ResourceEnvelope`` for affinity and external CPU contention.  Each load batch
is materialized as one atomic commit containing both load periods; the first
invalid batch stops acquisition without synthesizing replacement outcomes.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import platform
import queue
import subprocess
import sys
import time
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from training.azure_guard import is_azure_host

from .canonical import canonical_json_bytes, hash_file, hash_json
from .freeze import load_and_validate_freeze_manifest
from .ising_experiment import (
    ISING_RESULT_SCHEMA_VERSION,
    build_instrumentation_case_rows,
    execute_ising_case,
    instrumentation_result_record,
    validate_ising_case_result_against_row,
    validate_ising_manifest,
)
from .orchestration_guard import arm_parent_death_kill
from .period_journal import (
    atomic_write_new as write_period_journal,
    build_period_journal,
    discover_period_journals,
    period_journal_path,
    validate_period_journal_common,
)
from .process_safety import stop_process
from .resource_controller import LoadProfile, ResourceEnvelope, system_snapshot


ISING_BATCH_COMMIT_SCHEMA_VERSION = "ising-paired-batch-commit-1.0.0"
ISING_INVALID_ATTEMPT_SCHEMA_VERSION = "ising-invalid-batch-attempt-1.0.0"
ISING_ACQUISITION_SCHEMA_VERSION = "ising-acquisition-summary-1.0.0"
ISING_RESOURCE_VALIDATION_SCHEMA_VERSION = "ising-resource-profile-validation-1.0.0"
ISING_RUN_AUTHORIZATION_SCHEMA_VERSION = "ising-run-authorization-1.0.0"
ISING_INSTRUMENTATION_COMMIT_SCHEMA_VERSION = "ising-instrumentation-pair-commit-1.0.0"
REQUIRED_THREAD_ENV = frozenset(
    {
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "PYTHONHASHSEED",
        "VECLIB_MAXIMUM_THREADS",
    }
)


class IsingAcquisitionError(RuntimeError):
    """A paired load batch failed and acquisition stopped fail-closed."""


class IsingBatchFailure(IsingAcquisitionError):
    """Carry all partial evidence without replacing the primary error."""

    def __init__(
        self,
        message: str,
        *,
        attempted_results: Sequence[Mapping[str, Any]],
        attempted_episodes: Sequence[Mapping[str, Any]],
        evidence_errors: Sequence[str] = (),
    ) -> None:
        super().__init__(message)
        self.attempted_results = [dict(row) for row in attempted_results]
        self.attempted_episodes = [dict(row) for row in attempted_episodes]
        self.evidence_errors = list(map(str, evidence_errors))


@dataclass(frozen=True)
class IsingAcquisitionLimits:
    """Explicit bounds checked before any benchmark child is started."""

    maximum_total_cases: int = 10_000
    maximum_burn_in_sweeps: int = 1_000_000
    maximum_fixed_sweeps: int = 1_000_000
    maximum_wall_clock_budget_ns: int = 60_000_000_000
    worker_timeout_seconds: float = 600.0
    maximum_batches: int | None = None

    def validate(self) -> None:
        if self.maximum_total_cases <= 0:
            raise ValueError("maximum_total_cases must be positive")
        if self.maximum_burn_in_sweeps < 0:
            raise ValueError("maximum_burn_in_sweeps cannot be negative")
        if self.maximum_fixed_sweeps <= 0:
            raise ValueError("maximum_fixed_sweeps must be positive")
        if self.maximum_wall_clock_budget_ns <= 0:
            raise ValueError("maximum_wall_clock_budget_ns must be positive")
        if not math_is_finite_positive(self.worker_timeout_seconds):
            raise ValueError("worker_timeout_seconds must be finite and positive")
        if self.maximum_batches is not None and self.maximum_batches <= 0:
            raise ValueError("maximum_batches must be positive when supplied")


def math_is_finite_positive(value: float) -> bool:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return False
    return numeric > 0 and numeric != float("inf") and numeric == numeric


def _artifact_without_hash(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: item
        for key, item in value.items()
        if key not in {"artifact_sha256", "content_hash", "report_hash"}
    }


def _atomic_write_new(path: Path, value: Mapping[str, Any]) -> None:
    """Atomically publish a new artifact; never overwrite prior evidence."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite acquisition artifact {path}")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    if temporary.exists():
        raise FileExistsError(f"stale acquisition temporary exists: {temporary}")
    payload = canonical_json_bytes(dict(value))
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def _atomic_replace(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    if temporary.exists():
        raise FileExistsError(f"stale acquisition temporary exists: {temporary}")
    payload = canonical_json_bytes(dict(value))
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"artifact is not a JSON object: {path}")
    return value


def _git_text(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _validate_canonical_file(
    path: Path, parsed: Mapping[str, Any], expected_sha256: str
) -> None:
    if (
        not isinstance(expected_sha256, str)
        or len(expected_sha256) != 64
        or any(character not in "0123456789abcdef" for character in expected_sha256)
    ):
        raise ValueError("expected file SHA-256 must be 64 lowercase hexadecimal characters")
    observed_bytes = path.read_bytes()
    if observed_bytes != canonical_json_bytes(dict(parsed)):
        raise RuntimeError(f"scientific artifact is not canonical JSON: {path}")
    observed_hash = hash_file(path)
    if observed_hash != expected_sha256:
        raise RuntimeError(
            f"scientific artifact hash mismatch for {path}: "
            f"expected={expected_sha256}, observed={observed_hash}"
        )


def _validate_run_authorization(
    manifest: Mapping[str, Any],
    *,
    manifest_path: Path,
    manifest_sha256: str,
    authorization_path: Path,
    authorization_sha256: str,
    limits: IsingAcquisitionLimits,
) -> str:
    authorization = _load_json(authorization_path)
    _validate_canonical_file(
        authorization_path, authorization, authorization_sha256
    )
    phase = str(manifest["config"]["phase"])
    required = {
        "schema_version": ISING_RUN_AUTHORIZATION_SCHEMA_VERSION,
        "human_approved": True,
        "cloud_cost_authorized": True,
        "diagnostic_execution_authorized": True,
        "phase": phase,
        "manifest_content_hash": manifest["content_hash"],
        "manifest_sha256": manifest_sha256,
    }
    mismatches = [key for key, value in required.items() if authorization.get(key) != value]
    if mismatches:
        raise RuntimeError(
            f"scientific run authorization mismatches: {sorted(mismatches)}"
        )
    if not str(authorization.get("approval_id", "")).strip():
        raise RuntimeError("scientific run authorization lacks a human approval ID")
    if float(authorization.get("authorized_until_unix", 0.0)) <= time.time():
        raise RuntimeError("scientific run authorization is expired")
    if int(authorization.get("maximum_load_batches", 0)) < int(
        manifest["config"]["load_batch_count"]
    ):
        raise RuntimeError("authorization does not cover all paired load batches")
    required_cases = len(manifest["rows"]) + 2 * int(
        manifest["config"]["instrumentation_pair_count"]
    )
    if int(authorization.get("maximum_total_cases", 0)) < required_cases:
        raise RuntimeError("authorization does not cover the primary and instrumentation cases")
    if float(authorization.get("maximum_worker_seconds_per_period", 0.0)) < float(
        limits.worker_timeout_seconds
    ):
        raise RuntimeError("authorization does not cover the bounded worker timeout")

    if phase == "final":
        root = Path(__file__).resolve().parents[1]
        freeze_path = root / "resource_envelope_study" / "FREEZE_MANIFEST.json"
        try:
            manifest_relative = manifest_path.resolve().relative_to(root)
            authorization_relative = authorization_path.resolve().relative_to(root)
            freeze_relative = freeze_path.resolve().relative_to(root)
        except ValueError as exc:
            raise RuntimeError(
                "final manifest, authorization, and freeze must live inside the repository"
            ) from exc
        _git_text(root, "ls-files", "--error-unmatch", str(manifest_relative))
        _git_text(root, "ls-files", "--error-unmatch", str(authorization_relative))
        _git_text(root, "ls-files", "--error-unmatch", str(freeze_relative))
        protocol_commit = str(authorization.get("protocol_commit", ""))
        if len(protocol_commit) != 40 or any(
            character not in "0123456789abcdef" for character in protocol_commit
        ):
            raise RuntimeError("final authorization lacks a full protocol freeze commit")
        current_commit = _git_text(root, "rev-parse", "HEAD")
        current_branch = _git_text(root, "branch", "--show-current")
        if authorization.get("branch") != current_branch:
            raise RuntimeError("final authorization names another branch")
        freeze = load_and_validate_freeze_manifest(
            freeze_path,
            repository_root=root,
            verify_files=True,
            require_final_authorized=True,
        )
        if freeze.get("protocol_commit") != protocol_commit:
            raise RuntimeError("Ising authorization and protocol freeze name different commits")
        if freeze.get("branch") != current_branch:
            raise RuntimeError("study-wide protocol freeze names another branch")
        if freeze.get("ising_manifest_sha256") != manifest_sha256:
            raise RuntimeError("final Ising manifest differs from the study-wide freeze")
        approval = freeze.get("human_approval")
        if not isinstance(approval, Mapping):
            raise RuntimeError("study-wide freeze lacks structured final approval")
        if approval.get("attestation_path") != authorization_relative.as_posix():
            raise RuntimeError("Ising authorization is not the frozen human attestation")
        if approval.get("attestation_sha256") != authorization_sha256:
            raise RuntimeError("frozen human-attestation hash differs from authorization file")
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", protocol_commit, current_commit],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        if ancestor.returncode != 0:
            raise RuntimeError("protocol freeze commit is not an ancestor of HEAD")
        frozen_manifest = subprocess.run(
            ["git", "show", f"{protocol_commit}:{manifest_relative.as_posix()}"],
            cwd=root,
            check=True,
            capture_output=True,
        ).stdout
        import hashlib

        if hashlib.sha256(frozen_manifest).hexdigest() != manifest_sha256:
            raise RuntimeError("final manifest differs from the pushed protocol freeze")
        if _git_text(root, "status", "--porcelain"):
            raise RuntimeError("final Ising acquisition requires a completely clean worktree")
        upstream_commit = _git_text(root, "rev-parse", "@{upstream}")
        if upstream_commit != current_commit:
            raise RuntimeError("final authorization commit is not pushed to its upstream")
        changed = set(
            filter(
                None,
                _git_text(root, "diff", "--name-only", f"{protocol_commit}..HEAD").splitlines(),
            )
        )
        if changed - {str(authorization_relative), str(freeze_relative)}:
            raise RuntimeError(
                "scientific files other than explicit authorization changed after freeze"
            )
    return authorization_sha256


def _validate_thread_env(thread_env: Mapping[str, str], *, scientific: bool) -> None:
    if set(thread_env) != REQUIRED_THREAD_ENV:
        raise ValueError(
            f"thread environment requires exactly {sorted(REQUIRED_THREAD_ENV)}"
        )
    for key in REQUIRED_THREAD_ENV - {"PYTHONHASHSEED"}:
        if str(thread_env[key]) != "1":
            raise ValueError(f"{key} must equal 1")
    if not str(thread_env["PYTHONHASHSEED"]).isdigit():
        raise ValueError("PYTHONHASHSEED must be a decimal integer")
    if scientific and int(thread_env["PYTHONHASHSEED"]) < 0:
        raise ValueError("scientific PYTHONHASHSEED cannot be negative")


def _validate_bounds(
    manifest: Mapping[str, Any], limits: IsingAcquisitionLimits
) -> None:
    limits.validate()
    rows = list(manifest["rows"])
    if len(rows) > limits.maximum_total_cases:
        raise ValueError("manifest exceeds maximum_total_cases")
    for row in rows:
        if int(row["burn_in_sweeps"]) > limits.maximum_burn_in_sweeps:
            raise ValueError("manifest burn-in exceeds acquisition bound")
        if row["budget_mode"] == "fixed_sweeps":
            if int(row["requested_sweeps"]) > limits.maximum_fixed_sweeps:
                raise ValueError("manifest fixed sweeps exceed acquisition bound")
        elif int(row["requested_budget_ns"]) > limits.maximum_wall_clock_budget_ns:
            raise ValueError("manifest wall-clock budget exceeds acquisition bound")


def _batches(manifest: Mapping[str, Any]) -> list[tuple[str, list[dict[str, Any]]]]:
    rows_by_batch: dict[str, list[dict[str, Any]]] = {}
    for row in sorted(manifest["rows"], key=lambda item: int(item["execution_index"])):
        rows_by_batch.setdefault(str(row["load_batch_id"]), []).append(dict(row))
    return list(rows_by_batch.items())


def _periods(batch_rows: Sequence[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    ordered = sorted(batch_rows, key=lambda row: int(row["execution_index"]))
    periods: list[list[dict[str, Any]]] = []
    index = 0
    while index < len(ordered):
        condition = ordered[index]["load_condition"]
        period: list[dict[str, Any]] = []
        while index < len(ordered) and ordered[index]["load_condition"] == condition:
            period.append(ordered[index])
            index += 1
        periods.append(period)
    if len(periods) != 2 or {period[0]["load_condition"] for period in periods} != {
        "idle",
        "loaded",
    }:
        raise ValueError("paired Ising batch must contain two contiguous load periods")
    return periods


def _set_and_observe_affinity(target_cpus: tuple[int, ...]) -> tuple[bool, list[int] | None]:
    if not hasattr(os, "sched_setaffinity") or not hasattr(os, "sched_getaffinity"):
        return False, None
    os.sched_setaffinity(0, set(target_cpus))
    return True, sorted(int(cpu) for cpu in os.sched_getaffinity(0))


def _worker_main(
    output_queue: Any,
    period_rows: list[dict[str, Any]],
    target_cpus: tuple[int, ...],
    require_affinity: bool,
    thread_env: dict[str, str],
    expected_parent_pid: int,
) -> None:
    parent_guard = arm_parent_death_kill(
        expected_parent_pid=expected_parent_pid,
        required=require_affinity,
    )
    runtime: dict[str, Any] = {
        "observed_process_id": os.getpid(),
        "target_cpus": list(target_cpus),
        "started_process_time_ns": time.process_time_ns(),
    }
    try:
        runtime["parent_death_kill_armed"] = parent_guard is not None
        for key, value in thread_env.items():
            os.environ[str(key)] = str(value)
        affinity_applied, observed_affinity = _set_and_observe_affinity(target_cpus)
        runtime.update(
            {
                "affinity_applied": affinity_applied,
                "observed_affinity": observed_affinity,
                "thread_env": dict(thread_env),
            }
        )
        if require_affinity and (
            not affinity_applied or observed_affinity != sorted(target_cpus)
        ):
            raise RuntimeError(
                "benchmark child affinity mismatch: "
                f"requested={list(target_cpus)}, observed={observed_affinity}"
            )
        results: list[dict[str, Any]] = []
        for row in period_rows:
            result = execute_ising_case(row)
            result["schedule_row"] = dict(row)
            result["resource_profile_contract_hash"] = hash_json(
                row["resource_profile_contract"]
            )
            result["artifact_sha256"] = hash_json(_artifact_without_hash(result))
            results.append(result)
        runtime["finished_process_time_ns"] = time.process_time_ns()
        runtime["process_time_ns_delta"] = max(
            0,
            int(runtime["finished_process_time_ns"])
            - int(runtime["started_process_time_ns"]),
        )
        output_queue.put({"ok": True, "results": results, "runtime": runtime})
    except BaseException as exc:
        runtime["finished_process_time_ns"] = time.process_time_ns()
        runtime["process_time_ns_delta"] = max(
            0,
            int(runtime["finished_process_time_ns"])
            - int(runtime["started_process_time_ns"]),
        )
        output_queue.put(
            {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
                "runtime": runtime,
            }
        )


def _validate_worker_result(
    result: Mapping[str, Any], expected_row: Mapping[str, Any]
) -> None:
    validate_ising_case_result_against_row(result, expected_row)
    if result.get("schema_version") != ISING_RESULT_SCHEMA_VERSION:
        raise ValueError("benchmark child returned wrong result schema")
    if result.get("case_id") != expected_row.get("case_id"):
        raise ValueError("benchmark child case ID mismatch")
    if canonical_json_bytes(result.get("schedule_row")) != canonical_json_bytes(
        dict(expected_row)
    ):
        raise ValueError("benchmark child embedded a changed schedule row")
    if result.get("resource_profile_contract_hash") != hash_json(
        expected_row["resource_profile_contract"]
    ):
        raise ValueError("resource-profile contract hash mismatch")
    if result.get("artifact_sha256") != hash_json(_artifact_without_hash(result)):
        raise ValueError("Ising result artifact hash mismatch")
    if result.get("terminal_status") != "ok" or result.get("cleanup_succeeded") is not True:
        raise ValueError("Ising benchmark child returned a non-success terminal result")


def _run_period_process(
    period_rows: list[dict[str, Any]],
    *,
    target_cpus: tuple[int, ...],
    require_affinity: bool,
    thread_env: Mapping[str, str],
    timeout_seconds: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    context = mp.get_context("spawn")
    output_queue = context.Queue()
    process = context.Process(
        target=_worker_main,
        args=(
            output_queue,
            period_rows,
            tuple(target_cpus),
            bool(require_affinity),
            {str(key): str(value) for key, value in thread_env.items()},
            os.getpid(),
        ),
        name=f"ising-{period_rows[0]['load_batch_id']}-{period_rows[0]['load_condition']}",
    )
    process.start()
    try:
        try:
            message = output_queue.get(timeout=float(timeout_seconds))
        except queue.Empty as exc:
            stop_process(process)
            raise TimeoutError("Ising benchmark child exceeded its bounded timeout") from exc
        process.join(timeout=10.0)
        if process.is_alive():
            stop_process(process)
            raise RuntimeError("Ising benchmark child did not exit after reporting")
    except BaseException:
        if process.is_alive():
            stop_process(process)
        output_queue.close()
        output_queue.join_thread()
        raise
    output_queue.close()
    output_queue.join_thread()
    runtime = dict(message.get("runtime", {}))
    runtime["spawned_process_id"] = process.pid
    runtime["exitcode"] = process.exitcode
    if process.exitcode != 0:
        raise RuntimeError(f"Ising benchmark child exited with {process.exitcode}")
    if message.get("ok") is not True:
        raise RuntimeError(str(message.get("error", "unknown Ising worker error")))
    if runtime.get("observed_process_id") != process.pid:
        raise RuntimeError("Ising benchmark child PID evidence mismatch")
    if require_affinity and runtime.get("observed_affinity") != sorted(target_cpus):
        raise RuntimeError("Ising benchmark child affinity evidence mismatch")
    if require_affinity and runtime.get("parent_death_kill_armed") is not True:
        raise RuntimeError("Ising benchmark child lacks parent-death protection evidence")
    raw_results = message.get("results")
    if not isinstance(raw_results, list) or len(raw_results) != len(period_rows):
        raise RuntimeError("Ising benchmark child result cardinality mismatch")
    by_case = {str(result.get("case_id")): result for result in raw_results}
    expected = {str(row["case_id"]): row for row in period_rows}
    if set(by_case) != set(expected) or len(by_case) != len(raw_results):
        raise RuntimeError("Ising benchmark child result case-set mismatch")
    for case_id, row in expected.items():
        _validate_worker_result(by_case[case_id], row)
    return [dict(result) for result in raw_results], runtime


def _episode_from_envelope(
    envelope: ResourceEnvelope, period_rows: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    metadata = dict(envelope.metadata)
    episode = {
        **metadata,
        "period_case_ids": [str(row["case_id"]) for row in period_rows],
        "metadata_hash": hash_json(metadata),
    }
    return episode


def _validate_episode_evidence(
    episode: Mapping[str, Any],
    period_rows: Sequence[Mapping[str, Any]],
    *,
    scientific: bool,
) -> None:
    # Reuse the canonical acquisition validators instead of maintaining a
    # second definition of valid affinity/load evidence.
    from .acquire import _validate_episode, _validate_scientific_episode

    _validate_episode(episode, str(period_rows[0]["load_batch_id"]), list(period_rows))
    if scientific:
        _validate_scientific_episode(episode)


def _validate_ising_period_journal(
    journal: Mapping[str, Any],
    manifest: Mapping[str, Any],
    batch_id: str,
    period_rows: list[dict[str, Any]],
    *,
    scientific: bool,
) -> None:
    condition = str(period_rows[0]["load_condition"])
    validate_period_journal_common(
        journal,
        experiment="ising",
        manifest_content_hash=str(manifest["content_hash"]),
        phase=str(manifest["config"]["phase"]),
        load_batch_id=batch_id,
        load_condition=condition,
        period_case_ids=[str(row["case_id"]) for row in period_rows],
    )
    results = list(journal["case_results"])
    if [str(result.get("case_id")) for result in results] != [
        str(row["case_id"]) for row in period_rows
    ]:
        raise ValueError("Ising period journal result order mismatch")
    for result, row in zip(results, period_rows):
        _validate_worker_result(result, row)
    _validate_episode_evidence(
        journal["resource_episode"], period_rows, scientific=scientific
    )


def _validate_existing_ising_period_journals(
    output: Path,
    manifest: Mapping[str, Any],
    commits_by_batch: Mapping[str, Mapping[str, Any]],
    batches_by_id: Mapping[str, list[dict[str, Any]]],
    *,
    scientific: bool,
) -> list[str]:
    journals_by_batch: dict[str, dict[str, Mapping[str, Any]]] = {}
    for path, journal in discover_period_journals(output):
        batch_id = str(journal.get("load_batch_id", ""))
        condition = str(journal.get("load_condition", ""))
        if batch_id not in batches_by_id:
            raise RuntimeError(f"period journal names unknown Ising batch {batch_id!r}")
        expected_path = period_journal_path(output, batch_id, condition)
        if path != expected_path:
            raise RuntimeError(f"Ising period journal is stored at the wrong path: {path}")
        by_condition = journals_by_batch.setdefault(batch_id, {})
        if condition in by_condition:
            raise RuntimeError(f"duplicate Ising {condition} journal for {batch_id}")
        period_rows = [
            row
            for row in batches_by_id[batch_id]
            if str(row["load_condition"]) == condition
        ]
        _validate_ising_period_journal(
            journal,
            manifest,
            batch_id,
            period_rows,
            scientific=scientific,
        )
        by_condition[condition] = journal

    hashes: list[str] = []
    for batch_id, by_condition in sorted(journals_by_batch.items()):
        commit = commits_by_batch.get(batch_id)
        if commit is None:
            raise IsingAcquisitionError(
                f"Ising batch {batch_id} has completed-period evidence but no atomic "
                "batch commit; preserve it and use new frozen reserve IDs"
            )
        if set(by_condition) != {"idle", "loaded"}:
            raise IsingAcquisitionError(
                f"committed Ising batch {batch_id} has an incomplete period-journal pair"
            )
        results_by_id = {
            str(result["case_id"]): result for result in commit["case_results"]
        }
        episodes_by_condition = {
            str(episode["profile"]["condition"]): episode
            for episode in commit["resource_episodes"]
        }
        for condition in ("idle", "loaded"):
            journal = by_condition[condition]
            expected_results = [
                results_by_id[str(case_id)] for case_id in journal["period_case_ids"]
            ]
            if journal["case_result_hashes"] != [
                result["artifact_sha256"] for result in expected_results
            ]:
                raise RuntimeError(
                    f"Ising journal and batch commit disagree for {batch_id}:{condition}"
                )
            episode = episodes_by_condition.get(condition)
            if episode is None or journal["resource_episode_hash"] != episode["metadata_hash"]:
                raise RuntimeError(
                    f"Ising journal and resource episode disagree for {batch_id}:{condition}"
                )
            hashes.append(str(journal["content_hash"]))
    return hashes


def _acquire_batch(
    manifest: Mapping[str, Any],
    batch_id: str,
    batch_rows: list[dict[str, Any]],
    *,
    output: Path,
    target_cpus: tuple[int, ...],
    load_workers: int,
    require_affinity: bool,
    thread_env: Mapping[str, str],
    timeout_seconds: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    all_results: list[dict[str, Any]] = []
    episodes: list[dict[str, Any]] = []
    evidence_errors: list[str] = []
    for period_rows in _periods(batch_rows):
        condition = str(period_rows[0]["load_condition"])
        profile = LoadProfile(
            condition=condition,
            worker_count=0 if condition == "idle" else int(load_workers),
            target_cpus=tuple(target_cpus),
        )
        envelope = ResourceEnvelope(
            profile,
            int(period_rows[0]["load_seed"]),
            batch_id,
            require_affinity=require_affinity,
        )
        period_results: list[dict[str, Any]] = []
        period_error: BaseException | None = None
        try:
            with envelope:
                envelope.assert_compliant()
                period_results, runtime = _run_period_process(
                    period_rows,
                    target_cpus=target_cpus,
                    require_affinity=require_affinity,
                    thread_env=thread_env,
                    timeout_seconds=timeout_seconds,
                )
                envelope.record_benchmark_worker(runtime)
                envelope.assert_compliant()
                envelope.assert_compliant(period_complete=True)
        except BaseException as exc:
            period_error = exc
        finally:
            all_results.extend(period_results)
            if envelope.metadata:
                try:
                    episode = _episode_from_envelope(envelope, period_rows)
                    episodes.append(episode)
                    try:
                        _validate_episode_evidence(
                            episode, period_rows, scientific=require_affinity
                        )
                    except BaseException as exc:
                        evidence_error = f"{type(exc).__name__}: {exc}"
                        evidence_errors.append(evidence_error)
                        if period_error is None:
                            period_error = exc
                except BaseException as exc:
                    evidence_error = (
                        f"resource episode capture failed: {type(exc).__name__}: {exc}"
                    )
                    evidence_errors.append(evidence_error)
                    if period_error is None:
                        period_error = exc
            else:
                evidence_error = "resource envelope produced no metadata"
                evidence_errors.append(evidence_error)
                if period_error is None:
                    period_error = RuntimeError(evidence_error)
        if period_error is not None:
            raise IsingBatchFailure(
                f"{type(period_error).__name__}: {period_error}",
                attempted_results=all_results,
                attempted_episodes=episodes,
                evidence_errors=evidence_errors,
            ) from period_error
        order = {
            str(row["case_id"]): index for index, row in enumerate(period_rows)
        }
        period_results.sort(key=lambda result: order[str(result["case_id"])])
        period_episode = episodes[-1]
        journal = build_period_journal(
            experiment="ising",
            manifest_content_hash=str(manifest["content_hash"]),
            phase=str(manifest["config"]["phase"]),
            load_batch_id=batch_id,
            load_condition=condition,
            period_rows=period_rows,
            case_results=period_results,
            resource_episode=period_episode,
        )
        _validate_ising_period_journal(
            journal,
            manifest,
            batch_id,
            period_rows,
            scientific=require_affinity,
        )
        write_period_journal(
            period_journal_path(output, batch_id, condition), journal
        )
    if len(all_results) != len(batch_rows) or len(episodes) != 2:
        raise IsingBatchFailure(
            "paired Ising batch did not produce complete atomic evidence",
            attempted_results=all_results,
            attempted_episodes=episodes,
            evidence_errors=evidence_errors,
        )
    return all_results, episodes


def _acquire_instrumentation_pair(
    pair_rows: list[dict[str, Any]],
    *,
    target_cpus: tuple[int, ...],
    require_affinity: bool,
    thread_env: Mapping[str, str],
    timeout_seconds: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    first = pair_rows[0]
    profile = LoadProfile(
        condition="idle",
        worker_count=0,
        target_cpus=tuple(target_cpus),
    )
    envelope = ResourceEnvelope(
        profile,
        int(first["load_seed"]),
        str(first["load_batch_id"]),
        require_affinity=require_affinity,
    )
    results: list[dict[str, Any]] = []
    primary_error: BaseException | None = None
    evidence_errors: list[str] = []
    episode: dict[str, Any] | None = None
    try:
        with envelope:
            envelope.assert_compliant()
            results, runtime = _run_period_process(
                pair_rows,
                target_cpus=target_cpus,
                require_affinity=require_affinity,
                thread_env=thread_env,
                timeout_seconds=timeout_seconds,
            )
            envelope.record_benchmark_worker(runtime)
            envelope.assert_compliant()
            envelope.assert_compliant(period_complete=True)
    except BaseException as exc:
        primary_error = exc
    finally:
        if envelope.metadata:
            try:
                episode = _episode_from_envelope(envelope, pair_rows)
                _validate_episode_evidence(
                    episode, pair_rows, scientific=require_affinity
                )
            except BaseException as exc:
                evidence_errors.append(f"{type(exc).__name__}: {exc}")
                if primary_error is None:
                    primary_error = exc
        else:
            evidence_errors.append("resource envelope produced no metadata")
            if primary_error is None:
                primary_error = RuntimeError(evidence_errors[-1])
    if primary_error is not None:
        raise IsingBatchFailure(
            f"{type(primary_error).__name__}: {primary_error}",
            attempted_results=results,
            attempted_episodes=([episode] if episode is not None else []),
            evidence_errors=evidence_errors,
        ) from primary_error
    if len(results) != 2 or episode is None:
        raise IsingBatchFailure(
            "instrumentation pair did not produce two results and one episode",
            attempted_results=results,
            attempted_episodes=([episode] if episode is not None else []),
            evidence_errors=evidence_errors,
        )
    return results, episode


def _instrumentation_commit(
    manifest: Mapping[str, Any],
    pair_rows: list[dict[str, Any]],
    results: list[dict[str, Any]],
    episode: Mapping[str, Any],
) -> dict[str, Any]:
    records = [
        instrumentation_result_record(row, result)
        for row, result in zip(pair_rows, results)
    ]
    commit: dict[str, Any] = {
        "schema_version": ISING_INSTRUMENTATION_COMMIT_SCHEMA_VERSION,
        "manifest_content_hash": manifest["content_hash"],
        "pair_id": pair_rows[0]["instrumentation_pair_id"],
        "pair_plan_hash": pair_rows[0]["pair_plan_hash"],
        "case_ids": [row["case_id"] for row in pair_rows],
        "case_result_hashes": [result["artifact_sha256"] for result in results],
        "instrumentation_record_hashes": [record["record_hash"] for record in records],
        "resource_episode_hash": episode["metadata_hash"],
        "case_results": results,
        "instrumentation_records": records,
        "resource_episode": dict(episode),
        "terminal_status": "instrumentation_pair_complete",
    }
    commit["content_hash"] = hash_json(commit)
    return commit


def _validate_instrumentation_commit(
    commit: Mapping[str, Any],
    manifest: Mapping[str, Any],
    pair_rows: list[dict[str, Any]],
    *,
    scientific: bool,
) -> None:
    if commit.get("schema_version") != ISING_INSTRUMENTATION_COMMIT_SCHEMA_VERSION:
        raise ValueError("unexpected instrumentation commit schema")
    if commit.get("content_hash") != hash_json(_artifact_without_hash(commit)):
        raise ValueError("instrumentation commit hash mismatch")
    if commit.get("manifest_content_hash") != manifest.get("content_hash"):
        raise ValueError("instrumentation commit belongs to another manifest")
    if commit.get("pair_id") != pair_rows[0]["instrumentation_pair_id"]:
        raise ValueError("instrumentation pair ID mismatch")
    if commit.get("pair_plan_hash") != pair_rows[0]["pair_plan_hash"]:
        raise ValueError("instrumentation plan-row hash mismatch")
    if commit.get("case_ids") != [row["case_id"] for row in pair_rows]:
        raise ValueError("instrumentation case order mismatch")
    results = list(commit.get("case_results", ()))
    if len(results) != 2:
        raise ValueError("instrumentation commit result cardinality mismatch")
    for row, result in zip(pair_rows, results):
        _validate_worker_result(result, row)
    if commit.get("case_result_hashes") != [
        result["artifact_sha256"] for result in results
    ]:
        raise ValueError("instrumentation result hashes do not reconcile")
    records = list(commit.get("instrumentation_records", ()))
    expected_records = [
        instrumentation_result_record(row, result)
        for row, result in zip(pair_rows, results)
    ]
    if canonical_json_bytes(records) != canonical_json_bytes(expected_records):
        raise ValueError("instrumentation summary records do not reconcile")
    if commit.get("instrumentation_record_hashes") != [
        record["record_hash"] for record in records
    ]:
        raise ValueError("instrumentation record hashes do not reconcile")
    episode = commit.get("resource_episode")
    if not isinstance(episode, Mapping):
        raise ValueError("instrumentation commit lacks a resource episode")
    _validate_episode_evidence(episode, pair_rows, scientific=scientific)
    if commit.get("resource_episode_hash") != episode.get("metadata_hash"):
        raise ValueError("instrumentation episode hash does not reconcile")


def _acquire_instrumentation_panel(
    manifest: Mapping[str, Any],
    *,
    output: Path,
    target_cpus: tuple[int, ...],
    require_affinity: bool,
    thread_env: Mapping[str, str],
    timeout_seconds: float,
    resume: bool,
) -> list[dict[str, Any]]:
    rows = build_instrumentation_case_rows(manifest)
    by_pair: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_pair.setdefault(str(row["instrumentation_pair_id"]), []).append(row)
    commits: list[dict[str, Any]] = []
    for pair_id, pair_rows in by_pair.items():
        pair_rows.sort(key=lambda row: int(row["execution_position"]))
        path = output / "instrumentation_pairs" / f"{pair_id}.json"
        if path.exists():
            if not resume:
                raise FileExistsError(
                    f"instrumentation pair already exists and resume is false: {path}"
                )
            commit = _load_json(path)
            _validate_instrumentation_commit(
                commit, manifest, pair_rows, scientific=require_affinity
            )
            commits.append(commit)
            continue
        attempted_results: list[dict[str, Any]] = []
        attempted_episodes: list[dict[str, Any]] = []
        evidence_errors: list[str] = []
        try:
            attempted_results, episode = _acquire_instrumentation_pair(
                pair_rows,
                target_cpus=target_cpus,
                require_affinity=require_affinity,
                thread_env=thread_env,
                timeout_seconds=timeout_seconds,
            )
            attempted_episodes = [episode]
            commit = _instrumentation_commit(
                manifest, pair_rows, attempted_results, episode
            )
            _validate_instrumentation_commit(
                commit, manifest, pair_rows, scientific=require_affinity
            )
            _atomic_write_new(path, commit)
            commits.append(commit)
        except BaseException as exc:
            if isinstance(exc, IsingBatchFailure):
                attempted_results = list(exc.attempted_results)
                attempted_episodes = list(exc.attempted_episodes)
                evidence_errors = list(exc.evidence_errors)
            invalid: dict[str, Any] = {
                "schema_version": ISING_INVALID_ATTEMPT_SCHEMA_VERSION,
                "manifest_content_hash": manifest["content_hash"],
                "load_batch_id": pair_rows[0]["load_batch_id"],
                "instrumentation_pair_id": pair_id,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "evidence_validation_errors": evidence_errors,
                "attempted_results": attempted_results,
                "attempted_resource_episodes": attempted_episodes,
                "terminal_status": "invalid_stopped",
            }
            invalid["content_hash"] = hash_json(invalid)
            invalid_path = output / "invalid_attempts" / f"instrumentation-{pair_id}.json"
            if not invalid_path.exists():
                _atomic_write_new(invalid_path, invalid)
            raise IsingAcquisitionError(
                f"Ising acquisition stopped at invalid instrumentation pair {pair_id}: {exc}"
            ) from exc
    return commits


def _batch_commit(
    manifest: Mapping[str, Any],
    batch_id: str,
    batch_rows: Sequence[Mapping[str, Any]],
    results: Sequence[Mapping[str, Any]],
    episodes: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    commit: dict[str, Any] = {
        "schema_version": ISING_BATCH_COMMIT_SCHEMA_VERSION,
        "manifest_content_hash": manifest["content_hash"],
        "load_batch_id": batch_id,
        "load_period_order": batch_rows[0]["load_period_order"],
        "case_ids": [str(row["case_id"]) for row in batch_rows],
        "case_result_hashes": [str(result["artifact_sha256"]) for result in results],
        "resource_episode_hashes": [str(episode["metadata_hash"]) for episode in episodes],
        "case_results": [dict(result) for result in results],
        "resource_episodes": [dict(episode) for episode in episodes],
        "terminal_status": "paired_batch_complete",
    }
    commit["content_hash"] = hash_json(commit)
    return commit


def _validate_commit(
    commit: Mapping[str, Any],
    manifest: Mapping[str, Any],
    batch_id: str,
    batch_rows: Sequence[Mapping[str, Any]],
    *,
    scientific: bool,
) -> None:
    if commit.get("schema_version") != ISING_BATCH_COMMIT_SCHEMA_VERSION:
        raise ValueError("unexpected Ising batch commit schema")
    if commit.get("content_hash") != hash_json(_artifact_without_hash(commit)):
        raise ValueError("Ising batch commit hash mismatch")
    if commit.get("manifest_content_hash") != manifest.get("content_hash"):
        raise ValueError("Ising batch commit belongs to another manifest")
    if commit.get("load_batch_id") != batch_id:
        raise ValueError("Ising batch commit ID mismatch")
    if commit.get("terminal_status") != "paired_batch_complete":
        raise ValueError("Ising batch commit is not terminally complete")
    expected_ids = [str(row["case_id"]) for row in batch_rows]
    if commit.get("case_ids") != expected_ids:
        raise ValueError("Ising batch commit case order mismatch")
    results = list(commit.get("case_results", ()))
    if len(results) != len(batch_rows):
        raise ValueError("Ising batch commit result cardinality mismatch")
    by_case = {str(result.get("case_id")): result for result in results}
    expected = {str(row["case_id"]): row for row in batch_rows}
    if set(by_case) != set(expected) or len(by_case) != len(results):
        raise ValueError("Ising batch commit case set mismatch")
    for case_id, row in expected.items():
        _validate_worker_result(by_case[case_id], row)
    embedded_result_hashes = [str(result["artifact_sha256"]) for result in results]
    if commit.get("case_result_hashes") != embedded_result_hashes:
        raise ValueError("Ising batch commit result-hash list does not reconcile")
    episodes = list(commit.get("resource_episodes", ()))
    periods = _periods(list(batch_rows))
    if len(episodes) != 2:
        raise ValueError("Ising batch commit lacks two resource episodes")
    by_condition = {
        str(episode.get("profile", {}).get("condition")): episode for episode in episodes
    }
    from .acquire import _validate_episode, _validate_scientific_episode

    for period_rows in periods:
        condition = str(period_rows[0]["load_condition"])
        if condition not in by_condition:
            raise ValueError("Ising batch commit lacks a load-period episode")
        episode = by_condition[condition]
        _validate_episode(episode, batch_id, period_rows)
        if scientific:
            _validate_scientific_episode(episode)
    embedded_episode_hashes = [str(episode["metadata_hash"]) for episode in episodes]
    if commit.get("resource_episode_hashes") != embedded_episode_hashes:
        raise ValueError("Ising batch commit episode-hash list does not reconcile")


def _resource_validation(
    manifest: Mapping[str, Any],
    commits: Sequence[Mapping[str, Any]],
    *,
    scientific: bool,
    instrumentation_commits: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    episode_hashes = [
        str(episode["metadata_hash"])
        for commit in commits
        for episode in commit["resource_episodes"]
    ]
    case_result_hashes = [
        str(result["artifact_sha256"])
        for commit in commits
        for result in commit["case_results"]
    ]
    batch_commit_hashes = [str(commit["content_hash"]) for commit in commits]
    instrumentation_result_hashes = [
        str(result["artifact_sha256"])
        for commit in instrumentation_commits
        for result in commit["case_results"]
    ]
    instrumentation_episode_hashes = [
        str(commit["resource_episode_hash"]) for commit in instrumentation_commits
    ]
    instrumentation_commit_hashes = [
        str(commit["content_hash"]) for commit in instrumentation_commits
    ]
    report: dict[str, Any] = {
        "schema_version": ISING_RESOURCE_VALIDATION_SCHEMA_VERSION,
        "manifest_content_hash": manifest["content_hash"],
        "scientific_validation": bool(scientific),
        "passed": (
            bool(scientific)
            and len(commits) == int(manifest["config"]["load_batch_count"])
            and len(instrumentation_commits)
            == int(manifest["config"]["instrumentation_pair_count"])
        ),
        "validated_load_batch_count": len(commits),
        "validated_resource_episode_count": len(episode_hashes),
        "validated_case_result_count": len(case_result_hashes),
        "batch_commit_hashes": batch_commit_hashes,
        "case_result_hashes": case_result_hashes,
        "resource_episode_hashes": episode_hashes,
        "validated_instrumentation_pair_count": len(instrumentation_commits),
        "instrumentation_pair_commit_hashes": instrumentation_commit_hashes,
        "instrumentation_result_hashes": instrumentation_result_hashes,
        "instrumentation_resource_episode_hashes": instrumentation_episode_hashes,
        "validator_contract": (
            "resource_envelope_study.acquire._validate_episode+"
            "_validate_scientific_episode"
        ),
    }
    report["report_hash"] = hash_json(report)
    return report


def acquire_ising_manifest(
    manifest: Mapping[str, Any],
    *,
    output_dir: str | Path,
    manifest_path: str | Path | None = None,
    expected_manifest_sha256: str | None = None,
    authorization_path: str | Path | None = None,
    expected_authorization_sha256: str | None = None,
    target_cpus: tuple[int, ...] = (0,),
    load_workers: int = 1,
    thread_env: Mapping[str, str] | None = None,
    expected_machine: str | None = None,
    limits: IsingAcquisitionLimits = IsingAcquisitionLimits(),
    resume: bool = False,
    include_instrumentation_panel: bool | None = None,
) -> dict[str, Any]:
    """Acquire a manifest on the current host; never starts an Azure VM."""

    validate_ising_manifest(manifest)
    _validate_bounds(manifest, limits)
    phase = str(manifest["config"]["phase"])
    scientific = phase in {"pilot", "final"}
    if include_instrumentation_panel is not None and not isinstance(
        include_instrumentation_panel, bool
    ):
        raise ValueError("include_instrumentation_panel must be boolean or null")
    run_instrumentation = (
        scientific
        if include_instrumentation_panel is None
        else include_instrumentation_panel
    )
    total_case_bound = len(manifest["rows"]) + (
        2 * int(manifest["config"]["instrumentation_pair_count"])
        if run_instrumentation
        else 0
    )
    if total_case_bound > limits.maximum_total_cases:
        raise ValueError("primary plus instrumentation cases exceed maximum_total_cases")
    if limits.maximum_batches is not None and scientific:
        raise ValueError("pilot/final acquisition cannot truncate load batches")
    if scientific:
        if (
            manifest_path is None
            or expected_manifest_sha256 is None
            or authorization_path is None
            or expected_authorization_sha256 is None
        ):
            raise RuntimeError(
                "scientific Ising acquisition requires canonical manifest and "
                "authorization paths with expected whole-file SHA-256 values"
            )
        manifest_file = Path(manifest_path).resolve()
        manifest_from_file = _load_json(manifest_file)
        if canonical_json_bytes(manifest_from_file) != canonical_json_bytes(dict(manifest)):
            raise RuntimeError("parsed scientific manifest differs from the supplied mapping")
        _validate_canonical_file(
            manifest_file, manifest_from_file, expected_manifest_sha256
        )
        authorization_hash = _validate_run_authorization(
            manifest,
            manifest_path=manifest_file,
            manifest_sha256=expected_manifest_sha256,
            authorization_path=Path(authorization_path).resolve(),
            authorization_sha256=expected_authorization_sha256,
            limits=limits,
        )
        if platform.system() != "Linux" or not is_azure_host():
            raise RuntimeError(
                "scientific Ising acquisition requires an already-authorized Azure Linux host"
            )
        if not expected_machine or platform.machine() != expected_machine:
            raise RuntimeError(
                f"machine mismatch: expected={expected_machine!r}, observed={platform.machine()!r}"
            )
    else:
        authorization_hash = None
    if (
        not target_cpus
        or any(isinstance(cpu, bool) or not isinstance(cpu, int) or cpu < 0 for cpu in target_cpus)
        or len(set(target_cpus)) != len(target_cpus)
    ):
        raise ValueError("target_cpus must contain unique non-boolean non-negative integers")
    cpu_count = os.cpu_count()
    if cpu_count is None or any(cpu >= cpu_count for cpu in target_cpus):
        raise ValueError(
            f"target_cpus {target_cpus} are unavailable on a {cpu_count}-CPU host"
        )
    if hasattr(os, "sched_getaffinity"):
        authorized_cpus = set(os.sched_getaffinity(0))
        unavailable = set(target_cpus) - authorized_cpus
        if unavailable:
            raise ValueError(
                f"target_cpus are outside the authorized CPU set: {sorted(unavailable)}"
            )
    if isinstance(load_workers, bool) or not isinstance(load_workers, int) or load_workers <= 0:
        raise ValueError("loaded acquisition requires at least one co-runner")
    controls = {
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "PYTHONHASHSEED": "0",
        "VECLIB_MAXIMUM_THREADS": "1",
    }
    if thread_env is not None:
        controls = {str(key): str(value) for key, value in thread_env.items()}
    _validate_thread_env(controls, scientific=scientific)

    output = Path(output_dir).resolve()
    batch_dir = output / "paired_batches"
    invalid_dir = output / "invalid_attempts"
    if invalid_dir.exists() and any(invalid_dir.glob("*.json")):
        raise IsingAcquisitionError(
            "output contains a prior invalid attempt; use a new audited output directory"
        )
    commits: list[dict[str, Any]] = []
    selected_batches = _batches(manifest)
    if limits.maximum_batches is not None:
        selected_batches = selected_batches[: limits.maximum_batches]
    batches_by_id = {batch_id: rows for batch_id, rows in selected_batches}
    existing_commits_by_batch: dict[str, dict[str, Any]] = {}
    if batch_dir.exists():
        unexpected = sorted(
            path for path in batch_dir.iterdir() if not path.is_file() or path.suffix != ".json"
        )
        if unexpected:
            raise IsingAcquisitionError(
                f"unexpected paired-batch artifacts: {[str(path) for path in unexpected]}"
            )
        for path in sorted(batch_dir.glob("*.json")):
            batch_id = path.stem
            batch_rows = batches_by_id.get(batch_id)
            if batch_rows is None:
                raise IsingAcquisitionError(
                    f"paired-batch artifact names unknown batch {batch_id!r}"
                )
            commit = _load_json(path)
            _validate_commit(
                commit, manifest, batch_id, batch_rows, scientific=scientific
            )
            existing_commits_by_batch[batch_id] = commit
    _validate_existing_ising_period_journals(
        output,
        manifest,
        existing_commits_by_batch,
        batches_by_id,
        scientific=scientific,
    )
    for batch_index, (batch_id, batch_rows) in enumerate(selected_batches):
        commit_path = batch_dir / f"{batch_id}.json"
        if commit_path.exists():
            if not resume:
                raise FileExistsError(
                    f"paired batch already exists and resume is false: {commit_path}"
                )
            commit = existing_commits_by_batch[batch_id]
            commits.append(commit)
            continue
        attempted_results: list[dict[str, Any]] = []
        attempted_episodes: list[dict[str, Any]] = []
        try:
            attempted_results, attempted_episodes = _acquire_batch(
                manifest,
                batch_id,
                batch_rows,
                output=output,
                target_cpus=tuple(map(int, target_cpus)),
                load_workers=int(load_workers),
                require_affinity=scientific,
                thread_env=controls,
                timeout_seconds=limits.worker_timeout_seconds,
            )
            commit = _batch_commit(
                manifest,
                batch_id,
                batch_rows,
                attempted_results,
                attempted_episodes,
            )
            _validate_commit(
                commit, manifest, batch_id, batch_rows, scientific=scientific
            )
            _atomic_write_new(commit_path, commit)
            existing_commits_by_batch[batch_id] = commit
            commits.append(commit)
        except BaseException as exc:
            evidence_errors: list[str] = []
            if isinstance(exc, IsingBatchFailure):
                attempted_results = list(exc.attempted_results)
                attempted_episodes = list(exc.attempted_episodes)
                evidence_errors = list(exc.evidence_errors)
            invalid: dict[str, Any] = {
                "schema_version": ISING_INVALID_ATTEMPT_SCHEMA_VERSION,
                "manifest_content_hash": manifest["content_hash"],
                "load_batch_id": batch_id,
                "batch_index": batch_index,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "evidence_validation_errors": evidence_errors,
                "attempted_results": attempted_results,
                "attempted_resource_episodes": attempted_episodes,
                "terminal_status": "invalid_stopped",
            }
            invalid["content_hash"] = hash_json(invalid)
            invalid_path = invalid_dir / f"{batch_id}.json"
            if not invalid_path.exists():
                _atomic_write_new(invalid_path, invalid)
            raise IsingAcquisitionError(
                f"Ising acquisition stopped at invalid paired batch {batch_id}: {exc}"
            ) from exc

    _validate_existing_ising_period_journals(
        output,
        manifest,
        existing_commits_by_batch,
        batches_by_id,
        scientific=scientific,
    )

    complete = len(commits) == int(manifest["config"]["load_batch_count"])
    instrumentation_commits: list[dict[str, Any]] = []
    if complete and run_instrumentation:
        instrumentation_commits = _acquire_instrumentation_panel(
            manifest,
            output=output,
            target_cpus=tuple(map(int, target_cpus)),
            require_affinity=scientific,
            thread_env=controls,
            timeout_seconds=limits.worker_timeout_seconds,
            resume=resume,
        )
    resource_validation = _resource_validation(
        manifest,
        commits,
        scientific=scientific,
        instrumentation_commits=instrumentation_commits,
    )
    summary: dict[str, Any] = {
        "schema_version": ISING_ACQUISITION_SCHEMA_VERSION,
        "manifest_content_hash": manifest["content_hash"],
        "phase": phase,
        "status": (
            "complete"
            if complete and run_instrumentation
            else "complete_without_instrumentation"
            if complete
            else "bounded_smoke_partial"
        ),
        "scientific": scientific,
        "committed_load_batches": len(commits),
        "scheduled_load_batches": int(manifest["config"]["load_batch_count"]),
        "committed_case_count": sum(len(commit["case_results"]) for commit in commits),
        "target_cpus": list(map(int, target_cpus)),
        "load_workers": int(load_workers),
        "thread_env": controls,
        "expected_machine": expected_machine,
        "manifest_file_sha256": expected_manifest_sha256,
        "authorization_file_sha256": authorization_hash,
        "system_snapshot": system_snapshot(),
        "python": sys.version,
        "numpy": np.__version__,
        "limits": asdict(limits),
        "batch_commit_hashes": [str(commit["content_hash"]) for commit in commits],
        "instrumentation_pair_commit_hashes": [
            str(commit["content_hash"]) for commit in instrumentation_commits
        ],
        "instrumentation_records": [
            dict(record)
            for commit in instrumentation_commits
            for record in commit["instrumentation_records"]
        ],
        "resource_profile_validation": resource_validation,
    }
    summary["content_hash"] = hash_json(summary)
    _atomic_replace(output / "acquisition_summary.json", summary)
    return summary


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--authorization", required=True)
    parser.add_argument("--authorization-sha256", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--target-cpu", type=int, action="append", required=True)
    parser.add_argument("--load-workers", type=int, default=1)
    parser.add_argument("--expected-machine")
    parser.add_argument("--worker-timeout-seconds", type=float, default=600.0)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    manifest = _load_json(Path(args.manifest).resolve())
    summary = acquire_ising_manifest(
        manifest,
        output_dir=args.output_dir,
        manifest_path=args.manifest,
        expected_manifest_sha256=args.manifest_sha256,
        authorization_path=args.authorization,
        expected_authorization_sha256=args.authorization_sha256,
        target_cpus=tuple(args.target_cpu),
        load_workers=args.load_workers,
        expected_machine=args.expected_machine,
        limits=IsingAcquisitionLimits(
            worker_timeout_seconds=args.worker_timeout_seconds
        ),
        resume=args.resume,
    )
    sys.stdout.buffer.write(canonical_json_bytes(summary))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised on authorized host
    raise SystemExit(_main())
