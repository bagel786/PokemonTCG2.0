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
import random
import sys
import time
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
    seed = int(task["seed"])
    random.seed(seed)
    np.random.seed(seed & 0xFFFFFFFF)
    engine = get_engine(task["engine"])
    hero_path = Path(task["hero"])
    opponent_path = Path(task["opponent"])
    hero_seat = int(task["physical_seat"])
    order = str(task["actual_order"])
    capture_trace = bool(task.get("capture_trace", False))
    max_decisions = int(task.get("max_decisions", 2_000))

    hero = ExternalSubmissionAgent(hero_path, dict(task.get("hero_env") or {}))
    opponent = ExternalSubmissionAgent(opponent_path, dict(task.get("opponent_env") or {}))
    agents = {hero_seat: hero, 1 - hero_seat: opponent}
    decks = [hero.deck, opponent.deck] if hero_seat == 0 else [opponent.deck, hero.deck]
    battle_ptr = 0
    trace = bytearray()
    first_player = None
    decisions = 0
    try:
        battle_ptr, raw = engine.start(decks[0], decks[1], seed)
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
                    trace.extend(_canonical_line(terminal))
                return {
                    "task_id": task["task_id"],
                    "pair_index": int(task.get("pair_index", -1)),
                    "arm": task.get("arm"),
                    "seed": seed,
                    "actual_order": observed_order,
                    "physical_seat": hero_seat,
                    "win": int(result == hero_seat),
                    "draw": int(result == 2),
                    "decisions": decisions,
                    "hero_policy_errors": _policy_errors(hero),
                    "opponent_policy_errors": _policy_errors(opponent),
                    "trace_sha256": hashlib.sha256(trace).hexdigest() if capture_trace else None,
                    "trace_bytes": len(trace) if capture_trace else 0,
                    "trace": bytes(trace) if capture_trace else None,
                }

            if obs.select.context == SelectContext.IS_FIRST:
                action = _forced_order(obs.select, hero_seat, order)
                actor = "forced_order"
            else:
                acting_seat = int(obs.current.yourIndex)
                action = agents[acting_seat](raw)
                actor = "hero" if acting_seat == hero_seat else "opponent"
            if capture_trace:
                trace.extend(
                    _canonical_line(
                        {
                            "event": "action",
                            "decision": decisions,
                            "actor": actor,
                            "action": action,
                            "public_observation_sha256": _public_observation_sha256(raw),
                        }
                    )
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


def run_tasks(tasks: list[dict[str, Any]], workers: int) -> list[dict[str, Any]]:
    os.environ["PYTHONHASHSEED"] = "0"
    context = mp.get_context("spawn")
    rows: list[dict[str, Any]] = []
    with context.Pool(workers) as pool:
        for row in pool.imap_unordered(_run_game, tasks, chunksize=1):
            rows.append(row)
    return sorted(rows, key=lambda row: str(row["task_id"]))


def _without_trace(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key != "trace"}


def _proof_signature(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row["task_id"]): _without_trace(row) for row in rows}


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
) -> dict[str, Any]:
    tasks = []
    for order_index, order in enumerate(("first", "second")):
        for index in range(seeds_per_order):
            tasks.append(
                {
                    "task_id": f"{order}-{index:03d}",
                    "engine": str(engine.resolve()),
                    "hero": str(hero.resolve()),
                    "opponent": str(opponent.resolve()),
                    "seed": base_seed + order_index * 100_000 + index,
                    "actual_order": order,
                    "physical_seat": index % 2,
                    "capture_trace": True,
                    "max_decisions": max_decisions,
                }
            )
    runs = {
        "single_a": run_tasks(tasks, 1),
        "single_b": run_tasks(tasks, 1),
        f"workers_{parallel_workers}": run_tasks(tasks, parallel_workers),
    }
    names = list(runs)
    signatures = {name: _proof_signature(rows) for name, rows in runs.items()}
    reference = signatures[names[0]]
    mismatches = {
        name: sorted(task_id for task_id in reference if signatures[name].get(task_id) != reference[task_id])
        for name in names[1:]
    }
    trace_root = output.parent / "determinism_traces"
    trace_files: dict[str, dict[str, str]] = {}
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
        "engine": str(engine.resolve()),
        "engine_sha256": sha256_file(engine),
        "hero_sha256": sha256_path(hero),
        "opponent_sha256": sha256_path(opponent),
        "tasks": len(tasks),
        "seeds_per_order": seeds_per_order,
        "runs": {name: [_without_trace(row) for row in rows] for name, rows in runs.items()},
        "mismatches": mismatches,
        "trace_files": trace_files,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not passed:
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
        if (
            int(candidate_row["seed"]) != int(control_row["seed"])
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
    tasks = []
    for order in actual_orders:
        # Keep each order on its canonical seed stratum even when evaluating only
        # one order, so --actual-order second remains comparable to a two-order run.
        order_index = 0 if order == "first" else 1
        for pair_index in range(pairs_per_order):
            seed = base_seed + order_index * 1_000_000 + pair_index
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
                        "seed": seed,
                        "actual_order": order,
                        "physical_seat": physical_seat,
                        "capture_trace": False,
                        "max_decisions": max_decisions,
                        "hero_env": hero_env,
                        "opponent_env": opponent_env,
                    }
                )
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
        "engine": str(engine.resolve()),
        "engine_sha256": sha256_file(engine),
        "production_engine": str(production_engine.resolve()),
        "production_engine_sha256_before": production_before,
        "production_engine_sha256_after": production_after,
        "production_engine_preserved": production_before == production_after,
        "candidate": str(candidate.resolve()),
        "candidate_sha256": sha256_path(candidate),
        "control": str(control.resolve()),
        "control_sha256": sha256_path(control),
        "opponent": str(opponent.resolve()),
        "opponent_sha256": sha256_path(opponent),
        "pairs_per_order": pairs_per_order,
        "actual_orders": list(actual_orders),
        "games": len(rows),
        "workers": workers,
        "base_seed": base_seed,
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
    args = parser.parse_args()

    if args.mode == "prove":
        result = determinism_proof(
            engine=args.engine,
            hero=args.hero,
            opponent=args.opponent,
            output=args.output,
            base_seed=args.base_seed,
            seeds_per_order=args.seeds_per_order,
            parallel_workers=args.parallel_workers,
            max_decisions=args.max_decisions,
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
        )
    printable = {key: value for key, value in result.items() if key not in {"rows", "runs", "trace_files"}}
    print(json.dumps(printable, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
