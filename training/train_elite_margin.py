#!/usr/bin/env python3
"""Train a narrow pairwise ranker on elite moves already present in A2's top three."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if (ROOT / "vendor").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

import numpy as np
import torch
from torch.nn import functional as F

from training.train_bc import PolicyNet, collate, export_npz, iter_batches, load_npz_weights, move
from training.train_v2_model import evaluate_model, log


A2_ERR_BASE_SHA256 = "b19871a9f1499c2460ae266e58194acab1d8c90b390fa5cf24ed94b9a2b6bda8"
A2_ERR_SEED = 20260814
A2_ERR_BATCH_SIZE = 256
A2_ERR_LR = 3e-5
A2_ERR_WEIGHT_DECAY = 1e-4
A2_ERR_GRADIENT_CLIP = 1.0
A2_ERR_EPOCHS = 3
A2_ERR_MARGIN = 0.20
A2_ERR_KL_WEIGHT = 1.0
A2_ERR_TRAINABLE = ("option_linear", "score")
A2_ERR_MUTABLE_ARRAYS = frozenset({"option_w", "option_b", "score_w", "score_b"})


def semantic_option_key(option: dict) -> tuple:
    return (
        int(option["option_type"]), int(option["context"]),
        int(option["source_card"]), int(option["target_card"]),
        int(option["attack_id"]), int(option["area"]), int(option["in_play_area"]),
        tuple(
            round(float(value), 6)
            for index, value in enumerate(option["numeric"])
            if index not in (9, 10, 11)
        ),
    )


def semantic_groups(rows: list[dict]) -> list[list[list[int]]]:
    result = []
    for row in rows:
        groups = {}
        for index, option in enumerate(row["features"]["options"]):
            groups.setdefault(semantic_option_key(option), []).append(index)
        result.append(list(groups.values()))
    return result


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


def a2_rejected_margin_loss(
    student_logits: torch.Tensor,
    teacher_logits: torch.Tensor,
    batch: dict,
    margin: float = A2_ERR_MARGIN,
) -> torch.Tensor:
    """Frozen ERR loss: elite label against exact A2's rejected top-1 action."""
    terms = []
    weights = []
    for record_index, (start, end) in enumerate(batch["record_options"]):
        actions = batch["record_actions"][record_index]
        if len(actions) != 1 or end - start < 2:
            raise ValueError("ERR correction batch contains a non-single or forced row")
        groups = batch.get("record_semantic_groups")
        if groups is None:
            raise ValueError("ERR correction batch is missing semantic equivalence groups")
        record_groups = groups[record_index]
        label = int(actions[0])
        rejected = int(torch.argmax(teacher_logits[start:end]).item())
        elite_group = next((group for group in record_groups if label in group), None)
        rejected_group = next((group for group in record_groups if rejected in group), None)
        if elite_group is None or rejected_group is None:
            raise ValueError("ERR semantic equivalence group does not cover the correction")
        if elite_group is rejected_group:
            raise ValueError("ERR correction no longer disagrees with exact A2 top-1")
        weight = batch["weights"][record_index]
        elite_indices = torch.tensor([start + value for value in elite_group], device=student_logits.device)
        rejected_indices = torch.tensor([start + value for value in rejected_group], device=student_logits.device)
        delta = torch.max(student_logits[elite_indices]) - torch.max(student_logits[rejected_indices])
        terms.append(F.softplus(float(margin) - delta) * weight)
        weights.append(weight)
    return torch.stack(terms).sum() / torch.stack(weights).sum().clamp_min(1e-6)


def unweighted_segmented_kl(student_logits: torch.Tensor, teacher_logits: torch.Tensor, batch: dict) -> torch.Tensor:
    terms = []
    for start, end in batch["record_options"]:
        if end > start:
            terms.append(F.kl_div(
                F.log_softmax(student_logits[start:end], dim=0),
                F.softmax(teacher_logits[start:end], dim=0),
                reduction="sum",
            ))
    return torch.stack(terms).mean() if terms else student_logits.sum() * 0.0


def row_key(row: dict) -> tuple[str, int, int]:
    return str(row["episode_id"]), int(row["seat"]), int(row["step"])


def shuffled_rows(path: Path, *, excluded: set[tuple[str, int, int]] | None = None, buffer_size: int = 20_000):
    buffer = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if excluded is not None and row_key(row) in excluded:
                continue
            buffer.append(row)
            if len(buffer) >= buffer_size:
                random.shuffle(buffer)
                yield from buffer
                buffer = []
    random.shuffle(buffer)
    yield from buffer


