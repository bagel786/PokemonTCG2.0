"""Fail-closed frozen-state capture, calibration, and repeatability execution.

This module is intentionally separate from full-game acquisition.  It accepts
only calibration and repeatability manifests, is execution-disabled by
default, and treats captured artifacts as opaque byte strings.  A captured
state is never parsed and serialized again by the orchestrator: every child
reads the exact frozen file and independently verifies its SHA-256.
"""

from __future__ import annotations

import importlib
import json
import multiprocessing as mp
import os
import platform
import queue
import re
import tempfile
import time
import traceback
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .calibration import (
    collect_persisted_seeds,
    validate_calibration_manifest,
)
from .capture import load_frozen_captured_state
from .capture import (
    FROZEN_CAPTURE_SCHEMA_VERSION,
    CapturedDecisionState,
    capture_anchor_state,
)
from .canonical import (
    canonical_json_bytes,
    derive_u32,
    hash_file,
    hash_json,
    sha256_bytes,
)
from .orchestration_guard import arm_parent_death_kill
from .process_safety import stop_process
from .repeatability import validate_repeatability_manifest
from .resource_controller import LoadProfile, ResourceEnvelope, system_snapshot
from .runner import CaseContext, run_decision
from .stop_policy import FixedWorkStop, WallClockStop


DEFAULT_SELECTION_BANKS = (
    "deadline_calibration",
    "fixed_work_calibration",
    "repeatability_pilot",
    "repeatability_final",
    "repeatability_reserve",
)
SCIENTIFIC_CAPTURE_ENTRYPOINT = (
    "resource_envelope_study.state_panel:native_capture_entrypoint"
)
SCIENTIFIC_PANEL_ENTRYPOINT = (
    "resource_envelope_study.state_panel:pokemon_panel_entrypoint"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PANEL_OUTPUT_FIELDS = frozenset(
    {
        "terminal_status",
        "eligible",
        "completed_work_units",
        "completed_simulations",
        "completed_nodes",
        "forward_model_calls",
        "search_wall_ns",
        "overshoot_ns",
        "state_hash",
        "selected_action_hash",
        "cleanup_succeeded",
        "warmup_steps_completed",
        "warmup_consumed_sha256",
        "warmup_replay_sha256",
    }
)


class StatePanelError(RuntimeError):
    """The frozen-state execution contract was violated."""


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise StatePanelError(f"{label} must be a lowercase SHA-256 digest")
    return value


@dataclass(frozen=True)
class CaptureRequest:
    capture_id: str
    state_id: str
    source_game_id: str
    state_seed: int
    history_seed: int
    history_length: int
    capture_kwargs: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.capture_id or not self.state_id or not self.source_game_id:
            raise ValueError("capture, state, and source-game IDs must be nonempty")
        for name, value in (("state_seed", self.state_seed), ("history_seed", self.history_seed)):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 2**32:
                raise ValueError(f"{name} must be an unsigned 32-bit integer")
        if (
            isinstance(self.history_length, bool)
            or not isinstance(self.history_length, int)
            or self.history_length < 0
        ):
            raise ValueError("history_length must be a non-negative integer")
        if "target_eligible_index" in self.capture_kwargs:
            target = self.capture_kwargs["target_eligible_index"]
            if (
                isinstance(target, bool)
                or not isinstance(target, int)
                or target < 0
                or target != self.history_length
            ):
                raise ValueError(
                    "capture history length must equal the predeclared eligible ordinal"
                )
        hash_json(self.capture_kwargs)


@dataclass(frozen=True)
class PanelRuntime:
    """Frozen executor controls; execution requires an explicit enable flag."""

    entrypoint: str
    entrypoint_payload: dict[str, Any]
    target_cpus: tuple[int, ...]
    load_workers: int
    worker_timeout_s: float = 3_600.0
    execution_enabled: bool = False
    test_mode: bool = False
    require_linux_affinity: bool = True
    thread_env: dict[str, str] = field(default_factory=dict)
    platform_expectations: dict[str, str] = field(default_factory=dict)
    authorized_state_bank: str | None = None
    run_config_file: str | None = None
    run_config_sha256: str | None = None
    selection_bank_files: dict[str, str] = field(default_factory=dict)
    selection_bank_sha256: dict[str, str] = field(default_factory=dict)
    required_selection_banks: tuple[str, ...] = DEFAULT_SELECTION_BANKS

    def validate(self) -> None:
        _resolve_entrypoint(self.entrypoint)
        hash_json(self.entrypoint_payload)
        if (
            not self.target_cpus
            or any(
                isinstance(cpu, bool) or not isinstance(cpu, int) or cpu < 0
                for cpu in self.target_cpus
            )
            or len(set(self.target_cpus)) != len(self.target_cpus)
        ):
            raise ValueError("target_cpus must be unique non-negative integers")
        if (
            isinstance(self.load_workers, bool)
            or not isinstance(self.load_workers, int)
            or self.load_workers <= 0
        ):
            raise ValueError("load_workers must be positive")
        if (
            isinstance(self.worker_timeout_s, bool)
            or not isinstance(self.worker_timeout_s, (int, float))
            or self.worker_timeout_s <= 0
        ):
            raise ValueError("worker_timeout_s must be positive")
        if not self.require_linux_affinity and not self.test_mode:
            raise ValueError("only explicit test mode may disable Linux affinity")
        if any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in self.thread_env.items()
        ):
            raise ValueError("state-panel thread environment must contain strings")
        if self.entrypoint.endswith(":synthetic_panel_entrypoint") and not self.test_mode:
            raise ValueError("synthetic panel entrypoint is test-only")
        if not self.test_mode and self.entrypoint != SCIENTIFIC_PANEL_ENTRYPOINT:
            raise ValueError(
                "scientific state-panel execution requires the study-owned Pokémon entrypoint"
            )
        required = set(self.required_selection_banks)
        if len(required) != len(self.required_selection_banks) or not required:
            raise ValueError("required selection-bank names must be unique and nonempty")
        if not self.test_mode and tuple(self.required_selection_banks) != DEFAULT_SELECTION_BANKS:
            raise ValueError("scientific execution requires the complete frozen bank ledger")
        if set(self.selection_bank_files) != required:
            raise ValueError("selection-bank file mapping differs from the required ledger")
        if set(self.selection_bank_sha256) != required:
            raise ValueError("selection-bank hash mapping differs from the required ledger")
        for bank_name, digest in self.selection_bank_sha256.items():
            _require_sha256(digest, f"selection-bank hash for {bank_name}")
        if not self.test_mode:
            _validate_pokemon_panel_payload(self.entrypoint_payload)
            required_thread_env = {
                "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS",
                "PYTHONHASHSEED",
            }
            if set(self.thread_env) != required_thread_env:
                raise ValueError("scientific state panel requires exact thread/env controls")
            for key in required_thread_env - {"PYTHONHASHSEED"}:
                if self.thread_env[key] != "1":
                    raise ValueError(f"scientific state-panel {key} must equal 1")
            if not self.thread_env["PYTHONHASHSEED"].isdigit():
                raise ValueError("scientific state-panel PYTHONHASHSEED must be decimal")
            if set(self.platform_expectations) != {"system", "machine"}:
                raise ValueError("scientific state panel requires exact platform expectations")
            if self.authorized_state_bank is not None and self.authorized_state_bank not in (
                DEFAULT_SELECTION_BANKS
            ):
                raise ValueError("authorized state bank is not in the frozen ledger")
            if self.run_config_file is None or self.run_config_sha256 is None:
                raise ValueError("scientific state-panel execution requires a frozen run config")
            _require_sha256(self.run_config_sha256, "state-panel run-config hash")
            config, _ = _load_canonical_json(
                self.run_config_file,
                expected_file_sha256=self.run_config_sha256,
            )
            _verify_content_hash(config, "state-panel run config")
            expected_config = {
                "schema_version": "state-panel-run-config-1.0.0",
                "entrypoint": self.entrypoint,
                "entrypoint_payload": self.entrypoint_payload,
                "target_cpus": list(self.target_cpus),
                "load_workers": self.load_workers,
                "worker_timeout_s": self.worker_timeout_s,
                "require_linux_affinity": self.require_linux_affinity,
                "thread_env": self.thread_env,
                "platform_expectations": self.platform_expectations,
                "authorized_state_bank": self.authorized_state_bank,
                "selection_bank_files": self.selection_bank_files,
                "selection_bank_sha256": self.selection_bank_sha256,
                "required_selection_banks": list(self.required_selection_banks),
            }
            expected_config["content_hash"] = hash_json(expected_config)
            if config != expected_config:
                raise StatePanelError("state-panel run config differs from runtime controls")


@dataclass(frozen=True)
class FrozenResourceProfile:
    schema_version: str
    envelope_id: str
    budget_mode: str
    load_condition: str
    lifecycle: str
    target_cpus: tuple[int, ...]
    worker_count: int
    chunk_iterations: int = 50_000
    readiness_timeout_s: float = 15.0

    def validate(self) -> None:
        if self.schema_version != "state-panel-resource-profile-1.0.0":
            raise ValueError("unknown state-panel resource-profile schema")
        if not self.envelope_id:
            raise ValueError("resource-profile envelope_id must be nonempty")
        if self.budget_mode not in {"wall_clock", "fixed_work"}:
            raise ValueError("resource-profile budget mode is invalid")
        if self.load_condition not in {"idle", "loaded"}:
            raise ValueError("resource-profile load condition is invalid")
        if self.lifecycle not in {"fresh", "persistent"}:
            raise ValueError("resource-profile lifecycle is invalid")
        LoadProfile(
            condition=self.load_condition,
            worker_count=self.worker_count,
            target_cpus=self.target_cpus,
            chunk_iterations=self.chunk_iterations,
            readiness_timeout_s=self.readiness_timeout_s,
        ).validate()

    def to_load_profile(self) -> LoadProfile:
        self.validate()
        return LoadProfile(
            condition=self.load_condition,
            worker_count=self.worker_count,
            target_cpus=self.target_cpus,
            chunk_iterations=self.chunk_iterations,
            readiness_timeout_s=self.readiness_timeout_s,
        )


def _resolve_entrypoint(value: str) -> Callable[..., Any]:
    if not isinstance(value, str) or value.count(":") != 1:
        raise ValueError("entrypoint must use module:function syntax")
    module_name, function_name = value.split(":", 1)
    if not module_name or not function_name:
        raise ValueError("entrypoint must use module:function syntax")
    function = getattr(importlib.import_module(module_name), function_name, None)
    if not callable(function):
        raise ValueError(f"entrypoint is not callable: {value}")
    return function


def _load_canonical_json(
    path: str | Path,
    *,
    expected_file_sha256: str | None = None,
) -> tuple[dict[str, Any], str]:
    source = Path(path).resolve()
    raw = source.read_bytes()
    observed = sha256_bytes(raw)
    if expected_file_sha256 is not None and observed != expected_file_sha256:
        raise StatePanelError(
            f"file hash mismatch for {source}: expected={expected_file_sha256}, observed={observed}"
        )
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StatePanelError(f"invalid JSON artifact: {source}") from exc
    if not isinstance(value, dict) or raw != canonical_json_bytes(value):
        raise StatePanelError(f"JSON artifact is not canonical: {source}")
    return value, observed


