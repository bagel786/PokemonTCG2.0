#!/usr/bin/env python3
"""Seeded local-engine determinism proof and paired common-random-number evaluation."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import multiprocessing as mp
import os
import platform
import random
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from cg.api import OptionType, SelectContext, to_observation_class
from ptcg_ai.external import ExternalSubmissionAgent
from ptcg_ai.safety import sanitize_selection


DEFAULT_ENGINE = ROOT / "artifacts" / "deterministic_engine" / "bin" / "cg.dll"
DEFAULT_PRODUCTION_ENGINE = ROOT / "vendor" / "cg" / "cg.dll"
DEFAULT_CANDIDATE = (
    ROOT
    / "artifacts"
    / "elite_policy_candidates"
    / "temporal_schema3_full"
    / "package"
    / "extracted"
)
DEFAULT_CONTROL = ROOT / "artifacts" / "recovery_probes" / "extracted" / "a2"

UINT32_MODULUS = 1 << 32
SEED_CONVERSION_RULE = "engine_seed_uint32 = scheduled_seed & 0xffffffff"
PROCESS_START_METHOD = "spawn"
ORDER_SEED_OFFSET = 1_000_000
PROOF_EXECUTION_VARIANTS = (
    "serial-forward",
    "serial-reverse",
    "parallel-forward",
    "parallel-reverse",
)

_SCHEDULE_FINGERPRINT_FIELDS = (
    "task_id",
    "pair_index",
    "arm",
    "engine",
    "hero",
    "opponent",
    "scheduled_seed",
    "engine_seed_uint32",
    "actual_order",
    "physical_seat",
    "trace_mode",
    "max_decisions",
    "hero_env",
    "opponent_env",
    "enqueue_position",
)

_DETERMINISM_SIGNATURE_FIELDS = (
    "task_id",
    "pair_index",
    "arm",
    "seed",
    "requested_seed",
    "scheduled_seed",
    "engine_seed_uint32",
    "actual_order",
    "physical_seat",
    "win",
    "draw",
    "decisions",
    "hero_policy_errors",
    "opponent_policy_errors",
    "trace_sha256",
    "public_trace_sha256",
    "trace_bytes",
)


class StartData(ctypes.Structure):
    _fields_ = [
        ("battlePtr", ctypes.c_void_p),
        ("errorPlayer", ctypes.c_int),
        ("errorType", ctypes.c_int),
    ]


class SerialData(ctypes.Structure):
    _fields_ = [
        ("json", ctypes.c_char_p),
        ("data", ctypes.POINTER(ctypes.c_ubyte)),
        ("count", ctypes.c_int),
        ("selectPlayer", ctypes.c_int),
    ]


def load_deck(path: Path) -> list[int]:
    deck = [int(line) for line in path.read_text().splitlines() if line.strip()]
    if len(deck) != 60:
        raise ValueError(f"deck override must contain 60 cards: {path}")
    return deck


def parse_env(values: Iterable[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise ValueError(f"env override must be KEY=VALUE: {item}")
        key, value = item.split("=", 1)
        parsed[key] = value
    return parsed


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_path(path: Path) -> str:
    if path.is_file():
        return sha256_file(path)
    digest = hashlib.sha256()
    for child in sorted(
        item
        for item in path.rglob("*")
        if item.is_file() and "__pycache__" not in item.parts and item.suffix != ".pyc"
    ):
        relative = child.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256_file(child)))
    return digest.hexdigest()


def seed_to_uint32(seed: int) -> int:
    """Return the exact unsigned 32-bit value passed to BattleStartSeeded."""
    return int(seed) & 0xFFFFFFFF


def _scheduled_seed(task: dict[str, Any]) -> int:
    values = [
        int(task[key])
        for key in ("seed", "requested_seed", "scheduled_seed")
        if key in task
    ]
    if not values:
        raise ValueError("task requires seed, requested_seed, or scheduled_seed")
    if len(set(values)) != 1:
        raise ValueError("seed, requested_seed, and scheduled_seed must agree")
    return values[0]


def assert_converted_seed_uniqueness(tasks: Iterable[dict[str, Any]]) -> None:
    """Reject distinct scheduled seeds that narrow to the same uint32 value.

    A paired schedule intentionally repeats one scheduled seed across its two arms.
    Exact repeats within that pair are allowed; reuse across distinct units and
    collisions between distinct Python integers are not.
    """
    assignment_by_engine_seed: dict[int, tuple[int, tuple[Any, ...]]] = {}
    collisions: list[tuple[int, int, int]] = []
    for task in tasks:
        scheduled = _scheduled_seed(task)
        converted = seed_to_uint32(scheduled)
        if "pair_index" in task:
            schedule_unit = (str(task.get("actual_order")), int(task["pair_index"]))
        else:
            schedule_unit = (str(task.get("task_id")),)
        prior = assignment_by_engine_seed.setdefault(converted, (scheduled, schedule_unit))
        if prior[0] != scheduled:
            collisions.append((converted, prior[0], scheduled))
        elif prior[1] != schedule_unit:
            raise ValueError(
                "schedule reuses engine seed "
                f"{converted} for distinct units {prior[1]} and {schedule_unit}"
            )
    if collisions:
        converted, first, second = collisions[0]
        raise ValueError(
            "schedule contains a uint32 engine-seed collision: "
            f"{first} and {second} both convert to {converted}"
        )


def _trace_mode(task: dict[str, Any]) -> str:
    mode = task.get("trace_mode")
    if mode is None:
        mode = "full" if task.get("capture_trace", False) else "none"
    mode = str(mode)
    if mode not in {"none", "digest", "full"}:
        raise ValueError("trace_mode must be one of: none, digest, full")
    return mode


def _prepare_tasks(tasks: list[dict[str, Any]], workers: int) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for enqueue_position, source in enumerate(tasks):
        task = dict(source)
        scheduled = _scheduled_seed(task)
        converted = seed_to_uint32(scheduled)
        supplied_converted = task.get("engine_seed_uint32")
        if supplied_converted is not None and int(supplied_converted) != converted:
            raise ValueError(
                f"task {task.get('task_id')} engine_seed_uint32 does not match {SEED_CONVERSION_RULE}"
            )
        task.update(
            {
                # `seed` remains as a compatibility alias for historical readers.
                "seed": scheduled,
                "requested_seed": scheduled,
                "scheduled_seed": scheduled,
                "engine_seed_uint32": converted,
                "seed_conversion_rule": SEED_CONVERSION_RULE,
                "trace_mode": _trace_mode(task),
                "enqueue_position": int(task.get("enqueue_position", enqueue_position)),
                "worker_count": workers,
                "process_start_method": PROCESS_START_METHOD,
            }
        )
        prepared.append(task)
    assert_converted_seed_uniqueness(prepared)
    return prepared


def schedule_fingerprint(tasks: list[dict[str, Any]]) -> str:
    """Hash static schedule inputs, excluding timing and process identifiers."""
    prepared = _prepare_tasks(tasks, int(tasks[0].get("worker_count", 1)) if tasks else 1)
    schedule = [
        {key: task.get(key) for key in _SCHEDULE_FINGERPRINT_FIELDS}
        for task in prepared
    ]
    return hashlib.sha256(_canonical_json(schedule)).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _run_identity(
    *,
    mode: str,
    tasks: list[dict[str, Any]],
    protocol_id: str,
    protocol_commit: str | None,
    run_uuid: str | None,
    artifacts: dict[str, str],
    execution_plan: dict[str, Any],
) -> dict[str, Any]:
    resolved_uuid = str(uuid.UUID(run_uuid)) if run_uuid else str(uuid.uuid4())
    resolved_commit = protocol_commit or _git_commit()
    fingerprint = schedule_fingerprint(tasks)
    manifest = {
        "mode": mode,
        "protocol_id": protocol_id,
        "protocol_commit": resolved_commit,
        "schedule_fingerprint_sha256": fingerprint,
        "artifacts": artifacts,
        "execution_plan": execution_plan,
    }
    return {
        "protocol_id": protocol_id,
        "protocol_commit": resolved_commit,
        "run_uuid": resolved_uuid,
        "schedule_fingerprint_sha256": fingerprint,
        "run_fingerprint_sha256": hashlib.sha256(_canonical_json(manifest)).hexdigest(),
        "run_fingerprint_scope": (
            "protocol, artifact hashes, static schedule, and execution plan; "
            "excludes run UUID, wall-clock timing, and process identifiers"
        ),
    }


def _attach_run_identity(
    tasks: list[dict[str, Any]], identity: dict[str, Any]
) -> list[dict[str, Any]]:
    return [{**task, **identity} for task in tasks]


def _execution_environment() -> dict[str, Any]:
    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "process_start_method": PROCESS_START_METHOD,
        "python_hash_seed": "0",
    }


class SeededEngine:
    """Thin ctypes adapter for the isolated BattleStartSeeded export."""

    def __init__(self, dll_path: Path):
        self.dll_path = dll_path.resolve()
        self.lib = ctypes.CDLL(str(self.dll_path))
        self.lib.GameInitialize.argtypes = []
        self.lib.GameInitialize.restype = None
        self.lib.GameInitialize()
        self.lib.BattleStartSeeded.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_uint32]
        self.lib.BattleStartSeeded.restype = StartData
        self.lib.BattleFinish.argtypes = [ctypes.c_void_p]
        self.lib.BattleFinish.restype = None
        self.lib.GetBattleData.argtypes = [ctypes.c_void_p]
        self.lib.GetBattleData.restype = SerialData
        self.lib.Select.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.c_int]
        self.lib.Select.restype = ctypes.c_int
        self.lib.AllCard.argtypes = []
        self.lib.AllCard.restype = ctypes.c_char_p
        self.lib.AllAttack.argtypes = []
        self.lib.AllAttack.restype = ctypes.c_char_p

    def _observation(self, battle_ptr: int) -> dict:
        serial = self.lib.GetBattleData(battle_ptr)
        observation = json.loads(serial.json.decode("utf-8"))
        observation["search_begin_input"] = ctypes.string_at(serial.data, serial.count).decode("ascii")
        return observation

    def start(self, deck0: list[int], deck1: list[int], seed: int) -> tuple[int, dict]:
        if len(deck0) != 60 or len(deck1) != 60:
            raise ValueError("each engine deck must contain 60 cards")
        cards = (ctypes.c_int * 120)(*(deck0 + deck1))
        started = self.lib.BattleStartSeeded(cards, ctypes.c_uint32(seed).value)
        if not started.battlePtr:
            raise RuntimeError(
                f"seeded engine rejected deck for player {started.errorPlayer}: {started.errorType}"
            )
        return int(started.battlePtr), self._observation(started.battlePtr)

    def select(self, battle_ptr: int, selection: list[int]) -> dict:
        values = (ctypes.c_int * len(selection))(*selection)
        error = self.lib.Select(battle_ptr, values, len(selection))
        if error:
            raise RuntimeError(f"seeded engine rejected selection with error {error}")
        return self._observation(battle_ptr)

    def finish(self, battle_ptr: int) -> None:
        self.lib.BattleFinish(battle_ptr)


_ENGINE: SeededEngine | None = None
_ENGINE_PATH: Path | None = None


def get_engine(path: str | Path) -> SeededEngine:
    global _ENGINE, _ENGINE_PATH
    resolved = Path(path).resolve()
    if _ENGINE is None:
        _ENGINE = SeededEngine(resolved)
        _ENGINE_PATH = resolved
    elif resolved != _ENGINE_PATH:
        raise RuntimeError("a worker cannot load two deterministic engine builds")
    return _ENGINE


def _policy_errors(agent: ExternalSubmissionAgent) -> int:
    total = int(getattr(agent, "errors", 0) or 0)
    inner = getattr(agent.module, "_AGENT", None)
    total += int(getattr(inner, "errors", 0) or 0)
    return total


def _forced_order(select, hero_seat: int, order: str) -> list[int]:
    seat_zero_first = (order == "first") == (hero_seat == 0)
    desired = OptionType.YES if seat_zero_first else OptionType.NO
    choices = [index for index, option in enumerate(select.option) if option.type == desired]
    if len(choices) != 1:
        raise RuntimeError("seeded evaluation found an invalid IS_FIRST choice set")
    return sanitize_selection(select, choices, 1)


def _canonical_line(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8") + b"\n"


def _public_observation_sha256(raw: dict[str, Any]) -> str:
    """Hash gameplay JSON, excluding the pointer-layout-sensitive search snapshot."""
    public = {key: value for key, value in raw.items() if key != "search_begin_input"}
    encoded = json.dumps(public, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _run_game(task: dict[str, Any]) -> dict[str, Any]:
    game_started = time.perf_counter()
    scheduled_seed = _scheduled_seed(task)
    engine_seed = seed_to_uint32(scheduled_seed)
    supplied_engine_seed = int(task.get("engine_seed_uint32", engine_seed))
    if supplied_engine_seed != engine_seed:
        raise ValueError(f"engine seed does not satisfy {SEED_CONVERSION_RULE}")
    random.seed(scheduled_seed)
    np.random.seed(engine_seed)
    engine = get_engine(task["engine"])
    hero_path = Path(task["hero"])
    opponent_path = Path(task["opponent"])
    hero_seat = int(task["physical_seat"])
    order = str(task["actual_order"])
    trace_mode = _trace_mode(task)
    capture_trace = trace_mode != "none"
    max_decisions = int(task.get("max_decisions", 2_000))

    hero_env = dict(task.get("hero_env") or {})
    opponent_env = dict(task.get("opponent_env") or {})
    hero = ExternalSubmissionAgent(hero_path, hero_env)
    opponent = ExternalSubmissionAgent(opponent_path, opponent_env)
    agents = {hero_seat: hero, 1 - hero_seat: opponent}
    decks = [hero.deck, opponent.deck] if hero_seat == 0 else [opponent.deck, hero.deck]
    battle_ptr = 0
    trace_digest = hashlib.sha256()
    trace_payload = bytearray() if trace_mode == "full" else None
    trace_bytes = 0
    first_player = None
    decisions = 0
    completed: dict[str, Any] | None = None

    def append_trace(event: dict[str, Any]) -> None:
        nonlocal trace_bytes
        line = _canonical_line(event)
        trace_digest.update(line)
        trace_bytes += len(line)
        if trace_payload is not None:
            trace_payload.extend(line)

    try:
        battle_ptr, raw = engine.start(decks[0], decks[1], engine_seed)
        while True:
            obs = to_observation_class(raw)
            if obs.current is not None and int(obs.current.firstPlayer) in (0, 1):
                observed = int(obs.current.firstPlayer)
                if first_player is None:
                    first_player = observed
                elif observed != first_player:
                    raise RuntimeError("firstPlayer changed after latch")
            if obs.current is not None and int(obs.current.result) >= 0:
                if first_player is None:
                    raise RuntimeError("terminal seeded game has no latched firstPlayer")
                observed_order = "first" if first_player == hero_seat else "second"
                if observed_order != order:
                    raise RuntimeError(f"requested {order}, observed {observed_order}")
                result = int(obs.current.result)
                terminal = {
                    "event": "terminal",
                    "result": result,
                    "hero_win": int(result == hero_seat),
                    "draw": int(result == 2),
                    "decisions": decisions,
                }
                if capture_trace:
                    terminal["public_observation_sha256"] = _public_observation_sha256(raw)
                    append_trace(terminal)
                trace_sha256 = trace_digest.hexdigest() if capture_trace else None
                completed = {
                    "task_id": task["task_id"],
                    "pair_index": int(task.get("pair_index", -1)),
                    "arm": task.get("arm"),
                    # `seed` is retained as a compatibility alias.
                    "seed": scheduled_seed,
                    "requested_seed": scheduled_seed,
                    "scheduled_seed": scheduled_seed,
                    "engine_seed_uint32": engine_seed,
                    "seed_conversion_rule": SEED_CONVERSION_RULE,
                    "actual_order": observed_order,
                    "physical_seat": hero_seat,
                    "win": int(result == hero_seat),
                    "draw": int(result == 2),
                    "decisions": decisions,
                    "hero_policy_errors": _policy_errors(hero),
                    "opponent_policy_errors": _policy_errors(opponent),
                    "trace_mode": trace_mode,
                    "trace_sha256": trace_sha256,
                    "public_trace_sha256": trace_sha256,
                    "trace_bytes": trace_bytes if capture_trace else 0,
                    "trace": bytes(trace_payload) if trace_payload is not None else None,
                    "hero_env": hero_env,
                    "opponent_env": opponent_env,
                    "max_decisions": max_decisions,
                    "process_start_method": (
                        mp.get_start_method(allow_none=True)
                        or str(task.get("process_start_method", PROCESS_START_METHOD))
                    ),
                    "enqueue_position": int(task.get("enqueue_position", -1)),
                    "worker_count": int(task.get("worker_count", 1)),
                    "worker_pid": os.getpid(),
                    "worker_process_name": mp.current_process().name,
                    "execution_variant": task.get("execution_variant"),
                    "schedule_direction": task.get("schedule_direction"),
                    "protocol_id": task.get("protocol_id"),
                    "protocol_commit": task.get("protocol_commit"),
                    "run_uuid": task.get("run_uuid"),
                    "schedule_fingerprint_sha256": task.get("schedule_fingerprint_sha256"),
                    "run_fingerprint_sha256": task.get("run_fingerprint_sha256"),
                }
                break

            if obs.select.context == SelectContext.IS_FIRST:
                action = _forced_order(obs.select, hero_seat, order)
                actor = "forced_order"
            else:
                acting_seat = int(obs.current.yourIndex)
                action = agents[acting_seat](raw)
                actor = "hero" if acting_seat == hero_seat else "opponent"
            if capture_trace:
                append_trace(
                    {
                        "event": "action",
                        "decision": decisions,
                        "actor": actor,
                        "action": action,
                        "public_observation_sha256": _public_observation_sha256(raw),
                    }
                )
            raw = engine.select(battle_ptr, action)
            decisions += 1
            if decisions >= max_decisions:
                raise RuntimeError("seeded evaluation exceeded decision cap")
    finally:
        if battle_ptr:
            engine.finish(battle_ptr)
        hero.close()
        opponent.close()
    if completed is None:
        raise RuntimeError("seeded evaluation ended without a terminal record")
    completed["elapsed_wall_seconds"] = time.perf_counter() - game_started
    return completed


def run_tasks(tasks: list[dict[str, Any]], workers: int) -> list[dict[str, Any]]:
    os.environ["PYTHONHASHSEED"] = "0"
    prepared = _prepare_tasks(tasks, workers)
    context = mp.get_context(PROCESS_START_METHOD)
    rows: list[dict[str, Any]] = []
    with context.Pool(workers) as pool:
        for row in pool.imap_unordered(_run_game, prepared, chunksize=1):
            rows.append(row)
    return sorted(rows, key=lambda row: str(row["task_id"]))


def _without_trace(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key != "trace"}


def _proof_signature(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    # Execution provenance is deliberately absent: worker assignment, process ID,
    # enqueue timing, and elapsed wall time are audit data, not gameplay behavior.
    return {
        str(row["task_id"]): {
            key: row.get(key) for key in _DETERMINISM_SIGNATURE_FIELDS
        }
        for row in rows
    }


def _proof_execution_plan(
    execution_variants: tuple[str, ...] | None,
    parallel_workers: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if parallel_workers < 1:
        raise ValueError("parallel_workers must be positive")
    if execution_variants is None:
        variants = [
            {"name": "single_a", "workers": 1, "schedule_direction": "forward"},
            {"name": "single_b", "workers": 1, "schedule_direction": "forward"},
            {
                "name": f"workers_{parallel_workers}",
                "workers": parallel_workers,
                "schedule_direction": "forward",
            },
        ]
        serialized = {
            "profile": "legacy_three_run",
            "single_a_workers": 1,
            "single_b_workers": 1,
            f"workers_{parallel_workers}": parallel_workers,
            "variants": variants,
            "process_start_method": PROCESS_START_METHOD,
        }
        return variants, serialized

    requested = tuple(execution_variants)
    if len(requested) < 2:
        raise ValueError("determinism proof requires at least two execution variants")
    if len(set(requested)) != len(requested):
        raise ValueError("execution variants must be unique")
    invalid = [name for name in requested if name not in PROOF_EXECUTION_VARIANTS]
    if invalid:
        raise ValueError(f"unknown execution variants: {invalid}")
    if any(name.startswith("parallel-") for name in requested) and parallel_workers < 2:
        raise ValueError("parallel execution variants require at least two workers")

    variants = []
    for requested_name in requested:
        concurrency, direction = requested_name.split("-", 1)
        variants.append(
            {
                "name": requested_name.replace("-", "_"),
                "workers": 1 if concurrency == "serial" else parallel_workers,
                "schedule_direction": direction,
            }
        )
    return variants, {
        "profile": "explicit_variants",
        "variants": variants,
        "process_start_method": PROCESS_START_METHOD,
    }


def determinism_proof(
    *,
    engine: Path,
    hero: Path,
    opponent: Path,
    output: Path,
    base_seed: int,
    seeds_per_order: int,
    parallel_workers: int,
    max_decisions: int,
    protocol_id: str = "evaluate_deterministic_crn.prove.v2",
    protocol_commit: str | None = None,
    run_uuid: str | None = None,
    audit: bool = False,
    hero_env: dict[str, str] | None = None,
    opponent_env: dict[str, str] | None = None,
    trace_mode: str = "full",
    execution_variants: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    hero_env = dict(hero_env or {})
    opponent_env = dict(opponent_env or {})
    trace_mode = _trace_mode({"trace_mode": trace_mode})
    if trace_mode == "none":
        raise ValueError("determinism proof trace_mode must be digest or full")
    variants, execution_plan = _proof_execution_plan(execution_variants, parallel_workers)
    tasks = []
    for order_index, order in enumerate(("first", "second")):
        for index in range(seeds_per_order):
            tasks.append(
                {
                    "task_id": f"{order}-{index:03d}",
                    "engine": str(engine.resolve()),
                    "hero": str(hero.resolve()),
                    "opponent": str(opponent.resolve()),
                    "scheduled_seed": base_seed + order_index * ORDER_SEED_OFFSET + index,
                    "actual_order": order,
                    "physical_seat": index % 2,
                    "trace_mode": trace_mode,
                    "max_decisions": max_decisions,
                    "hero_env": hero_env,
                    "opponent_env": opponent_env,
                }
            )
    artifacts = {
        "engine_sha256": sha256_file(engine),
        "hero_sha256": sha256_path(hero),
        "opponent_sha256": sha256_path(opponent),
    }
    identity = _run_identity(
        mode="prove",
        tasks=tasks,
        protocol_id=protocol_id,
        protocol_commit=protocol_commit,
        run_uuid=run_uuid,
        artifacts=artifacts,
        execution_plan=execution_plan,
    )
    tasks = _attach_run_identity(tasks, identity)
    runs: dict[str, list[dict[str, Any]]] = {}
    for variant in variants:
        ordered_tasks = (
            tasks
            if variant["schedule_direction"] == "forward"
            else list(reversed(tasks))
        )
        scheduled_tasks = [
            {
                **task,
                "execution_variant": variant["name"],
                "schedule_direction": variant["schedule_direction"],
            }
            for task in ordered_tasks
        ]
        runs[str(variant["name"])] = run_tasks(
            scheduled_tasks, int(variant["workers"])
        )
    names = list(runs)
    signatures = {name: _proof_signature(rows) for name, rows in runs.items()}
    reference = signatures[names[0]]
    mismatches = {
        name: sorted(task_id for task_id in reference if signatures[name].get(task_id) != reference[task_id])
        for name in names[1:]
    }
    trace_files: dict[str, dict[str, str]] = {}
    if trace_mode == "full":
        trace_root = output.parent / "determinism_traces"
        for name, rows in runs.items():
            run_dir = trace_root / name
            run_dir.mkdir(parents=True, exist_ok=True)
            trace_files[name] = {}
            for row in rows:
                trace_path = run_dir / f"{row['task_id']}.jsonl"
                trace_path.write_bytes(row["trace"])
                trace_files[name][str(row["task_id"])] = sha256_file(trace_path)

    passed = all(not values for values in mismatches.values())
    result = {
        "passed": passed,
        "claim": "same seed, agents, order, and physical seat produce byte-identical public-state/action/outcome traces",
        "excluded_from_trace": [
            "search_begin_input (opaque raw-struct search snapshot is not byte-stable across process starts; downstream public observations, selected actions, and outcomes remain covered)"
        ],
        **identity,
        "audit_mode": audit,
        "admission_decision": "admit" if passed else "suppress",
        "engine": str(engine.resolve()),
        **artifacts,
        "tasks": len(tasks),
        "seeds_per_order": seeds_per_order,
        "base_seed": base_seed,
        "order_seed_offset": ORDER_SEED_OFFSET,
        "seed_conversion": {
            "requested_field": "scheduled_seed",
            "engine_field": "engine_seed_uint32",
            "rule": SEED_CONVERSION_RULE,
            "modulus": UINT32_MODULUS,
            "schedule_wide_distinct_seed_collision_check": "passed",
        },
        "max_decisions": max_decisions,
        "trace_mode": trace_mode,
        "trace_payload_files_written": trace_mode == "full",
        "hero_env": hero_env,
        "opponent_env": opponent_env,
        "execution_plan": execution_plan,
        "execution_environment": _execution_environment(),
        "runs": {name: [_without_trace(row) for row in rows] for name, rows in runs.items()},
        "mismatches": mismatches,
        "trace_files": trace_files,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not passed and not audit:
        raise RuntimeError(f"determinism proof failed: {mismatches}")
    return result


def paired_summary(candidate: list[dict[str, Any]], control: list[dict[str, Any]]) -> dict[str, Any]:
    candidate_by_pair = {
        (str(row["actual_order"]), int(row["pair_index"])): row for row in candidate
    }
    control_by_pair = {
        (str(row["actual_order"]), int(row["pair_index"])): row for row in control
    }
    if set(candidate_by_pair) != set(control_by_pair) or len(candidate_by_pair) < 2:
        raise ValueError("candidate and control require at least two identical seed pairs")
    differences = []
    seed_mismatches = []
    for pair_key in sorted(candidate_by_pair):
        candidate_row = candidate_by_pair[pair_key]
        control_row = control_by_pair[pair_key]
        candidate_seed = int(candidate_row.get("scheduled_seed", candidate_row["seed"]))
        control_seed = int(control_row.get("scheduled_seed", control_row["seed"]))
        candidate_engine_seed = int(
            candidate_row.get("engine_seed_uint32", seed_to_uint32(candidate_seed))
        )
        control_engine_seed = int(
            control_row.get("engine_seed_uint32", seed_to_uint32(control_seed))
        )
        if (
            candidate_seed != control_seed
            or candidate_engine_seed != control_engine_seed
            or candidate_row["actual_order"] != control_row["actual_order"]
            or int(candidate_row["physical_seat"]) != int(control_row["physical_seat"])
        ):
            seed_mismatches.append(pair_key)
        differences.append(int(candidate_row["win"]) - int(control_row["win"]))
    if seed_mismatches:
        raise ValueError(f"paired schedules differ at pairs {seed_mismatches[:10]}")
    size = len(differences)
    mean = sum(differences) / size
    variance = sum((value - mean) ** 2 for value in differences) / (size - 1)
    standard_error = math.sqrt(variance / size)
    z = 1.959963984540054
    one_sided_z = 1.6448536269514722
    candidate_wins = sum(int(row["win"]) for row in candidate)
    control_wins = sum(int(row["win"]) for row in control)
    return {
        "pairs": size,
        "candidate_wins": candidate_wins,
        "candidate_win_rate": candidate_wins / size,
        "control_wins": control_wins,
        "control_win_rate": control_wins / size,
        "paired_difference": mean,
        "paired_standard_error": standard_error,
        "paired_95_ci": [max(-1.0, mean - z * standard_error), min(1.0, mean + z * standard_error)],
        "paired_one_sided_95_lower": max(-1.0, mean - one_sided_z * standard_error),
        "discordant_candidate_wins": sum(value == 1 for value in differences),
        "discordant_control_wins": sum(value == -1 for value in differences),
        "concordant": sum(value == 0 for value in differences),
        "candidate_draws": sum(int(row["draw"]) for row in candidate),
        "control_draws": sum(int(row["draw"]) for row in control),
        "candidate_policy_errors": sum(int(row["hero_policy_errors"]) for row in candidate),
        "control_policy_errors": sum(int(row["hero_policy_errors"]) for row in control),
        "opponent_policy_errors": sum(int(row["opponent_policy_errors"]) for row in candidate + control),
        "candidate_decisions": sum(int(row["decisions"]) for row in candidate),
        "control_decisions": sum(int(row["decisions"]) for row in control),
        "method": "paired_win_indicator_difference_normal_95_ci",
    }


def paired_evaluation(
    *,
    engine: Path,
    candidate: Path,
    control: Path,
    opponent: Path,
    production_engine: Path,
    output: Path,
    base_seed: int,
    pairs_per_order: int,
    workers: int,
    max_decisions: int,
    actual_orders: tuple[str, ...] = ("first", "second"),
    hero_env: dict[str, str] | None = None,
    opponent_env: dict[str, str] | None = None,
    capture_trace_digest: bool = False,
    protocol_id: str = "evaluate_deterministic_crn.paired.v2",
    protocol_commit: str | None = None,
    run_uuid: str | None = None,
) -> dict[str, Any]:
    hero_env = dict(hero_env or {})
    opponent_env = dict(opponent_env or {})
    if not actual_orders:
        raise ValueError("actual_orders must contain at least one order")
    if len(set(actual_orders)) != len(actual_orders) or any(
        order not in {"first", "second"} for order in actual_orders
    ):
        raise ValueError("actual_orders must be a unique subset of ('first', 'second')")
    production_before = sha256_file(production_engine)
    artifacts = {
        "engine_sha256": sha256_file(engine),
        "production_engine_sha256": production_before,
        "candidate_sha256": sha256_path(candidate),
        "control_sha256": sha256_path(control),
        "opponent_sha256": sha256_path(opponent),
    }
    tasks = []
    for order in actual_orders:
        # Keep each order on its canonical seed stratum even when evaluating only
        # one order, so --actual-order second remains comparable to a two-order run.
        order_index = 0 if order == "first" else 1
        for pair_index in range(pairs_per_order):
            seed = base_seed + order_index * ORDER_SEED_OFFSET + pair_index
            physical_seat = pair_index % 2
            for arm, hero in (("candidate", candidate), ("control", control)):
                tasks.append(
                    {
                        "task_id": f"{order}-{pair_index:05d}-{arm}",
                        "pair_index": pair_index,
                        "arm": arm,
                        "engine": str(engine.resolve()),
                        "hero": str(hero.resolve()),
                        "opponent": str(opponent.resolve()),
                        "scheduled_seed": seed,
                        "actual_order": order,
                        "physical_seat": physical_seat,
                        "trace_mode": "digest" if capture_trace_digest else "none",
                        "max_decisions": max_decisions,
                        "hero_env": hero_env,
                        "opponent_env": opponent_env,
                    }
                )
    execution_plan = {
        "workers": workers,
        "process_start_method": PROCESS_START_METHOD,
        "actual_orders": list(actual_orders),
        "pairs_per_order": pairs_per_order,
        "capture_trace_digest": capture_trace_digest,
    }
    identity = _run_identity(
        mode="paired",
        tasks=tasks,
        protocol_id=protocol_id,
        protocol_commit=protocol_commit,
        run_uuid=run_uuid,
        artifacts=artifacts,
        execution_plan=execution_plan,
    )
    tasks = _attach_run_identity(tasks, identity)
    started = time.time()
    rows = run_tasks(tasks, workers)
    orders: dict[str, Any] = {}
    for order in actual_orders:
        candidate_rows = [row for row in rows if row["actual_order"] == order and row["arm"] == "candidate"]
        control_rows = [row for row in rows if row["actual_order"] == order and row["arm"] == "control"]
        orders[order] = paired_summary(candidate_rows, control_rows)
    all_candidate = [row for row in rows if row["arm"] == "candidate"]
    all_control = [row for row in rows if row["arm"] == "control"]
    production_after = sha256_file(production_engine)
    result = {
        **identity,
        "engine": str(engine.resolve()),
        "engine_sha256": artifacts["engine_sha256"],
        "production_engine": str(production_engine.resolve()),
        "production_engine_sha256_before": production_before,
        "production_engine_sha256_after": production_after,
        "production_engine_preserved": production_before == production_after,
        "candidate": str(candidate.resolve()),
        "candidate_sha256": artifacts["candidate_sha256"],
        "control": str(control.resolve()),
        "control_sha256": artifacts["control_sha256"],
        "opponent": str(opponent.resolve()),
        "opponent_sha256": artifacts["opponent_sha256"],
        "pairs_per_order": pairs_per_order,
        "actual_orders": list(actual_orders),
        "games": len(rows),
        "workers": workers,
        "base_seed": base_seed,
        "order_seed_offset": ORDER_SEED_OFFSET,
        "seed_conversion": {
            "requested_field": "scheduled_seed",
            "engine_field": "engine_seed_uint32",
            "rule": SEED_CONVERSION_RULE,
            "modulus": UINT32_MODULUS,
            "schedule_wide_distinct_seed_collision_check": "passed",
        },
        "max_decisions": max_decisions,
        "capture_trace_digest": capture_trace_digest,
        "execution_plan": execution_plan,
        "execution_environment": _execution_environment(),
        "hero_env": hero_env,
        "opponent_env": opponent_env,
        "elapsed_seconds": time.time() - started,
        "rng_provenance": {
            "engine": "local_seeded_mt19937",
            "entrypoint": "BattleStartSeeded",
            "deviceRand": False,
            "same_seed_within_candidate_control_pair": True,
            "same_actual_order_and_physical_seat_within_pair": True,
            "native_gameplay_random_device": False,
        },
        "orders": orders,
        "overall": paired_summary(all_candidate, all_control),
        "rows": [_without_trace(row) for row in rows],
    }
    if not result["production_engine_preserved"]:
        raise RuntimeError("production engine changed during isolated paired evaluation")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="mode", required=True)
    proof = subparsers.add_parser("prove", help="prove deterministic traces across repeats/workers")
    proof.add_argument("--engine", type=Path, default=DEFAULT_ENGINE)
    proof.add_argument("--hero", type=Path, default=DEFAULT_CANDIDATE)
    proof.add_argument("--opponent", type=Path, default=DEFAULT_CONTROL)
    proof.add_argument("--output", type=Path, required=True)
    proof.add_argument("--base-seed", type=int, default=2026082201)
    proof.add_argument("--seeds-per-order", type=int, default=2)
    proof.add_argument("--parallel-workers", type=int, default=4)
    proof.add_argument("--max-decisions", type=int, default=2_000)
    proof.add_argument("--hero-env", type=json.loads, default={})
    proof.add_argument("--opponent-env", type=json.loads, default={})
    proof.add_argument("--trace-mode", choices=("digest", "full"), default="full")
    proof.add_argument(
        "--execution-variant",
        action="append",
        choices=PROOF_EXECUTION_VARIANTS,
        help="repeat to select explicit serial/parallel and forward/reverse runs",
    )
    proof.add_argument(
        "--stress-matrix",
        action="store_true",
        help="run all four serial/parallel by forward/reverse execution variants",
    )
    proof.add_argument("--protocol-id", default="evaluate_deterministic_crn.prove.v2")
    proof.add_argument("--protocol-commit")
    proof.add_argument("--run-uuid")
    proof.add_argument(
        "--audit",
        action="store_true",
        help="write and return failed reproducibility audits instead of raising",
    )

    paired = subparsers.add_parser("paired", help="paired temporal/control arms on common engine seeds")
    paired.add_argument("--engine", type=Path, default=DEFAULT_ENGINE)
    paired.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    paired.add_argument("--control", type=Path, default=DEFAULT_CONTROL)
    paired.add_argument("--opponent", type=Path, default=DEFAULT_CONTROL)
    paired.add_argument("--production-engine", type=Path, default=DEFAULT_PRODUCTION_ENGINE)
    paired.add_argument("--output", type=Path, required=True)
    paired.add_argument("--base-seed", type=int, default=2026082301)
    paired.add_argument("--pairs-per-order", type=int, default=500)
    paired.add_argument("--actual-order", choices=("both", "first", "second"), default="both")
    paired.add_argument("--workers", type=int, default=max(1, (mp.cpu_count() or 2) - 1))
    paired.add_argument("--max-decisions", type=int, default=2_000)
    paired.add_argument("--hero-env", type=json.loads, default={})
    paired.add_argument("--opponent-env", type=json.loads, default={})
    paired.add_argument(
        "--capture-trace-digest",
        action="store_true",
        help="hash public-state/action traces without retaining trace payloads",
    )
    paired.add_argument("--protocol-id", default="evaluate_deterministic_crn.paired.v2")
    paired.add_argument("--protocol-commit")
    paired.add_argument("--run-uuid")
    args = parser.parse_args()

    if args.mode == "prove":
        if args.stress_matrix and args.execution_variant:
            parser.error("--stress-matrix cannot be combined with --execution-variant")
        execution_variants = (
            PROOF_EXECUTION_VARIANTS
            if args.stress_matrix
            else tuple(args.execution_variant) if args.execution_variant else None
        )
        result = determinism_proof(
            engine=args.engine,
            hero=args.hero,
            opponent=args.opponent,
            output=args.output,
            base_seed=args.base_seed,
            seeds_per_order=args.seeds_per_order,
            parallel_workers=args.parallel_workers,
            max_decisions=args.max_decisions,
            protocol_id=args.protocol_id,
            protocol_commit=args.protocol_commit,
            run_uuid=args.run_uuid,
            audit=args.audit,
            hero_env=args.hero_env,
            opponent_env=args.opponent_env,
            trace_mode=args.trace_mode,
            execution_variants=execution_variants,
        )
    else:
        result = paired_evaluation(
            engine=args.engine,
            candidate=args.candidate,
            control=args.control,
            opponent=args.opponent,
            production_engine=args.production_engine,
            output=args.output,
            base_seed=args.base_seed,
            pairs_per_order=args.pairs_per_order,
            workers=args.workers,
            max_decisions=args.max_decisions,
            actual_orders=("first", "second") if args.actual_order == "both" else (args.actual_order,),
            hero_env=args.hero_env,
            opponent_env=args.opponent_env,
            capture_trace_digest=args.capture_trace_digest,
            protocol_id=args.protocol_id,
            protocol_commit=args.protocol_commit,
            run_uuid=args.run_uuid,
        )
    printable = {key: value for key, value in result.items() if key not in {"rows", "runs", "trace_files"}}
    print(json.dumps(printable, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
