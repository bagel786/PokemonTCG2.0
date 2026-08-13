#!/usr/bin/env python3
"""Authentic, seat-balanced evaluation for FESTIVAL-D0 and FESTIVAL-D1.

Both policies are loaded from extracted submission directories through the
isolated external-submission adapter.  The engine still seeds games from
``std::random_device``; ``--seed`` controls only the Python/NumPy schedule and
must not be interpreted as paired deals or common random numbers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import multiprocessing as mp
import os
import platform
import random
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if (ROOT / "vendor").is_dir():
    sys.path.insert(0, str(ROOT / "vendor"))

from cg import sim as cg_sim  # noqa: E402
from cg.api import OptionType, SelectContext, to_observation_class  # noqa: E402
from cg.game import battle_finish, battle_select, battle_start  # noqa: E402
from ptcg_ai.external import ExternalSubmissionAgent  # noqa: E402
from ptcg_ai.safety import sanitize_selection  # noqa: E402
from scripts.dipplin_second_trace import (  # noqa: E402
    SCHEMA as SECOND_BUCKET_TRACE_SCHEMA,
    SecondBucketTrace,
)
from training.evaluation_schema import (  # noqa: E402
    build_provenance,
    sha256_file,
    sha256_path,
)


DEFAULT_INTERVENTION_KEYS = (
    "d1_overrides",
    "search_interventions",
    "search_overrides",
    "interventions",
    "d0_d1_disagreements",
)
D1_METRIC_ALIASES = {
    "attempts": ("d1_attempts", "search_attempts", "searches_started"),
    "abstentions": ("d1_abstentions", "search_abstentions", "abstentions"),
    "overrides": (
        "d1_overrides",
        "search_interventions",
        "search_overrides",
        "interventions",
    ),
    "d0_d1_disagreements": (
        "d0_d1_disagreements",
        "search_disagreements",
    ),
}
CONTEXT_PREFIXES = (
    "d1_context_",
    "d1_override_context_",
    "search_intervention_context_",
)
RELEVANT_ENV_KEYS = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "PYTHONHASHSEED",
    "PYTHONDONTWRITEBYTECODE",
)


class EvaluationFailure(RuntimeError):
    """A game-level failure that should be retained in the output rows."""


def _trace_call(
    trace: SecondBucketTrace | None,
    errors: list[str],
    method: str,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Run optional read-only instrumentation without affecting gameplay.

    The first collector exception disables subsequent observation/action hooks.
    Finalization is still attempted so the row retains explicit partial
    coverage.  This helper never mutates or replaces an engine action.
    """
    if trace is None or (errors and method != "finalize"):
        return None
    try:
        return getattr(trace, method)(*args, **kwargs)
    except Exception as error:  # instrumentation is never gameplay-critical
        errors.append(f"{method}:{type(error).__name__}:{error}"[:2000])
        return None


def _is_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def numeric_mapping(values: object) -> dict[str, float]:
    """Return only finite scalar telemetry, never nested audit metadata."""
    if not isinstance(values, Mapping):
        return {}
    return {
        str(key): float(value)
        for key, value in values.items()
        if _is_number(value)
    }


def policy_error_count(agent: ExternalSubmissionAgent | None) -> int:
    """Count adapter exceptions and submission-internal emergency fallbacks."""
    if agent is None:
        return 0
    errors = int(getattr(agent, "errors", 0) or 0)
    module = getattr(agent, "module", None)
    inner = getattr(module, "_AGENT", None)
    errors += int(getattr(inner, "errors", 0) or 0)
    return errors


def route_telemetry(agent: ExternalSubmissionAgent | None) -> dict[str, float]:
    """Read the packaged agent's public, flat numeric mechanism telemetry."""
    if agent is None:
        return {}
    module = getattr(agent, "module", None)
    inner = getattr(module, "_AGENT", None)
    candidates = (
        getattr(inner, "route_telemetry", None),
        getattr(inner, "telemetry", None),
        getattr(module, "ROUTE_TELEMETRY", None),
    )
    for candidate in candidates:
        if hasattr(candidate, "flat"):
            candidate = candidate.flat()
        elif hasattr(candidate, "snapshot"):
            candidate = candidate.snapshot()
        numeric = numeric_mapping(candidate)
        if numeric:
            return numeric
    return {}


def external_diagnostics(
    agent: ExternalSubmissionAgent | None,
) -> tuple[dict[str, float], dict[str, float]]:
    """Capture finite legacy runtime/search counters when a package exposes them."""
    if agent is None:
        return {}, {}
    module = getattr(agent, "module", None)
    runtime = numeric_mapping(getattr(module, "RUNTIME_STATS", None))
    search_module = getattr(module, "search", None)
    search = numeric_mapping(getattr(search_module, "STATS", None))
    return runtime, search


