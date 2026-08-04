#!/usr/bin/env python3
"""Seat-balanced qualification evaluation for a training-only search teacher."""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
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
from training.azure_guard import enforce_azure_workload
from training.evaluate import capture_initial_first_player, wilson
from training.mcts_teacher import InformationSetMCTSAgent, MCTSConfig
from training.search_teacher import SearchConfig, SearchTeacherAgent, load_deck


def run_game(task: tuple) -> dict:
    index, deck_a_path, model_a, deck_b_path, model_b, agent_kind, config = task
    seat_a = index % 2
    deck_a = load_deck(deck_a_path)
    deck_b = load_deck(deck_b_path)
    decks = [deck_a, deck_b] if seat_a == 0 else [deck_b, deck_a]
    teacher_class, teacher_config = (
        (InformationSetMCTSAgent, MCTSConfig(**config))
        if agent_kind == "mcts"
        else (SearchTeacherAgent, SearchConfig(**config))
    )
    teacher = teacher_class(deck_a_path, model_a, deck_b_path, model_b, teacher_config)
    opponent = CompetitionAgent(deck_b_path, model_b)
    raw, start = battle_start(decks[0], decks[1])
    if start.errorType != 0:
        raise RuntimeError(f"engine rejected deck: {start.errorType}")
    initial_first_player = None
    decisions = 0
    try:
        while True:
            obs = to_observation_class(raw)
            initial_first_player = capture_initial_first_player(obs.current, initial_first_player)
            if obs.current is not None and obs.current.result != -1:
                telemetry = teacher.telemetry()
                return {
                    "win": int(obs.current.result == seat_a),
                    "seat_a": seat_a,
                    "hero_went_first": (
                        None if initial_first_player is None else bool(initial_first_player == seat_a)
                    ),
                    "teacher_errors": telemetry["search_errors"],
                    "teacher_calls": telemetry["search_calls"],
                    "teacher_rollouts": telemetry["search_rollouts"],
                    "teacher_simulations": telemetry.get("search_simulations", 0),
                    "teacher_nodes": telemetry.get("search_nodes", 0),
                    "teacher_error_counts": telemetry["search_error_counts"],
                    "last_teacher_error": telemetry["last_search_error"],
                    "opponent_errors": opponent.errors,
                    "decisions": decisions,
                }
            action = teacher(raw) if obs.current.yourIndex == seat_a else opponent(raw)
            raw = battle_select(action)
            decisions += 1
    finally:
        battle_finish()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deck-a", required=True)
    parser.add_argument("--model-a", required=True, help="frozen neural prior for the teacher")
    parser.add_argument("--deck-b", required=True)
    parser.add_argument("--model-b", required=True, help="frozen opponent policy")
    parser.add_argument("--games", type=int, default=1_000)
    parser.add_argument("--workers", type=int, default=max(1, (mp.cpu_count() or 2) - 1))
    parser.add_argument("--agent-kind", choices=("rollout", "mcts"), default="rollout")
    parser.add_argument("--determinizations", type=int, default=2)
    parser.add_argument("--max-candidates", type=int, default=8)
    parser.add_argument("--candidate-width", type=int, default=8)
    parser.add_argument("--candidate-mode", choices=("prior", "exhaustive"), default="prior")
    parser.add_argument("--rollout-steps", type=int, default=320)
    parser.add_argument("--mcts-simulations", type=int, default=48)
    parser.add_argument("--mcts-max-depth", type=int, default=64)
    parser.add_argument("--mcts-puct-c", type=float, default=1.5)
    parser.add_argument("--mcts-tree-max-candidates", type=int, default=8)
    parser.add_argument("--mcts-leaf-rollout-steps", type=int, default=0)
    parser.add_argument("--mcts-rollout-weight", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=20260803)
    parser.add_argument("--output")
    parser.add_argument("--allow-local-smoke", action="store_true")
    args = parser.parse_args()
    enforce_azure_workload(allow_local_smoke=args.allow_local_smoke, workload_size=args.games)

    if args.agent_kind == "mcts":
        config = {
            "determinizations": args.determinizations,
            "simulations": args.mcts_simulations,
            "max_depth": args.mcts_max_depth,
            "puct_c": args.mcts_puct_c,
            "root_max_candidates": args.max_candidates,
            "tree_max_candidates": args.mcts_tree_max_candidates,
            "tree_candidate_width": args.candidate_width,
            "leaf_rollout_steps": args.mcts_leaf_rollout_steps,
            "rollout_weight": args.mcts_rollout_weight,
            "seed": args.seed,
        }
    else:
        config = {
            "determinizations": args.determinizations,
            "max_candidates": args.max_candidates,
            "candidate_width": args.candidate_width,
            "candidate_mode": args.candidate_mode,
            "rollout_steps": args.rollout_steps,
            "seed": args.seed,
        }
    tasks = [
        (
            index,
            str(Path(args.deck_a).resolve()),
            str(Path(args.model_a).resolve()),
            str(Path(args.deck_b).resolve()),
            str(Path(args.model_b).resolve()),
            args.agent_kind,
            {**config, "seed": args.seed + index * 1_000_003},
        )
        for index in range(args.games)
    ]
    wins = decisions = teacher_errors = teacher_calls = teacher_rollouts = opponent_errors = 0
    teacher_simulations = teacher_nodes = 0
    teacher_error_counts: dict[str, int] = {}
    last_teacher_error = ""
    seat_games = [0, 0]
    seat_wins = [0, 0]
    first_games = {"first": 0, "second": 0, "unknown": 0}
    first_wins = {"first": 0, "second": 0, "unknown": 0}
    context = mp.get_context("spawn")
    with context.Pool(args.workers) as pool:
        for complete, row in enumerate(pool.imap_unordered(run_game, tasks, chunksize=1), 1):
            wins += row["win"]
            decisions += row["decisions"]
            teacher_errors += row["teacher_errors"]
            teacher_calls += row["teacher_calls"]
            teacher_rollouts += row["teacher_rollouts"]
            teacher_simulations += row["teacher_simulations"]
            teacher_nodes += row["teacher_nodes"]
            for key, value in row["teacher_error_counts"].items():
                teacher_error_counts[key] = teacher_error_counts.get(key, 0) + value
            last_teacher_error = row["last_teacher_error"] or last_teacher_error
            opponent_errors += row["opponent_errors"]
            seat_games[row["seat_a"]] += 1
            seat_wins[row["seat_a"]] += row["win"]
            order = (
                "unknown" if row["hero_went_first"] is None
                else ("first" if row["hero_went_first"] else "second")
            )
            first_games[order] += 1
            first_wins[order] += row["win"]
            if complete % 25 == 0 or complete == args.games:
                print(
                    {"complete": complete, "win_rate_a": wins / complete, "search_errors": teacher_errors},
                    flush=True,
                )

    lower, upper = wilson(wins, args.games)
    report = {
        "version": 2,
        "kind": f"information_set_{args.agent_kind}_teacher_qualification",
        "games": args.games,
        "wins_a": wins,
        "win_rate_a": wins / args.games,
        "wilson_95": [lower, upper],
        "deck_a": args.deck_a,
        "model_a": args.model_a,
        "deck_b": args.deck_b,
        "model_b": args.model_b,
        "config": config,
        "teacher_search_errors": teacher_errors,
        "teacher_search_calls": teacher_calls,
        "teacher_rollouts": teacher_rollouts,
        "teacher_simulations": teacher_simulations,
        "teacher_nodes": teacher_nodes,
        "teacher_error_counts": teacher_error_counts,
        "last_teacher_error": last_teacher_error,
        "opponent_policy_errors": opponent_errors,
        "decisions": decisions,
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
                "games": first_games[order],
                "wins": first_wins[order],
                "win_rate": first_wins[order] / first_games[order] if first_games[order] else 0.0,
            }
            for order in ("first", "second", "unknown")
        },
        "qualified": (
            wins / args.games >= 0.25
            and all(
                seat_wins[seat] / seat_games[seat] >= 0.20
                for seat in range(2)
                if seat_games[seat]
            )
            and teacher_errors == 0
            and opponent_errors == 0
        ),
    }
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
