import json, gzip, sys, torch
import numpy as np
from pathlib import Path
ROOT = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))
from training.train_bc import collate
from training.schema5_relational import RelationalDirectPolicyNet, load_relational
from training.outcome_rl import complete_logprob

actor = RelationalDirectPolicyNet()
load_relational(actor, ROOT / "artifacts/dragapult_emergency/bc_combined_8ep.npz")
actor.eval()

diffs = []
ratios = []

with torch.no_grad():
    with gzip.open("trace_rl_pilot/rollouts.jsonl.gz", "rt") as f:
        for line in f:
            row = json.loads(line)
            old_logprob = row["old_logprob"]
            batch = collate([{"features": row["features"], "action": row["action"], "reward": 0}])
            logits, counts = actor(batch)
            new_logprob = complete_logprob(logits, counts, batch, 0, row["action"], temperature=0.15).item()
            diffs.append(abs(new_logprob - old_logprob))
            ratios.append(np.exp(new_logprob - old_logprob))
            
diffs = np.array(diffs)
ratios = np.array(ratios)

print(f"Rows: {len(diffs)}")
print(f"Max absolute difference: {np.max(diffs)}")
print(f"Mean absolute difference: {np.mean(diffs)}")
print(f"p99 absolute difference: {np.percentile(diffs, 99)}")
print(f"Ratio mean: {np.mean(ratios)}")
print(f"Ratio min: {np.min(ratios)}")
print(f"Ratio max: {np.max(ratios)}")
approx_kl = (ratios - 1) - np.log(ratios)
print(f"Approximate KL mean: {np.mean(approx_kl)}")
