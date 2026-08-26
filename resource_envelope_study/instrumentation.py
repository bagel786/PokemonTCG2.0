"""Fail-closed native Pokémon instrumentation-overhead pilot.

The scientific path compares optional telemetry collection off versus on at an
identical frozen decision state.  Each member of a pair runs in a new spawned
process, under the same idle :class:`ResourceEnvelope`, on the same pinned CPU,
with the same agent seed and exact fixed-work request.  No function in this
module starts or manages an Azure VM.

Pair journals are durable before work starts and after every child result.  A
pair commit is written only after both modes and their resource evidence pass
all checks.  An interrupted or invalid journal is never resumed in place.
"""

from __future__ import annotations

import importlib
import json
import math
import multiprocessing as mp
import os
import platform
import queue
import re
import statistics
import time
import traceback
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .canonical import (
    canonical_json_bytes,
    derive_u32,
    deterministic_shuffle,
    hash_file,
    hash_json,
    sha256_bytes,
)
from .orchestration_guard import arm_parent_death_kill
from .process_safety import stop_process
from .resource_controller import LoadProfile, ResourceEnvelope, system_snapshot


MANIFEST_SCHEMA_VERSION = "pokemon-instrumentation-manifest-1.0.0"
RUN_CONFIG_SCHEMA_VERSION = "pokemon-instrumentation-run-config-1.0.0"
RUNTIME_PAYLOAD_SCHEMA_VERSION = "pokemon-instrumentation-runtime-1.0.0"
ROW_SCHEMA_VERSION = "pokemon-instrumentation-row-1.0.0"
RESULT_SCHEMA_VERSION = "pokemon-instrumentation-result-1.0.0"
EPISODE_SCHEMA_VERSION = "pokemon-instrumentation-resource-episode-1.0.0"
ATTEMPT_SCHEMA_VERSION = "pokemon-instrumentation-attempt-1.0.0"
PAIR_COMMIT_SCHEMA_VERSION = "pokemon-instrumentation-pair-commit-1.0.0"
GATE_REPORT_SCHEMA_VERSION = "pokemon-instrumentation-gate-report-1.0.0"

SCIENTIFIC_ENTRYPOINT = (
    "resource_envelope_study.instrumentation:pokemon_instrumentation_entrypoint"
)
SYNTHETIC_ENTRYPOINT = (
    "resource_envelope_study.instrumentation:synthetic_instrumentation_entrypoint"
)
STUDY_AGENTS = (
    "one_ply_value_v1",
    "flat_rollout_v1",
    "puct_tree_v1",
)
AGENT_ALGORITHMS = {
    "one_ply_value_v1": "one_ply_value",
    "flat_rollout_v1": "flat_rollout",
    "puct_tree_v1": "puct_tree",
}
THREAD_ENV_KEYS = frozenset(
    {
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "PYTHONHASHSEED",
    }
)
ARTIFACT_NAMES = frozenset(
    {
        "engine_binary",
        "engine_source",
        "hero_deck",
        "hero_model",
        "opponent_deck",
        "opponent_model",
    }
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

GATE_SPECIFICATION: dict[str, Any] = {
    "schema_version": "pokemon-instrumentation-gate-specification-1.0.0",
    "source": "PILOT_GATE.md Instrumentation row",
    "minimum_pair_count": 20,
    "pair_order_balance": "exact_AB_BA",
    "throughput_ratio": (
        "instrumentation_on_completed_work_per_ns/"
        "instrumentation_off_completed_work_per_ns"
    ),
    "interval_method": "paired_log_ratio_student_t_two_sided_90_percent",
    "confidence_level": 0.90,
    "go_bounds": [0.95, 1.05],
    "narrow_bounds": [0.90, 1.10],
    "stop_rule": "outside_narrow_bounds_or_any_exact_semantic_mismatch",
    "exact_equality_fields": [
        "state_hash",
        "selected_action",
        "selected_action_hash",
        "completed_work_units",
        "terminal_status",
        "cleanup_succeeded",
    ],
}
DESIGN_SPECIFICATION: dict[str, str] = {
    "scientific_scope": "main_pokemon_native_instrumentation_overhead_pilot",
    "state_source": "exact_frozen_captured_decision_artifacts",
    "pairing": "same_state_agent_seed_fixed_work_action_semantics",
    "process_lifecycle": "fresh_spawned_subprocess_per_mode",
    "resource_envelope": "idle_external_controller_same_pair_episode",
    "load_period_balance": "exact_AB_BA",
    "selection_rule": "outcome_blind_deterministic_manifest_only",
}


class InstrumentationError(RuntimeError):
    """The frozen instrumentation acquisition contract was violated."""


class InstrumentationWorkerError(InstrumentationError):
    def __init__(self, message: str, runtime: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.runtime = dict(runtime or {})


@dataclass(frozen=True)
class FrozenInstrumentationState:
    state_id: str
    source_game_id: str
    state_file: str
    state_file_sha256: str

    def validate(self) -> None:
        if not self.state_id or not self.source_game_id or not self.state_file:
            raise ValueError("instrumentation state identifiers/path must be nonempty")
        _require_sha256(self.state_file_sha256, "state file hash")
        path = Path(self.state_file).resolve()
        if not path.is_file() or hash_file(path) != self.state_file_sha256:
            raise ValueError(f"frozen instrumentation state file/hash mismatch: {path}")


@dataclass(frozen=True)
class InstrumentationLimits:
    """Caller-supplied hard bounds; scientific execution requires this object."""

    maximum_pairs: int
    maximum_total_worker_seconds: float

    def validate(self) -> None:
        if (
            isinstance(self.maximum_pairs, bool)
            or not isinstance(self.maximum_pairs, int)
            or self.maximum_pairs < 20
        ):
            raise ValueError("maximum_pairs must be an integer of at least 20")
        if (
            isinstance(self.maximum_total_worker_seconds, bool)
            or not isinstance(self.maximum_total_worker_seconds, (int, float))
            or not math.isfinite(float(self.maximum_total_worker_seconds))
            or float(self.maximum_total_worker_seconds) <= 0.0
        ):
            raise ValueError("maximum_total_worker_seconds must be finite and positive")


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise InstrumentationError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _without_hash(value: Mapping[str, Any], field_name: str = "content_hash") -> dict[str, Any]:
    payload = dict(value)
    payload.pop(field_name, None)
    return payload


def _verify_content_hash(value: Mapping[str, Any], label: str) -> None:
    supplied = _require_sha256(value.get("content_hash"), f"{label} content hash")
    if supplied != hash_json(_without_hash(value)):
        raise InstrumentationError(f"{label} content hash mismatch")


def _load_canonical_json(
    path: str | Path,
    *,
    expected_file_sha256: str | None = None,
) -> tuple[dict[str, Any], str]:
    source = Path(path).resolve()
    try:
        raw = source.read_bytes()
    except OSError as exc:
        raise InstrumentationError(f"cannot read JSON artifact: {source}") from exc
    observed = sha256_bytes(raw)
    if expected_file_sha256 is not None and observed != _require_sha256(
        expected_file_sha256, f"expected file hash for {source.name}"
    ):
        raise InstrumentationError(
            f"file hash mismatch for {source}: expected={expected_file_sha256}, observed={observed}"
        )
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise InstrumentationError(f"invalid ASCII JSON artifact: {source}") from exc
    if not isinstance(value, dict) or raw != canonical_json_bytes(value):
        raise InstrumentationError(f"JSON artifact is not canonical: {source}")
    return value, observed


def _atomic_write_new(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(dict(value))
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _atomic_replace(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = canonical_json_bytes(dict(value))
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _resolve_entrypoint(value: Any) -> Callable[..., Mapping[str, Any]]:
    if not isinstance(value, str) or value.count(":") != 1:
        raise InstrumentationError("entrypoint must use module:function syntax")
    module_name, function_name = value.split(":", 1)
    function = getattr(importlib.import_module(module_name), function_name, None)
    if not callable(function):
        raise InstrumentationError(f"instrumentation entrypoint is not callable: {value}")
    return function


def _validate_target_cpus(value: Any, *, scientific: bool) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)):
        raise InstrumentationError("target_cpus must be an array")
    cpus = tuple(value)
    if (
        not cpus
        or any(isinstance(cpu, bool) or not isinstance(cpu, int) or cpu < 0 for cpu in cpus)
        or len(set(cpus)) != len(cpus)
    ):
        raise InstrumentationError("target_cpus must contain unique non-negative integers")
    if scientific and len(cpus) != 1:
        raise InstrumentationError("scientific instrumentation requires one pinned benchmark CPU")
    return cpus


def _validate_native_payload(payload: Mapping[str, Any], *, verify_files: bool) -> None:
    required = {
        "schema_version",
        "adapter_configs",
        "artifact_files",
        "artifact_sha256",
    }
    if set(payload) != required or payload.get("schema_version") != RUNTIME_PAYLOAD_SCHEMA_VERSION:
        raise InstrumentationError("native instrumentation payload differs from schema")
    artifact_files = payload.get("artifact_files")
    artifact_hashes = payload.get("artifact_sha256")
    if (
        not isinstance(artifact_files, Mapping)
        or not isinstance(artifact_hashes, Mapping)
        or set(artifact_files) != ARTIFACT_NAMES
        or set(artifact_hashes) != ARTIFACT_NAMES
    ):
        raise InstrumentationError("native instrumentation artifact ledger differs from schema")
    for name in sorted(ARTIFACT_NAMES):
        expected = _require_sha256(artifact_hashes[name], f"{name} hash")
        path = Path(str(artifact_files[name])).resolve()
        if verify_files and (not path.is_file() or hash_file(path) != expected):
            raise InstrumentationError(f"native instrumentation {name} file/hash mismatch")

    configs = payload.get("adapter_configs")
    if not isinstance(configs, Mapping) or set(configs) != set(STUDY_AGENTS):
        raise InstrumentationError("native instrumentation requires exactly three study agents")
    from .adapters.pokemon import PokemonAdapterConfig

    expected_paths = {
        "seeded_engine_path": Path(str(artifact_files["engine_binary"])).resolve(),
        "hero_deck_path": Path(str(artifact_files["hero_deck"])).resolve(),
        "hero_model_path": Path(str(artifact_files["hero_model"])).resolve(),
        "opponent_deck_path": Path(str(artifact_files["opponent_deck"])).resolve(),
        "opponent_model_path": Path(str(artifact_files["opponent_model"])).resolve(),
    }
    for agent_id in STUDY_AGENTS:
        raw_config = configs.get(agent_id)
        if not isinstance(raw_config, Mapping):
            raise InstrumentationError(f"adapter config is malformed for {agent_id}")
        try:
            config = PokemonAdapterConfig(**dict(raw_config))
            config.validate()
        except (TypeError, ValueError) as exc:
            raise InstrumentationError(f"invalid adapter config for {agent_id}") from exc
        if (
            config.agent_id != agent_id
            or config.algorithm != AGENT_ALGORITHMS[agent_id]
            or config.initialize_engine is not True
        ):
            raise InstrumentationError(f"adapter identity/init contract differs for {agent_id}")
        for field_name, expected_path in expected_paths.items():
            if Path(str(getattr(config, field_name))).resolve() != expected_path:
                raise InstrumentationError(
                    f"adapter {agent_id} path differs from frozen {field_name}"
                )


def build_instrumentation_run_config(
    *,
    entrypoint: str,
    entrypoint_payload: Mapping[str, Any],
    target_cpus: Sequence[int],
    worker_timeout_s: float,
    thread_env: Mapping[str, str],
    platform_expectations: Mapping[str, str],
    test_mode: bool = False,
    require_linux_affinity: bool = True,
) -> dict[str, Any]:
    """Build immutable runtime controls before constructing the pair manifest."""

    config: dict[str, Any] = {
        "schema_version": RUN_CONFIG_SCHEMA_VERSION,
        "entrypoint": str(entrypoint),
        "entrypoint_payload": dict(entrypoint_payload),
        "target_cpus": list(target_cpus),
        "worker_timeout_s": worker_timeout_s,
        "require_linux_affinity": bool(require_linux_affinity),
        "thread_env": dict(thread_env),
        "platform_expectations": dict(platform_expectations),
        "resource_profile": {
            "condition": "idle",
            "worker_count": 0,
            "target_cpus": list(target_cpus),
            "chunk_iterations": 50_000,
            "readiness_timeout_s": 15.0,
        },
        "test_mode": bool(test_mode),
    }
    config["content_hash"] = hash_json(config)
    validate_instrumentation_run_config(config)
    return config


def validate_instrumentation_run_config(config: Mapping[str, Any]) -> None:
    _verify_content_hash(config, "instrumentation run config")
    required = {
        "schema_version",
        "entrypoint",
        "entrypoint_payload",
        "target_cpus",
        "worker_timeout_s",
        "require_linux_affinity",
        "thread_env",
        "platform_expectations",
        "resource_profile",
        "test_mode",
        "content_hash",
    }
    if set(config) != required or config.get("schema_version") != RUN_CONFIG_SCHEMA_VERSION:
        raise InstrumentationError("instrumentation run config differs from schema")
    test_mode = config.get("test_mode")
    if not isinstance(test_mode, bool):
        raise InstrumentationError("instrumentation test_mode must be boolean")
    scientific = not test_mode
    cpus = _validate_target_cpus(config.get("target_cpus"), scientific=scientific)
    timeout = config.get("worker_timeout_s")
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(float(timeout))
        or float(timeout) <= 0.0
    ):
        raise InstrumentationError("instrumentation worker timeout must be finite and positive")
    if not isinstance(config.get("require_linux_affinity"), bool):
        raise InstrumentationError("require_linux_affinity must be boolean")
    if scientific and config.get("require_linux_affinity") is not True:
        raise InstrumentationError("scientific instrumentation requires Linux affinity")
    entrypoint = config.get("entrypoint")
    _resolve_entrypoint(entrypoint)
    payload = config.get("entrypoint_payload")
    if not isinstance(payload, Mapping):
        raise InstrumentationError("instrumentation entrypoint payload must be an object")
    if scientific:
        if entrypoint != SCIENTIFIC_ENTRYPOINT:
            raise InstrumentationError("scientific instrumentation requires its native entrypoint")
        _validate_native_payload(payload, verify_files=True)
    elif entrypoint != SYNTHETIC_ENTRYPOINT:
        raise InstrumentationError("test instrumentation requires its synthetic entrypoint")

    thread_env = config.get("thread_env")
    if not isinstance(thread_env, Mapping) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in thread_env.items()
    ):
        raise InstrumentationError("instrumentation thread environment must contain strings")
    if scientific:
        if set(thread_env) != THREAD_ENV_KEYS:
            raise InstrumentationError("scientific instrumentation requires exact thread controls")
        if any(thread_env[name] != "1" for name in THREAD_ENV_KEYS - {"PYTHONHASHSEED"}):
            raise InstrumentationError("scientific instrumentation thread counts must equal one")
        if not thread_env["PYTHONHASHSEED"].isdigit():
            raise InstrumentationError("scientific PYTHONHASHSEED must be decimal")
    expectations = config.get("platform_expectations")
    if not isinstance(expectations, Mapping) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in expectations.items()
    ):
        raise InstrumentationError("platform expectations must contain strings")
    if scientific and set(expectations) != {"system", "machine"}:
        raise InstrumentationError("scientific instrumentation requires system/machine expectations")

    profile = config.get("resource_profile")
    expected_profile = {
        "condition": "idle",
        "worker_count": 0,
        "target_cpus": list(cpus),
        "chunk_iterations": 50_000,
        "readiness_timeout_s": 15.0,
    }
    if profile != expected_profile:
        raise InstrumentationError("instrumentation resource profile is not frozen idle")


