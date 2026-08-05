#!/usr/bin/env python3
"""Run diagnostic meta gauntlet across multiple archetypes to compare candidate_2 vs d842."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECK_DIR = ROOT / "freshstart" / "decklists"
OUT_DIR = ROOT / "artifacts" / "meta_diagnostics"
OUT_DIR.mkdir(parents=True, exist_ok=True)

MODEL_NEW = ROOT / "artifacts" / "overnight_pipeline_output" / "candidate_checkpoints" / "candidate_2_heads_1e4.npz"
MODEL_5K = ROOT / "artifacts" / "overnight_grim_20260730" / "grim_selected.npz"
HERO_DECK = DECK_DIR / "grimmsnarl_marnie.deck.csv"

OPPONENTS = [
    ("Alakazam / Dudunsparce", DECK_DIR / "alakazam_dudunsparce.deck.csv"),
    ("Mega Lucario ex", DECK_DIR / "mega_lucario_ex.deck.csv"),
    ("Kangaskhan / Crustle", DECK_DIR / "kangaskhan_crustle.deck.csv"),
    ("Iono / Bellibolt ex", DECK_DIR / "iono_bellibolt_ex.deck.csv"),
    ("Dragapult ex", DECK_DIR / "dragapult_ex.deck.csv"),
]

def run_matchup(name: str, opp_deck: Path, model: Path, model_tag: str, games: int = 200) -> dict:
    out_file = OUT_DIR / f"{model_tag}_{name.replace(' ', '_').replace('/', '_')}.json"
    cmd = [
        sys.executable,
        str(ROOT / "training" / "evaluate.py"),
        "--deck-a", str(HERO_DECK),
        "--model-a", str(model),
        "--deck-b", str(opp_deck),
        "--model-b", str(model),
        "--games", str(games),
        "--workers", "8",
        "--output", str(out_file),
        "--seed", "20260805",
    ]
    subprocess.run(cmd, check=True)
    data = json.loads(out_file.read_text())
    return {
        "matchup": name,
        "model": model_tag,
        "win_rate": data.get("win_rate_a", 0.0),
        "seat_0": data.get("seat_0_win_rate_a", 0.0),
        "seat_1": data.get("seat_1_win_rate_a", 0.0),
        "errors": data.get("hero_policy_errors", 0),
    }

def main():
    print(f"{'Matchup':<30} | {'5k Control (d842)':<18} | {'New Distilled (C2)':<18} | {'Delta':<10}")
    print("-" * 85)
    results = []
    for name, opp_deck in OPPONENTS:
        if not opp_deck.exists():
            continue
        res_5k = run_matchup(name, opp_deck, MODEL_5K, "d842", games=200)
        res_new = run_matchup(name, opp_deck, MODEL_NEW, "candidate_2", games=200)
        delta = res_new["win_rate"] - res_5k["win_rate"]
        print(f"{name:<30} | {res_5k['win_rate']*100:>6.2f}% (s0:{res_5k['seat_0']*100:.0f}/s1:{res_5k['seat_1']*100:.0f}) | {res_new['win_rate']*100:>6.2f}% (s0:{res_new['seat_0']*100:.0f}/s1:{res_new['seat_1']*100:.0f}) | {delta*100:>+6.2f}%")
        results.append({"matchup": name, "d842": res_5k, "new": res_new, "delta": delta})

    (OUT_DIR / "summary.json").write_text(json.dumps(results, indent=2))

if __name__ == "__main__":
    main()
