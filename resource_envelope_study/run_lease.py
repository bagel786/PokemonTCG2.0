"""Fail-closed, single-run authorization and durable execution leases.

The authorization is deliberately narrower than a general configuration file.
It binds one manifest, one resolved output directory, one host, one finite time
window, and one cumulative worker-second budget.  The authorization file must
be canonical JSON and is consumed under an advisory lock held for the lifetime
of the returned :class:`RunLease`.

Two identical consumption records are maintained: one beside the authorization
and one inside the output directory.  Missing or divergent copies are treated
as corruption, not as an unused authorization.  This makes copying an
authorization or changing its output path insufficient to start another run.
An interrupted run can only resume when explicitly authorized and accompanied
by a new canonical audit that hashes an existing checkpoint below the same
output directory.
"""

from __future__ import annotations

import fcntl
import json
import math
import os
import platform
import re
import secrets
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping

from .canonical import canonical_json_bytes, hash_file, hash_json, sha256_bytes


AUTHORIZATION_SCHEMA_VERSION = "run-authorization-1.0.0"
CONSUMPTION_SCHEMA_VERSION = "run-consumption-1.0.0"
RESUME_AUDIT_SCHEMA_VERSION = "run-resume-audit-1.0.0"

ResumePolicy = Literal["forbid", "audited_same_output"]
TerminalStatus = Literal["interrupted", "completed", "failed"]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,127}$")
_NONCE_RE = re.compile(r"^[0-9a-f]{32,128}$")
_MAX_EXACT_INTEGER = (1 << 63) - 1
_AUTHORIZATION_KEYS = frozenset(
    {
        "schema_version",
        "run_id",
        "nonce",
        "manifest_sha256",
        "output_path_sha256",
        "host_fingerprint",
        "not_before_unix",
        "expires_at_unix",
        "maximum_total_worker_seconds",
        "resume_policy",
        "maximum_resume_count",
    }
)
_CONSUMPTION_KEYS = frozenset(
    {
        "schema_version",
        "authorization_sha256",
        "run_id",
        "nonce",
        "manifest_sha256",
        "output_path_sha256",
        "host_fingerprint",
        "maximum_total_worker_seconds",
        "resume_policy",
        "maximum_resume_count",
        "status",
        "claim_count",
        "resume_count",
        "reserved_worker_seconds_total",
        "claims",
    }
)
_CLAIM_KEYS = frozenset(
    {
        "claim_index",
        "kind",
        "acquired_at_unix",
        "closed_at_unix",
        "requested_worker_seconds",
        "actual_worker_seconds",
        "resume_audit_sha256",
        "pid",
        "outcome",
    }
)
_RESUME_AUDIT_KEYS = frozenset(
    {
        "schema_version",
        "authorization_sha256",
        "run_id",
        "nonce",
        "manifest_sha256",
        "output_path_sha256",
        "host_fingerprint",
        "prior_consumption_sha256",
        "audited_artifact_relative_path",
        "audited_artifact_sha256",
        "audited_at_unix",
    }
)


class RunLeaseError(RuntimeError):
    """Base class for authorization and lease failures."""


class RunAuthorizationError(RunLeaseError):
    """The authorization is malformed, expired, or does not bind this run."""


class RunLeaseBusyError(RunLeaseError):
    """Another process currently holds the output-directory lease."""


class RunLeaseReuseError(RunLeaseError):
    """A consumed authorization cannot be used for the requested execution."""


class RunLeaseStateError(RunLeaseError):
    """Durable lease state is missing, divergent, or malformed."""


@dataclass(frozen=True)
class RunAuthorization:
    run_id: str
    nonce: str
    manifest_sha256: str
    output_path_sha256: str
    host_fingerprint: str
    not_before_unix: int
    expires_at_unix: int
    maximum_total_worker_seconds: int
    resume_policy: ResumePolicy
    maximum_resume_count: int
    authorization_sha256: str


