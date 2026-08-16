#!/usr/bin/env python3
"""Report C1 clone-vs-teacher agreement on validation rows, split by opponent tag."""
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

import numpy as np
import torch

from training.train_bc import iter_batches, move
from training.schema5 import DirectPolicyNet
from scripts.dragapult_emergency_train import semantic_group_loss

TAGS = ("record_starmie", "record_grimmsnarl", "record_dipplin",
        "record_alakazam")


def main() -> int:
    model_path = sys.argv[1]
    shard_paths = sys.argv[2:]
    model = DirectPolicyNet()
    device = torch.device("cpu")
    model.load_state_dict(torch.load(model_path, map_location=device, weights_only=False) if model_path.endswith(".pt") else load_npz_state(model_path, model))
    model.eval()
    buckets = {tag: [0, 0] for tag in TAGS}
    buckets["other"] = [0, 0]
    ctx_buckets = defaultdict(lambda: [0, 0])
    for batch in iter_batches(shard_paths, 256, feature_version=5, validation=False):
        batch = move(batch, device)
        with torch.no_grad():
            logits, counts = model(batch)
        for ri, (start, end) in enumerate(batch["record_options"]):
            actions = batch["record_actions"][ri]
            if len(actions) != 1:
                continue
            local = logits[start:end]
            ranked = torch.argsort(local, descending=True, stable=True).tolist()
            top1 = int(ranked[0] == actions[0])
            ctx = int(batch["context"][start])
            ctx_buckets[ctx][0] += top1
            ctx_buckets[ctx][1] += 1
            for tag in TAGS:
                flagged = batch.get(tag)
                if flagged and flagged[ri]:
                    buckets[tag][0] += top1
                    buckets[tag][1] += 1
                    break
            else:
                buckets["other"][0] += top1
                buckets["other"][1] += 1
    print(f"model: {model_path}")
    total_c = sum(v[0] for v in buckets.values())
    total_n = sum(v[1] for v in buckets.values())
    print(f"overall top1 {total_c}/{total_n} ({100*total_c/max(1,total_n):.1f}%)")
    for tag, (c, n) in buckets.items():
        if n:
            print(f"  {tag}: {c}/{n} ({100*c/n:.1f}%)")
    for ctx, (c, n) in sorted(ctx_buckets.items()):
        if n >= 30:
            print(f"  ctx {ctx}: {c}/{n} ({100*c/n:.1f}%)")
    return 0


def load_npz_state(path, model):
    arrays = np.load(path, allow_pickle=False)
    state = model.state_dict()
    for name in state:
        key = f"d__{name.replace('.', '__')}"
        if key not in arrays:
            raise ValueError(f"missing weight: {key}")
        state[name].copy_(torch.as_tensor(np.asarray(arrays[key]), dtype=state[name].dtype))
    model.load_state_dict(state)
    return state


if __name__ == "__main__":
    raise SystemExit(main())
