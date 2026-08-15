#!/usr/bin/env python3
import sys
import json
import torch
import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from ptcg_ai.features import DecisionFeatures
from cg.api import SelectContext
from training.schema5_relational import RelationalDirectPolicyNet, load_relational
from training.train_bc import collate

def main():
    initial_path = ROOT / "artifacts/dragapult_emergency/bc_combined_8ep.npz"
    candidate_path = ROOT / "trace_rl_pilot/rl_candidate.npz"
    
    if not candidate_path.exists():
        print(f"Not found: {candidate_path}")
        return 1

    model_init = RelationalDirectPolicyNet()
    load_relational(model_init, initial_path)
    model_init.eval()

    model_cand = RelationalDirectPolicyNet()
    load_relational(model_cand, candidate_path)
    model_cand.eval()

    traces = list(ROOT.glob("trace_out/*.jsonl"))
    
    total = 0
    top1_disagreements = 0
    top3_disagreements = 0
    cnt_disagreements = 0
    greedy_disagreements = 0
    logit_movements = []
    
    context_disagreements = {}
    context_totals = {}

    for trace_file in traces:
        for line in trace_file.read_text().splitlines():
            if not line.strip(): continue
            row = json.loads(line)
            feat_dict = row["features"]
            feat_obj = DecisionFeatures.from_json(feat_dict)
            if not feat_obj.options:
                continue
            
            ctx = feat_obj.options[0].context
            context_totals[ctx] = context_totals.get(ctx, 0) + 1

            batch = collate([{"features": feat_dict, "action": row["action"], "reward": row["reward"]}])
            with torch.no_grad():
                init_l, init_c = model_init(batch)
                cand_l, cand_c = model_cand(batch)
                
            init_l = init_l.numpy().squeeze()
            init_c = init_c.numpy().squeeze()
            if init_l.ndim == 0: init_l = init_l.reshape(-1)
            if init_c.ndim == 0: init_c = init_c.reshape(-1)
            
            cand_l = cand_l.numpy().squeeze()
            cand_c = cand_c.numpy().squeeze()
            if cand_l.ndim == 0: cand_l = cand_l.reshape(-1)
            if cand_c.ndim == 0: cand_c = cand_c.reshape(-1)
            
            # top1
            top1_diff = (np.argmax(init_l) != np.argmax(cand_l))
            if top1_diff: top1_disagreements += 1
            
            # top3
            if set(np.argsort(init_l)[-3:]) != set(np.argsort(cand_l)[-3:]):
                top3_disagreements += 1
                
            # count
            cnt_diff = (np.argmax(init_c) != np.argmax(cand_c))
            if cnt_diff: cnt_disagreements += 1
                
            # greedy
            c_init = min(np.argmax(init_c) + 1, len(init_l))
            c_cand = min(np.argmax(cand_c) + 1, len(cand_l))
            g_init = sorted(np.argsort(init_l)[-c_init:].tolist())
            g_cand = sorted(np.argsort(cand_l)[-c_cand:].tolist())
            greedy_diff = (g_init != g_cand)
            if greedy_diff:
                greedy_disagreements += 1
                context_disagreements[ctx] = context_disagreements.get(ctx, 0) + 1

            # logit movement
            logit_movements.append(np.abs(init_l - cand_l).mean())
            
            total += 1

    print("=== Static Policy Movement Audit ===")
    print(f"Total rows: {total}")
    print(f"Top-1 disagreement: {top1_disagreements} ({top1_disagreements/max(1, total)*100:.2f}%)")
    print(f"Top-3-set disagreement: {top3_disagreements} ({top3_disagreements/max(1, total)*100:.2f}%)")
    print(f"Count-choice disagreement: {cnt_disagreements} ({cnt_disagreements/max(1, total)*100:.2f}%)")
    print(f"Complete-action disagreement: {greedy_disagreements} ({greedy_disagreements/max(1, total)*100:.2f}%)")
    
    print(f"Mean logit movement: {np.mean(logit_movements):.8f}")
    print(f"Median logit movement: {np.median(logit_movements):.8f}")
    
    print("\nComplete-action disagreements by SelectContext:")
    for ctx, count in sorted(context_totals.items()):
        disagreements = context_disagreements.get(ctx, 0)
        print(f"  {SelectContext(ctx).name}: {disagreements}/{count} ({disagreements/max(1, count)*100:.2f}%)")

if __name__ == "__main__":
    sys.exit(main())
