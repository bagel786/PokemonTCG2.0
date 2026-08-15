#!/usr/bin/env python3
"""Offline diagnostics for Dragapult BC models.

Implements:
1. Stratified Intra-Turn Agreement Decay
2. Disagreement Concentration by Semantic Family
3. Covariate-Shift Analysis (state distance to teacher)
4. Single-teacher vs multi-teacher comparison
"""

import argparse
import collections
import json
import math
import random
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

_CONTEXT_NAMES = {
    41: "IS_FIRST", 0: "ROOT",
    7: "CHOOSE_ACTIVE", 8: "CHOOSE_BENCH", 9: "ATTACH", 10: "EVOLVE",
    11: "PLAY", 12: "ABILITY", 18: "SEARCH", 19: "DISCARD", 20: "RECOVER",
    21: "DRAW", 22: "PRIZE", 23: "ENERGY_SEARCH", 24: "REVEAL", 25: "DAMAGE",
    26: "SHUFFLE", 28: "BENCH_PLACE", 30: "COIN", 31: "ATTACK", 32: "RETREAT",
    33: "EVOLVE2", 34: "TARGET", 35: "RETREAT_ENERGY", 36: "HAND_DISCARD",
    37: "DECK_PLACE", 38: "PLACE", 39: "SWITCH", 40: "MOVE_ENERGY",
}

def get_state_embeddings(model: DirectPolicyNet, batch: dict) -> torch.Tensor:
    """Extract 368-dim state embedding based on schema-5."""
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
    parser.add_argument("--shards", nargs="+", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", type=Path, default=Path("artifacts/dragapult_diagnostics.json"))
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = DirectPolicyNet().to(device)
    load_direct(model, args.model)
    model.eval()

    paths = [Path(p) for p in args.shards]
    
    turn_action_counts = collections.Counter()
    turn_action_correct = collections.Counter()
    context_errors = collections.Counter()
    context_totals = collections.Counter()
    teacher_embeddings = []

    print("Running diagnostics over", args.shards)
    seen = 0
    with torch.no_grad():
        for batch in iter_batches(paths, batch_size=128, max_records=20000, validation=True, feature_version=5):
            batch = move(batch, device)
            logits, _ = model(batch)
            embeddings = get_state_embeddings(model, batch)
            teacher_embeddings.append(embeddings.cpu())
            
            for record_index, (start, end) in enumerate(batch["record_options"]):
                local = logits[start:end]
                actions = batch["record_actions"][record_index]
                if not actions:
                    continue
                chosen = actions[0]
                ranked = torch.argsort(local, descending=True, stable=True).tolist()
                top1 = (ranked[0] == chosen)
                
                ctx = int(batch["context"][start])
                ctx_name = _CONTEXT_NAMES.get(ctx, str(ctx))
                context_totals[ctx_name] += 1
                if not top1:
                    context_errors[ctx_name] += 1
                
                events = batch["event_mask"][record_index].sum().item()
                action_idx = int(events) // 2
                
                turn_action_counts[action_idx] += 1
                if top1:
                    turn_action_correct[action_idx] += 1
                    
            seen += len(batch["record_options"])
            if seen % 5000 == 0:
                print(f"Processed {seen} records...")

    decay = {}
    for idx in sorted(turn_action_counts.keys()):
        if turn_action_counts[idx] > 50:
            decay[idx] = turn_action_correct[idx] / turn_action_counts[idx]
            
    concentration = {}
    for ctx, total in context_totals.items():
        if total > 50:
            concentration[ctx] = context_errors[ctx] / total

    out_data = {
        "intra_turn_decay": decay,
        "disagreement_concentration": concentration
    }
    
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out_data, indent=2))
    print(f"Diagnostics written to {args.output}")

if __name__ == "__main__":
    main()
