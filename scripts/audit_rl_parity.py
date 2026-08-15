#!/usr/bin/env python3
import sys
import json
import torch
import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from ptcg_ai.direct import NumpyDirectPolicyModel
from ptcg_ai.features import DecisionFeatures
from training.schema5_relational import RelationalDirectPolicyNet, load_relational
from training.train_bc import collate

class DummyFallback:
    def choose(self, obs):
        return [0]
    def reset(self):
        pass

def main():
    model_path = ROOT / "artifacts/dragapult_emergency/bc_combined_8ep.npz"
    np_model = NumpyDirectPolicyModel(model_path)
    torch_model = RelationalDirectPolicyNet()
    
    # Load weights into relational torch model
    load_relational(torch_model, model_path)
    torch_model.eval()

    # (removed runtime policy instance)

    traces = list(ROOT.glob("trace_out/*.jsonl"))
    if not traces:
        print("No traces found!")
        return 1
    
    total_states = 0
    max_opt_diff = 0.0
    sum_opt_diff = 0.0
    max_cnt_diff = 0.0
    sum_cnt_diff = 0.0
    top1_mismatch = 0
    top3_mismatch = 0
    cnt_mismatch = 0
    greedy_mismatch = 0

    shield_changes = 0
    sanitization_changes = 0
    fallback_changes = 0
    
    for trace_file in traces:
        for line in trace_file.read_text().splitlines():
            if not line.strip(): continue
            row = json.loads(line)
            features_dict = row["features"]
            feat_obj = DecisionFeatures.from_json(features_dict)
            
            if not feat_obj.options:
                continue

            # NumPy
            np_logits, np_counts = np_model.predict(feat_obj)
            
            # Torch
            batch = collate([{"features": features_dict, "action": row["action"], "reward": row["reward"]}])
            with torch.no_grad():
                torch_logits, torch_counts = torch_model(batch)
                
            torch_logits_np = torch_logits.numpy().squeeze()
            torch_counts_np = torch_counts.numpy().squeeze()
            
            # If after squeeze it became a 0-d array (scalar), make it 1D
            if torch_logits_np.ndim == 0: torch_logits_np = torch_logits_np.reshape(-1)
            if torch_counts_np.ndim == 0: torch_counts_np = torch_counts_np.reshape(-1)

            
            # Differences
            opt_diff = np.abs(np_logits - torch_logits_np)
            cnt_diff = np.abs(np_counts - torch_counts_np)
            
            max_opt_diff = max(max_opt_diff, opt_diff.max())
            sum_opt_diff += opt_diff.mean()
            
            max_cnt_diff = max(max_cnt_diff, cnt_diff.max())
            sum_cnt_diff += cnt_diff.mean()
            
            # Top-1 mismatch
            np_top1 = np.argmax(np_logits)
            torch_top1 = np.argmax(torch_logits_np)
            if np_top1 != torch_top1:
                top1_mismatch += 1
                
            # Top-3 mismatch
            np_top3 = set(np.argsort(np_logits)[-3:])
            torch_top3 = set(np.argsort(torch_logits_np)[-3:])
            if np_top3 != torch_top3:
                top3_mismatch += 1
                
            # Count mismatch
            np_cnt = np.argmax(np_counts) + 1
            torch_cnt = np.argmax(torch_counts_np) + 1
            if np_cnt != torch_cnt:
                cnt_mismatch += 1
                
            # Raw greedy complete action
            # Wait, greedy complete action includes picking the top `count` options!
            count = min(np_cnt, len(np_logits))
            np_greedy = sorted(np.argsort(np_logits)[-count:].tolist())
            
            t_count = min(torch_cnt, len(torch_logits_np))
            t_greedy = sorted(np.argsort(torch_logits_np)[-t_count:].tolist())
            if np_greedy != t_greedy:
                greedy_mismatch += 1
                
            # Runtime intervention check
            # We don't have full observation object here, but we can see what the runtime would do.
            # However, we only have `feat_obj`. `runtime_policy.choose(obs)` expects full `cg.api.Observation`.
            # We can't re-run full `choose()` without the observation dictionary!
            
            total_states += 1

    print("=== Parity Report ===")
    print(f"Rows evaluated: {total_states}")
    print(f"Max abs option-logit difference: {max_opt_diff}")
    print(f"Mean abs option-logit difference: {sum_opt_diff / max(1, total_states)}")
    print(f"Max abs count-logit difference: {max_cnt_diff}")
    print(f"Mean abs count-logit difference: {sum_cnt_diff / max(1, total_states)}")
    print(f"Top-1 mismatch count: {top1_mismatch}")
    print(f"Top-3-set mismatch count: {top3_mismatch}")
    print(f"Desired-count mismatch count: {cnt_mismatch}")
    print(f"Raw greedy complete-action mismatch count: {greedy_mismatch}")

if __name__ == "__main__":
    sys.exit(main())
