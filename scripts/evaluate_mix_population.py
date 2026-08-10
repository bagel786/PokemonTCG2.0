#!/usr/bin/env python3
"""Run a compact forced-order payoff matrix for policy-mix candidates."""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from cg.api import OptionType, SelectContext, to_observation_class
from cg.game import battle_finish, battle_select, battle_start
from ptcg_ai.external import ExternalSubmissionAgent
from ptcg_ai.safety import sanitize_selection
from training.evaluation_schema import sha256_path


def _force(select, hero_seat: int, order: str) -> list[int]:
    seat_zero_first = (order == "first") == (hero_seat == 0)
    desired = OptionType.YES if seat_zero_first else OptionType.NO
    choices = [index for index, option in enumerate(select.option) if option.type == desired]
    if len(choices) != 1:
        raise RuntimeError("invalid IS_FIRST choice set")
    return sanitize_selection(select, choices, 1)


def _errors(agent: ExternalSubmissionAgent) -> int:
    inner = getattr(agent.module, "_AGENT", None)
    return int(agent.errors) + int(getattr(inner, "errors", 0) or 0)


def run_game(task: dict) -> dict:
    random.seed(task["seed"])
    hero_path = Path(task["hero_path"])
    opponent_path = Path(task["opponent_path"])
    hero_deck = [int(x) for x in (hero_path / "deck.csv").read_text().splitlines() if x.strip()]
    opponent_deck = [int(x) for x in (opponent_path / "deck.csv").read_text().splitlines() if x.strip()]
    hero_seat = task["game_index"] % 2
    decks = [hero_deck, opponent_deck] if hero_seat == 0 else [opponent_deck, hero_deck]
    hero = ExternalSubmissionAgent(hero_path, task.get("hero_env", {}))
    opponent = ExternalSubmissionAgent(opponent_path, task.get("opponent_env", {}))
    agents = {hero_seat: hero, 1 - hero_seat: opponent}
    raw, started = battle_start(decks[0], decks[1])
    if started.errorType:
        hero.close(); opponent.close()
        raise RuntimeError(f"engine rejected deck: {started.errorType}")
    first_player = None
    decisions = 0
    try:
        while True:
            obs = to_observation_class(raw)
            if obs.current is not None and int(obs.current.firstPlayer) in (0, 1):
                observed = int(obs.current.firstPlayer)
                if first_player is None:
                    first_player = observed
                elif first_player != observed:
                    raise RuntimeError("firstPlayer changed")
            if obs.current is not None and int(obs.current.result) >= 0:
                actual_order = "first" if first_player == hero_seat else "second"
                if actual_order != task["order"]:
                    raise RuntimeError(f"requested {task['order']}, observed {actual_order}")
                return {
                    "candidate": task["candidate"], "opponent": task["opponent"],
                    "group": task["group"], "order": actual_order,
                    "win": int(int(obs.current.result) == hero_seat),
                    "draw": int(int(obs.current.result) == 2),
                    "hero_errors": _errors(hero), "opponent_errors": _errors(opponent),
                    "decisions": decisions,
                }
            if obs.select.context == SelectContext.IS_FIRST:
                action = _force(obs.select, hero_seat, task["order"])
            else:
                action = agents[int(obs.current.yourIndex)](raw)
            raw = battle_select(action)
            decisions += 1
            if decisions >= task["max_decisions"]:
                raise RuntimeError("decision cap exceeded")
    finally:
        battle_finish(); hero.close(); opponent.close()


def _rate(row: dict) -> float:
    return row["wins"] / row["games"] if row["games"] else 0.0


def _wilson(wins: int, games: int, z: float = 1.6448536269514722) -> float:
    if games <= 0:
        return 0.0
    p = wins / games
    den = 1 + z * z / games
    center = (p + z * z / (2 * games)) / den
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * games)) / games) / den
    return center - margin


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=max(1, (mp.cpu_count() or 2) - 1))
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    tasks = []
    for candidate in config["candidates"]:
        for opponent in config["opponents"]:
            games = int(opponent.get("games_per_order", config["games_per_order"]))
            for order_index, order in enumerate(("first", "second")):
                for game_index in range(games):
                    tasks.append({
                        "candidate": candidate["name"], "hero_path": str((ROOT / candidate["path"]).resolve()),
                        "hero_env": candidate.get("env", {}),
                        "opponent": opponent["name"], "opponent_path": str((ROOT / opponent["path"]).resolve()),
                        "opponent_env": opponent.get("env", {}), "group": opponent["group"],
                        "order": order, "game_index": game_index,
                        "seed": int(config["seed"]) + int(opponent.get("seed_offset", 0)) + order_index * 1_000_000 + game_index,
                        "max_decisions": int(config.get("max_decisions", 2000)),
                    })
    started = time.time()
    rows = []
    context = mp.get_context("spawn")
    with context.Pool(args.workers) as pool:
        for complete, row in enumerate(pool.imap_unordered(run_game, tasks, chunksize=2), 1):
            rows.append(row)
            if complete % 250 == 0:
                print(json.dumps({"complete": complete, "total": len(tasks), "elapsed_seconds": round(time.time() - started, 1)}), flush=True)

    cells = defaultdict(lambda: {"games": 0, "wins": 0, "draws": 0, "hero_errors": 0, "opponent_errors": 0, "decisions": 0})
    for row in rows:
        for key in ((row["candidate"], row["opponent"], row["order"]),
                    (row["candidate"], row["opponent"], "overall"),
                    (row["candidate"], row["group"], row["order"]),
                    (row["candidate"], row["group"], "overall"),
                    (row["candidate"], "all", row["order"]),
                    (row["candidate"], "all", "overall")):
            cell = cells[key]
            cell["games"] += 1; cell["wins"] += row["win"]; cell["draws"] += row["draw"]
            cell["hero_errors"] += row["hero_errors"]; cell["opponent_errors"] += row["opponent_errors"]
            cell["decisions"] += row["decisions"]

    table = []
    weights = {row["name"]: float(row["weight"]) for row in config["opponents"]}
    total_weight = sum(weights.values())
    for candidate in config["candidates"]:
        name = candidate["name"]
        weighted = sum(weights[opp] * _rate(cells[(name, opp, "overall")]) for opp in weights) / total_weight
        aggregate = cells[(name, "all", "overall")]
        table.append({
            "candidate": name, "games": aggregate["games"], "raw_win_rate": _rate(aggregate),
            "weighted_win_rate": weighted,
            "first_win_rate": _rate(cells[(name, "all", "first")]),
            "second_win_rate": _rate(cells[(name, "all", "second")]),
            "grim_win_rate": _rate(cells[(name, "grim", "overall")]),
            "alakazam_win_rate": _rate(cells[(name, "alakazam", "overall")]),
            "one_sided_95_lower_raw": _wilson(aggregate["wins"], aggregate["games"]),
            "hero_policy_errors": aggregate["hero_errors"],
            "opponent_policy_errors": aggregate["opponent_errors"],
            "decisions": aggregate["decisions"],
        })
    cell_output = {
        "|".join(key): {**value, "win_rate": _rate(value)}
        for key, value in sorted(cells.items())
    }
    result = {
        "config": config, "elapsed_seconds": time.time() - started,
        "candidate_hashes": {c["name"]: sha256_path((ROOT / c["path"]).resolve()) for c in config["candidates"]},
        "opponent_hashes": {o["name"]: sha256_path((ROOT / o["path"]).resolve()) for o in config["opponents"]},
        "summary": sorted(table, key=lambda row: row["weighted_win_rate"], reverse=True),
        "cells": cell_output,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
