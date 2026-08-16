#!/usr/bin/env python3
"""Run unpaired native B1/B2/B3 gameplay screens against frozen B0.

The script uses the repository's forced-order runner and external submission
adapter.  Candidate trees must already be materialized by
``build_grim_variance_candidates.py``.  It reports raw W/L, Wilson intervals,
actual-order splits, policy errors, and floor mechanisms.  It does not create
archives or upload anything.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import random
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]

from scripts.build_grim_variance_candidates import build_candidates
from scripts.evaluate_grim_variance_floor import burn_in
from training.evaluate import summarize_game_metrics
from training.evaluate_forced_order import run_game


DEFAULT_CANDIDATES = ROOT / "artifacts" / "grim_variance_floor" / "candidates"
DEFAULT_OUTPUT = ROOT / "artifacts" / "grim_variance_floor" / "native_results.json"


def wilson_interval(wins: int, games: int, z: float = 1.96) -> list[float]:
    if games <= 0:
        return [0.0, 1.0]
    p = wins / games
    denominator = 1 + z * z / games
    center = (p + z * z / (2 * games)) / denominator
    margin = z * ((p * (1 - p) + z * z / (4 * games)) / games) ** 0.5 / denominator
    return [center - margin, center + margin]


def _run_cell(hero: Path, opponent: Path, order: str, games: int, workers: int, seed: int) -> list[dict]:
    tasks = [
        (index, str(hero), str(opponent), order, seed + index, 2000)
        for index in range(games)
    ]
    if workers == 1:
        return [run_game(task) for task in tasks]
    context = mp.get_context("spawn")
    with context.Pool(workers) as pool:
        return list(pool.imap_unordered(run_game, tasks, chunksize=1))


def _summarize(rows: list[dict]) -> dict[str, Any]:
    wins = sum(int(row["win"]) for row in rows)
    games = len(rows)
    return {
        "games": games,
        "wins": wins,
        "losses": games - wins,
        "win_rate": wins / games if games else None,
        "wilson_95": wilson_interval(wins, games),
        "hero_policy_errors": sum(int(row.get("hero_errors", 0)) for row in rows),
        "opponent_policy_errors": sum(int(row.get("opponent_errors", 0)) for row in rows),
        "decisions": sum(int(row.get("decisions", 0)) for row in rows),
        "actual_order": rows[0].get("actual_order") if rows else None,
        "physical_seats": {
            str(seat): {
                "games": sum(int(row["physical_seat"]) == seat for row in rows),
                "wins": sum(int(row["physical_seat"]) == seat and row["win"] for row in rows),
            }
            for seat in (0, 1)
        },
        "floor_metrics": summarize_game_metrics([row["game_metrics"] for row in rows]),
        "games_detail": [row["game_metrics"] for row in rows],
    }


def _balanced_burn_in(rows: list[dict], block: int, samples: int = 20_000, seed: int = 842) -> dict:
    first = [row for row in rows if row.get("actual_order") == "first"]
    second = [row for row in rows if row.get("actual_order") == "second"]
    if not first or not second:
        return {"games": 0, "samples": 0, "label": "LOCAL BURN-IN RISK PROXY"}
    rng = random.Random(seed)
    sequences = []
    for _ in range(samples):
        sequence = []
        for index in range(block):
            pool = first if index % 2 == 0 else second
            sequence.append(pool[rng.randrange(len(pool))])
        sequences.append(sequence)
    wins_low = {
        "wins_le_1" if block == 5 else "wins_le_3": sum(
            sum(row["win"] for row in sequence) <= (1 if block == 5 else 3)
            for sequence in sequences
        )
        / samples,
        "wins_le_2" if block == 5 else "wins_le_4": sum(
            sum(row["win"] for row in sequence) <= (2 if block == 5 else 4)
            for sequence in sequences
        )
        / samples,
    }
    zero = sum(any(row["zero_attack_game"] for row in sequence) for sequence in sequences) / samples
    catastrophic = sum(
        any(row["catastrophic_floor_game"] for row in sequence) for sequence in sequences
    ) / samples
    return {
        "label": "LOCAL BURN-IN RISK PROXY - NOT A KAGGLE SCORE FORECAST",
        "block_games": block,
        "samples": samples,
        "forced_alternating_order": True,
        "p_wins_low": wins_low,
        "p_at_least_one_zero_attack": zero,
        "p_at_least_one_catastrophic_floor": catastrophic,
    }


def evaluate(
    *,
    candidates: Path,
    games_per_order: int,
    workers: int,
    seed: int,
    opponent_name: str = "B0_exact_d842",
    opponent_path: Path | None = None,
) -> dict:
    b0 = opponent_path or candidates / "B0"
    result = {
        "label": "LOCAL NATIVE GAMEPLAY EVALUATION - UNPAIRED ENGINE DEALS",
        "configuration": {
            "games_per_candidate_per_order": games_per_order,
            "workers": workers,
            "seed_schedule": seed,
            "engine_deals_paired": False,
            "opponent": opponent_name,
        },
        "candidates": {},
    }
    for variant in ("B1", "B2", "B3"):
        rows = []
        cells = {}
        for order in ("first", "second"):
            cell_rows = _run_cell(candidates / variant, b0, order, games_per_order, workers, seed)
            cells[order] = _summarize(cell_rows)
            rows.extend(cell_rows)
        overall = _summarize(rows)
        overall["by_actual_order"] = cells
        overall["intervention_counts"] = {}
        for row in rows:
            telemetry = row.get("hero_telemetry", {})
            runtime = telemetry.get("runtime_policy", {}) if isinstance(telemetry, dict) else {}
            guardrail = runtime.get("guardrail", {}) if isinstance(runtime, dict) else {}
            for field in ("interventions", "variance_interventions"):
                for reason, count in (guardrail.get(field, {}) or {}).items():
                    overall["intervention_counts"][reason] = (
                        overall["intervention_counts"].get(reason, 0) + int(count)
                    )
        overall["burn_in_5_mixed"] = burn_in([row["game_metrics"] for row in rows], block=5)
        overall["burn_in_10_mixed"] = burn_in([row["game_metrics"] for row in rows], block=10)
        overall["burn_in_5_balanced"] = _balanced_burn_in(
            [row["game_metrics"] for row in rows], 5
        )
        overall["burn_in_10_balanced"] = _balanced_burn_in(
            [row["game_metrics"] for row in rows], 10
        )
        result["candidates"][variant] = overall
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--games-per-order", type=int, default=100)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260812)
    parser.add_argument("--opponent-name", default="B0_exact_d842")
    parser.add_argument("--opponent", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if not args.candidates.exists():
        build_candidates(output=args.candidates)
    result = evaluate(
        candidates=args.candidates,
        games_per_order=args.games_per_order,
        workers=args.workers,
        seed=args.seed,
        opponent_name=args.opponent_name,
        opponent_path=args.opponent,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
