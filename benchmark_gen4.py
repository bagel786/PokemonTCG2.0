"""Benchmark Generation 4 Grimmsnarl vs Gen 2, 5k baseline, and Evolved Meta Archetypes."""

import subprocess
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

GEN4_GRIM = ROOT / "artifacts/coevo_run_03/round_002/grimmsnarl_marnie_challenger.npz"
GEN2_GRIM = ROOT / "artifacts/coevo_run_02/round_001/grimmsnarl_marnie_challenger.npz"
INCUMBENT_5K = ROOT / "artifacts/overnight_grim_20260730/grim_selected.npz"
GRIM_DECK = ROOT / "freshstart/decklists/grimmsnarl_marnie.deck.csv"

OPPONENTS = [
    ("Mirror vs Gen 2 Champ", GRIM_DECK, GEN2_GRIM),
    ("Mirror vs 5k Baseline", GRIM_DECK, INCUMBENT_5K),
    ("vs Gen 4 Mewtwo ex", ROOT / "freshstart/decklists/team_rockets_mewtwo_ex.deck.csv", ROOT / "artifacts/coevo_run_03/round_002/team_rockets_mewtwo_ex_challenger.npz"),
    ("vs Gen 4 Alakazam", ROOT / "freshstart/decklists/alakazam_dudunsparce.deck.csv", ROOT / "artifacts/coevo_run_03/round_002/alakazam_dudunsparce_challenger.npz"),
    ("vs Gen 4 Crustle", ROOT / "freshstart/decklists/kangaskhan_crustle.deck.csv", ROOT / "artifacts/coevo_run_03/round_002/kangaskhan_crustle_challenger.npz"),
    ("vs Gen 4 Dragapult", ROOT / "freshstart/decklists/dragapult_ex.deck.csv", ROOT / "artifacts/coevo_run_03/round_002/dragapult_ex_challenger.npz"),
    ("vs Gen 4 Garchomp", ROOT / "freshstart/decklists/cynthias_garchomp_ex.deck.csv", ROOT / "artifacts/coevo_run_03/round_002/cynthias_garchomp_ex_challenger.npz"),
]

print("=" * 70)
print("BENCHMARKING GEN 4 GRIMMSNARL AGAINST EVOLVED POPULATION")
print("=" * 70)

results = []
for name, opp_deck, opp_model in OPPONENTS:
    cmd = [
        str(ROOT / ".venv/bin/python"),
        str(ROOT / "training/evaluate.py"),
        "--deck-a", str(GRIM_DECK),
        "--model-a", str(GEN4_GRIM),
        "--deck-b", str(opp_deck),
        "--model-b", str(opp_model),
        "--games", "100",
        "--workers", "8",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    if res.returncode == 0:
        line = res.stdout.strip().splitlines()[-1]
        try:
            data = ast.literal_eval(line)
        except Exception:
            data = json.loads(line)
        wr = data.get("win_rate_a", 0.0)
        wins = data.get("wins_a", 0)
        total = data.get("games", 100)
        print(f"{name:<30} | {wins:>3}/{total} ({wr:.1%})")
        results.append({"matchup": name, "win_rate": wr, "wins": wins, "total": total})
    else:
        print(f"{name:<30} | ERROR: {res.stderr[:200]}")

print("=" * 70)
with open(ROOT / "artifacts/gen4_benchmark.json", "w") as f:
    json.dump(results, f, indent=2)
print("Saved to artifacts/gen4_benchmark.json")
