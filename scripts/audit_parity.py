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
from training.schema5 import DirectPolicyNet
from training.train_bc import collate

def main():
    model_path = ROOT / "artifacts/dragapult_emergency/bc_combined_sem.npz"
    np_model = NumpyDirectPolicyModel(model_path)
    torch_model = DirectPolicyNet()
    
    # Load weights into torch model
    arrays = np.load(model_path, allow_pickle=False)
    state_dict = {}
    for k in arrays.files:
        if k.startswith("d__"):
            state_dict[k[3:].replace("__", ".")] = torch.from_numpy(arrays[k])
    # Ignore missing keys (e.g. optimizer states or extra stuff)
    torch_model.load_state_dict(state_dict, strict=False)
    torch_model.eval()

    traces = list(ROOT.glob("trace_out/*.jsonl"))
    if not traces:
        print("No traces found!")
        return 1
    
    total_states = 0
    max_diff = 0.0
    
    for trace_file in traces:
        for line in trace_file.read_text().splitlines():
            if not line.strip(): continue
            row = json.loads(line)
            features_dict = row["features"]
            
            # 1. NumPy prediction
            feat_obj = DecisionFeatures.from_json(features_dict)
            np_logits, np_counts = np_model.predict(feat_obj)
            
            # 2. Torch prediction
            # Need to format batch for collate
            batch_row = {"features": features_dict, "action": row["action"], "reward": row["reward"]}
            batch = collate([batch_row])
            with torch.no_grad():
                torch_logits, torch_counts = torch_model(batch)
            
            torch_logits_np = torch_logits.numpy()
            
            # 3. Assert exact float parity
            # Logits can have different shapes if one is 1D and other is 2D
            if np_logits.shape != torch_logits_np.shape:
                if torch_logits_np.ndim == 2 and torch_logits_np.shape[0] == 1:
                    torch_logits_np = torch_logits_np.squeeze(0)
            
            diff = np.abs(np_logits - torch_logits_np).max()
            max_diff = max(max_diff, diff)
            if diff > 1e-5:
                print(f"Parity mismatch at {row['episode_id']} step {row['step']}: diff {diff}")
                return 1
            
            total_states += 1
            
    print(f"Parity Audit PASS: {total_states} states verified. Max difference: {max_diff}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
