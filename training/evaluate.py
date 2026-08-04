#!/usr/bin/env python3
"""Seat-balanced local evaluation with Wilson confidence intervals."""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

from cg.api import to_observation_class
from cg.game import battle_finish, battle_select, battle_start
from ptcg_ai.agent import CompetitionAgent
from ptcg_ai.external import ExternalSubmissionAgent


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


def capture_initial_first_player(current, captured=None):
    """Capture valid opening metadata once; never replace it from a later state."""
    if captured in (0, 1):
        return captured
    value = getattr(current, "firstPlayer", -1) if current is not None else -1
    return int(value) if value in (0, 1) else None


def run_game_diagnostic(task):
    index, deck_a_path, model_a, deck_b_path, model_b, *external = task
    seed = int(external[2]) if len(external) > 2 else 0
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
    opponent = (
        ExternalSubmissionAgent(external[0], external[1] if len(external) > 1 else {})
        if external and external[0]
        else CompetitionAgent(deck_b_path, model_b or None)
    )
    agents = {
        seat_a: CompetitionAgent(deck_a_path, model_a or None),
        1 - seat_a: opponent,
    }
    raw, start = battle_start(decks[0], decks[1])
    if start.errorType != 0:
        raise RuntimeError(f"engine rejected deck: {start.errorType}")
    try:
        decisions = 0
        initial_first_player = None
        while True:
            obs = to_observation_class(raw)
            # Terminal observations are not a reliable source of setup metadata:
            # some engine builds clear/reset firstPlayer while resolving DONE.
            # Capture it once from the first live state and retain it for the report.
            initial_first_player = capture_initial_first_player(obs.current, initial_first_player)
            if obs.current is not None and obs.current.result != -1:
                runtime_stats, search_stats = external_diagnostics(opponent)
                return {
                    "win": int(obs.current.result == seat_a),
                    "seat_a": seat_a,
                    "hero_went_first": bool(initial_first_player == seat_a),
                    "initial_first_player": initial_first_player,
                    "hero_errors": agents[seat_a].errors,
                    "opponent_errors": agents[1 - seat_a].errors,
                    "opponent_runtime_stats": runtime_stats,
                    "opponent_search_stats": search_stats,
                    "decisions": decisions,
                }
            raw = battle_select(agents[obs.current.yourIndex](raw))
            decisions += 1
    finally:
        battle_finish()
        if isinstance(opponent, ExternalSubmissionAgent):
            opponent.close()


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
    parser.add_argument("--submission-b", default="", help="authentic submission directory for player B")
    parser.add_argument("--submission-env-b", default="{}", help="JSON environment overrides for player B")
    parser.add_argument("--games", type=int, default=2000)
    parser.add_argument("--workers", type=int, default=max(1, (mp.cpu_count() or 2) - 1))
    parser.add_argument("--seed", type=int, default=20260729, help="paired per-game Python/NumPy seed schedule")
    parser.add_argument("--output", help="optional JSON result path")
    args = parser.parse_args()
    submission_b = str(Path(args.submission_b).resolve()) if args.submission_b else ""
    submission_env_b = {str(key): str(value) for key, value in json.loads(args.submission_env_b).items()}
    tasks = [
        (
            index,
            str(Path(args.deck_a).resolve()),
            args.model_a,
            str(Path(args.deck_b).resolve()),
            args.model_b,
            submission_b,
            submission_env_b,
            args.seed,
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

    def merge_stats(total, current):
        for key, value in current.items():
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
            if complete % 500 == 0:
                print({"complete": complete, "win_rate_a": wins / complete})
    lower, upper = wilson(wins, args.games)
    result = {
        "games": args.games,
        "wins_a": wins,
        "win_rate_a": wins / args.games,
        "wilson_95": [lower, upper],
        "deck_a": args.deck_a,
        "model_a": args.model_a or "heuristic",
        "deck_b": args.deck_b,
        "model_b": args.model_b or "heuristic",
        "submission_b": submission_b or None,
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
        "opponent_runtime_stats": opponent_runtime_stats,
        "opponent_search_stats": opponent_search_stats,
        "decisions": decisions,
    }
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