def _state_payload(states: Sequence[FrozenInstrumentationState]) -> list[dict[str, Any]]:
    ordered = sorted(states, key=lambda state: state.state_id)
    if not ordered:
        raise ValueError("instrumentation manifest requires frozen states")
    for state in ordered:
        state.validate()
    for field_name in ("state_id", "source_game_id", "state_file_sha256"):
        values = [getattr(state, field_name) for state in ordered]
        if len(values) != len(set(values)):
            raise ValueError(f"instrumentation state ledger repeats {field_name}")
    return [
        {
            **asdict(state),
            "state_file": str(Path(state.state_file).resolve()),
        }
        for state in ordered
    ]


def _build_pair_schedule(
    *,
    master_seed: int,
    pair_count: int,
    states: Sequence[Mapping[str, Any]],
    fixed_work_by_agent: Mapping[str, int],
) -> list[dict[str, Any]]:
    agents = deterministic_shuffle(STUDY_AGENTS, master_seed, "instrumentation_agents")
    ordered_states = deterministic_shuffle(
        sorted((dict(state) for state in states), key=lambda state: str(state["state_id"])),
        master_seed,
        "instrumentation_states",
    )
    order_indexes = deterministic_shuffle(
        range(pair_count), master_seed, "instrumentation_AB_BA"
    )
    off_first = set(order_indexes[: pair_count // 2])
    pairs: list[dict[str, Any]] = []
    seeds: set[int] = set()
    execution_index = 0
    for pair_index in range(pair_count):
        agent_id = agents[pair_index % len(agents)]
        state = ordered_states[pair_index % len(ordered_states)]
        agent_seed = derive_u32(
            master_seed,
            "pokemon_instrumentation_agent",
            pair_index,
            agent_id,
            state["state_id"],
        )
        if agent_seed in seeds:
            raise ValueError("derived instrumentation agent seeds collided")
        seeds.add(agent_seed)
        common = {
            "pair_index": pair_index,
            "state_id": state["state_id"],
            "source_game_id": state["source_game_id"],
            "state_file": state["state_file"],
            "state_file_sha256": state["state_file_sha256"],
            "agent_id": agent_id,
            "agent_seed": agent_seed,
            "requested_work_units": int(fixed_work_by_agent[agent_id]),
        }
        pair_id = f"instr-{hash_json(common)[:20]}"
        order = "off_then_on" if pair_index in off_first else "on_then_off"
        modes = (False, True) if order == "off_then_on" else (True, False)
        rows: list[dict[str, Any]] = []
        for position, enabled in enumerate(modes):
            mode_name = "on" if enabled else "off"
            row: dict[str, Any] = {
                "schema_version": ROW_SCHEMA_VERSION,
                "case_id": f"{pair_id}-{mode_name}",
                "pair_id": pair_id,
                "pair_index": pair_index,
                "execution_index": execution_index,
                "execution_position": position,
                "instrumentation_order": order,
                "instrumentation_enabled": enabled,
                "state_id": common["state_id"],
                "source_game_id": common["source_game_id"],
                "state_file": common["state_file"],
                "state_file_sha256": common["state_file_sha256"],
                "agent_id": agent_id,
                "agent_seed": agent_seed,
                "requested_work_units": common["requested_work_units"],
                "budget_mode": "fixed_work",
                "load_condition": "idle",
                "lifecycle": "fresh",
            }
            rows.append(row)
            execution_index += 1
        pair: dict[str, Any] = {
            "pair_id": pair_id,
            "pair_index": pair_index,
            "instrumentation_order": order,
            "rows": rows,
        }
        pair["pair_plan_hash"] = hash_json(pair)
        pairs.append(pair)
    return pairs


def build_instrumentation_manifest(
    *,
    master_seed: int,
    frozen_states: Sequence[FrozenInstrumentationState],
    fixed_work_by_agent: Mapping[str, int],
    pair_count: int,
    run_config_file: str | Path,
    run_config_file_sha256: str,
    pilot_gate_file: str | Path | None = None,
    state_selection_bank_file: str | Path | None = None,
    state_selection_bank_file_sha256: str | None = None,
) -> dict[str, Any]:
    """Freeze deterministic AB/BA pairs without inspecting timing outcomes."""

    if isinstance(master_seed, bool) or not isinstance(master_seed, int) or master_seed < 0:
        raise ValueError("instrumentation master_seed must be a non-negative integer")
    if (
        isinstance(pair_count, bool)
        or not isinstance(pair_count, int)
        or pair_count < GATE_SPECIFICATION["minimum_pair_count"]
        or pair_count % 2
    ):
        raise ValueError("instrumentation pair_count must be even and at least 20")
    if set(fixed_work_by_agent) != set(STUDY_AGENTS):
        raise ValueError("fixed-work ledger must contain exactly three study agents")
    work = dict(fixed_work_by_agent)
    for agent_id, value in work.items():
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"fixed work must be positive for {agent_id}")
    run_config, observed_run_hash = _load_canonical_json(
        run_config_file, expected_file_sha256=run_config_file_sha256
    )
    validate_instrumentation_run_config(run_config)
    states = _state_payload(frozen_states)
    selection_bank_name: str | None = None
    selection_bank_content_hash: str | None = None
    observed_selection_bank_hash: str | None = None
    resolved_selection_bank_file: str | None = None
    scientific = not bool(run_config["test_mode"])
    if state_selection_bank_file is None or state_selection_bank_file_sha256 is None:
        if scientific:
            raise ValueError(
                "scientific instrumentation requires the frozen repeatability-pilot state bank"
            )
        if state_selection_bank_file is not None or state_selection_bank_file_sha256 is not None:
            raise ValueError("state selection-bank path and hash must be supplied together")
    else:
        selection_bank, observed_selection_bank_hash = _load_canonical_json(
            state_selection_bank_file,
            expected_file_sha256=state_selection_bank_file_sha256,
        )
        from .state_panel import validate_state_selection_bank

        validate_state_selection_bank(selection_bank)
        selection_bank_name = str(selection_bank["bank_name"])
        if scientific and selection_bank_name != "repeatability_pilot":
            raise ValueError(
                "scientific instrumentation states must come from repeatability_pilot"
            )
        selection_bank_content_hash = str(selection_bank["content_hash"])
        resolved_selection_bank_file = str(Path(state_selection_bank_file).resolve())
        selected = {
            (
                str(state["state_id"]),
                str(state["source_game_id"]),
                str(state["state_artifact_sha256"]),
            )
            for state in selection_bank["states"]
        }
        requested = {
            (
                str(state["state_id"]),
                str(state["source_game_id"]),
                str(state["state_file_sha256"]),
            )
            for state in states
        }
        if not requested.issubset(selected):
            raise ValueError("instrumentation state ledger escapes its frozen selection bank")
    gate_path = Path(
        pilot_gate_file
        if pilot_gate_file is not None
        else Path(__file__).resolve().with_name("PILOT_GATE.md")
    ).resolve()
    if not gate_path.is_file():
        raise ValueError(f"missing PILOT_GATE artifact: {gate_path}")
    config: dict[str, Any] = {
        "phase": "pilot",
        "master_seed": master_seed,
        "pair_count": pair_count,
        "agents": list(STUDY_AGENTS),
        "fixed_work_by_agent": work,
        "frozen_states": states,
        "run_config_file": str(Path(run_config_file).resolve()),
        "run_config_file_sha256": observed_run_hash,
        "run_config_content_hash": run_config["content_hash"],
        "state_selection_bank_name": selection_bank_name,
        "state_selection_bank_file": resolved_selection_bank_file,
        "state_selection_bank_file_sha256": observed_selection_bank_hash,
        "state_selection_bank_content_hash": selection_bank_content_hash,
        "pilot_gate_file": str(gate_path),
        "pilot_gate_file_sha256": hash_file(gate_path),
        "gate_specification": dict(GATE_SPECIFICATION),
    }
    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "config": config,
        "design": dict(DESIGN_SPECIFICATION),
        "pairs": _build_pair_schedule(
            master_seed=master_seed,
            pair_count=pair_count,
            states=states,
            fixed_work_by_agent=work,
        ),
    }
    manifest["content_hash"] = hash_json(manifest)
    validate_instrumentation_manifest(manifest)
    return manifest