def capture_initial_first_player(current: object, captured: int | None = None) -> int | None:
    """Capture stable opening order before terminal states can clear metadata."""
    value = getattr(current, "firstPlayer", -1) if current is not None else -1
    observed = int(value) if value in (0, 1) else None
    if captured in (0, 1):
        if observed in (0, 1) and observed != captured:
            raise EvaluationFailure(
                f"firstPlayer changed from {captured} to {observed}"
            )
        return captured
    return observed


def force_actual_order(select: object, hero_seat: int, order: str) -> list[int]:
    """Choose the unique IS_FIRST option that gives the hero ``order``.

    Physical seat zero owns the engine's go-first prompt.  Crossing the hero
    between physical seats while applying this mapping keeps order forcing and
    seat balancing independent.
    """
    if order not in {"first", "second"}:
        raise EvaluationFailure(f"invalid forced actual order: {order!r}")
    seat_zero_first = (order == "first") == (int(hero_seat) == 0)
    desired = OptionType.YES if seat_zero_first else OptionType.NO
    choices = [
        index
        for index, option in enumerate(getattr(select, "option", ()) or ())
        if getattr(option, "type", None) == desired
    ]
    if len(choices) != 1:
        raise EvaluationFailure(
            "forced-order evaluation found an invalid IS_FIRST choice set"
        )
    return sanitize_selection(select, choices, 1)


def percentile(values: Sequence[float], probability: float) -> float:
    """Linear-interpolated percentile with deterministic empty-stream behavior."""
    if not values:
        return 0.0
    if not 0.0 <= probability <= 1.0:
        raise ValueError("probability must be in [0, 1]")
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def latency_summary(values: Sequence[float]) -> dict[str, int | float]:
    samples = [float(value) for value in values if _is_number(value)]
    return {
        "count": len(samples),
        "mean": fmean(samples) if samples else 0.0,
        "p50": percentile(samples, 0.50),
        "p95": percentile(samples, 0.95),
        "p99": percentile(samples, 0.99),
        "max": max(samples, default=0.0),
    }


def wilson(wins: int, games: int, z: float = 1.959963984540054) -> list[float]:
    """Two-sided 95% Wilson score interval for the binary win indicator."""
    if games <= 0:
        return [0.0, 1.0]
    proportion = wins / games
    denominator = 1.0 + z * z / games
    center = (proportion + z * z / (2.0 * games)) / denominator
    margin = (
        z
        * math.sqrt(
            (proportion * (1.0 - proportion) + z * z / (4.0 * games))
            / games
        )
        / denominator
    )
    return [max(0.0, center - margin), min(1.0, center + margin)]


def _load_deck(path: str | Path) -> list[int]:
    deck_path = Path(path)
    try:
        deck = [
            int(line.strip())
            for line in deck_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, ValueError) as error:
        raise ValueError(f"invalid deck {deck_path}: {error}") from error
    if len(deck) != 60:
        raise ValueError(f"deck must contain exactly 60 cards: {deck_path} ({len(deck)})")
    return deck


def _seed_python_numpy(schedule_seed: int) -> int:
    random.seed(schedule_seed)
    numpy_seed = schedule_seed % (2**32)
    try:
        import numpy as np

        np.random.seed(numpy_seed)
    except ImportError:
        pass
    return numpy_seed


def _failure(error: BaseException, actor: str | None = None) -> dict[str, str | None]:
    message = str(error).strip() or repr(error)
    return {
        "type": type(error).__name__,
        "message": message[:2000],
        "actor": actor,
    }


def _inside(path: Path, directory: Path) -> bool:
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except (OSError, ValueError):
        return False


def _remove_submission_modules(before: set[str], directories: Sequence[Path]) -> None:
    """Best-effort cleanup for submission modules imported under absolute names.

    ``ExternalSubmissionAgent.close`` removes its unique package.  Historical
    packages occasionally import sibling files by an absolute top-level name;
    those are removed here before a worker is reused for another game.
    """
    for name in list(sys.modules):
        if name in before:
            continue
        module = sys.modules.get(name)
        filename = getattr(module, "__file__", None)
        if not filename:
            continue
        try:
            source = Path(filename)
        except TypeError:
            continue
        if any(_inside(source, directory) for directory in directories):
            sys.modules.pop(name, None)


