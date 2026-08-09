#!/usr/bin/env python3
"""Execute strict 3-way validation gate on the fine-tuned Seat-1 candidate model."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EVAL_SCRIPT = ROOT / "training" / "evaluate.py"

from training.evaluation_schema import load_evaluation

CANDIDATE_MODEL = ROOT / "artifacts" / "seat1_data" / "candidate_seat1_boosted.npz"
CONTROL_MODEL = ROOT / "artifacts" / "overnight_grim_20260730" / "grim_selected.npz"
HERO_DECK = ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv"

META_DECKS = {
    "Alakazam / Dudunsparce": ROOT / "freshstart" / "decklists" / "alakazam_dudunsparce.deck.csv",
    "Mega Lucario ex": ROOT / "freshstart" / "decklists" / "mega_lucario_ex.deck.csv",
    "Kangaskhan / Crustle": ROOT / "freshstart" / "decklists" / "kangaskhan_crustle.deck.csv",
    "Iono / Bellibolt ex": ROOT / "freshstart" / "decklists" / "iono_bellibolt_ex.deck.csv",
    "Dragapult ex": ROOT / "freshstart" / "decklists" / "dragapult_ex.deck.csv",
}

OUT_DIR = ROOT / "artifacts" / "seat1_data"
OUT_REPORT = OUT_DIR / "validation_3way_gate.json"

def log(msg: str):
    ts = time.strftime("[%Y-%m-%d %H:%M:%S]")
    print(f"{ts} {msg}", flush=True)

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log("=== RUNNING STRICT 3-WAY VALIDATION GATE ===")
    if not CANDIDATE_MODEL.exists():
        log(f"Error: {CANDIDATE_MODEL} not found.")
        return 1

    report = {
        "candidate": str(CANDIDATE_MODEL),
        "control": str(CONTROL_MODEL),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "gates": {},
    }

    # -------------------------------------------------------------
    # GATE 1 & 2: Seat-Balanced & Seat-1 Mirror Gauntlet (5,000 games)
    # -------------------------------------------------------------
    log("Running 5,000-game Seat-Balanced Mirror Gate vs d842...")
    mirror_out = OUT_DIR / "mirror_gate_5k.json"
    cmd_mirror = [
        sys.executable,
        str(EVAL_SCRIPT),
        "--deck-a", str(HERO_DECK),
        "--model-a", str(CANDIDATE_MODEL),
        "--deck-b", str(HERO_DECK),
        "--model-b", str(CONTROL_MODEL),
        "--games", "5000",
        "--workers", "8",
        "--output", str(mirror_out),
        "--seed", "20260805",
    ]
    subprocess.run(cmd_mirror, check=True)
    mirror_data = load_evaluation(mirror_out)

    overall_mirror_wr = mirror_data["win_rate_a"] * 100
    seat_0_wr = mirror_data["seat_results_a"]["0"]["win_rate"] * 100
    seat_1_wr = mirror_data["seat_results_a"]["1"]["win_rate"] * 100

    log(f"Mirror Overall Win Rate: {overall_mirror_wr:.2f}% (Target: >= 52.0%)")
    log(f"  - Going First  (Seat 0): {seat_0_wr:.2f}%")
    log(f"  - Going Second (Seat 1): {seat_1_wr:.2f}% (Target: >= 50.0%)")

    gate_1_pass = seat_1_wr >= 50.0
    gate_2_pass = overall_mirror_wr >= 52.0

    report["gates"]["gate_1_seat1_mirror"] = {
        "passed": gate_1_pass,
        "seat_1_win_rate": seat_1_wr,
        "target": ">= 50.0%",
    }
    report["gates"]["gate_2_overall_mirror"] = {
        "passed": gate_2_pass,
        "overall_win_rate": overall_mirror_wr,
        "target": ">= 52.0%",
    }

    # -------------------------------------------------------------
    # GATE 3: 5-Archetype Cross-Meta Gauntlet (200 games each)
    # -------------------------------------------------------------
    log("\nRunning Cross-Meta Gauntlet across 5 Archetypes...")
    meta_results = {}
    all_meta_pass = True

    for name, deck_path in META_DECKS.items():
        slug = name.split()[0].lower()
        meta_out = OUT_DIR / f"meta_{slug}_200.json"
        cmd_meta = [
            sys.executable,
            str(EVAL_SCRIPT),
            "--deck-a", str(HERO_DECK),
            "--model-a", str(CANDIDATE_MODEL),
            "--deck-b", str(deck_path),
            "--model-b", str(CONTROL_MODEL),
            "--games", "200",
            "--workers", "8",
            "--output", str(meta_out),
            "--seed", "20260805",
        ]
        subprocess.run(cmd_meta, check=True)
        meta_data = load_evaluation(meta_out)
        wr = meta_data["win_rate_a"] * 100
        errors = meta_data["hero_policy_errors"] + meta_data["opponent_policy_errors"]
        passed = wr >= 98.0 and errors == 0
        if not passed:
            all_meta_pass = False
        log(f"  {name:25s}: {wr:6.2f}% Win Rate | Errors: {errors} | Passed: {passed}")
        meta_results[name] = {"win_rate": wr, "errors": errors, "passed": passed}

    report["gates"]["gate_3_cross_meta"] = {
        "passed": all_meta_pass,
        "archetypes": meta_results,
        "target": ">= 98.0% across all 5 archetypes with 0 errors",
    }

    overall_passed = gate_1_pass and gate_2_pass and all_meta_pass
    report["overall_passed"] = overall_passed

    OUT_REPORT.write_text(json.dumps(report, indent=2))
    log(f"\nReport written to {OUT_REPORT}")
    log(f"=== OVERALL 3-WAY GATE RESULT: {'PASSED [READY TO SHIP]' if overall_passed else 'FAILED [RETRAIN NEEDED]'} ===")
    return 0 if overall_passed else 1

if __name__ == "__main__":
    raise SystemExit(main())
