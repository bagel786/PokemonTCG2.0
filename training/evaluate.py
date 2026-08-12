#!/usr/bin/env python3
"""Seat-balanced local evaluation with Wilson confidence intervals."""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import random
import time
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

from cg import sim as cg_sim
from cg.api import OptionType, to_observation_class
from cg.game import battle_finish, battle_select, battle_start
from ptcg_ai.card_ids import (
    FROSLASS_VARIANTS,
    MARNIES_GRIMMSNARL_EX,
    MARNIES_IMPIDIMP,
    MARNIES_MORGREM,
    MUNKIDORI,
    SNORUNT,
    SHADOW_BULLET,
)
from ptcg_ai.agent import CompetitionAgent
from ptcg_ai.external import ExternalSubmissionAgent
from ptcg_ai.prevention import attack_nullified
from training.evaluation_schema import build_provenance


def loaded_engine_path() -> Path:
    """Return the native binary path selected and loaded by cg.sim."""
    return Path(cg_sim.lib_path).resolve()


def external_diagnostics(agent):
    """Return numeric telemetry exposed by an authentic external submission."""
    if not isinstance(agent, ExternalSubmissionAgent):
        return {}, {}
    runtime = getattr(agent.module, "RUNTIME_STATS", {})
    search_module = getattr(agent.module, "search", None)
    search = getattr(search_module, "STATS", {})
    numeric = lambda values: {
        str(key): float(value)
        for key, value in values.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    return numeric(runtime), numeric(search)


def policy_error_count(agent) -> int:
    """Count adapter failures plus failures swallowed inside a submission."""
    errors = int(getattr(agent, "errors", 0) or 0)
    if isinstance(agent, ExternalSubmissionAgent):
        inner = getattr(agent.module, "_AGENT", None)
        errors += int(getattr(inner, "errors", 0) or 0)
    return errors


def evaluation_exit_code(hero_errors: int, opponent_errors: int) -> int:
    """Fail closed if either adapter or packaged agent reported a fallback."""
    return int(bool(hero_errors or opponent_errors))


def competition_telemetry(agent) -> dict:
    inner = getattr(agent.module, "_AGENT", None) if isinstance(agent, ExternalSubmissionAgent) else agent
    route = getattr(inner, "route_telemetry", {})
    result = dict(route) if isinstance(route, dict) else {}
    policy = getattr(inner, "policy", None)
    runtime = getattr(policy, "runtime_policy", None)
    telemetry = getattr(runtime, "telemetry", None)
    if callable(telemetry):
        telemetry = telemetry()
    if isinstance(telemetry, dict):
        result["runtime_policy"] = telemetry
    return result


def capture_initial_first_player(current, captured=None):
    """Capture valid opening metadata once; never replace it from a later state."""
    if captured in (0, 1):
        return captured
    value = getattr(current, "firstPlayer", -1) if current is not None else -1
    return int(value) if value in (0, 1) else None


GRIM_LINE = frozenset({MARNIES_IMPIDIMP, MARNIES_MORGREM, MARNIES_GRIMMSNARL_EX})
DEAD_SUPPORT = frozenset({MUNKIDORI, SNORUNT, *FROSLASS_VARIANTS})


def _own_turn_ordinal(turn: int, seat: int, first_player: int | None) -> int:
    if first_player not in (0, 1) or turn <= 0:
        return 0
    return (turn + 1) // 2 if seat == first_player else turn // 2


def _energy_count(pokemon) -> int:
    energies = getattr(pokemon, "energies", None)
    if energies is not None:
        return len(energies)
    return len(getattr(pokemon, "energyCards", None) or [])


def _board(player) -> list:
    return [card for card in (player.active or []) + (player.bench or []) if card is not None]


def _ready_attackers(player) -> int:
    return sum(
        int(
            int(card.id) == MARNIES_IMPIDIMP and _energy_count(card) >= 1
            or int(card.id) == MARNIES_MORGREM and _energy_count(card) >= 2
            or int(card.id) == MARNIES_GRIMMSNARL_EX and _energy_count(card) >= 2
        )
        for card in _board(player)
    )


def _new_game_metrics() -> dict:
    return {
        "ever_attacked": False,
        "total_attacks": 0,
        "shadow_bullet_attacks": 0,
        "first_productive_attack_own_turn": None,
        "first_grim_own_turn": None,
        "first_ready_grim_own_turn": None,
        "board_width_after_own_turn": {"1": 0, "2": 0},
        "marnies_bodies_after_own_turn": {"1": 0, "2": 0},
        "energy_after_own_turn": {"2": 0, "3": 0, "4": 0},
        "ready_attackers_after_own_turn": {"2": 0, "3": 0, "4": 0},
        "late_dead_support_active_turns": 0,
        "dead_support_active_with_ready_bench_grim": 0,
        "trapped_support_active_turns": 0,
        "illegal_actions": 0,
    }


def _record_hero_action(metrics: dict, obs, action: list[int], hero_seat: int, first_player: int | None) -> None:
    if obs.current is None or int(obs.current.yourIndex) != hero_seat:
        return
    player = obs.current.players[hero_seat]
    ordinal = _own_turn_ordinal(int(obs.current.turn), hero_seat, first_player)
    board = _board(player)
    board_ids = {int(card.id) for card in board}
    if metrics["first_grim_own_turn"] is None and MARNIES_GRIMMSNARL_EX in board_ids and ordinal > 0:
        metrics["first_grim_own_turn"] = ordinal
    if metrics["first_ready_grim_own_turn"] is None and any(
        int(card.id) == MARNIES_GRIMMSNARL_EX and _energy_count(card) >= 2 for card in board
    ):
        metrics["first_ready_grim_own_turn"] = ordinal
    if ordinal in (1, 2):
        key = str(ordinal)
        metrics["board_width_after_own_turn"][key] = max(
            metrics["board_width_after_own_turn"][key], len(board)
        )
        metrics["marnies_bodies_after_own_turn"][key] = max(
            metrics["marnies_bodies_after_own_turn"][key],
            sum(int(card.id) in GRIM_LINE for card in board),
        )
    if ordinal in (2, 3, 4):
        key = str(ordinal)
        metrics["energy_after_own_turn"][key] = max(
            metrics["energy_after_own_turn"][key],
            sum(_energy_count(card) for card in board),
        )
        metrics["ready_attackers_after_own_turn"][key] = max(
            metrics["ready_attackers_after_own_turn"][key], _ready_attackers(player)
        )

    active = (player.active or [None])[0]
    if active is not None and int(active.id) in DEAD_SUPPORT and ordinal >= 4:
        metrics["late_dead_support_active_turns"] += 1
        ready_bench = any(
            int(card.id) == MARNIES_GRIMMSNARL_EX and _energy_count(card) >= 2
            for card in (player.bench or [])
        )
        if ready_bench:
            metrics["dead_support_active_with_ready_bench_grim"] += 1
            if not any(int(option.type) == int(OptionType.RETREAT) for option in obs.select.option):
                metrics["trapped_support_active_turns"] += 1

    for index in action:
        if not isinstance(index, int) or not 0 <= index < len(obs.select.option):
            metrics["illegal_actions"] += 1
            continue
        option = obs.select.option[index]
        if int(option.type) != int(OptionType.ATTACK):
            continue
        metrics["ever_attacked"] = True
        metrics["total_attacks"] += 1
        if int(getattr(option, "attackId", 0) or 0) == SHADOW_BULLET:
            metrics["shadow_bullet_attacks"] += 1
        if metrics["first_productive_attack_own_turn"] is None:
            try:
                productive = not attack_nullified(obs, option)
            except Exception:
                productive = False
            if productive:
                metrics["first_productive_attack_own_turn"] = ordinal


def _finish_game_metrics(metrics: dict, obs, hero_seat: int, first_player: int | None) -> dict:
    state = obs.current
    hero = state.players[hero_seat]
    opponent = state.players[1 - hero_seat]
    hero_prizes = 6 - len(hero.prize or [])
    opponent_prizes = 6 - len(opponent.prize or [])
    loss = int(state.result != hero_seat)
    public_margin = opponent_prizes - hero_prizes
    result = dict(metrics)
    result.update(
        {
            "win": int(state.result == hero_seat),
            "actual_order": "first" if first_player == hero_seat else "second",
            "physical_seat": hero_seat,
            "prizes_taken": hero_prizes,
            "prizes_conceded": opponent_prizes,
            "zero_attack_game": int(not metrics["ever_attacked"]),
            "zero_prize_game": int(hero_prizes == 0),
            "blowout_loss": int(loss and public_margin >= 4),
            "catastrophic_floor_game": int(
                not metrics["ever_attacked"] or hero_prizes == 0 or loss and public_margin >= 4
            ),
        }
    )
    return result


def summarize_game_metrics(rows: list[dict], *, include_order: bool = True) -> dict:
    """Aggregate floor mechanisms without treating intervention games as causal."""

    games = len(rows)
    if not games:
        return {"games": 0}

    def rate(key: str) -> float:
        return sum(int(row.get(key, 0)) for row in rows) / games

    result = {
        "games": games,
        "wins": sum(int(row.get("win", 0)) for row in rows),
        "win_rate": sum(int(row.get("win", 0)) for row in rows) / games,
        "zero_attack_rate": rate("zero_attack_game"),
        "zero_prize_rate": rate("zero_prize_game"),
        "blowout_loss_rate": rate("blowout_loss"),
        "catastrophic_floor_rate": rate("catastrophic_floor_game"),
        "total_attacks": sum(int(row.get("total_attacks", 0)) for row in rows),
        "policy_errors": sum(int(row.get("policy_errors", 0)) for row in rows),
        "illegal_actions": sum(int(row.get("illegal_actions", 0)) for row in rows),
        "mean_first_productive_attack_own_turn": (
            sum(
                int(row["first_productive_attack_own_turn"])
                for row in rows
                if row.get("first_productive_attack_own_turn") is not None
            )
            / sum(row.get("first_productive_attack_own_turn") is not None for row in rows)
            if any(row.get("first_productive_attack_own_turn") is not None for row in rows)
            else None
        ),
    }
    if include_order:
        result["by_actual_order"] = {
            order: summarize_game_metrics(
                [row for row in rows if row.get("actual_order") == order],
                include_order=False,
            )
            for order in ("first", "second")
        }
    return result


def _game_intervention_counts(telemetry: dict) -> dict[str, int]:
    runtime = telemetry.get("runtime_policy", {}) if isinstance(telemetry, dict) else {}
    guardrail = runtime.get("guardrail", {}) if isinstance(runtime, dict) else {}
    counts: dict[str, int] = {}
    for field in ("interventions", "variance_interventions"):
        values = guardrail.get(field, {}) if isinstance(guardrail, dict) else {}
        if isinstance(values, dict):
            for reason, count in values.items():
                counts[str(reason)] = counts.get(str(reason), 0) + int(count)
    return counts


def run_game_diagnostic(task):
    index, deck_a_path, model_a, deck_b_path, model_b, *external = task
    seed = int(external[4]) if len(external) > 4 else 0
    max_decisions = int(external[5]) if len(external) > 5 else 0
    random.seed(seed + index)
    try:
        import numpy as np

        np.random.seed((seed + index) % (2**32))
    except ImportError:
        pass
    deck_a = [int(line) for line in Path(deck_a_path).read_text().splitlines() if line.strip()]
    deck_b = [int(line) for line in Path(deck_b_path).read_text().splitlines() if line.strip()]
    seat_a = index % 2
    decks = [deck_a, deck_b] if seat_a == 0 else [deck_b, deck_a]
    hero = (
        ExternalSubmissionAgent(external[0], external[1] if len(external) > 1 else {})
        if external and external[0]
        else CompetitionAgent(deck_a_path, model_a or None)
    )
    opponent = (
        ExternalSubmissionAgent(external[2], external[3] if len(external) > 3 else {})
        if len(external) > 2 and external[2]
        else CompetitionAgent(deck_b_path, model_b or None)
    )
    agents = {
        seat_a: hero,
        1 - seat_a: opponent,
    }
    raw, start = battle_start(decks[0], decks[1])
    if start.errorType != 0:
        raise RuntimeError(f"engine rejected deck: {start.errorType}")
    try:
        decisions = 0
        initial_first_player = None
        game_metrics = _new_game_metrics()
        while True:
            obs = to_observation_class(raw)
            # Terminal observations are not a reliable source of setup metadata:
            # some engine builds clear/reset firstPlayer while resolving DONE.
            # Capture it once from the first live state and retain it for the report.
            initial_first_player = capture_initial_first_player(obs.current, initial_first_player)
            if obs.current is not None and obs.current.result != -1:
                runtime_stats, search_stats = external_diagnostics(opponent)
                game_metrics = _finish_game_metrics(
                    game_metrics, obs, seat_a, initial_first_player
                )
                game_metrics["policy_errors"] = policy_error_count(agents[seat_a])
                return {
                    "win": int(obs.current.result == seat_a),
                    "seat_a": seat_a,
                    "hero_went_first": bool(initial_first_player == seat_a),
                    "initial_first_player": initial_first_player,
                    "hero_errors": policy_error_count(agents[seat_a]),
                    "opponent_errors": policy_error_count(agents[1 - seat_a]),
                    "opponent_runtime_stats": runtime_stats,
                    "opponent_search_stats": search_stats,
                    "hero_telemetry": competition_telemetry(agents[seat_a]),
                    "game_metrics": game_metrics,
                    "decisions": decisions,
                }
            acting_seat = int(obs.current.yourIndex)
            action = agents[acting_seat](raw)
            if acting_seat == seat_a:
                _record_hero_action(game_metrics, obs, action, seat_a, initial_first_player)
            raw = battle_select(action)
            decisions += 1
            if max_decisions and decisions >= max_decisions:
                raise RuntimeError(f"game exceeded fail-closed decision cap: {max_decisions}")
    finally:
        battle_finish()
        for agent in (hero, opponent):
            if isinstance(agent, ExternalSubmissionAgent):
                agent.close()


def run_game(task):
    return run_game_diagnostic(task)["win"]


def wilson(wins, games, z=1.96):
    if games == 0:
        return 0.0, 1.0
    p = wins / games
    denominator = 1 + z * z / games
    center = (p + z * z / (2 * games)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * games)) / games) / denominator
    return center - margin, center + margin


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deck-a", required=True)
    parser.add_argument("--model-a", default="")
    parser.add_argument("--deck-b", required=True)
    parser.add_argument("--model-b", default="")
    parser.add_argument("--submission-a", default="", help="authentic submission directory for player A")
    parser.add_argument("--submission-env-a", default="{}", help="JSON environment overrides for player A")
    parser.add_argument("--submission-b", default="", help="authentic submission directory for player B")
    parser.add_argument("--submission-env-b", default="{}", help="JSON environment overrides for player B")
    parser.add_argument("--opponent-name", default="", help="stable opponent identifier recorded in the shard")
    parser.add_argument("--games", type=int, default=2000)
    parser.add_argument("--workers", type=int, default=max(1, (mp.cpu_count() or 2) - 1))
    parser.add_argument(
        "--seed", type=int, default=20260729,
        help="Python/NumPy schedule only; engine std::random_device remains independent/unpaired",
    )
    parser.add_argument("--max-decisions", type=int, default=0, help="fail a game at this decision count; 0 disables")
    parser.add_argument("--output", help="optional JSON result path")
    args = parser.parse_args()
    started = time.time()
    submission_a = str(Path(args.submission_a).resolve()) if args.submission_a else ""
    submission_env_a = {str(key): str(value) for key, value in json.loads(args.submission_env_a).items()}
    submission_b = str(Path(args.submission_b).resolve()) if args.submission_b else ""
    submission_env_b = {str(key): str(value) for key, value in json.loads(args.submission_env_b).items()}
    tasks = [
        (
            index,
            str(Path(args.deck_a).resolve()),
            args.model_a,
            str(Path(args.deck_b).resolve()),
            args.model_b,
            submission_a,
            submission_env_a,
            submission_b,
            submission_env_b,
            args.seed,
            args.max_decisions,
        )
        for index in range(args.games)
    ]
    context = mp.get_context("spawn")
    wins = hero_errors = opponent_errors = decisions = 0
    seat_games = [0, 0]
    seat_wins = [0, 0]
    first_order_games = {"first": 0, "second": 0}
    first_order_wins = {"first": 0, "second": 0}
    opponent_runtime_stats = {}
    opponent_search_stats = {}
    hero_telemetry = {}
    game_metrics_rows = []
    intervention_counts = {}

    def merge_stats(total, current):
        for key, value in current.items():
            # Route telemetry also carries audit metadata such as ``None``
            # activation steps and lists of public evidence.  Gameplay
            # aggregation is numeric-only; attempting to add those fields made
            # otherwise valid evaluations crash before producing a report.
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            if key.endswith("_max"):
                total[key] = max(total.get(key, 0.0), value)
            else:
                total[key] = total.get(key, 0.0) + value

    with context.Pool(args.workers) as pool:
        for complete, result in enumerate(pool.imap_unordered(run_game_diagnostic, tasks, chunksize=4), 1):
            wins += result["win"]
            hero_errors += result["hero_errors"]
            opponent_errors += result["opponent_errors"]
            decisions += result["decisions"]
            seat = result["seat_a"]
            seat_games[seat] += 1
            seat_wins[seat] += result["win"]
            order = "first" if result["hero_went_first"] else "second"
            first_order_games[order] += 1
            first_order_wins[order] += result["win"]
            merge_stats(opponent_runtime_stats, result["opponent_runtime_stats"])
            merge_stats(opponent_search_stats, result["opponent_search_stats"])
            merge_stats(hero_telemetry, result["hero_telemetry"])
            game_metrics_rows.append(result["game_metrics"])
            for reason, count in _game_intervention_counts(result["hero_telemetry"]).items():
                intervention_counts[reason] = intervention_counts.get(reason, 0) + count
            if complete % 500 == 0:
                print({"complete": complete, "win_rate_a": wins / complete})
    lower, upper = wilson(wins, args.games)
    opponent_name = args.opponent_name or (Path(submission_b).name if submission_b else Path(args.deck_b).stem)
    provenance = build_provenance(
        root=ROOT,
        deck_a=args.deck_a,
        model_a=args.model_a or None,
        deck_b=args.deck_b,
        model_b=args.model_b or None,
        submission_a=submission_a or None,
        submission_b=submission_b or None,
        engine_path=loaded_engine_path(),
        seed=args.seed,
        submission_env_a=submission_env_a,
        submission_env_b=submission_env_b,
    )
    result = {
        "games": args.games,
        "wins_a": wins,
        "win_rate_a": wins / args.games,
        "wilson_95": [lower, upper],
        "overall": {
            "games": args.games,
            "wins": wins,
            "win_rate": wins / args.games,
            "wilson_95": [lower, upper],
        },
        "deck_a": args.deck_a,
        "model_a": args.model_a or "heuristic",
        "deck_b": args.deck_b,
        "model_b": args.model_b or "heuristic",
        "submission_b": submission_b or None,
        "submission_a": submission_a or None,
        "hero_policy_errors": hero_errors,
        "opponent_policy_errors": opponent_errors,
        "seat_results_a": {
            str(seat): {
                "games": seat_games[seat],
                "wins": seat_wins[seat],
                "win_rate": seat_wins[seat] / seat_games[seat] if seat_games[seat] else 0.0,
            }
            for seat in range(2)
        },
        "first_player_results_a": {
            order: {
                "games": first_order_games[order],
                "wins": first_order_wins[order],
                "win_rate": first_order_wins[order] / first_order_games[order]
                if first_order_games[order] else 0.0,
            }
            for order in ("first", "second")
        },
        "rng_provenance": {
            "engine": "unpaired_std_random_device",
            "python_numpy_seed_schedule": args.seed,
            "paired_deals": False,
        },
        "opponent_results_a": {
            opponent_name: {
                "games": args.games,
                "wins": wins,
                "win_rate": wins / args.games,
                "wilson_95": [lower, upper],
            }
        },
        "artifact_provenance": provenance,
        "elapsed_seconds": time.time() - started,
        "opponent_runtime_stats": opponent_runtime_stats,
        "opponent_search_stats": opponent_search_stats,
        "hero_telemetry": hero_telemetry,
        "game_metrics": summarize_game_metrics(game_metrics_rows),
        "games_detail": game_metrics_rows,
        "intervention_counts": dict(sorted(intervention_counts.items())),
        "decisions": decisions,
    }
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(result)
    return evaluation_exit_code(hero_errors, opponent_errors)


if __name__ == "__main__":
    raise SystemExit(main())
