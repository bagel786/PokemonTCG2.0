"""File-bound record verification for public admission.

The verifier accepts a closed, versioned evidence envelope, validates every
declared schema assertion, checks a canonical SHA-256 binding, and derives gate
states from the records.  It never reads ``result_data``.  The included schema
can establish Levels 1--5 only; Levels 6 and 7 are conservatively represented
as unavailable and not applicable until evidence with a separately reviewed
verifier is added.
"""

from __future__ import annotations

import hashlib
import os
import stat
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from .admission import (
    INPUT_SCHEMA_VERSION,
    PROTOCOL_ID,
    TRUSTED_INPUT_KIND,
    AdmissionProtocol,
    AdmissionProtocolError,
    _object_sha256,
    load_json_document,
)
from .schema_subset import CheckedSchemaError, validate_instance


EVIDENCE_BUNDLE_SCHEMA_VERSION = "admission-evidence-bundle-2.0.0"
EVIDENCE_BUNDLE_INPUT_KIND = "file_bound_record_evidence_bundle"
VERIFIER_ID = "pevl-evidence-verifier-2.0.0"
MAX_EVIDENCE_FILE_BYTES = 64 * 1024 * 1024
_ARTIFACT_ROLES = frozenset(
    {"candidate_agent", "control_agent", "engine", "protocol", "runner"}
)
_ARMS = ("candidate", "control")
_IDENTICAL_PROFILES = ("fresh-process-1", "fresh-process-2")
_REPEAT_PROFILES = (
    "fresh-process-1",
    "fresh-process-2",
    "workers-8-reverse",
)


class EvidenceVerificationError(ValueError):
    """Raised when a purported evidence bundle cannot support classification."""


def evidence_projection(document: Mapping[str, Any]) -> dict[str, Any]:
    """Return the only evidence members covered by the admission binding."""

    return {
        "gate_evidence": document["gate_evidence"],
        "trace_projection": document["trace_projection"],
    }


def compute_admission_evidence_sha256(document: Mapping[str, Any]) -> str:
    """Compute the canonical evidence binding, excluding ``result_data``."""

    return _object_sha256(evidence_projection(document))


