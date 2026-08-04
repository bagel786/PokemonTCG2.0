"""Run a grand head-to-head gauntlet comparing the 3 primary Grimmsnarl champion models."""

import subprocess
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

GRIM_DECK = ROOT / "freshstart/decklists/grimmsnarl_marnie.deck.csv"

CANDIDATES = [
    ("Grimmsnarl 5k (975 Elo)", ROOT / "artifacts/overnight_grim_20260730/grim_selected.npz"),
    ("Grimmsnarl Coevo R2 (928 Elo)", ROOT / "artifacts/coevo_run_02/round_001/grimmsnarl_marnie_challenger.npz"),
    ("Grimmsnarl Gen4 Sparred", ROOT / "artifacts/sparring_gen4/grimmsnarl_gen4_sparred.npz"),
]

OPPONENTS = [
    ("Mirror: 5k Incumbent", GRIM_DECK, ROOT / "artifacts/overnight_grim_20260730/grim_selected.npz"),
    ("Mirror: Coevo R2", GRIM_DECK, ROOT / "artifacts/coevo_run_02/round_001/grimmsnarl_marnie_challenger.npz"),
    ("vs Gen 4 Mewtwo ex", ROOT / "freshstart/decklists/team_rockets_mewtwo_ex.deck.csv", ROOT / "artifacts/coevo_run_03/round_002/team_rockets_mewtwo_ex_challenger.npz"),
    ("vs Gen 4 Alakazam", ROOT / "freshstart/decklists/alakazam_dudunsparce.deck.csv", ROOT / "artifacts/coevo_run_03/round_002/alakazam_dudunsparce_challenger.npz"),
    ("vs Gen 4 Crustle", ROOT / "freshstart/decklists/kangaskhan_crustle.deck.csv", ROOT / "artifacts/coevo_run_03/round_002/kangaskhan_crustle_challenger.npz"),
    ("vs Gen 4 Dragapult", ROOT / "freshstart/decklists/dragapult_ex.deck.csv", ROOT / "artifacts/coevo_run_03/round_002/dragapult_ex_challenger.npz"),
    ("vs Gen 4 Garchomp", ROOT / "freshstart/decklists/cynthias_garchomp_ex.deck.csv", ROOT / "artifacts/coevo_run_03/round_002/cynthias_garchomp_ex_challenger.npz"),
]

def eval_match(model_a, deck_b, model_b, games=100):
    cmd = [
        str(ROOT / ".venv/bin/python"),
        str(ROOT / "training/evaluate.py"),
        "--deck-a", str(GRIM_DECK),
        "--model-a", str(model_a),
        "--deck-b", str(deck_b),
        "--model-b", str(model_b),
        "--games", str(games),
        "--workers", "8",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    if res.returncode == 0:
        line = res.stdout.strip().splitlines()[-1]
        try:
            data = ast.literal_eval(line)
        except Exception:
            data = json.loads(line)
        return data.get("win_rate_a", 0.0), data.get("wins_a", 0)
    return 0.0, 0

print("=" * 85)
print("GRAND GAUNTLET: 3-WAY GRIMMSNARL CHAMPION BENCHMARK")
print("=" * 85)

matrix = {}
header = f"{'Opponent / Matchup':<26} | {'5k Incumbent':<16} | {'Coevo R2':<16} | {'Gen4 Sparred':<16}"
print(header)
print("-" * 85)

for opp_name, opp_deck, opp_model in OPPONENTS:
    row = []
    matrix[opp_name] = {}
    for cand_name, cand_model in CANDIDATES:
        # Avoid self vs self exact 50% dummy runs if identical
        if str(cand_model) == str(opp_model):
            wr, wins = 0.50, 50
        else:
            wr, wins = eval_match(cand_model, opp_deck, opp_model, games=100)
        row.append(f"{wins:>3}/100 ({wr:.1%})")
        matrix[opp_name][cand_name] = wr
    print(f"{opp_name:<26} | {row[0]:<16} | {row[1]:<16} | {row[2]:<16}")

print("=" * 85)
with open(ROOT / "artifacts/grand_gauntlet_results.json", "w") as f:
    json.dump(matrix, f, indent=2)
print("Saved to artifacts/grand_gauntlet_results.json")
