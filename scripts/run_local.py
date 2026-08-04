#!/usr/bin/env python3
"""Run the clean-room agent against a random opponent using the official engine."""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

from cg.api import to_observation_class  # noqa: E402
from cg.game import battle_finish, battle_select, battle_start  # noqa: E402
from ptcg_ai.agent import CompetitionAgent  # noqa: E402


def random_action(obs):
    select = obs.select
    count = random.randint(select.minCount, select.maxCount)
    return random.sample(range(len(select.option)), count)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=20)
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument("--deck", choices=("grimmsnarl", "garchomp"), default="grimmsnarl")
    parser.add_argument("--model", help="optional .npz policy weights for the hero")
    parser.add_argument("--opponent", choices=("random", "heuristic"), default="random")
    args = parser.parse_args()
    random.seed(args.seed)

    deck_path = ROOT / "decks" / f"{args.deck}.csv"
    deck = [int(line) for line in deck_path.read_text().splitlines()]
    wins = losses = decisions = policy_errors = 0
    start_time = time.perf_counter()
    for game_index in range(args.games):
        hero_seat = game_index % 2
        agent = CompetitionAgent(deck_path, args.model)
        opponent_agent = CompetitionAgent(deck_path)
        raw, start = battle_start(deck, deck)
        if start.errorType != 0:
            raise RuntimeError(f"engine rejected deck: {start.errorType}")
        try:
            while True:
                obs = to_observation_class(raw)
                if obs.current is not None and obs.current.result != -1:
                    if obs.current.result == hero_seat:
                        wins += 1
                    else:
                        losses += 1
                    break
                if obs.current.yourIndex == hero_seat:
                    action = agent(raw)
                elif args.opponent == "heuristic":
                    action = opponent_agent(raw)
                else:
                    action = random_action(obs)
                raw = battle_select(action)
                decisions += 1
        finally:
            policy_errors += agent.errors
            policy_errors += opponent_agent.errors
            battle_finish()

    elapsed = time.perf_counter() - start_time
    print({
        "games": args.games,
        "wins": wins,
        "losses": losses,
        "win_rate": wins / max(1, wins + losses),
        "decisions": decisions,
        "policy_errors": policy_errors,
        "seconds": round(elapsed, 3),
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
