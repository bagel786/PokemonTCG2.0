"""Sequential, resumable, fail-closed acquisition on the authorized host."""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import platform
import queue
import re
import subprocess
import time
import traceback
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from .adapters.pokemon import PokemonAdapterConfig
from .canonical import canonical_json_bytes, derive_u32, hash_file, hash_json
from .freeze import load_and_validate_freeze_manifest
from .game import GameExecutor
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
from .scheduler import validate_schedule, verify_schedule_content_hash
from .telemetry import DecisionTelemetry, GameTelemetry


SCIENTIFIC_PHASES = frozenset({"pilot", "final"})
ARTIFACT_HASH_KEYS = frozenset(
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
RUN_CONFIG_ARTIFACT_KEYS = ARTIFACT_HASH_KEYS - {"run_config"}
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
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


def _canonical_line(value: Any) -> bytes:
    return canonical_json_bytes(value)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {path}:{line_number}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"JSONL record is not an object at {path}:{line_number}")
            rows.append(value)
    return rows


def _append_jsonl(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _canonical_line(value)
    with path.open("ab") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = canonical_json_bytes(value)
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _artifact_without_hash(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(value)
    payload.pop("artifact_sha256", None)
    return payload


def _infrastructure_result(row: Mapping[str, Any], error: str) -> dict[str, Any]:
    game = {
        "schema_version": "game-1.0.0",
        "case_id": str(row["case_id"]),
        "block_id": str(row["block_id"]),
        "agent_id": str(row["agent_id"]),
        "score": None,
        "winner": None,
        "terminal_status": "infrastructure_error",
        "decision_count": 0,
        "completed_work_units": 0,
        "completed_simulations": 0,
        "completed_nodes": 0,
        "completed_sweeps": 0,
        "forward_model_calls": 0,
        "decision_record_hashes": [],
        "error_type": "WorkerFailure",
        "error_message": error,
    }
    payload = {
        "schedule_row": dict(row),
        "game": game,
        "decisions": [],
        "gameplay_decisions": 0,
        "public_trace_sha256": None,
        "observed_worker": None,
    }
    payload["artifact_sha256"] = hash_json(payload)
    return payload


def _child_affinity() -> list[int] | None:
    if not hasattr(os, "sched_getaffinity"):
        return None
    return sorted(int(cpu) for cpu in os.sched_getaffinity(0))


def _apply_child_affinity(target_cpus: tuple[int, ...]) -> bool:
    if not hasattr(os, "sched_setaffinity"):
        return False
    os.sched_setaffinity(0, set(target_cpus))
    return True


def _run_unit(
    output_queue: Any,
    rows: list[dict[str, Any]],
    engine_path: str,
    configs: dict[str, dict[str, Any]],
    anchor_deck_path: str,
    anchor_model_path: str,
    max_decisions: int,
    target_cpus: tuple[int, ...],
    require_affinity: bool,
    thread_env: dict[str, str],
    expected_parent_pid: int,
) -> None:
    parent_guard = arm_parent_death_kill(
        expected_parent_pid=expected_parent_pid,
        required=require_affinity,
    )
    started_process_ns = time.process_time_ns()
    runtime: dict[str, Any] = {
        "observed_process_id": os.getpid(),
        "observed_affinity": _child_affinity(),
        "target_cpus": list(target_cpus),
        "process_time_ns_start": started_process_ns,
        "thread_env": {},
    }
    try:
        runtime["parent_death_kill_armed"] = parent_guard is not None
        for key, value in thread_env.items():
            os.environ[str(key)] = str(value)
        affinity_applied = _apply_child_affinity(target_cpus)
        runtime["affinity_applied"] = affinity_applied
        runtime["thread_env"] = {key: os.environ.get(key) for key in sorted(thread_env)}
        runtime["observed_affinity"] = _child_affinity()
        if require_affinity and runtime["observed_affinity"] != sorted(target_cpus):
            raise RuntimeError(
                "benchmark child affinity mismatch: "
                f"requested={list(target_cpus)}, observed={runtime['observed_affinity']}"
            )
        executor = GameExecutor(
            engine_path=engine_path,
            adapter_configs={key: PokemonAdapterConfig(**value) for key, value in configs.items()},
            anchor_deck_path=anchor_deck_path,
            anchor_model_path=anchor_model_path,
            max_decisions=max_decisions,
        )
        results = [executor.run(row) for row in rows]
        runtime["process_time_ns_end"] = time.process_time_ns()
        runtime["process_time_ns_delta"] = (
            runtime["process_time_ns_end"] - runtime["process_time_ns_start"]
        )
        output_queue.put({"ok": True, "results": results, "runtime": runtime})
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


def _execution_units(rows: Iterable[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Convert ordered schedule rows to one fresh case or one persistent session."""

    ordered = sorted(rows, key=lambda row: int(row["execution_index"]))
    units: list[list[dict[str, Any]]] = []
    index = 0
    while index < len(ordered):
        row = ordered[index]
        if row["lifecycle"] == "fresh":
            units.append([row])
            index += 1
            continue
        process_id = row["process_instance_id"]
        group: list[dict[str, Any]] = []
        while index < len(ordered) and ordered[index]["process_instance_id"] == process_id:
            group.append(ordered[index])
            index += 1
        expected_slots = list(range(len(group)))
        observed_slots = [int(item["sequence_index"]) for item in group]
        if observed_slots != expected_slots:
            raise ValueError(
                f"persistent session {process_id} is not contiguous and zero-indexed: "
                f"{observed_slots}"
            )
        units.append(group)
    return units


def validate_schedule_for_acquisition(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Validate structure, cryptographic content, phase, and derived case IDs."""

    if not isinstance(manifest, Mapping):
        raise ValueError("schedule manifest must be an object")
    value = dict(manifest)
    verify_schedule_content_hash(value)
    validate_schedule(value)
    phase = value.get("config", {}).get("phase")
    if phase not in {"smoke", *SCIENTIFIC_PHASES}:
        raise ValueError(f"invalid acquisition phase: {phase}")
    for row in value["rows"]:
        if row.get("phase") != phase:
            raise ValueError(f"case {row.get('case_id')} has a phase mismatch")
        expected = (
            f"{phase}-case-"
            f"{hash_json({k: v for k, v in row.items() if k != 'case_id'})[:20]}"
        )
        if row.get("case_id") != expected:
            raise ValueError(
                f"derived case ID mismatch: supplied={row.get('case_id')}, expected={expected}"
            )
    return value


def validate_schedule_file(
    manifest: Mapping[str, Any], schedule_path: str | Path
) -> None:
    path = Path(schedule_path).resolve()
    raw = path.read_bytes()
    disk_manifest = json.loads(raw)
    if raw != canonical_json_bytes(disk_manifest):
        raise ValueError("schedule file is not canonical JSON")
    if canonical_json_bytes(disk_manifest) != canonical_json_bytes(dict(manifest)):
        raise ValueError("in-memory schedule differs from the scheduled file")
    validate_schedule_for_acquisition(disk_manifest)


def _validate_scientific_runtime(
    *,
    target_cpus: tuple[int, ...],
    load_workers: int,
    max_decisions: int,
    worker_timeout_s: float,
    thread_env: Mapping[str, str] | None,
    platform_expectations: Mapping[str, Any] | None,
) -> None:
    if (
        not target_cpus
        or any(isinstance(cpu, bool) or not isinstance(cpu, int) or cpu < 0 for cpu in target_cpus)
        or len(set(target_cpus)) != len(target_cpus)
    ):
        raise ValueError("scientific target CPUs must be unique non-negative integers")
    if isinstance(load_workers, bool) or not isinstance(load_workers, int) or load_workers <= 0:
        raise ValueError("scientific load_workers must be positive")
    if isinstance(max_decisions, bool) or not isinstance(max_decisions, int) or max_decisions <= 0:
        raise ValueError("scientific max_decisions must be positive")
    if (
        isinstance(worker_timeout_s, bool)
        or not isinstance(worker_timeout_s, (int, float))
        or worker_timeout_s <= 0
    ):
        raise ValueError("scientific worker_timeout_s must be positive")
    controls = dict(thread_env or {})
    if not REQUIRED_THREAD_ENV <= set(controls):
        raise ValueError(
            f"scientific thread controls must include {sorted(REQUIRED_THREAD_ENV)}"
        )
    for key in REQUIRED_THREAD_ENV - {"PYTHONHASHSEED"}:
        if controls.get(key) != "1":
            raise ValueError(f"scientific {key} must equal 1")
    if not str(controls.get("PYTHONHASHSEED", "")).isdigit():
        raise ValueError("scientific PYTHONHASHSEED must be a decimal integer")
    expectations = dict(platform_expectations or {})
    if set(expectations) != {"system", "machine"}:
        raise ValueError("scientific platform expectations require exactly system and machine")


def _validate_result_against_row(
    result: Mapping[str, Any], row: Mapping[str, Any]
) -> None:
    case_id = str(row["case_id"])
    game = result.get("game")
    result_row = result.get("schedule_row")
    if not isinstance(game, Mapping) or not isinstance(result_row, Mapping):
        raise ValueError(f"terminal result {case_id} lacks game or schedule row")
    if str(game.get("case_id")) != case_id or str(result_row.get("case_id")) != case_id:
        raise ValueError(f"terminal result case identity mismatch for {case_id}")
    if canonical_json_bytes(dict(result_row)) != canonical_json_bytes(dict(row)):
        raise ValueError(f"terminal result embeds a non-identical schedule row for {case_id}")
    if not isinstance(game.get("terminal_status"), str) or not game["terminal_status"]:
        raise ValueError(f"terminal result {case_id} lacks terminal status")
    try:
        game_record = GameTelemetry(**dict(game))
        game_record.validate()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"terminal result {case_id} has invalid game telemetry") from exc
    if game_record.schema_version != "game-1.0.0":
        raise ValueError(f"terminal result {case_id} has an unexpected game schema")
    if (
        game_record.block_id != str(row["block_id"])
        or game_record.agent_id != str(row["agent_id"])
    ):
        raise ValueError(f"terminal result {case_id} has mismatched game identity")
    if game_record.terminal_status == "completed" and game_record.score is None:
        raise ValueError(f"completed terminal result {case_id} lacks a score")

    decisions = result.get("decisions")
    if not isinstance(decisions, list):
        raise ValueError(f"terminal result {case_id} decisions must be an array")
    parsed_decisions: list[DecisionTelemetry] = []
    for decision_index, raw_decision in enumerate(decisions):
        if not isinstance(raw_decision, Mapping):
            raise ValueError(
                f"terminal result {case_id} decision {decision_index} is not an object"
            )
        try:
            decision = DecisionTelemetry(**dict(raw_decision))
            decision.validate()
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"terminal result {case_id} has invalid decision {decision_index}"
            ) from exc
        expected_context = {
            "schema_version": "decision-1.1.0",
            "case_id": case_id,
            "block_id": str(row["block_id"]),
            "decision_index": decision_index,
            "agent_id": str(row["agent_id"]),
            "budget_mode": str(row["budget_mode"]),
            "load_condition": str(row["load_condition"]),
            "lifecycle": str(row["lifecycle"]),
            "lifecycle_id": str(row["lifecycle_id"]),
            "process_instance_id": str(row["process_instance_id"]),
            "sequence_index": int(row["sequence_index"]),
            "load_batch_id": str(row["load_batch_id"]),
            "requested_budget_ns": row["requested_budget_ns"],
            "requested_work_units": row["requested_work_units"],
        }
        mismatched = [
            field
            for field, expected in expected_context.items()
            if getattr(decision, field) != expected
        ]
        expected_seed = derive_u32(
            int(row["agent_seed"]), "game_decision", decision_index
        )
        if decision.agent_seed_hash != hash_json({"agent_seed": expected_seed}):
            mismatched.append("agent_seed_hash")
        if decision.extra.get("stop_completed_units") != decision.completed_work_units:
            mismatched.append("stop_completed_units")
        identity = decision.extra.get("selected_action_identity")
        if identity is None or decision.selected_action_hash != hash_json(identity):
            mismatched.append("selected_action_hash")
        for digest_field in ("state_hash", "agent_seed_hash", "selected_action_hash"):
            if SHA256_PATTERN.fullmatch(str(getattr(decision, digest_field))) is None:
                mismatched.append(digest_field)
        if mismatched:
            raise ValueError(
                f"terminal result {case_id} decision {decision_index} differs on "
                f"{sorted(set(mismatched))}"
            )
        parsed_decisions.append(decision)

    expected_decision_hashes = [hash_json(dict(value)) for value in decisions]
    aggregate_fields = {
        "decision_count": len(parsed_decisions),
        "completed_work_units": sum(value.completed_work_units for value in parsed_decisions),
        "completed_simulations": sum(value.completed_simulations for value in parsed_decisions),
        "completed_nodes": sum(value.completed_nodes for value in parsed_decisions),
        "completed_sweeps": sum(value.completed_sweeps for value in parsed_decisions),
        "forward_model_calls": sum(value.forward_model_calls for value in parsed_decisions),
        "decision_record_hashes": expected_decision_hashes,
    }
    aggregate_mismatches = [
        field
        for field, expected in aggregate_fields.items()
        if getattr(game_record, field) != expected
    ]
    if aggregate_mismatches:
        raise ValueError(
            f"terminal result {case_id} game/decision totals differ on "
            f"{aggregate_mismatches}"
        )
    worker = result.get("observed_worker")
    if parsed_decisions and (
        not isinstance(worker, Mapping)
        or any(
            decision.worker_pid != worker.get("observed_process_id")
            for decision in parsed_decisions
        )
    ):
        raise ValueError(f"terminal result {case_id} decision PID evidence mismatch")
    gameplay_decisions = result.get("gameplay_decisions")
    if (
        isinstance(gameplay_decisions, bool)
        or not isinstance(gameplay_decisions, int)
        or gameplay_decisions < 0
    ):
        raise ValueError(f"terminal result {case_id} has invalid gameplay decision count")
    public_trace = result.get("public_trace_sha256")
    if game_record.terminal_status == "completed" and (
        not isinstance(public_trace, str)
        or SHA256_PATTERN.fullmatch(public_trace) is None
    ):
        raise ValueError(f"completed terminal result {case_id} lacks a public trace hash")
    supplied_hash = result.get("artifact_sha256")
    expected_hash = hash_json(_artifact_without_hash(result))
    if supplied_hash != expected_hash:
        raise ValueError(
            f"terminal result artifact hash mismatch for {case_id}: "
            f"supplied={supplied_hash}, expected={expected_hash}"
        )


def validate_terminal_accounting(
    manifest: Mapping[str, Any],
    results: Iterable[Mapping[str, Any]],
    *,
    require_complete: bool,
) -> dict[str, Any]:
    scheduled_rows = {str(row["case_id"]): row for row in manifest["rows"]}
    if len(scheduled_rows) != len(manifest["rows"]):
        raise ValueError("schedule case IDs are not unique")
    materialized = list(results)
    observed: list[str] = []
    for result in materialized:
        game = result.get("game")
        if not isinstance(game, Mapping):
            raise ValueError("terminal result lacks a game object")
        case_id = str(game.get("case_id"))
        if case_id in scheduled_rows:
            _validate_result_against_row(result, scheduled_rows[case_id])
        observed.append(case_id)
    counts = Counter(observed)
    duplicates = sorted(case_id for case_id, count in counts.items() if count != 1)
    unexpected = sorted(set(observed) - set(scheduled_rows))
    missing = sorted(set(scheduled_rows) - set(observed))
    if duplicates or unexpected or (require_complete and missing):
        raise ValueError(
            f"terminal accounting failure: duplicates={duplicates[:5]}, "
            f"unexpected={unexpected[:5]}, missing={missing[:5]}"
        )
    return {
        "scheduled_cases": len(scheduled_rows),
        "observed_cases": len(observed),
        "missing_cases": missing,
        "terminal_status_counts": dict(
            Counter(result["game"]["terminal_status"] for result in materialized)
        ),
    }


def _load_batches(manifest: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    batches: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(manifest["rows"], key=lambda item: int(item["execution_index"])):
        batches[str(row["load_batch_id"])].append(row)
    return dict(batches)


def _validate_episode(
    episode: Mapping[str, Any], batch_id: str, period_rows: list[dict[str, Any]]
) -> None:
    if episode.get("load_batch_id") != batch_id:
        raise ValueError(f"resource episode has wrong batch ID for {batch_id}")
    expected_ids = [row["case_id"] for row in period_rows]
    if episode.get("period_case_ids") != expected_ids:
        raise ValueError(f"resource episode has wrong ordered case IDs for {batch_id}")
    metadata = dict(episode)
    supplied = metadata.pop("metadata_hash", None)
    metadata.pop("period_case_ids", None)
    if supplied != hash_json(metadata):
        raise ValueError(f"resource episode metadata hash mismatch for {batch_id}")


def _validate_scientific_episode(episode: Mapping[str, Any]) -> None:
    profile = episode.get("profile", {})
    target_cpus = sorted(profile.get("target_cpus", []))
    if episode.get("cleanup_succeeded") is not True:
        raise RuntimeError("scientific resource episode lacks successful cleanup evidence")
    orchestrator = episode.get("orchestrator_observed_affinity")
    if not isinstance(orchestrator, list) or set(orchestrator) & set(target_cpus):
        raise RuntimeError("scientific orchestrator affinity overlaps benchmark CPUs")
    benchmark_workers = episode.get("benchmark_workers")
    if not isinstance(benchmark_workers, list) or not benchmark_workers:
        raise RuntimeError("scientific resource episode lacks benchmark child evidence")
    for worker in benchmark_workers:
        if (
            worker.get("exitcode") != 0
            or worker.get("parent_death_kill_armed") is not True
            or worker.get("observed_process_id") != worker.get("spawned_process_id")
            or worker.get("observed_affinity") != target_cpus
            or not isinstance(worker.get("process_time_ns_delta"), int)
            or worker["process_time_ns_delta"] < 0
        ):
            raise RuntimeError("scientific benchmark child PID/affinity/CPU evidence is invalid")
    load_workers = episode.get("workers")
    if profile.get("condition") == "idle":
        if load_workers:
            raise RuntimeError("idle resource episode unexpectedly launched co-runners")
        return
    if not isinstance(load_workers, list) or len(load_workers) != profile.get("worker_count"):
        raise RuntimeError("loaded resource episode has wrong co-runner cardinality")
    for worker in load_workers:
        if (
            worker.get("affinity_applied") is not True
            or worker.get("parent_death_kill_armed") is not True
            or worker.get("observed_affinity") != target_cpus
            or not isinstance(worker.get("cpu_ticks_delta"), int)
            or worker["cpu_ticks_delta"] <= 0
        ):
            raise RuntimeError("loaded resource episode lacks valid CPU/affinity evidence")
    exitcodes = episode.get("worker_exitcodes", {})
    if len(exitcodes) != len(load_workers) or any(code != 0 for code in exitcodes.values()):
        raise RuntimeError("loaded resource episode has invalid co-runner exit evidence")


def _validate_pokemon_period_journal(
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
        experiment="pokemon",
        manifest_content_hash=str(manifest["content_hash"]),
        phase=str(manifest["config"]["phase"]),
        load_batch_id=batch_id,
        load_condition=condition,
        period_case_ids=[str(row["case_id"]) for row in period_rows],
    )
    results = list(journal["case_results"])
    observed_ids = [str(result.get("game", {}).get("case_id")) for result in results]
    expected_ids = [str(row["case_id"]) for row in period_rows]
    if observed_ids != expected_ids:
        raise ValueError("Pokemon period journal result order mismatch")
    for result, row in zip(results, period_rows):
        _validate_result_against_row(result, row)
    _assert_unit_scientifically_usable(results)
    episode = journal["resource_episode"]
    _validate_episode(episode, batch_id, period_rows)
    if scientific:
        _validate_scientific_episode(episode)


def _validate_existing_period_journals(
    output: Path,
    manifest: Mapping[str, Any],
    complete_batches: set[str],
    existing_results: list[dict[str, Any]],
    existing_episodes: list[dict[str, Any]],
) -> list[str]:
    batches = _load_batches(manifest)
    journals_by_batch: dict[str, dict[str, Mapping[str, Any]]] = defaultdict(dict)
    scientific = manifest.get("config", {}).get("phase") in SCIENTIFIC_PHASES
    for path, journal in discover_period_journals(output):
        batch_id = str(journal.get("load_batch_id", ""))
        condition = str(journal.get("load_condition", ""))
        if batch_id not in batches:
            raise RuntimeError(f"period journal names unknown load batch {batch_id!r}")
        expected_path = period_journal_path(output, batch_id, condition)
        if path != expected_path:
            raise RuntimeError(f"period journal is stored at the wrong path: {path}")
        if condition in journals_by_batch[batch_id]:
            raise RuntimeError(f"duplicate {condition} period journal for {batch_id}")
        period_rows = [
            row for row in batches[batch_id] if row["load_condition"] == condition
        ]
        _validate_pokemon_period_journal(
            journal,
            manifest,
            batch_id,
            period_rows,
            scientific=scientific,
        )
        journals_by_batch[batch_id][condition] = journal

    result_by_id = {
        str(result["game"]["case_id"]): result for result in existing_results
    }
    episode_by_key = {
        (
            str(episode["load_batch_id"]),
            str(episode["profile"]["condition"]),
        ): episode
        for episode in existing_episodes
    }
    hashes: list[str] = []
    for batch_id, by_condition in sorted(journals_by_batch.items()):
        if batch_id not in complete_batches:
            raise RuntimeError(
                f"paired load batch {batch_id} has crash-durable period evidence but no "
                "atomic batch commit; preserve it and use new frozen reserve IDs"
            )
        if set(by_condition) != {"idle", "loaded"}:
            raise RuntimeError(
                f"committed load batch {batch_id} has an incomplete period-journal pair"
            )
        for condition in ("idle", "loaded"):
            journal = by_condition[condition]
            expected_results = [
                result_by_id[str(case_id)] for case_id in journal["period_case_ids"]
            ]
            if journal["case_result_hashes"] != [
                result["artifact_sha256"] for result in expected_results
            ]:
                raise RuntimeError(
                    f"period journal and committed results disagree for {batch_id}:{condition}"
                )
            episode = episode_by_key.get((batch_id, condition))
            if episode is None or journal["resource_episode_hash"] != episode["metadata_hash"]:
                raise RuntimeError(
                    f"period journal and committed episode disagree for {batch_id}:{condition}"
                )
            hashes.append(str(journal["content_hash"]))
    return hashes


def validate_batch_resume_state(
    manifest: Mapping[str, Any],
    results: list[dict[str, Any]],
    episodes: list[dict[str, Any]],
    commits: list[dict[str, Any]],
) -> set[str]:
    """Return complete load pairs; reject every partial or orphaned pair."""

    validate_terminal_accounting(manifest, results, require_complete=False)
    batches = _load_batches(manifest)
    result_ids = {str(result["game"]["case_id"]) for result in results}
    episodes_by_batch: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for episode in episodes:
        episodes_by_batch[str(episode.get("load_batch_id"))].append(episode)
    commits_by_batch: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for commit in commits:
        commits_by_batch[str(commit.get("load_batch_id"))].append(commit)
    unknown = (set(episodes_by_batch) | set(commits_by_batch)) - set(batches)
    if unknown:
        raise RuntimeError(f"resume state contains unknown load batches: {sorted(unknown)}")

    complete: set[str] = set()
    for batch_id, batch_rows in batches.items():
        expected_ids = {str(row["case_id"]) for row in batch_rows}
        observed_ids = expected_ids & result_ids
        batch_episodes = episodes_by_batch.get(batch_id, [])
        batch_commits = commits_by_batch.get(batch_id, [])
        if not (observed_ids or batch_episodes or batch_commits):
            continue
        if observed_ids != expected_ids or len(batch_episodes) != 2 or len(batch_commits) != 1:
            raise RuntimeError(
                f"paired load batch {batch_id} is partially materialized; preserve it and "
                "continue only from a new frozen reserve schedule"
            )
        for condition in ("idle", "loaded"):
            period_rows = [row for row in batch_rows if row["load_condition"] == condition]
            matching = [
                episode
                for episode in batch_episodes
                if episode.get("profile", {}).get("condition") == condition
            ]
            if len(matching) != 1:
                raise RuntimeError(
                    f"paired load batch {batch_id} does not have one {condition} episode"
                )
            _validate_episode(matching[0], batch_id, period_rows)
        commit = batch_commits[0]
        expected_result_hashes = [
            result["artifact_sha256"]
            for result in sorted(
                (result for result in results if result["game"]["case_id"] in expected_ids),
                key=lambda result: int(result["schedule_row"]["execution_index"]),
            )
        ]
        expected_episode_hashes = [episode["metadata_hash"] for episode in batch_episodes]
        if (
            commit.get("schema_version") != "load-batch-commit-1.0.0"
            or commit.get("case_ids") != [row["case_id"] for row in batch_rows]
            or commit.get("result_hashes") != expected_result_hashes
            or Counter(commit.get("episode_hashes", [])) != Counter(expected_episode_hashes)
        ):
            raise RuntimeError(f"paired load batch commit mismatch for {batch_id}")
        supplied_commit_hash = commit.get("content_hash")
        commit_payload = dict(commit)
        commit_payload.pop("content_hash", None)
        if supplied_commit_hash != hash_json(commit_payload):
            raise RuntimeError(f"paired load batch commit hash mismatch for {batch_id}")
        batch_results = [
            result for result in results if result["game"]["case_id"] in expected_ids
        ]
        statuses = [result["game"]["terminal_status"] for result in batch_results]
        batch_status = commit.get("batch_status")
        if batch_status == "scientific_complete" and "infrastructure_error" in statuses:
            raise RuntimeError(f"scientific load batch {batch_id} contains infrastructure errors")
        if batch_status == "infrastructure_invalid" and set(statuses) != {
            "infrastructure_error"
        }:
            raise RuntimeError(f"invalid load batch {batch_id} was not terminalized atomically")
        if batch_status not in {"scientific_complete", "infrastructure_invalid"}:
            raise RuntimeError(f"load batch {batch_id} has invalid commit status")
        if manifest.get("config", {}).get("phase") in SCIENTIFIC_PHASES:
            if batch_status == "scientific_complete":
                for episode in batch_episodes:
                    _validate_scientific_episode(episode)
                for result in batch_results:
                    observed = result.get("observed_worker")
                    if not isinstance(observed, Mapping):
                        raise RuntimeError(
                            f"scientific result {result['game']['case_id']} lacks child PID evidence"
                        )
        complete.add(batch_id)
    return complete


def assert_scientific_resume_allowed(
    manifest: Mapping[str, Any], commits: Iterable[Mapping[str, Any]]
) -> None:
    if manifest.get("config", {}).get("phase") not in SCIENTIFIC_PHASES:
        return
    invalid = sorted(
        str(commit.get("load_batch_id"))
        for commit in commits
        if commit.get("batch_status") == "infrastructure_invalid"
    )
    if invalid:
        raise RuntimeError(
            "scientific acquisition is terminated after invalid paired load batches "
            f"{invalid}; preserve the artifacts and use new frozen reserve IDs"
        )


def compute_artifact_hashes(
    *,
    engine_binary: str | Path,
    engine_source: str | Path,
    hero_deck: str | Path,
    hero_model: str | Path,
    opponent_deck: str | Path,
    opponent_model: str | Path,
    run_config: str | Path,
) -> dict[str, str]:
    paths = {
        "engine_binary": engine_binary,
        "engine_source": engine_source,
        "hero_deck": hero_deck,
        "hero_model": hero_model,
        "opponent_deck": opponent_deck,
        "opponent_model": opponent_model,
        "run_config": run_config,
    }
    return {key: hash_file(Path(value).resolve()) for key, value in paths.items()}


def verify_scientific_artifacts(
    manifest: Mapping[str, Any], actual_hashes: Mapping[str, str]
) -> None:
    expected = manifest.get("config", {}).get("artifact_hashes")
    if set(actual_hashes) != ARTIFACT_HASH_KEYS:
        raise ValueError(
            f"actual artifact hashes must name exactly {sorted(ARTIFACT_HASH_KEYS)}"
        )
    if not isinstance(expected, Mapping) or set(expected) != ARTIFACT_HASH_KEYS:
        raise ValueError(
            "scientific schedule artifact_hashes must name exactly "
            f"{sorted(ARTIFACT_HASH_KEYS)}"
        )
    for key in sorted(ARTIFACT_HASH_KEYS):
        observed = str(actual_hashes[key])
        frozen = str(expected[key])
        if not SHA256_PATTERN.fullmatch(observed) or frozen != observed:
            raise ValueError(
                f"artifact hash mismatch for {key}: frozen={frozen}, observed={observed}"
            )


def _git_text(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def validate_final_authorization(
    manifest: Mapping[str, Any],
    *,
    schedule_path: str | Path | None,
    freeze_manifest_path: str | Path | None,
    actual_artifact_hashes: Mapping[str, str],
) -> dict[str, Any]:
    """Refuse final seeds unless the approved, pushed freeze is exact and clean."""

    if manifest.get("config", {}).get("phase") != "final":
        return {}
    if schedule_path is None or freeze_manifest_path is None:
        raise RuntimeError("final acquisition requires schedule and freeze-manifest paths")
    schedule_file = Path(schedule_path).resolve()
    freeze_file = Path(freeze_manifest_path).resolve()
    root = Path(__file__).resolve().parents[1]
    freeze = load_and_validate_freeze_manifest(
        freeze_file,
        repository_root=root,
        verify_files=True,
        require_final_authorized=True,
    )
    protocol_commit = freeze.get("protocol_commit")
    if not isinstance(protocol_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", protocol_commit):
        raise RuntimeError("freeze manifest lacks an exact protocol commit")
    approval = freeze.get("human_approval")
    if not isinstance(approval, Mapping) or approval.get("approved") is not True:
        raise RuntimeError("final acquisition lacks structured explicit human approval")
    if approval.get("protocol_commit") != protocol_commit:
        raise RuntimeError("human approval does not name the frozen protocol commit")
    current_commit = _git_text(root, "rev-parse", "HEAD")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", protocol_commit, current_commit],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if ancestor.returncode != 0:
        raise RuntimeError(
            f"frozen protocol commit {protocol_commit} is not an ancestor of {current_commit}"
        )
    current_branch = _git_text(root, "branch", "--show-current")
    if freeze.get("branch") != current_branch:
        raise RuntimeError(
            f"current branch {current_branch} is not frozen branch {freeze.get('branch')}"
        )
    tracked_changes = _git_text(root, "status", "--porcelain", "--untracked-files=no")
    if tracked_changes:
        raise RuntimeError("final acquisition requires a clean tracked worktree")
    try:
        schedule_relative = schedule_file.relative_to(root)
        freeze_relative = freeze_file.relative_to(root)
    except ValueError as exc:
        raise RuntimeError("final schedule and freeze manifest must be inside the repository") from exc
    _git_text(root, "ls-files", "--error-unmatch", str(schedule_relative))
    _git_text(root, "ls-files", "--error-unmatch", str(freeze_relative))
    allowed_authorization_files = {str(freeze_relative)}
    attestation_path = approval.get("attestation_path")
    if attestation_path is not None:
        if not isinstance(attestation_path, str):
            raise RuntimeError("human approval attestation_path must be a repository path")
        attestation_file = (root / attestation_path).resolve()
        try:
            attestation_relative = attestation_file.relative_to(root)
        except ValueError as exc:
            raise RuntimeError("human approval attestation must be inside the repository") from exc
        _git_text(root, "ls-files", "--error-unmatch", str(attestation_relative))
        allowed_authorization_files.add(str(attestation_relative))
        expected_attestation_hash = approval.get("attestation_sha256")
        if expected_attestation_hash != hash_file(attestation_file):
            raise RuntimeError("human approval attestation hash mismatch")
        attestation = json.loads(attestation_file.read_text(encoding="utf-8"))
        if (
            not isinstance(attestation, Mapping)
            or attestation.get("approved") is not True
            or attestation.get("protocol_commit") != protocol_commit
        ):
            raise RuntimeError("human approval attestation does not approve the protocol commit")
    changed_after_protocol = set(
        filter(None, _git_text(root, "diff", "--name-only", f"{protocol_commit}..HEAD").splitlines())
    )
    unauthorized_changes = changed_after_protocol - allowed_authorization_files
    if unauthorized_changes:
        raise RuntimeError(
            "files other than explicit authorization metadata changed after protocol freeze: "
            f"{sorted(unauthorized_changes)}"
        )
    try:
        upstream_commit = _git_text(root, "rev-parse", "@{upstream}")
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("frozen branch has no pushed upstream") from exc
    if upstream_commit != current_commit:
        raise RuntimeError(
            f"current authorization commit {current_commit} is not pushed upstream "
            f"{upstream_commit}"
        )
    frozen_manifest_hash = freeze.get("final_manifest_sha256")
    observed_manifest_hash = hash_file(schedule_file)
    if frozen_manifest_hash != observed_manifest_hash:
        raise RuntimeError(
            "final schedule file hash does not match freeze manifest: "
            f"frozen={frozen_manifest_hash}, observed={observed_manifest_hash}"
        )
    frozen_artifacts = freeze.get("artifact_hashes")
    if not isinstance(frozen_artifacts, Mapping) or dict(frozen_artifacts) != dict(
        actual_artifact_hashes
    ):
        raise RuntimeError("freeze-manifest artifact hashes do not match current artifacts")
    verify_scientific_artifacts(manifest, actual_artifact_hashes)
    return freeze


def _periods_for_batch(batch_rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    periods: list[list[dict[str, Any]]] = []
    ordered = sorted(batch_rows, key=lambda row: int(row["execution_index"]))
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
        raise ValueError(f"load batch {batch_rows[0]['load_batch_id']} lacks two contiguous periods")
    return periods


def _attach_worker_runtime(
    result: Mapping[str, Any], runtime: Mapping[str, Any]
) -> dict[str, Any]:
    payload = dict(result)
    payload["observed_worker"] = dict(runtime)
    payload["artifact_sha256"] = hash_json(_artifact_without_hash(payload))
    return payload


def _run_process_unit(
    context: Any,
    unit: list[dict[str, Any]],
    *,
    engine_path: Path,
    config_payload: dict[str, dict[str, Any]],
    anchor_deck_path: Path,
    anchor_model_path: Path,
    max_decisions: int,
    target_cpus: tuple[int, ...],
    require_affinity: bool,
    thread_env: dict[str, str],
    worker_timeout_s: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    output_queue = context.Queue()
    process = context.Process(
        target=_run_unit,
        args=(
            output_queue,
            unit,
            str(engine_path),
            config_payload,
            str(anchor_deck_path),
            str(anchor_model_path),
            int(max_decisions),
            tuple(target_cpus),
            bool(require_affinity),
            dict(thread_env),
            os.getpid(),
        ),
        name=f"study-{unit[0]['process_instance_id']}",
    )
    process.start()
    try:
        try:
            message = output_queue.get(timeout=worker_timeout_s)
        except queue.Empty:
            stop_process(process)
            message = {
                "ok": False,
                "error": "worker result timeout",
                "runtime": {
                    "observed_process_id": process.pid,
                    "observed_affinity": None,
                    "target_cpus": list(target_cpus),
                },
            }
        else:
            process.join(timeout=30.0)
            if process.is_alive():
                stop_process(process)
                message = {
                    "ok": False,
                    "error": "worker did not exit after producing result",
                    "runtime": message.get("runtime", {}),
                }
            elif process.exitcode != 0:
                message = {
                    "ok": False,
                    "error": f"worker exited with code {process.exitcode}",
                    "runtime": message.get("runtime", {}),
                }
    except BaseException:
        # Parent-side cancellation/IPC failure must never orphan a benchmark
        # child.  If hard kill itself fails, leave IPC open and surface that
        # stronger safety failure.
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
    if runtime.get("observed_process_id") != process.pid:
        message = {"ok": False, "error": "worker PID evidence mismatch", "runtime": runtime}
    if require_affinity and runtime.get("observed_affinity") != sorted(target_cpus):
        message = {"ok": False, "error": "worker affinity evidence mismatch", "runtime": runtime}
    if require_affinity and runtime.get("parent_death_kill_armed") is not True:
        message = {
            "ok": False,
            "error": "worker parent-death protection evidence mismatch",
            "runtime": runtime,
        }
    if message.get("ok"):
        raw_results = message.get("results")
        if not isinstance(raw_results, list) or len(raw_results) != len(unit):
            message = {
                "ok": False,
                "error": "worker result cardinality mismatch",
                "runtime": runtime,
            }
        else:
            results = [_attach_worker_runtime(result, runtime) for result in raw_results]
            by_case = {str(result.get("game", {}).get("case_id")): result for result in results}
            expected = {str(row["case_id"]): row for row in unit}
            if set(by_case) != set(expected) or len(by_case) != len(results):
                message = {
                    "ok": False,
                    "error": "worker result case-set mismatch",
                    "runtime": runtime,
                }
            else:
                for case_id, row in expected.items():
                    _validate_result_against_row(by_case[case_id], row)
                return results, runtime
    error = str(message.get("error", "unknown worker failure"))
    results = [
        _attach_worker_runtime(_infrastructure_result(row, error), runtime) for row in unit
    ]
    return results, runtime


def _assert_unit_scientifically_usable(results: Iterable[Mapping[str, Any]]) -> None:
    fatal_game_statuses = {
        "engine_error",
        "infrastructure_error",
        "protocol_invalid",
    }
    fatal_decision_statuses = {
        "cleanup_error",
        "fixed_work_invalid",
        "illegal_action",
        "infrastructure_error",
    }
    fatal: list[str] = []
    for result in results:
        game = result.get("game", {})
        case_id = str(game.get("case_id"))
        game_status = game.get("terminal_status")
        if game_status in fatal_game_statuses:
            fatal.append(f"{case_id}:game:{game_status}")
        for decision in result.get("decisions", ()):
            decision_status = decision.get("terminal_status")
            if decision_status in fatal_decision_statuses:
                fatal.append(
                    f"{case_id}:decision:{decision.get('decision_index')}:{decision_status}"
                )
    if fatal:
        raise RuntimeError(
            "fatal scientific result invalidates the whole paired load batch: "
            f"{fatal}"
        )


def _invalid_episode(
    batch_id: str, period_rows: list[dict[str, Any]], error: str
) -> dict[str, Any]:
    first = period_rows[0]
    metadata = {
        "schema_version": "resource-episode-1.0.0",
        "load_batch_id": batch_id,
        "load_seed": int(first["load_seed"]),
        "profile": {
            "condition": str(first["load_condition"]),
            "worker_count": None,
            "target_cpus": None,
        },
        "status": "infrastructure_invalid",
        "error": error,
        "before": system_snapshot(),
        "after": system_snapshot(),
        "workers": [],
        "benchmark_workers": [],
        "cleanup_succeeded": False,
    }
    return {
        **metadata,
        "period_case_ids": [row["case_id"] for row in period_rows],
        "metadata_hash": hash_json(metadata),
    }


def acquire_schedule(
    manifest: Mapping[str, Any],
    *,
    engine_path: str | Path,
    adapter_configs: Mapping[str, PokemonAdapterConfig],
    anchor_deck_path: str | Path,
    anchor_model_path: str | Path,
    output_dir: str | Path,
    target_cpus: tuple[int, ...] = (0,),
    load_workers: int = 1,
    max_decisions: int = 2_000,
    worker_timeout_s: float = 3_600.0,
    schedule_path: str | Path | None = None,
    freeze_manifest_path: str | Path | None = None,
    actual_artifact_hashes: Mapping[str, str] | None = None,
    artifact_paths: Mapping[str, str | Path] | None = None,
    thread_env: Mapping[str, str] | None = None,
    platform_expectations: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Acquire every scheduled case once, never silently replacing a failure."""

    checked_manifest = validate_schedule_for_acquisition(manifest)
    if schedule_path is not None:
        validate_schedule_file(checked_manifest, schedule_path)
    phase = str(checked_manifest["config"]["phase"])
    scientific = phase in SCIENTIFIC_PHASES
    scheduled_agents = set(checked_manifest["config"]["agents"])
    if set(adapter_configs) != scheduled_agents:
        raise ValueError("adapter IDs do not exactly match scheduled agent IDs")
    expected_algorithms = {
        "one_ply_value_v1": "one_ply_value",
        "flat_rollout_v1": "flat_rollout",
        "puct_tree_v1": "puct_tree",
    }
    for agent_id, config in adapter_configs.items():
        config.validate()
        if config.agent_id != agent_id or expected_algorithms.get(agent_id) != config.algorithm:
            raise ValueError(f"adapter identity/algorithm mismatch for {agent_id}")
    if scientific:
        if platform.system() != "Linux":
            raise RuntimeError(f"{phase} acquisition requires Linux")
        _validate_scientific_runtime(
            target_cpus=target_cpus,
            load_workers=load_workers,
            max_decisions=max_decisions,
            worker_timeout_s=worker_timeout_s,
            thread_env=thread_env,
            platform_expectations=platform_expectations,
        )
        if artifact_paths is None or set(artifact_paths) != ARTIFACT_HASH_KEYS:
            raise RuntimeError(
                f"{phase} acquisition requires exact paths for {sorted(ARTIFACT_HASH_KEYS)}"
            )
        observed_artifact_hashes = {
            key: hash_file(Path(path).resolve()) for key, path in artifact_paths.items()
        }
        if actual_artifact_hashes is not None and dict(actual_artifact_hashes) != (
            observed_artifact_hashes
        ):
            raise RuntimeError("precomputed artifact hashes differ from current file hashes")
        actual_artifact_hashes = observed_artifact_hashes
        verify_scientific_artifacts(checked_manifest, observed_artifact_hashes)
        if Path(engine_path).resolve() != Path(artifact_paths["engine_binary"]).resolve():
            raise ValueError("engine path differs from the frozen engine artifact")
        if Path(anchor_deck_path).resolve() != Path(artifact_paths["opponent_deck"]).resolve():
            raise ValueError("anchor deck differs from the frozen opponent deck")
        if Path(anchor_model_path).resolve() != Path(artifact_paths["opponent_model"]).resolve():
            raise ValueError("anchor model differs from the frozen opponent model")
        for agent_id, config in adapter_configs.items():
            configured_paths = {
                "engine_binary": config.seeded_engine_path,
                "hero_deck": config.hero_deck_path,
                "hero_model": config.hero_model_path,
                "opponent_deck": config.opponent_deck_path,
                "opponent_model": config.opponent_model_path,
            }
            for key, configured_path in configured_paths.items():
                if Path(configured_path).resolve() != Path(artifact_paths[key]).resolve():
                    raise ValueError(f"adapter {agent_id} path differs from frozen {key}")
            if config.initialize_engine:
                raise ValueError(f"adapter {agent_id} must not initialize the engine")
        expectations = dict(platform_expectations or {})
        if expectations.get("system") != platform.system():
            raise RuntimeError(
                f"platform system mismatch: expected={expectations.get('system')}, "
                f"observed={platform.system()}"
            )
        if expectations.get("machine") != platform.machine():
            raise RuntimeError(
                f"platform machine mismatch: expected={expectations.get('machine')}, "
                f"observed={platform.machine()}"
            )
    validate_final_authorization(
        checked_manifest,
        schedule_path=schedule_path,
        freeze_manifest_path=freeze_manifest_path,
        actual_artifact_hashes=dict(actual_artifact_hashes or {}),
    )

    output = Path(output_dir)
    raw_path = output / "raw_cases.jsonl"
    envelope_path = output / "resource_episodes.jsonl"
    commit_path = output / "load_batch_commits.jsonl"
    invalid_path = output / "invalid_attempts.jsonl"
    existing = _read_jsonl(raw_path)
    existing_episodes = _read_jsonl(envelope_path)
    existing_commits = _read_jsonl(commit_path)
    complete_batches = validate_batch_resume_state(
        checked_manifest, existing, existing_episodes, existing_commits
    )
    _validate_existing_period_journals(
        output,
        checked_manifest,
        complete_batches,
        existing,
        existing_episodes,
    )
    assert_scientific_resume_allowed(checked_manifest, existing_commits)
    batches = _load_batches(checked_manifest)
    context = mp.get_context("spawn")
    config_payload = {key: asdict(value) for key, value in adapter_configs.items()}
    acquired = list(existing)
    invalid_batches = sum(
        1 for commit in existing_commits if commit.get("batch_status") != "scientific_complete"
    )

    for batch_id, batch_rows in batches.items():
        if batch_id in complete_batches:
            continue
        batch_results: list[dict[str, Any]] = []
        batch_episodes: list[dict[str, Any]] = []
        attempted_results: list[dict[str, Any]] = []
        periods = _periods_for_batch(batch_rows)
        batch_error: str | None = None
        try:
            for period_rows in periods:
                first = period_rows[0]
                period_results: list[dict[str, Any]] = []
                period_episode: dict[str, Any] | None = None
                profile = LoadProfile(
                    condition=str(first["load_condition"]),
                    worker_count=(0 if first["load_condition"] == "idle" else int(load_workers)),
                    target_cpus=tuple(target_cpus),
                )
                envelope = ResourceEnvelope(
                    profile,
                    int(first["load_seed"]),
                    batch_id,
                    require_affinity=scientific,
                )
                try:
                    with envelope:
                        for unit in _execution_units(period_rows):
                            envelope.assert_compliant()
                            results, runtime = _run_process_unit(
                                context,
                                unit,
                                engine_path=Path(engine_path).resolve(),
                                config_payload=config_payload,
                                anchor_deck_path=Path(anchor_deck_path).resolve(),
                                anchor_model_path=Path(anchor_model_path).resolve(),
                                max_decisions=max_decisions,
                                target_cpus=tuple(target_cpus),
                                require_affinity=scientific,
                                thread_env={str(k): str(v) for k, v in (thread_env or {}).items()},
                                worker_timeout_s=worker_timeout_s,
                            )
                            envelope.record_benchmark_worker(runtime)
                            attempted_results.extend(results)
                            batch_results.extend(results)
                            period_results.extend(results)
                            # Deliberately after every unit, including the last.
                            envelope.assert_compliant()
                            _assert_unit_scientifically_usable(results)
                        # Distinct period-end check requires positive load CPU evidence.
                        envelope.assert_compliant(period_complete=True)
                finally:
                    if envelope.metadata:
                        metadata = dict(envelope.metadata)
                        episode = {
                            **metadata,
                            "period_case_ids": [row["case_id"] for row in period_rows],
                            "metadata_hash": hash_json(metadata),
                        }
                        batch_episodes.append(episode)
                        period_episode = episode
                if period_episode is None:
                    raise RuntimeError("completed load period produced no resource episode")
                order = {
                    str(row["case_id"]): index for index, row in enumerate(period_rows)
                }
                period_results.sort(
                    key=lambda result: order[str(result["game"]["case_id"])]
                )
                journal = build_period_journal(
                    experiment="pokemon",
                    manifest_content_hash=str(checked_manifest["content_hash"]),
                    phase=phase,
                    load_batch_id=batch_id,
                    load_condition=str(first["load_condition"]),
                    period_rows=period_rows,
                    case_results=period_results,
                    resource_episode=period_episode,
                )
                _validate_pokemon_period_journal(
                    journal,
                    checked_manifest,
                    batch_id,
                    period_rows,
                    scientific=scientific,
                )
                write_period_journal(
                    period_journal_path(output, batch_id, str(first["load_condition"])),
                    journal,
                )
        except BaseException as exc:
            batch_error = f"{type(exc).__name__}: {exc}"

        if batch_error is not None:
            invalid_batches += 1
            invalid_attempt = {
                "schema_version": "invalid-load-batch-attempt-1.0.0",
                "load_batch_id": batch_id,
                "error": batch_error,
                "attempted_results": attempted_results,
                "resource_episodes": batch_episodes,
                "attempted_result_hashes": [
                    result["artifact_sha256"] for result in attempted_results
                ],
                "resource_episode_hashes": [
                    episode["metadata_hash"] for episode in batch_episodes
                ],
            }
            invalid_attempt["content_hash"] = hash_json(invalid_attempt)
            _append_jsonl(
                invalid_path,
                invalid_attempt,
            )
            batch_results = [
                _infrastructure_result(row, f"paired load batch invalid: {batch_error}")
                for row in batch_rows
            ]
            by_condition = {
                episode.get("profile", {}).get("condition"): episode
                for episode in batch_episodes
            }
            batch_episodes = [
                by_condition.get(str(period[0]["load_condition"]))
                or _invalid_episode(batch_id, period, batch_error)
                for period in periods
            ]

        batch_results.sort(key=lambda result: int(result["schedule_row"]["execution_index"]))
        validate_terminal_accounting(
            {**checked_manifest, "rows": batch_rows}, batch_results, require_complete=True
        )
        for episode in batch_episodes:
            condition = str(episode["profile"]["condition"])
            period_rows = [row for row in batch_rows if row["load_condition"] == condition]
            _validate_episode(episode, batch_id, period_rows)
        for episode in batch_episodes:
            _append_jsonl(envelope_path, episode)
        for result in batch_results:
            _append_jsonl(raw_path, result)
            acquired.append(result)
        commit = {
            "schema_version": "load-batch-commit-1.0.0",
            "load_batch_id": batch_id,
            "batch_status": (
                "scientific_complete" if batch_error is None else "infrastructure_invalid"
            ),
            "case_ids": [row["case_id"] for row in batch_rows],
            "result_hashes": [result["artifact_sha256"] for result in batch_results],
            "episode_hashes": [episode["metadata_hash"] for episode in batch_episodes],
        }
        commit["content_hash"] = hash_json(commit)
        # The marker makes any interruption before this line a rejected partial batch.
        _append_jsonl(commit_path, commit)
        if scientific and batch_error is not None:
            raise RuntimeError(
                f"scientific acquisition terminated after invalid paired load batch {batch_id}; "
                "preserve the committed artifacts and use new frozen reserve IDs"
            )

    accounting = validate_terminal_accounting(checked_manifest, acquired, require_complete=True)
    completed = validate_batch_resume_state(
        checked_manifest,
        acquired,
        _read_jsonl(envelope_path),
        _read_jsonl(commit_path),
    )
    if completed != set(batches):
        raise RuntimeError("acquisition ended without every paired load batch committed")
    summary = {
        "schema_version": "acquisition-summary-1.0.0",
        "status": "complete",
        "phase": phase,
        "schedule_content_hash": checked_manifest["content_hash"],
        "schedule_file_sha256": (
            hash_file(Path(schedule_path).resolve()) if schedule_path is not None else None
        ),
        "artifact_hashes": dict(actual_artifact_hashes or {}),
        "engine_path": str(Path(engine_path).resolve()),
        "machine": system_snapshot(),
        "committed_load_batches": len(completed),
        "invalid_load_batches": invalid_batches,
        **accounting,
    }
    summary["content_hash"] = hash_json(summary)
    _atomic_write_json(output / "acquisition_summary.json", summary)
    return summary