def validate_instrumentation_manifest(manifest: Mapping[str, Any]) -> None:
    _verify_content_hash(manifest, "instrumentation manifest")
    if set(manifest) != {"schema_version", "config", "design", "pairs", "content_hash"}:
        raise InstrumentationError("instrumentation manifest top-level fields differ")
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise InstrumentationError("unknown instrumentation manifest schema")
    if manifest.get("design") != DESIGN_SPECIFICATION:
        raise InstrumentationError("instrumentation design contract was changed")
    config = manifest.get("config")
    if not isinstance(config, Mapping):
        raise InstrumentationError("instrumentation manifest lacks config")
    required_config = {
        "phase",
        "master_seed",
        "pair_count",
        "agents",
        "fixed_work_by_agent",
        "frozen_states",
        "run_config_file",
        "run_config_file_sha256",
        "run_config_content_hash",
        "state_selection_bank_name",
        "state_selection_bank_file",
        "state_selection_bank_file_sha256",
        "state_selection_bank_content_hash",
        "pilot_gate_file",
        "pilot_gate_file_sha256",
        "gate_specification",
    }
    if set(config) != required_config or config.get("phase") != "pilot":
        raise InstrumentationError("instrumentation config differs from pilot schema")
    if config.get("agents") != list(STUDY_AGENTS):
        raise InstrumentationError("instrumentation agent ledger differs")
    pair_count = config.get("pair_count")
    if (
        isinstance(pair_count, bool)
        or not isinstance(pair_count, int)
        or pair_count < 20
        or pair_count % 2
    ):
        raise InstrumentationError("instrumentation requires an even pair count of at least 20")
    master_seed = config.get("master_seed")
    if isinstance(master_seed, bool) or not isinstance(master_seed, int) or master_seed < 0:
        raise InstrumentationError("instrumentation master seed is invalid")
    work = config.get("fixed_work_by_agent")
    if not isinstance(work, Mapping) or set(work) != set(STUDY_AGENTS):
        raise InstrumentationError("instrumentation fixed-work ledger differs")
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in work.values()):
        raise InstrumentationError("instrumentation fixed-work values must be positive")
    if config.get("gate_specification") != GATE_SPECIFICATION:
        raise InstrumentationError("instrumentation gate criterion was changed")
    gate_path = Path(str(config.get("pilot_gate_file"))).resolve()
    expected_gate_hash = _require_sha256(
        config.get("pilot_gate_file_sha256"), "PILOT_GATE file hash"
    )
    if not gate_path.is_file() or hash_file(gate_path) != expected_gate_hash:
        raise InstrumentationError("PILOT_GATE artifact/hash mismatch")
    run_config, observed_run_hash = _load_canonical_json(
        str(config.get("run_config_file")),
        expected_file_sha256=_require_sha256(
            config.get("run_config_file_sha256"), "run config file hash"
        ),
    )
    validate_instrumentation_run_config(run_config)
    if (
        observed_run_hash != config.get("run_config_file_sha256")
        or run_config.get("content_hash") != config.get("run_config_content_hash")
    ):
        raise InstrumentationError("instrumentation run-config binding differs")
    selection_fields = (
        config.get("state_selection_bank_name"),
        config.get("state_selection_bank_file"),
        config.get("state_selection_bank_file_sha256"),
        config.get("state_selection_bank_content_hash"),
    )
    if run_config["test_mode"]:
        if any(value is not None for value in selection_fields):
            raise InstrumentationError(
                "test instrumentation unexpectedly binds a scientific selection bank"
            )
        selection_bank = None
    else:
        if config.get("state_selection_bank_name") != "repeatability_pilot":
            raise InstrumentationError(
                "scientific instrumentation has the wrong frozen state bank"
            )
        selection_bank, observed_bank_hash = _load_canonical_json(
            str(config.get("state_selection_bank_file")),
            expected_file_sha256=_require_sha256(
                config.get("state_selection_bank_file_sha256"),
                "state selection-bank file hash",
            ),
        )
        from .state_panel import validate_state_selection_bank

        validate_state_selection_bank(selection_bank)
        if (
            observed_bank_hash != config.get("state_selection_bank_file_sha256")
            or selection_bank.get("content_hash")
            != config.get("state_selection_bank_content_hash")
            or selection_bank.get("bank_name") != "repeatability_pilot"
        ):
            raise InstrumentationError("instrumentation selection-bank binding differs")
    state_rows = config.get("frozen_states")
    if not isinstance(state_rows, list) or not state_rows:
        raise InstrumentationError("instrumentation state ledger is empty")
    states: list[FrozenInstrumentationState] = []
    for item in state_rows:
        if not isinstance(item, Mapping) or set(item) != {
            "state_id",
            "source_game_id",
            "state_file",
            "state_file_sha256",
        }:
            raise InstrumentationError("instrumentation state row differs from schema")
        try:
            state = FrozenInstrumentationState(**dict(item))
            state.validate()
        except (TypeError, ValueError) as exc:
            raise InstrumentationError("invalid frozen instrumentation state") from exc
        states.append(state)
    for field_name in ("state_id", "source_game_id", "state_file_sha256"):
        values = [getattr(state, field_name) for state in states]
        if len(values) != len(set(values)):
            raise InstrumentationError(f"instrumentation states repeat {field_name}")
    if selection_bank is not None:
        selected = {
            (
                str(state["state_id"]),
                str(state["source_game_id"]),
                str(state["state_artifact_sha256"]),
            )
            for state in selection_bank["states"]
        }
        requested = {
            (state.state_id, state.source_game_id, state.state_file_sha256)
            for state in states
        }
        if not requested.issubset(selected):
            raise InstrumentationError(
                "instrumentation state ledger escapes its frozen selection bank"
            )
    expected_pairs = _build_pair_schedule(
        master_seed=master_seed,
        pair_count=pair_count,
        states=[asdict(state) for state in states],
        fixed_work_by_agent={str(key): int(value) for key, value in work.items()},
    )
    if manifest.get("pairs") != expected_pairs:
        raise InstrumentationError("instrumentation pair schedule is not deterministic")
    if sum(pair["instrumentation_order"] == "off_then_on" for pair in expected_pairs) != (
        pair_count // 2
    ):
        raise InstrumentationError("instrumentation schedule lost exact AB/BA balance")