def take_rows(iterator, count: int) -> list[dict]:
    rows = []
    for _ in range(count):
        try:
            rows.append(next(iterator))
        except StopIteration as exc:
            raise RuntimeError("KL anchor stream exhausted before the correction epoch") from exc
    return rows


def frozen_array_audit(base: Path, candidate: Path) -> dict:
    with np.load(base, allow_pickle=False) as expected, np.load(candidate, allow_pickle=False) as actual:
        if set(expected.files) != set(actual.files):
            raise ValueError("candidate NPZ array set differs from exact A2")
        arrays = {}
        for name in expected.files:
            left, right = expected[name], actual[name]
            identical = left.dtype == right.dtype and left.shape == right.shape and left.tobytes() == right.tobytes()
            arrays[name] = identical
        frozen = {name: value for name, value in arrays.items() if name not in A2_ERR_MUTABLE_ARRAYS}
        return {
            "all_frozen_arrays_byte_identical": all(frozen.values()),
            "frozen_arrays": frozen,
            "mutable_arrays_changed": {name: not arrays[name] for name in sorted(A2_ERR_MUTABLE_ARRAYS)},
        }


def train_a2_err(args: argparse.Namespace) -> list[Path]:
    base = Path(args.base).resolve()
    if hashlib.sha256(base.read_bytes()).hexdigest() != A2_ERR_BASE_SHA256:
        raise ValueError("A2-ERR-1 base SHA-256 mismatch")
    corrections = Path(args.corrections).resolve()
    anchors = Path(args.anchor_data).resolve()
    rehearsal = Path(args.rehearsal_data).resolve()
    for required in (corrections, anchors, rehearsal):
        if not required.is_file():
            raise FileNotFoundError(required)

    random.seed(A2_ERR_SEED)
    np.random.seed(A2_ERR_SEED)
    torch.manual_seed(A2_ERR_SEED)
    torch.use_deterministic_algorithms(True)
    torch.set_num_threads(1)
    device = torch.device("cpu")
    output_dir = Path(args.out_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "training.log"
    log_path.write_text("", encoding="utf-8")

    correction_keys = {row_key(row) for row in shuffled_rows(corrections, buffer_size=1)}
    # Reset after the key scan: the only optimization RNG stream starts below.
    random.seed(A2_ERR_SEED)
    np.random.seed(A2_ERR_SEED)
    torch.manual_seed(A2_ERR_SEED)

    teacher = PolicyNet(2).to(device)
    student = PolicyNet(2).to(device)
    load_npz_weights(teacher, base)
    load_npz_weights(student, base)
    teacher.eval()
    for parameter in teacher.parameters():
        parameter.requires_grad = False
    for name, parameter in student.named_parameters():
        parameter.requires_grad = name.split(".", 1)[0] in A2_ERR_TRAINABLE
    trainable = [parameter for parameter in student.parameters() if parameter.requires_grad]
    optimizer = torch.optim.AdamW(trainable, lr=A2_ERR_LR, weight_decay=A2_ERR_WEIGHT_DECAY)
    history = []
    checkpoints = []
    correction_batch_size = A2_ERR_BATCH_SIZE // 2

    for epoch in range(1, A2_ERR_EPOCHS + 1):
        student.train()
        correction_iterator = iter(shuffled_rows(corrections))
        anchor_iterator = iter(shuffled_rows(anchors, excluded=correction_keys))
        rehearsal_iterator = iter(shuffled_rows(rehearsal))
        totals = Counter()
        while True:
            correction_rows = []
            for _ in range(correction_batch_size):
                try:
                    correction_rows.append(next(correction_iterator))
                except StopIteration:
                    break
            if not correction_rows:
                break
            side_count = len(correction_rows) // 2
            correction_batch = collate(correction_rows)
            correction_batch["record_semantic_groups"] = semantic_groups(correction_rows)
            correction_batch = move(correction_batch, device)
            anchor_batch = move(collate(take_rows(anchor_iterator, side_count)), device)
            rehearsal_batch = move(collate(take_rows(rehearsal_iterator, side_count)), device)

            student_correction, _, _ = student(correction_batch)
            student_anchor, _, _ = student(anchor_batch)
            student_rehearsal, _, _ = student(rehearsal_batch)
            with torch.no_grad():
                teacher_correction, _, _ = teacher(correction_batch)
                teacher_anchor, _, _ = teacher(anchor_batch)
                teacher_rehearsal, _, _ = teacher(rehearsal_batch)
            margin_loss = a2_rejected_margin_loss(
                student_correction, teacher_correction, correction_batch, A2_ERR_MARGIN
            )
            correction_kl = unweighted_segmented_kl(student_correction, teacher_correction, correction_batch)
            anchor_kl = unweighted_segmented_kl(student_anchor, teacher_anchor, anchor_batch)
            rehearsal_kl = unweighted_segmented_kl(student_rehearsal, teacher_rehearsal, rehearsal_batch)
            kl_loss = 0.50 * correction_kl + 0.25 * anchor_kl + 0.25 * rehearsal_kl
            loss = margin_loss + A2_ERR_KL_WEIGHT * kl_loss
            if not torch.isfinite(loss):
                raise FloatingPointError("non-finite A2-ERR-1 loss")
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(trainable, A2_ERR_GRADIENT_CLIP)
            optimizer.step()
            totals["batches"] += 1
            totals["correction_rows"] += len(correction_rows)
            totals["anchor_rows"] += side_count
            totals["rehearsal_rows"] += side_count
            totals["margin_loss"] += float(margin_loss.detach())
            totals["kl_loss"] += float(kl_loss.detach())

        checkpoint = output_dir / f"epoch_{epoch}" / "policy_weights.npz"
        export_npz(student, checkpoint)
        audit = frozen_array_audit(base, checkpoint)
        if not audit["all_frozen_arrays_byte_identical"]:
            raise RuntimeError(f"epoch {epoch} changed a frozen array")
        checkpoints.append(checkpoint)
        row = {
            "epoch": epoch,
            "batches": int(totals["batches"]),
            "correction_rows": int(totals["correction_rows"]),
            "anchor_rows": int(totals["anchor_rows"]),
            "rehearsal_rows": int(totals["rehearsal_rows"]),
            "margin_loss": totals["margin_loss"] / max(1, totals["batches"]),
            "kl_loss": totals["kl_loss"] / max(1, totals["batches"]),
            "checkpoint": str(checkpoint),
            "checkpoint_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
            "frozen_array_audit": audit,
        }
        history.append(row)
        log(json.dumps(row, sort_keys=True), log_path)

    summary = {
        "experiment": "A2-ERR-1",
        "mechanism": "exact_a2_top1_pairwise_margin_plus_frozen_a2_option_kl",
        "device": "cpu",
        "deterministic_algorithms": True,
        "base": str(base),
        "base_sha256": hashlib.sha256(base.read_bytes()).hexdigest(),
        "corrections": str(corrections),
        "corrections_sha256": hashlib.sha256(corrections.read_bytes()).hexdigest(),
        "anchor_data": str(anchors),
        "anchor_data_sha256": hashlib.sha256(anchors.read_bytes()).hexdigest(),
        "rehearsal_data": str(rehearsal),
        "rehearsal_data_sha256": hashlib.sha256(rehearsal.read_bytes()).hexdigest(),
        "seed": A2_ERR_SEED,
        "batch_size": A2_ERR_BATCH_SIZE,
        "batch_mass": {"corrections": 0.50, "qualified_kl_only": 0.25, "a2_rehearsal_kl_only": 0.25},
        "epochs": A2_ERR_EPOCHS,
        "learning_rate": A2_ERR_LR,
        "weight_decay": A2_ERR_WEIGHT_DECAY,
        "gradient_clip": A2_ERR_GRADIENT_CLIP,
        "margin": A2_ERR_MARGIN,
        "kl_weight": A2_ERR_KL_WEIGHT,
        "trainable_modules": list(A2_ERR_TRAINABLE),
        "checkpoint_selection": "none; evaluate epochs 1, 2, 3 and select earliest passing all offline gates",
        "history": history,
    }
    (output_dir / "training_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return checkpoints


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
    parser.add_argument("--a2-err-1", action="store_true")
    parser.add_argument("--base", required=True)
    parser.add_argument("--train-data")
    parser.add_argument("--val-data")
    parser.add_argument("--corrections")
    parser.add_argument("--anchor-data")
    parser.add_argument("--rehearsal-data")
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
    if args.a2_err_1:
        missing = [name for name in ("corrections", "anchor_data", "rehearsal_data") if not getattr(args, name)]
        if missing:
            parser.error(f"A2-ERR-1 requires: {', '.join(missing)}")
        outputs = train_a2_err(args)
        print("\n".join(map(str, outputs)))
        return 0
    if not args.train_data or not args.val_data:
        parser.error("ordinary elite margin training requires --train-data and --val-data")
    output = train(args)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
