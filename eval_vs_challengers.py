import subprocess
import json
from pathlib import Path

ROOT = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0")
PYTHON = str(ROOT / ".venv/bin/python")
ROUND1 = ROOT / "artifacts/coevo_run_01/round_001"
HERO_MODEL = str(ROUND1 / "grimmsnarl_marnie_challenger.npz")
HERO_DECK = str(ROOT / "freshstart/decklists/grimmsnarl_marnie.deck.csv")

opponents = [
    ("kangaskhan_crustle", "freshstart/decklists/kangaskhan_crustle.deck.csv", str(ROUND1 / "kangaskhan_crustle_challenger.npz")),
    ("alakazam_dudunsparce", "freshstart/decklists/alakazam_dudunsparce.deck.csv", str(ROUND1 / "alakazam_dudunsparce_challenger.npz")),
    ("team_rockets_mewtwo_ex", "freshstart/decklists/team_rockets_mewtwo_ex.deck.csv", str(ROUND1 / "team_rockets_mewtwo_ex_challenger.npz")),
    ("dragapult_ex", "freshstart/decklists/dragapult_ex.deck.csv", str(ROUND1 / "dragapult_ex_challenger.npz")),
    ("cynthias_garchomp_ex", "freshstart/decklists/cynthias_garchomp_ex.deck.csv", str(ROUND1 / "cynthias_garchomp_ex_challenger.npz")),
]

results = {}
for name, deck, model in opponents:
    cmd = [
        PYTHON, "training/evaluate.py",
        "--deck-a", HERO_DECK,
        "--model-a", HERO_MODEL,
        "--deck-b", str(ROOT / deck),
        "--model-b", model,
        "--games", "50",
        "--workers", "8",
    ]
    res = subprocess.run(cmd, cwd=ROOT, check=True, capture_output=True, text=True)
    for line in res.stdout.strip().splitlines():
        if line.startswith("{") and "win_rate_a" in line:
            import ast
            data = ast.literal_eval(line)
            results[name] = {
                "wins": data["wins_a"],
                "games": data["games"],
                "win_rate": data["win_rate_a"],
                "wilson_95": data["wilson_95"]
            }

print(json.dumps(results, indent=2))
