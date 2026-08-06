#!/usr/bin/env python3
"""Airtight End-to-End Packaging & Live Benchmark for submission_v2_2.tar.gz."""

import ast
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

from scripts.package_v2_agent import package_v2

GRIM_DECK = ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv"
MODEL_V2 = ROOT / "artifacts" / "v2_model" / "policy_weights.npz"
BASE_5K_MODEL = ROOT / "artifacts" / "overnight_grim_20260730" / "grim_selected.npz"
OUT_TAR = ROOT / "artifacts" / "submission_v2_2.tar.gz"

ALAKAZAM_2_4A_SUB = ROOT / "freshstart" / "elite_submissions" / "alakazam_2_4a"
ALAKAZAM_2_4A_DECK = ALAKAZAM_2_4A_SUB / "deck.csv"

ALAKAZAM_2_7_SUB = ROOT / "freshstart" / "elite_submissions" / "alakazam_2_7"
ALAKAZAM_2_7_DECK = ALAKAZAM_2_7_SUB / "deck.csv"


def run_benchmark_eval(model_path: Path, sub_b_path: Path, deck_b_path: Path, games: int = 40, workers: int = 6) -> dict:
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
    res = subprocess.run(cmd, capture_output=True, text=True, env=dict(os.environ, PYTHONPATH=f"{ROOT}/vendor;{ROOT}"))
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


def run_mirror_eval(model_a: Path, model_b: Path, games: int = 40, workers: int = 6) -> dict:
    cmd = [
        sys.executable,
        "-m",
        "training.evaluate",
        "--deck-a", str(GRIM_DECK),
        "--model-a", str(model_a),
        "--deck-b", str(GRIM_DECK),
        "--model-b", str(model_b),
        "--games", str(games),
        "--workers", str(workers),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, env=dict(os.environ, PYTHONPATH=f"{ROOT}/vendor;{ROOT}"))
    for line in reversed(res.stdout.splitlines()):
        line = line.strip()
        if line.startswith("{") and "win_rate_a" in line:
            try:
                return ast.literal_eval(line)
            except Exception:
                pass
    return {"wins_a": 0, "games": games, "win_rate_a": 0.0}


def print_stat(label: str, res: dict):
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
    print(f"  * Win Rate        : {wins}/{games} ({wr:.1f}%) [95% CI: {w95[0]:.1f}% - {w95[1]:.1f}%]")
    print(f"  * Seat 0 (Go 1st) : {s0.get('wins', 0)}/{s0.get('games', 0)} ({s0_wr:.1f}%)")
    print(f"  * Seat 1 (Go 2nd) : {s1.get('wins', 0)}/{s1.get('games', 0)} ({s1_wr:.1f}%)")


def main():
    print("=" * 80)
    print("=== PACKAGING & VALIDATING SUBMISSION V2.2 ===")
    print("=" * 80)
    
    # 1. Package tarball
    package_v2(model_path=MODEL_V2, deck_path=GRIM_DECK, output_tar=OUT_TAR)
    print(f"\n[Step 1] Packaged {OUT_TAR} ({OUT_TAR.stat().st_size / 1024 / 1024:.2f} MB)")
    
    # 2. Extract into sterile temporary directory to test pure standalone execution
    with tempfile.TemporaryDirectory(prefix="v2_2_sterile_") as tmp_dir:
        sterile_stage = Path(tmp_dir)
        with tarfile.open(OUT_TAR, "r:gz") as tar:
            tar.extractall(sterile_stage)
        
        extracted_model = sterile_stage / "policy_weights.npz"
        print(f"[Step 2] Extracted to sterile sandbox: {extracted_model.exists()}")
        
        # 3. Benchmark vs Alakazam 2.4a (Search ON)
        print("\n[Step 3] Running 40 Games vs Authentic Alakazam 2.4a (Search ON)...")
        t0 = time.time()
        res_24a = run_benchmark_eval(extracted_model, ALAKAZAM_2_4A_SUB, ALAKAZAM_2_4A_DECK, games=40, workers=6)
        print_stat("v2.2 vs Alakazam 2.4a (Search ON)", res_24a)
        print(f"  * Time: {time.time() - t0:.1f}s")
        
        # 4. Benchmark vs Alakazam 2.7 (Learned Policy)
        print("\n[Step 4] Running 40 Games vs Authentic Alakazam 2.7 (Learned Policy)...")
        t0 = time.time()
        res_27 = run_benchmark_eval(extracted_model, ALAKAZAM_2_7_SUB, ALAKAZAM_2_7_DECK, games=40, workers=6)
        print_stat("v2.2 vs Alakazam 2.7 (Learned Policy)", res_27)
        print(f"  * Time: {time.time() - t0:.1f}s")
        
        # 5. Benchmark vs 5k Control Baseline (Mirror Match)
        print("\n[Step 5] Running 40 Games vs 5k Control Baseline (Mirror Match)...")
        t0 = time.time()
        res_mirror = run_mirror_eval(extracted_model, BASE_5K_MODEL, games=40, workers=6)
        print_stat("v2.2 vs 5k Baseline (Mirror Match)", res_mirror)
        print(f"  * Time: {time.time() - t0:.1f}s")
        
        print("\n" + "=" * 80)
        print("=== FINAL BENCHMARK SUMMARY ===")
        print("=" * 80)
        print(f"  * vs Alakazam 2.4a (Search ON)   : {res_24a.get('win_rate_a', 0)*100:5.1f}% ({res_24a.get('wins_a', 0)}/{res_24a.get('games', 0)})")
        print(f"  * vs Alakazam 2.7 (Learned)      : {res_27.get('win_rate_a', 0)*100:5.1f}% ({res_27.get('wins_a', 0)}/{res_27.get('games', 0)})")
        print(f"  * vs 5k Baseline (Mirror Match)  : {res_mirror.get('win_rate_a', 0)*100:5.1f}% ({res_mirror.get('wins_a', 0)}/{res_mirror.get('games', 0)})")
        print("=" * 80)

if __name__ == "__main__":
    main()
