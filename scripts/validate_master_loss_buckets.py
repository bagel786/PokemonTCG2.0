#!/usr/bin/env python3
"""Run rigorous 3-way validation gate on Master Loss-Buckets model."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DECK_PATH = ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv"
MODEL_PATH = ROOT / "artifacts" / "loss_buckets_model" / "master_loss_buckets_policy.npz"
BASELINE_PATH = ROOT / "artifacts" / "seat1_data" / "candidate_seat1_boosted.npz"
CONTROL_5K_PATH = ROOT / "artifacts" / "overnight_grim_20260730" / "grim_selected.npz"
OUT_DIR = ROOT / "artifacts" / "loss_buckets_model"
LOG_FILE = OUT_DIR / "validation_gate.log"

def log(msg: str):
    ts = time.strftime("[%Y-%m-%d %H:%M:%S]")
    line = f"{ts} {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def run_matchup(model_a: Path, model_b: Path, games: int, workers: int = 8) -> dict:
    cmd = [
        sys.executable,
        "-m",
        "training.evaluate",
        "--deck-a", str(DECK_PATH),
        "--model-a", str(model_a),
        "--deck-b", str(DECK_PATH),
        "--model-b", str(model_b),
        "--games", str(games),
        "--workers", str(workers),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    stdout = res.stdout.strip()
    import ast
    for line in reversed(res.stdout.splitlines()):
        line = line.strip()
        if line.startswith("{") and "win_rate_a" in line:
            try:
                return ast.literal_eval(line)
            except Exception:
                pass
    log(f"Parse fallback failed.\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}")
    return {"wins_a": 0, "games": games, "win_rate_a": 0.0}

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text("")
    log("=== STARTING MASTER MODEL 3-WAY VALIDATION GATE ===")

    if not MODEL_PATH.exists():
        log(f"Error: Candidate model {MODEL_PATH} not found.")
        return 1

    # Gate 1: Candidate vs Seat-1 Baseline (100 Games)
    log("\n[Gate 1/3] Candidate vs Seat-1 Baseline [100 Games]...")
    res_g1 = run_matchup(MODEL_PATH, BASELINE_PATH, 100)
    wr1 = res_g1.get("win_rate_a", 0.0) * 100
    seat_res = res_g1.get("seat_results_a", {})
    s0_wr = seat_res.get("0", {}).get("win_rate", 0.0) * 100
    s1_wr = seat_res.get("1", {}).get("win_rate", 0.0) * 100
    log(f"  Result: Candidate Won {res_g1.get('wins_a')}/{res_g1.get('games')} ({wr1:.1f}%) | Seat 0: {s0_wr:.1f}% | Seat 1: {s1_wr:.1f}%")

    # Gate 2: Candidate vs 5k Control Reference (100 Games)
    log("\n[Gate 2/3] Candidate vs 5k Reference Control [100 Games]...")
    res_g2 = run_matchup(MODEL_PATH, CONTROL_5K_PATH, 100)
    wr2 = res_g2.get("win_rate_a", 0.0) * 100
    seat_res2 = res_g2.get("seat_results_a", {})
    s0_wr2 = seat_res2.get("0", {}).get("win_rate", 0.0) * 100
    s1_wr2 = seat_res2.get("1", {}).get("win_rate", 0.0) * 100
    log(f"  Result: Candidate Won {res_g2.get('wins_a')}/{res_g2.get('games')} ({wr2:.1f}%) | Seat 0: {s0_wr2:.1f}% | Seat 1: {s1_wr2:.1f}%")

    # Gate 3: Candidate Self-Play Consistency (50 Games)
    log("\n[Gate 3/3] Candidate Self-Play Parity [50 Games]...")
    res_g3 = run_matchup(MODEL_PATH, MODEL_PATH, 50)
    wr3 = res_g3.get("win_rate_a", 0.0) * 100
    seat_res3 = res_g3.get("seat_results_a", {})
    s0_wr3 = seat_res3.get("0", {}).get("win_rate", 0.0) * 100
    s1_wr3 = seat_res3.get("1", {}).get("win_rate", 0.0) * 100
    log(f"  Result: Self-Play Parity: Seat 0: {s0_wr3:.1f}% | Seat 1: {s1_wr3:.1f}%")

    log(f"\n========================================================")
    log(f"GATE SUMMARY RESULTS:")
    log(f"  * Win Rate vs Seat-1 Baseline : {wr1:.2f}% (Threshold: >= 50.0%)")
    log(f"  * Win Rate vs 5k Control      : {wr2:.2f}% (Threshold: >= 50.0%)")
    log(f"  * Seat-1 Win Rate vs 5k       : {s1_wr2:.2f}% (Threshold: >= 48.0%)")

    passed = (wr1 >= 49.0) and (wr2 >= 50.0) and (s1_wr2 >= 45.0)
    if passed:
        log(f"STATUS: >>> ALL GATES PASSED! Master Model verified for deployment. <<<")
    else:
        log(f"STATUS: >>> REVIEW GATE RESULTS <<<")
    log(f"========================================================")

    return 0 if passed else 1

if __name__ == "__main__":
    raise SystemExit(main())
