#!/usr/bin/env python3
"""Execute staged fine-tuning on Candidate 2 for Seat-1 defense with KL distillation anchoring."""

import gzip
import json
import os
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if (ROOT / "vendor").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

import numpy as np
import torch
import torch.nn.functional as F

from ptcg_ai.features import MAX_SELECT_COUNT
from training.train_bc import (
    PolicyNet,
    collate,
    export_npz,
    load_npz_weights,
    masked_count_loss,
    policy_loss,
)

BASE_MODEL = ROOT / "artifacts" / "overnight_pipeline_output" / "candidate_checkpoints" / "candidate_2_heads_1e4.npz"
TEACHER_MODEL = ROOT / "artifacts" / "overnight_grim_20260730" / "grim_selected.npz"
TRAIN_DATA = ROOT / "artifacts" / "seat1_data" / "seat1_train.jsonl.gz"
OUT_DIR = ROOT / "artifacts" / "seat1_data"
OUT_MODEL = OUT_DIR / "candidate_seat1_boosted.npz"
LOG_FILE = OUT_DIR / "seat1_training.log"

def log(msg: str):
    ts = time.strftime("[%Y-%m-%d %H:%M:%S]")
    line = f"{ts} {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text("")
    log("=== STARTING SEAT-1 STAGED FINE-TUNING ===")

    if not BASE_MODEL.exists():
        log(f"Error: Base model {BASE_MODEL} not found.")
        return 1
    if not TEACHER_MODEL.exists():
        log(f"Error: Teacher model {TEACHER_MODEL} not found.")
        return 1
    if not TRAIN_DATA.exists():
        log(f"Error: Training data {TRAIN_DATA} not found.")
        return 1

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    log(f"Using device: {device}")

    # Load Teacher (d842 for KL distillation)
    teacher = PolicyNet(feature_version=2)
    load_npz_weights(teacher, TEACHER_MODEL)
    teacher.eval().to(device)
    for p in teacher.parameters():
        p.requires_grad = False

    # Load Student (Base Candidate 2)
    student = PolicyNet(feature_version=2)
    load_npz_weights(student, BASE_MODEL)
    student.to(device)

    # Trainable heads
    trainable_modules = ("option_linear", "score", "count", "value")
    trainable_params = []
    for name, p in student.named_parameters():
        mod = name.split(".")[0]
        if mod in trainable_modules:
            p.requires_grad = True
            trainable_params.append(p)
        else:
            p.requires_grad = False

    lr = 3e-5
    distill_weight = 0.75
    optimizer = torch.optim.AdamW(trainable_params, lr=lr, weight_decay=1e-5)

    log(f"Base Model: {BASE_MODEL.name}")
    log(f"Distill Weight (KL to d842): {distill_weight}")
    log(f"Fine-Tuning Head LR: {lr}")

    epochs = 2
    batch_size = 256

    # Load data into memory stream
    log(f"Streaming data from {TRAIN_DATA.name}...")
    rows = []
    with gzip.open(TRAIN_DATA, "rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))

    total_rows = len(rows)
    log(f"Loaded {total_rows} Seat-1 upweighted training records.")

    for ep in range(1, epochs + 1):
        random.shuffle(rows)
        student.train()
        total_loss = 0.0
        total_batches = 0
        ep_start = time.time()

        for b_idx in range(0, total_rows, batch_size):
            batch_rows = rows[b_idx : b_idx + batch_size]
            if not batch_rows:
                continue

            batch = collate(batch_rows)
            batch_dev = {k: v.to(device) if isinstance(v, torch.Tensor) else v for k, v in batch.items()}

            logits, count_logits, val = student(batch_dev)
            with torch.no_grad():
                t_logits, t_count_logits, _ = teacher(batch_dev)

            # Supervision losses
            p_loss, _, _ = policy_loss(logits, batch_dev)
            c_loss = masked_count_loss(count_logits, batch_dev)

            # Distillation KL losses
            kl_policy = F.kl_div(F.log_softmax(logits, dim=-1), F.softmax(t_logits, dim=-1), reduction="batchmean")
            kl_count = F.kl_div(F.log_softmax(count_logits, dim=-1), F.softmax(t_count_logits, dim=-1), reduction="batchmean")

            loss = (1.0 - distill_weight) * (p_loss + c_loss) + distill_weight * (kl_policy + kl_count)

            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(trainable_params, 1.0)
            optimizer.step()

            total_loss += loss.item()
            total_batches += 1

            if total_batches % 200 == 0:
                elapsed = time.time() - ep_start
                avg_loss = total_loss / total_batches
                log(f"Epoch {ep}/{epochs} | Batch {total_batches} | Loss: {avg_loss:.4f} | Elapsed: {elapsed:.1f}s")

        ep_elapsed = time.time() - ep_start
        log(f"Epoch {ep}/{epochs} Complete. Avg Loss: {total_loss / total_batches:.4f} in {ep_elapsed:.1f}s")

    # Export weights
    log(f"Exporting fine-tuned weights to {OUT_MODEL}...")
    export_npz(student, OUT_MODEL)
    log(f"Checkpoint successfully exported to {OUT_MODEL}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
