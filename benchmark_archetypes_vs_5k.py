"""Benchmark Generation 2 vs Generation 4 meta decks against the 5k Grimmsnarl agent."""

import subprocess
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INCUMBENT_5K = ROOT / "artifacts/overnight_grim_20260730/grim_selected.npz"
GRIM_DECK = ROOT / "freshstart/decklists/grimmsnarl_marnie.deck.csv"

ARCHETYPES = [
    (
        "Mewtwo ex",
        ROOT / "freshstart/decklists/team_rockets_mewtwo_ex.deck.csv",
        ROOT / "artifacts/coevo_run_02/round_001/team_rockets_mewtwo_ex_challenger.npz",
        ROOT / "artifacts/coevo_run_03/round_002/team_rockets_mewtwo_ex_challenger.npz"
    ),
    (
        "Alakazam Dudunsparce",
        ROOT / "freshstart/decklists/alakazam_dudunsparce.deck.csv",
        ROOT / "artifacts/coevo_run_02/round_001/alakazam_dudunsparce_challenger.npz",
        ROOT / "artifacts/coevo_run_03/round_002/alakazam_dudunsparce_challenger.npz"
    ),
    (
        "Kangaskhan Crustle",
        ROOT / "freshstart/decklists/kangaskhan_crustle.deck.csv",
        ROOT / "artifacts/coevo_run_02/round_001/kangaskhan_crustle_challenger.npz",
        ROOT / "artifacts/coevo_run_03/round_002/kangaskhan_crustle_challenger.npz"
    ),
    (
        "Dragapult ex",
        ROOT / "freshstart/decklists/dragapult_ex.deck.csv",
        ROOT / "artifacts/coevo_run_02/round_001/dragapult_ex_challenger.npz",
        ROOT / "artifacts/coevo_run_03/round_002/dragapult_ex_challenger.npz"
    ),
    (
        "Garchomp ex",
        ROOT / "freshstart/decklists/cynthias_garchomp_ex.deck.csv",
        ROOT / "artifacts/coevo_run_02/round_001/cynthias_garchomp_ex_challenger.npz",
        ROOT / "artifacts/coevo_run_03/round_002/cynthias_garchomp_ex_challenger.npz"
    ),
]

def eval_matchup(deck, model, games=100):
    cmd = [
        str(ROOT / ".venv/bin/python"),
        str(ROOT / "training/evaluate.py"),
        "--deck-a", str(deck),
        "--model-a", str(model),
        "--deck-b", str(GRIM_DECK),
        "--model-b", str(INCUMBENT_5K),
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

print("=" * 75)
print(f"{'Archetype':<25} | {'Gen 2 vs 5k Grim':<18} | {'Gen 4 vs 5k Grim':<18} | {'Delta':<8}")
print("=" * 75)

comparison = []
for name, deck, gen2_model, gen4_model in ARCHETYPES:
    wr_gen2, wins_gen2 = eval_matchup(deck, gen2_model, games=100)
    wr_gen4, wins_gen4 = eval_matchup(deck, gen4_model, games=100)
    delta = wr_gen4 - wr_gen2
    print(f"{name:<25} | {wins_gen2:>3}/100 ({wr_gen2:.1%})     | {wins_gen4:>3}/100 ({wr_gen4:.1%})     | {delta:+.1%}")
    comparison.append({
        "archetype": name,
        "gen2_win_rate": wr_gen2,
        "gen4_win_rate": wr_gen4,
        "delta": delta
    })

print("=" * 75)
with open(ROOT / "artifacts/coevo_archetypes_progression.json", "w") as f:
    json.dump(comparison, f, indent=2)
print("Saved to artifacts/coevo_archetypes_progression.json")