def _load_frozen_capture_bytes(raw: bytes, *, expected_sha256: str):
    """Load the exact canonical capture wrapper without a recapture/normalization."""

    from .capture import CapturedDecisionState, FROZEN_CAPTURE_SCHEMA_VERSION

    if sha256_bytes(raw) != _require_sha256(expected_sha256, "captured-state hash"):
        raise InstrumentationError("in-memory captured-state file hash mismatch")
    try:
        wrapper = json.loads(raw.decode("ascii"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise InstrumentationError("cannot decode captured-state bytes") from exc
    if not isinstance(wrapper, Mapping) or canonical_json_bytes(wrapper) != raw:
        raise InstrumentationError("captured-state bytes are not canonical")
    if set(wrapper) != {
        "schema_version",
        "captured_state_artifact_hash",
        "captured_state",
    } or wrapper.get("schema_version") != FROZEN_CAPTURE_SCHEMA_VERSION:
        raise InstrumentationError("captured-state wrapper differs from schema")
    captured = wrapper.get("captured_state")
    if not isinstance(captured, Mapping):
        raise InstrumentationError("captured-state wrapper lacks captured_state")
    try:
        state = CapturedDecisionState.from_dict(captured)
    except RuntimeError as exc:
        raise InstrumentationError("captured-state payload is invalid") from exc
    if wrapper.get("captured_state_artifact_hash") != state.artifact_hash:
        raise InstrumentationError("captured-state embedded artifact hash mismatch")
    return state


def pokemon_instrumentation_entrypoint(
    row: Mapping[str, Any],
    state_bytes: bytes,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Run one native fixed-work decision in an otherwise fresh child."""

    _validate_native_payload(payload, verify_files=True)
    state = _load_frozen_capture_bytes(
        state_bytes, expected_sha256=str(row["state_file_sha256"])
    )
    if (
        state.state_id != row.get("state_id")
        or state.source_game_id != row.get("source_game_id")
    ):
        raise InstrumentationError("captured-state identity differs from manifest row")
    agent_id = str(row["agent_id"])
    configs = payload["adapter_configs"]
    if agent_id not in configs:
        raise InstrumentationError(f"manifest row references unknown agent: {agent_id}")

    from .adapters.pokemon import PokemonAdapterConfig, PokemonSearchAdapter
    from .runner import CaseContext, run_decision
    from .stop_policy import FixedWorkStop

    adapter = PokemonSearchAdapter(PokemonAdapterConfig(**dict(configs[agent_id])))
    context = CaseContext(
        case_id=str(row["case_id"]),
        block_id=str(row["pair_id"]),
        decision_index=0,
        load_condition="idle",
        lifecycle="fresh",
        lifecycle_id=str(row["case_id"]),
        process_instance_id=str(row["case_id"]),
        sequence_index=int(row["execution_position"]),
        load_batch_id=str(row["pair_id"]),
        agent_seed=int(row["agent_seed"]),
        instrumentation_enabled=bool(row["instrumentation_enabled"]),
    )
    decision = run_decision(
        adapter,
        state.raw_state,
        FixedWorkStop(int(row["requested_work_units"])),
        context,
    )
    return {
        "schema_version": "pokemon-instrumentation-callback-1.0.0",
        "decision_record": decision.to_dict(),
    }


def synthetic_instrumentation_entrypoint(
    row: Mapping[str, Any],
    state_bytes: bytes,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Deterministic test-only callback; never accepted by scientific config."""

    if payload.get("fail_case_id") == row.get("case_id"):
        raise RuntimeError("synthetic instrumentation failure")
    enabled = bool(row["instrumentation_enabled"])
    work = int(row["requested_work_units"])
    off_ns = int(payload.get("off_search_wall_ns", 1_000_000))
    on_ns = int(payload.get("on_search_wall_ns", off_ns))
    search_wall_ns = on_ns if enabled else off_ns
    if search_wall_ns <= 0:
        raise ValueError("synthetic search wall time must be positive")
    state_hash = sha256_bytes(state_bytes)
    action = [derive_u32(int(row["agent_seed"]), "synthetic_action", row["state_id"]) % 8]
    action_identity = {
        "state": state_hash,
        "agent_id": row["agent_id"],
        "agent_seed": row["agent_seed"],
        "requested_work_units": work,
        "action": action,
    }
    decision = {
        "schema_version": "decision-1.1.0",
        "case_id": row["case_id"],
        "block_id": row["pair_id"],
        "decision_index": 0,
        "agent_id": row["agent_id"],
        "budget_mode": "fixed_work",
        "load_condition": "idle",
        "lifecycle": "fresh",
        "lifecycle_id": row["case_id"],
        "process_instance_id": row["case_id"],
        "worker_pid": os.getpid(),
        "sequence_index": row["execution_position"],
        "load_batch_id": row["pair_id"],
        "requested_budget_ns": None,
        "requested_work_units": work,
        "completed_work_units": work,
        "completed_simulations": work if enabled else 0,
        "completed_nodes": work if enabled else 0,
        "completed_sweeps": 0,
        "forward_model_calls": 2 * work if enabled else 0,
        "setup_wall_ns": 1,
        "search_wall_ns": search_wall_ns,
        "selection_wall_ns": 1,
        "cleanup_wall_ns": 1,
        "process_cpu_ns": search_wall_ns,
        "overshoot_ns": 0,
        "state_hash": state_hash,
        "agent_seed_hash": hash_json({"agent_seed": row["agent_seed"]}),
        "selected_action": action,
        "selected_action_hash": hash_json(action_identity),
        "value_estimates": [0.0],
        "timeout_reason": "",
        "fallback_reason": "",
        "cleanup_succeeded": True,
        "instrumentation_enabled": enabled,
        "work_counters_collected": enabled,
        "terminal_status": "ok",
        "error_type": "",
        "error_message": "",
        "extra": {
            "stop_completed_units": work,
            "selected_action_identity": action_identity,
        },
    }
    return {
        "schema_version": "pokemon-instrumentation-callback-1.0.0",
        "decision_record": decision,
    }


def _set_affinity(target_cpus: Sequence[int]) -> bool:
    if not hasattr(os, "sched_setaffinity"):
        return False
    os.sched_setaffinity(0, set(target_cpus))
    return True


def _observed_affinity() -> list[int] | None:
    if not hasattr(os, "sched_getaffinity"):
        return None
    return sorted(int(cpu) for cpu in os.sched_getaffinity(0))


def _instrumentation_child(
    output_queue: Any,
    entrypoint: str,
    row: dict[str, Any],
    state_path: str,
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
    runtime: dict[str, Any] = {
        "observed_process_id": os.getpid(),
        "target_cpus": list(target_cpus),
        "spawn_method": "spawn",
        "fresh_process": True,
        "process_time_ns_start": time.process_time_ns(),
        "parent_death_kill_armed": parent_guard is not None,
    }
    try:
        runtime["thread_env"] = {key: os.environ.get(key) for key in thread_env}
        if runtime["thread_env"] != thread_env:
            raise RuntimeError("instrumentation child thread environment mismatch")
        runtime["affinity_applied"] = _set_affinity(target_cpus)
        runtime["observed_affinity"] = _observed_affinity()
        if require_affinity and (
            not runtime["affinity_applied"]
            or runtime["observed_affinity"] != sorted(target_cpus)
        ):
            raise RuntimeError("instrumentation child affinity mismatch")
        raw = Path(state_path).read_bytes()
        observed_state_hash = sha256_bytes(raw)
        if observed_state_hash != row["state_file_sha256"]:
            raise RuntimeError("instrumentation child state-file hash mismatch")
        callback = _resolve_entrypoint(entrypoint)(row, raw, payload)
        if not isinstance(callback, Mapping):
            raise TypeError("instrumentation callback did not return a mapping")
        runtime["process_time_ns_end"] = time.process_time_ns()
        runtime["process_time_ns_delta"] = (
            runtime["process_time_ns_end"] - runtime["process_time_ns_start"]
        )
        output_queue.put(
            {
                "ok": True,
                "callback": dict(callback),
                "state_bytes_sha256": observed_state_hash,
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


def _stop_child(process: Any, *, terminate_timeout_s: float = 2.0, kill_timeout_s: float = 2.0) -> str:
    """Use the shared tested terminate-then-hard-kill implementation."""

    return stop_process(
        process,
        terminate_timeout_s=terminate_timeout_s,
        kill_timeout_s=kill_timeout_s,
    )


def _spawn_case(
    row: Mapping[str, Any],
    *,
    run_config: Mapping[str, Any],
) -> dict[str, Any]:
    context = mp.get_context("spawn")
    output_queue = context.Queue()
    process = context.Process(
        target=_instrumentation_child,
        args=(
            output_queue,
            str(run_config["entrypoint"]),
            dict(row),
            str(row["state_file"]),
            dict(run_config["entrypoint_payload"]),
            tuple(run_config["target_cpus"]),
            bool(run_config["require_linux_affinity"]),
            dict(run_config["thread_env"]),
            os.getpid(),
        ),
        name=f"pokemon-instrumentation-{row['case_id']}",
    )
    started = False
    message: dict[str, Any] = {}
    try:
        process.start()
        started = True
        try:
            message = output_queue.get(timeout=float(run_config["worker_timeout_s"]))
        except queue.Empty as exc:
            runtime = {"spawned_process_id": process.pid}
            runtime["stop_disposition"] = _stop_child(process)
            raise InstrumentationWorkerError(
                f"instrumentation worker timeout for {row['case_id']}", runtime
            ) from exc
        process.join(timeout=min(30.0, float(run_config["worker_timeout_s"])))
        if process.is_alive():
            runtime = dict(message.get("runtime", {}))
            runtime["spawned_process_id"] = process.pid
            runtime["stop_disposition"] = _stop_child(process)
            raise InstrumentationWorkerError(
                f"instrumentation worker failed to exit for {row['case_id']}", runtime
            )
        runtime = dict(message.get("runtime", {}))
        runtime["spawned_process_id"] = process.pid
        runtime["exitcode"] = process.exitcode
        if runtime.get("observed_process_id") != process.pid:
            raise InstrumentationWorkerError("instrumentation worker PID evidence mismatch", runtime)
        if process.exitcode != 0:
            raise InstrumentationWorkerError(
                f"instrumentation worker exited with code {process.exitcode}", runtime
            )
        if message.get("ok") is not True:
            raise InstrumentationWorkerError(
                str(message.get("error", "instrumentation worker failed")), runtime
            )
        if bool(run_config["require_linux_affinity"]) and (
            runtime.get("affinity_applied") is not True
            or runtime.get("parent_death_kill_armed") is not True
            or runtime.get("observed_affinity") != sorted(run_config["target_cpus"])
        ):
            raise InstrumentationWorkerError(
                "instrumentation worker affinity evidence mismatch", runtime
            )
        message["runtime"] = runtime
        return message
    except BaseException:
        if (started or process.pid is not None) and process.is_alive():
            _stop_child(process)
        raise
    finally:
        if not process.is_alive():
            output_queue.close()
            output_queue.join_thread()


def _decision_from_callback(callback: Mapping[str, Any]):
    from .telemetry import DecisionTelemetry

    if set(callback) != {"schema_version", "decision_record"} or callback.get(
        "schema_version"
    ) != "pokemon-instrumentation-callback-1.0.0":
        raise InstrumentationError("instrumentation callback fields differ from schema")
    raw = callback.get("decision_record")
    if not isinstance(raw, Mapping):
        raise InstrumentationError("instrumentation callback lacks decision telemetry")
    expected = {field.name for field in fields(DecisionTelemetry)}
    if set(raw) != expected:
        raise InstrumentationError("decision telemetry fields differ from schema")
    try:
        decision = DecisionTelemetry(**dict(raw))
        decision.validate()
    except (TypeError, ValueError) as exc:
        raise InstrumentationError("instrumentation decision telemetry is invalid") from exc
    return decision


def _normalize_result(
    row: Mapping[str, Any],
    message: Mapping[str, Any],
    *,
    manifest: Mapping[str, Any],
    manifest_file_sha256: str,
    run_config: Mapping[str, Any],
    run_config_file_sha256: str,
) -> dict[str, Any]:
    callback = message.get("callback")
    if not isinstance(callback, Mapping):
        raise InstrumentationError("instrumentation worker lacks callback result")
    decision = _decision_from_callback(callback)
    decision_record = decision.to_dict()
    runtime = message.get("runtime")
    if not isinstance(runtime, Mapping):
        raise InstrumentationError("instrumentation result lacks worker evidence")
    result: dict[str, Any] = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "case_id": row["case_id"],
        "pair_id": row["pair_id"],
        "manifest_content_hash": manifest["content_hash"],
        "manifest_file_sha256": manifest_file_sha256,
        "run_config_content_hash": run_config["content_hash"],
        "run_config_file_sha256": run_config_file_sha256,
        "schedule_row": dict(row),
        "manifest_row_hash": hash_json(row),
        "state_artifact_sha256": row["state_file_sha256"],
        "state_bytes_sha256": message.get("state_bytes_sha256"),
        "agent_id": decision.agent_id,
        "agent_seed_hash": decision.agent_seed_hash,
        "requested_work_units": decision.requested_work_units,
        "completed_work_units": decision.completed_work_units,
        "search_wall_ns": decision.search_wall_ns,
        "state_hash": decision.state_hash,
        "selected_action": list(decision.selected_action),
        "selected_action_hash": decision.selected_action_hash,
        "cleanup_succeeded": decision.cleanup_succeeded,
        "instrumentation_enabled": decision.instrumentation_enabled,
        "work_counters_collected": decision.work_counters_collected,
        "terminal_status": decision.terminal_status,
        "decision_record": decision_record,
        "observed_worker": dict(runtime),
    }
    result["artifact_sha256"] = hash_json(result)
    _validate_result_against_row(
        result,
        row,
        manifest=manifest,
        manifest_file_sha256=manifest_file_sha256,
        run_config=run_config,
        run_config_file_sha256=run_config_file_sha256,
    )
    return result


def _validate_result_against_row(
    result: Mapping[str, Any],
    row: Mapping[str, Any],
    *,
    manifest: Mapping[str, Any],
    manifest_file_sha256: str,
    run_config: Mapping[str, Any],
    run_config_file_sha256: str,
) -> None:
    required = {
        "schema_version",
        "case_id",
        "pair_id",
        "manifest_content_hash",
        "manifest_file_sha256",
        "run_config_content_hash",
        "run_config_file_sha256",
        "schedule_row",
        "manifest_row_hash",
        "state_artifact_sha256",
        "state_bytes_sha256",
        "agent_id",
        "agent_seed_hash",
        "requested_work_units",
        "completed_work_units",
        "search_wall_ns",
        "state_hash",
        "selected_action",
        "selected_action_hash",
        "cleanup_succeeded",
        "instrumentation_enabled",
        "work_counters_collected",
        "terminal_status",
        "decision_record",
        "observed_worker",
        "artifact_sha256",
    }
    if set(result) != required or result.get("schema_version") != RESULT_SCHEMA_VERSION:
        raise InstrumentationError("instrumentation result fields differ from schema")
    if result.get("artifact_sha256") != hash_json(_without_hash(result, "artifact_sha256")):
        raise InstrumentationError("instrumentation result artifact hash mismatch")
    provenance = {
        "case_id": row["case_id"],
        "pair_id": row["pair_id"],
        "manifest_content_hash": manifest["content_hash"],
        "manifest_file_sha256": manifest_file_sha256,
        "run_config_content_hash": run_config["content_hash"],
        "run_config_file_sha256": run_config_file_sha256,
        "schedule_row": dict(row),
        "manifest_row_hash": hash_json(row),
        "state_artifact_sha256": row["state_file_sha256"],
        "state_bytes_sha256": row["state_file_sha256"],
    }
    for name, expected in provenance.items():
        if result.get(name) != expected:
            raise InstrumentationError(f"instrumentation result differs in {name}")
    decision = _decision_from_callback(
        {
            "schema_version": "pokemon-instrumentation-callback-1.0.0",
            "decision_record": result["decision_record"],
        }
    )
    expected_decision = {
        "case_id": row["case_id"],
        "block_id": row["pair_id"],
        "agent_id": row["agent_id"],
        "budget_mode": "fixed_work",
        "load_condition": "idle",
        "lifecycle": "fresh",
        "load_batch_id": row["pair_id"],
        "requested_budget_ns": None,
        "requested_work_units": row["requested_work_units"],
        "completed_work_units": row["requested_work_units"],
        "overshoot_ns": 0,
        "agent_seed_hash": hash_json({"agent_seed": row["agent_seed"]}),
        "instrumentation_enabled": row["instrumentation_enabled"],
        "work_counters_collected": row["instrumentation_enabled"],
        "terminal_status": "ok",
        "cleanup_succeeded": True,
    }
    for name, expected in expected_decision.items():
        if getattr(decision, name) != expected:
            raise InstrumentationError(f"instrumentation decision differs in {name}")
    if decision.search_wall_ns <= 0:
        raise InstrumentationError("instrumentation search_wall_ns must be positive")
    if not row["instrumentation_enabled"] and any(
        (
            decision.completed_simulations,
            decision.completed_nodes,
            decision.completed_sweeps,
            decision.forward_model_calls,
        )
    ):
        raise InstrumentationError("uninstrumented decision contains optional counters")
    if row["instrumentation_enabled"] and decision.completed_simulations != row[
        "requested_work_units"
    ]:
        raise InstrumentationError("instrumented simulation count differs from fixed work")
    flattened = {
        "agent_id": decision.agent_id,
        "agent_seed_hash": decision.agent_seed_hash,
        "requested_work_units": decision.requested_work_units,
        "completed_work_units": decision.completed_work_units,
        "search_wall_ns": decision.search_wall_ns,
        "state_hash": decision.state_hash,
        "selected_action": list(decision.selected_action),
        "selected_action_hash": decision.selected_action_hash,
        "cleanup_succeeded": decision.cleanup_succeeded,
        "instrumentation_enabled": decision.instrumentation_enabled,
        "work_counters_collected": decision.work_counters_collected,
        "terminal_status": decision.terminal_status,
    }
    for name, expected in flattened.items():
        if result.get(name) != expected:
            raise InstrumentationError(f"instrumentation flattened result differs in {name}")
    worker = result.get("observed_worker")
    if not isinstance(worker, Mapping):
        raise InstrumentationError("instrumentation result lacks worker runtime")
    if (
        worker.get("fresh_process") is not True
        or worker.get("spawn_method") != "spawn"
        or worker.get("spawned_process_id") != worker.get("observed_process_id")
        or worker.get("observed_process_id") != decision.worker_pid
        or worker.get("exitcode") != 0
    ):
        raise InstrumentationError("instrumentation fresh-process/PID evidence is invalid")
    if bool(run_config["require_linux_affinity"]) and (
        worker.get("affinity_applied") is not True
        or worker.get("parent_death_kill_armed") is not True
        or worker.get("observed_affinity") != sorted(run_config["target_cpus"])
    ):
        raise InstrumentationError("instrumentation worker affinity evidence is invalid")


def _pair_rows(pair: Mapping[str, Any]) -> list[dict[str, Any]]:
    if set(pair) != {
        "pair_id",
        "pair_index",
        "instrumentation_order",
        "rows",
        "pair_plan_hash",
    }:
        raise InstrumentationError("instrumentation pair fields differ from schema")
    if pair.get("pair_plan_hash") != hash_json(_without_hash(pair, "pair_plan_hash")):
        raise InstrumentationError("instrumentation pair-plan hash mismatch")
    rows = pair.get("rows")
    if not isinstance(rows, list) or len(rows) != 2 or any(
        not isinstance(row, Mapping) for row in rows
    ):
        raise InstrumentationError("instrumentation pair requires exactly two rows")
    normalized = [dict(row) for row in rows]
    if [row["execution_position"] for row in normalized] != [0, 1]:
        raise InstrumentationError("instrumentation row positions differ")
    if {bool(row["instrumentation_enabled"]) for row in normalized} != {False, True}:
        raise InstrumentationError("instrumentation pair lacks one off and one on row")
    return normalized


def _pair_semantic_failures(
    pair: Mapping[str, Any], results: Sequence[Mapping[str, Any]]
) -> list[str]:
    rows = _pair_rows(pair)
    if len(results) != 2:
        return ["pair_result_count"]
    by_mode = {bool(result.get("instrumentation_enabled")): result for result in results}
    if set(by_mode) != {False, True}:
        return ["pair_mode_count"]
    off = by_mode[False]
    on = by_mode[True]
    failures: list[str] = []
    for name in GATE_SPECIFICATION["exact_equality_fields"]:
        if off.get(name) != on.get(name):
            failures.append(str(name))
    expected_work = int(rows[0]["requested_work_units"])
    if off.get("completed_work_units") != expected_work:
        failures.append("off_fixed_work_exact")
    if on.get("completed_work_units") != expected_work:
        failures.append("on_fixed_work_exact")
    if off.get("terminal_status") != "ok" or on.get("terminal_status") != "ok":
        failures.append("terminal_status_ok")
    if off.get("cleanup_succeeded") is not True or on.get("cleanup_succeeded") is not True:
        failures.append("cleanup_succeeded")
    for name in (
        "state_artifact_sha256",
        "state_bytes_sha256",
        "agent_id",
        "agent_seed_hash",
        "requested_work_units",
    ):
        if off.get(name) != on.get(name):
            failures.append(name)
    if off.get("instrumentation_enabled") is not False:
        failures.append("off_mode")
    if on.get("instrumentation_enabled") is not True:
        failures.append("on_mode")
    return sorted(set(failures))


def _throughput_ratio(results: Sequence[Mapping[str, Any]]) -> float:
    by_mode = {bool(result["instrumentation_enabled"]): result for result in results}
    off = by_mode[False]
    on = by_mode[True]
    off_work = int(off["completed_work_units"])
    on_work = int(on["completed_work_units"])
    off_ns = int(off["search_wall_ns"])
    on_ns = int(on["search_wall_ns"])
    if off_work <= 0 or on_work <= 0 or off_ns <= 0 or on_ns <= 0:
        raise InstrumentationError("instrumentation throughput inputs must be positive")
    return (on_work / on_ns) / (off_work / off_ns)


def _episode_payload(
    *,
    pair: Mapping[str, Any],
    manifest: Mapping[str, Any],
    manifest_file_sha256: str,
    run_config: Mapping[str, Any],
    run_config_file_sha256: str,
    metadata: Mapping[str, Any],
    status: str,
    error: str,
) -> dict[str, Any]:
    episode: dict[str, Any] = {
        "schema_version": EPISODE_SCHEMA_VERSION,
        "pair_id": pair["pair_id"],
        "pair_plan_hash": pair["pair_plan_hash"],
        "manifest_content_hash": manifest["content_hash"],
        "manifest_file_sha256": manifest_file_sha256,
        "run_config_content_hash": run_config["content_hash"],
        "run_config_file_sha256": run_config_file_sha256,
        "case_ids": [row["case_id"] for row in _pair_rows(pair)],
        "resource_envelope": dict(metadata),
        "resource_envelope_hash": hash_json(metadata),
        "terminal_status": status,
        "error": error,
    }
    episode["artifact_sha256"] = hash_json(episode)
    return episode


def _validate_episode(
    episode: Mapping[str, Any],
    *,
    pair: Mapping[str, Any],
    manifest: Mapping[str, Any],
    manifest_file_sha256: str,
    run_config: Mapping[str, Any],
    run_config_file_sha256: str,
    allow_invalid: bool = False,
) -> None:
    required = {
        "schema_version",
        "pair_id",
        "pair_plan_hash",
        "manifest_content_hash",
        "manifest_file_sha256",
        "run_config_content_hash",
        "run_config_file_sha256",
        "case_ids",
        "resource_envelope",
        "resource_envelope_hash",
        "terminal_status",
        "error",
        "artifact_sha256",
    }
    if set(episode) != required or episode.get("schema_version") != EPISODE_SCHEMA_VERSION:
        raise InstrumentationError("instrumentation resource episode differs from schema")
    if episode.get("artifact_sha256") != hash_json(
        _without_hash(episode, "artifact_sha256")
    ):
        raise InstrumentationError("instrumentation resource-episode hash mismatch")
    rows = _pair_rows(pair)
    expected = {
        "pair_id": pair["pair_id"],
        "pair_plan_hash": pair["pair_plan_hash"],
        "manifest_content_hash": manifest["content_hash"],
        "manifest_file_sha256": manifest_file_sha256,
        "run_config_content_hash": run_config["content_hash"],
        "run_config_file_sha256": run_config_file_sha256,
        "case_ids": [row["case_id"] for row in rows],
    }
    for name, value in expected.items():
        if episode.get(name) != value:
            raise InstrumentationError(f"resource episode differs in {name}")
    metadata = episode.get("resource_envelope")
    if not isinstance(metadata, Mapping) or episode.get("resource_envelope_hash") != hash_json(
        metadata
    ):
        raise InstrumentationError("resource episode embedded metadata hash mismatch")
    status = episode.get("terminal_status")
    if status not in {"scientific_complete", "invalid_stopped"}:
        raise InstrumentationError("unknown instrumentation resource-episode status")
    if status == "invalid_stopped":
        if not allow_invalid or not episode.get("error"):
            raise InstrumentationError("invalid instrumentation episode is not usable")
        return
    if episode.get("error") != "":
        raise InstrumentationError("complete instrumentation episode contains an error")
    profile = metadata.get("profile")
    if not isinstance(profile, Mapping) or (
        profile.get("condition") != "idle"
        or profile.get("worker_count") != 0
        or list(profile.get("target_cpus", ())) != list(run_config["target_cpus"])
    ):
        raise InstrumentationError("instrumentation episode escaped frozen idle profile")
    if metadata.get("workers") != []:
        raise InstrumentationError("idle instrumentation episode launched a co-runner")
    if metadata.get("cleanup_succeeded") is not True or metadata.get("cleanup_errors") != []:
        raise InstrumentationError("instrumentation resource cleanup failed")
    benchmark_workers = metadata.get("benchmark_workers")
    if not isinstance(benchmark_workers, list) or len(benchmark_workers) != 2:
        raise InstrumentationError("instrumentation episode lacks two benchmark workers")
    for worker in benchmark_workers:
        if not isinstance(worker, Mapping) or (
            worker.get("fresh_process") is not True
            or worker.get("spawn_method") != "spawn"
            or worker.get("spawned_process_id") != worker.get("observed_process_id")
            or worker.get("exitcode") != 0
        ):
            raise InstrumentationError("instrumentation episode has invalid worker evidence")
        if bool(run_config["require_linux_affinity"]) and (
            worker.get("affinity_applied") is not True
            or worker.get("parent_death_kill_armed") is not True
            or worker.get("observed_affinity") != sorted(run_config["target_cpus"])
        ):
            raise InstrumentationError("instrumentation episode worker affinity is invalid")


def _pair_commit(
    *,
    pair: Mapping[str, Any],
    results: Sequence[Mapping[str, Any]],
    episode: Mapping[str, Any],
    manifest: Mapping[str, Any],
    manifest_file_sha256: str,
    run_config: Mapping[str, Any],
    run_config_file_sha256: str,
) -> dict[str, Any]:
    failures = _pair_semantic_failures(pair, results)
    if failures:
        raise InstrumentationError(
            f"instrumentation pair semantic mismatch: {', '.join(failures)}"
        )
    ratio = _throughput_ratio(results)
    semantic = {
        name: results[0][name]
        for name in GATE_SPECIFICATION["exact_equality_fields"]
    }
    commit: dict[str, Any] = {
        "schema_version": PAIR_COMMIT_SCHEMA_VERSION,
        "pair_id": pair["pair_id"],
        "pair_plan_hash": pair["pair_plan_hash"],
        "manifest_content_hash": manifest["content_hash"],
        "manifest_file_sha256": manifest_file_sha256,
        "run_config_content_hash": run_config["content_hash"],
        "run_config_file_sha256": run_config_file_sha256,
        "case_ids": [row["case_id"] for row in _pair_rows(pair)],
        "result_hashes": [result["artifact_sha256"] for result in results],
        "resource_episode_hash": episode["artifact_sha256"],
        "case_results": [dict(result) for result in results],
        "resource_episode": dict(episode),
        "exact_semantic_fingerprint": hash_json(semantic),
        "throughput_ratio_on_over_off": ratio,
        "terminal_status": "instrumentation_pair_complete",
    }
    commit["content_hash"] = hash_json(commit)
    return commit


def _validate_pair_commit(
    commit: Mapping[str, Any],
    *,
    pair: Mapping[str, Any],
    manifest: Mapping[str, Any],
    manifest_file_sha256: str,
    run_config: Mapping[str, Any],
    run_config_file_sha256: str,
) -> None:
    required = {
        "schema_version",
        "pair_id",
        "pair_plan_hash",
        "manifest_content_hash",
        "manifest_file_sha256",
        "run_config_content_hash",
        "run_config_file_sha256",
        "case_ids",
        "result_hashes",
        "resource_episode_hash",
        "case_results",
        "resource_episode",
        "exact_semantic_fingerprint",
        "throughput_ratio_on_over_off",
        "terminal_status",
        "content_hash",
    }
    if set(commit) != required or commit.get("schema_version") != PAIR_COMMIT_SCHEMA_VERSION:
        raise InstrumentationError("instrumentation pair commit differs from schema")
    _verify_content_hash(commit, "instrumentation pair commit")
    if commit.get("terminal_status") != "instrumentation_pair_complete":
        raise InstrumentationError("instrumentation pair commit is not complete")
    rows = _pair_rows(pair)
    provenance = {
        "pair_id": pair["pair_id"],
        "pair_plan_hash": pair["pair_plan_hash"],
        "manifest_content_hash": manifest["content_hash"],
        "manifest_file_sha256": manifest_file_sha256,
        "run_config_content_hash": run_config["content_hash"],
        "run_config_file_sha256": run_config_file_sha256,
        "case_ids": [row["case_id"] for row in rows],
    }
    for name, value in provenance.items():
        if commit.get(name) != value:
            raise InstrumentationError(f"instrumentation pair commit differs in {name}")
    results = commit.get("case_results")
    if not isinstance(results, list) or len(results) != 2:
        raise InstrumentationError("instrumentation commit lacks two results")
    for row, result in zip(rows, results):
        if not isinstance(result, Mapping):
            raise InstrumentationError("instrumentation commit embeds a malformed result")
        _validate_result_against_row(
            result,
            row,
            manifest=manifest,
            manifest_file_sha256=manifest_file_sha256,
            run_config=run_config,
            run_config_file_sha256=run_config_file_sha256,
        )
    if commit.get("result_hashes") != [result["artifact_sha256"] for result in results]:
        raise InstrumentationError("instrumentation result hashes do not reconcile")
    failures = _pair_semantic_failures(pair, results)
    if failures:
        raise InstrumentationError(
            f"instrumentation committed semantic mismatch: {', '.join(failures)}"
        )
    semantic = {
        name: results[0][name]
        for name in GATE_SPECIFICATION["exact_equality_fields"]
    }
    if commit.get("exact_semantic_fingerprint") != hash_json(semantic):
        raise InstrumentationError("instrumentation semantic fingerprint mismatch")
    ratio = _throughput_ratio(results)
    observed_ratio = commit.get("throughput_ratio_on_over_off")
    if (
        isinstance(observed_ratio, bool)
        or not isinstance(observed_ratio, (int, float))
        or not math.isfinite(float(observed_ratio))
        or float(observed_ratio) != ratio
    ):
        raise InstrumentationError("instrumentation throughput ratio does not reconcile")
    episode = commit.get("resource_episode")
    if not isinstance(episode, Mapping):
        raise InstrumentationError("instrumentation commit lacks resource episode")
    _validate_episode(
        episode,
        pair=pair,
        manifest=manifest,
        manifest_file_sha256=manifest_file_sha256,
        run_config=run_config,
        run_config_file_sha256=run_config_file_sha256,
    )
    if commit.get("resource_episode_hash") != episode.get("artifact_sha256"):
        raise InstrumentationError("instrumentation episode hash does not reconcile")


def _attempt_record(
    *,
    pair: Mapping[str, Any],
    manifest: Mapping[str, Any],
    manifest_file_sha256: str,
    run_config: Mapping[str, Any],
    run_config_file_sha256: str,
    status: str,
    results: Sequence[Mapping[str, Any]],
    episode: Mapping[str, Any] | None,
    error_type: str = "",
    error_message: str = "",
    failed_worker: Mapping[str, Any] | None = None,
    pair_commit_hash: str | None = None,
) -> dict[str, Any]:
    attempt: dict[str, Any] = {
        "schema_version": ATTEMPT_SCHEMA_VERSION,
        "pair_id": pair["pair_id"],
        "pair_plan_hash": pair["pair_plan_hash"],
        "manifest_content_hash": manifest["content_hash"],
        "manifest_file_sha256": manifest_file_sha256,
        "run_config_content_hash": run_config["content_hash"],
        "run_config_file_sha256": run_config_file_sha256,
        "case_ids": [row["case_id"] for row in _pair_rows(pair)],
        "status": status,
        "attempted_result_hashes": [result["artifact_sha256"] for result in results],
        "attempted_results": [dict(result) for result in results],
        "resource_episode": None if episode is None else dict(episode),
        "resource_episode_hash": None if episode is None else episode["artifact_sha256"],
        "error_type": error_type,
        "error_message": error_message,
        "failed_worker": None if failed_worker is None else dict(failed_worker),
        "pair_commit_hash": pair_commit_hash,
    }
    attempt["content_hash"] = hash_json(attempt)
    return attempt


def _validate_attempt(
    attempt: Mapping[str, Any],
    *,
    pair: Mapping[str, Any],
    manifest: Mapping[str, Any],
    manifest_file_sha256: str,
    run_config: Mapping[str, Any],
    run_config_file_sha256: str,
) -> None:
    required = {
        "schema_version",
        "pair_id",
        "pair_plan_hash",
        "manifest_content_hash",
        "manifest_file_sha256",
        "run_config_content_hash",
        "run_config_file_sha256",
        "case_ids",
        "status",
        "attempted_result_hashes",
        "attempted_results",
        "resource_episode",
        "resource_episode_hash",
        "error_type",
        "error_message",
        "failed_worker",
        "pair_commit_hash",
        "content_hash",
    }
    if set(attempt) != required or attempt.get("schema_version") != ATTEMPT_SCHEMA_VERSION:
        raise InstrumentationError("instrumentation attempt differs from schema")
    _verify_content_hash(attempt, "instrumentation attempt")
    rows = _pair_rows(pair)
    expected = {
        "pair_id": pair["pair_id"],
        "pair_plan_hash": pair["pair_plan_hash"],
        "manifest_content_hash": manifest["content_hash"],
        "manifest_file_sha256": manifest_file_sha256,
        "run_config_content_hash": run_config["content_hash"],
        "run_config_file_sha256": run_config_file_sha256,
        "case_ids": [row["case_id"] for row in rows],
    }
    for name, value in expected.items():
        if attempt.get(name) != value:
            raise InstrumentationError(f"instrumentation attempt differs in {name}")
    status = attempt.get("status")
    if status not in {"in_progress", "invalid_stopped", "complete"}:
        raise InstrumentationError("instrumentation attempt has an unknown status")
    results = attempt.get("attempted_results")
    if not isinstance(results, list) or len(results) > 2:
        raise InstrumentationError("instrumentation attempt result count is invalid")
    for index, result in enumerate(results):
        if not isinstance(result, Mapping):
            raise InstrumentationError("instrumentation attempt embeds malformed result")
        _validate_result_against_row(
            result,
            rows[index],
            manifest=manifest,
            manifest_file_sha256=manifest_file_sha256,
            run_config=run_config,
            run_config_file_sha256=run_config_file_sha256,
        )
    if attempt.get("attempted_result_hashes") != [
        result["artifact_sha256"] for result in results
    ]:
        raise InstrumentationError("instrumentation attempt result hashes do not reconcile")
    episode = attempt.get("resource_episode")
    if episode is None:
        if attempt.get("resource_episode_hash") is not None:
            raise InstrumentationError("instrumentation attempt has an orphan episode hash")
    else:
        if not isinstance(episode, Mapping):
            raise InstrumentationError("instrumentation attempt episode is malformed")
        _validate_episode(
            episode,
            pair=pair,
            manifest=manifest,
            manifest_file_sha256=manifest_file_sha256,
            run_config=run_config,
            run_config_file_sha256=run_config_file_sha256,
            allow_invalid=True,
        )
        if attempt.get("resource_episode_hash") != episode.get("artifact_sha256"):
            raise InstrumentationError("instrumentation attempt episode hash differs")
    if status == "invalid_stopped":
        if not attempt.get("error_type") or not attempt.get("error_message"):
            raise InstrumentationError("invalid instrumentation attempt lacks an error")
        if attempt.get("pair_commit_hash") is not None:
            raise InstrumentationError("invalid instrumentation attempt names a commit")
    elif status == "complete":
        _require_sha256(attempt.get("pair_commit_hash"), "attempt pair-commit hash")
        if len(results) != 2 or episode is None or attempt.get("error_type") or attempt.get(
            "error_message"
        ):
            raise InstrumentationError("complete instrumentation attempt is incomplete")
    elif attempt.get("pair_commit_hash") is not None:
        raise InstrumentationError("in-progress instrumentation attempt names a commit")


def _scientific_preflight(
    manifest: Mapping[str, Any], run_config: Mapping[str, Any]
) -> None:
    from training.azure_guard import is_azure_host

    if platform.system() != "Linux" or not is_azure_host():
        raise InstrumentationError(
            "scientific Pokémon instrumentation requires an already-authorized Azure Linux host"
        )
    expectations = run_config["platform_expectations"]
    observed_platform = {"system": platform.system(), "machine": platform.machine()}
    if observed_platform != expectations:
        raise InstrumentationError(
            f"instrumentation platform mismatch: expected={expectations}, observed={observed_platform}"
        )
    cpus = tuple(run_config["target_cpus"])
    if not hasattr(os, "sched_getaffinity") or not hasattr(os, "sched_setaffinity"):
        raise InstrumentationError("scientific instrumentation lacks Linux affinity APIs")
    available = set(os.sched_getaffinity(0))
    if not set(cpus).issubset(available):
        raise InstrumentationError(
            f"instrumentation target CPUs are unavailable: {sorted(set(cpus) - available)}"
        )
    if not (available - set(cpus)):
        raise InstrumentationError(
            "scientific instrumentation requires a non-benchmark orchestrator CPU"
        )
    observed_env = {key: os.environ.get(key) for key in run_config["thread_env"]}
    if observed_env != run_config["thread_env"]:
        raise InstrumentationError("instrumentation parent thread environment mismatch")
    for state in manifest["config"]["frozen_states"]:
        raw = Path(str(state["state_file"])).read_bytes()
        captured = _load_frozen_capture_bytes(
            raw, expected_sha256=str(state["state_file_sha256"])
        )
        if (
            captured.state_id != state["state_id"]
            or captured.source_game_id != state["source_game_id"]
        ):
            raise InstrumentationError("scientific state identity differs from manifest")


def _validate_limits(
    limits: InstrumentationLimits,
    *,
    manifest: Mapping[str, Any],
    run_config: Mapping[str, Any],
) -> None:
    limits.validate()
    pair_count = int(manifest["config"]["pair_count"])
    if pair_count > limits.maximum_pairs:
        raise InstrumentationError(
            f"instrumentation pair count {pair_count} exceeds bound {limits.maximum_pairs}"
        )
    worst_case = 2.0 * pair_count * float(run_config["worker_timeout_s"])
    if worst_case > float(limits.maximum_total_worker_seconds):
        raise InstrumentationError(
            "instrumentation worst-case worker time exceeds the caller's hard bound"
        )


def _existing_artifact_paths(output: Path) -> tuple[dict[str, Path], dict[str, Path]]:
    commits = {
        path.stem: path for path in sorted((output / "pair_commits").glob("*.json"))
    }
    attempts = {
        path.stem: path for path in sorted((output / "pair_attempts").glob("*.json"))
    }
    return commits, attempts


def _validate_resume_inventory(
    *,
    output: Path,
    manifest: Mapping[str, Any],
    manifest_file_sha256: str,
    run_config: Mapping[str, Any],
    run_config_file_sha256: str,
    resume: bool,
) -> dict[str, dict[str, Any]]:
    pairs = {str(pair["pair_id"]): pair for pair in manifest["pairs"]}
    commit_paths, attempt_paths = _existing_artifact_paths(output)
    unknown = (set(commit_paths) | set(attempt_paths)) - set(pairs)
    if unknown:
        raise InstrumentationError(
            f"instrumentation output references unknown pair IDs: {sorted(unknown)}"
        )
    if not resume and (commit_paths or attempt_paths):
        raise InstrumentationError("instrumentation output exists and resume is false")
    complete: dict[str, dict[str, Any]] = {}
    for pair_id, pair in pairs.items():
        commit_path = commit_paths.get(pair_id)
        attempt_path = attempt_paths.get(pair_id)
        if commit_path is None and attempt_path is None:
            continue
        if commit_path is None or attempt_path is None:
            raise InstrumentationError(
                f"partial instrumentation pair {pair_id}; preserve it and use reserve IDs"
            )
        commit, _ = _load_canonical_json(commit_path)
        attempt, _ = _load_canonical_json(attempt_path)
        _validate_pair_commit(
            commit,
            pair=pair,
            manifest=manifest,
            manifest_file_sha256=manifest_file_sha256,
            run_config=run_config,
            run_config_file_sha256=run_config_file_sha256,
        )
        _validate_attempt(
            attempt,
            pair=pair,
            manifest=manifest,
            manifest_file_sha256=manifest_file_sha256,
            run_config=run_config,
            run_config_file_sha256=run_config_file_sha256,
        )
        if (
            attempt.get("status") != "complete"
            or attempt.get("pair_commit_hash") != commit.get("content_hash")
        ):
            raise InstrumentationError(
                f"instrumentation pair {pair_id} has an invalid/interrupted attempt; "
                "resume is refused and reserve IDs are required"
            )
        complete[pair_id] = commit
    # A journal without a commit is always an interrupted/invalid attempt.
    orphan_attempts = set(attempt_paths) - set(commit_paths)
    if orphan_attempts:
        raise InstrumentationError(
            "instrumentation resume refused after invalid/interrupted attempts: "
            f"{sorted(orphan_attempts)}"
        )
    return complete


def _acquire_pair(
    *,
    pair: Mapping[str, Any],
    manifest: Mapping[str, Any],
    manifest_file_sha256: str,
    run_config: Mapping[str, Any],
    run_config_file_sha256: str,
    attempt_path: Path,
    commit_path: Path,
) -> dict[str, Any]:
    rows = _pair_rows(pair)
    results: list[dict[str, Any]] = []
    episode: dict[str, Any] | None = None
    failed_worker: dict[str, Any] | None = None
    started_attempt = _attempt_record(
        pair=pair,
        manifest=manifest,
        manifest_file_sha256=manifest_file_sha256,
        run_config=run_config,
        run_config_file_sha256=run_config_file_sha256,
        status="in_progress",
        results=results,
        episode=None,
    )
    _atomic_write_new(attempt_path, started_attempt)
    profile = LoadProfile(
        condition="idle",
        worker_count=0,
        target_cpus=tuple(run_config["target_cpus"]),
        chunk_iterations=int(run_config["resource_profile"]["chunk_iterations"]),
        readiness_timeout_s=float(
            run_config["resource_profile"]["readiness_timeout_s"]
        ),
    )
    envelope = ResourceEnvelope(
        profile,
        derive_u32(
            int(manifest["config"]["master_seed"]),
            "pokemon_instrumentation_idle_envelope",
            pair["pair_id"],
        ),
        str(pair["pair_id"]),
        require_affinity=bool(run_config["require_linux_affinity"]),
    )
    commit_written = False
    try:
        with envelope:
            envelope.assert_compliant()
            for row in rows:
                envelope.assert_compliant()
                message = _spawn_case(row, run_config=run_config)
                failed_worker = dict(message["runtime"])
                envelope.record_benchmark_worker(failed_worker)
                result = _normalize_result(
                    row,
                    message,
                    manifest=manifest,
                    manifest_file_sha256=manifest_file_sha256,
                    run_config=run_config,
                    run_config_file_sha256=run_config_file_sha256,
                )
                results.append(result)
                _atomic_replace(
                    attempt_path,
                    _attempt_record(
                        pair=pair,
                        manifest=manifest,
                        manifest_file_sha256=manifest_file_sha256,
                        run_config=run_config,
                        run_config_file_sha256=run_config_file_sha256,
                        status="in_progress",
                        results=results,
                        episode=None,
                    ),
                )
                envelope.assert_compliant()
            envelope.assert_compliant(period_complete=True)
        episode = _episode_payload(
            pair=pair,
            manifest=manifest,
            manifest_file_sha256=manifest_file_sha256,
            run_config=run_config,
            run_config_file_sha256=run_config_file_sha256,
            metadata=envelope.metadata,
            status="scientific_complete",
            error="",
        )
        _validate_episode(
            episode,
            pair=pair,
            manifest=manifest,
            manifest_file_sha256=manifest_file_sha256,
            run_config=run_config,
            run_config_file_sha256=run_config_file_sha256,
        )
        _atomic_replace(
            attempt_path,
            _attempt_record(
                pair=pair,
                manifest=manifest,
                manifest_file_sha256=manifest_file_sha256,
                run_config=run_config,
                run_config_file_sha256=run_config_file_sha256,
                status="in_progress",
                results=results,
                episode=episode,
            ),
        )
        commit = _pair_commit(
            pair=pair,
            results=results,
            episode=episode,
            manifest=manifest,
            manifest_file_sha256=manifest_file_sha256,
            run_config=run_config,
            run_config_file_sha256=run_config_file_sha256,
        )
        _validate_pair_commit(
            commit,
            pair=pair,
            manifest=manifest,
            manifest_file_sha256=manifest_file_sha256,
            run_config=run_config,
            run_config_file_sha256=run_config_file_sha256,
        )
        _atomic_write_new(commit_path, commit)
        commit_written = True
        _atomic_replace(
            attempt_path,
            _attempt_record(
                pair=pair,
                manifest=manifest,
                manifest_file_sha256=manifest_file_sha256,
                run_config=run_config,
                run_config_file_sha256=run_config_file_sha256,
                status="complete",
                results=results,
                episode=episode,
                pair_commit_hash=commit["content_hash"],
            ),
        )
        return commit
    except BaseException as exc:
        if isinstance(exc, InstrumentationWorkerError):
            failed_worker = dict(exc.runtime)
        if commit_written:
            # Preserve the valid immutable commit and the last durable journal;
            # a later resume refuses the inconsistent pair for manual review.
            raise
        error = f"{type(exc).__name__}: {exc}"
        if episode is None and envelope.metadata:
            episode = _episode_payload(
                pair=pair,
                manifest=manifest,
                manifest_file_sha256=manifest_file_sha256,
                run_config=run_config,
                run_config_file_sha256=run_config_file_sha256,
                metadata=envelope.metadata,
                status="invalid_stopped",
                error=error,
            )
        invalid = _attempt_record(
            pair=pair,
            manifest=manifest,
            manifest_file_sha256=manifest_file_sha256,
            run_config=run_config,
            run_config_file_sha256=run_config_file_sha256,
            status="invalid_stopped",
            results=results,
            episode=episode,
            error_type=type(exc).__name__,
            error_message=str(exc),
            failed_worker=failed_worker,
        )
        _validate_attempt(
            invalid,
            pair=pair,
            manifest=manifest,
            manifest_file_sha256=manifest_file_sha256,
            run_config=run_config,
            run_config_file_sha256=run_config_file_sha256,
        )
        _atomic_replace(attempt_path, invalid)
        raise InstrumentationError(
            f"instrumentation acquisition stopped at invalid pair {pair['pair_id']}: {exc}"
        ) from exc


def execute_instrumentation_manifest(
    manifest_path: str | Path,
    *,
    expected_manifest_sha256: str,
    output_dir: str | Path,
    limits: InstrumentationLimits,
    execution_enabled: bool = False,
    resume: bool = False,
    allow_test_mode: bool = False,
) -> dict[str, Any]:
    """Execute a frozen panel on the current host; never starts an Azure VM."""

    manifest, manifest_file_sha256 = _load_canonical_json(
        manifest_path, expected_file_sha256=expected_manifest_sha256
    )
    validate_instrumentation_manifest(manifest)
    run_config, run_config_file_sha256 = _load_canonical_json(
        manifest["config"]["run_config_file"],
        expected_file_sha256=manifest["config"]["run_config_file_sha256"],
    )
    validate_instrumentation_run_config(run_config)
    _validate_limits(limits, manifest=manifest, run_config=run_config)
    if not execution_enabled:
        raise InstrumentationError(
            "instrumentation execution is disabled until explicitly authorized"
        )
    if run_config["test_mode"]:
        if not allow_test_mode:
            raise InstrumentationError("test instrumentation requires allow_test_mode=True")
    else:
        _scientific_preflight(manifest, run_config)
    output = Path(output_dir).resolve()
    complete = _validate_resume_inventory(
        output=output,
        manifest=manifest,
        manifest_file_sha256=manifest_file_sha256,
        run_config=run_config,
        run_config_file_sha256=run_config_file_sha256,
        resume=resume,
    )
    output.mkdir(parents=True, exist_ok=True)
    for pair in manifest["pairs"]:
        pair_id = str(pair["pair_id"])
        if pair_id in complete:
            continue
        commit = _acquire_pair(
            pair=pair,
            manifest=manifest,
            manifest_file_sha256=manifest_file_sha256,
            run_config=run_config,
            run_config_file_sha256=run_config_file_sha256,
            attempt_path=output / "pair_attempts" / f"{pair_id}.json",
            commit_path=output / "pair_commits" / f"{pair_id}.json",
        )
        complete[pair_id] = commit
    expected_ids = {str(pair["pair_id"]) for pair in manifest["pairs"]}
    if set(complete) != expected_ids:
        raise InstrumentationError("instrumentation acquisition ended incomplete")
    ordered_commits = [complete[str(pair["pair_id"])] for pair in manifest["pairs"]]
    summary: dict[str, Any] = {
        "schema_version": "pokemon-instrumentation-acquisition-summary-1.0.0",
        "status": "complete",
        "manifest_content_hash": manifest["content_hash"],
        "manifest_file_sha256": manifest_file_sha256,
        "run_config_content_hash": run_config["content_hash"],
        "run_config_file_sha256": run_config_file_sha256,
        "committed_pair_count": len(ordered_commits),
        "pair_commit_hashes": [commit["content_hash"] for commit in ordered_commits],
        "result_hashes": [
            digest for commit in ordered_commits for digest in commit["result_hashes"]
        ],
        "resource_episode_hashes": [
            commit["resource_episode_hash"] for commit in ordered_commits
        ],
        "machine": system_snapshot(),
    }
    summary["content_hash"] = hash_json(summary)
    _atomic_replace(output / "acquisition_summary.json", summary)
    return summary


def _beta_continued_fraction(a: float, b: float, x: float) -> float:
    """Continued fraction used by the regularized incomplete beta."""

    maximum_iterations = 300
    epsilon = 3.0e-14
    tiny = 1.0e-300
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    value = d
    for iteration in range(1, maximum_iterations + 1):
        even = 2 * iteration
        numerator = iteration * (b - iteration) * x / (
            (qam + even) * (a + even)
        )
        d = 1.0 + numerator * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + numerator / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        value *= d * c
        numerator = -(a + iteration) * (qab + iteration) * x / (
            (a + even) * (qap + even)
        )
        d = 1.0 + numerator * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + numerator / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        value *= delta
        if abs(delta - 1.0) <= epsilon:
            return value
    raise InstrumentationError("Student-t interval beta fraction did not converge")


def _regularized_incomplete_beta(a: float, b: float, x: float) -> float:
    if a <= 0.0 or b <= 0.0 or not 0.0 <= x <= 1.0:
        raise ValueError("invalid regularized-incomplete-beta arguments")
    if x == 0.0:
        return 0.0
    if x == 1.0:
        return 1.0
    front = math.exp(
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log1p(-x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _beta_continued_fraction(a, b, x) / a
    return 1.0 - front * _beta_continued_fraction(b, a, 1.0 - x) / b


def _student_t_cdf(value: float, degrees_of_freedom: int) -> float:
    if degrees_of_freedom <= 0:
        raise ValueError("Student-t degrees of freedom must be positive")
    if value == 0.0:
        return 0.5
    x = degrees_of_freedom / (degrees_of_freedom + value * value)
    tail = 0.5 * _regularized_incomplete_beta(
        degrees_of_freedom / 2.0, 0.5, x
    )
    return 1.0 - tail if value > 0.0 else tail


def _student_t_quantile(probability: float, degrees_of_freedom: int) -> float:
    if not 0.5 < probability < 1.0:
        raise ValueError("only upper Student-t quantiles are supported")
    lower = 0.0
    upper = 1.0
    while _student_t_cdf(upper, degrees_of_freedom) < probability:
        upper *= 2.0
        if upper > 1.0e6:
            raise InstrumentationError("cannot bracket Student-t quantile")
    for _ in range(120):
        middle = (lower + upper) / 2.0
        if _student_t_cdf(middle, degrees_of_freedom) < probability:
            lower = middle
        else:
            upper = middle
    return (lower + upper) / 2.0


def paired_log_ratio_interval(
    ratios: Sequence[float], *, confidence_level: float = 0.90
) -> dict[str, Any]:
    """Geometric paired mean and two-sided Student-t interval on log ratios."""

    if confidence_level != 0.90:
        raise ValueError("the frozen instrumentation interval is exactly 90%")
    if len(ratios) < 2:
        raise ValueError("paired interval requires at least two ratios")
    normalized = [float(value) for value in ratios]
    if any(not math.isfinite(value) or value <= 0.0 for value in normalized):
        raise ValueError("throughput ratios must be finite and positive")
    logs = [math.log(value) for value in normalized]
    mean = statistics.fmean(logs)
    standard_deviation = statistics.stdev(logs)
    critical = _student_t_quantile(0.95, len(logs) - 1)
    margin = critical * standard_deviation / math.sqrt(len(logs))
    return {
        "method": GATE_SPECIFICATION["interval_method"],
        "confidence_level": confidence_level,
        "pair_count": len(logs),
        "degrees_of_freedom": len(logs) - 1,
        "t_critical": critical,
        "geometric_mean": math.exp(mean),
        "lower": math.exp(mean - margin),
        "upper": math.exp(mean + margin),
    }


def _gate_report_hash(report: Mapping[str, Any]) -> str:
    return hash_json(_without_hash(report, "report_hash"))


def validate_instrumentation_gate_report(report: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "decision",
        "manifest_content_hash",
        "manifest_file_sha256",
        "run_config_content_hash",
        "run_config_file_sha256",
        "pilot_gate_file_sha256",
        "gate_specification",
        "expected_pair_count",
        "committed_pair_count",
        "pair_commit_hashes",
        "pair_ratios",
        "paired_interval_90",
        "exact_semantic_equality",
        "invalid_or_interrupted_attempts",
        "reasons",
        "interpretation",
        "report_hash",
    }
    if set(report) != required or report.get("schema_version") != GATE_REPORT_SCHEMA_VERSION:
        raise InstrumentationError("instrumentation gate report differs from schema")
    if report.get("report_hash") != _gate_report_hash(report):
        raise InstrumentationError("instrumentation gate report hash mismatch")
    if report.get("decision") not in {"GO", "NARROW", "STOP"}:
        raise InstrumentationError("instrumentation gate report has an unknown decision")
    if report.get("gate_specification") != GATE_SPECIFICATION:
        raise InstrumentationError("instrumentation gate report changed the criterion")
    expected = report.get("expected_pair_count")
    committed = report.get("committed_pair_count")
    if (
        isinstance(expected, bool)
        or not isinstance(expected, int)
        or expected < 20
        or isinstance(committed, bool)
        or not isinstance(committed, int)
        or not 0 <= committed <= expected
    ):
        raise InstrumentationError("instrumentation gate pair accounting is invalid")
    hashes = report.get("pair_commit_hashes")
    ratios = report.get("pair_ratios")
    if not isinstance(hashes, list) or len(hashes) != committed or any(
        _SHA256_RE.fullmatch(str(value)) is None for value in hashes
    ):
        raise InstrumentationError("instrumentation gate commit hashes are invalid")
    if len(hashes) != len(set(hashes)):
        raise InstrumentationError("instrumentation gate repeats a pair commit hash")
    if not isinstance(ratios, list) or len(ratios) != committed or any(
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) <= 0.0
        for value in ratios
    ):
        raise InstrumentationError("instrumentation gate ratios are invalid")
    exact = report.get("exact_semantic_equality")
    if not isinstance(exact, Mapping) or set(exact) != {
        "passed",
        "checked_fields",
        "failed_pairs",
    }:
        raise InstrumentationError("instrumentation equality evidence differs from schema")
    if exact.get("checked_fields") != GATE_SPECIFICATION["exact_equality_fields"]:
        raise InstrumentationError("instrumentation report changed equality fields")
    if not isinstance(exact.get("failed_pairs"), list):
        raise InstrumentationError("instrumentation report failure ledger is malformed")
    invalid = report.get("invalid_or_interrupted_attempts")
    if not isinstance(invalid, list):
        raise InstrumentationError("instrumentation invalid-attempt ledger is malformed")
    complete = committed == expected and not invalid
    interval = report.get("paired_interval_90")
    if complete:
        recomputed_interval = paired_log_ratio_interval(
            [float(value) for value in ratios]
        )
        if (
            not isinstance(interval, Mapping)
            or interval.get("pair_count") != committed
            or dict(interval) != recomputed_interval
        ):
            raise InstrumentationError("complete gate report lacks paired interval")
    elif interval is not None:
        raise InstrumentationError("incomplete gate report must not estimate an interval")
    expected_exact = complete and not exact["failed_pairs"]
    if exact.get("passed") is not expected_exact:
        raise InstrumentationError("instrumentation equality pass flag does not reconcile")
    expected_decision = "STOP"
    if expected_exact and interval is not None:
        lower = float(interval["lower"])
        upper = float(interval["upper"])
        if lower >= 0.95 and upper <= 1.05:
            expected_decision = "GO"
        elif lower >= 0.90 and upper <= 1.10:
            expected_decision = "NARROW"
    if report.get("decision") != expected_decision:
        raise InstrumentationError("instrumentation report decision does not reconcile")
    if report.get("decision") != "STOP" and (
        not complete or exact.get("passed") is not True
    ):
        raise InstrumentationError("non-STOP instrumentation report lacks complete equality")


def evaluate_instrumentation_gate(
    manifest_path: str | Path,
    *,
    expected_manifest_sha256: str,
    acquisition_dir: str | Path,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Apply the frozen criterion once, without selecting pairs from outcomes."""

    manifest, manifest_file_sha256 = _load_canonical_json(
        manifest_path, expected_file_sha256=expected_manifest_sha256
    )
    validate_instrumentation_manifest(manifest)
    run_config, run_config_file_sha256 = _load_canonical_json(
        manifest["config"]["run_config_file"],
        expected_file_sha256=manifest["config"]["run_config_file_sha256"],
    )
    validate_instrumentation_run_config(run_config)
    output = Path(acquisition_dir).resolve()
    pairs = {str(pair["pair_id"]): pair for pair in manifest["pairs"]}
    commit_paths, attempt_paths = _existing_artifact_paths(output)
    unknown = (set(commit_paths) | set(attempt_paths)) - set(pairs)
    if unknown:
        raise InstrumentationError(
            f"instrumentation gate found unknown pair IDs: {sorted(unknown)}"
        )
    commits: list[dict[str, Any]] = []
    invalid_attempts: list[dict[str, Any]] = []
    equality_failures: list[dict[str, Any]] = []
    for pair in manifest["pairs"]:
        pair_id = str(pair["pair_id"])
        attempt_path = attempt_paths.get(pair_id)
        commit_path = commit_paths.get(pair_id)
        attempt: dict[str, Any] | None = None
        if attempt_path is not None:
            attempt, _ = _load_canonical_json(attempt_path)
            _validate_attempt(
                attempt,
                pair=pair,
                manifest=manifest,
                manifest_file_sha256=manifest_file_sha256,
                run_config=run_config,
                run_config_file_sha256=run_config_file_sha256,
            )
        if commit_path is None:
            invalid_attempts.append(
                {
                    "pair_id": pair_id,
                    "status": "missing" if attempt is None else attempt["status"],
                    "attempt_hash": None if attempt is None else attempt["content_hash"],
                }
            )
            continue
        if attempt is None:
            raise InstrumentationError(
                f"instrumentation gate found commit without journal for {pair_id}"
            )
        commit, _ = _load_canonical_json(commit_path)
        _validate_pair_commit(
            commit,
            pair=pair,
            manifest=manifest,
            manifest_file_sha256=manifest_file_sha256,
            run_config=run_config,
            run_config_file_sha256=run_config_file_sha256,
        )
        if (
            attempt.get("status") != "complete"
            or attempt.get("pair_commit_hash") != commit.get("content_hash")
        ):
            invalid_attempts.append(
                {
                    "pair_id": pair_id,
                    "status": str(attempt.get("status")),
                    "attempt_hash": attempt["content_hash"],
                }
            )
            continue
        failures = _pair_semantic_failures(pair, commit["case_results"])
        if failures:
            equality_failures.append({"pair_id": pair_id, "fields": failures})
        commits.append(commit)

    complete = len(commits) == len(manifest["pairs"]) and not invalid_attempts
    ratios = [float(commit["throughput_ratio_on_over_off"]) for commit in commits]
    interval = paired_log_ratio_interval(ratios) if complete else None
    exact_passed = complete and not equality_failures
    reasons: list[str] = []
    if not complete:
        reasons.append("The frozen pair inventory is incomplete or contains an invalid attempt.")
    if equality_failures:
        reasons.append("At least one off/on pair changed exact state/action/work/cleanup semantics.")
    decision = "STOP"
    if complete and exact_passed and interval is not None:
        lower = float(interval["lower"])
        upper = float(interval["upper"])
        if lower >= 0.95 and upper <= 1.05:
            decision = "GO"
            reasons.append("The paired 90% interval is wholly inside [0.95, 1.05].")
        elif lower >= 0.90 and upper <= 1.10:
            decision = "NARROW"
            reasons.append(
                "The paired 90% interval is inside [0.90, 1.10] but not [0.95, 1.05]."
            )
        else:
            reasons.append("The paired 90% interval extends outside [0.90, 1.10].")
    if not reasons:
        reasons.append("The frozen instrumentation criterion produced no valid passing result.")
    interpretation = {
        "GO": "Instrumentation equivalence passed the frozen pilot criterion.",
        "NARROW": (
            "Only the prospective NARROW path is available after reducing instrumentation "
            "and freezing a new disjoint bank."
        ),
        "STOP": "Instrumentation evidence does not authorize the Pokémon final acquisition.",
    }[decision]
    report: dict[str, Any] = {
        "schema_version": GATE_REPORT_SCHEMA_VERSION,
        "decision": decision,
        "manifest_content_hash": manifest["content_hash"],
        "manifest_file_sha256": manifest_file_sha256,
        "run_config_content_hash": run_config["content_hash"],
        "run_config_file_sha256": run_config_file_sha256,
        "pilot_gate_file_sha256": manifest["config"]["pilot_gate_file_sha256"],
        "gate_specification": dict(GATE_SPECIFICATION),
        "expected_pair_count": len(manifest["pairs"]),
        "committed_pair_count": len(commits),
        "pair_commit_hashes": [commit["content_hash"] for commit in commits],
        "pair_ratios": ratios,
        "paired_interval_90": interval,
        "exact_semantic_equality": {
            "passed": exact_passed,
            "checked_fields": list(GATE_SPECIFICATION["exact_equality_fields"]),
            "failed_pairs": equality_failures,
        },
        "invalid_or_interrupted_attempts": invalid_attempts,
        "reasons": reasons,
        "interpretation": interpretation,
    }
    report["report_hash"] = _gate_report_hash(report)
    validate_instrumentation_gate_report(report)
    if output_path is not None:
        _atomic_write_new(Path(output_path).resolve(), report)
    return report
