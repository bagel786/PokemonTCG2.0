#!/usr/bin/env python3
"""Train B1/B2 schema-3 candidates over three deterministic seeds."""

from __future__ import annotations

import argparse
from collections import deque
import gzip
import hashlib
import heapq
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

import numpy as np
import torch
import torch.nn.functional as F

from training.lucario_data import deterministic_gzip_text, sha256_file
from training.train_bc import (
    PolicyNet,
    export_npz,
    iter_batches,
    load_npz_weights,
    masked_count_loss,
    move,
    policy_loss,
)


def stable_key(row: dict) -> str:
    value = f"{row.get('episode_id')}:{row.get('seat')}:{row.get('step')}"
    return hashlib.sha256(value.encode()).hexdigest()


def training_projection(row: dict) -> dict:
    """Drop raw observations and provenance fields unused by the BC loader."""
    keys = (
        "episode_id", "seat", "step", "action", "reward", "features",
        "sample_weight", "split", "team", "source", "source_date", "correction",
    )
    return {key: row[key] for key in keys if key in row}


def migrate_legacy_row(row: dict) -> dict:
    row = dict(row)
    features = dict(row["features"])
    if int(features.get("feature_version", 1)) != 2:
        raise ValueError("legacy rehearsal stream must be schema 2")
    options = []
    for option in features["options"]:
        option = dict(option)
        numeric = list(option["numeric"])
        if len(numeric) != 12:
            raise ValueError("legacy option does not have 12 numeric inputs")
        option["numeric"] = numeric + [0.0]
        options.append(option)
    features["options"] = options
    features["feature_version"] = 3
    row["features"] = features
    row["source"] = "legacy_winner_rehearsal"
    row["sample_weight"] = min(float(row.get("sample_weight", 1.0)), 1.0)
    return row


