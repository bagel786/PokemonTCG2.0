#!/usr/bin/env python3
"""Run side-by-side Alakazam 2.7 and 5k mirror evaluations for 5k, Gen4, and Gen5."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ptcg_ai.eval.evaluator import evaluate_matchup

PPO_5K = ROOT / "artifacts" / "overnight_grim_20260730" / "grim_selected.npz"
GEN4_SPARRED = ROOT / "artifacts" / "coevo_p1" / "round_004" / "grimmsnarl_marnie_challenger.npz"
if not GEN4_SPARRED.exists():
    GEN4_SPARRED = ROOT / "artifacts" / "sparring_gen4" / "grimmsnarl_sparred.npz"
if not GEN4_SPARRED.exists():
    # extract from tar
    pass

GEN5_CHALLENGER = ROOT / "artifacts" / "coevo_run_04" / "round_001" / "grimmsnarl_marnie_challenger.npz"


def main():
    print(f"5k Path: {PPO_5K.exists()}")
    print(f"Gen4 Path: {GEN4_SPARRED.exists()}")
    print(f"Gen5 Path: {GEN5_CHALLENGER.exists()}")

    # Check against Alakazam 2.7
    results = {}
    models = [("5k Baseline", PPO_5K), ("Gen-5 Challenger", GEN5_CHALLENGER)]
    if GEN4_SPARRED.exists():
        models.insert(1, ("Gen-4 Sparred", GEN4_SPARRED))

    for name, model_path in models:
        print(f"\nEvaluating {name} vs Alakazam 2.7 (40 games)...")
        res = evaluate_matchup(
            deck_a="grimmsnarl_marnie",
            model_a=model_path,
            deck_b="alakazam_dudunsparce",
            bot_b="alakazam_2_7",
            games=40,
            seed=42,
        )
        print(f"-> {name} vs Alakazam 2.7: {res['wins']}/{res['games']} ({res['win_rate']*100:.1f}%)")
        results[f"{name}_vs_alakazam27"] = res

    print("\n" + "="*60)
    print("SUMMARY")
    for k, v in results.items():
        print(f"{k}: {v['wins']}/{v['games']} ({v['win_rate']*100:.1f}%)")


if __name__ == "__main__":
    main()
