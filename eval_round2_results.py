import subprocess
import json
from pathlib import Path

ROOT = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0")
PYTHON = str(ROOT / ".venv/bin/python")
ROUND2 = ROOT / "artifacts/coevo_run_02/round_001"
HERO_MODEL = str(ROUND2 / "grimmsnarl_marnie_challenger.npz")
HERO_DECK = str(ROOT / "freshstart/decklists/grimmsnarl_marnie.deck.csv")
INCUMBENT_5K = str(ROOT / "artifacts/overnight_grim_20260730/grim_selected.npz")
SPARRED_MODEL = str(ROOT / "artifacts/sparring_01/grimmsnarl_sparred.npz")

OUTPUT_DIR = ROOT / "artifacts/eval_coevo_02"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

print("=== 1. Mirror Match vs 5k Incumbent (200 games) ===", flush=True)
cmd_5k = [
    PYTHON, "training/evaluate.py",
    "--deck-a", HERO_DECK,
    "--model-a", HERO_MODEL,
    "--deck-b", HERO_DECK,
    "--model-b", INCUMBENT_5K,
    "--games", "200",
    "--workers", "8",
    "--output", str(OUTPUT_DIR / "vs_5k_incumbent_200.json"),
]
subprocess.run(cmd_5k, cwd=ROOT, check=True)

print("=== 2. Matchup vs Evolved Gen-2 Challengers (50 games each) ===", flush=True)
opponents = [
    ("kangaskhan_crustle", "freshstart/decklists/kangaskhan_crustle.deck.csv", str(ROUND2 / "kangaskhan_crustle_challenger.npz")),
    ("alakazam_dudunsparce", "freshstart/decklists/alakazam_dudunsparce.deck.csv", str(ROUND2 / "alakazam_dudunsparce_challenger.npz")),
    ("team_rockets_mewtwo_ex", "freshstart/decklists/team_rockets_mewtwo_ex.deck.csv", str(ROUND2 / "team_rockets_mewtwo_ex_challenger.npz")),
    ("dragapult_ex", "freshstart/decklists/dragapult_ex.deck.csv", str(ROUND2 / "dragapult_ex_challenger.npz")),
    ("cynthias_garchomp_ex", "freshstart/decklists/cynthias_garchomp_ex.deck.csv", str(ROUND2 / "cynthias_garchomp_ex_challenger.npz")),
]

challenger_results = {}
for name, deck, model in opponents:
    out_file = OUTPUT_DIR / f"vs_{name}_50.json"
    cmd = [
        PYTHON, "training/evaluate.py",
        "--deck-a", HERO_DECK,
        "--model-a", HERO_MODEL,
        "--deck-b", str(ROOT / deck),
        "--model-b", model,
        "--games", "50",
        "--workers", "8",
        "--output", str(out_file),
    ]
    subprocess.run(cmd, cwd=ROOT, check=True)
    res = json.loads(out_file.read_text())
    challenger_results[name] = {
        "wins": res["wins_a"],
        "games": res["games"],
        "win_rate": res["win_rate_a"],
        "wilson_95": res["wilson_95"]
    }

(OUTPUT_DIR / "vs_gen2_challengers_summary.json").write_text(json.dumps(challenger_results, indent=2))

print("=== 3. 50-Game Gauntlet vs Alakazam (Search Enabled) ===", flush=True)
cmd_alakazam = [
    PYTHON, "training/evaluate.py",
    "--deck-a", HERO_DECK,
    "--model-a", HERO_MODEL,
    "--deck-b", str(ROOT / "freshstart/elite_submissions/alakazam_2_4a/deck.csv"),
    "--submission-b", str(ROOT / "freshstart/elite_submissions/alakazam_2_4a"),
    "--games", "50",
    "--workers", "8",
    "--output", str(OUTPUT_DIR / "vs_alakazam_search_50.json"),
]
subprocess.run(cmd_alakazam, cwd=ROOT, check=True)

print("=== All Round 2 Evaluations Completed Successfully! ===", flush=True)
