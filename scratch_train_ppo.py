import subprocess
import json
from pathlib import Path

ROOT = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0")
learners = json.loads((ROOT / "training/learners.json").read_text())["learners"]
round_dir = ROOT / "artifacts/coevo_run_01/round_001"

# The live_models in round 0 were from learners.json directly.
# Let's rebuild the dict
live_models = {
    "grimmsnarl_marnie": ROOT / "artifacts/overnight_grim_20260730/grim_selected.npz",
    "kangaskhan_crustle": ROOT / "artifacts/bc_v2/kangaskhan_crustle.npz",
    "alakazam_dudunsparce": ROOT / "artifacts/bc_v2/alakazam_dudunsparce.npz",
    "team_rockets_mewtwo_ex": ROOT / "artifacts/bc_v2/team_rockets_mewtwo_ex.npz",
    "dragapult_ex": ROOT / "artifacts/bc_v2/dragapult_ex.npz",
    "cynthias_garchomp_ex": ROOT / "artifacts/bc_v2/cynthias_garchomp_ex.npz",
}

for index, learner in enumerate(learners):
    name = learner["name"]
    challenger = round_dir / f"{name}_challenger.npz"
    rollout = round_dir / f"{name}_rollouts.jsonl.gz"
    
    command = [
        str(ROOT / ".venv/bin/python"),
        "training/train_ppo.py",
        "--initial-model", str(live_models[name]),
        "--rollouts", str(rollout),
        "--output", str(challenger),
        "--epochs", "2",
        "--learning-rate", "0.0001",
        "--bc-weight", str(learner.get("bc_weight", 0.25)),
        "--require-card", str(learner["marker_card"]),
        "--seed", str(20260729 + 50 + index),
    ]
    
    print(f"Running PPO for {name}...")
    subprocess.run(command, cwd=ROOT, check=True)
    print(f"Finished PPO for {name}.")

print("All recovery PPO training completed successfully.")
