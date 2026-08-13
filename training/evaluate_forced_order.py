#!/usr/bin/env python3
"""Evaluate authentic submission directories at a verified actual play order."""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import random
import sys
import time
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
        raise RuntimeError("forced-order evaluation found an invalid IS_FIRST choice set")
    return sanitize_selection(select, choices, 1)


def _errors(agent: ExternalSubmissionAgent) -> int:
    result = int(getattr(agent, "errors", 0) or 0)
    inner = getattr(agent.module, "_AGENT", None)
    result += int(getattr(inner, "errors", 0) or 0)
    return result


def _route_telemetry(agent: ExternalSubmissionAgent) -> dict:
    """Read the packaged agent's flat numeric mechanism telemetry."""
    inner = getattr(agent.module, "_AGENT", None)
    candidate = getattr(inner, "route_telemetry", None)
    if candidate is None:
        candidate = getattr(inner, "telemetry", None)
    if candidate is None:
        return {}
    if hasattr(candidate, "flat"):
        candidate = candidate.flat()
    elif hasattr(candidate, "snapshot"):
        candidate = candidate.snapshot()
    result = {}
    for key, value in (candidate or {}).items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            result[str(key)] = float(value)
    return result


def run_game(task: tuple) -> dict:
    index, hero_path, opponent_path, order, seed, max_decisions, hero_env, opponent_env = task
    random.seed(seed + index)
    hero_path = Path(hero_path)
    opponent_path = Path(opponent_path)
    hero_deck = [int(value) for value in (hero_path / "deck.csv").read_text().splitlines() if value.strip()]
    opponent_deck = [int(value) for value in (opponent_path / "deck.csv").read_text().splitlines() if value.strip()]
    hero_seat = index % 2
    decks = [hero_deck, opponent_deck] if hero_seat == 0 else [opponent_deck, hero_deck]
    hero = ExternalSubmissionAgent(hero_path, hero_env)
    opponent = ExternalSubmissionAgent(opponent_path, opponent_env)
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
                elif observed != first_player:
                    raise RuntimeError("firstPlayer changed after latch")
            if obs.current is not None and int(obs.current.result) >= 0:
                if first_player is None:
                    raise RuntimeError("terminal state has no latched firstPlayer")
                observed_order = "first" if first_player == hero_seat else "second"
                if observed_order != order:
                    raise RuntimeError(f"requested {order}, observed {observed_order}")
                result = int(obs.current.result)
                return {
                    "win": int(result == hero_seat),
                    "draw": int(result == 2),
                    "physical_seat": hero_seat,
                    "actual_order": observed_order,
                    "hero_errors": _errors(hero),
                    "opponent_errors": _errors(opponent),
                    "decisions": decisions,
                    "hero_telemetry": _route_telemetry(hero),
                }
            if obs.select.context == SelectContext.IS_FIRST:
                action = _force(obs.select, hero_seat, order)
            else:
                action = agents[int(obs.current.yourIndex)](raw)
            raw = battle_select(action)
            decisions += 1
            if decisions >= max_decisions:
                raise RuntimeError("forced-order evaluation exceeded decision cap")
    finally:
        battle_finish(); hero.close(); opponent.close()


def wilson_lower(wins: int, games: int, z: float = 1.6448536269514722) -> float:
    if games <= 0:
        return 0.0
    p = wins / games
    denominator = 1 + z * z / games
    center = (p + z * z / (2 * games)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * games)) / games) / denominator
    return center - margin


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hero", type=Path, required=True)
    parser.add_argument("--opponent", type=Path, required=True)
    parser.add_argument("--actual-order", choices=("first", "second"), required=True)
    parser.add_argument("--games", type=int, required=True)
    parser.add_argument("--workers", type=int, default=max(1, (mp.cpu_count() or 2) - 1))
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--max-decisions", type=int, default=2_000)
    parser.add_argument("--hero-env", default="{}", help="JSON env overrides for the hero submission")
    parser.add_argument("--opponent-env", default="{}", help="JSON env overrides for the opponent submission")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    hero_env = json.loads(args.hero_env)
    opponent_env = json.loads(args.opponent_env)
    if not isinstance(hero_env, dict) or not isinstance(opponent_env, dict):
        parser.error("--hero-env and --opponent-env must be JSON objects")
    started = time.time()
    hero = args.hero.resolve(); opponent = args.opponent.resolve()
    tasks = [(index, str(hero), str(opponent), args.actual_order, args.seed, args.max_decisions, hero_env, opponent_env)
             for index in range(args.games)]
    totals = {"wins": 0, "draws": 0, "hero_policy_errors": 0, "opponent_policy_errors": 0, "decisions": 0}
    seats = {"0": {"games": 0, "wins": 0}, "1": {"games": 0, "wins": 0}}
    telemetry: dict[str, float] = {}
    context = mp.get_context("spawn")
    with context.Pool(args.workers) as pool:
        for completed, row in enumerate(pool.imap_unordered(run_game, tasks, chunksize=2), 1):
            totals["wins"] += row["win"]; totals["draws"] += row["draw"]
            totals["hero_policy_errors"] += row["hero_errors"]
            totals["opponent_policy_errors"] += row["opponent_errors"]
            totals["decisions"] += row["decisions"]
            for key, value in row.get("hero_telemetry", {}).items():
                telemetry[key] = telemetry.get(key, 0.0) + value
            seat = str(row["physical_seat"])
            seats[seat]["games"] += 1; seats[seat]["wins"] += row["win"]
            if completed % 100 == 0:
                print(json.dumps({"complete": completed, "win_rate": totals["wins"] / completed}), flush=True)
    result = {
        "games": args.games, "wins": totals["wins"], "draws": totals["draws"],
        "win_rate": totals["wins"] / args.games,
        "one_sided_95_lower": wilson_lower(totals["wins"], args.games),
        "actual_order": args.actual_order, "physical_seats": seats,
        "hero_policy_errors": totals["hero_policy_errors"],
        "opponent_policy_errors": totals["opponent_policy_errors"],
        "decisions": totals["decisions"], "seed": args.seed,
        "hero": str(hero), "opponent": str(opponent),
        "hero_sha256": sha256_path(hero), "opponent_sha256": sha256_path(opponent),
        "hero_telemetry": dict(sorted(telemetry.items())),
        "actual_order_accounting_complete": sum(value["games"] for value in seats.values()) == args.games,
        "elapsed_seconds": time.time() - started,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