def _certificate(
    gate: str,
    state: str,
    evidence: Any,
    reason: str,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    certificate = {
        "gate": gate,
        "state": state,
        "evidence_sha256": _object_sha256(evidence),
        "verifier_id": VERIFIER_ID,
        "reason": reason,
    }
    if details:
        certificate["machine_checkable_details"] = dict(details)
    return certificate


def _verified_file(
    root: Path,
    relative: str,
    expected_sha256: str,
    *,
    expected_bytes: int | None = None,
) -> Path:
    """Resolve and hash one regular, single-link evidence file below ``root``."""

    root = root.resolve(strict=True)
    candidate = Path(relative)
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        raise EvidenceVerificationError(f"unsafe evidence path: {relative!r}")
    path = root.joinpath(candidate)
    cursor = root
    for part in candidate.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise EvidenceVerificationError(
                f"symlinked evidence path component prohibited: {relative}"
            )
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise EvidenceVerificationError(f"evidence file is missing: {relative}") from exc
    if not resolved.is_relative_to(root):
        raise EvidenceVerificationError(f"evidence path escapes bundle directory: {relative}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise EvidenceVerificationError(
            f"regular non-symlink evidence file could not be opened: {relative}"
        ) from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise EvidenceVerificationError(
                f"regular single-link evidence file required: {relative}"
            )
        if metadata.st_size > MAX_EVIDENCE_FILE_BYTES:
            raise EvidenceVerificationError(
                f"evidence file exceeds the {MAX_EVIDENCE_FILE_BYTES}-byte bound: {relative}"
            )
        digest = hashlib.sha256()
        observed_bytes = 0
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            digest.update(block)
            observed_bytes += len(block)
    finally:
        os.close(descriptor)
    observed = digest.hexdigest()
    if observed != expected_sha256:
        raise EvidenceVerificationError(
            f"evidence SHA-256 mismatch for {relative}: expected {expected_sha256}, found {observed}"
        )
    if expected_bytes is not None and observed_bytes != expected_bytes:
        raise EvidenceVerificationError(
            f"evidence byte-count mismatch for {relative}: expected {expected_bytes}, found {observed_bytes}"
        )
    return resolved


def _declared_evidence_paths(document: Mapping[str, Any]) -> set[str]:
    gate_evidence = document["gate_evidence"]
    paths = {
        row["path"] for row in gate_evidence["artifact_identity"]["artifacts"]
    }
    paths.add(gate_evidence["artifact_identity"]["configuration_path"])
    for row in gate_evidence["schedule"]["rows"]:
        paths.add(row["condition_path"])
        paths.add(row["initial_state_path"])
    for row in gate_evidence["execution_profiles"]["records"]:
        paths.add(row["trace_path"])
    if any(PurePosixPath(path).parts[0] != "evidence" for path in paths):
        raise EvidenceVerificationError(
            "every supporting path must be below the dedicated evidence/ directory"
        )
    return paths


def _verify_closed_evidence_tree(
    document: Mapping[str, Any], evidence_root: Path
) -> None:
    """Reject undeclared support files, links, special objects, and empty extras."""

    root = evidence_root.resolve(strict=True)
    expected_files = _declared_evidence_paths(document)
    support = root / "evidence"
    if support.is_symlink() or not support.is_dir():
        raise EvidenceVerificationError("a regular evidence/ support directory is required")
    actual_files: set[str] = set()
    actual_directories: set[str] = set()
    for path in support.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise EvidenceVerificationError(
                f"symlink prohibited in evidence support tree: {relative}"
            )
        if path.is_file():
            if path.stat().st_nlink != 1:
                raise EvidenceVerificationError(
                    f"hard-linked file prohibited in evidence support tree: {relative}"
                )
            actual_files.add(relative)
        elif path.is_dir():
            actual_directories.add(relative)
        else:
            raise EvidenceVerificationError(
                f"special object prohibited in evidence support tree: {relative}"
            )
    expected_directories = {
        parent.as_posix()
        for relative in expected_files
        for parent in PurePosixPath(relative).parents
        if parent.as_posix() not in {".", "evidence"}
    }
    if actual_files != expected_files or actual_directories != expected_directories:
        raise EvidenceVerificationError(
            "evidence support tree differs from the declared closed set: "
            f"missing={sorted(expected_files - actual_files)}, "
            f"extra={sorted(actual_files - expected_files)}, "
            f"missing_directories={sorted(expected_directories - actual_directories)}, "
            f"extra_directories={sorted(actual_directories - expected_directories)}"
        )


def _artifact_state(value: Mapping[str, Any], evidence_root: Path) -> tuple[str, str]:
    roles = [row["role"] for row in value["artifacts"]]
    if len(roles) != len(set(roles)):
        return "malformed", "artifact roles are duplicated"
    if set(roles) != _ARTIFACT_ROLES:
        return "malformed", "artifact roles do not form the required closed role set"
    for row in value["artifacts"]:
        _verified_file(evidence_root, row["path"], row["sha256"])
    _verified_file(
        evidence_root,
        value["configuration_path"],
        value["configuration_sha256"],
    )
    return "pass", "five required artifact files and the configuration file match their SHA-256 identities"


def _schedule_states(
    value: Mapping[str, Any], evidence_root: Path
) -> tuple[tuple[str, str], tuple[str, str]]:
    rows = value["rows"]
    keyed: dict[tuple[str, str], Mapping[str, Any]] = {}
    by_pair: dict[str, dict[str, Mapping[str, Any]]] = defaultdict(dict)
    engine_to_requested: dict[int, int] = {}
    conversion_mismatch = False
    collision = False
    for row in rows:
        _verified_file(evidence_root, row["condition_path"], row["condition_sha256"])
        _verified_file(evidence_root, row["initial_state_path"], row["initial_state_sha256"])
        key = (row["pair_id"], row["arm"])
        if key in keyed:
            malformed = ("malformed", f"duplicate schedule row for {key[0]}/{key[1]}")
            return malformed, malformed
        keyed[key] = row
        by_pair[row["pair_id"]][row["arm"]] = row
        expected = row["requested_seed"] % (2**32)
        if row["engine_seed_uint32"] != expected:
            conversion_mismatch = True
        previous = engine_to_requested.setdefault(row["engine_seed_uint32"], row["requested_seed"])
        if previous != row["requested_seed"]:
            collision = True

    incomplete = [pair_id for pair_id, arms in by_pair.items() if set(arms) != set(_ARMS)]
    if incomplete:
        malformed = (
            "malformed",
            "each schedule pair must contain exactly candidate and control rows: "
            + ", ".join(sorted(incomplete)),
        )
        return malformed, malformed

    if conversion_mismatch or collision:
        details = []
        if conversion_mismatch:
            details.append("a boundary seed violates the declared uint32 conversion")
        if collision:
            details.append("distinct requested seeds collide at the engine boundary")
        seed_state = ("fail", "; ".join(details))
    else:
        seed_state = ("pass", "all boundary seeds satisfy the declared conversion without namespace collisions")

    paired_fields: Sequence[str] = value["paired_fields"]
    mismatched_pairs = []
    for pair_id, arms in by_pair.items():
        candidate = arms["candidate"]
        control = arms["control"]
        if any(candidate[field] != control[field] for field in paired_fields):
            mismatched_pairs.append(pair_id)
    schedule_state = (
        ("fail", "paired schedule fields disagree for: " + ", ".join(sorted(mismatched_pairs)))
        if mismatched_pairs
        else ("pass", "candidate and control rows match on every declared paired field")
    )
    return seed_state, schedule_state


def _execution_signature(record: Mapping[str, Any]) -> tuple[Any, ...]:
    # Values are compared for equality only; their direction/favorability is
    # irrelevant.  Top-level result_data is neither read nor hashed.
    return (
        record["trace_sha256"],
        record["trace_bytes"],
        record["outcome"],
        record["error_count"],
        record["decision_count"],
    )


def _execution_states(
    value: Mapping[str, Any], pair_ids: Sequence[str], evidence_root: Path
) -> tuple[tuple[str, str], tuple[str, str]]:
    records: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for record in value["records"]:
        _verified_file(
            evidence_root,
            record["trace_path"],
            record["trace_sha256"],
            expected_bytes=record["trace_bytes"],
        )
        key = (record["pair_id"], record["arm"], record["profile"])
        if key in records:
            malformed = (
                "malformed",
                f"duplicate execution record for {key[0]}/{key[1]}/{key[2]}",
            )
            return malformed, malformed
        records[key] = record

    expected = {
        (pair_id, arm, profile)
        for pair_id in pair_ids
        for arm in _ARMS
        for profile in _REPEAT_PROFILES
    }
    observed = set(records)
    if observed != expected:
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        malformed = (
            "malformed",
            f"execution profile coverage differs: missing={missing}, extra={extra}",
        )
        return malformed, malformed

    identical_mismatches = []
    repeat_mismatches = []
    for pair_id in pair_ids:
        for arm in _ARMS:
            fresh = [
                _execution_signature(records[(pair_id, arm, profile)])
                for profile in _IDENTICAL_PROFILES
            ]
            repeated = [
                _execution_signature(records[(pair_id, arm, profile)])
                for profile in _REPEAT_PROFILES
            ]
            label = f"{pair_id}/{arm}"
            if len(set(fresh)) != 1:
                identical_mismatches.append(label)
            if len(set(repeated)) != 1:
                repeat_mismatches.append(label)

    identical_state = (
        ("fail", "fresh-process records disagree for: " + ", ".join(identical_mismatches))
        if identical_mismatches
        else ("pass", "fresh-process records agree within every pair and arm")
    )
    repeat_state = (
        ("fail", "repeat/worker records disagree for: " + ", ".join(repeat_mismatches))
        if repeat_mismatches
        else ("pass", "all declared repeat and worker profiles agree within every pair and arm")
    )
    return identical_state, repeat_state


def derive_gate_states(
    document: Mapping[str, Any], protocol: AdmissionProtocol, evidence_root: Path
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Derive all seven states and per-gate certificates from validated records."""

    gate_evidence = document["gate_evidence"]
    artifact = gate_evidence["artifact_identity"]
    schedule = gate_evidence["schedule"]
    execution = gate_evidence["execution_profiles"]
    source = gate_evidence["stochastic_source_audit"]
    alignment = gate_evidence["cross_arm_event_alignment"]

    artifact_state = _artifact_state(artifact, evidence_root)
    seed_state, schedule_state = _schedule_states(schedule, evidence_root)
    pair_ids = sorted({row["pair_id"] for row in schedule["rows"]})
    identical_state, repeat_state = _execution_states(execution, pair_ids, evidence_root)
    execution_details = {
        "stage4_within_artifact_fresh_process_repeatability": {
            "required_profiles": list(_IDENTICAL_PROFILES),
            "compared_record_fields": ["trace_sha256", "trace_bytes", "outcome", "error_count", "decision_count"],
            "scope": (
                "byte-identical artifacts re-executed in fresh processes on the same declared "
                "schedule rows; launch provenance is a caller/external trust anchor"
            ),
        },
        "stage5_execution_context_parity": {
            "required_profiles": list(_REPEAT_PROFILES),
            "compared_record_fields": ["trace_sha256", "trace_bytes", "outcome", "error_count", "decision_count"],
            "scope": (
                "declared worker/enqueue/pool-lifecycle profile variation; the stage-4 fresh-process "
                "profiles are a subset of this required set, so the gates are nested rather than "
                "independent"
            ),
        },
        "record_binding": {
            "pair_arms": len(pair_ids) * len(_ARMS),
            "records_per_pair_arm": len(_REPEAT_PROFILES),
            "artifact_roles_verified_by_level_1_records": sorted(_ARTIFACT_ROLES),
        },
    }
    states_with_evidence = (
        ("artifact_identity", artifact_state, artifact, None),
        ("seed_namespace_integrity", seed_state, schedule, None),
        ("schedule_parity", schedule_state, schedule, None),
        ("identical_arm_record_parity", identical_state, execution, execution_details["stage4_within_artifact_fresh_process_repeatability"]),
        ("repeat_and_worker_parity", repeat_state, execution, execution_details["stage5_execution_context_parity"]),
        (
            "stochastic_source_audit",
            ("unavailable", source["reason"]),
            source,
            None,
        ),
        (
            "cross_arm_event_alignment",
            ("not_applicable", alignment["reason"]),
            alignment,
            None,
        ),
    )
    states = {gate: state for gate, (state, _), _evidence, _d in states_with_evidence}
    if tuple(states) != protocol.gate_order:
        raise EvidenceVerificationError("derived gate order differs from the protocol")
    certificates = [
        _certificate(gate, state, evidence, reason, details)
        for gate, (state, reason), evidence, details in states_with_evidence
    ]
    return states, certificates


def verify_and_admit(
    document: Mapping[str, Any] | Any,
    protocol: AdmissionProtocol | None = None,
    *,
    evidence_root: Path | None = None,
) -> dict[str, Any]:
    """Verify a standardized evidence bundle and classify its derived states."""

    protocol = protocol or AdmissionProtocol.load()
    binding: str | None = None
    try:
        validate_instance(document, protocol.evidence_schema, label="evidence bundle")
        if not isinstance(document, Mapping):
            raise EvidenceVerificationError("evidence bundle must be an object")
        if evidence_root is None:
            raise EvidenceVerificationError(
                "evidence_root is required so declared artifact and trace bytes can be verified"
            )
        binding = compute_admission_evidence_sha256(document)
        if document["admission_evidence_sha256"] != binding:
            raise EvidenceVerificationError(
                "admission_evidence_sha256 contradicts the canonical gate-evidence projection"
            )
        _verify_closed_evidence_tree(document, Path(evidence_root))
        states, certificates = derive_gate_states(document, protocol, Path(evidence_root))
    except (CheckedSchemaError, EvidenceVerificationError, KeyError, OSError, TypeError, ValueError) as exc:
        return protocol.invalid_verified_evidence(
            [str(exc)], evidence_binding_sha256=binding, verifier_id=VERIFIER_ID
        )

    trusted_document = {
        "schema_version": INPUT_SCHEMA_VERSION,
        "protocol_id": PROTOCOL_ID,
        "input_kind": TRUSTED_INPUT_KIND,
        "evidence": states,
        "trace_projection": document["trace_projection"],
    }
    decision = protocol._evaluate_verifier_states(
        trusted_document,
        evidence_binding_sha256=binding,
        verifier_id=VERIFIER_ID,
        gate_certificates=certificates,
    )
    decision["evidence_bundle_schema_version"] = EVIDENCE_BUNDLE_SCHEMA_VERSION
    decision.pop("decision_sha256", None)
    decision["decision_sha256"] = _object_sha256(decision)
    return decision


def admit_file(path: Path, protocol: AdmissionProtocol | None = None) -> dict[str, Any]:
    protocol = protocol or AdmissionProtocol.load()
    path = Path(path)
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
            raise AdmissionProtocolError(
                "evidence envelope must be a regular single-link non-symlink file"
            )
        document = load_json_document(Path(path))
    except AdmissionProtocolError as exc:
        return protocol.invalid_verified_evidence([str(exc)], verifier_id=VERIFIER_ID)
    return verify_and_admit(document, protocol, evidence_root=path.parent)
