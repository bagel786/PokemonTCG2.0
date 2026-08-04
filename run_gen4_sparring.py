"""Spar Gen 4 Grimmsnarl against 5k baseline and Gen 2 champion."""

import json
import subprocess
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "artifacts/sparring_gen4"
OUT_DIR.mkdir(parents=True, exist_ok=True)

GEN4_MODEL = ROOT / "artifacts/coevo_run_03/round_002/grimmsnarl_marnie_challenger.npz"
GEN2_MODEL = ROOT / "artifacts/coevo_run_02/round_001/grimmsnarl_marnie_challenger.npz"
INCUMBENT_5K = ROOT / "artifacts/overnight_grim_20260730/grim_selected.npz"
GRIM_DECK = ROOT / "freshstart/decklists/grimmsnarl_marnie.deck.csv"

# 1. Write dual-mirror sparring league
spar_league = {
    "version": 1,
    "opponents": [
        {
            "name": "grimmsnarl_5k_frozen",
            "deck": str(GRIM_DECK),
            "model": str(INCUMBENT_5K),
            "meta_weight": 50,
            "train_weight": 50,
            "evaluate": True,
        },
        {
            "name": "grimmsnarl_gen2_champ",
            "deck": str(GRIM_DECK),
            "model": str(GEN2_MODEL),
            "meta_weight": 50,
            "train_weight": 50,
            "evaluate": True,
        }
    ]
}
with open(OUT_DIR / "spar_league.json", "w") as f:
    json.dump(spar_league, f, indent=2)

rollout_file = OUT_DIR / "rollouts.jsonl.gz"
if not rollout_file.exists():
    print("Step 1: Collecting 4,000 dual-mirror rollouts...")
    cmd_collect = [
        str(ROOT / ".venv/bin/python"),
        str(ROOT / "training/collect_selfplay.py"),
        "--model", str(GEN4_MODEL),
        "--hero-deck", str(GRIM_DECK),
        "--league", str(OUT_DIR / "spar_league.json"),
        "--games", "4000",
        "--workers", "8",
        "--temperature", "0.65",
        "--seed", "20260840",
        "--output", str(rollout_file)
    ]
    subprocess.run(cmd_collect, check=True, cwd=str(ROOT))
else:
    print("Step 1: Found existing 4,000 rollouts, skipping collection.")

print("Step 2: Training PPO with bc_weight=0.02...")
cmd_train = [
    str(ROOT / ".venv/bin/python"),
    str(ROOT / "training/train_ppo.py"),
    "--initial-model", str(GEN4_MODEL),
    "--rollouts", str(rollout_file),
    "--output", str(OUT_DIR / "grimmsnarl_gen4_sparred.npz"),
    "--epochs", "2",
    "--learning-rate", "1e-4",
    "--bc-weight", "0.02",
    "--require-card", "648",
    "--seed", "20260841",
]
subprocess.run(cmd_train, check=True, cwd=str(ROOT))

print("Step 3: Running comprehensive tournament on sparred model...")
SPARRED_MODEL = OUT_DIR / "grimmsnarl_gen4_sparred.npz"
OPPONENTS = [
    ("Mirror vs 5k Baseline", GRIM_DECK, INCUMBENT_5K),
    ("Mirror vs Gen 2 Champ", GRIM_DECK, GEN2_MODEL),
    ("vs Gen 4 Mewtwo ex", ROOT / "freshstart/decklists/team_rockets_mewtwo_ex.deck.csv", ROOT / "artifacts/coevo_run_03/round_002/team_rockets_mewtwo_ex_challenger.npz"),
    ("vs Gen 4 Alakazam", ROOT / "freshstart/decklists/alakazam_dudunsparce.deck.csv", ROOT / "artifacts/coevo_run_03/round_002/alakazam_dudunsparce_challenger.npz"),
    ("vs Gen 4 Crustle", ROOT / "freshstart/decklists/kangaskhan_crustle.deck.csv", ROOT / "artifacts/coevo_run_03/round_002/kangaskhan_crustle_challenger.npz"),
    ("vs Gen 4 Dragapult", ROOT / "freshstart/decklists/dragapult_ex.deck.csv", ROOT / "artifacts/coevo_run_03/round_002/dragapult_ex_challenger.npz"),
    ("vs Gen 4 Garchomp", ROOT / "freshstart/decklists/cynthias_garchomp_ex.deck.csv", ROOT / "artifacts/coevo_run_03/round_002/cynthias_garchomp_ex_challenger.npz"),
]

print("=" * 70)
print("BENCHMARKING DUAL-SPARRED GEN 4 GRIMMSNARL")
print("=" * 70)

results = []
for name, opp_deck, opp_model in OPPONENTS:
    cmd_eval = [
        str(ROOT / ".venv/bin/python"),
        str(ROOT / "training/evaluate.py"),
        "--deck-a", str(GRIM_DECK),
        "--model-a", str(SPARRED_MODEL),
        "--deck-b", str(opp_deck),
        "--model-b", str(opp_model),
        "--games", "100",
        "--workers", "8",
    ]
    res = subprocess.run(cmd_eval, capture_output=True, text=True, cwd=str(ROOT))
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
with open(OUT_DIR / "sparred_benchmark.json", "w") as f:
    json.dump(results, f, indent=2)
print("Saved to artifacts/sparring_gen4/sparred_benchmark.json")
