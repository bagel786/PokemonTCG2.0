import subprocess
import json
from pathlib import Path

ROOT = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0")
PYTHON = str(ROOT / ".venv/bin/python")
OUT_DIR = ROOT / "artifacts/sparring_01"
OUT_DIR.mkdir(parents=True, exist_ok=True)

HERO_START = str(ROOT / "artifacts/coevo_run_01/round_001/grimmsnarl_marnie_challenger.npz")
HERO_DECK = str(ROOT / "freshstart/decklists/grimmsnarl_marnie.deck.csv")
INCUMBENT_5K = str(ROOT / "artifacts/overnight_grim_20260730/grim_selected.npz")
SPARRING_LEAGUE = str(ROOT / "training/sparring_grim_league.json")
ROLLOUTS = str(OUT_DIR / "grimmsnarl_sparring_rollouts.jsonl.gz")
SPARRED_MODEL = str(OUT_DIR / "grimmsnarl_sparred.npz")
EVAL_OUT = str(OUT_DIR / "vs_5k_incumbent_200.json")

print("=== STEP 1: Collecting 5,000 1-on-1 Sparring Rollouts vs 5k Incumbent ===", flush=True)
cmd_collect = [
    PYTHON, "training/collect_selfplay.py",
    "--model", HERO_START,
    "--hero-deck", HERO_DECK,
    "--league", SPARRING_LEAGUE,
    "--games", "5000",
    "--workers", "8",
    "--temperature", "0.65",
    "--seed", "20260801",
    "--output", ROLLOUTS,
]
subprocess.run(cmd_collect, cwd=ROOT, check=True)

print("=== STEP 2: Running PPO Training with low BC weight (0.02) ===", flush=True)
cmd_train = [
    PYTHON, "training/train_ppo.py",
    "--initial-model", HERO_START,
    "--rollouts", ROLLOUTS,
    "--output", SPARRED_MODEL,
    "--epochs", "2",
    "--learning-rate", "0.0001",
    "--bc-weight", "0.02",
    "--require-card", "648",
    "--seed", "20260851",
]
subprocess.run(cmd_train, cwd=ROOT, check=True)

print("=== STEP 3: Evaluating 200 Games vs 5k Incumbent ===", flush=True)
cmd_eval = [
    PYTHON, "training/evaluate.py",
    "--deck-a", HERO_DECK,
    "--model-a", SPARRED_MODEL,
    "--deck-b", HERO_DECK,
    "--model-b", INCUMBENT_5K,
    "--games", "200",
    "--workers", "8",
    "--output", EVAL_OUT,
]
subprocess.run(cmd_eval, cwd=ROOT, check=True)

print("=== Phase 1 Sparring & Verification Completed! ===", flush=True)
result = json.loads(Path(EVAL_OUT).read_text())
print(f"Final Mirror Win Rate vs 5k Incumbent: {result['win_rate_a'] * 100:.2f}% ({result['wins_a']}/{result['games']} wins)")
