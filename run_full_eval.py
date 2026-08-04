import subprocess
import json
from pathlib import Path

ROOT = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0")
PYTHON = str(ROOT / ".venv/bin/python")
CHALLENGER = str(ROOT / "artifacts/coevo_run_01/round_001/grimmsnarl_marnie_challenger.npz")
INCUMBENT = str(ROOT / "artifacts/overnight_grim_20260730/grim_selected.npz")
HERO_DECK = str(ROOT / "freshstart/decklists/grimmsnarl_marnie.deck.csv")
OUTPUT_DIR = ROOT / "artifacts/eval_coevo_01"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

print("=== 1. Running Head-to-Head vs 5k Incumbent (200 games) ===", flush=True)
cmd_h2h = [
    PYTHON, "training/evaluate.py",
    "--deck-a", HERO_DECK,
    "--model-a", CHALLENGER,
    "--deck-b", HERO_DECK,
    "--model-b", INCUMBENT,
    "--games", "200",
    "--workers", "8",
    "--output", str(OUTPUT_DIR / "vs_incumbent_200.json"),
]
subprocess.run(cmd_h2h, cwd=ROOT, check=True)

print("=== 2. Running Meta League Evaluation (50 games per opponent) ===", flush=True)
cmd_league = [
    PYTHON, "training/evaluate_league.py",
    "--hero-deck", HERO_DECK,
    "--hero-model", CHALLENGER,
    "--league", "training/meta_league.json",
    "--games-per-opponent", "50",
    "--workers", "8",
    "--output", str(OUTPUT_DIR / "meta_league_eval_50.json"),
]
subprocess.run(cmd_league, cwd=ROOT, check=True)

print("=== 3. Running 50-Game Gauntlet vs Alakazam (Search Enabled) ===", flush=True)
cmd_alakazam = [
    PYTHON, "training/evaluate.py",
    "--deck-a", HERO_DECK,
    "--model-a", CHALLENGER,
    "--deck-b", str(ROOT / "freshstart/elite_submissions/alakazam_2_4a/deck.csv"),
    "--submission-b", str(ROOT / "freshstart/elite_submissions/alakazam_2_4a"),
    "--games", "50",
    "--workers", "8",
    "--output", str(OUTPUT_DIR / "vs_alakazam_search_50.json"),
]
subprocess.run(cmd_alakazam, cwd=ROOT, check=True)

print("=== All Evaluations Completed Successfully! ===", flush=True)
