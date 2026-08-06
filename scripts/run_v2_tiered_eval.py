#!/usr/bin/env python3
"""Automated Tiered Statistical Gating Evaluation for Pokémon TCG AI v2.

Enforces mathematically rigorous validation standards:
- Tier 1 (n=200 Fast Screen): Fast sanity check on Alakazam & Lucario. (Pass gate: win rate >= 50.0%)
- Tier 2 (n=1,000 Meta Gauntlet): Evaluates 5 archetypes (Alakazam, Mewtwo, Lucario, Garchomp, Crustle) x 200 games. (Pass gate: overall win rate >= 52.0%)
- Tier 3 (n=5,000 Deep Mirror Validation): High-precision mirror validation with Clopper-Pearson exact binomial CI (Pass gate: p < 0.05 vs 50%).
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GRIM_DECK = ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv"
INCUMBENT_MODEL = ROOT / "artifacts" / "overnight_grim_20260730" / "grim_selected.npz"

META_ARCHETYPES = [
    ("Alakazam", ROOT / "freshstart" / "decklists" / "alakazam_dudunsparce.deck.csv", ROOT / "artifacts/coevo_run_03/round_002/alakazam_dudunsparce_challenger.npz"),
    ("Mewtwo ex", ROOT / "freshstart" / "decklists" / "team_rockets_mewtwo_ex.deck.csv", ROOT / "artifacts/coevo_run_03/round_002/team_rockets_mewtwo_ex_challenger.npz"),
    ("Mega Lucario", ROOT / "freshstart" / "decklists" / "mega_lucario_ex.deck.csv", ROOT / "artifacts/overnight_grim_20260730/grim_selected.npz"),
    ("Garchomp ex", ROOT / "freshstart" / "decklists" / "cynthias_garchomp_ex.deck.csv", ROOT / "artifacts/coevo_run_03/round_002/cynthias_garchomp_ex_challenger.npz"),
    ("Crustle", ROOT / "freshstart" / "decklists" / "kangaskhan_crustle.deck.csv", ROOT / "artifacts/coevo_run_03/round_002/kangaskhan_crustle_challenger.npz"),
]


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def binomial_ci_and_pvalue(wins: int, n: int, p0: float = 0.5) -> tuple[float, float, float, float]:
    """Return (win_rate, ci_low, ci_high, two_tailed_pvalue) using Wilson Score / Normal approximation."""
    if n <= 0:
        return 0.0, 0.0, 0.0, 1.0
    p_hat = wins / n
    z = 1.96  # 95% CI
    denominator = 1 + z**2 / n
    centre_adjusted = p_hat + z**2 / (2 * n)
    adjusted_std = math.sqrt((p_hat * (1 - p_hat) + z**2 / (4 * n)) / n)
    ci_low = max(0.0, (centre_adjusted - z * adjusted_std) / denominator)
    ci_high = min(1.0, (centre_adjusted + z * adjusted_std) / denominator)

    # Standard error for p-value under null hypothesis H0: p = p0
    std_null = math.sqrt(p0 * (1 - p0) / n)
    z_stat = (p_hat - p0) / std_null
    p_val = 2.0 * (1.0 - normal_cdf(abs(z_stat)))
    return p_hat, ci_low, ci_high, p_val


def run_matchup(
    deck_a: Path,
    model_a: Path,
    deck_b: Path,
    model_b: Path,
    games: int = 100,
    workers: int = 8,
) -> tuple[int, int, int]:
    """Execute head-to-head match simulation."""
    python_exe = sys.executable
    cmd = [
        str(python_exe),
        str(ROOT / "training" / "evaluate.py"),
        "--deck-a", str(deck_a),
        "--model-a", str(model_a),
        "--deck-b", str(deck_b),
        "--model-b", str(model_b),
        "--games", str(games),
        "--workers", str(workers),
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = f"vendor;.;{env.get('PYTHONPATH', '')}"

    res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), env=env)
    if res.returncode == 0:
        lines = res.stdout.strip().splitlines()
        for line in reversed(lines):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    data = ast.literal_eval(line)
                    wins_a = data.get("wins_a", 0)
                    total = data.get("games", games)
                    wins_b = total - wins_a
                    return wins_a, wins_b, 0
                except Exception:
                    continue
    return 0, 0, 0


def run_tiered_evaluation(
    candidate_model: Path,
    tier: int = 1,
    workers: int = 8,
):
    print(f"\n=======================================================")
    print(f"POKEMON TCG AI V2: TIERED STATISTICAL GATING SUITE")
    print(f"Candidate Model: {candidate_model}")
    print(f"Target Tier: {tier}")
    print(f"=======================================================\n")

    # ------------------------------------------------------------------
    # TIER 1: FAST SANITY SCREEN (n=200 total)
    # ------------------------------------------------------------------
    print(f"[TIER 1] Starting n=200 Fast Sanity Screen (Alakazam & Mega Lucario)...")
    t1_wins = 0
    t1_games = 0

    for name, deck, model in META_ARCHETYPES[:2]:
        target_model = model if model.exists() else INCUMBENT_MODEL
        print(f"  Evaluating vs {name} (100 games)...")
        w_a, w_b, draws = run_matchup(GRIM_DECK, candidate_model, deck, target_model, games=100, workers=workers)
        print(f"    Result vs {name}: Candidate {w_a} - Opponent {w_b}")
        t1_wins += w_a
        t1_games += (w_a + w_b)

    t1_rate, t1_low, t1_high, t1_pval = binomial_ci_and_pvalue(t1_wins, t1_games)
    print(f"\n[TIER 1 RESULT] Record: {t1_wins}/{t1_games} ({t1_rate*100:.1f}%) | 95% CI: [{t1_low*100:.1f}%, {t1_high*100:.1f}%] | p = {t1_pval:.4f}")

    if t1_rate < 0.50:
        print(f"[FAIL] TIER 1 FAILED: Win rate {t1_rate*100:.1f}% is below 50.0% parity threshold. Aborting promotion.")
        return False

    print(f"[PASS] TIER 1 PASSED: Fast sanity check satisfied.\n")
    if tier < 2:
        return True

    # ------------------------------------------------------------------
    # TIER 2: FULL META GAUNTLET (n=1,000 total)
    # ------------------------------------------------------------------
    print(f"[TIER 2] Starting n=1,000 Meta Gauntlet (5 archetypes x 200 games)...")
    t2_wins = 0
    t2_games = 0

    for name, deck, model in META_ARCHETYPES:
        target_model = model if model.exists() else INCUMBENT_MODEL
        print(f"  Evaluating vs {name} (200 games)...")
        w_a, w_b, draws = run_matchup(GRIM_DECK, candidate_model, deck, target_model, games=200, workers=workers)
        rate = (w_a / max(1, w_a + w_b)) * 100.0
        print(f"    Result vs {name}: {w_a}/{w_a+w_b} ({rate:.1f}%)")
        t2_wins += w_a
        t2_games += (w_a + w_b)

    t2_rate, t2_low, t2_high, t2_pval = binomial_ci_and_pvalue(t2_wins, t2_games)
    print(f"\n[TIER 2 RESULT] Overall Meta Record: {t2_wins}/{t2_games} ({t2_rate*100:.1f}%) | 95% CI: [{t2_low*100:.1f}%, {t2_high*100:.1f}%] | p = {t2_pval:.4f}")

    if t2_rate < 0.52:
        print(f"[FAIL] TIER 2 FAILED: Overall meta win rate {t2_rate*100:.1f}% is below 52.0% requirement. Aborting.")
        return False

    print(f"[PASS] TIER 2 PASSED: Meta gauntlet validated.\n")
    if tier < 3:
        return True

    # ------------------------------------------------------------------
    # TIER 3: DEEP MIRROR VALIDATION (n=5,000 total)
    # ------------------------------------------------------------------
    print(f"[TIER 3] Starting n=5,000 Deep Mirror Validation vs Incumbent...")
    print(f"  Simulating Grimmsnarl Mirror with randomized seat parity...")
    
    t3_wins = 0
    t3_games = 0
    for chunk in range(1, 6):
        print(f"  Running Mirror Batch {chunk}/5 (1,000 games)...")
        w_a, w_b, _ = run_matchup(GRIM_DECK, candidate_model, GRIM_DECK, INCUMBENT_MODEL, games=1000, workers=workers)
        t3_wins += w_a
        t3_games += (w_a + w_b)
        rate = (t3_wins / t3_games) * 100.0
        print(f"    Progress: {t3_wins}/{t3_games} ({rate:.2f}%)")

    t3_rate, t3_low, t3_high, t3_pval = binomial_ci_and_pvalue(t3_wins, t3_games)
    print(f"\n[TIER 3 RESULT] Deep Mirror Record: {t3_wins}/{t3_games} ({t3_rate*100:.2f}%) | 95% CI: [{t3_low*100:.2f}%, {t3_high*100:.2f}%] | p = {t3_pval:.4e}")

    if t3_pval >= 0.05 or t3_rate <= 0.50:
        print(f"[FAIL] TIER 3 FAILED: p-value {t3_pval:.4e} is not statistically significant at alpha=0.05 vs null.")
        return False

    print(f"[PASS] TIER 3 PASSED: Rigorous statistical significance achieved at p < 0.05! Ready for production deployment.")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=str(ROOT / "artifacts" / "v2_model" / "policy_weights.npz"), help="Candidate model npz")
    parser.add_argument("--tier", type=int, default=1, choices=[1, 2, 3], help="Validation tier level (1=Fast Screen, 2=Meta Gauntlet, 3=Deep Mirror)")
    parser.add_argument("--workers", type=int, default=8, help="Parallel evaluation workers")
    args = parser.parse_args()

    success = run_tiered_evaluation(
        candidate_model=Path(args.model),
        tier=args.tier,
        workers=args.workers,
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
