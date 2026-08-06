#!/usr/bin/env python3
"""Train master policy model on 1M+ loss-bucket dataset with streaming batches and KL distillation."""

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

BASE_MODEL = ROOT / "artifacts" / "seat1_data" / "candidate_seat1_boosted.npz"
TEACHER_MODEL = ROOT / "artifacts" / "overnight_grim_20260730" / "grim_selected.npz"
TRAIN_DATA = ROOT / "artifacts" / "top_loss_buckets" / "elite_loss_buckets_train.jsonl.gz"
OUT_DIR = ROOT / "artifacts" / "loss_buckets_model"
OUT_MODEL = OUT_DIR / "master_loss_buckets_policy.npz"
LOG_FILE = OUT_DIR / "training.log"

BATCH_SIZE = 256
EPOCHS = 2
LR = 2e-4
KD_WEIGHT = 0.65

def log(msg: str):
    ts = time.strftime("[%Y-%m-%d %H:%M:%S]")
    line = f"{ts} {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

@torch.no_grad()
def evaluate_stream(model: PolicyNet, paths: list[Path], device: torch.device, max_records: int = 10000) -> tuple[float, float]:
    model.eval()
    running = agreements = agreement_total = batches = records = 0
    for batch in iter_batches(paths, BATCH_SIZE, max_records=max_records, validation=True, feature_version=model.feature_version):
        records += len(batch["record_options"])
        batch = move(batch, device)
        logits, count_logits, values = model(batch)
        option_loss, correct, total = policy_loss(logits, batch)
        loss = option_loss + 0.25 * masked_count_loss(count_logits, batch) + 0.10 * F.binary_cross_entropy_with_logits(values, batch["values"])
        running += float(loss.item())
        agreements += correct
        agreement_total += total
        batches += 1
    val_loss = running / max(1, batches)
    val_acc = (agreements / max(1, agreement_total)) * 100.0 if agreement_total else 0.0
    return val_loss, val_acc

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text("")
    log("=== STARTING MASTER LOSS-BUCKETS STREAMING TRAINING ===")

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
    log(f"Using compute device: {device}")

    student_model = PolicyNet(feature_version=2).to(device)
    load_npz_weights(student_model, BASE_MODEL)
    log(f"Loaded student base weights from {BASE_MODEL.name}")

    teacher_model = PolicyNet(feature_version=2).to(device)
    load_npz_weights(teacher_model, TEACHER_MODEL)
    teacher_model.eval()
    for param in teacher_model.parameters():
        param.requires_grad = False
    log(f"Loaded teacher weights from {TEACHER_MODEL.name} for KL distillation anchoring.")

    paths = [TRAIN_DATA]

    val_loss, val_acc = evaluate_stream(student_model, paths, device, max_records=8000)
    log(f"Pre-training Validation Loss: {val_loss:.4f} | Single-Choice Top-1 Accuracy: {val_acc:.2f}%")

    optimizer = torch.optim.AdamW(student_model.parameters(), lr=LR, weight_decay=1e-4)

    best_val_acc = val_acc

    for epoch in range(1, EPOCHS + 1):
        student_model.train()
        running_ce = 0.0
        running_kd = 0.0
        start_t = time.time()
        batch_idx = 0

        for batch in iter_batches(paths, BATCH_SIZE, validation=False, feature_version=student_model.feature_version):
            batch_idx += 1
            batch = move(batch, device)

            optimizer.zero_grad()
            student_logits, student_count_logits, student_values = student_model(batch)

            with torch.no_grad():
                teacher_logits, _, _ = teacher_model(batch)

            opt_loss, _, _ = policy_loss(student_logits, batch)
            cnt_loss = masked_count_loss(student_count_logits, batch)
            val_loss_term = F.binary_cross_entropy_with_logits(student_values, batch["values"])

            # Option-level KL Divergence
            kd_loss = F.kl_div(
                F.log_softmax(student_logits, dim=-1),
                F.softmax(teacher_logits, dim=-1),
                reduction="batchmean",
            )

            total_loss = (1.0 - KD_WEIGHT) * opt_loss + KD_WEIGHT * kd_loss + 0.25 * cnt_loss + 0.10 * val_loss_term
            total_loss.backward()
            torch.nn.utils.clip_grad_norm_(student_model.parameters(), 1.0)
            optimizer.step()

            running_ce += float(opt_loss.item())
            running_kd += float(kd_loss.item())

            if batch_idx % 250 == 0:
                elapsed = time.time() - start_t
                log(f"Epoch {epoch}/{EPOCHS} [Batch {batch_idx}] | "
                    f"Option Loss: {running_ce/250:.4f} | KD Loss: {running_kd/250:.4f} | "
                    f"Speed: {250*BATCH_SIZE/elapsed:.1f} samples/s")
                running_ce = 0.0
                running_kd = 0.0
                start_t = time.time()

        val_loss, val_acc = evaluate_stream(student_model, paths, device, max_records=10000)
        log(f"--- Epoch {epoch} Complete ---")
        log(f"Validation Loss: {val_loss:.4f} | Accuracy: {val_acc:.2f}%")

        if val_acc >= best_val_acc or epoch == EPOCHS:
            best_val_acc = val_acc
            export_npz(student_model, OUT_MODEL)
            log(f"Saved master model checkpoint to {OUT_MODEL.name} (Val Acc: {val_acc:.2f}%)")

    log("=== MASTER LOSS-BUCKETS TRAINING FINISHED ===")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
