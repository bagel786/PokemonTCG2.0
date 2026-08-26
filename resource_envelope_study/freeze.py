"""Fail-closed validation for the protocol freeze and artifact inventory.

The freeze manifest deliberately separates existing inputs, which can be
bound by content hash, from outputs that do not exist until acquisition or
analysis, which are bound by path, schema, producer, phase, and cardinality.
The manifest itself is forbidden from the hashed input inventory so that the
protocol does not depend on an impossible self-referential digest.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

from .canonical import hash_file


FREEZE_SCHEMA_VERSION = "freeze-manifest-1.0.0"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
AUTHORIZED_FINAL_PHASE = "final"
EXPECTED_OUTPUT_ROOT = PurePosixPath("resource_envelope_study/runs")
REQUIRED_ARTIFACT_KEYS = frozenset(
    {
        "engine_binary",
        "engine_source",
        "hero_deck",
        "hero_model",
        "opponent_deck",
        "opponent_model",
        "run_config",
    }
)

# Each public digest field is bound to exactly one semantic inventory item.
# The role is deliberately machine checked: a digest for (say) analysis.py may
# not satisfy the final-manifest field merely because its bytes happen to be
# identical.
TOP_LEVEL_BINDINGS: dict[str, tuple[str, str]] = {
    "pilot_manifest_sha256": ("manifest.pilot", "pilot_manifest"),
    "final_manifest_sha256": ("manifest.final", "final_manifest"),
    "reserve_manifest_sha256": ("manifest.reserve", "reserve_manifest"),
    "environment_lock_sha256": ("environment.lock", "environment_lock"),
    "engine_binary_sha256": (
        "artifact.engine_binary",
        "scientific_artifact:engine_binary",
    ),
    "analysis_sha256": ("source.analysis", "analysis_code"),
    "reaggregation_sha256": ("source.reaggregation", "reaggregation_code"),
    "plotting_sha256": ("source.plotting", "plotting_code"),
    "state_panel_manifest_sha256": (
        "manifest.state_panel",
        "state_panel_manifest",
    ),
    "ising_manifest_sha256": ("manifest.ising", "ising_manifest"),
}


def _artifact_binding(key: str) -> tuple[str, str]:
    return f"artifact.{key}", f"scientific_artifact:{key}"


ARTIFACT_BINDINGS: dict[str, tuple[str, str]] = {
    key: _artifact_binding(key) for key in REQUIRED_ARTIFACT_KEYS
}


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _repository_relative_path(value: Any, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a nonempty repository-relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ValueError(f"{label} is not a normalized repository-relative path")
    if value == "." or not path.parts:
        raise ValueError(f"{label} may not name the repository root")
    return path


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")
    return value


def _validate_frozen_inputs(
    values: Any,
    *,
    repository_root: Path | None,
    verify_files: bool,
    freeze_relative_path: PurePosixPath | None,
) -> tuple[dict[str, Any], ...]:
    if not isinstance(values, list) or not values:
        raise ValueError("FROZEN manifest requires a nonempty frozen_inputs array")
    seen_paths: set[PurePosixPath] = set()
    seen_logical_ids: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, value in enumerate(values):
        label = f"frozen_inputs[{index}]"
        required = {"logical_id", "path", "sha256", "role"}
        if not isinstance(value, Mapping) or set(value) != required:
            raise ValueError(f"{label} must contain exactly {sorted(required)}")
        logical_id = _require_string(value["logical_id"], f"{label}.logical_id")
        if re.fullmatch(r"[a-z][a-z0-9_.-]*", logical_id) is None:
            raise ValueError(f"{label}.logical_id is not normalized")
        if logical_id in seen_logical_ids:
            raise ValueError(f"duplicate frozen input logical_id: {logical_id}")
        path = _repository_relative_path(value["path"], f"{label}.path")
        if path in seen_paths:
            raise ValueError(f"duplicate frozen input path: {path}")
        if freeze_relative_path is not None and path == freeze_relative_path:
            raise ValueError("FREEZE_MANIFEST.json may not hash itself")
        seen_paths.add(path)
        seen_logical_ids.add(logical_id)
        digest = _require_sha256(value["sha256"], f"{label}.sha256")
        role = _require_string(value["role"], f"{label}.role")
        if verify_files:
            if repository_root is None:
                raise ValueError("repository_root is required when verify_files is true")
            full_path = (repository_root / Path(path.as_posix())).resolve()
            try:
                full_path.relative_to(repository_root)
            except ValueError as exc:
                raise RuntimeError(f"frozen input resolves outside repository: {path}") from exc
            if not full_path.is_file():
                raise RuntimeError(f"frozen input is missing: {path}")
            observed = hash_file(full_path)
            if observed != digest:
                raise RuntimeError(
                    f"frozen input hash mismatch for {path}: expected {digest}, observed {observed}"
                )
        normalized.append(
            {
                "logical_id": logical_id,
                "path": path.as_posix(),
                "sha256": digest,
                "role": role,
            }
        )
    return tuple(normalized)


def _validate_expected_outputs(
    values: Any, *, frozen_input_paths: set[str]
) -> tuple[dict[str, Any], ...]:
    if not isinstance(values, list) or not values:
        raise ValueError("FROZEN manifest requires a nonempty expected_outputs array")
    required = {
        "logical_id",
        "path",
        "schema_version",
        "producer",
        "phase",
        "cardinality",
    }
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, value in enumerate(values):
        label = f"expected_outputs[{index}]"
        if not isinstance(value, Mapping) or set(value) != required:
            raise ValueError(f"{label} must contain exactly {sorted(required)}")
        logical_id = _require_string(value["logical_id"], f"{label}.logical_id")
        path = _repository_relative_path(value["path"], f"{label}.path").as_posix()
        output_path = PurePosixPath(path)
        if output_path == EXPECTED_OUTPUT_ROOT or EXPECTED_OUTPUT_ROOT not in output_path.parents:
            raise ValueError(
                f"{label}.path must be a file below {EXPECTED_OUTPUT_ROOT.as_posix()}/"
            )
        schema_version = _require_string(
            value["schema_version"], f"{label}.schema_version"
        )
        producer = _require_string(value["producer"], f"{label}.producer")
        phase = _require_string(value["phase"], f"{label}.phase")
        cardinality = value["cardinality"]
        if isinstance(cardinality, bool) or not isinstance(cardinality, int) or cardinality < 1:
            raise ValueError(f"{label}.cardinality must be a positive integer")
        if logical_id in seen_ids:
            raise ValueError(f"duplicate expected-output logical_id: {logical_id}")
        if path in seen_paths:
            raise ValueError(f"duplicate expected-output path: {path}")
        if path in frozen_input_paths:
            raise ValueError(f"expected output collides with frozen input: {path}")
        seen_ids.add(logical_id)
        seen_paths.add(path)
        normalized.append(
            {
                "logical_id": logical_id,
                "path": path,
                "schema_version": schema_version,
                "producer": producer,
                "phase": phase,
                "cardinality": cardinality,
            }
        )
    return tuple(normalized)


def validate_freeze_manifest(
    manifest: Mapping[str, Any],
    *,
    repository_root: str | Path | None = None,
    freeze_manifest_path: str | Path | None = None,
    verify_files: bool = False,
    require_final_authorized: bool = False,
) -> dict[str, Any]:
    """Validate a placeholder or frozen manifest and optionally its files.

    ``NOT_FROZEN`` is accepted only as an inert placeholder.  Any request for
    file verification or final authorization requires ``FROZEN`` and applies
    the complete inventory and approval checks.
    """

    if not isinstance(manifest, Mapping):
        raise ValueError("freeze manifest must be an object")
    if manifest.get("schema_version") != FREEZE_SCHEMA_VERSION:
        raise ValueError("unsupported freeze-manifest schema version")
    status = manifest.get("status")
    if status not in {"NOT_FROZEN", "FROZEN"}:
        raise ValueError("freeze status must be NOT_FROZEN or FROZEN")
    if status == "NOT_FROZEN":
        if manifest.get("final_acquisition_authorized") is not False:
            raise ValueError("NOT_FROZEN manifest must keep final authorization false")
        if verify_files or require_final_authorized:
            raise RuntimeError("final acquisition forbidden: freeze status is not FROZEN")
        return dict(manifest)

    base_commit = manifest.get("base_commit")
    protocol_commit = manifest.get("protocol_commit")
    if not isinstance(base_commit, str) or COMMIT_RE.fullmatch(base_commit) is None:
        raise ValueError("FROZEN manifest lacks an exact base commit")
    if not isinstance(protocol_commit, str) or COMMIT_RE.fullmatch(protocol_commit) is None:
        raise ValueError("FROZEN manifest lacks an exact protocol commit")
    _require_string(manifest.get("branch"), "branch")

    root = Path(repository_root).resolve() if repository_root is not None else None
    freeze_relative: PurePosixPath | None = None
    if freeze_manifest_path is not None:
        if root is None:
            raise ValueError("repository_root is required with freeze_manifest_path")
        freeze_file = Path(freeze_manifest_path).resolve()
        try:
            freeze_relative = PurePosixPath(freeze_file.relative_to(root).as_posix())
        except ValueError as exc:
            raise ValueError("freeze manifest must be inside the repository") from exc

    inventory = manifest.get("inventory")
    if not isinstance(inventory, Mapping) or set(inventory) != {
        "frozen_inputs",
        "expected_outputs",
    }:
        raise ValueError("FROZEN manifest requires exact frozen/expected inventory sections")
    frozen_inputs = _validate_frozen_inputs(
        inventory["frozen_inputs"],
        repository_root=root,
        verify_files=verify_files,
        freeze_relative_path=freeze_relative,
    )
    expected_outputs = _validate_expected_outputs(
        inventory["expected_outputs"],
        frozen_input_paths={entry["path"] for entry in frozen_inputs},
    )

    required_hashes = set(TOP_LEVEL_BINDINGS)
    for name in sorted(required_hashes):
        _require_sha256(manifest.get(name), name)
    artifact_hashes = manifest.get("artifact_hashes")
    if not isinstance(artifact_hashes, Mapping) or set(artifact_hashes) != REQUIRED_ARTIFACT_KEYS:
        raise ValueError(
            "FROZEN manifest artifact_hashes must contain exactly "
            f"{sorted(REQUIRED_ARTIFACT_KEYS)}"
        )
    for key, value in artifact_hashes.items():
        _require_string(key, "artifact_hashes key")
        _require_sha256(value, f"artifact_hashes[{key!r}]")
    by_logical_id = {entry["logical_id"]: entry for entry in frozen_inputs}

    def require_binding(
        field_name: str, digest: str, logical_id: str, expected_role: str
    ) -> None:
        entry = by_logical_id.get(logical_id)
        if entry is None:
            raise ValueError(
                f"{field_name} lacks frozen input logical_id {logical_id!r}"
            )
        if entry["role"] != expected_role:
            raise ValueError(
                f"{field_name} requires role {expected_role!r}, observed {entry['role']!r}"
            )
        if entry["sha256"] != digest:
            raise ValueError(
                f"{field_name} digest differs from its bound inventory path {entry['path']}"
            )

    for field_name, (logical_id, role) in TOP_LEVEL_BINDINGS.items():
        require_binding(field_name, manifest[field_name], logical_id, role)
    for key in sorted(REQUIRED_ARTIFACT_KEYS):
        logical_id, role = ARTIFACT_BINDINGS[key]
        require_binding(
            f"artifact_hashes.{key}", artifact_hashes[key], logical_id, role
        )

    if not isinstance(manifest.get("unresolved"), list) or manifest["unresolved"]:
        raise ValueError("FROZEN manifest may not retain unresolved items")
    approval = manifest.get("human_approval")
    authorized = manifest.get("final_acquisition_authorized")
    if not isinstance(authorized, bool):
        raise ValueError("final_acquisition_authorized must be boolean")
    if authorized:
        approval_fields = {
            "approved",
            "phase",
            "protocol_commit",
            "approval_commit",
            "approval_id",
            "attestation_path",
            "attestation_sha256",
        }
        if not isinstance(approval, Mapping) or set(approval) != approval_fields:
            raise ValueError(
                "authorized final acquisition requires exact structured human approval"
            )
        if approval.get("approved") is not True:
            raise ValueError("authorized final acquisition requires structured human approval")
        if approval.get("protocol_commit") != protocol_commit:
            raise ValueError("human approval does not name the protocol commit")
        if approval.get("phase") != AUTHORIZED_FINAL_PHASE:
            raise ValueError("human approval must explicitly authorize the final phase")
        _require_string(approval.get("approval_id"), "human_approval.approval_id")
        approval_commit = approval.get("approval_commit")
        if not isinstance(approval_commit, str) or COMMIT_RE.fullmatch(approval_commit) is None:
            raise ValueError("human_approval.approval_commit must be a full commit hash")
        if approval_commit == protocol_commit:
            raise ValueError("human approval must occur after the protocol freeze commit")
        attestation_path = _repository_relative_path(
            approval.get("attestation_path"), "human_approval.attestation_path"
        )
        authorization_root = PurePosixPath("resource_envelope_study/authorizations")
        if authorization_root not in attestation_path.parents:
            raise ValueError(
                "human approval attestation must be below resource_envelope_study/authorizations/"
            )
        _require_sha256(
            approval.get("attestation_sha256"), "human_approval.attestation_sha256"
        )
    elif approval is not None:
        raise ValueError("pre-approval human_approval must be null")
    if require_final_authorized and not authorized:
        raise RuntimeError("final acquisition forbidden: authorization flag is not true")

    validated = dict(manifest)
    validated["inventory"] = {
        "frozen_inputs": [dict(value) for value in frozen_inputs],
        "expected_outputs": [dict(value) for value in expected_outputs],
    }
    return validated


def load_and_validate_freeze_manifest(
    path: str | Path,
    *,
    repository_root: str | Path | None = None,
    verify_files: bool = False,
    require_final_authorized: bool = False,
) -> dict[str, Any]:
    freeze_path = Path(path).resolve()
    try:
        value = json.loads(freeze_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read freeze manifest: {freeze_path}") from exc
    return validate_freeze_manifest(
        value,
        repository_root=repository_root,
        freeze_manifest_path=freeze_path,
        verify_files=verify_files,
        require_final_authorized=require_final_authorized,
    )