def _duplicate_rejecting_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def _load_canonical_json_bytes(raw: bytes, *, label: str) -> dict[str, Any]:
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise RunAuthorizationError(f"{label} must be canonical ASCII JSON") from exc
    try:
        value = json.loads(
            text,
            object_pairs_hook=_duplicate_rejecting_object,
            parse_constant=_reject_nonfinite_json_constant,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise RunAuthorizationError(f"invalid {label}: {exc}") from exc
    if type(value) is not dict:
        raise RunAuthorizationError(f"{label} must be a JSON object")
    try:
        canonical = canonical_json_bytes(value)
    except (TypeError, ValueError) as exc:
        raise RunAuthorizationError(f"invalid value in {label}: {exc}") from exc
    if raw != canonical:
        raise RunAuthorizationError(f"{label} is not exact canonical JSON")
    return value


def _read_regular_file(path: Path, *, label: str) -> bytes:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise RunAuthorizationError(f"missing {label}: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RunAuthorizationError(f"{label} must be a non-symlink regular file: {path}")
    return path.read_bytes()


def _require_exact_keys(value: Mapping[str, Any], expected: frozenset[str], label: str) -> None:
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise RunAuthorizationError(
            f"{label} fields mismatch; missing={missing!r}, extra={extra!r}"
        )


def _require_exact_string(value: Any, label: str) -> str:
    if type(value) is not str or not value:
        raise RunAuthorizationError(f"{label} must be a nonempty JSON string")
    return value


def _require_sha256(value: Any, label: str) -> str:
    text = _require_exact_string(value, label)
    if _SHA256_RE.fullmatch(text) is None:
        raise RunAuthorizationError(f"{label} must be a lowercase SHA-256")
    return text


def _require_exact_int(
    value: Any,
    label: str,
    *,
    minimum: int = 0,
    maximum: int = _MAX_EXACT_INTEGER,
) -> int:
    if type(value) is not int:
        raise RunAuthorizationError(f"{label} must be an exact JSON integer")
    if value < minimum or value > maximum:
        raise RunAuthorizationError(f"{label} must be in [{minimum}, {maximum}]")
    return value


def _require_finite_runtime_number(value: Any, label: str) -> float:
    if type(value) not in {int, float}:
        raise RunAuthorizationError(f"{label} must be a finite number")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise RunAuthorizationError(f"{label} must be finite")
    return numeric


def _resolved_path(path: str | os.PathLike[str]) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def resolved_output_path_hash(path: str | os.PathLike[str]) -> str:
    """Hash the canonical absolute output path used by an authorization."""

    resolved = _resolved_path(path)
    return hash_json({"resolved_output_path": os.fspath(resolved)})


def local_host_fingerprint() -> str:
    """Return a stable hash of available host identity material.

    Linux machine and DMI identifiers are included when present.  The raw
    identifiers are never written to an authorization or consumption record.
    """

    identity: dict[str, str] = {
        "platform_system": platform.system(),
        "platform_machine": platform.machine(),
        "hostname": platform.node(),
    }
    for label, candidate in (
        ("machine_id", Path("/etc/machine-id")),
        ("dmi_product_uuid", Path("/sys/class/dmi/id/product_uuid")),
    ):
        try:
            text = candidate.read_text(encoding="ascii").strip()
        except (OSError, UnicodeError):
            continue
        if text:
            identity[label] = text
    return hash_json(identity)


def authorization_document(
    *,
    run_id: str,
    nonce: str,
    manifest_path: str | os.PathLike[str],
    output_path: str | os.PathLike[str],
    host_fingerprint: str,
    not_before_unix: int,
    expires_at_unix: int,
    maximum_total_worker_seconds: int,
    resume_policy: ResumePolicy,
    maximum_resume_count: int,
) -> dict[str, Any]:
    """Construct, but do not write, a canonicalizable authorization document."""

    document: dict[str, Any] = {
        "schema_version": AUTHORIZATION_SCHEMA_VERSION,
        "run_id": run_id,
        "nonce": nonce,
        "manifest_sha256": hash_file(manifest_path),
        "output_path_sha256": resolved_output_path_hash(output_path),
        "host_fingerprint": host_fingerprint,
        "not_before_unix": not_before_unix,
        "expires_at_unix": expires_at_unix,
        "maximum_total_worker_seconds": maximum_total_worker_seconds,
        "resume_policy": resume_policy,
        "maximum_resume_count": maximum_resume_count,
    }
    _parse_authorization(document, authorization_sha256=hash_json(document))
    return document


def _parse_authorization(
    value: Mapping[str, Any], *, authorization_sha256: str
) -> RunAuthorization:
    _require_exact_keys(value, _AUTHORIZATION_KEYS, "authorization")
    if value["schema_version"] != AUTHORIZATION_SCHEMA_VERSION:
        raise RunAuthorizationError("unsupported authorization schema_version")
    run_id = _require_exact_string(value["run_id"], "run_id")
    if _RUN_ID_RE.fullmatch(run_id) is None:
        raise RunAuthorizationError("run_id has an invalid format")
    nonce = _require_exact_string(value["nonce"], "nonce")
    if _NONCE_RE.fullmatch(nonce) is None:
        raise RunAuthorizationError("nonce must be 32-128 lowercase hexadecimal characters")
    manifest_sha256 = _require_sha256(value["manifest_sha256"], "manifest_sha256")
    output_path_sha256 = _require_sha256(
        value["output_path_sha256"], "output_path_sha256"
    )
    host_fingerprint = _require_sha256(value["host_fingerprint"], "host_fingerprint")
    not_before_unix = _require_exact_int(
        value["not_before_unix"], "not_before_unix", minimum=1
    )
    expires_at_unix = _require_exact_int(
        value["expires_at_unix"], "expires_at_unix", minimum=1
    )
    if expires_at_unix <= not_before_unix:
        raise RunAuthorizationError("expires_at_unix must be after not_before_unix")
    maximum_total_worker_seconds = _require_exact_int(
        value["maximum_total_worker_seconds"],
        "maximum_total_worker_seconds",
        minimum=1,
    )
    resume_policy = value["resume_policy"]
    if type(resume_policy) is not str or resume_policy not in {
        "forbid",
        "audited_same_output",
    }:
        raise RunAuthorizationError("resume_policy is invalid")
    maximum_resume_count = _require_exact_int(
        value["maximum_resume_count"], "maximum_resume_count", minimum=0
    )
    if resume_policy == "forbid" and maximum_resume_count != 0:
        raise RunAuthorizationError("forbid resume policy requires maximum_resume_count=0")
    if resume_policy == "audited_same_output" and maximum_resume_count < 1:
        raise RunAuthorizationError(
            "audited_same_output requires a positive maximum_resume_count"
        )
    return RunAuthorization(
        run_id=run_id,
        nonce=nonce,
        manifest_sha256=manifest_sha256,
        output_path_sha256=output_path_sha256,
        host_fingerprint=host_fingerprint,
        not_before_unix=not_before_unix,
        expires_at_unix=expires_at_unix,
        maximum_total_worker_seconds=maximum_total_worker_seconds,
        resume_policy=resume_policy,
        maximum_resume_count=maximum_resume_count,
        authorization_sha256=_require_sha256(
            authorization_sha256, "authorization_sha256"
        ),
    )


def load_run_authorization(path: str | os.PathLike[str]) -> RunAuthorization:
    authorization_path = _resolved_path(path)
    raw = _read_regular_file(authorization_path, label="authorization")
    value = _load_canonical_json_bytes(raw, label="authorization")
    return _parse_authorization(value, authorization_sha256=sha256_bytes(raw))


def validate_run_authorization(
    authorization_path: str | os.PathLike[str],
    *,
    manifest_path: str | os.PathLike[str],
    output_path: str | os.PathLike[str],
    requested_worker_seconds: int,
    actual_host_fingerprint: str | None = None,
    now_unix: int | float | None = None,
) -> RunAuthorization:
    """Validate all runtime bindings without consuming the authorization."""

    authorization = load_run_authorization(authorization_path)
    requested = _require_exact_int(
        requested_worker_seconds, "requested_worker_seconds", minimum=1
    )
    if requested > authorization.maximum_total_worker_seconds:
        raise RunAuthorizationError("requested worker seconds exceed authorization ceiling")
    current = _require_finite_runtime_number(
        time.time() if now_unix is None else now_unix, "now_unix"
    )
    if current < authorization.not_before_unix:
        raise RunAuthorizationError("authorization is not yet valid")
    if current >= authorization.expires_at_unix:
        raise RunAuthorizationError("authorization has expired")
    if hash_file(manifest_path) != authorization.manifest_sha256:
        raise RunAuthorizationError("manifest SHA-256 does not match authorization")
    if resolved_output_path_hash(output_path) != authorization.output_path_sha256:
        raise RunAuthorizationError("resolved output path does not match authorization")
    observed_host = (
        local_host_fingerprint()
        if actual_host_fingerprint is None
        else _require_sha256(actual_host_fingerprint, "actual_host_fingerprint")
    )
    if observed_host != authorization.host_fingerprint:
        raise RunAuthorizationError("host fingerprint does not match authorization")
    return authorization


def _authorization_record_path(authorization_path: Path) -> Path:
    return authorization_path.with_name(f".{authorization_path.name}.consumed.json")


def _output_record_path(output_path: Path) -> Path:
    return output_path / ".resource-envelope-run-identity.json"


def _output_lock_path(output_path: Path) -> Path:
    return output_path / ".resource-envelope-run.lock"


def _open_exclusive_lock(path: Path) -> int:
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise RunLeaseStateError(f"cannot open lease lock {path}: {exc}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise RunLeaseStateError("lease lock is not a regular file")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RunLeaseBusyError("another process holds the run lease") from exc
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _release_lock(descriptor: int) -> None:
    try:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write_new_or_replace(path: Path, payload: bytes, *, replace: bool) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{secrets.token_hex(8)}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if not replace and path.exists():
            raise FileExistsError(path)
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def _write_record_pair(
    authorization_record_path: Path,
    output_record_path: Path,
    record: Mapping[str, Any],
    *,
    replace: bool,
) -> None:
    payload = canonical_json_bytes(record)
    _atomic_write_new_or_replace(
        authorization_record_path, payload, replace=replace
    )
    _atomic_write_new_or_replace(output_record_path, payload, replace=replace)


def _load_record_pair(
    authorization_record_path: Path, output_record_path: Path
) -> tuple[dict[str, Any] | None, bytes | None]:
    auth_exists = authorization_record_path.exists()
    output_exists = output_record_path.exists()
    if auth_exists != output_exists:
        raise RunLeaseStateError("only one of the two durable consumption records exists")
    if not auth_exists:
        return None, None
    try:
        auth_raw = _read_regular_file(
            authorization_record_path, label="authorization consumption record"
        )
        output_raw = _read_regular_file(
            output_record_path, label="output consumption record"
        )
        if auth_raw != output_raw:
            raise RunLeaseStateError("durable consumption records diverge")
        record = _load_canonical_json_bytes(auth_raw, label="consumption record")
    except RunAuthorizationError as exc:
        raise RunLeaseStateError(str(exc)) from exc
    return record, auth_raw


def _validate_claim(claim: Any, *, expected_index: int) -> None:
    if type(claim) is not dict:
        raise RunLeaseStateError("each claim must be an object")
    try:
        _require_exact_keys(claim, _CLAIM_KEYS, "claim")
        index = _require_exact_int(claim["claim_index"], "claim_index", minimum=1)
        if index != expected_index:
            raise RunLeaseStateError("claim indexes are not contiguous")
        if claim["kind"] not in {"initial", "resume"}:
            raise RunLeaseStateError("invalid claim kind")
        _require_exact_int(claim["acquired_at_unix"], "acquired_at_unix", minimum=1)
        _require_exact_int(
            claim["requested_worker_seconds"],
            "requested_worker_seconds",
            minimum=1,
        )
        _require_exact_int(claim["pid"], "pid", minimum=1)
        for optional_integer in ("closed_at_unix", "actual_worker_seconds"):
            if claim[optional_integer] is not None:
                _require_exact_int(claim[optional_integer], optional_integer, minimum=0)
        if (
            claim["closed_at_unix"] is not None
            and claim["closed_at_unix"] < claim["acquired_at_unix"]
        ):
            raise RunLeaseStateError("claim closed before it was acquired")
        if (
            claim["actual_worker_seconds"] is not None
            and claim["actual_worker_seconds"] > claim["requested_worker_seconds"]
        ):
            raise RunLeaseStateError("claim actual work exceeds its reservation")
        audit = claim["resume_audit_sha256"]
        if audit is not None:
            _require_sha256(audit, "resume_audit_sha256")
        if claim["kind"] == "initial" and audit is not None:
            raise RunLeaseStateError("initial claim cannot have a resume audit")
        if claim["kind"] == "resume" and audit is None:
            raise RunLeaseStateError("resume claim must have a resume audit")
        if claim["outcome"] not in {None, "interrupted", "completed", "failed"}:
            raise RunLeaseStateError("invalid claim outcome")
        if (claim["outcome"] is None) != (claim["closed_at_unix"] is None):
            raise RunLeaseStateError("claim closure fields are inconsistent")
    except RunAuthorizationError as exc:
        raise RunLeaseStateError(str(exc)) from exc


def _validate_consumption_record(
    record: Mapping[str, Any], authorization: RunAuthorization
) -> None:
    try:
        _require_exact_keys(record, _CONSUMPTION_KEYS, "consumption record")
    except RunAuthorizationError as exc:
        raise RunLeaseStateError(str(exc)) from exc
    expected_identity = {
        "schema_version": CONSUMPTION_SCHEMA_VERSION,
        "authorization_sha256": authorization.authorization_sha256,
        "run_id": authorization.run_id,
        "nonce": authorization.nonce,
        "manifest_sha256": authorization.manifest_sha256,
        "output_path_sha256": authorization.output_path_sha256,
        "host_fingerprint": authorization.host_fingerprint,
        "maximum_total_worker_seconds": authorization.maximum_total_worker_seconds,
        "resume_policy": authorization.resume_policy,
        "maximum_resume_count": authorization.maximum_resume_count,
    }
    for key, expected in expected_identity.items():
        if record[key] != expected or type(record[key]) is not type(expected):
            raise RunLeaseStateError(f"consumption identity mismatch for {key}")
    try:
        claim_count = _require_exact_int(record["claim_count"], "claim_count", minimum=1)
        resume_count = _require_exact_int(record["resume_count"], "resume_count", minimum=0)
        reserved = _require_exact_int(
            record["reserved_worker_seconds_total"],
            "reserved_worker_seconds_total",
            minimum=1,
        )
    except RunAuthorizationError as exc:
        raise RunLeaseStateError(str(exc)) from exc
    if record["status"] not in {"active", "interrupted", "completed", "failed"}:
        raise RunLeaseStateError("invalid consumption status")
    claims = record["claims"]
    if type(claims) is not list or len(claims) != claim_count:
        raise RunLeaseStateError("claim_count does not match claims")
    for index, claim in enumerate(claims, start=1):
        _validate_claim(claim, expected_index=index)
    if claims[0]["kind"] != "initial":
        raise RunLeaseStateError("first claim must be initial")
    if any(claim["kind"] != "resume" for claim in claims[1:]):
        raise RunLeaseStateError("all later claims must be resumes")
    for previous, following in zip(claims, claims[1:]):
        if previous["outcome"] != "interrupted":
            raise RunLeaseStateError("only an interrupted claim may precede a resume")
        if following["acquired_at_unix"] < previous["closed_at_unix"]:
            raise RunLeaseStateError("claim acquisition timestamps are not monotone")
    if resume_count != claim_count - 1:
        raise RunLeaseStateError("resume_count does not match claims")
    if reserved != sum(claim["requested_worker_seconds"] for claim in claims):
        raise RunLeaseStateError("reserved worker-second total does not match claims")
    if reserved > authorization.maximum_total_worker_seconds:
        raise RunLeaseStateError("record exceeds authorized worker-second ceiling")
    last = claims[-1]
    if record["status"] == "active":
        if last["outcome"] is not None or last["closed_at_unix"] is not None:
            raise RunLeaseStateError("active claim is already closed")
    elif last["outcome"] != record["status"] or last["closed_at_unix"] is None:
        raise RunLeaseStateError("record status does not match final claim outcome")


def _new_claim(
    *,
    index: int,
    kind: Literal["initial", "resume"],
    acquired_at_unix: int,
    requested_worker_seconds: int,
    resume_audit_sha256: str | None,
) -> dict[str, Any]:
    return {
        "claim_index": index,
        "kind": kind,
        "acquired_at_unix": acquired_at_unix,
        "closed_at_unix": None,
        "requested_worker_seconds": requested_worker_seconds,
        "actual_worker_seconds": None,
        "resume_audit_sha256": resume_audit_sha256,
        "pid": os.getpid(),
        "outcome": None,
    }


def _initial_record(
    authorization: RunAuthorization,
    *,
    requested_worker_seconds: int,
    acquired_at_unix: int,
) -> dict[str, Any]:
    return {
        "schema_version": CONSUMPTION_SCHEMA_VERSION,
        "authorization_sha256": authorization.authorization_sha256,
        "run_id": authorization.run_id,
        "nonce": authorization.nonce,
        "manifest_sha256": authorization.manifest_sha256,
        "output_path_sha256": authorization.output_path_sha256,
        "host_fingerprint": authorization.host_fingerprint,
        "maximum_total_worker_seconds": authorization.maximum_total_worker_seconds,
        "resume_policy": authorization.resume_policy,
        "maximum_resume_count": authorization.maximum_resume_count,
        "status": "active",
        "claim_count": 1,
        "resume_count": 0,
        "reserved_worker_seconds_total": requested_worker_seconds,
        "claims": [
            _new_claim(
                index=1,
                kind="initial",
                acquired_at_unix=acquired_at_unix,
                requested_worker_seconds=requested_worker_seconds,
                resume_audit_sha256=None,
            )
        ],
    }


def _path_below_output(path: Path, output_path: Path, *, label: str) -> Path:
    resolved = path.expanduser().resolve(strict=False)
    try:
        relative = resolved.relative_to(output_path)
    except ValueError as exc:
        raise RunLeaseReuseError(f"{label} must be below the authorized output directory") from exc
    if not relative.parts:
        raise RunLeaseReuseError(f"{label} must name a file below the output directory")
    return relative


def _load_and_validate_resume_audit(
    path: Path,
    *,
    output_path: Path,
    authorization: RunAuthorization,
    prior_record: Mapping[str, Any],
    prior_record_raw: bytes,
    now_unix: float,
) -> str:
    _path_below_output(path, output_path, label="resume audit")
    raw = _read_regular_file(path.resolve(strict=False), label="resume audit")
    try:
        audit = _load_canonical_json_bytes(raw, label="resume audit")
        _require_exact_keys(audit, _RESUME_AUDIT_KEYS, "resume audit")
        expected = {
            "schema_version": RESUME_AUDIT_SCHEMA_VERSION,
            "authorization_sha256": authorization.authorization_sha256,
            "run_id": authorization.run_id,
            "nonce": authorization.nonce,
            "manifest_sha256": authorization.manifest_sha256,
            "output_path_sha256": authorization.output_path_sha256,
            "host_fingerprint": authorization.host_fingerprint,
            "prior_consumption_sha256": sha256_bytes(prior_record_raw),
        }
        for key, expected_value in expected.items():
            if audit[key] != expected_value or type(audit[key]) is not type(expected_value):
                raise RunLeaseReuseError(f"resume audit identity mismatch for {key}")
        audited_at = _require_exact_int(
            audit["audited_at_unix"], "audited_at_unix", minimum=1
        )
        if audited_at > now_unix:
            raise RunLeaseReuseError("resume audit timestamp is in the future")
        prior_closed_at = prior_record["claims"][-1]["closed_at_unix"]
        if prior_closed_at is not None and audited_at < prior_closed_at:
            raise RunLeaseReuseError("resume audit predates the interrupted claim")
        relative_text = _require_exact_string(
            audit["audited_artifact_relative_path"],
            "audited_artifact_relative_path",
        )
        if Path(relative_text).is_absolute() or Path(relative_text).as_posix() != relative_text:
            raise RunLeaseReuseError("audited artifact path must be canonical and relative")
        artifact_path = (output_path / relative_text).resolve(strict=False)
        actual_relative = _path_below_output(
            artifact_path, output_path, label="audited artifact"
        )
        if actual_relative.as_posix() != relative_text:
            raise RunLeaseReuseError("audited artifact path is not canonical")
        artifact_raw = _read_regular_file(artifact_path, label="audited artifact")
        expected_artifact_hash = _require_sha256(
            audit["audited_artifact_sha256"], "audited_artifact_sha256"
        )
        if sha256_bytes(artifact_raw) != expected_artifact_hash:
            raise RunLeaseReuseError("audited checkpoint artifact changed after audit")
    except RunAuthorizationError as exc:
        raise RunLeaseReuseError(str(exc)) from exc
    return sha256_bytes(raw)


class RunLease:
    """An acquired lease whose file lock is held until :meth:`close`."""

    def __init__(
        self,
        *,
        lock_descriptor: int,
        authorization: RunAuthorization,
        authorization_record_path: Path,
        output_record_path: Path,
        record: dict[str, Any],
    ) -> None:
        self.authorization = authorization
        self.authorization_record_path = authorization_record_path
        self.output_record_path = output_record_path
        self._lock_descriptor: int | None = lock_descriptor
        self._record = record

    @property
    def is_closed(self) -> bool:
        return self._lock_descriptor is None

    @property
    def record(self) -> dict[str, Any]:
        """Return a JSON round-tripped snapshot, not mutable internal state."""

        return json.loads(canonical_json_bytes(self._record))

    def close(
        self,
        outcome: TerminalStatus = "interrupted",
        *,
        actual_worker_seconds: int | None = None,
        now_unix: int | float | None = None,
    ) -> None:
        if self._lock_descriptor is None:
            return
        if outcome not in {"interrupted", "completed", "failed"}:
            raise ValueError("invalid lease outcome")
        current = _require_finite_runtime_number(
            time.time() if now_unix is None else now_unix, "now_unix"
        )
        closed_at = int(current)
        if closed_at < 1:
            raise ValueError("now_unix must be positive")
        final_claim = self._record["claims"][-1]
        if actual_worker_seconds is not None:
            actual = _require_exact_int(
                actual_worker_seconds, "actual_worker_seconds", minimum=0
            )
            if actual > final_claim["requested_worker_seconds"]:
                raise RunLeaseStateError(
                    "actual worker seconds exceed this claim's reservation"
                )
        else:
            actual = None
        final_claim["closed_at_unix"] = closed_at
        final_claim["actual_worker_seconds"] = actual
        final_claim["outcome"] = outcome
        self._record["status"] = outcome
        descriptor = self._lock_descriptor
        try:
            _write_record_pair(
                self.authorization_record_path,
                self.output_record_path,
                self._record,
                replace=True,
            )
        finally:
            self._lock_descriptor = None
            _release_lock(descriptor)

    def mark_completed(
        self,
        *,
        actual_worker_seconds: int | None = None,
        now_unix: int | float | None = None,
    ) -> None:
        self.close(
            "completed",
            actual_worker_seconds=actual_worker_seconds,
            now_unix=now_unix,
        )

    def mark_failed(
        self,
        *,
        actual_worker_seconds: int | None = None,
        now_unix: int | float | None = None,
    ) -> None:
        self.close(
            "failed",
            actual_worker_seconds=actual_worker_seconds,
            now_unix=now_unix,
        )

    def __enter__(self) -> "RunLease":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        del exc_type, exc, traceback
        if not self.is_closed:
            self.close("interrupted")
        return False


def acquire_run_lease(
    authorization_path: str | os.PathLike[str],
    *,
    manifest_path: str | os.PathLike[str],
    output_path: str | os.PathLike[str],
    requested_worker_seconds: int,
    actual_host_fingerprint: str | None = None,
    now_unix: int | float | None = None,
    resume_audit_path: str | os.PathLike[str] | None = None,
) -> RunLease:
    """Validate, consume, and exclusively lock one bounded run authorization."""

    current = _require_finite_runtime_number(
        time.time() if now_unix is None else now_unix, "now_unix"
    )
    authorization = validate_run_authorization(
        authorization_path,
        manifest_path=manifest_path,
        output_path=output_path,
        requested_worker_seconds=requested_worker_seconds,
        actual_host_fingerprint=actual_host_fingerprint,
        now_unix=current,
    )
    requested = _require_exact_int(
        requested_worker_seconds, "requested_worker_seconds", minimum=1
    )
    resolved_authorization_path = _resolved_path(authorization_path)
    resolved_output_path = _resolved_path(output_path)
    resolved_output_path.mkdir(parents=True, exist_ok=True)
    if not resolved_output_path.is_dir():
        raise RunLeaseStateError("authorized output path is not a directory")
    lock_descriptor = _open_exclusive_lock(_output_lock_path(resolved_output_path))
    authorization_record_path = _authorization_record_path(resolved_authorization_path)
    output_record_path = _output_record_path(resolved_output_path)
    try:
        record, record_raw = _load_record_pair(
            authorization_record_path, output_record_path
        )
        acquired_at = int(current)
        if record is None:
            if resume_audit_path is not None:
                raise RunLeaseReuseError("unused authorization cannot begin as a resume")
            unexpected_entries = sorted(
                entry.name
                for entry in resolved_output_path.iterdir()
                if entry.name != _output_lock_path(resolved_output_path).name
            )
            if unexpected_entries:
                raise RunLeaseStateError(
                    "unused authorization requires a pristine output directory; "
                    f"found={unexpected_entries!r}"
                )
            record = _initial_record(
                authorization,
                requested_worker_seconds=requested,
                acquired_at_unix=acquired_at,
            )
            _write_record_pair(
                authorization_record_path, output_record_path, record, replace=False
            )
        else:
            assert record_raw is not None
            _validate_consumption_record(record, authorization)
            if authorization.resume_policy != "audited_same_output":
                raise RunLeaseReuseError("authorization forbids reuse")
            if record["status"] in {"completed", "failed"}:
                raise RunLeaseReuseError(
                    f"cannot resume a {record['status']} authorization"
                )
            if record["resume_count"] >= authorization.maximum_resume_count:
                raise RunLeaseReuseError("maximum authorized resume count reached")
            if (
                record["reserved_worker_seconds_total"] + requested
                > authorization.maximum_total_worker_seconds
            ):
                raise RunLeaseReuseError("resume exceeds cumulative worker-second ceiling")
            if resume_audit_path is None:
                raise RunLeaseReuseError("resume requires a bound checkpoint audit")
            audit_hash = _load_and_validate_resume_audit(
                _resolved_path(resume_audit_path),
                output_path=resolved_output_path,
                authorization=authorization,
                prior_record=record,
                prior_record_raw=record_raw,
                now_unix=current,
            )
            record["claims"].append(
                _new_claim(
                    index=record["claim_count"] + 1,
                    kind="resume",
                    acquired_at_unix=acquired_at,
                    requested_worker_seconds=requested,
                    resume_audit_sha256=audit_hash,
                )
            )
            record["claim_count"] += 1
            record["resume_count"] += 1
            record["reserved_worker_seconds_total"] += requested
            record["status"] = "active"
            _write_record_pair(
                authorization_record_path, output_record_path, record, replace=True
            )
        return RunLease(
            lock_descriptor=lock_descriptor,
            authorization=authorization,
            authorization_record_path=authorization_record_path,
            output_record_path=output_record_path,
            record=record,
        )
    except BaseException:
        _release_lock(lock_descriptor)
        raise


def write_resume_audit(
    authorization_path: str | os.PathLike[str],
    *,
    output_path: str | os.PathLike[str],
    audited_artifact_path: str | os.PathLike[str],
    audit_path: str | os.PathLike[str],
    now_unix: int | float | None = None,
) -> str:
    """Write a one-use audit bound to the current record and checkpoint bytes.

    The output-directory lock must be free.  Both the audited artifact and the
    audit itself must be regular files below the authorized output directory.
    The audit ceases to be valid as soon as the consumption record or checkpoint
    changes.
    """

    current = _require_finite_runtime_number(
        time.time() if now_unix is None else now_unix, "now_unix"
    )
    authorization = load_run_authorization(authorization_path)
    resolved_output_path = _resolved_path(output_path)
    if resolved_output_path_hash(resolved_output_path) != authorization.output_path_sha256:
        raise RunLeaseReuseError("output path does not match authorization")
    resolved_artifact = _resolved_path(audited_artifact_path)
    artifact_relative = _path_below_output(
        resolved_artifact, resolved_output_path, label="audited artifact"
    )
    resolved_audit_path = _resolved_path(audit_path)
    _path_below_output(resolved_audit_path, resolved_output_path, label="resume audit")
    lock_descriptor = _open_exclusive_lock(_output_lock_path(resolved_output_path))
    try:
        authorization_record_path = _authorization_record_path(
            _resolved_path(authorization_path)
        )
        output_record_path = _output_record_path(resolved_output_path)
        record, record_raw = _load_record_pair(
            authorization_record_path, output_record_path
        )
        if record is None or record_raw is None:
            raise RunLeaseReuseError("cannot audit an unused authorization")
        _validate_consumption_record(record, authorization)
        if authorization.resume_policy != "audited_same_output":
            raise RunLeaseReuseError("authorization forbids resumes")
        if record["status"] not in {"active", "interrupted"}:
            raise RunLeaseReuseError("only an interrupted execution can be audited")
        artifact_raw = _read_regular_file(resolved_artifact, label="audited artifact")
        audit = {
            "schema_version": RESUME_AUDIT_SCHEMA_VERSION,
            "authorization_sha256": authorization.authorization_sha256,
            "run_id": authorization.run_id,
            "nonce": authorization.nonce,
            "manifest_sha256": authorization.manifest_sha256,
            "output_path_sha256": authorization.output_path_sha256,
            "host_fingerprint": authorization.host_fingerprint,
            "prior_consumption_sha256": sha256_bytes(record_raw),
            "audited_artifact_relative_path": artifact_relative.as_posix(),
            "audited_artifact_sha256": sha256_bytes(artifact_raw),
            "audited_at_unix": int(current),
        }
        payload = canonical_json_bytes(audit)
        _atomic_write_new_or_replace(resolved_audit_path, payload, replace=False)
        return sha256_bytes(payload)
    except FileExistsError as exc:
        raise RunLeaseReuseError("resume audit path already exists") from exc
    finally:
        _release_lock(lock_descriptor)
