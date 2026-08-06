#!/usr/bin/env python3
"""Real-time streaming evaluation of Master Loss-Buckets model vs Alakazam (Search ON and Direct Policy)."""

import multiprocessing as mp
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

from training.evaluate import run_game_diagnostic, wilson

GRIM_DECK = ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv"
MASTER_MODEL = ROOT / "artifacts" / "loss_buckets_model" / "master_loss_buckets_policy.npz"
BASE_5K_MODEL = ROOT / "artifacts" / "overnight_grim_20260730" / "grim_selected.npz"

ALAKAZAM_2_4A = ROOT / "freshstart" / "elite_submissions" / "alakazam_2_4a"
ALAKAZAM_2_7 = ROOT / "freshstart" / "elite_submissions" / "alakazam_2_7"

LOG_FILE = ROOT / "artifacts" / "loss_buckets_model" / "alakazam_eval.log"

def log(msg: str):
    ts = time.strftime("[%Y-%m-%d %H:%M:%S]")
    line = f"{ts} {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def run_suite(label: str, model_path: Path, opp_dir: Path, num_games: int = 40, workers: int = 8):
    log(f"\n>>> Running: {label} ({num_games} Games)...")
    deck_b = opp_dir / "deck.csv"
    tasks = [
        (
            i,
            str(GRIM_DECK.resolve()),
            str(model_path.resolve()),
            str(deck_b.resolve()),
            "",
            str(opp_dir.resolve()),
            {},
            20260729,
        )
        for i in range(num_games)
    ]

    wins = 0
    s0_wins = 0
    s0_games = 0
    s1_wins = 0
    s1_games = 0

    start_t = time.time()
    context = mp.get_context("spawn")

    with context.Pool(workers) as pool:
        for done_idx, res in enumerate(pool.imap_unordered(run_game_diagnostic, tasks), 1):
            w = res["win"]
            s = res["seat_a"]
            wins += w
            if s == 0:
                s0_games += 1
                s0_wins += w
            else:
                s1_games += 1
                s1_wins += w

            if done_idx % 5 == 0 or done_idx == num_games:
                wr = (wins / done_idx) * 100
                s0_wr = (s0_wins / max(1, s0_games)) * 100
                s1_wr = (s1_wins / max(1, s1_games)) * 100
                elapsed = time.time() - start_t
                log(f"  [{done_idx:2d}/{num_games}] Win Rate: {wr:5.1f}% ({wins}/{done_idx}) | "
                    f"Seat 0 (1st): {s0_wr:4.1f}% ({s0_wins}/{s0_games}) | "
                    f"Seat 1 (2nd): {s1_wr:4.1f}% ({s1_wins}/{s1_games}) | {elapsed:.1f}s")

    final_wr = (wins / num_games) * 100
    low, high = wilson(wins, num_games)
    log(f"--- {label} Result: {wins}/{num_games} ({final_wr:.1f}%) [95% CI: {low*100:.1f}% - {high*100:.1f}%] ---")
    return {
        "games": num_games,
        "wins": wins,
        "win_rate": final_wr,
        "seat0_wr": (s0_wins / max(1, s0_games)) * 100,
        "seat1_wr": (s1_wins / max(1, s1_games)) * 100,
        "ci": [low * 100, high * 100],
    }

def main():
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text("")
    log("================================================================================")
    log("=== LIVE ALAKAZAM BENCHMARK: MASTER MODEL VS AUTHENTIC SEARCH OPPONENTS ===")
    log("================================================================================")

    # 1. Master Model vs Alakazam 2.4a (Authentic Search ON)
    res_m_24a = run_suite("Master Model vs Alakazam 2.4a (Search ON)", MASTER_MODEL, ALAKAZAM_2_4A, num_games=40, workers=8)

    # 2. Master Model vs Alakazam 2.7 (Learned Direct Policy)
    res_m_27 = run_suite("Master Model vs Alakazam 2.7 (Learned Policy)", MASTER_MODEL, ALAKAZAM_2_7, num_games=40, workers=8)

    # 3. 5k Baseline vs Alakazam 2.4a (Search ON)
    res_5k_24a = run_suite("5k Baseline vs Alakazam 2.4a (Search ON)", BASE_5K_MODEL, ALAKAZAM_2_4A, num_games=40, workers=8)

    log("\n================================================================================")
    log("=== FINAL BENCHMARK SUMMARY ===")
    log("================================================================================")
    log(f"1. Master Model vs Alakazam 2.4a (Search ON) : {res_m_24a['win_rate']:.1f}% ({res_m_24a['wins']}/{res_m_24a['games']}) | Seat 0: {res_m_24a['seat0_wr']:.1f}% | Seat 1: {res_m_24a['seat1_wr']:.1f}% | CI: {res_m_24a['ci'][0]:.1f}%-{res_m_24a['ci'][1]:.1f}%")
    log(f"2. Master Model vs Alakazam 2.7 (Learned)   : {res_m_27['win_rate']:.1f}% ({res_m_27['wins']}/{res_m_27['games']}) | Seat 0: {res_m_27['seat0_wr']:.1f}% | Seat 1: {res_m_27['seat1_wr']:.1f}% | CI: {res_m_27['ci'][0]:.1f}%-{res_m_27['ci'][1]:.1f}%")
    log(f"3. 5k Baseline vs Alakazam 2.4a (Search ON)  : {res_5k_24a['win_rate']:.1f}% ({res_5k_24a['wins']}/{res_5k_24a['games']}) | Seat 0: {res_5k_24a['seat0_wr']:.1f}% | Seat 1: {res_5k_24a['seat1_wr']:.1f}% | CI: {res_5k_24a['ci'][0]:.1f}%-{res_5k_24a['ci'][1]:.1f}%")
    log("================================================================================")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
