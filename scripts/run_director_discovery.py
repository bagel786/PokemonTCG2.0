#!/usr/bin/env python3
"""Successive-halving outcome tournament for twelve fixed Director policies."""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from training.evaluate import run_game_diagnostic
from training.evaluation_schema import sha256_path


@dataclass(frozen=True)
class Policy:
    fallback: str
    horizon: str
    trigger: str

    @property
    def name(self) -> str:
        return f"{self.fallback}__{self.horizon}__{self.trigger}"

    def env(self) -> dict[str, str]:
        return {
            "PTCG_DIRECTOR_ARM": "treatment",
            "PTCG_DIRECTOR_HORIZON": self.horizon,
            "PTCG_DIRECTOR_TRIGGER": self.trigger,
            "PTCG_DIRECTOR_SWAP_FALLBACK": "1" if self.fallback == "d842" else "0",
        }


POLICIES = [Policy(fallback, horizon, trigger) for fallback in ("a2", "d842") for horizon in ("turn", "turn_reply") for trigger in ("first_high_impact", "first_robust_disagreement", "third_turn")]


def _parse_opponent(value: str):
    name, path = value.split("=", 1)
    target = Path(path).resolve()
    if not target.is_dir():
        raise argparse.ArgumentTypeError(value)
    return name, target


def evaluate(candidate: Path, policies: list[Policy], opponents, games_per_policy: int, workers: int, seed: int) -> dict:
    tasks = []
    metadata = []
    index = 0
    for policy in policies:
        for game in range(games_per_policy):
            lineage, opponent = opponents[game % len(opponents)]
            task = (
                index, str(candidate / "deck.csv"), "", str(opponent / "deck.csv"), "",
                str(candidate), policy.env(), str(opponent), {}, seed, 2_000,
            )
            tasks.append(task); metadata.append((policy.name, lineage)); index += 1
    results = {policy.name: {"games": 0, "wins": 0, "first_games": 0, "first_wins": 0, "second_games": 0, "second_wins": 0, "errors": 0, "lineages": {}} for policy in policies}
    context = mp.get_context("spawn")
    with context.Pool(workers) as pool:
        for position, result in enumerate(pool.imap(run_game_diagnostic, tasks, chunksize=1)):
            name, lineage = metadata[position]
            row = results[name]; win = int(result["win"]); order = "first" if result["hero_went_first"] else "second"
            row["games"] += 1; row["wins"] += win; row[f"{order}_games"] += 1; row[f"{order}_wins"] += win; row["errors"] += int(result["hero_errors"])
            cell = row["lineages"].setdefault(lineage, {"games": 0, "wins": 0})
            cell["games"] += 1; cell["wins"] += win
    for row in results.values():
        row["win_rate"] = row["wins"] / row["games"]
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--opponent", action="append", type=_parse_opponent, required=True)
    parser.add_argument("--workers", type=int, default=max(1, (mp.cpu_count() or 2) - 1))
    parser.add_argument("--seed", type=int, default=2026080801)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    active = list(POLICIES); stages = []
    for stage, (games, keep) in enumerate(((500, 4), (2_000, 2), (5_000, 1)), 1):
        result = evaluate(args.candidate.resolve(), active, args.opponent, games, args.workers, args.seed + stage * 100_000)
        ranked = sorted(active, key=lambda policy: (result[policy.name]["errors"] == 0, result[policy.name]["win_rate"]), reverse=True)
        stages.append({"stage": stage, "games_per_policy": games, "results": result, "ranking": [policy.name for policy in ranked]})
        active = ranked[:keep]
    winner = active[0]
    payload = {
        "status": "frozen",
        "candidate_sha256": sha256_path(args.candidate),
        "winner": winner.name,
        "winner_config": winner.env(),
        "stages": stages,
        "behavior_clones_used": False,
        "engine_randomness": "independent_unpaired",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"winner": winner.name}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
