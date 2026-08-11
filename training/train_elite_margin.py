#!/usr/bin/env python3
"""Train a narrow pairwise ranker on elite moves already present in A2's top three."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if (ROOT / "vendor").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

import numpy as np
import torch
from torch.nn import functional as F

from training.train_bc import PolicyNet, export_npz, iter_batches, load_npz_weights, move
from training.train_v2_model import evaluate_model, log


def segmented_kl(student_logits: torch.Tensor, teacher_logits: torch.Tensor, batch: dict) -> torch.Tensor:
    terms = []
    for record_index, (start, end) in enumerate(batch["record_options"]):
        if end <= start:
            continue
        term = F.kl_div(
            F.log_softmax(student_logits[start:end], dim=0),
            F.softmax(teacher_logits[start:end], dim=0),
            reduction="sum",
        )
        terms.append(term * batch["weights"][record_index])
    if not terms:
        return student_logits.sum() * 0.0
    return torch.stack(terms).sum() / batch["weights"].sum().clamp_min(1e-6)


def top3_margin_loss(
    student_logits: torch.Tensor,
    teacher_logits: torch.Tensor,
    batch: dict,
    margin: float,
) -> tuple[torch.Tensor, int]:
    """Pair the elite label against the student's strongest alternative.

    Only A2 top-three misses are changed.  The all-row KL term preserves the
    rest of the policy, avoiding the broad policy drift that hurt v2.
    """
    terms = []
    weights = []
    for record_index, (start, end) in enumerate(batch["record_options"]):
        actions = batch["record_actions"][record_index]
        if len(actions) != 1 or end - start < 2:
            continue
        label = int(actions[0])
        teacher_local = teacher_logits[start:end]
        teacher_ranked = torch.argsort(teacher_local, descending=True, stable=True)
        label_rank = int((teacher_ranked == label).nonzero(as_tuple=False)[0].item())
        if label_rank == 0 or label_rank >= 3:
            continue
        student_local = student_logits[start:end]
        mask = torch.ones(end - start, dtype=torch.bool, device=student_local.device)
        mask[label] = False
        strongest_other = student_local[mask].max()
        weight = batch["weights"][record_index]
        terms.append(F.softplus(strongest_other - student_local[label] + margin) * weight)
        weights.append(weight)
    if not terms:
        return student_logits.sum() * 0.0, 0
    return torch.stack(terms).sum() / torch.stack(weights).sum().clamp_min(1e-6), len(terms)


def train(args: argparse.Namespace) -> Path:
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    output_dir = Path(args.out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "training.log"
    log_path.write_text("", encoding="utf-8")

    student = PolicyNet(args.feature_version).to(device)
    teacher = PolicyNet(args.feature_version).to(device)
    load_npz_weights(student, args.base)
    load_npz_weights(teacher, args.base)
    teacher.eval()
    for parameter in teacher.parameters():
        parameter.requires_grad = False

    modules = tuple(value.strip() for value in args.trainable_modules.split(",") if value.strip())
    if modules:
        known = {name for name, _ in student.named_children()}
        unknown = set(modules) - known
        if unknown:
            raise ValueError(f"unknown trainable modules: {sorted(unknown)}")
        for name, parameter in student.named_parameters():
            parameter.requires_grad = name.split(".", 1)[0] in modules
    trainable = [parameter for parameter in student.parameters() if parameter.requires_grad]
    if not trainable:
        raise ValueError("no trainable parameters")

    validation_path = Path(args.val_data)
    pre_loss, pre_acc, _ = evaluate_model(
        student, validation_path, device, max_records=args.max_validation_records, batch_size=args.batch_size
    )
    output = output_dir / "policy_weights.npz"
    export_npz(student, output)
    best_acc = pre_acc
    history = []
    optimizer = torch.optim.AdamW(trainable, lr=args.lr, weight_decay=1e-4)
    log(f"Pre-validation top1={pre_acc:.4f}% loss={pre_loss:.6f}", log_path)

    for epoch in range(1, args.epochs + 1):
        student.train()
        batches = hard_records = records = 0
        running_margin = running_kl = 0.0
        for batch in iter_batches(
            [Path(args.train_data)],
            args.batch_size,
            max_records=args.max_records,
            validation=False,
            feature_version=args.feature_version,
        ):
            batch = move(batch, device)
            student_logits, _, _ = student(batch)
            with torch.no_grad():
                teacher_logits, _, _ = teacher(batch)
            margin_loss, hard = top3_margin_loss(student_logits, teacher_logits, batch, args.margin)
            kl_loss = segmented_kl(student_logits, teacher_logits, batch)
            loss = margin_loss + args.kd_weight * kl_loss
            if not torch.isfinite(loss):
                raise FloatingPointError("non-finite elite margin loss")
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(trainable, 1.0)
            optimizer.step()
            batches += 1
            hard_records += hard
            records += len(batch["record_options"])
            running_margin += float(margin_loss.item())
            running_kl += float(kl_loss.item())

        val_loss, val_acc, _ = evaluate_model(
            student,
            validation_path,
            device,
            max_records=args.max_validation_records,
            batch_size=args.batch_size,
        )
        row = {
            "epoch": epoch,
            "records": records,
            "top3_miss_records": hard_records,
            "margin_loss": running_margin / max(1, batches),
            "kl_loss": running_kl / max(1, batches),
            "validation_loss": val_loss,
            "validation_top1_percent": val_acc,
        }
        history.append(row)
        log(json.dumps(row, sort_keys=True), log_path)
        if val_acc > best_acc:
            best_acc = val_acc
            export_npz(student, output)

    summary = {
        "mechanism": "top3_pairwise_margin_with_all_state_a2_kl",
        "base": str(args.base),
        "base_sha256": hashlib.sha256(Path(args.base).read_bytes()).hexdigest(),
        "train_data": str(args.train_data),
        "validation_data": str(args.val_data),
        "seed": args.seed,
        "feature_version": args.feature_version,
        "epochs": args.epochs,
        "learning_rate": args.lr,
        "margin": args.margin,
        "kd_weight": args.kd_weight,
        "trainable_modules": list(modules) if modules else "all",
        "pre_validation_top1_percent": pre_acc,
        "best_validation_top1_percent": best_acc,
        "history": history,
        "output": str(output),
        "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }
    (output_dir / "training_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--train-data", required=True)
    parser.add_argument("--val-data", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--lr", type=float, default=3e-5)
    parser.add_argument("--margin", type=float, default=0.20)
    parser.add_argument("--kd-weight", type=float, default=0.50)
    parser.add_argument("--seed", type=int, default=20260813)
    parser.add_argument("--feature-version", type=int, default=2, choices=(2, 3, 4, 5))
    parser.add_argument("--trainable-modules", default="")
    parser.add_argument("--max-records", type=int, default=0)
    parser.add_argument("--max-validation-records", type=int, default=0)
    args = parser.parse_args()
    output = train(args)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