def assemble_family_data(
    corrected: Path,
    legacy_dir: Path,
    corrections: Path,
    output_dir: Path,
    recent_winner_cap: int = 200_000,
    legacy_rehearsal_cap: int = 20_000,
) -> dict[str, Path]:
    if recent_winner_cap <= 0 or legacy_rehearsal_cap < 0:
        raise ValueError("recent_winner_cap must be positive and legacy_rehearsal_cap cannot be negative")
    # Split files are assembled in ascending source-date order, so a bounded
    # deque retains the most recent demonstrations without materializing every
    # winning decision from the multi-million-row corrected corpus.
    winners: deque[dict] = deque(maxlen=recent_winner_cap)
    total_winners = 0
    with gzip.open(corrected, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if int(row.get("features", {}).get("feature_version", 0)) == 3 and float(row.get("reward", 0)) > 0:
                winners.append(training_projection(row))
                total_winners += 1
    if not winners:
        raise RuntimeError("corrected corpus contains no schema-3 winning demonstrations")
    winners = list(winners)
    legacy_cap = min(legacy_rehearsal_cap, len(winners) // 4)
    legacy_candidates: deque[dict] = deque(maxlen=legacy_cap)
    total_legacy_candidates = 0
    for path in sorted(legacy_dir.glob("*_decisions.jsonl.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                if int(row.get("features", {}).get("feature_version", 1)) == 2:
                    legacy_candidates.append(training_projection(row))
                    total_legacy_candidates += 1
    winner_rows = sorted(winners, key=stable_key)
    legacy_rows = sorted(legacy_candidates, key=stable_key)
    correction_rows = []
    if corrections.exists():
        with gzip.open(corrections, "rt", encoding="utf-8") as handle:
            correction_rows = [training_projection(json.loads(line)) for line in handle]
    if not correction_rows:
        raise RuntimeError("B2 requires a nonempty certified corrective-label corpus")

    output_dir.mkdir(parents=True, exist_ok=True)
    b1 = output_dir / "b1_train.jsonl.gz"
    b2 = output_dir / "b2_train.jsonl.gz"

    def base_rows():
        return heapq.merge(
            winner_rows,
            (migrate_legacy_row(row) for row in legacy_rows),
            key=stable_key,
        )

    with deterministic_gzip_text(b1) as handle:
        for row in base_rows():
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    # Keep corrections influential, but never let a tiny mined set dominate B2
    # simply because it can be repeated to one quarter of the corpus.
    max_replays_per_correction = 32
    correction_cap = min(
        max(1, (len(winners) + legacy_cap) // 3),
        len(correction_rows) * max_replays_per_correction,
    )
    repeated = []
    ordered_corrections = sorted(correction_rows, key=stable_key)
    while len(repeated) < correction_cap:
        repeated.extend(ordered_corrections)
    repeated = repeated[:correction_cap]
    with deterministic_gzip_text(b2) as handle:
        for row in heapq.merge(base_rows(), sorted(repeated, key=stable_key), key=stable_key):
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    manifest = {
        "recent_winning_decisions": len(winners),
        "total_winning_decisions_scanned": total_winners,
        "recent_winner_cap": recent_winner_cap,
        "recent_winners_truncated": total_winners > len(winners),
        "legacy_rehearsal_decisions": legacy_cap,
        "total_legacy_candidates_scanned": total_legacy_candidates,
        "legacy_candidates_truncated": total_legacy_candidates > len(legacy_candidates),
        "legacy_cap": legacy_cap,
        "configured_legacy_rehearsal_cap": legacy_rehearsal_cap,
        "certified_unique_corrections": len(correction_rows),
        "b2_correction_training_rows": len(repeated),
        "max_replays_per_correction": max_replays_per_correction,
        "b1_sha256": sha256_file(b1),
        "b2_sha256": sha256_file(b2),
    }
    (output_dir / "assembly_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"b1": b1, "b2": b2}


def option_kl(student_logits, teacher_logits, record_options) -> torch.Tensor:
    losses = []
    for start, end in record_options:
        if end > start:
            losses.append(F.kl_div(
                F.log_softmax(student_logits[start:end], dim=0),
                F.softmax(teacher_logits[start:end], dim=0),
                reduction="sum",
            ))
    return torch.stack(losses).mean() if losses else student_logits.sum() * 0


def train_one(
    family: str,
    seed: int,
    data: Path,
    validation: Path,
    anchor: Path,
    output_dir: Path,
    epochs: int,
    batch_size: int,
) -> dict:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    teacher = PolicyNet(3)
    student = PolicyNet(3)
    load_npz_weights(teacher, anchor)
    load_npz_weights(student, anchor)
    teacher.eval().to(device)
    student.to(device)
    for parameter in teacher.parameters():
        parameter.requires_grad = False
    for parameter in student.value.parameters():
        parameter.requires_grad = False
    optimizer = torch.optim.AdamW(
        [parameter for parameter in student.parameters() if parameter.requires_grad],
        lr=3e-5 if family == "b1" else 5e-5,
        weight_decay=1e-5,
    )
    kl_weight = 0.80 if family == "b1" else 0.70
    history = []
    for epoch in range(epochs):
        student.train()
        totals = {"loss": 0.0, "hard": 0.0, "kl": 0.0, "batches": 0}
        for batch in iter_batches([data], batch_size, 0, 0, validation=False, feature_version=3):
            batch = move(batch, device)
            student_logits, student_counts, _ = student(batch)
            with torch.no_grad():
                teacher_logits, teacher_counts, _ = teacher(batch)
            action_loss, _, _ = policy_loss(student_logits, batch)
            count_loss = masked_count_loss(student_counts, batch)
            hard = action_loss + 0.25 * count_loss
            distill = option_kl(student_logits, teacher_logits, batch["record_options"])
            distill += 0.25 * F.kl_div(
                F.log_softmax(student_counts, dim=1),
                F.softmax(teacher_counts, dim=1),
                reduction="batchmean",
            )
            loss = (1 - kl_weight) * hard + kl_weight * distill
            if not torch.isfinite(loss):
                raise FloatingPointError("non-finite recovery training loss")
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(student.parameters(), 1.0)
            optimizer.step()
            totals["loss"] += float(loss.detach())
            totals["hard"] += float(hard.detach())
            totals["kl"] += float(distill.detach())
            totals["batches"] += 1
        if not totals["batches"]:
            raise RuntimeError("no training batches matched schema 3")
        history.append({
            "epoch": epoch + 1,
            **{name: value / totals["batches"] for name, value in totals.items() if name != "batches"},
            "batches": totals["batches"],
        })
        print({"family": family, "seed": seed, **history[-1]}, flush=True)
    output = output_dir / family / f"seed_{seed}" / "policy_weights.npz"
    export_npz(student.cpu(), output)
    return {
        "family": family,
        "seed": seed,
        "output": str(output),
        "sha256": sha256_file(output),
        "anchor_sha256": sha256_file(anchor),
        "data_sha256": sha256_file(data),
        "validation_sha256": sha256_file(validation),
        "kl_weight": kl_weight,
        "value_head": "frozen_diagnostic_only",
        "history": history,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corrected-train", default="data/grim_daily_v3/splits/train.jsonl.gz")
    parser.add_argument("--validation", default="data/grim_daily_v3/splits/validation.jsonl.gz")
    parser.add_argument("--legacy-dir", default="data/daily_extracted")
    parser.add_argument("--corrections", default="artifacts/recovery_training/b2_corrections.jsonl.gz")
    parser.add_argument("--anchor", default="artifacts/recovery_schema3/d842_schema3_zero_init.npz")
    parser.add_argument("--output-dir", default="artifacts/recovery_training")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--recent-winner-cap", type=int, default=200_000)
    parser.add_argument("--legacy-rehearsal-cap", type=int, default=20_000)
    parser.add_argument("--seeds", default="20260807,20260808,20260809")
    parser.add_argument("--families", default="b1,b2")
    parser.add_argument("--assemble-only", action="store_true")
    parser.add_argument("--skip-assembly", action="store_true")
    args = parser.parse_args()
    if args.assemble_only and args.skip_assembly:
        parser.error("assemble-only and skip-assembly are mutually exclusive")
    families = [value.strip() for value in args.families.split(",") if value.strip()]
    if not families or any(family not in {"b1", "b2"} for family in families):
        parser.error("families must be a comma-separated subset of b1,b2")
    output_dir = Path(args.output_dir)
    if args.skip_assembly:
        data = {
            family: output_dir / "datasets" / f"{family}_train.jsonl.gz"
            for family in ("b1", "b2")
        }
        missing = [str(data[family]) for family in families if not data[family].exists()]
        if missing:
            raise FileNotFoundError(f"assembled recovery datasets are missing: {missing}")
    else:
        data = assemble_family_data(
            Path(args.corrected_train), Path(args.legacy_dir), Path(args.corrections),
            output_dir / "datasets", args.recent_winner_cap, args.legacy_rehearsal_cap,
        )
    if args.assemble_only:
        print(json.dumps({"assembled": {name: str(path) for name, path in data.items()}}))
        return 0
    reports = []
    for family in families:
        for seed in [int(value) for value in args.seeds.split(",")]:
            reports.append(train_one(
                family, seed, data[family], Path(args.validation), Path(args.anchor), output_dir,
                args.epochs, args.batch_size,
            ))
    manifest = {"created_unix": time.time(), "runs": reports}
    (output_dir / "training_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