def run_game(task: Mapping[str, Any]) -> dict[str, Any]:
    """Run one independent engine game and retain failures as JSON-safe rows.

    Deliberately absent from ``task`` are the human opponent label and any
    matchup/archetype identifier.  The packaged runtime receives observations,
    its own package deck, and only its explicitly requested environment.
    """
    game_index = int(task["game_index"])
    schedule_seed = int(task["seed"]) + game_index
    numpy_seed = _seed_python_numpy(schedule_seed)
    hero_seat = game_index % 2
    opponent_seat = 1 - hero_seat
    hero_path = Path(str(task["submission_a"]))
    opponent_path = Path(str(task["submission_b"]))
    deck_a = _load_deck(str(task["deck_a"]))
    deck_b = _load_deck(str(task["deck_b"]))
    decks = [deck_a, deck_b] if hero_seat == 0 else [deck_b, deck_a]
    modules_before = set(sys.modules)

    hero: ExternalSubmissionAgent | None = None
    opponent: ExternalSubmissionAgent | None = None
    battle_active = False
    active_actor: str | None = None
    initial_first_player: int | None = None
    result_seat: int | None = None
    decisions = 0
    hero_decisions = 0
    opponent_decisions = 0
    hero_illegal_actions = 0
    opponent_illegal_actions = 0
    hero_latencies: list[float] = []
    opponent_latencies: list[float] = []
    failure: dict[str, str | None] | None = None
    second_bucket_trace = (
        SecondBucketTrace(hero_seat=hero_seat)
        if bool(task.get("second_bucket_trace"))
        else None
    )
    second_bucket_trace_errors: list[str] = []
    game_started = time.perf_counter()

    try:
        # Load the candidate first: its import cannot observe an already-loaded
        # opponent package.  No opponent label/path is passed into its adapter.
        hero = ExternalSubmissionAgent(hero_path, dict(task["submission_env_a"]))
        if list(hero.deck) != deck_a:
            raise EvaluationFailure("hero package deck.csv differs from --deck-a")
        opponent = ExternalSubmissionAgent(
            opponent_path, dict(task["submission_env_b"])
        )
        if list(opponent.deck) != deck_b:
            raise EvaluationFailure("opponent package deck.csv differs from --deck-b")
        agents = {hero_seat: hero, opponent_seat: opponent}

        raw, start = battle_start(decks[0], decks[1])
        if int(start.errorType) != 0 or raw is None:
            raise EvaluationFailure(
                "engine rejected deck "
                f"(errorType={int(start.errorType)}, errorPlayer={int(start.errorPlayer)})"
            )
        battle_active = True

        while True:
            obs = to_observation_class(raw)
            _trace_call(
                second_bucket_trace,
                second_bucket_trace_errors,
                "observe",
                obs,
            )
            current = obs.current
            initial_first_player = capture_initial_first_player(
                current, initial_first_player
            )
            if current is not None and int(current.result) >= 0:
                result_seat = int(current.result)
                if initial_first_player not in (0, 1):
                    raise EvaluationFailure("terminal game has no captured firstPlayer")
                break
            if decisions >= int(task["max_decisions"]):
                raise EvaluationFailure(
                    "game exceeded fail-closed decision cap: "
                    f"{int(task['max_decisions'])}"
                )
            if current is None or int(current.yourIndex) not in (0, 1):
                raise EvaluationFailure("live observation has no valid acting player")

            acting_seat = int(current.yourIndex)
            forced_order = task.get("actual_order")
            if (
                forced_order
                and getattr(obs.select, "context", None) == SelectContext.IS_FIRST
            ):
                action = force_actual_order(obs.select, hero_seat, str(forced_order))
                active_actor = None
            else:
                active_actor = "hero" if acting_seat == hero_seat else "opponent"
                call_started = time.perf_counter()
                action = agents[acting_seat](raw)
                latency_ms = (time.perf_counter() - call_started) * 1000.0
                if active_actor == "hero":
                    hero_latencies.append(latency_ms)
                    hero_decisions += 1
                else:
                    opponent_latencies.append(latency_ms)
                    opponent_decisions += 1
            decisions += 1
            try:
                selected_action = tuple(map(int, action))
                next_raw = battle_select(action)
            except (IndexError, ValueError) as error:
                if active_actor == "hero":
                    hero_illegal_actions += 1
                else:
                    opponent_illegal_actions += 1
                raise EvaluationFailure(
                    f"engine rejected {active_actor} action {action!r}"
                ) from error
            # Gameplay is committed before the read-only collector sees the
            # selected public action.  A collector failure therefore cannot
            # alter legality, timing, or the engine transition.
            _trace_call(
                second_bucket_trace,
                second_bucket_trace_errors,
                "record_action",
                obs,
                selected_action,
                acting_seat,
            )
            raw = next_raw
            active_actor = None
    except Exception as error:  # retain an auditable row instead of losing the shard
        failure = _failure(error, active_actor)
    finally:
        hero_errors = policy_error_count(hero)
        opponent_errors = policy_error_count(opponent)
        hero_telemetry = route_telemetry(hero)
        opponent_telemetry = route_telemetry(opponent)
        hero_runtime, hero_search = external_diagnostics(hero)
        opponent_runtime, opponent_search = external_diagnostics(opponent)
        cleanup_errors: list[str] = []
        if battle_active:
            try:
                battle_finish()
            except Exception as error:  # pragma: no cover - native cleanup failure
                cleanup_errors.append(f"battle_finish:{type(error).__name__}:{error}")
        for label, agent in (("hero", hero), ("opponent", opponent)):
            if agent is not None:
                try:
                    agent.close()
                except Exception as error:  # pragma: no cover - best effort
                    cleanup_errors.append(f"{label}_close:{type(error).__name__}:{error}")
        _remove_submission_modules(modules_before, (hero_path, opponent_path))

    completed = failure is None and result_seat is not None and not cleanup_errors
    if cleanup_errors and failure is None:
        failure = {
            "type": "CleanupFailure",
            "message": "; ".join(cleanup_errors),
            "actor": None,
        }
    actual_order = (
        "first"
        if initial_first_player == hero_seat
        else "second"
        if initial_first_player in (0, 1)
        else None
    )
    draw = int(completed and result_seat not in (0, 1))
    win = int(completed and result_seat == hero_seat)
    outcome = "win" if win else "draw" if draw else "loss" if completed else "failed"
    row = {
        "game_index": game_index,
        "python_seed": schedule_seed,
        "numpy_seed": numpy_seed,
        "hero_seat": hero_seat,
        "opponent_seat": opponent_seat,
        "first_player": initial_first_player,
        "actual_order": actual_order,
        "completed": completed,
        "result_seat": result_seat if completed else None,
        "outcome": outcome,
        "win": win,
        "draw": draw,
        "decisions": decisions,
        "hero_decisions": hero_decisions,
        "opponent_decisions": opponent_decisions,
        "hero_policy_errors": hero_errors,
        "opponent_policy_errors": opponent_errors,
        "hero_illegal_actions": hero_illegal_actions,
        "opponent_illegal_actions": opponent_illegal_actions,
        "hero_telemetry": hero_telemetry,
        "opponent_telemetry": opponent_telemetry,
        "hero_runtime_stats": hero_runtime,
        "hero_search_stats": hero_search,
        "opponent_runtime_stats": opponent_runtime,
        "opponent_search_stats": opponent_search,
        "hero_latency_ms": latency_summary(hero_latencies),
        "opponent_latency_ms": latency_summary(opponent_latencies),
        "elapsed_ms": (time.perf_counter() - game_started) * 1000.0,
        "failure": failure,
        "cleanup_errors": cleanup_errors,
        # Samples are removed before serialization after exact global quantiles.
        "_hero_latency_samples_ms": hero_latencies,
        "_opponent_latency_samples_ms": opponent_latencies,
    }
    if second_bucket_trace is not None:
        trace_payload = _trace_call(
            second_bucket_trace,
            second_bucket_trace_errors,
            "finalize",
            completed=completed,
            result_seat=result_seat if completed else None,
        )
        if not isinstance(trace_payload, dict):
            trace_payload = {
                "schema": SECOND_BUCKET_TRACE_SCHEMA,
                "completed": False,
            }
        trace_payload["collection_complete"] = bool(
            completed and not second_bucket_trace_errors
        )
        trace_payload["trace_errors"] = list(second_bucket_trace_errors)
        row["second_bucket_trace"] = trace_payload
    return row


