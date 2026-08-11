#!/usr/bin/env python3
"""Train Pokémon TCG AI v2 model with balanced distillation and calibrated Value Head."""

from __future__ import annotations

import argparse
import hashlib
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
import torch.nn as nn
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

DEFAULT_BASE = ROOT / "artifacts" / "overnight_grim_20260730" / "grim_selected.npz"
DEFAULT_TEACHER = ROOT / "artifacts" / "overnight_grim_20260730" / "grim_selected.npz"
DEFAULT_TRAIN_DATA = ROOT / "data" / "multiday_processed" / "train.jsonl.gz"
DEFAULT_VAL_DATA = ROOT / "data" / "multiday_processed" / "validation.jsonl.gz"
DEFAULT_OUT_DIR = ROOT / "artifacts" / "v2_model"


def log(msg: str, log_file: Path | None = None):
    ts = time.strftime("[%Y-%m-%d %H:%M:%S]")
    line = f"{ts} {msg}"
    print(line, flush=True)
    if log_file is not None:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")


@torch.no_grad()
def evaluate_model(
    model: PolicyNet,
    val_path: Path,
    device: torch.device,
    max_records: int = 0,
    batch_size: int = 256,
) -> tuple[float, float, float]:
    model.eval()
    running_loss = 0.0
    running_val_err = 0.0
    agreements = 0
    agreement_total = 0
    batches = 0

    for batch in iter_batches([val_path], batch_size, max_records=max_records, validation=True, feature_version=model.feature_version):
        batch = move(batch, device)
        logits, count_logits, values = model(batch)
        opt_loss, correct, total = policy_loss(logits, batch)
        cnt_loss = masked_count_loss(count_logits, batch)
        val_loss = F.binary_cross_entropy_with_logits(values, batch["values"])

        loss = opt_loss + 0.25 * cnt_loss + 0.20 * val_loss
        running_loss += float(loss.item())
        running_val_err += float(val_loss.item())
        agreements += correct
        agreement_total += total
        batches += 1

    mean_loss = running_loss / max(1, batches)
    mean_val_err = running_val_err / max(1, batches)
    acc = (agreements / max(1, agreement_total)) * 100.0 if agreement_total else 0.0
    return mean_loss, acc, mean_val_err


