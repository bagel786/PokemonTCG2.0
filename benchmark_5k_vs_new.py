import subprocess
import json
from pathlib import Path

ROOT = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0")
PYTHON = str(ROOT / ".venv/bin/python")

HERO_DECK = str(ROOT / "freshstart/decklists/grimmsnarl_marnie.deck.csv")
MODEL_5K = str(ROOT / "artifacts/overnight_grim_20260730/grim_selected.npz")
MODEL_NEW = str(ROOT / "artifacts/coevo_run_02/round_001/grimmsnarl_marnie_challenger.npz")

ROUND2_DIR = ROOT / "artifacts/coevo_run_02/round_001"
OUTPUT_DIR = ROOT / "artifacts/comparative_benchmark"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

test_opponents = [
    {
        "name": "team_rockets_mewtwo_ex (Gen-2)",
        "deck": str(ROOT / "freshstart/decklists/team_rockets_mewtwo_ex.deck.csv"),
        "model": str(ROUND2_DIR / "team_rockets_mewtwo_ex_challenger.npz"),
        "submission": None,
        "games": 50,
    },
    {
        "name": "kangaskhan_crustle (Gen-2)",
        "deck": str(ROOT / "freshstart/decklists/kangaskhan_crustle.deck.csv"),
        "model": str(ROUND2_DIR / "kangaskhan_crustle_challenger.npz"),
        "submission": None,
        "games": 50,
    },
    {
        "name": "alakazam_dudunsparce (Gen-2)",
        "deck": str(ROOT / "freshstart/decklists/alakazam_dudunsparce.deck.csv"),
        "model": str(ROUND2_DIR / "alakazam_dudunsparce_challenger.npz"),
        "submission": None,
        "games": 50,
    },
    {
        "name": "cynthias_garchomp_ex (Gen-2)",
        "deck": str(ROOT / "freshstart/decklists/cynthias_garchomp_ex.deck.csv"),
        "model": str(ROUND2_DIR / "cynthias_garchomp_ex_challenger.npz"),
        "submission": None,
        "games": 50,
    },
    {
        "name": "dragapult_ex (Gen-2)",
        "deck": str(ROOT / "freshstart/decklists/dragapult_ex.deck.csv"),
        "model": str(ROUND2_DIR / "dragapult_ex_challenger.npz"),
        "submission": None,
        "games": 50,
    },
    {
        "name": "alakazam_2_4a (Authentic Search)",
        "deck": str(ROOT / "freshstart/elite_submissions/alakazam_2_4a/deck.csv"),
        "model": "heuristic",
        "submission": str(ROOT / "freshstart/elite_submissions/alakazam_2_4a"),
        "games": 50,
    },
]

def run_eval(hero_model, opp_entry, tag):
    out_file = OUTPUT_DIR / f"{tag}_{opp_entry['name'].replace(' ', '_').replace('(', '').replace(')', '')}.json"
    cmd = [
        PYTHON, "training/evaluate.py",
        "--deck-a", HERO_DECK,
        "--model-a", hero_model,
        "--deck-b", opp_entry["deck"],
        "--games", str(opp_entry["games"]),
        "--workers", "8",
        "--output", str(out_file),
    ]
    if opp_entry["submission"]:
        cmd.extend(["--submission-b", opp_entry["submission"]])
    else:
        cmd.extend(["--model-b", opp_entry["model"]])
    
    print(f"Running {tag} vs {opp_entry['name']} ({opp_entry['games']} games)...", flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)
    res = json.loads(out_file.read_text())
    return {
        "wins": res["wins_a"],
        "games": res["games"],
        "win_rate": res["win_rate_a"],
        "wilson_95": res["wilson_95"]
    }

results_5k = {}
results_new = {}

print("=== Starting 5k Incumbent vs Evolved Population Evaluations ===", flush=True)
for opp in test_opponents:
    results_5k[opp["name"]] = run_eval(MODEL_5K, opp, "5k_incumbent")

print("=== Starting New Challenger vs Evolved Population Evaluations ===", flush=True)
for opp in test_opponents:
    results_new[opp["name"]] = run_eval(MODEL_NEW, opp, "new_challenger")

print("=== Running Head-to-Head Mirror (200 games) ===", flush=True)
h2h_file = OUTPUT_DIR / "h2h_new_vs_5k.json"
cmd_h2h = [
    PYTHON, "training/evaluate.py",
    "--deck-a", HERO_DECK,
    "--model-a", MODEL_NEW,
    "--deck-b", HERO_DECK,
    "--model-b", MODEL_5K,
    "--games", "200",
    "--workers", "8",
    "--output", str(h2h_file),
]
subprocess.run(cmd_h2h, cwd=ROOT, check=True)
h2h_res = json.loads(h2h_file.read_text())

summary = {
    "head_to_head": {
        "games": h2h_res["games"],
        "new_challenger_wins": h2h_res["wins_a"],
        "new_challenger_win_rate": h2h_res["win_rate_a"],
        "5k_incumbent_wins": h2h_res["games"] - h2h_res["wins_a"],
        "5k_incumbent_win_rate": 1.0 - h2h_res["win_rate_a"],
        "seat_results": h2h_res["seat_results_a"],
    },
    "comparison": {
        opp["name"]: {
            "5k_incumbent": results_5k[opp["name"]],
            "new_challenger": results_new[opp["name"]],
            "delta_win_rate": results_new[opp["name"]]["win_rate"] - results_5k[opp["name"]]["win_rate"],
        }
        for opp in test_opponents
    }
}

summary_path = OUTPUT_DIR / "full_side_by_side_summary.json"
summary_path.write_text(json.dumps(summary, indent=2))
print("=== Side-by-Side Benchmark Finished! ===", flush=True)
print(json.dumps(summary, indent=2))