def _cell(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    selected = list(rows)
    completed = [row for row in selected if row["completed"]]
    wins = sum(int(row["win"]) for row in completed)
    draws = sum(int(row["draw"]) for row in completed)
    games = len(completed)
    return {
        "scheduled_games": len(selected),
        "games": games,
        "failed_games": len(selected) - games,
        "wins": wins,
        "draws": draws,
        "losses": games - wins - draws,
        "win_rate": wins / games if games else 0.0,
        "wilson_95": wilson(wins, games),
        "hero_policy_errors": sum(int(row["hero_policy_errors"]) for row in selected),
        "opponent_policy_errors": sum(
            int(row["opponent_policy_errors"]) for row in selected
        ),
        "hero_illegal_actions": sum(
            int(row["hero_illegal_actions"]) for row in selected
        ),
        "opponent_illegal_actions": sum(
            int(row["opponent_illegal_actions"]) for row in selected
        ),
        "decisions": sum(int(row["decisions"]) for row in selected),
    }


def seat_order_cells(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate overall, marginal seat/order, and all four crossed cells."""
    return {
        "overall": _cell(rows),
        "seat": {
            str(seat): _cell(row for row in rows if int(row["hero_seat"]) == seat)
            for seat in (0, 1)
        },
        "actual_order": {
            order: _cell(row for row in rows if row["actual_order"] == order)
            for order in ("first", "second")
        },
        "seat_x_actual_order": {
            f"seat_{seat}_{order}": _cell(
                row
                for row in rows
                if int(row["hero_seat"]) == seat and row["actual_order"] == order
            )
            for seat in (0, 1)
            for order in ("first", "second")
        },
    }


def merge_numeric_rows(
    rows: Iterable[Mapping[str, Any]], field: str
) -> dict[str, float]:
    """Merge counter telemetry; operational ``*_max`` fields remain maxima."""
    merged: dict[str, float] = {}
    for row in rows:
        values = numeric_mapping(row.get(field))
        for key, value in values.items():
            if key.endswith("_max") or key.endswith("_ms_max"):
                merged[key] = max(merged.get(key, 0.0), value)
            else:
                merged[key] = merged.get(key, 0.0) + value
    return dict(sorted(merged.items()))


def intervention_analysis(
    rows: Sequence[Mapping[str, Any]], keys: Sequence[str]
) -> dict[str, Any]:
    telemetry_present = any(
        any(key in row["hero_telemetry"] for key in keys) for row in rows
    )
    intervened = [row for row in rows if bool(row.get("d1_intervened"))]
    returned_d0 = [row for row in rows if not bool(row.get("d1_intervened"))]
    contexts: dict[str, float] = {}
    for row in rows:
        for key, value in numeric_mapping(row["hero_telemetry"]).items():
            if any(key.startswith(prefix) for prefix in CONTEXT_PREFIXES):
                contexts[key] = contexts.get(key, 0.0) + value
    completed = sum(int(row["completed"]) for row in rows)
    completed_interventions = sum(int(row["completed"]) for row in intervened)
    normalized_counts: dict[str, float] = {}
    for name, aliases in D1_METRIC_ALIASES.items():
        total = 0.0
        for row in rows:
            telemetry = row["hero_telemetry"]
            # Prefer the canonical/first key.  Packages sometimes expose both
            # a new key and a compatibility alias for the same event.
            total += next(
                (
                    float(telemetry[key])
                    for key in aliases
                    if key in telemetry and _is_number(telemetry[key])
                ),
                0.0,
            )
        normalized_counts[name] = total
    return {
        "enabled": telemetry_present,
        "keys_checked": list(keys),
        "canonical_counts": normalized_counts,
        "intervention_games": len(intervened),
        "completed_intervention_games": completed_interventions,
        "intervention_game_rate": (
            completed_interventions / completed if completed else 0.0
        ),
        "intervened": seat_order_cells(intervened),
        "returned_d0": seat_order_cells(returned_d0),
        "context_counts": dict(sorted(contexts.items())),
    }


def _git_output(arguments: Sequence[str]) -> str:
    try:
        return subprocess.check_output(
            ["git", *arguments],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _behavior_environment() -> dict[str, str]:
    keys = {
        key
        for key in os.environ
        if key.startswith("PTCG_") or key in RELEVANT_ENV_KEYS
    }
    return {key: os.environ[key] for key in sorted(keys)}


def exact_provenance(
    args: argparse.Namespace,
    *,
    deck_a: Path,
    deck_b: Path,
    submission_a: Path,
    submission_b: Path,
    env_a: Mapping[str, str],
    env_b: Mapping[str, str],
) -> dict[str, Any]:
    """Augment the repository provenance schema with evaluator/runtime facts."""
    base = build_provenance(
        root=ROOT,
        deck_a=deck_a,
        model_a=None,
        deck_b=deck_b,
        model_b=None,
        submission_a=submission_a,
        submission_b=submission_b,
        engine_path=Path(cg_sim.lib_path).resolve(),
        seed=args.seed,
        submission_env_a=env_a,
        submission_env_b=env_b,
    )
    status = _git_output(("status", "--porcelain=v1", "--untracked-files=all"))
    evaluator_path = Path(__file__).resolve()
    adapter_path = ROOT / "ptcg_ai" / "external.py"
    schema_path = ROOT / "training" / "evaluation_schema.py"
    second_trace_path = ROOT / "scripts" / "dipplin_second_trace.py"
    base.update(
        {
            "captured_utc": datetime.now(timezone.utc).isoformat(),
            "hostname": socket.gethostname(),
            "python_executable": sys.executable,
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "multiprocessing_start_method": "spawn",
            "workers": int(args.workers),
            "max_decisions": int(args.max_decisions),
            "deck_a_path": str(deck_a.resolve()),
            "deck_b_path": str(deck_b.resolve()),
            "evaluator_path": str(evaluator_path),
            "evaluator_sha256": sha256_file(evaluator_path),
            "external_adapter_sha256": sha256_file(adapter_path),
            "evaluation_schema_sha256": sha256_file(schema_path),
            "source_head": _git_output(("rev-parse", "HEAD")),
            "source_worktree_dirty": bool(status),
            "source_worktree_status_sha256": _sha256_text(status),
            "process_behavior_environment": _behavior_environment(),
            "archive_a": str(args.archive_a.resolve()) if args.archive_a else None,
            "archive_a_sha256": sha256_file(args.archive_a) if args.archive_a else None,
            "archive_b": str(args.archive_b.resolve()) if args.archive_b else None,
            "archive_b_sha256": sha256_file(args.archive_b) if args.archive_b else None,
            "rng_contract": {
                "engine": "independent_std_random_device",
                "python_numpy_schedule_seed": int(args.seed),
                "paired_deals": False,
                "common_random_numbers": False,
            },
            "runtime_blinding_contract": {
                "hero_receives_opponent_label": False,
                "hero_receives_opponent_package_identity": False,
                "agent_call_payload": "engine_observation_only",
                "labels_added_in_parent_after_game": True,
            },
            "forced_actual_order": args.actual_order,
            "second_bucket_trace": {
                "enabled": bool(args.second_bucket_trace),
                "schema": SECOND_BUCKET_TRACE_SCHEMA,
                "collector_path": str(second_trace_path.resolve()),
                "collector_sha256": sha256_file(second_trace_path),
                "agent_latency_includes_collection": False,
                "public_information_only": True,
            },
        }
    )
    return base


def _parse_env(parser: argparse.ArgumentParser, raw: str, flag: str) -> dict[str, str]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        parser.error(f"{flag} must be a JSON object: {error}")
    if not isinstance(value, dict):
        parser.error(f"{flag} must be a JSON object")
    return {str(key): str(setting) for key, setting in value.items()}


def _resolve_inputs(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> tuple[Path, Path, Path, Path]:
    submission_a = args.submission_a.resolve()
    submission_b = args.submission_b.resolve()
    for label, path in (("--submission-a", submission_a), ("--submission-b", submission_b)):
        if not path.is_dir() or not (path / "main.py").is_file():
            parser.error(f"{label} must be an extracted submission directory: {path}")
    deck_a = (args.deck_a or submission_a / "deck.csv").resolve()
    deck_b = (args.deck_b or submission_b / "deck.csv").resolve()
    try:
        loaded_a = _load_deck(deck_a)
        loaded_b = _load_deck(deck_b)
        packaged_a = _load_deck(submission_a / "deck.csv")
        packaged_b = _load_deck(submission_b / "deck.csv")
    except ValueError as error:
        parser.error(str(error))
    if loaded_a != packaged_a:
        parser.error("--deck-a must exactly match --submission-a/deck.csv")
    if loaded_b != packaged_b:
        parser.error("--deck-b must exactly match --submission-b/deck.csv")
    for flag, archive in (("--archive-a", args.archive_a), ("--archive-b", args.archive_b)):
        if archive is not None and not archive.is_file():
            parser.error(f"{flag} does not exist: {archive}")
    return submission_a, submission_b, deck_a, deck_b


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--submission-a",
        type=Path,
        required=True,
        help="extracted authentic hero (D0/D1) submission directory",
    )
    parser.add_argument(
        "--submission-b",
        type=Path,
        required=True,
        help="extracted authentic opponent submission directory",
    )
    parser.add_argument("--deck-a", type=Path, help="defaults to submission A deck.csv")
    parser.add_argument("--deck-b", type=Path, help="defaults to submission B deck.csv")
    parser.add_argument("--archive-a", type=Path, help="optional source archive to hash")
    parser.add_argument("--archive-b", type=Path, help="optional source archive to hash")
    parser.add_argument(
        "--submission-env-a",
        default="{}",
        help="JSON string of explicit hero environment overrides",
    )
    parser.add_argument(
        "--submission-env-b",
        default="{}",
        help="JSON string of explicit opponent environment overrides",
    )
    parser.add_argument("--hero-name", default="", help="report label only; never sent to a runtime")
    parser.add_argument(
        "--opponent-name",
        default="",
        help="report label only; never sent to the Dipplin runtime",
    )
    parser.add_argument("--games", type=int, default=400)
    parser.add_argument(
        "--actual-order",
        choices=("first", "second"),
        help="force the hero's actual play order while retaining crossed physical seats",
    )
    parser.add_argument(
        "--second-bucket-trace",
        action="store_true",
        help="retain read-only public-board causal diagnostics per game",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=max(1, (mp.cpu_count() or 2) - 1),
    )
    parser.add_argument(
        "--maxtasksperchild",
        type=int,
        default=50,
        help="recycle spawned workers periodically to bound third-party module state",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=20260811,
        help="Python/NumPy schedule only; native engine deals remain independent/unpaired",
    )
    parser.add_argument(
        "--max-decisions",
        type=int,
        default=2000,
        help="fail closed when a game exceeds this many decisions (default: 2000)",
    )
    parser.add_argument("--chunksize", type=int, default=1)
    parser.add_argument("--progress-every", type=int, default=100)
    parser.add_argument(
        "--intervention-key",
        action="append",
        default=[],
        help="additional flat telemetry key whose positive value marks a D1 intervention",
    )
    parser.add_argument("--output", type=Path, required=True, help="full JSON result")
    parser.add_argument("--rows-output", type=Path, help="optional per-game JSONL mirror")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.games <= 0:
        parser.error("--games must be positive")
    if args.workers <= 0 or args.maxtasksperchild <= 0 or args.chunksize <= 0:
        parser.error("--workers, --maxtasksperchild, and --chunksize must be positive")
    if args.max_decisions <= 0:
        parser.error("--max-decisions must be positive")
    if args.progress_every < 0:
        parser.error("--progress-every cannot be negative")

    submission_a, submission_b, deck_a, deck_b = _resolve_inputs(parser, args)
    env_a = _parse_env(parser, args.submission_env_a, "--submission-env-a")
    env_b = _parse_env(parser, args.submission_env_b, "--submission-env-b")
    hero_name = args.hero_name or submission_a.name
    opponent_name = args.opponent_name or submission_b.name
    intervention_keys = tuple(
        dict.fromkeys((*DEFAULT_INTERVENTION_KEYS, *args.intervention_key))
    )
    started = time.time()
    # Hash the actual inputs before any historical package can import, cache,
    # or otherwise mutate its extracted directory.
    provenance = exact_provenance(
        args,
        deck_a=deck_a,
        deck_b=deck_b,
        submission_a=submission_a,
        submission_b=submission_b,
        env_a=env_a,
        env_b=env_b,
    )
    tasks = [
        {
            "game_index": game_index,
            "seed": int(args.seed),
            "submission_a": str(submission_a),
            "submission_b": str(submission_b),
            "deck_a": str(deck_a),
            "deck_b": str(deck_b),
            "submission_env_a": env_a,
            "submission_env_b": env_b,
            "max_decisions": int(args.max_decisions),
            "actual_order": args.actual_order,
            "second_bucket_trace": bool(args.second_bucket_trace),
            # Human labels are intentionally not included in worker tasks.
        }
        for game_index in range(args.games)
    ]

    rows: list[dict[str, Any]] = []
    hero_latency_samples: list[float] = []
    opponent_latency_samples: list[float] = []
    context = mp.get_context("spawn")
    with context.Pool(
        processes=args.workers,
        maxtasksperchild=args.maxtasksperchild,
    ) as pool:
        for complete, row in enumerate(
            pool.imap_unordered(run_game, tasks, chunksize=args.chunksize), 1
        ):
            hero_latency_samples.extend(row.pop("_hero_latency_samples_ms"))
            opponent_latency_samples.extend(row.pop("_opponent_latency_samples_ms"))
            row["hero_name"] = hero_name
            row["opponent_name"] = opponent_name
            intervention_count = max(
                (
                    max(0.0, float(row["hero_telemetry"].get(key, 0.0)))
                    for key in intervention_keys
                    if _is_number(row["hero_telemetry"].get(key, 0.0))
                ),
                default=0.0,
            )
            row["d1_intervened"] = bool(intervention_count > 0.0)
            row["d1_intervention_count"] = intervention_count
            rows.append(row)
            if args.progress_every and complete % args.progress_every == 0:
                complete_rows = sum(int(item["completed"]) for item in rows)
                wins = sum(int(item["win"]) for item in rows)
                print(
                    json.dumps(
                        {
                            "complete": complete,
                            "scheduled": args.games,
                            "completed_games": complete_rows,
                            "win_rate": wins / complete_rows if complete_rows else 0.0,
                            "elapsed_seconds": round(time.time() - started, 3),
                        },
                        sort_keys=True,
                    ),
                    file=sys.stderr,
                    flush=True,
                )

    rows.sort(key=lambda row: int(row["game_index"]))
    cells = seat_order_cells(rows)
    overall = cells["overall"]
    second_bucket_trace_errors = sum(
        len((row.get("second_bucket_trace") or {}).get("trace_errors") or ())
        for row in rows
    )
    second_bucket_traces_complete = sum(
        bool((row.get("second_bucket_trace") or {}).get("collection_complete"))
        for row in rows
    )
    forced_order_accounting_complete = bool(
        args.actual_order is None
        or (
            cells["actual_order"][args.actual_order]["games"] == overall["games"]
            and all(
                row.get("actual_order") == args.actual_order
                for row in rows
                if row.get("completed")
            )
        )
    )
    post_submission_a_sha256 = sha256_path(submission_a)
    post_submission_b_sha256 = sha256_path(submission_b)
    artifacts_unchanged = bool(
        post_submission_a_sha256 == provenance["submission_a_sha256"]
        and post_submission_b_sha256 == provenance["submission_b_sha256"]
    )
    provenance.update(
        {
            "post_evaluation_submission_a_sha256": post_submission_a_sha256,
            "post_evaluation_submission_b_sha256": post_submission_b_sha256,
            "submission_artifacts_unchanged_during_evaluation": artifacts_unchanged,
        }
    )
    elapsed_seconds = time.time() - started
    result = {
        "schema": "dipplin-authentic-evaluation-v1",
        "hero_name": hero_name,
        "opponent_name": opponent_name,
        "scheduled_games": int(args.games),
        "games": int(overall["games"]),
        "wins_a": int(overall["wins"]),
        "win_rate_a": float(overall["win_rate"]),
        "wilson_95": list(overall["wilson_95"]),
        "hero_policy_errors": int(overall["hero_policy_errors"]),
        "opponent_policy_errors": int(overall["opponent_policy_errors"]),
        "hero_illegal_actions": int(overall["hero_illegal_actions"]),
        "opponent_illegal_actions": int(overall["opponent_illegal_actions"]),
        "failed_games": int(overall["failed_games"]),
        "forced_actual_order": args.actual_order,
        "forced_order_accounting_complete": forced_order_accounting_complete,
        "second_bucket_trace": {
            "enabled": bool(args.second_bucket_trace),
            "schema": SECOND_BUCKET_TRACE_SCHEMA,
            "complete_rows": second_bucket_traces_complete,
            "trace_errors": second_bucket_trace_errors,
        },
        "decisions": int(overall["decisions"]),
        "elapsed_seconds": elapsed_seconds,
        "games_per_second": overall["games"] / elapsed_seconds if elapsed_seconds else 0.0,
        "cells": cells,
        # Compatibility aliases used by existing local result readers.
        "overall": overall,
        "seat_results_a": cells["seat"],
        "first_player_results_a": cells["actual_order"],
        "opponent_results_a": {opponent_name: overall},
        "rng_provenance": {
            "engine": "unpaired_std_random_device",
            "python_numpy_seed_schedule": int(args.seed),
            "paired_deals": False,
            "common_random_numbers": False,
        },
        "latency_ms": {
            "measurement": "wall clock around ExternalSubmissionAgent.__call__",
            "quantile_method": "linear interpolation at (n-1)*p",
            "hero": latency_summary(hero_latency_samples),
            "opponent": latency_summary(opponent_latency_samples),
        },
        "hero_telemetry": merge_numeric_rows(rows, "hero_telemetry"),
        "opponent_telemetry": merge_numeric_rows(rows, "opponent_telemetry"),
        "hero_runtime_stats": merge_numeric_rows(rows, "hero_runtime_stats"),
        "hero_search_stats": merge_numeric_rows(rows, "hero_search_stats"),
        "opponent_runtime_stats": merge_numeric_rows(rows, "opponent_runtime_stats"),
        "opponent_search_stats": merge_numeric_rows(rows, "opponent_search_stats"),
        "d1_intervention_analysis": intervention_analysis(rows, intervention_keys),
        "artifact_provenance": provenance,
        "game_rows": rows,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if args.rows_output:
        args.rows_output.parent.mkdir(parents=True, exist_ok=True)
        args.rows_output.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )

    concise = {
        "output": str(args.output.resolve()),
        "scheduled_games": args.games,
        "completed_games": overall["games"],
        "wins": overall["wins"],
        "win_rate": overall["win_rate"],
        "wilson_95": overall["wilson_95"],
        "hero_policy_errors": overall["hero_policy_errors"],
        "opponent_policy_errors": overall["opponent_policy_errors"],
        "hero_illegal_actions": overall["hero_illegal_actions"],
        "opponent_illegal_actions": overall["opponent_illegal_actions"],
        "failed_games": overall["failed_games"],
        "forced_actual_order": args.actual_order,
        "forced_order_accounting_complete": forced_order_accounting_complete,
        "second_bucket_trace": result["second_bucket_trace"],
        "hero_latency_ms": result["latency_ms"]["hero"],
    }
    print(json.dumps(concise, indent=2, sort_keys=True))
    return int(
        bool(
            overall["failed_games"]
            or overall["hero_policy_errors"]
            or overall["opponent_policy_errors"]
            or overall["hero_illegal_actions"]
            or overall["opponent_illegal_actions"]
            or not artifacts_unchanged
            or not forced_order_accounting_complete
            or (args.second_bucket_trace and second_bucket_trace_errors)
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
