#!/usr/bin/env python3
"""Run seat-balanced evaluation of Master Loss-Buckets Model and 5k Baseline against Authentic Alakazam Search agents."""

import ast
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GRIM_DECK = ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv"
MASTER_MODEL = ROOT / "artifacts" / "loss_buckets_model" / "master_loss_buckets_policy.npz"
BASE_5K_MODEL = ROOT / "artifacts" / "overnight_grim_20260730" / "grim_selected.npz"

ALAKAZAM_2_4A_SUB = ROOT / "freshstart" / "elite_submissions" / "alakazam_2_4a"
ALAKAZAM_2_4A_DECK = ALAKAZAM_2_4A_SUB / "deck.csv"

ALAKAZAM_2_7_SUB = ROOT / "freshstart" / "elite_submissions" / "alakazam_2_7"
ALAKAZAM_2_7_DECK = ALAKAZAM_2_7_SUB / "deck.csv"

def run_eval(model_path: Path, sub_b_path: Path, deck_b_path: Path, games: int = 60, workers: int = 6) -> dict:
    cmd = [
        sys.executable,
        "-m",
        "training.evaluate",
        "--deck-a", str(GRIM_DECK),
        "--model-a", str(model_path),
        "--deck-b", str(deck_b_path),
        "--submission-b", str(sub_b_path),
        "--games", str(games),
        "--workers", str(workers),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    for line in reversed(res.stdout.splitlines()):
        line = line.strip()
        if line.startswith("{") and "win_rate_a" in line:
            try:
                return ast.literal_eval(line)
            except Exception:
                pass
    print("Eval stdout:", res.stdout[:500])
    print("Eval stderr:", res.stderr[:500])
    return {"wins_a": 0, "games": games, "win_rate_a": 0.0}

def print_result(label: str, res: dict):
    games = res.get("games", 0)
    wins = res.get("wins_a", 0)
    wr = res.get("win_rate_a", 0.0) * 100
    w95 = [x * 100 for x in res.get("wilson_95", [0, 0])]
    s_res = res.get("seat_results_a", {})
    s0 = s_res.get("0", {})
    s1 = s_res.get("1", {})
    s0_wr = s0.get("win_rate", 0.0) * 100
    s1_wr = s1.get("win_rate", 0.0) * 100
    
    print(f"\n{label}:")
    print(f"  * Overall Win Rate : {wins}/{games} ({wr:.1f}%) [95% CI: {w95[0]:.1f}% - {w95[1]:.1f}%]")
    print(f"  * Going First  (Seat 0) : {s0.get('wins', 0)}/{s0.get('games', 0)} ({s0_wr:.1f}%)")
    print(f"  * Going Second (Seat 1) : {s1.get('wins', 0)}/{s1.get('games', 0)} ({s1_wr:.1f}%)")
    search_stats = res.get("opponent_search_stats", {})
    if search_stats:
        print(f"  * Opponent Search Telemetry: {search_stats}")

def main():
    print("=" * 80)
    print("=== BENCHMARKING MASTER LOSS-BUCKETS MODEL VS AUTHENTIC ALAKAZAM SEARCH ===")
    print("=" * 80)

    # 1. Master Model vs Alakazam 2.4a (Search ON)
    print("\n[Test 1/4] Master Loss-Buckets Model vs Alakazam 2.4a (Authentic Search ON)...")
    res_m_24a = run_eval(MASTER_MODEL, ALAKAZAM_2_4A_SUB, ALAKAZAM_2_4A_DECK, games=60, workers=6)
    print_result("Master Model vs Alakazam 2.4a (Search ON)", res_m_24a)

    # 2. 5k Baseline vs Alakazam 2.4a (Search ON)
    print("\n[Test 2/4] 5k Control Baseline vs Alakazam 2.4a (Authentic Search ON)...")
    res_5k_24a = run_eval(BASE_5K_MODEL, ALAKAZAM_2_4A_SUB, ALAKAZAM_2_4A_DECK, games=60, workers=6)
    print_result("5k Baseline vs Alakazam 2.4a (Search ON)", res_5k_24a)

    # 3. Master Model vs Alakazam 2.7 (Learned Direct Policy)
    print("\n[Test 3/4] Master Loss-Buckets Model vs Alakazam 2.7...")
    res_m_27 = run_eval(MASTER_MODEL, ALAKAZAM_2_7_SUB, ALAKAZAM_2_7_DECK, games=60, workers=6)
    print_result("Master Model vs Alakazam 2.7", res_m_27)

    # 4. 5k Baseline vs Alakazam 2.7
    print("\n[Test 4/4] 5k Control Baseline vs Alakazam 2.7...")
    res_5k_27 = run_eval(BASE_5K_MODEL, ALAKAZAM_2_7_SUB, ALAKAZAM_2_7_DECK, games=60, workers=6)
    print_result("5k Baseline vs Alakazam 2.7", res_5k_27)

    print("\n" + "=" * 80)
    print("=== SUMMARY COMPARISON TABLE ===")
    print("=" * 80)
    print(f"{'MATCHUP':<42} | {'MASTER LOSS-BUCKETS':<18} | {'5k BASELINE':<18}")
    print("-" * 80)
    print(f"{'vs Alakazam 2.4a (Search ON)':<42} | {res_m_24a.get('win_rate_a', 0)*100:5.1f}% ({res_m_24a.get('wins_a', 0)}/{res_m_24a.get('games', 0)}){'':<4} | {res_5k_24a.get('win_rate_a', 0)*100:5.1f}% ({res_5k_24a.get('wins_a', 0)}/{res_5k_24a.get('games', 0)})")
    print(f"{'vs Alakazam 2.7 (Learned Policy)':<42} | {res_m_27.get('win_rate_a', 0)*100:5.1f}% ({res_m_27.get('wins_a', 0)}/{res_m_27.get('games', 0)}){'':<4} | {res_5k_27.get('win_rate_a', 0)*100:5.1f}% ({res_5k_27.get('wins_a', 0)}/{res_5k_27.get('games', 0)})")
    print("=" * 80)

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
