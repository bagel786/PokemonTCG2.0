#!/usr/bin/env python3
"""Evaluate one policy independently against every tracked meta archetype."""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from training.evaluate import run_game_diagnostic, wilson


def resolve(path: str) -> str:
    value = Path(path)
    return str(value if value.is_absolute() else (ROOT / value).resolve())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hero-deck", required=True)
    parser.add_argument("--hero-model", default="")
    parser.add_argument("--league", default="training/meta_league.json")
    parser.add_argument("--games-per-opponent", type=int, default=2000)
    parser.add_argument("--workers", type=int, default=max(1, (mp.cpu_count() or 2) - 1))
    parser.add_argument("--output")
    args = parser.parse_args()

    entries = [entry for entry in json.loads(Path(args.league).read_text())["opponents"] if entry.get("evaluate")]
    context = mp.get_context("spawn")
    results = []
    weighted_wins = weighted_games = 0.0
    with context.Pool(args.workers) as pool:
        for entry in entries:
            tasks = [
                (
                    index,
                    resolve(args.hero_deck),
                    resolve(args.hero_model) if args.hero_model else "",
                    resolve(entry["deck"]),
                    resolve(entry.get("model", "")) if entry.get("model") else "",
                    resolve(entry.get("submission", "")) if entry.get("submission") else "",
                    {str(key): str(value) for key, value in entry.get("submission_env", {}).items()},
                )
                for index in range(args.games_per_opponent)
            ]
            diagnostics = list(pool.imap_unordered(run_game_diagnostic, tasks, chunksize=4))
            wins = sum(row["win"] for row in diagnostics)
            hero_errors = sum(row["hero_errors"] for row in diagnostics)
            opponent_errors = sum(row["opponent_errors"] for row in diagnostics)
            decisions = sum(row["decisions"] for row in diagnostics)
            lower, upper = wilson(wins, args.games_per_opponent)
            weight = float(entry.get("meta_weight", 1.0))
            weighted_wins += weight * wins
            weighted_games += weight * args.games_per_opponent
            row = {
                "opponent": entry["name"],
                "games": args.games_per_opponent,
                "wins": wins,
                "win_rate": wins / args.games_per_opponent,
                "wilson_95": [lower, upper],
                "meta_weight": weight,
                "hero_policy_errors": hero_errors,
                "opponent_policy_errors": opponent_errors,
                "decisions": decisions,
            }
            results.append(row)
            print(row)
    report = {
        "hero_deck": args.hero_deck,
        "hero_model": args.hero_model or "heuristic",
        "games_per_opponent": args.games_per_opponent,
        "total_games": args.games_per_opponent * len(entries),
        "meta_weighted_win_rate": weighted_wins / max(1.0, weighted_games),
        "matchups": results,
    }
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
