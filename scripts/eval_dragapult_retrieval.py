#!/usr/bin/env python3
"""Conservative Elite-State Retrieval to rerank BC Top-3 actions.

Implements a Macro-RAG approach:
1. Load elite Dragapult states and compute 368-dim embeddings.
2. Build an offline exact-NN index.
3. For held-out episodes, retrieve K=5 nearest neighbors.
4. Hard filter by context/semantics.
5. Override BC Top-1 only if consensus is strong and action is in BC Top-3.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from training.schema5 import DirectPolicyNet, load_direct
from training.train_bc import iter_batches, move

def get_state_embeddings(model: DirectPolicyNet, batch: dict) -> torch.Tensor:
    with torch.no_grad():
        _, board = model.encode_entities(batch)
        history = model.encode_events(batch)
        global_vector = F.relu(model.global_input(batch["global"]))
        order = (batch["global"][:, 3] >= 0.5).long()
        order_vector = model.order_embedding(order)
        emb = torch.cat([board, history, global_vector, order_vector], dim=-1)
        return F.normalize(emb, p=2, dim=-1)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-shards", nargs="+", required=True)
    parser.add_argument("--eval-shards", nargs="+", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--threshold", type=float, default=0.98, help="Cosine similarity threshold")
    parser.add_argument("--output", type=Path, default=Path("artifacts/retrieval_eval.json"))
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = DirectPolicyNet().to(device)
    load_direct(model, args.model)
    model.eval()

    print("Building Index...")
    index_embeddings = []
    index_actions = []
    index_contexts = []
    
    with torch.no_grad():
        for batch in iter_batches([Path(p) for p in args.train_shards], batch_size=256, max_records=50000, validation=False, feature_version=5):
            batch = move(batch, device)
            emb = get_state_embeddings(model, batch)
            
            starts = [s for s, _ in batch["record_options"]]
            for record_index, start in enumerate(starts):
                actions = batch["record_actions"][record_index]
                if not actions:
                    continue
                index_embeddings.append(emb[record_index].cpu().numpy())
                index_actions.append(actions[0])
                index_contexts.append(int(batch["context"][start]))
                
    index_tensor = torch.tensor(np.array(index_embeddings), device=device)
    print(f"Index built with {len(index_tensor)} states.")

    # Evaluation
    metrics = {
        "records": 0,
        "overrides_attempted": 0,
        "override_precision": 0,
        "conversions": 0,
        "regressions": 0,
        "bc_correct_baseline": 0,
        "net_correct": 0
    }

    print("Evaluating Retrieval on held-out shards...")
    with torch.no_grad():
        for batch in iter_batches([Path(p) for p in args.eval_shards], batch_size=128, max_records=10000, validation=True, feature_version=5):
            batch = move(batch, device)
            logits, _ = model(batch)
            query_emb = get_state_embeddings(model, batch)
            
            # Compute cosine similarities for the batch
            # Since vectors are L2-normalized, matrix mult gives cosine sim
            sims = torch.matmul(query_emb, index_tensor.T)
            
            starts = [s for s, _ in batch["record_options"]]
            for record_index, (start, end) in enumerate(batch["record_options"]):
                local = logits[start:end]
                actions = batch["record_actions"][record_index]
                if not actions:
                    continue
                    
                metrics["records"] += 1
                chosen = actions[0]
                ranked = torch.argsort(local, descending=True, stable=True).tolist()
                bc_top1 = ranked[0]
                bc_top3 = set(ranked[:3])
                ctx = int(batch["context"][start])
                
                is_bc_correct = (bc_top1 == chosen)
                metrics["bc_correct_baseline"] += int(is_bc_correct)
                
                # Retrieval Logic
                record_sims = sims[record_index]
                top_k_sims, top_k_indices = torch.topk(record_sims, args.k)
                
                valid_neighbors = []
                for sim, idx in zip(top_k_sims.tolist(), top_k_indices.tolist()):
                    if sim < args.threshold:
                        continue
                    if index_contexts[idx] != ctx:
                        continue
                    # Check legality mapping: The retrieved semantic action must be legal
                    # For this offline simplified test, we just check if it's in the current options
                    # In a full engine test we'd map semantic labels.
                    retrieved_action = index_actions[idx]
                    if retrieved_action < (end - start):
                        valid_neighbors.append(retrieved_action)
                        
                final_action = bc_top1
                if len(valid_neighbors) >= (args.k * 0.8): # 80% consensus
                    consensus = max(set(valid_neighbors), key=valid_neighbors.count)
                    if consensus in bc_top3:
                        final_action = consensus
                        metrics["overrides_attempted"] += 1
                        if final_action == chosen:
                            metrics["override_precision"] += 1
                        
                        if not is_bc_correct and final_action == chosen:
                            metrics["conversions"] += 1
                        elif is_bc_correct and final_action != chosen:
                            metrics["regressions"] += 1

                metrics["net_correct"] += int(final_action == chosen)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(metrics, indent=2))
    
    print("Results:")
    for k, v in metrics.items():
        print(f"  {k}: {v}")

if __name__ == "__main__":
    main()