def _write_atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("wb") as handle:
        handle.write(canonical_json_bytes(dict(value)))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _append_jsonl(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(canonical_json_bytes(dict(value)))
        handle.flush()
        os.fsync(handle.fileno())
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    values: list[dict[str, Any]] = []
    with path.open("rb") as handle:
        for line_number, raw in enumerate(handle, 1):
            if not raw.strip():
                continue
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise StatePanelError(f"invalid JSONL {path}:{line_number}") from exc
            if not isinstance(value, dict) or raw != canonical_json_bytes(value):
                raise StatePanelError(f"noncanonical JSONL {path}:{line_number}")
            values.append(value)
    return values


def _verify_content_hash(value: Mapping[str, Any], label: str) -> None:
    supplied = value.get("content_hash")
    payload = dict(value)
    payload.pop("content_hash", None)
    if supplied != hash_json(payload):
        raise StatePanelError(f"{label} content hash mismatch")


def build_state_bank_preallocation(
    allocations: Mapping[str, Sequence[CaptureRequest]],
    *,
    purposes: Mapping[str, str],
) -> dict[str, Any]:
    """Freeze disjoint state/source/seed requests before any capture exists."""

    if set(allocations) != set(DEFAULT_SELECTION_BANKS) or set(purposes) != set(
        DEFAULT_SELECTION_BANKS
    ):
        raise ValueError("state-bank preallocation differs from the required state banks")
    banks: dict[str, Any] = {}
    owner: dict[tuple[str, Any], str] = {}
    for bank_name in DEFAULT_SELECTION_BANKS:
        purpose = purposes[bank_name]
        expected_purpose = (
            "calibration" if bank_name.endswith("calibration") else "repeatability"
        )
        if purpose != expected_purpose:
            raise ValueError(f"state-bank {bank_name} has an invalid purpose")
        requests = sorted(allocations[bank_name], key=lambda request: request.capture_id)
        if not requests:
            raise ValueError(f"state-bank {bank_name} has no preallocated requests")
        for request in requests:
            request.validate()
            for label in (
                "capture_id",
                "state_id",
                "source_game_id",
                "state_seed",
                "history_seed",
            ):
                key = (label, getattr(request, label))
                prior = owner.get(key)
                if prior is not None:
                    raise ValueError(
                        f"state-bank preallocation overlaps {prior}/{bank_name} on {label}"
                    )
                owner[key] = bank_name
        banks[bank_name] = {
            "purpose": purpose,
            "requests": [asdict(request) for request in requests],
        }
    manifest: dict[str, Any] = {
        "schema_version": "state-bank-preallocation-1.0.0",
        "required_banks": list(DEFAULT_SELECTION_BANKS),
        "banks": banks,
    }
    manifest["content_hash"] = hash_json(manifest)
    validate_state_bank_preallocation(manifest)
    return manifest


def validate_state_bank_preallocation(manifest: Mapping[str, Any]) -> None:
    _verify_content_hash(manifest, "state-bank preallocation")
    if (
        manifest.get("schema_version") != "state-bank-preallocation-1.0.0"
        or manifest.get("required_banks") != list(DEFAULT_SELECTION_BANKS)
    ):
        raise StatePanelError("unknown state-bank preallocation schema/ledger")
    banks = manifest.get("banks")
    if not isinstance(banks, Mapping) or set(banks) != set(DEFAULT_SELECTION_BANKS):
        raise StatePanelError("state-bank preallocation is incomplete")
    allocations: dict[str, list[CaptureRequest]] = {}
    purposes: dict[str, str] = {}
    for bank_name, value in banks.items():
        if not isinstance(value, Mapping):
            raise StatePanelError(f"preallocation bank {bank_name} is malformed")
        purposes[str(bank_name)] = str(value.get("purpose"))
        allocations[str(bank_name)] = [
            CaptureRequest(**dict(item)) for item in value.get("requests", [])
        ]
    # Re-run construction's disjointness without recursively validating again.
    owner: dict[tuple[str, Any], str] = {}
    for bank_name in DEFAULT_SELECTION_BANKS:
        expected_purpose = (
            "calibration" if bank_name.endswith("calibration") else "repeatability"
        )
        if purposes[bank_name] != expected_purpose or not allocations[bank_name]:
            raise StatePanelError(f"preallocation purpose/requests invalid for {bank_name}")
        for request in allocations[bank_name]:
            request.validate()
            for label in (
                "capture_id",
                "state_id",
                "source_game_id",
                "state_seed",
                "history_seed",
            ):
                key = (label, getattr(request, label))
                if key in owner:
                    raise StatePanelError(
                        f"state-bank preallocation overlaps {owner[key]}/{bank_name} on {label}"
                    )
                owner[key] = bank_name


def build_capture_manifest(
    bank_id: str,
    purpose: str,
    requests: Sequence[CaptureRequest],
    *,
    preallocation_manifest: Mapping[str, Any],
    preallocation_file_sha256: str,
) -> dict[str, Any]:
    if not bank_id:
        raise ValueError("capture bank_id must be nonempty")
    if purpose not in {"calibration", "repeatability"}:
        raise ValueError("state capture is limited to calibration or repeatability")
    ordered = sorted(requests, key=lambda request: request.capture_id)
    if not ordered:
        raise ValueError("capture manifest needs at least one request")
    for request in ordered:
        request.validate()
    for field_name in ("capture_id", "state_id", "source_game_id", "state_seed", "history_seed"):
        values = [getattr(request, field_name) for request in ordered]
        if len(values) != len(set(values)):
            raise ValueError(f"capture manifest repeats {field_name}")
    validate_state_bank_preallocation(preallocation_manifest)
    _require_sha256(preallocation_file_sha256, "state-bank preallocation file hash")
    banks = preallocation_manifest["banks"]
    if bank_id not in banks:
        raise ValueError("capture bank_id is not in the frozen preallocation")
    allocation = banks[bank_id]
    if allocation["purpose"] != purpose or allocation["requests"] != [
        asdict(request) for request in ordered
    ]:
        raise ValueError("capture requests differ from the frozen preallocation")
    manifest: dict[str, Any] = {
        "schema_version": "state-capture-manifest-1.0.0",
        "bank_id": bank_id,
        "purpose": purpose,
        "preallocation_content_hash": preallocation_manifest["content_hash"],
        "preallocation_file_sha256": preallocation_file_sha256,
        "requests": [asdict(request) for request in ordered],
    }
    manifest["content_hash"] = hash_json(manifest)
    validate_capture_manifest(manifest)
    return manifest


def validate_capture_manifest(manifest: Mapping[str, Any]) -> None:
    _verify_content_hash(manifest, "capture manifest")
    if set(manifest) != {
        "schema_version",
        "bank_id",
        "purpose",
        "preallocation_content_hash",
        "preallocation_file_sha256",
        "requests",
        "content_hash",
    }:
        raise StatePanelError("capture manifest fields differ from schema")
    if manifest.get("schema_version") != "state-capture-manifest-1.0.0":
        raise StatePanelError("unknown capture-manifest schema")
    if manifest.get("bank_id") not in DEFAULT_SELECTION_BANKS:
        raise StatePanelError("capture manifest bank is not a state-selection bank")
    if manifest.get("purpose") not in {"calibration", "repeatability"}:
        raise StatePanelError("capture manifest escaped calibration/repeatability scope")
    expected_purpose = (
        "calibration"
        if str(manifest.get("bank_id", "")).endswith("calibration")
        else "repeatability"
    )
    if manifest.get("purpose") != expected_purpose:
        raise StatePanelError("capture manifest purpose differs from state bank")
    _require_sha256(
        manifest.get("preallocation_file_sha256"),
        "state-bank preallocation file hash",
    )
    _require_sha256(
        manifest.get("preallocation_content_hash"),
        "state-bank preallocation content hash",
    )
    requests = [CaptureRequest(**dict(value)) for value in manifest.get("requests", [])]
    if not requests:
        raise StatePanelError("capture manifest has no requests")
    for request in requests:
        request.validate()
    for field_name in ("capture_id", "state_id", "source_game_id", "state_seed", "history_seed"):
        values = [getattr(request, field_name) for request in requests]
        if len(values) != len(set(values)):
            raise StatePanelError(f"capture manifest repeats {field_name}")


def _frozen_capture_bytes(state: CapturedDecisionState) -> bytes:
    state.validate()
    return canonical_json_bytes(
        {
            "schema_version": FROZEN_CAPTURE_SCHEMA_VERSION,
            "captured_state_artifact_hash": state.artifact_hash,
            "captured_state": state.to_dict(),
        }
    )


def _load_frozen_capture_bytes(raw: bytes, *, expected_sha256: str) -> CapturedDecisionState:
    """Validate a complete frozen wrapper while retaining its raw-state object exactly."""

    if sha256_bytes(raw) != expected_sha256:
        raise StatePanelError("in-memory frozen captured-state file SHA-256 mismatch")
    try:
        payload = json.loads(raw.decode("ascii"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise StatePanelError("cannot decode frozen captured-state bytes") from exc
    if not isinstance(payload, Mapping) or canonical_json_bytes(payload) != raw:
        raise StatePanelError("frozen captured-state bytes are not canonical")
    if set(payload) != {
        "schema_version",
        "captured_state_artifact_hash",
        "captured_state",
    } or payload.get("schema_version") != FROZEN_CAPTURE_SCHEMA_VERSION:
        raise StatePanelError("frozen captured-state wrapper differs from schema")
    captured = payload.get("captured_state")
    if not isinstance(captured, Mapping):
        raise StatePanelError("frozen captured-state wrapper lacks captured_state")
    state = CapturedDecisionState.from_dict(captured)
    if payload.get("captured_state_artifact_hash") != state.artifact_hash:
        raise StatePanelError("frozen captured-state embedded hash mismatch")
    return state


def _history_artifact_bytes(
    request: Mapping[str, Any], state: CapturedDecisionState
) -> bytes:
    payload: dict[str, Any] = {
        "schema_version": "state-panel-history-prefix-1.0.0",
        "capture_id": request["capture_id"],
        "state_id": state.state_id,
        "source_game_id": state.source_game_id,
        "source_environment_seed": state.source_environment_seed,
        "target_eligible_index": state.target_eligible_index,
        "history_seed": request["history_seed"],
        "history_length": request["history_length"],
        "gameplay_decision_count": len(state.history_prefix),
        "history_prefix": list(state.history_prefix),
    }
    payload["content_hash"] = hash_json(payload)
    return canonical_json_bytes(payload)


def _load_history_artifact_bytes(
    raw: bytes,
    *,
    row: Mapping[str, Any] | None = None,
    request: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise StatePanelError("cannot decode frozen state-panel history") from exc
    if not isinstance(payload, dict) or canonical_json_bytes(payload) != raw:
        raise StatePanelError("frozen state-panel history is not canonical JSON")
    _verify_content_hash(payload, "state-panel history")
    required = {
        "schema_version",
        "capture_id",
        "state_id",
        "source_game_id",
        "source_environment_seed",
        "target_eligible_index",
        "history_seed",
        "history_length",
        "gameplay_decision_count",
        "history_prefix",
        "content_hash",
    }
    if set(payload) != required or payload.get("schema_version") != (
        "state-panel-history-prefix-1.0.0"
    ):
        raise StatePanelError("state-panel history differs from schema")
    history = payload.get("history_prefix")
    if not isinstance(history, list) or any(not isinstance(item, Mapping) for item in history):
        raise StatePanelError("state-panel history prefix is malformed")
    if payload.get("gameplay_decision_count") != len(history):
        raise StatePanelError("state-panel gameplay prefix length does not reconcile")
    history_length = payload.get("history_length")
    target_eligible_index = payload.get("target_eligible_index")
    if (
        isinstance(history_length, bool)
        or not isinstance(history_length, int)
        or history_length < 0
        or history_length != target_eligible_index
    ):
        raise StatePanelError("state-panel warm-up length differs from eligible ordinal")
    expected = row if row is not None else request
    if expected is not None:
        comparisons = {
            "state_id": expected.get("state_id"),
            "source_game_id": expected.get("source_game_id"),
            "history_seed": expected.get("history_seed"),
            "history_length": expected.get("history_length"),
        }
        if request is not None:
            comparisons["capture_id"] = request.get("capture_id")
            comparisons["source_environment_seed"] = request.get("state_seed")
            comparisons["target_eligible_index"] = dict(
                request.get("capture_kwargs", {})
            ).get("target_eligible_index")
        for field_name, expected_value in comparisons.items():
            if payload.get(field_name) != expected_value:
                raise StatePanelError(
                    f"state-panel history differs from frozen {field_name}"
                )
    return payload


def native_capture_entrypoint(
    request: Mapping[str, Any], payload: Mapping[str, Any]
) -> dict[str, Any]:
    """Capture one native state and emit the canonical frozen wrapper bytes."""

    required_payload = {
        "schema_version",
        "engine_path",
        "engine_sha256",
        "deck_path",
        "deck_sha256",
        "model_path",
        "model_sha256",
        "max_decisions",
    }
    if set(payload) != required_payload or payload.get("schema_version") != (
        "native-state-capture-runtime-1.0.0"
    ):
        raise StatePanelError("native capture runtime differs from schema")
    for label in ("engine", "deck", "model"):
        path = Path(str(payload[f"{label}_path"])).resolve()
        expected = _require_sha256(payload[f"{label}_sha256"], f"{label} hash")
        if hash_file(path) != expected:
            raise StatePanelError(f"native capture {label} file hash mismatch")
    kwargs = request.get("capture_kwargs")
    if not isinstance(kwargs, Mapping) or set(kwargs) != {
        "target_eligible_index",
        "physical_seat",
        "play_order",
    }:
        raise StatePanelError("native capture request kwargs differ from schema")
    state = capture_anchor_state(
        engine_path=str(payload["engine_path"]),
        deck_path=str(payload["deck_path"]),
        model_path=str(payload["model_path"]),
        source_environment_seed=int(request["state_seed"]),
        target_eligible_index=int(kwargs["target_eligible_index"]),
        physical_seat=int(kwargs["physical_seat"]),
        play_order=int(kwargs["play_order"]),
        max_decisions=int(payload["max_decisions"]),
    )
    if (
        state.state_id != request.get("state_id")
        or state.source_game_id != request.get("source_game_id")
        or state.source_environment_seed != request.get("state_seed")
        or state.target_eligible_index != kwargs.get("target_eligible_index")
        or state.observed_eligible_index != kwargs.get("target_eligible_index")
        or state.target_eligible_index != request.get("history_length")
    ):
        raise StatePanelError("native capture differs from the predeclared request")
    state_bytes = _frozen_capture_bytes(state)
    history_bytes = _history_artifact_bytes(request, state)
    return {
        "state_bytes": state_bytes,
        "history_bytes": history_bytes,
        "metadata": {
            "capture_id": request["capture_id"],
            "state_id": state.state_id,
            "source_game_id": state.source_game_id,
            "source_environment_seed": state.source_environment_seed,
            "target_eligible_index": state.target_eligible_index,
            "observed_eligible_index": state.observed_eligible_index,
            "history_seed": request["history_seed"],
            "history_length": state.target_eligible_index,
            "gameplay_decision_count": len(state.history_prefix),
            "captured_state_artifact_hash": state.artifact_hash,
            "state_file_sha256": sha256_bytes(state_bytes),
            "history_file_sha256": sha256_bytes(history_bytes),
        },
    }


def _capture_child(
    output_queue: Any,
    entrypoint: str,
    request: dict[str, Any],
    payload: dict[str, Any],
    expected_parent_pid: int,
    require_parent_death: bool,
) -> None:
    parent_guard = arm_parent_death_kill(
        expected_parent_pid=expected_parent_pid,
        required=require_parent_death,
    )
    try:
        result = _resolve_entrypoint(entrypoint)(request, payload)
        if not isinstance(result, Mapping):
            raise TypeError("capture entrypoint did not return a mapping")
        state_bytes = result.get("state_bytes")
        history_bytes = result.get("history_bytes")
        metadata = result.get("metadata")
        if not isinstance(state_bytes, bytes) or not state_bytes:
            raise TypeError("capture entrypoint returned no opaque state bytes")
        if not isinstance(history_bytes, bytes):
            raise TypeError("capture entrypoint returned non-byte history")
        if not isinstance(metadata, Mapping):
            raise TypeError("capture entrypoint returned no metadata mapping")
        output_queue.put(
            {
                "ok": True,
                "state_bytes": state_bytes,
                "history_bytes": history_bytes,
                "metadata": dict(metadata),
                "observed_process_id": os.getpid(),
                "parent_death_kill_armed": parent_guard is not None,
            }
        )
    except BaseException as exc:
        output_queue.put(
            {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
                "observed_process_id": os.getpid(),
            }
        )


def _terminate_then_kill(process: Any, *, label: str) -> None:
    """Ensure a failed spawned worker is dead before any IPC cleanup proceeds."""

    try:
        stop_process(process)
    except RuntimeError as exc:
        raise StatePanelError(f"{label}: {exc}") from exc


def _spawn_capture(
    request: Mapping[str, Any],
    *,
    entrypoint: str,
    payload: Mapping[str, Any],
    timeout_s: float,
    require_parent_death: bool = False,
) -> dict[str, Any]:
    context = mp.get_context("spawn")
    output_queue = context.Queue()
    process = context.Process(
        target=_capture_child,
        args=(
            output_queue,
            entrypoint,
            dict(request),
            dict(payload),
            os.getpid(),
            require_parent_death,
        ),
        name=f"capture-{request['state_id']}",
    )
    started = False
    try:
        process.start()
        started = True
        try:
            message = output_queue.get(timeout=timeout_s)
        except queue.Empty as exc:
            raise StatePanelError(
                f"capture worker timed out for {request['state_id']}"
            ) from exc
        process.join(timeout=30.0)
        if process.is_alive():
            raise StatePanelError(f"capture worker failed to exit for {request['state_id']}")
        if process.exitcode != 0 or message.get("ok") is not True:
            raise StatePanelError(
                f"capture worker failed for {request['state_id']}: {message.get('error')}"
            )
        if message.get("observed_process_id") != process.pid:
            raise StatePanelError("capture worker PID evidence mismatch")
        if require_parent_death and message.get("parent_death_kill_armed") is not True:
            raise StatePanelError("capture worker lacks parent-death protection evidence")
        return message
    except BaseException:
        child_started = started or process.pid is not None
        if child_started and process.is_alive():
            _terminate_then_kill(process, label=f"capture worker {request['state_id']}")
        raise
    finally:
        # Never touch queue feeder state while a child might still be using it.
        child_started = started or process.pid is not None
        if not child_started or not process.is_alive():
            output_queue.close()
            output_queue.join_thread()


def _validate_capture_directory(
    directory: Path,
    request: Mapping[str, Any],
    manifest_content_hash: str,
    *,
    test_mode: bool,
) -> dict[str, Any]:
    commit, _ = _load_canonical_json(directory / "capture_commit.json")
    _verify_content_hash(commit, "capture commit")
    if (
        commit.get("schema_version") != "state-capture-commit-1.0.0"
        or commit.get("request") != dict(request)
        or commit.get("capture_manifest_content_hash") != manifest_content_hash
    ):
        raise StatePanelError(f"capture commit provenance mismatch for {request['state_id']}")
    state_path = directory / "state.raw"
    history_path = directory / "history.raw"
    if (
        hash_file(state_path) != commit.get("state_artifact_sha256")
        or hash_file(history_path) != commit.get("history_prefix_sha256")
        or state_path.stat().st_size != commit.get("state_bytes")
        or history_path.stat().st_size != commit.get("history_bytes")
    ):
        raise StatePanelError(f"captured raw bytes changed for {request['state_id']}")
    _validate_captured_artifacts(
        state_path,
        history_path,
        request=request,
        metadata=commit.get("capture_metadata"),
        test_mode=test_mode,
    )
    return commit


def _validate_captured_artifacts(
    state_path: Path,
    history_path: Path,
    *,
    request: Mapping[str, Any],
    metadata: Any,
    test_mode: bool,
) -> None:
    if not isinstance(metadata, Mapping):
        raise StatePanelError("capture metadata is not a mapping")
    expected_metadata = {
        "capture_id": request.get("capture_id"),
        "state_id": request.get("state_id"),
        "source_game_id": request.get("source_game_id"),
        "source_environment_seed": request.get("state_seed"),
        "history_seed": request.get("history_seed"),
        "history_length": request.get("history_length"),
    }
    target = dict(request.get("capture_kwargs", {})).get("target_eligible_index")
    if target is not None:
        expected_metadata["target_eligible_index"] = target
    for field_name, expected in expected_metadata.items():
        if metadata.get(field_name) != expected:
            raise StatePanelError(f"capture metadata differs from request in {field_name}")
    if test_mode:
        return
    state_sha256 = hash_file(state_path)
    state = load_frozen_captured_state(
        state_path,
        expected_file_sha256=state_sha256,
    )
    kwargs = dict(request.get("capture_kwargs", {}))
    if (
        state.state_id != request.get("state_id")
        or state.source_game_id != request.get("source_game_id")
        or state.source_environment_seed != request.get("state_seed")
        or state.target_eligible_index != kwargs.get("target_eligible_index")
        or state.observed_eligible_index != kwargs.get("target_eligible_index")
        or state.target_eligible_index != request.get("history_length")
    ):
        raise StatePanelError("captured state content differs from request")
    history = _load_history_artifact_bytes(history_path.read_bytes(), request=request)
    if history["history_prefix"] != list(state.history_prefix):
        raise StatePanelError("captured history bytes differ from captured state history")
    required_native_metadata = {
        **expected_metadata,
        "observed_eligible_index": kwargs.get("target_eligible_index"),
        "gameplay_decision_count": len(state.history_prefix),
        "captured_state_artifact_hash": state.artifact_hash,
        "state_file_sha256": state_sha256,
        "history_file_sha256": hash_file(history_path),
    }
    if dict(metadata) != required_native_metadata:
        raise StatePanelError("native capture metadata differs from exact schema")


def capture_states_isolated(
    manifest_path: str | Path,
    *,
    expected_manifest_sha256: str,
    preallocation_path: str | Path,
    output_dir: str | Path,
    entrypoint: str,
    entrypoint_payload: Mapping[str, Any],
    execution_enabled: bool = False,
    test_mode: bool = False,
    worker_timeout_s: float = 3_600.0,
) -> dict[str, Any]:
    """Capture each state once in a new child and atomically freeze its bytes."""

    manifest, observed_manifest_hash = _load_canonical_json(
        manifest_path, expected_file_sha256=expected_manifest_sha256
    )
    validate_capture_manifest(manifest)
    preallocation, _ = _load_canonical_json(
        preallocation_path,
        expected_file_sha256=str(manifest["preallocation_file_sha256"]),
    )
    validate_state_bank_preallocation(preallocation)
    if preallocation.get("content_hash") != manifest.get("preallocation_content_hash"):
        raise StatePanelError("capture manifest preallocation content hash changed")
    allocation = preallocation["banks"].get(manifest["bank_id"])
    if not isinstance(allocation, Mapping) or (
        allocation.get("purpose") != manifest.get("purpose")
        or allocation.get("requests") != manifest.get("requests")
    ):
        raise StatePanelError("capture manifest differs from its frozen preallocation")
    function = _resolve_entrypoint(entrypoint)
    if function is synthetic_capture_entrypoint and not test_mode:
        raise StatePanelError("synthetic capture is test-only")
    if not test_mode and entrypoint != SCIENTIFIC_CAPTURE_ENTRYPOINT:
        raise StatePanelError(
            "scientific state capture requires the study-owned native entrypoint"
        )
    if not execution_enabled:
        raise StatePanelError("state capture is disabled until explicitly enabled")
    if not test_mode:
        from training.azure_guard import is_azure_host

        if platform.system() != "Linux" or not is_azure_host():
            raise StatePanelError(
                "scientific state capture requires an already-authorized Azure Linux host"
            )
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    captured: list[dict[str, Any]] = []
    for request in manifest["requests"]:
        final_directory = output / str(request["state_id"])
        partials = list(output.glob(f".{request['state_id']}.*.tmp"))
        if partials:
            raise StatePanelError(
                f"partial capture directories exist for {request['state_id']}; preserve and inspect"
            )
        if final_directory.exists():
            captured.append(
                _validate_capture_directory(
                    final_directory,
                    request,
                    str(manifest["content_hash"]),
                    test_mode=test_mode,
                )
            )
            continue
        message = _spawn_capture(
            request,
            entrypoint=entrypoint,
            payload=entrypoint_payload,
            timeout_s=worker_timeout_s,
            require_parent_death=not test_mode,
        )
        state_bytes = message["state_bytes"]
        history_bytes = message["history_bytes"]
        temporary = Path(
            tempfile.mkdtemp(prefix=f".{request['state_id']}.", suffix=".tmp", dir=output)
        )
        try:
            for name, raw in (("state.raw", state_bytes), ("history.raw", history_bytes)):
                with (temporary / name).open("wb") as handle:
                    handle.write(raw)
                    handle.flush()
                    os.fsync(handle.fileno())
            _validate_captured_artifacts(
                temporary / "state.raw",
                temporary / "history.raw",
                request=request,
                metadata=message["metadata"],
                test_mode=test_mode,
            )
            commit: dict[str, Any] = {
                "schema_version": "state-capture-commit-1.0.0",
                "request": dict(request),
                "capture_manifest_content_hash": manifest["content_hash"],
                "capture_manifest_file_sha256": observed_manifest_hash,
                "state_artifact_sha256": sha256_bytes(state_bytes),
                "history_prefix_sha256": sha256_bytes(history_bytes),
                "state_bytes": len(state_bytes),
                "history_bytes": len(history_bytes),
                "capture_metadata": message["metadata"],
                "observed_process_id": message["observed_process_id"],
            }
            commit["content_hash"] = hash_json(commit)
            _write_atomic_json(temporary / "capture_commit.json", commit)
            os.rename(temporary, final_directory)
            captured.append(commit)
        except BaseException:
            # Preserve the incomplete capture for forensic inspection.  Its
            # .tmp name makes every later resume refuse rather than recapture.
            raise
    inventory: dict[str, Any] = {
        "schema_version": "state-capture-inventory-1.0.0",
        "capture_manifest_content_hash": manifest["content_hash"],
        "capture_manifest_file_sha256": observed_manifest_hash,
        "captured_states": sorted(captured, key=lambda item: item["request"]["state_id"]),
    }
    inventory["content_hash"] = hash_json(inventory)
    _write_atomic_json(output / "capture_inventory.json", inventory)
    return inventory


def synthetic_capture_entrypoint(
    request: Mapping[str, Any], payload: Mapping[str, Any]
) -> dict[str, Any]:
    """Test-only capture that deliberately permits noncanonical opaque bytes."""

    kwargs = dict(request.get("capture_kwargs", {}))
    state_hex = kwargs.get("state_bytes_hex")
    history_hex = kwargs.get("history_bytes_hex", "")
    if not isinstance(state_hex, str) or not isinstance(history_hex, str):
        raise ValueError("synthetic capture requires hexadecimal byte strings")
    state_bytes = bytes.fromhex(state_hex)
    history_bytes = bytes.fromhex(history_hex)
    kwargs = dict(request.get("capture_kwargs", {}))
    return {
        "state_bytes": state_bytes,
        "history_bytes": history_bytes,
        "metadata": {
            "capture_id": request["capture_id"],
            "state_id": request["state_id"],
            "source_game_id": request["source_game_id"],
            "source_environment_seed": request["state_seed"],
            "target_eligible_index": kwargs.get("target_eligible_index"),
            "history_seed": request["history_seed"],
            "history_length": request["history_length"],
            "payload_hash": hash_json(dict(payload)),
            "state_file_sha256": sha256_bytes(state_bytes),
            "history_file_sha256": sha256_bytes(history_bytes),
            "synthetic": True,
        },
    }


def build_state_selection_bank(
    bank_name: str,
    *,
    execution_manifest_path: str | Path,
    execution_manifest_sha256: str,
    capture_inventory_path: str | Path,
    capture_inventory_sha256: str,
) -> dict[str, Any]:
    """Bind a completed capture inventory to its later execution manifest."""

    if bank_name not in DEFAULT_SELECTION_BANKS:
        raise ValueError("unknown state selection bank")
    execution, _ = _load_canonical_json(
        execution_manifest_path,
        expected_file_sha256=_require_sha256(
            execution_manifest_sha256, "execution manifest file hash"
        ),
    )
    inventory, _ = _load_canonical_json(
        capture_inventory_path,
        expected_file_sha256=_require_sha256(
            capture_inventory_sha256, "capture inventory file hash"
        ),
    )
    _verify_content_hash(inventory, "capture inventory")
    schema = execution.get("schema_version")
    if bank_name.endswith("calibration"):
        if schema != "calibration-manifest-1.0.0":
            raise StatePanelError("calibration state bank has the wrong execution manifest")
        validate_calibration_manifest(execution)
    else:
        if schema != "repeatability-manifest-1.0.0":
            raise StatePanelError("repeatability state bank has the wrong execution manifest")
        validate_repeatability_manifest(execution)
    if inventory.get("schema_version") != "state-capture-inventory-1.0.0":
        raise StatePanelError("state bank has an unknown capture inventory")
    captures = inventory.get("captured_states")
    if not isinstance(captures, list):
        raise StatePanelError("state bank capture inventory lacks states")
    capture_by_state: dict[str, Mapping[str, Any]] = {}
    for capture in captures:
        if not isinstance(capture, Mapping) or not isinstance(capture.get("request"), Mapping):
            raise StatePanelError("state bank capture inventory is malformed")
        _verify_content_hash(capture, "state capture commit")
        state_id = str(capture["request"]["state_id"])
        if state_id in capture_by_state:
            raise StatePanelError("state bank capture inventory repeats a state")
        capture_by_state[state_id] = capture
    execution_states = execution.get("states")
    if not isinstance(execution_states, list):
        raise StatePanelError("state bank execution manifest lacks states")
    if {str(state["state_id"]) for state in execution_states} != set(capture_by_state):
        raise StatePanelError("capture inventory and execution state IDs differ")
    bound_states: list[dict[str, Any]] = []
    for state in sorted(execution_states, key=lambda item: str(item["state_id"])):
        capture = capture_by_state[str(state["state_id"])]
        request = capture["request"]
        common = {
            "state_id": request["state_id"],
            "source_game_id": request["source_game_id"],
            "state_seed": request["state_seed"],
            "state_artifact_sha256": capture["state_artifact_sha256"],
        }
        for field_name, expected in common.items():
            if state.get(field_name) != expected:
                raise StatePanelError(
                    f"execution state differs from capture inventory in {field_name}"
                )
        if schema == "repeatability-manifest-1.0.0":
            for field_name, expected in (
                ("history_seed", request["history_seed"]),
                ("history_length", request["history_length"]),
                ("history_prefix_sha256", capture["history_prefix_sha256"]),
            ):
                if state.get(field_name) != expected:
                    raise StatePanelError(
                        f"repeatability history differs from capture in {field_name}"
                    )
        bound_states.append(dict(state))
    bank: dict[str, Any] = {
        "schema_version": "state-selection-bank-1.0.0",
        "bank_name": bank_name,
        "execution_manifest_path": str(Path(execution_manifest_path).resolve()),
        "execution_manifest_file_sha256": execution_manifest_sha256,
        "execution_manifest_content_hash": execution["content_hash"],
        "capture_inventory_path": str(Path(capture_inventory_path).resolve()),
        "capture_inventory_file_sha256": capture_inventory_sha256,
        "capture_inventory_content_hash": inventory["content_hash"],
        "states": bound_states,
        "seed_inventory": execution.get("seed_inventory"),
    }
    bank["content_hash"] = hash_json(bank)
    validate_state_selection_bank(bank)
    return bank


def validate_state_selection_bank(bank: Mapping[str, Any]) -> None:
    _verify_content_hash(bank, "state selection bank")
    required = {
        "schema_version",
        "bank_name",
        "execution_manifest_path",
        "execution_manifest_file_sha256",
        "execution_manifest_content_hash",
        "capture_inventory_path",
        "capture_inventory_file_sha256",
        "capture_inventory_content_hash",
        "states",
        "seed_inventory",
        "content_hash",
    }
    if (
        set(bank) != required
        or bank.get("schema_version") != "state-selection-bank-1.0.0"
        or bank.get("bank_name") not in DEFAULT_SELECTION_BANKS
    ):
        raise StatePanelError("state selection bank differs from schema")
    execution, _ = _load_canonical_json(
        str(bank["execution_manifest_path"]),
        expected_file_sha256=_require_sha256(
            bank["execution_manifest_file_sha256"], "execution manifest hash"
        ),
    )
    inventory, _ = _load_canonical_json(
        str(bank["capture_inventory_path"]),
        expected_file_sha256=_require_sha256(
            bank["capture_inventory_file_sha256"], "capture inventory hash"
        ),
    )
    _verify_content_hash(inventory, "capture inventory")
    if (
        execution.get("content_hash") != bank.get("execution_manifest_content_hash")
        or inventory.get("content_hash") != bank.get("capture_inventory_content_hash")
    ):
        raise StatePanelError("state selection bank embedded content hashes changed")
    schema = execution.get("schema_version")
    if schema == "calibration-manifest-1.0.0":
        validate_calibration_manifest(execution)
    elif schema == "repeatability-manifest-1.0.0":
        validate_repeatability_manifest(execution)
    else:
        raise StatePanelError("state selection bank execution manifest is unsupported")
    if bank.get("states") != execution.get("states") or bank.get(
        "seed_inventory"
    ) != execution.get("seed_inventory"):
        raise StatePanelError("state selection bank inventory differs from execution manifest")
    captures = inventory.get("captured_states")
    if not isinstance(captures, list) or len(captures) != len(bank["states"]):
        raise StatePanelError("state selection bank capture cardinality changed")
    capture_by_state = {
        str(item["request"]["state_id"]): item
        for item in captures
        if isinstance(item, Mapping) and isinstance(item.get("request"), Mapping)
    }
    if len(capture_by_state) != len(captures):
        raise StatePanelError("state selection bank capture inventory repeats a state")
    for capture in captures:
        _verify_content_hash(capture, "state capture commit")
    for state in bank["states"]:
        capture = capture_by_state.get(str(state["state_id"]))
        if capture is None:
            raise StatePanelError("state selection bank lacks a captured execution state")
        request = capture["request"]
        for field_name, expected in (
            ("source_game_id", request["source_game_id"]),
            ("state_seed", request["state_seed"]),
            ("state_artifact_sha256", capture["state_artifact_sha256"]),
        ):
            if state.get(field_name) != expected:
                raise StatePanelError(
                    f"state selection bank differs from capture in {field_name}"
                )
        if schema == "repeatability-manifest-1.0.0" and (
            state.get("history_seed") != request["history_seed"]
            or state.get("history_length") != request["history_length"]
            or state.get("history_prefix_sha256") != capture["history_prefix_sha256"]
        ):
            raise StatePanelError("state selection bank repeatability history changed")


def _selection_bank_states(value: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    states = value.get("states")
    if isinstance(states, list):
        return [item for item in states if isinstance(item, Mapping)]
    captured = value.get("captured_states")
    if isinstance(captured, list):
        result: list[Mapping[str, Any]] = []
        for item in captured:
            if not isinstance(item, Mapping):
                continue
            request = item.get("request")
            if not isinstance(request, Mapping):
                continue
            result.append(
                {
                    "state_id": request.get("state_id"),
                    "source_game_id": request.get("source_game_id"),
                    "state_artifact_sha256": item.get("state_artifact_sha256"),
                    "state_seed": request.get("state_seed"),
                    "history_seed": request.get("history_seed"),
                }
            )
        return result
    raise StatePanelError("selection bank has no state inventory")


def validate_disjoint_selection_banks(
    bank_files: Mapping[str, str | Path],
    expected_file_sha256: Mapping[str, str],
    *,
    required_banks: Iterable[str] = DEFAULT_SELECTION_BANKS,
) -> dict[str, str]:
    """Validate exact bank files and state/source/artifact/seed disjointness."""

    required = set(required_banks)
    if set(bank_files) != required or set(expected_file_sha256) != required:
        raise StatePanelError("selection-bank files/hashes differ from the frozen ledger")
    owners: dict[tuple[str, Any], str] = {}
    seed_owner: dict[int, str] = {}
    observed_hashes: dict[str, str] = {}
    for bank_name in sorted(required):
        value, observed = _load_canonical_json(
            bank_files[bank_name],
            expected_file_sha256=expected_file_sha256[bank_name],
        )
        observed_hashes[bank_name] = observed
        if "content_hash" in value:
            _verify_content_hash(value, f"selection bank {bank_name}")
        schema = value.get("schema_version")
        if schema != "state-selection-bank-1.0.0":
            raise StatePanelError("selection ledger must contain state-selection-bank wrappers")
        validate_state_selection_bank(value)
        if value.get("bank_name") != bank_name:
            raise StatePanelError("state selection-bank filename key differs from wrapper")
        for state in _selection_bank_states(value):
            for label in ("state_id", "source_game_id", "state_artifact_sha256"):
                item = state.get(label)
                if item is None:
                    raise StatePanelError(f"selection bank {bank_name} state lacks {label}")
                key = (label, item)
                prior = owners.get(key)
                if prior is not None and prior != bank_name:
                    raise StatePanelError(
                        f"selection banks {prior} and {bank_name} overlap on {label}={item}"
                    )
                owners[key] = bank_name
        inventory = value.get("seed_inventory")
        if isinstance(inventory, Mapping):
            seeds = {
                int(seed)
                for values in inventory.values()
                if isinstance(values, list)
                for seed in values
            }
        else:
            seeds = collect_persisted_seeds(value)
        for seed in seeds:
            prior = seed_owner.get(seed)
            if prior is not None and prior != bank_name:
                raise StatePanelError(
                    f"selection-bank seed {seed} overlaps {prior} and {bank_name}"
                )
            seed_owner[seed] = bank_name
    return observed_hashes


def _load_resource_profile(
    path: str | Path,
    expected_sha256: str,
    *,
    row: Mapping[str, Any],
    runtime: PanelRuntime,
) -> FrozenResourceProfile:
    value, _ = _load_canonical_json(path, expected_file_sha256=expected_sha256)
    data = dict(value)
    data["target_cpus"] = tuple(data.get("target_cpus", ()))
    profile = FrozenResourceProfile(**data)
    profile.validate()
    for field_name in ("envelope_id", "budget_mode", "load_condition", "lifecycle"):
        if getattr(profile, field_name) != row.get(field_name):
            raise StatePanelError(
                f"resource profile {profile.envelope_id} differs from row in {field_name}"
            )
    if profile.target_cpus != runtime.target_cpus:
        raise StatePanelError("resource-profile CPUs differ from frozen runtime CPUs")
    expected_workers = 0 if profile.load_condition == "idle" else runtime.load_workers
    if profile.worker_count != expected_workers:
        raise StatePanelError("resource-profile worker count differs from frozen runtime")
    return profile


def _validate_state_file(path: str | Path, expected_sha256: str, label: str) -> Path:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise StatePanelError(f"missing {label} file: {resolved}")
    observed = hash_file(resolved)
    if observed != expected_sha256:
        raise StatePanelError(
            f"{label} raw-byte hash mismatch: expected={expected_sha256}, observed={observed}"
        )
    return resolved


def _validate_frozen_capture_file(
    path: str | Path,
    expected_sha256: str,
    *,
    state_id: str,
    source_game_id: str,
    test_mode: bool,
) -> Path:
    resolved = _validate_state_file(path, expected_sha256, "captured-state")
    if not test_mode:
        state = load_frozen_captured_state(
            resolved,
            expected_file_sha256=expected_sha256,
        )
        if state.state_id != state_id or state.source_game_id != source_game_id:
            raise StatePanelError("frozen captured-state identity differs from manifest")
    return resolved


def _apply_affinity(target_cpus: tuple[int, ...]) -> bool:
    if not hasattr(os, "sched_setaffinity"):
        return False
    os.sched_setaffinity(0, set(target_cpus))
    return True


def _observed_affinity() -> list[int] | None:
    if not hasattr(os, "sched_getaffinity"):
        return None
    return sorted(int(cpu) for cpu in os.sched_getaffinity(0))


def _panel_child(
    output_queue: Any,
    entrypoint: str,
    row: dict[str, Any],
    state_path: str,
    history_path: str | None,
    payload: dict[str, Any],
    target_cpus: tuple[int, ...],
    require_affinity: bool,
    thread_env: dict[str, str],
    expected_parent_pid: int,
) -> None:
    parent_guard = arm_parent_death_kill(
        expected_parent_pid=expected_parent_pid,
        required=require_affinity,
    )
    started = time.process_time_ns()
    runtime: dict[str, Any] = {
        "observed_process_id": os.getpid(),
        "target_cpus": list(target_cpus),
        "process_time_ns_start": started,
        "parent_death_kill_armed": parent_guard is not None,
    }
    try:
        observed_thread_env = {key: os.environ.get(key) for key in thread_env}
        runtime["thread_env"] = observed_thread_env
        if observed_thread_env != thread_env:
            raise RuntimeError("state-panel child thread environment mismatch")
        runtime["affinity_applied"] = _apply_affinity(target_cpus)
        runtime["observed_affinity"] = _observed_affinity()
        if require_affinity and (
            not runtime["affinity_applied"]
            or runtime["observed_affinity"] != sorted(target_cpus)
        ):
            raise RuntimeError("state-panel child affinity mismatch")
        state_bytes = Path(state_path).read_bytes()
        history_bytes = None if history_path is None else Path(history_path).read_bytes()
        state_sha256 = sha256_bytes(state_bytes)
        history_sha256 = None if history_bytes is None else sha256_bytes(history_bytes)
        result = _resolve_entrypoint(entrypoint)(
            row,
            state_bytes,
            history_bytes,
            payload,
        )
        if not isinstance(result, Mapping):
            raise TypeError("panel entrypoint did not return a mapping")
        runtime["process_time_ns_end"] = time.process_time_ns()
        runtime["process_time_ns_delta"] = (
            runtime["process_time_ns_end"] - runtime["process_time_ns_start"]
        )
        output_queue.put(
            {
                "ok": True,
                "result": dict(result),
                "state_bytes_sha256": state_sha256,
                "history_bytes_sha256": history_sha256,
                "runtime": runtime,
            }
        )
    except BaseException as exc:
        runtime["process_time_ns_end"] = time.process_time_ns()
        runtime["process_time_ns_delta"] = (
            runtime["process_time_ns_end"] - runtime["process_time_ns_start"]
        )
        output_queue.put(
            {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
                "runtime": runtime,
            }
        )


def _spawn_panel_case(
    row: Mapping[str, Any],
    *,
    state_path: Path,
    history_path: Path | None,
    runtime: PanelRuntime,
) -> dict[str, Any]:
    context = mp.get_context("spawn")
    output_queue = context.Queue()
    process = context.Process(
        target=_panel_child,
        args=(
            output_queue,
            runtime.entrypoint,
            dict(row),
            str(state_path),
            None if history_path is None else str(history_path),
            dict(runtime.entrypoint_payload),
            runtime.target_cpus,
            runtime.require_linux_affinity,
            dict(runtime.thread_env),
            os.getpid(),
        ),
        name=f"panel-{_row_case_id(row)}",
    )
    started = False
    try:
        process.start()
        started = True
        try:
            message = output_queue.get(timeout=runtime.worker_timeout_s)
        except queue.Empty:
            message = {
                "ok": False,
                "error": "state-panel worker timeout",
                "runtime": {"observed_process_id": process.pid},
            }
            _terminate_then_kill(
                process, label=f"state-panel worker {_row_case_id(row)}"
            )
        else:
            process.join(timeout=30.0)
            if process.is_alive():
                _terminate_then_kill(
                    process, label=f"state-panel worker {_row_case_id(row)}"
                )
                message = {
                    "ok": False,
                    "error": "state-panel worker failed to exit",
                    "runtime": message.get("runtime", {}),
                }
            elif process.exitcode != 0:
                message = {
                    "ok": False,
                    "error": f"state-panel worker exit code {process.exitcode}",
                    "runtime": message.get("runtime", {}),
                }
        worker = dict(message.get("runtime", {}))
        worker["spawned_process_id"] = process.pid
        worker["exitcode"] = process.exitcode
        if worker.get("observed_process_id") != process.pid:
            message = {"ok": False, "error": "state-panel PID evidence mismatch"}
        if runtime.require_linux_affinity and worker.get("observed_affinity") != sorted(
            runtime.target_cpus
        ):
            message = {"ok": False, "error": "state-panel affinity evidence mismatch"}
        if (
            runtime.require_linux_affinity
            and worker.get("parent_death_kill_armed") is not True
        ):
            message = {
                "ok": False,
                "error": "state-panel parent-death protection evidence mismatch",
            }
        if message.get("ok") is not True:
            raise StatePanelError(str(message.get("error", "state-panel worker failed")))
        message["runtime"] = worker
        return message
    except BaseException:
        child_started = started or process.pid is not None
        if child_started and process.is_alive():
            _terminate_then_kill(
                process, label=f"state-panel worker {_row_case_id(row)}"
            )
        raise
    finally:
        child_started = started or process.pid is not None
        if not child_started or not process.is_alive():
            output_queue.close()
            output_queue.join_thread()


def _row_case_id(row: Mapping[str, Any]) -> str:
    for key in ("repeatability_case_id", "calibration_case_id"):
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
    raise StatePanelError("panel row lacks a case ID")


def _normalize_panel_result(
    row: Mapping[str, Any],
    message: Mapping[str, Any],
    *,
    manifest_content_hash: str,
) -> dict[str, Any]:
    callback = message.get("result")
    if not isinstance(callback, Mapping) or set(callback) != PANEL_OUTPUT_FIELDS:
        raise StatePanelError("panel result fields differ from the frozen result schema")
    integers = (
        "completed_work_units",
        "completed_simulations",
        "completed_nodes",
        "forward_model_calls",
        "search_wall_ns",
        "overshoot_ns",
        "warmup_steps_completed",
    )
    for field_name in integers:
        value = callback[field_name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise StatePanelError(f"panel result has invalid {field_name}")
    if callback["terminal_status"] not in {"ok", "deadline_no_work"}:
        raise StatePanelError(
            f"panel case {_row_case_id(row)} failed: {callback['terminal_status']}"
        )
    if callback["eligible"] is not True or callback["cleanup_succeeded"] is not True:
        raise StatePanelError("panel case is ineligible or cleanup failed")
    for field_name in ("state_hash", "selected_action_hash"):
        value = callback[field_name]
        if not isinstance(value, str) or len(value) != 64:
            raise StatePanelError(f"panel result has invalid {field_name}")
    budget_mode = str(row["budget_mode"])
    if budget_mode == "fixed_work":
        requested = row.get("requested_work_units")
        if (
            row.get("requested_budget_ns") is not None
            or callback["completed_work_units"] != requested
            or callback["overshoot_ns"] != 0
        ):
            raise StatePanelError("fixed-work panel case is not exact and clock-free")
    elif budget_mode == "wall_clock":
        if row.get("requested_work_units") is not None or not isinstance(
            row.get("requested_budget_ns"), int
        ):
            raise StatePanelError("wall-clock panel case has an invalid stop request")
    else:
        raise StatePanelError(f"unknown panel budget mode: {budget_mode}")
    lifecycle = str(row["lifecycle"])
    history_sha256 = message.get("history_bytes_sha256")
    if lifecycle == "fresh":
        if (
            callback["warmup_steps_completed"] != 0
            or callback["warmup_consumed_sha256"] is not None
            or callback["warmup_replay_sha256"] is not None
            or history_sha256 is not None
        ):
            raise StatePanelError("fresh panel case consumed persistent history")
    elif lifecycle == "persistent":
        if (
            callback["warmup_steps_completed"] != int(row["history_length"])
            or callback["warmup_consumed_sha256"] != row["history_prefix_sha256"]
            or history_sha256 != row["history_prefix_sha256"]
            or _SHA256_RE.fullmatch(str(callback["warmup_replay_sha256"])) is None
        ):
            raise StatePanelError("persistent history replay did not match frozen bytes")
    else:
        raise StatePanelError(f"unknown lifecycle: {lifecycle}")
    if message.get("state_bytes_sha256") != row["state_artifact_sha256"]:
        raise StatePanelError("worker did not consume the frozen state bytes")
    result: dict[str, Any] = {
        "schema_version": "state-panel-result-1.0.0",
        "case_id": _row_case_id(row),
        "manifest_content_hash": manifest_content_hash,
        "schedule_row": dict(row),
        "state_artifact_sha256": message["state_bytes_sha256"],
        "history_prefix_sha256": history_sha256,
        "budget_mode": budget_mode,
        "requested_budget_ns": row.get("requested_budget_ns"),
        "requested_work_units": row.get("requested_work_units"),
        **dict(callback),
        "observed_worker": dict(message["runtime"]),
    }
    result["artifact_sha256"] = hash_json(result)
    return result


def _infrastructure_panel_result(
    row: Mapping[str, Any], manifest_content_hash: str, error: str
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": "state-panel-result-1.0.0",
        "case_id": _row_case_id(row),
        "manifest_content_hash": manifest_content_hash,
        "schedule_row": dict(row),
        "state_artifact_sha256": row["state_artifact_sha256"],
        "history_prefix_sha256": (
            row.get("history_prefix_sha256")
            if row.get("lifecycle") == "persistent"
            else None
        ),
        "budget_mode": row["budget_mode"],
        "requested_budget_ns": row.get("requested_budget_ns"),
        "requested_work_units": row.get("requested_work_units"),
        "terminal_status": "infrastructure_error",
        "eligible": False,
        "completed_work_units": 0,
        "completed_simulations": 0,
        "completed_nodes": 0,
        "forward_model_calls": 0,
        "search_wall_ns": 0,
        "overshoot_ns": 0,
        "state_hash": row["state_artifact_sha256"],
        "selected_action_hash": "0" * 64,
        "cleanup_succeeded": False,
        "warmup_steps_completed": 0,
        "warmup_consumed_sha256": None,
        "warmup_replay_sha256": None,
        "observed_worker": None,
        "error": error,
    }
    result["artifact_sha256"] = hash_json(result)
    return result


def synthetic_panel_entrypoint(
    row: Mapping[str, Any],
    state_bytes: bytes,
    history_bytes: bytes | None,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Deterministic test-only work boundary over opaque captured bytes."""

    if payload.get("fail_case_id") == _row_case_id(row):
        raise RuntimeError("synthetic requested failure")
    if row["budget_mode"] == "fixed_work":
        completed = int(row["requested_work_units"])
        search_wall_ns = completed * int(payload.get("unit_ns", 10))
    else:
        budget = int(row["requested_budget_ns"])
        unit_ns = max(1, int(payload.get("unit_ns", 10)))
        completed = budget // unit_ns
        search_wall_ns = budget
    history_sha256 = None if history_bytes is None else sha256_bytes(history_bytes)
    warmups = 0 if history_bytes is None else int(row.get("history_length", 0))
    return {
        "terminal_status": "ok" if completed else "deadline_no_work",
        "eligible": True,
        "completed_work_units": completed,
        "completed_simulations": completed,
        "completed_nodes": completed,
        "forward_model_calls": completed * 2,
        "search_wall_ns": search_wall_ns,
        "overshoot_ns": 0,
        "state_hash": sha256_bytes(state_bytes),
        "selected_action_hash": hash_json(
            {
                "state": state_bytes.hex(),
                "agent_seed": row["agent_seed"],
                "warmup": history_sha256,
            }
        ),
        "cleanup_succeeded": True,
        "warmup_steps_completed": warmups,
        "warmup_consumed_sha256": history_sha256,
        "warmup_replay_sha256": (
            None
            if history_bytes is None
            else hash_json(
                {
                    "history_sha256": history_sha256,
                    "history_length": warmups,
                    "agent_seed": row["history_seed"],
                }
            )
        ),
    }


def _validate_pokemon_panel_payload(payload: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "adapter_configs",
        "artifact_files",
        "artifact_sha256",
        "persistent_sequence_length",
        "warmup_work_by_agent",
        "instrumentation_enabled",
    }
    if set(payload) != required or payload.get("schema_version") != (
        "pokemon-state-panel-runtime-1.0.0"
    ):
        raise StatePanelError("Pokémon state-panel runtime payload differs from schema")
    configs = payload.get("adapter_configs")
    warmup = payload.get("warmup_work_by_agent")
    if not isinstance(configs, Mapping) or not configs:
        raise StatePanelError("Pokémon state-panel runtime has no adapter configs")
    if not isinstance(warmup, Mapping) or set(warmup) != set(configs):
        raise StatePanelError("warm-up work counts differ from adapter IDs")
    for agent_id, count in warmup.items():
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
            raise StatePanelError(f"invalid persistent warm-up work for {agent_id}")
    bound = payload.get("persistent_sequence_length")
    if isinstance(bound, bool) or not isinstance(bound, int) or bound <= 0:
        raise StatePanelError("persistent sequence bound must be positive")
    if payload.get("instrumentation_enabled") is not True:
        raise StatePanelError("scientific state-panel work counters must be enabled")
    artifact_files = payload.get("artifact_files")
    artifact_hashes = payload.get("artifact_sha256")
    required_artifacts = {
        "engine_binary",
        "engine_source",
        "hero_deck",
        "hero_model",
        "opponent_deck",
        "opponent_model",
    }
    if (
        not isinstance(artifact_files, Mapping)
        or not isinstance(artifact_hashes, Mapping)
        or set(artifact_files) != required_artifacts
        or set(artifact_hashes) != required_artifacts
    ):
        raise StatePanelError("Pokémon panel artifact ledger differs from schema")
    for name in sorted(required_artifacts):
        expected = _require_sha256(artifact_hashes[name], f"panel {name} hash")
        if hash_file(Path(str(artifact_files[name])).resolve()) != expected:
            raise StatePanelError(f"Pokémon panel {name} hash mismatch")

    from .adapters.pokemon import PokemonAdapterConfig

    expected_paths = {
        "seeded_engine_path": Path(str(artifact_files["engine_binary"])).resolve(),
        "hero_deck_path": Path(str(artifact_files["hero_deck"])).resolve(),
        "hero_model_path": Path(str(artifact_files["hero_model"])).resolve(),
        "opponent_deck_path": Path(str(artifact_files["opponent_deck"])).resolve(),
        "opponent_model_path": Path(str(artifact_files["opponent_model"])).resolve(),
    }
    algorithms = {
        "one_ply_value_v1": "one_ply_value",
        "flat_rollout_v1": "flat_rollout",
        "puct_tree_v1": "puct_tree",
    }
    if set(configs) != set(algorithms):
        raise StatePanelError("Pokémon state panel requires exactly three frozen agents")
    for agent_id, raw_config in configs.items():
        if not isinstance(raw_config, Mapping):
            raise StatePanelError(f"adapter config for {agent_id} is not a mapping")
        config = PokemonAdapterConfig(**dict(raw_config))
        config.validate()
        if config.agent_id != agent_id or config.algorithm != algorithms.get(agent_id):
            raise StatePanelError(f"adapter identity differs for {agent_id}")
        for field_name, expected_path in expected_paths.items():
            if Path(str(getattr(config, field_name))).resolve() != expected_path:
                raise StatePanelError(
                    f"adapter {agent_id} path differs from frozen {field_name}"
                )
        if config.initialize_engine:
            raise StatePanelError(
                f"adapter {agent_id} must reuse the child-level engine initialization"
            )


def pokemon_panel_entrypoint(
    row: Mapping[str, Any],
    state_bytes: bytes,
    history_bytes: bytes | None,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Execute frozen warm-ups and one target decision in one isolated child.

    Persistent rows recreate the predeclared pseudo-sequence prefix in the
    same process using fixed work.  The target state is always the exact
    ``raw_state`` loaded from the frozen file; no serializer is invoked.
    """

    _validate_pokemon_panel_payload(payload)
    state = _load_frozen_capture_bytes(
        state_bytes,
        expected_sha256=str(row["state_artifact_sha256"]),
    )
    if state.state_id != row.get("state_id") or state.source_game_id != row.get(
        "source_game_id"
    ):
        raise StatePanelError("frozen state identity differs from panel row")
    configs = payload["adapter_configs"]
    agent_id = str(row["agent_id"])
    if agent_id not in configs:
        raise StatePanelError(f"panel row references unknown agent {agent_id}")
    from .adapters.native_backend import SeededGameBackend
    from .adapters.pokemon import PokemonAdapterConfig, PokemonSearchAdapter

    # Exactly one explicit GameInitialize happens before a search config whose
    # initialize_engine flag is frozen false.  The same game backend is then
    # reused for source-path reconstruction.
    game_backend = SeededGameBackend(str(payload["artifact_files"]["engine_binary"]))
    adapter = PokemonSearchAdapter(PokemonAdapterConfig(**dict(configs[agent_id])))
    lifecycle = str(row["lifecycle"])
    history_sha256: str | None = None
    history_length = 0
    warmup_replay_sha256: str | None = None
    if lifecycle == "fresh":
        if history_bytes is not None:
            raise StatePanelError("fresh panel callback received history bytes")
    elif lifecycle == "persistent":
        if history_bytes is None:
            raise StatePanelError("persistent panel callback lacks history bytes")
        history_sha256 = sha256_bytes(history_bytes)
        if history_sha256 != row.get("history_prefix_sha256"):
            raise StatePanelError("persistent history whole-file hash mismatch")
        history = _load_history_artifact_bytes(history_bytes, row=row)
        history_length = int(history["history_length"])
        bound = int(payload["persistent_sequence_length"])
        if history_length >= bound or history_length != int(row["sequence_index"]):
            raise StatePanelError("persistent history escaped the frozen K bound/slot")
        completed, warmup_replay_sha256 = _replay_native_persistent_history(
            adapter,
            state,
            history,
            row=row,
            payload=payload,
            game_backend=game_backend,
        )
        if completed != history_length:
            raise StatePanelError("persistent warm-up count did not reconcile")
    else:
        raise StatePanelError(f"unknown panel lifecycle: {lifecycle}")

    if row["budget_mode"] == "fixed_work":
        stop = FixedWorkStop(int(row["requested_work_units"]))
    elif row["budget_mode"] == "wall_clock":
        stop = WallClockStop(int(row["requested_budget_ns"]), time.monotonic_ns)
    else:
        raise StatePanelError("unknown state-panel stop mode")
    context = CaseContext(
        case_id=_row_case_id(row),
        block_id=str(row.get("inference_unit_id", row.get("block_id", row["state_id"]))),
        decision_index=0,
        load_condition=str(row["load_condition"]),
        lifecycle=lifecycle,
        lifecycle_id=str(row.get("session_id", _row_case_id(row))),
        process_instance_id=str(row.get("process_instance_id", _row_case_id(row))),
        sequence_index=int(row.get("sequence_index", 0)),
        load_batch_id=str(row.get("load_batch_id", "calibration")),
        agent_seed=int(row["agent_seed"]),
        instrumentation_enabled=True,
    )
    decision = run_decision(adapter, state.raw_state, stop, context)
    return {
        "terminal_status": decision.terminal_status,
        "eligible": decision.terminal_status in {"ok", "deadline_no_work"},
        "completed_work_units": decision.completed_work_units,
        "completed_simulations": decision.completed_simulations,
        "completed_nodes": decision.completed_nodes,
        "forward_model_calls": decision.forward_model_calls,
        "search_wall_ns": decision.search_wall_ns,
        "overshoot_ns": decision.overshoot_ns,
        "state_hash": decision.state_hash,
        "selected_action_hash": decision.selected_action_hash,
        "cleanup_succeeded": decision.cleanup_succeeded,
        "warmup_steps_completed": history_length,
        "warmup_consumed_sha256": history_sha256,
        "warmup_replay_sha256": warmup_replay_sha256,
    }


def _capture_public_state(raw_state: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in raw_state.items() if key != "search_begin_input"}


def _replay_native_persistent_history(
    adapter: Any,
    state: CapturedDecisionState,
    history: Mapping[str, Any],
    *,
    row: Mapping[str, Any],
    payload: Mapping[str, Any],
    game_backend: Any,
) -> tuple[int, str]:
    """Reconstruct and verify the anchor path, warming search at prior eligible states."""

    from cg.api import SelectContext, to_observation_class

    from .game import FixedAnchorAgent, _combination_count, _forced_order

    artifacts = payload["artifact_files"]
    engine = game_backend
    anchor = FixedAnchorAgent(
        str(artifacts["opponent_deck"]),
        str(artifacts["opponent_model"]),
    )
    battle_ptr = 0
    warmup_index = 0
    warmup_records: list[dict[str, Any]] = []
    warmup_work = int(payload["warmup_work_by_agent"][str(row["agent_id"])])
    try:
        battle_ptr, raw = engine.start(
            anchor.deck,
            anchor.deck,
            int(state.source_environment_seed),
        )
        for expected_index, frozen_step in enumerate(history["history_prefix"]):
            if not isinstance(frozen_step, Mapping) or set(frozen_step) != {
                "decision_index",
                "acting_seat",
                "public_state_hash",
                "action",
            }:
                raise StatePanelError("frozen gameplay-history row differs from schema")
            observation = to_observation_class(raw)
            current = observation.current
            select = observation.select
            if select is None:
                raise StatePanelError("reconstructed history produced no selection")
            acting_seat = None if current is None else int(current.yourIndex)
            if (
                frozen_step.get("decision_index") != expected_index
                or frozen_step.get("acting_seat") != acting_seat
                or frozen_step.get("public_state_hash")
                != hash_json(_capture_public_state(raw))
            ):
                raise StatePanelError("reconstructed public gameplay history changed")
            possible = _combination_count(
                len(select.option), int(select.minCount), int(select.maxCount)
            )
            forced_order = select.context == SelectContext.IS_FIRST
            if possible > 1 and not forced_order:
                if warmup_index >= state.target_eligible_index:
                    raise StatePanelError("history contains the measured target or later state")
                warmup_seed = derive_u32(
                    int(row["history_seed"]),
                    "state-panel-persistent-warmup",
                    warmup_index,
                    frozen_step["public_state_hash"],
                )
                warmup_context = CaseContext(
                    case_id=f"{_row_case_id(row)}-warmup-{warmup_index:02d}",
                    block_id=str(
                        row.get("inference_unit_id", row.get("block_id", row["state_id"]))
                    ),
                    decision_index=warmup_index,
                    load_condition=str(row["load_condition"]),
                    lifecycle="persistent_warmup",
                    lifecycle_id=str(row.get("session_id", _row_case_id(row))),
                    process_instance_id=str(
                        row.get("process_instance_id", _row_case_id(row))
                    ),
                    sequence_index=warmup_index,
                    load_batch_id=str(row.get("load_batch_id", "state-panel-warmup")),
                    agent_seed=warmup_seed,
                    instrumentation_enabled=True,
                )
                warmup = run_decision(
                    adapter,
                    raw,
                    FixedWorkStop(warmup_work),
                    warmup_context,
                )
                for field_name, digest in (
                    ("state_hash", warmup.state_hash),
                    ("selected_action_hash", warmup.selected_action_hash),
                ):
                    _require_sha256(digest, f"warm-up {field_name}")
                if (
                    warmup.terminal_status != "ok"
                    or warmup.completed_work_units != warmup_work
                    or not warmup.cleanup_succeeded
                ):
                    raise StatePanelError(
                        f"persistent warm-up {warmup_index} failed: "
                        f"{warmup.terminal_status}"
                    )
                warmup_records.append(
                    {
                        "warmup_index": warmup_index,
                        "public_state_hash": frozen_step["public_state_hash"],
                        "agent_seed_hash": warmup.agent_seed_hash,
                        "state_hash": warmup.state_hash,
                        "selected_action_hash": warmup.selected_action_hash,
                        "requested_work_units": warmup_work,
                        "completed_work_units": warmup.completed_work_units,
                        "completed_simulations": warmup.completed_simulations,
                        "completed_nodes": warmup.completed_nodes,
                        "forward_model_calls": warmup.forward_model_calls,
                        "terminal_status": warmup.terminal_status,
                        "cleanup_succeeded": warmup.cleanup_succeeded,
                    }
                )
                warmup_index += 1
            expected_action = (
                _forced_order(select, state.source_physical_seat, state.source_play_order)
                if forced_order
                else anchor(raw)
            )
            if frozen_step.get("action") != list(expected_action):
                raise StatePanelError("reconstructed anchor action changed")
            raw = engine.select(battle_ptr, expected_action)
        if warmup_index != state.target_eligible_index:
            raise StatePanelError("reconstructed eligible ordinal differs from frozen target")
        if hash_json(_capture_public_state(raw)) != state.public_semantic_hash:
            raise StatePanelError("reconstructed target public state changed")
        # Deliberately discard ``raw`` here.  The target measurement below
        # reuses state.raw_state from the one frozen artifact, including its
        # exact opaque search_begin_input bytes.
        return warmup_index, hash_json(warmup_records)
    finally:
        if battle_ptr:
            engine.finish(battle_ptr)


def _validate_runtime_preflight(runtime: PanelRuntime) -> None:
    runtime.validate()
    if runtime.require_linux_affinity and platform.system() != "Linux":
        raise StatePanelError("scientific state-panel execution requires Linux affinity")
    if not runtime.test_mode:
        from training.azure_guard import is_azure_host

        if not is_azure_host():
            raise StatePanelError(
                "scientific state-panel execution requires an already-authorized Azure host"
            )
        observed_env = {key: os.environ.get(key) for key in runtime.thread_env}
        if observed_env != runtime.thread_env:
            raise StatePanelError("scientific state-panel thread environment is not active")
        observed_platform = {
            "system": platform.system(),
            "machine": platform.machine(),
        }
        if observed_platform != runtime.platform_expectations:
            raise StatePanelError("scientific state-panel platform differs from run config")


def _validate_selection_ledger_for_manifest(
    manifest_path: str | Path,
    observed_manifest_sha256: str,
    runtime: PanelRuntime,
) -> str:
    observed = validate_disjoint_selection_banks(
        runtime.selection_bank_files,
        runtime.selection_bank_sha256,
        required_banks=runtime.required_selection_banks,
    )
    manifest_resolved = Path(manifest_path).resolve()
    matching: list[str] = []
    for name, path in runtime.selection_bank_files.items():
        wrapper, _ = _load_canonical_json(
            path,
            expected_file_sha256=runtime.selection_bank_sha256[name],
        )
        if (
            Path(str(wrapper["execution_manifest_path"])).resolve() == manifest_resolved
            and wrapper.get("execution_manifest_file_sha256") == observed_manifest_sha256
        ):
            matching.append(name)
    if len(matching) != 1 or observed.get(matching[0]) != runtime.selection_bank_sha256[
        matching[0]
    ]:
        raise StatePanelError("current manifest is not bound once in the selection-bank ledger")
    return matching[0]


def validate_repeatability_execution_inputs(
    manifest_path: str | Path,
    *,
    expected_manifest_sha256: str,
    state_files: Mapping[str, str | Path],
    history_files: Mapping[str, str | Path],
    resource_profile_files: Mapping[str, str | Path],
    runtime: PanelRuntime,
) -> dict[str, Any]:
    """Validate the complete frozen repeatability execution contract, read-only."""

    runtime.validate()
    manifest, observed_manifest_hash = _load_canonical_json(
        manifest_path,
        expected_file_sha256=expected_manifest_sha256,
    )
    validate_repeatability_manifest(manifest)
    if manifest.get("phase") in {"pilot", "final"}:
        raise StatePanelError("pilot/final manifests cannot route into the state panel")
    envelopes = list(manifest["config"]["envelopes"])
    cells = {
        (item["budget_mode"], item["load_condition"], item["lifecycle"])
        for item in envelopes
    }
    required_cells = {
        (budget, load, lifecycle)
        for budget in ("wall_clock", "fixed_work")
        for load in ("idle", "loaded")
        for lifecycle in ("fresh", "persistent")
    }
    if len(envelopes) != 8 or cells != required_cells:
        raise StatePanelError("repeatability execution requires all eight frozen envelopes")
    state_bank_name = _validate_selection_ledger_for_manifest(
        manifest_path, observed_manifest_hash, runtime
    )
    states = list(manifest["states"])
    state_ids = {str(state["state_id"]) for state in states}
    if set(state_files) != state_ids or set(history_files) != state_ids:
        raise StatePanelError("state/history file mappings differ from panel state inventory")
    resolved_states: dict[str, Path] = {}
    resolved_histories: dict[str, Path] = {}
    state_hashes: set[str] = set()
    for state in states:
        state_id = str(state["state_id"])
        state_hash = str(state["state_artifact_sha256"])
        if state_hash in state_hashes:
            raise StatePanelError("repeatability state artifacts are not unique")
        state_hashes.add(state_hash)
        resolved_states[state_id] = _validate_frozen_capture_file(
            state_files[state_id],
            state_hash,
            state_id=state_id,
            source_game_id=str(state["source_game_id"]),
            test_mode=runtime.test_mode,
        )
        resolved_histories[state_id] = _validate_state_file(
            history_files[state_id],
            str(state["history_prefix_sha256"]),
            "persistent-history",
        )
        if int(state["history_length"]) > 0 and resolved_histories[state_id].stat().st_size == 0:
            raise StatePanelError("nonzero frozen history has no bytes")
        if not runtime.test_mode:
            _load_history_artifact_bytes(
                resolved_histories[state_id].read_bytes(), row=state
            )
    envelope_ids = {str(envelope["envelope_id"]) for envelope in envelopes}
    if set(resource_profile_files) != envelope_ids:
        raise StatePanelError("resource-profile files differ from the eight envelope IDs")
    profiles: dict[str, FrozenResourceProfile] = {}
    representative_row = {
        str(row["envelope_id"]): row for row in manifest["rows"]
    }
    for envelope in envelopes:
        envelope_id = str(envelope["envelope_id"])
        profiles[envelope_id] = _load_resource_profile(
            resource_profile_files[envelope_id],
            str(envelope["resource_profile_sha256"]),
            row=representative_row[envelope_id],
            runtime=runtime,
        )
    if not runtime.test_mode:
        payload = runtime.entrypoint_payload
        if set(payload["adapter_configs"]) != set(manifest["config"]["agents"]):
            raise StatePanelError("panel adapters differ from manifest agents")
        if int(payload["persistent_sequence_length"]) != int(
            manifest["config"]["persistent_sequence_length"]
        ):
            raise StatePanelError("panel persistent K differs from manifest")
    return {
        "manifest": manifest,
        "manifest_file_sha256": observed_manifest_hash,
        "state_files": resolved_states,
        "history_files": resolved_histories,
        "profiles": profiles,
        "state_bank_name": state_bank_name,
    }


def validate_calibration_execution_inputs(
    manifest_path: str | Path,
    *,
    expected_manifest_sha256: str,
    state_files: Mapping[str, str | Path],
    resource_profile_file: str | Path,
    resource_profile_sha256: str,
    runtime: PanelRuntime,
) -> dict[str, Any]:
    """Validate the outcome-blind idle/fresh calibration execution contract."""

    runtime.validate()
    manifest, observed_manifest_hash = _load_canonical_json(
        manifest_path,
        expected_file_sha256=expected_manifest_sha256,
    )
    validate_calibration_manifest(manifest)
    if manifest.get("phase") in {"pilot", "final"}:
        raise StatePanelError("pilot/final manifests cannot route into calibration")
    state_bank_name = _validate_selection_ledger_for_manifest(
        manifest_path, observed_manifest_hash, runtime
    )
    states = list(manifest["states"])
    state_ids = {str(state["state_id"]) for state in states}
    if set(state_files) != state_ids:
        raise StatePanelError("state-file mapping differs from calibration inventory")
    resolved_states: dict[str, Path] = {}
    hashes: set[str] = set()
    for state in states:
        state_id = str(state["state_id"])
        state_hash = str(state["state_artifact_sha256"])
        if state_hash in hashes:
            raise StatePanelError("calibration state artifacts are not unique")
        hashes.add(state_hash)
        resolved_states[state_id] = _validate_frozen_capture_file(
            state_files[state_id],
            state_hash,
            state_id=state_id,
            source_game_id=str(state["source_game_id"]),
            test_mode=runtime.test_mode,
        )
    profile_value, _ = _load_canonical_json(
        resource_profile_file,
        expected_file_sha256=resource_profile_sha256,
    )
    profile_data = dict(profile_value)
    profile_data["target_cpus"] = tuple(profile_data.get("target_cpus", ()))
    profile = FrozenResourceProfile(**profile_data)
    profile.validate()
    if (
        profile.budget_mode != "wall_clock"
        or profile.load_condition != "idle"
        or profile.lifecycle != "fresh"
        or profile.target_cpus != runtime.target_cpus
        or profile.worker_count != 0
    ):
        raise StatePanelError("calibration resource profile escaped idle/fresh/wall-clock")
    if not runtime.test_mode and set(runtime.entrypoint_payload["adapter_configs"]) != set(
        manifest["config"]["agents"]
    ):
        raise StatePanelError("calibration adapters differ from manifest agents")
    return {
        "manifest": manifest,
        "manifest_file_sha256": observed_manifest_hash,
        "state_files": resolved_states,
        "profile": profile,
        "resource_profile_file_sha256": resource_profile_sha256,
        "state_bank_name": state_bank_name,
    }


def _without_hash(value: Mapping[str, Any], field_name: str) -> dict[str, Any]:
    payload = dict(value)
    payload.pop(field_name, None)
    return payload


def _validate_panel_result_against_row(
    result: Mapping[str, Any],
    row: Mapping[str, Any],
    *,
    manifest_content_hash: str,
) -> None:
    if result.get("schema_version") != "state-panel-result-1.0.0":
        raise StatePanelError("state-panel result has an unknown schema")
    if (
        result.get("case_id") != _row_case_id(row)
        or result.get("manifest_content_hash") != manifest_content_hash
        or result.get("schedule_row") != dict(row)
    ):
        raise StatePanelError("state-panel result provenance differs from schedule")
    supplied_hash = _require_sha256(result.get("artifact_sha256"), "result artifact hash")
    if supplied_hash != hash_json(_without_hash(result, "artifact_sha256")):
        raise StatePanelError("state-panel result artifact hash mismatch")
    status = result.get("terminal_status")
    if status not in {"ok", "deadline_no_work", "infrastructure_error"}:
        raise StatePanelError(f"unknown state-panel terminal status: {status}")
    if status == "infrastructure_error":
        if result.get("eligible") is not False or result.get("cleanup_succeeded") is not False:
            raise StatePanelError("infrastructure result carries usable scientific flags")
        return
    if result.get("eligible") is not True or result.get("cleanup_succeeded") is not True:
        raise StatePanelError("scientific panel result is not eligible/clean")
    worker = result.get("observed_worker")
    if not isinstance(worker, Mapping):
        raise StatePanelError("scientific panel result lacks observed worker evidence")
    if worker.get("spawned_process_id") != worker.get("observed_process_id"):
        raise StatePanelError("scientific panel worker PID evidence changed")
    if result.get("state_artifact_sha256") != row.get("state_artifact_sha256"):
        raise StatePanelError("scientific panel result consumed another state artifact")
    if row.get("budget_mode") == "fixed_work" and (
        result.get("completed_work_units") != row.get("requested_work_units")
        or result.get("overshoot_ns") != 0
    ):
        raise StatePanelError("fixed-work scientific result is not exact")


def validate_panel_terminal_accounting(
    manifest: Mapping[str, Any],
    results: Sequence[Mapping[str, Any]],
    *,
    require_complete: bool,
) -> dict[str, int]:
    scheduled = {_row_case_id(row): row for row in manifest["rows"]}
    observed = Counter(str(result.get("case_id")) for result in results)
    duplicates = sorted(case_id for case_id, count in observed.items() if count != 1)
    unknown = sorted(set(observed) - set(scheduled))
    missing = sorted(set(scheduled) - set(observed))
    if duplicates or unknown or (require_complete and missing):
        raise StatePanelError(
            "state-panel terminal accounting failure: "
            f"duplicates={duplicates[:5]}, unknown={unknown[:5]}, missing={missing[:5]}"
        )
    for result in results:
        row = scheduled.get(str(result.get("case_id")))
        if row is None:
            raise StatePanelError("state-panel result references an unknown case")
        _validate_panel_result_against_row(
            result,
            row,
            manifest_content_hash=str(manifest["content_hash"]),
        )
    statuses = Counter(str(result["terminal_status"]) for result in results)
    return {
        "scheduled_cases": len(scheduled),
        "terminal_cases": len(results),
        "scientific_cases": statuses["ok"] + statuses["deadline_no_work"],
        "infrastructure_error_cases": statuses["infrastructure_error"],
    }


def _assert_persistent_warmup_pairing(
    rows: Sequence[Mapping[str, Any]], results: Sequence[Mapping[str, Any]]
) -> None:
    row_by_case = {_row_case_id(row): row for row in rows}
    hashes: dict[tuple[str, str, str, int], dict[str, str]] = defaultdict(dict)
    for result in results:
        row = row_by_case[str(result["case_id"])]
        if row.get("lifecycle") != "persistent":
            continue
        digest = _require_sha256(
            result.get("warmup_replay_sha256"), "persistent warm-up replay hash"
        )
        key = (
            str(row["state_id"]),
            str(row["agent_id"]),
            str(row["budget_mode"]),
            int(row["repeat_index"]),
        )
        condition = str(row["load_condition"])
        if condition in hashes[key]:
            raise StatePanelError("persistent warm-up pairing repeats a load condition")
        hashes[key][condition] = digest
    for key, by_condition in hashes.items():
        if set(by_condition) != {"idle", "loaded"} or len(set(by_condition.values())) != 1:
            raise StatePanelError(
                f"persistent warm-up replay differs across paired load envelopes: {key}"
            )


def _repeatability_periods(
    batch_id: str, batch_rows: Sequence[Mapping[str, Any]]
) -> list[list[dict[str, Any]]]:
    ordered = [dict(row) for row in sorted(batch_rows, key=lambda item: int(item["execution_index"]))]
    periods: list[list[dict[str, Any]]] = []
    for row in ordered:
        if not periods or periods[-1][0]["load_condition"] != row["load_condition"]:
            periods.append([])
        periods[-1].append(row)
    if len(periods) != 2 or {period[0]["load_condition"] for period in periods} != {
        "idle",
        "loaded",
    }:
        raise StatePanelError(f"repeatability batch {batch_id} lacks two contiguous periods")
    declared = str(ordered[0]["load_period_order"])
    observed = "_then_".join(str(period[0]["load_condition"]) for period in periods)
    if declared != observed:
        raise StatePanelError(f"repeatability batch {batch_id} period order changed")
    return periods


def _ordered_execution_groups(
    manifest: Mapping[str, Any], *, kind: str
) -> list[tuple[str, list[dict[str, Any]], list[list[dict[str, Any]]]]]:
    ordered = sorted(manifest["rows"], key=lambda row: int(row["execution_index"]))
    if kind == "calibration":
        return [
            (
                str(row["calibration_case_id"]),
                [dict(row)],
                [[dict(row)]],
            )
            for row in ordered
        ]
    by_batch: dict[str, list[dict[str, Any]]] = defaultdict(list)
    order: list[str] = []
    for row in ordered:
        batch_id = str(row["load_batch_id"])
        if batch_id not in by_batch:
            order.append(batch_id)
        by_batch[batch_id].append(dict(row))
    return [
        (batch_id, by_batch[batch_id], _repeatability_periods(batch_id, by_batch[batch_id]))
        for batch_id in order
    ]


def _episode_payload(
    *,
    group_id: str,
    period_index: int,
    rows: Sequence[Mapping[str, Any]],
    resource_profile_sha256: Sequence[str],
    metadata: Mapping[str, Any],
    status: str,
    error: str | None,
    test_mode: bool,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": "state-panel-resource-episode-1.0.0",
        "group_id": group_id,
        "period_id": f"{group_id}-period-{period_index:02d}",
        "period_index": period_index,
        "load_condition": rows[0]["load_condition"],
        "case_ids": [_row_case_id(row) for row in rows],
        "resource_profile_sha256": sorted(set(resource_profile_sha256)),
        "status": status,
        "error": error,
        "test_mode": test_mode,
        "resource_metadata": dict(metadata),
    }
    value["artifact_sha256"] = hash_json(value)
    return value


def _invalid_episode(
    *,
    group_id: str,
    period_index: int,
    rows: Sequence[Mapping[str, Any]],
    resource_profile_sha256: Sequence[str],
    error: str,
    test_mode: bool,
) -> dict[str, Any]:
    metadata = {
        "schema_version": "resource-episode-1.0.0",
        "load_batch_id": group_id,
        "load_seed": rows[0].get("load_seed"),
        "profile": {
            "condition": rows[0]["load_condition"],
            "worker_count": None,
            "target_cpus": None,
        },
        "before": system_snapshot(),
        "after": system_snapshot(),
        "workers": [],
        "benchmark_workers": [],
        "cleanup_succeeded": False,
        "cleanup_errors": [error],
    }
    return _episode_payload(
        group_id=group_id,
        period_index=period_index,
        rows=rows,
        resource_profile_sha256=resource_profile_sha256,
        metadata=metadata,
        status="infrastructure_invalid",
        error=error,
        test_mode=test_mode,
    )


def _mark_episode_invalid(episode: Mapping[str, Any], error: str) -> dict[str, Any]:
    value = dict(episode)
    value["status"] = "infrastructure_invalid"
    value["error"] = error
    value["artifact_sha256"] = hash_json(_without_hash(value, "artifact_sha256"))
    return value


def _validate_panel_episode(
    episode: Mapping[str, Any],
    *,
    group_id: str,
    period_index: int,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    if episode.get("schema_version") != "state-panel-resource-episode-1.0.0":
        raise StatePanelError("state-panel episode has an unknown schema")
    supplied = _require_sha256(episode.get("artifact_sha256"), "episode artifact hash")
    if supplied != hash_json(_without_hash(episode, "artifact_sha256")):
        raise StatePanelError("state-panel episode artifact hash mismatch")
    if (
        episode.get("group_id") != group_id
        or episode.get("period_id") != f"{group_id}-period-{period_index:02d}"
        or episode.get("period_index") != period_index
        or episode.get("load_condition") != rows[0]["load_condition"]
        or episode.get("case_ids") != [_row_case_id(row) for row in rows]
    ):
        raise StatePanelError("state-panel episode differs from scheduled period")
    status = episode.get("status")
    metadata = episode.get("resource_metadata")
    if status not in {"scientific_complete", "infrastructure_invalid"} or not isinstance(
        metadata, Mapping
    ):
        raise StatePanelError("state-panel episode status/metadata is invalid")
    if status == "scientific_complete":
        if metadata.get("cleanup_succeeded") is not True:
            raise StatePanelError("scientific resource episode cleanup failed")
        workers = metadata.get("benchmark_workers")
        if not isinstance(workers, list) or len(workers) != len(rows):
            raise StatePanelError("resource episode worker accounting is incomplete")
        if episode.get("test_mode") is not True:
            profile = metadata.get("profile")
            target_cpus = metadata.get("benchmark_target_cpus")
            if (
                not isinstance(profile, Mapping)
                or profile.get("condition") != rows[0]["load_condition"]
                or not isinstance(target_cpus, (list, tuple))
                or not target_cpus
                or metadata.get("orchestrator_affinity_applied") is not True
                or metadata.get("orchestrator_observed_affinity_latest")
                != metadata.get("orchestrator_target_cpus")
                or metadata.get("cleanup_errors") != []
            ):
                raise StatePanelError("scientific resource episode affinity/cleanup evidence failed")
            for worker in workers:
                if (
                    not isinstance(worker, Mapping)
                    or worker.get("observed_process_id") != worker.get("spawned_process_id")
                    or worker.get("parent_death_kill_armed") is not True
                    or worker.get("observed_affinity") != sorted(target_cpus)
                    or worker.get("exitcode") != 0
                    or not isinstance(worker.get("process_time_ns_delta"), int)
                    or worker.get("process_time_ns_delta") < 0
                ):
                    raise StatePanelError("benchmark-child PID/affinity/CPU evidence failed")
            load_workers = metadata.get("workers")
            if rows[0]["load_condition"] == "idle":
                if load_workers != []:
                    raise StatePanelError("idle episode unexpectedly launched load workers")
            else:
                if not isinstance(load_workers, list) or not load_workers:
                    raise StatePanelError("loaded episode lacks co-runner evidence")
                exitcodes = metadata.get("worker_exitcodes")
                for worker in load_workers:
                    pid = str(worker.get("pid"))
                    if (
                        worker.get("affinity_applied") is not True
                        or worker.get("observed_affinity") != sorted(target_cpus)
                        or not isinstance(worker.get("cpu_ticks_delta"), int)
                        or worker.get("cpu_ticks_delta") <= 0
                        or not isinstance(exitcodes, Mapping)
                        or exitcodes.get(pid) != 0
                    ):
                        raise StatePanelError("loaded co-runner CPU/affinity/exit evidence failed")


class _PanelPeriodFailure(Exception):
    def __init__(
        self,
        error: str,
        results: list[dict[str, Any]],
        episode: dict[str, Any],
    ) -> None:
        super().__init__(error)
        self.error = error
        self.results = results
        self.episode = episode


def _run_panel_period(
    *,
    group_id: str,
    period_index: int,
    rows: Sequence[Mapping[str, Any]],
    profile: LoadProfile,
    resource_profile_sha256: Sequence[str],
    manifest_content_hash: str,
    state_files: Mapping[str, Path],
    history_files: Mapping[str, Path],
    runtime: PanelRuntime,
    load_seed: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    results: list[dict[str, Any]] = []
    envelope = ResourceEnvelope(
        profile,
        load_seed,
        group_id,
        require_affinity=runtime.require_linux_affinity,
    )
    error: str | None = None
    try:
        with envelope:
            for row in rows:
                # Compliance is checked on both sides of every unit, including
                # the final unit in a period.
                envelope.assert_compliant()
                state_id = str(row["state_id"])
                message = _spawn_panel_case(
                    row,
                    state_path=state_files[state_id],
                    history_path=(
                        history_files[state_id]
                        if row["lifecycle"] == "persistent"
                        else None
                    ),
                    runtime=runtime,
                )
                envelope.record_benchmark_worker(dict(message["runtime"]))
                result = _normalize_panel_result(
                    row,
                    message,
                    manifest_content_hash=manifest_content_hash,
                )
                _validate_panel_result_against_row(
                    result,
                    row,
                    manifest_content_hash=manifest_content_hash,
                )
                results.append(result)
                envelope.assert_compliant()
            envelope.assert_compliant(period_complete=True)
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}"
    metadata = dict(envelope.metadata)
    status = "scientific_complete" if error is None else "infrastructure_invalid"
    episode = _episode_payload(
        group_id=group_id,
        period_index=period_index,
        rows=rows,
        resource_profile_sha256=resource_profile_sha256,
        metadata=metadata,
        status=status,
        error=error,
        test_mode=runtime.test_mode,
    )
    if error is not None:
        raise _PanelPeriodFailure(error, results, episode)
    _validate_panel_episode(
        episode,
        group_id=group_id,
        period_index=period_index,
        rows=rows,
    )
    return results, episode


def _validate_commit(commit: Mapping[str, Any]) -> None:
    if commit.get("schema_version") != "state-panel-batch-commit-1.0.0":
        raise StatePanelError("state-panel commit has an unknown schema")
    supplied = _require_sha256(commit.get("content_hash"), "state-panel commit hash")
    if supplied != hash_json(_without_hash(commit, "content_hash")):
        raise StatePanelError("state-panel commit content hash mismatch")
    if commit.get("batch_status") not in {
        "scientific_complete",
        "infrastructure_invalid",
    }:
        raise StatePanelError("state-panel commit has an unknown status")


def _validate_invalid_attempt(attempt: Mapping[str, Any]) -> None:
    if attempt.get("schema_version") != "state-panel-invalid-attempt-1.0.0":
        raise StatePanelError("state-panel invalid attempt has an unknown schema")
    supplied = _require_sha256(attempt.get("content_hash"), "invalid-attempt hash")
    if supplied != hash_json(_without_hash(attempt, "content_hash")):
        raise StatePanelError("state-panel invalid-attempt hash mismatch")


def validate_panel_resume_state(
    manifest: Mapping[str, Any],
    *,
    kind: str,
    results: Sequence[Mapping[str, Any]],
    episodes: Sequence[Mapping[str, Any]],
    commits: Sequence[Mapping[str, Any]],
    invalid_attempts: Sequence[Mapping[str, Any]],
    runtime: PanelRuntime,
) -> set[str]:
    """Accept only whole committed groups; reject every partial/invalid resume."""

    groups = {
        group_id: (rows, periods)
        for group_id, rows, periods in _ordered_execution_groups(manifest, kind=kind)
    }
    result_by_group: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    case_to_group = {
        _row_case_id(row): group_id
        for group_id, (rows, _periods) in groups.items()
        for row in rows
    }
    for result in results:
        case_id = str(result.get("case_id"))
        group_id = case_to_group.get(case_id)
        if group_id is None:
            raise StatePanelError(f"resume result references unknown case {case_id}")
        result_by_group[group_id].append(result)
    episodes_by_group: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for episode in episodes:
        episodes_by_group[str(episode.get("group_id"))].append(episode)
    commits_by_group: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for commit in commits:
        _validate_commit(commit)
        commits_by_group[str(commit.get("group_id"))].append(commit)
    attempts_by_group: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for attempt in invalid_attempts:
        _validate_invalid_attempt(attempt)
        attempts_by_group[str(attempt.get("group_id"))].append(attempt)
    unknown_groups = (
        set(episodes_by_group) | set(commits_by_group) | set(attempts_by_group)
    ) - set(groups)
    if unknown_groups:
        raise StatePanelError(f"resume journal references unknown groups: {sorted(unknown_groups)}")

    complete: set[str] = set()
    for group_id, (rows, periods) in groups.items():
        group_results = result_by_group.get(group_id, [])
        group_episodes = episodes_by_group.get(group_id, [])
        group_commits = commits_by_group.get(group_id, [])
        group_attempts = attempts_by_group.get(group_id, [])
        if not (group_results or group_episodes or group_commits or group_attempts):
            continue
        if (
            len(group_results) != len(rows)
            or len(group_episodes) != len(periods)
            or len(group_commits) != 1
        ):
            raise StatePanelError(
                f"partial state-panel group {group_id}; preserve artifacts and use reserve IDs"
            )
        validate_panel_terminal_accounting(
            {**dict(manifest), "rows": rows},
            group_results,
            require_complete=True,
        )
        ordered_results = sorted(
            group_results, key=lambda result: int(result["schedule_row"]["execution_index"])
        )
        ordered_episodes = sorted(group_episodes, key=lambda episode: int(episode["period_index"]))
        for period_index, (episode, period_rows) in enumerate(zip(ordered_episodes, periods)):
            _validate_panel_episode(
                episode,
                group_id=group_id,
                period_index=period_index,
                rows=period_rows,
            )
        commit = group_commits[0]
        expected_run_hash = runtime.run_config_sha256 if not runtime.test_mode else None
        if (
            commit.get("manifest_content_hash") != manifest["content_hash"]
            or commit.get("run_config_file_sha256") != expected_run_hash
            or commit.get("case_ids") != [_row_case_id(row) for row in rows]
            or commit.get("result_hashes")
            != [result["artifact_sha256"] for result in ordered_results]
            or commit.get("episode_hashes")
            != [episode["artifact_sha256"] for episode in ordered_episodes]
        ):
            raise StatePanelError(f"state-panel commit differs from group {group_id}")
        invalid = commit["batch_status"] == "infrastructure_invalid"
        if invalid != bool(group_attempts) or len(group_attempts) > 1:
            raise StatePanelError(f"invalid-attempt accounting differs for {group_id}")
        expected_result_status = (
            {"infrastructure_error"}
            if invalid
            else {"ok", "deadline_no_work"}
        )
        if not {str(result["terminal_status"]) for result in group_results}.issubset(
            expected_result_status
        ):
            raise StatePanelError(f"result statuses disagree with commit for {group_id}")
        if invalid:
            raise StatePanelError(
                f"state-panel group {group_id} is infrastructure_invalid; "
                "resume requires newly frozen reserve IDs"
            )
        if kind == "repeatability":
            _assert_persistent_warmup_pairing(rows, group_results)
        complete.add(group_id)
    return complete


def _profile_for_period(
    rows: Sequence[Mapping[str, Any]],
    *,
    kind: str,
    prepared: Mapping[str, Any],
) -> tuple[LoadProfile, list[str]]:
    if kind == "calibration":
        return (
            prepared["profile"].to_load_profile(),
            [str(prepared["resource_profile_file_sha256"])],
        )
    profiles = [prepared["profiles"][str(row["envelope_id"])] for row in rows]
    load_profiles = [profile.to_load_profile() for profile in profiles]
    if any(profile != load_profiles[0] for profile in load_profiles[1:]):
        raise StatePanelError("one load period contains incompatible resource controls")
    return load_profiles[0], [str(row["resource_profile_sha256"]) for row in rows]


def _execute_panel(
    prepared: Mapping[str, Any],
    *,
    kind: str,
    output_dir: str | Path,
    runtime: PanelRuntime,
) -> dict[str, Any]:
    manifest = prepared["manifest"]
    if not runtime.execution_enabled:
        raise StatePanelError("state-panel execution is disabled until explicitly enabled")
    _validate_runtime_preflight(runtime)
    if not runtime.test_mode and runtime.authorized_state_bank != prepared.get(
        "state_bank_name"
    ):
        raise StatePanelError(
            "state-panel bank is not explicitly authorized by the frozen run config"
        )
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    results_path = output / "panel_results.jsonl"
    episodes_path = output / "resource_episodes.jsonl"
    commits_path = output / "panel_batch_commits.jsonl"
    invalid_path = output / "invalid_attempts.jsonl"
    results = _read_jsonl(results_path)
    episodes = _read_jsonl(episodes_path)
    commits = _read_jsonl(commits_path)
    invalid_attempts = _read_jsonl(invalid_path)
    complete = validate_panel_resume_state(
        manifest,
        kind=kind,
        results=results,
        episodes=episodes,
        commits=commits,
        invalid_attempts=invalid_attempts,
        runtime=runtime,
    )
    groups = _ordered_execution_groups(manifest, kind=kind)
    empty_histories: dict[str, Path] = {}
    histories = prepared.get("history_files", empty_histories)
    for group_id, rows, periods in groups:
        if group_id in complete:
            continue
        group_results: list[dict[str, Any]] = []
        group_episodes: list[dict[str, Any]] = []
        attempted_results: list[dict[str, Any]] = []
        group_error: str | None = None
        failed_period_index: int | None = None
        for period_index, period_rows in enumerate(periods):
            profile, profile_hashes = _profile_for_period(
                period_rows,
                kind=kind,
                prepared=prepared,
            )
            load_seed = (
                int(period_rows[0]["load_seed"])
                if "load_seed" in period_rows[0]
                else derive_u32(
                    int(manifest["config"]["master_seed"]),
                    "state-panel-calibration-load",
                    group_id,
                )
            )
            try:
                period_results, episode = _run_panel_period(
                    group_id=group_id,
                    period_index=period_index,
                    rows=period_rows,
                    profile=profile,
                    resource_profile_sha256=profile_hashes,
                    manifest_content_hash=str(manifest["content_hash"]),
                    state_files=prepared["state_files"],
                    history_files=histories,
                    runtime=runtime,
                    load_seed=load_seed,
                )
                attempted_results.extend(period_results)
                group_results.extend(period_results)
                group_episodes.append(episode)
            except _PanelPeriodFailure as failure:
                attempted_results.extend(failure.results)
                group_episodes.append(failure.episode)
                group_error = failure.error
                failed_period_index = period_index
                break
        if group_error is not None:
            attempted_episodes = list(group_episodes)
            invalid_attempt: dict[str, Any] = {
                "schema_version": "state-panel-invalid-attempt-1.0.0",
                "group_id": group_id,
                "failed_period_index": failed_period_index,
                "error": group_error,
                "attempted_results": attempted_results,
                "resource_episodes": attempted_episodes,
                "attempted_result_hashes": [
                    result["artifact_sha256"] for result in attempted_results
                ],
                "resource_episode_hashes": [
                    episode["artifact_sha256"] for episode in attempted_episodes
                ],
            }
            invalid_attempt["content_hash"] = hash_json(invalid_attempt)
            _append_jsonl(invalid_path, invalid_attempt)
            group_results = [
                _infrastructure_panel_result(
                    row,
                    str(manifest["content_hash"]),
                    f"atomic state-panel group invalid: {group_error}",
                )
                for row in rows
            ]
            group_episodes = [
                _mark_episode_invalid(group_episodes[index], group_error)
                if index < len(group_episodes)
                else _invalid_episode(
                    group_id=group_id,
                    period_index=index,
                    rows=period_rows,
                    resource_profile_sha256=_profile_for_period(
                        period_rows, kind=kind, prepared=prepared
                    )[1],
                    error=group_error,
                    test_mode=runtime.test_mode,
                )
                for index, period_rows in enumerate(periods)
            ]
        ordered_results = sorted(
            group_results, key=lambda result: int(result["schedule_row"]["execution_index"])
        )
        ordered_episodes = sorted(group_episodes, key=lambda episode: int(episode["period_index"]))
        validate_panel_terminal_accounting(
            {**dict(manifest), "rows": rows},
            ordered_results,
            require_complete=True,
        )
        if kind == "repeatability" and group_error is None:
            _assert_persistent_warmup_pairing(rows, ordered_results)
        for period_index, (episode, period_rows) in enumerate(zip(ordered_episodes, periods)):
            _validate_panel_episode(
                episode,
                group_id=group_id,
                period_index=period_index,
                rows=period_rows,
            )
        for episode in ordered_episodes:
            _append_jsonl(episodes_path, episode)
        for result in ordered_results:
            _append_jsonl(results_path, result)
            results.append(result)
        commit: dict[str, Any] = {
            "schema_version": "state-panel-batch-commit-1.0.0",
            "group_kind": "paired_load_batch" if kind == "repeatability" else "calibration_case",
            "group_id": group_id,
            "manifest_content_hash": manifest["content_hash"],
            "run_config_file_sha256": (
                runtime.run_config_sha256 if not runtime.test_mode else None
            ),
            "batch_status": (
                "scientific_complete"
                if group_error is None
                else "infrastructure_invalid"
            ),
            "case_ids": [_row_case_id(row) for row in rows],
            "result_hashes": [result["artifact_sha256"] for result in ordered_results],
            "episode_hashes": [episode["artifact_sha256"] for episode in ordered_episodes],
        }
        commit["content_hash"] = hash_json(commit)
        _append_jsonl(commits_path, commit)
        if group_error is not None:
            raise StatePanelError(
                f"state-panel stopped after invalid atomic group {group_id}; "
                "preserve artifacts and use newly frozen reserve IDs"
            )
        complete.add(group_id)
    accounting = validate_panel_terminal_accounting(
        manifest,
        results,
        require_complete=True,
    )
    final_complete = validate_panel_resume_state(
        manifest,
        kind=kind,
        results=results,
        episodes=_read_jsonl(episodes_path),
        commits=_read_jsonl(commits_path),
        invalid_attempts=_read_jsonl(invalid_path),
        runtime=runtime,
    )
    if final_complete != {group_id for group_id, _rows, _periods in groups}:
        raise StatePanelError("state-panel ended without every atomic group committed")
    summary: dict[str, Any] = {
        "schema_version": "state-panel-summary-1.0.0",
        "status": "complete",
        "execution_kind": kind,
        "manifest_content_hash": manifest["content_hash"],
        "manifest_file_sha256": prepared["manifest_file_sha256"],
        "run_config_file_sha256": (
            runtime.run_config_sha256 if not runtime.test_mode else None
        ),
        "committed_groups": len(final_complete),
        "resource_episode_count": len(_read_jsonl(episodes_path)),
        "machine": system_snapshot(),
        **accounting,
    }
    summary["content_hash"] = hash_json(summary)
    _write_atomic_json(output / "panel_summary.json", summary)
    if kind == "calibration":
        calibration_records = [
            {
                "calibration_case_id": result["case_id"],
                "agent_id": result["schedule_row"]["agent_id"],
                "state_id": result["schedule_row"]["state_id"],
                "block_id": result["schedule_row"]["block_id"],
                "requested_budget_ns": result["requested_budget_ns"],
                "completed_work_units": result["completed_work_units"],
                "search_wall_ns": result["search_wall_ns"],
                "overshoot_ns": result["overshoot_ns"],
                "terminal_status": result["terminal_status"],
                "eligible": result["eligible"],
            }
            for result in sorted(
                results, key=lambda item: int(item["schedule_row"]["execution_index"])
            )
        ]
        _write_atomic_json(output / "calibration_records.json", {"records": calibration_records})
    return summary


def execute_repeatability_manifest(
    manifest_path: str | Path,
    *,
    expected_manifest_sha256: str,
    state_files: Mapping[str, str | Path],
    history_files: Mapping[str, str | Path],
    resource_profile_files: Mapping[str, str | Path],
    output_dir: str | Path,
    runtime: PanelRuntime,
) -> dict[str, Any]:
    prepared = validate_repeatability_execution_inputs(
        manifest_path,
        expected_manifest_sha256=expected_manifest_sha256,
        state_files=state_files,
        history_files=history_files,
        resource_profile_files=resource_profile_files,
        runtime=runtime,
    )
    return _execute_panel(prepared, kind="repeatability", output_dir=output_dir, runtime=runtime)


def execute_calibration_manifest(
    manifest_path: str | Path,
    *,
    expected_manifest_sha256: str,
    state_files: Mapping[str, str | Path],
    resource_profile_file: str | Path,
    resource_profile_sha256: str,
    output_dir: str | Path,
    runtime: PanelRuntime,
) -> dict[str, Any]:
    prepared = validate_calibration_execution_inputs(
        manifest_path,
        expected_manifest_sha256=expected_manifest_sha256,
        state_files=state_files,
        resource_profile_file=resource_profile_file,
        resource_profile_sha256=resource_profile_sha256,
        runtime=runtime,
    )
    return _execute_panel(prepared, kind="calibration", output_dir=output_dir, runtime=runtime)