def train_v2(
    base_model_path: Path = DEFAULT_BASE,
    teacher_model_path: Path = DEFAULT_TEACHER,
    train_data_path: Path = DEFAULT_TRAIN_DATA,
    val_data_path: Path = DEFAULT_VAL_DATA,
    out_dir: Path = DEFAULT_OUT_DIR,
    epochs: int = 2,
    batch_size: int = 256,
    lr: float = 1.5e-4,
    kd_weight: float = 0.50,
    value_weight: float = 0.20,
    max_train_records: int = 0,
    max_validation_records: int = 0,
    seed: int = 20260811,
    trainable_modules: tuple[str, ...] = (),
    feature_version: int = 0,
):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_file = out_dir / "training_v2.log"
    log_file.write_text("")

    log("=== STARTING POKÉMON TCG AI V2 MODEL TRAINING ===", log_file)
    log(f"Base Model: {base_model_path}", log_file)
    log(f"Teacher Model: {teacher_model_path}", log_file)
    log(f"Train Data: {train_data_path}", log_file)
    if not feature_version:
        with np.load(base_model_path, allow_pickle=False) as arrays:
            feature_version = int(np.asarray(arrays.get("model_schema_version", 1)).item())
    if feature_version not in (1, 2, 3, 4, 5):
        raise ValueError(f"unsupported feature version: {feature_version}")
    log(
        f"Hyperparameters: epochs={epochs}, batch_size={batch_size}, lr={lr}, "
        f"kd={kd_weight}, value_weight={value_weight}, seed={seed}, "
        f"feature_version={feature_version}, "
        f"trainable_modules={','.join(trainable_modules) if trainable_modules else 'all'}",
        log_file,
    )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    log(f"Compute Device: {device}", log_file)

    student = PolicyNet(feature_version=feature_version).to(device)
    load_npz_weights(student, base_model_path)
    log("Loaded student base weights.", log_file)

    known_modules = {name for name, _ in student.named_children()}
    if trainable_modules:
        unknown = set(trainable_modules) - known_modules
        if unknown:
            raise ValueError(f"unknown trainable modules: {sorted(unknown)}")
        for name, parameter in student.named_parameters():
            parameter.requires_grad = name.split(".", 1)[0] in trainable_modules
    trainable_parameters = [parameter for parameter in student.parameters() if parameter.requires_grad]
    if not trainable_parameters:
        raise ValueError("at least one model parameter must be trainable")

    teacher = PolicyNet(feature_version=feature_version).to(device)
    load_npz_weights(teacher, teacher_model_path)
    teacher.eval()
    for param in teacher.parameters():
        param.requires_grad = False
    log("Loaded frozen teacher weights for KL distillation anchoring.", log_file)

    pre_acc = 0.0
    if val_data_path.exists():
        pre_loss, pre_acc, pre_verr = evaluate_model(
            student,
            val_data_path,
            device,
            max_records=max_validation_records,
            batch_size=batch_size,
        )
        log(f"Pre-training Validation: Loss={pre_loss:.4f} | Top-1 Acc={pre_acc:.2f}% | Value BCE={pre_verr:.4f}", log_file)

    optimizer = torch.optim.AdamW(trainable_parameters, lr=lr, weight_decay=1e-4)
    best_val_acc = pre_acc
    out_weights = out_dir / "policy_weights.npz"
    export_npz(student, out_weights)
    log(f"Saved baseline checkpoint to {out_weights}", log_file)

    for epoch in range(1, epochs + 1):
        student.train()
        total_batches = 0
        running_loss = 0.0
        running_opt_loss = 0.0
        running_kd_loss = 0.0
        running_val_loss = 0.0
        agreements = 0
        total_decisions = 0
        t0 = time.time()

        for batch in iter_batches(
            [train_data_path],
            batch_size,
            max_records=max_train_records,
            validation=False,
            feature_version=feature_version,
        ):
            batch = move(batch, device)
            optimizer.zero_grad()

            logits, count_logits, values = student(batch)
            opt_loss, correct, total = policy_loss(logits, batch)
            cnt_loss = masked_count_loss(count_logits, batch)
            val_loss = F.binary_cross_entropy_with_logits(values, batch["values"])

            # Teacher distillation target
            with torch.no_grad():
                t_logits, _, _ = teacher(batch)

            # Segmented logit distillation
            kd_loss = torch.tensor(0.0, device=device)
            if kd_weight > 0:
                kd_terms = []
                for s_start, s_end in batch["record_options"]:
                    if s_end > s_start:
                        s_sub = F.log_softmax(logits[s_start:s_end], dim=0)
                        t_sub = F.softmax(t_logits[s_start:s_end], dim=0)
                        kd_terms.append(F.kl_div(s_sub, t_sub, reduction="sum"))
                if kd_terms:
                    kd_loss = torch.stack(kd_terms).mean()

            loss = opt_loss + 0.25 * cnt_loss + kd_weight * kd_loss + value_weight * val_loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(trainable_parameters, 1.0)
            optimizer.step()

            running_loss += float(loss.item())
            running_opt_loss += float(opt_loss.item())
            running_kd_loss += float(kd_loss.item())
            running_val_loss += float(val_loss.item())
            agreements += correct
            total_decisions += total
            total_batches += 1

            if total_batches % 200 == 0:
                elapsed = time.time() - t0
                step_acc = (agreements / max(1, total_decisions)) * 100.0
                log(
                    f"Epoch {epoch} [{total_batches} batches] Loss: {running_loss/total_batches:.4f} "
                    f"(Opt: {running_opt_loss/total_batches:.4f}, KD: {running_kd_loss/total_batches:.4f}, Val: {running_val_loss/total_batches:.4f}) "
                    f"| Acc: {step_acc:.2f}% | Elapsed: {elapsed:.1f}s",
                    log_file,
                )

        # Validation at epoch end
        if val_data_path.exists():
            v_loss, v_acc, v_verr = evaluate_model(
                student,
                val_data_path,
                device,
                max_records=max_validation_records,
                batch_size=batch_size,
            )
            log(f"=== Epoch {epoch} Validation: Loss={v_loss:.4f} | Top-1 Acc={v_acc:.2f}% | Value BCE={v_verr:.4f} ===", log_file)
            if v_acc > best_val_acc:
                best_val_acc = v_acc
                export_npz(student, out_weights)
                log(f"-> Saved new best model checkpoint to {out_weights}", log_file)
        else:
            export_npz(student, out_weights)
            log(f"-> Exported model checkpoint to {out_weights}", log_file)

    digest = hashlib.sha256(out_weights.read_bytes()).hexdigest()
    summary = {
        "base_model": str(base_model_path),
        "teacher_model": str(teacher_model_path),
        "train_data": str(train_data_path),
        "validation_data": str(val_data_path),
        "seed": seed,
        "epochs": epochs,
        "batch_size": batch_size,
        "learning_rate": lr,
        "kd_weight": kd_weight,
        "value_weight": value_weight,
        "max_train_records": max_train_records,
        "max_validation_records": max_validation_records,
        "trainable_modules": list(trainable_modules) if trainable_modules else "all",
        "feature_version": feature_version,
        "best_validation_top1_percent": best_val_acc,
        "output_sha256": digest,
    }
    (out_dir / "training_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    log(f"Training completed successfully! Best model saved to {out_weights} ({digest})", log_file)
    return out_weights


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=str(DEFAULT_BASE), help="Base model npz")
    parser.add_argument("--teacher", default=str(DEFAULT_TEACHER), help="Teacher model npz")
    parser.add_argument("--train-data", default=str(DEFAULT_TRAIN_DATA), help="Train jsonl.gz")
    parser.add_argument("--val-data", default=str(DEFAULT_VAL_DATA), help="Validation jsonl.gz")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output directory")
    parser.add_argument("--epochs", type=int, default=2, help="Training epochs")
    parser.add_argument("--batch-size", type=int, default=256, help="Batch size")
    parser.add_argument("--lr", type=float, default=1.5e-4, help="Learning rate")
    parser.add_argument("--kd-weight", type=float, default=0.50, help="Distillation weight")
    parser.add_argument("--value-weight", type=float, default=0.20, help="Value loss weight")
    parser.add_argument("--max-records", type=int, default=0, help="Max records (0=all)")
    parser.add_argument("--max-validation-records", type=int, default=0, help="Max validation records (0=all)")
    parser.add_argument("--seed", type=int, default=20260811)
    parser.add_argument("--feature-version", type=int, choices=(1, 2, 3, 4, 5), default=0)
    parser.add_argument(
        "--trainable-modules",
        default="",
        help="Comma-separated child modules to update; empty updates the full network",
    )
    args = parser.parse_args()

    train_v2(
        base_model_path=Path(args.base),
        teacher_model_path=Path(args.teacher),
        train_data_path=Path(args.train_data),
        val_data_path=Path(args.val_data),
        out_dir=Path(args.out_dir),
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        kd_weight=args.kd_weight,
        value_weight=args.value_weight,
        max_train_records=args.max_records,
        max_validation_records=args.max_validation_records,
        seed=args.seed,
        trainable_modules=tuple(value.strip() for value in args.trainable_modules.split(",") if value.strip()),
        feature_version=args.feature_version,
    )


if __name__ == "__main__":
    main()
