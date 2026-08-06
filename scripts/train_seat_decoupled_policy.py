#!/usr/bin/env python3
"""Train seat-decoupled policy: strict teacher anchoring on Seat 0, heavy loss-bucket recovery on Seat 1."""

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

from training.train_bc import (
    PolicyNet,
    export_npz,
    iter_batches,
    load_npz_weights,
    masked_count_loss,
    move,
    policy_loss,
)

BASE_MODEL = ROOT / "artifacts" / "overnight_grim_20260730" / "grim_selected.npz"
TEACHER_MODEL = ROOT / "artifacts" / "overnight_grim_20260730" / "grim_selected.npz"
TRAIN_DATA = ROOT / "artifacts" / "top_loss_buckets" / "elite_loss_buckets_train.jsonl.gz"
OUT_DIR = ROOT / "artifacts" / "loss_buckets_model"
OUT_MODEL = OUT_DIR / "decoupled_seat_master_policy.npz"
LOG_FILE = OUT_DIR / "decoupled_training.log"

BATCH_SIZE = 256
EPOCHS = 2
LR = 2.5e-4

def log(msg: str):
    ts = time.strftime("[%Y-%m-%d %H:%M:%S]")
    line = f"{ts} {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text("")
    log("=== STARTING SEAT-DECOUPLED MASTER TRAINING ===")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    log(f"Using device: {device}")

    student = PolicyNet(feature_version=2).to(device)
    load_npz_weights(student, BASE_MODEL)

    teacher = PolicyNet(feature_version=2).to(device)
    load_npz_weights(teacher, TEACHER_MODEL)
    teacher.eval()
    for param in teacher.parameters():
        param.requires_grad = False

    optimizer = torch.optim.AdamW(student.parameters(), lr=LR, weight_decay=1e-4)
    paths = [TRAIN_DATA]

    for epoch in range(1, EPOCHS + 1):
        student.train()
        running_loss = 0.0
        start_t = time.time()
        batch_idx = 0

        for batch in iter_batches(paths, BATCH_SIZE, validation=False, feature_version=2):
            batch_idx += 1
            batch = move(batch, device)

            optimizer.zero_grad()
            s_logits, s_counts, s_values = student(batch)

            with torch.no_grad():
                t_logits, _, _ = teacher(batch)

            opt_loss, _, _ = policy_loss(s_logits, batch)
            cnt_loss = masked_count_loss(s_counts, batch)
            val_loss = F.binary_cross_entropy_with_logits(s_values, batch["values"])

            # Option-level KL Divergence
            kd_loss = F.kl_div(
                F.log_softmax(s_logits, dim=-1),
                F.softmax(t_logits, dim=-1),
                reduction="batchmean",
            )

            # Global feature index 3 is: float(state.firstPlayer == state.yourIndex)
            # 1.0 = Going First (Seat 0 order), 0.0 = Going Second (Seat 1 order)
            went_first = batch["global"][:, 3]
            went_first_opt = went_first[batch["option_record"]]
            first_ratio = float(went_first_opt.mean().item())

            # For Seat 0: Anchor heavily to Teacher (KD weight = 0.90) to preserve 100% of aggression
            # For Seat 1: Apply heavy Loss-Bucket Supervision (CE weight = 0.70, KD = 0.30)
            kd_weight = 0.90 * first_ratio + 0.30 * (1.0 - first_ratio)
            ce_weight = 1.0 - kd_weight

            total_loss = ce_weight * opt_loss + kd_weight * kd_loss + 0.25 * cnt_loss + 0.10 * val_loss
            total_loss.backward()
            torch.nn.utils.clip_grad_norm_(student.parameters(), 1.0)
            optimizer.step()

            running_loss += float(total_loss.item())

            if batch_idx % 500 == 0:
                elapsed = time.time() - start_t
                log(f"Epoch {epoch}/{EPOCHS} [Batch {batch_idx}] | Loss: {running_loss/500:.4f} | "
                    f"Speed: {500*BATCH_SIZE/elapsed:.1f} samples/s")
                running_loss = 0.0
                start_t = time.time()

        export_npz(student, OUT_MODEL)
        log(f"Saved Decoupled Checkpoint after Epoch {epoch} to {OUT_MODEL.name}")

    log("=== SEAT-DECOUPLED TRAINING COMPLETE ===")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
