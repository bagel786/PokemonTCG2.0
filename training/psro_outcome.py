"""PSRO population manifests, maximin mixture solving, and admission gates."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from training.promotion import ONE_SIDED_Z_95


def lower_bound(wins: int, games: int, baseline_wins: int, baseline_games: int) -> float:
    if min(games, baseline_games) <= 0:
        raise ValueError("PSRO admission cell is empty")
    p, b = wins / games, baseline_wins / baseline_games
    variance = p * (1 - p) / games + b * (1 - b) / baseline_games
    return p - b - ONE_SIDED_Z_95 * math.sqrt(variance)


def solve_maximin(payoff: np.ndarray, iterations: int = 20_000) -> list[float]:
    """Deterministic multiplicative-weights approximation of row maximin mix."""
    matrix = np.asarray(payoff, dtype=np.float64)
    if matrix.ndim != 2 or not matrix.size or not np.all(np.isfinite(matrix)):
        raise ValueError("invalid PSRO payoff matrix")
    weights = np.ones(matrix.shape[0], dtype=np.float64)
    average = np.zeros_like(weights)
    eta = math.sqrt(2 * math.log(max(2, matrix.shape[0])) / max(1, iterations))
    for _ in range(iterations):
        mixture = weights / weights.sum()
        adversary = int(np.argmin(mixture @ matrix))
        rewards = matrix[:, adversary]
        weights *= np.exp(eta * (rewards - rewards.max()))
        average += mixture
    result = average / average.sum()
    return result.tolist()


def admission(cells: list[dict[str, Any]], minimum_games: int = 20_000) -> dict[str, Any]:
    if not cells:
        raise ValueError("PSRO admission has no evaluation cells")
    total_games = sum(int(cell["candidate_games"]) for cell in cells)
    required_orders = {"first", "second"}
    if {str(cell["actual_order"]) for cell in cells} != required_orders:
        raise ValueError("PSRO admission requires both actual orders")
    lineages = sorted({str(cell["lineage"]) for cell in cells})
    bounds = {}
    for lineage in lineages:
        selected = [cell for cell in cells if str(cell["lineage"]) == lineage]
        cw = sum(int(cell["candidate_wins"]) for cell in selected)
        cg = sum(int(cell["candidate_games"]) for cell in selected)
        bw = sum(int(cell["baseline_wins"]) for cell in selected)
        bg = sum(int(cell["baseline_games"]) for cell in selected)
        bounds[f"lineage:{lineage}"] = lower_bound(cw, cg, bw, bg)
    for order in required_orders:
        selected = [cell for cell in cells if str(cell["actual_order"]) == order]
        cw = sum(int(cell["candidate_wins"]) for cell in selected)
        cg = sum(int(cell["candidate_games"]) for cell in selected)
        bw = sum(int(cell["baseline_wins"]) for cell in selected)
        bg = sum(int(cell["baseline_games"]) for cell in selected)
        bounds[f"order:{order}"] = lower_bound(cw, cg, bw, bg)
    checks = {
        "minimum_20k_balanced_games": total_games >= minimum_games,
        "positive_worst_lineage_lower_bound": min(value for key, value in bounds.items() if key.startswith("lineage:")) > 0,
        "positive_both_order_lower_bounds": all(bounds[f"order:{order}"] > 0 for order in required_orders),
        "zero_errors": all(int(cell.get("policy_errors", -1)) == 0 for cell in cells),
        "complete_hashes": all(cell.get("candidate_sha256") and cell.get("opponent_sha256") for cell in cells),
    }
    return {"passed": all(checks.values()), "checks": checks, "lower_bounds": bounds, "candidate_games": total_games, "lineages": lineages}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payoff", type=Path, required=True, help="JSON matrix with policies/opponents/payoff")
    parser.add_argument("--cells", type=Path, required=True)
    parser.add_argument("--iteration", type=int, choices=(1, 2, 3), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payoff = json.loads(args.payoff.read_text(encoding="utf-8"))
    cells = json.loads(args.cells.read_text(encoding="utf-8"))
    decision = admission(cells["cells"])
    mixture = solve_maximin(np.asarray(payoff["payoff"], np.float64)) if decision["passed"] else None
    result = {
        "status": "admitted" if decision["passed"] else "rejected",
        "iteration": args.iteration,
        "decision": decision,
        "policies": payoff["policies"],
        "opponents": payoff["opponents"],
        "maximin_mixture": mixture,
        "next_iteration_population": payoff["policies"] if mixture is not None else None,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if decision["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
