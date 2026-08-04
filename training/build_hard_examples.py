#!/usr/bin/env python3
"""Build a training-only, audited hard-example replay view."""

from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

import torch

from training.replay_refresh import (
    PolicyNet,
    _decision,
    auto_device,
    iter_split_rows,
    load_npz_weights,
    move,
    row_key,
    sha256_file,
)
from training.train_bc import collate


def hard_strata(row: dict) -> dict[str, str]:
    features = row["features"]
    return {
        "seat": str(int(row.get("seat", round(features["global"][2])))),
        "first_order": "first" if features["global"][3] >= 0.5 else "second",
        "team": str(row.get("team", "")),
        "context": str(features["options"][0]["context"] if features["options"] else -1),
    }


def balancing_weight(row: dict, counts: dict[str, Counter], total: int) -> float:
    strata = hard_strata(row)
    factors = []
    for dimension, value in strata.items():
        groups = max(1, len(counts[dimension]))
        target = total / groups
        observed = max(1, counts[dimension][value])
        ratio = target / observed
        if dimension in {"team", "context"}:
            ratio = math.sqrt(ratio)
        factors.append(max(0.5, min(3.0, ratio)))
    geometric = math.prod(factors) ** (1.0 / len(factors))
    priority = 2.0 if row["hard_priority"] == 2 else 1.25
    winner = 1.25 if float(row.get("reward", 0.0)) > 0 else 1.0
    return priority * winner * geometric


@torch.no_grad()
def build_hard_examples(
    *,
    fresh: str | Path,
    manifest: dict,
    baseline_model: str | Path,
    finalist_model: str | Path,
    output: str | Path,
    audit_output: str | Path,
    batch_size: int = 256,
    device_name: str = "auto",
    max_records: int = 0,
) -> dict:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    device = auto_device(device_name)
    models = []
    for path in (baseline_model, finalist_model):
        model = PolicyNet(manifest["feature_version"])
        load_npz_weights(model, path)
        models.append(model.eval().to(device))

    handle, temporary_name = tempfile.mkstemp(prefix="hard-unweighted-", suffix=".jsonl.gz", dir=output.parent)
    os.close(handle)
    temporary = Path(temporary_name)
    counts = defaultdict(Counter)
    summary = Counter()
    seen = set()
    batch_rows = []

    def consume(rows: list[dict], writer):
        batch = move(collate(rows), device)
        predictions = []
        for model in models:
            logits, count_logits, _ = model(batch)
            predictions.append([_decision(logits, count_logits, batch, index) for index in range(len(rows))])
        for index, row in enumerate(rows):
            elite = set(row["action"])
            baseline_wrong = set(predictions[0][index]) != elite
            finalist_wrong = set(predictions[1][index]) != elite
            summary["scored"] += 1
            if not baseline_wrong:
                continue
            row = dict(row)
            row.pop("sample_weight", None)
            row.pop("sample_source", None)
            row["hard_priority"] = 2 if finalist_wrong else 1
            summary[f"priority_{row['hard_priority']}"] += 1
            strata = hard_strata(row)
            for dimension, value in strata.items():
                counts[dimension][value] += 1
            writer.write(json.dumps(row, separators=(",", ":")) + "\n")

    try:
        with gzip.open(temporary, "wt", encoding="utf-8") as writer:
            for row in iter_split_rows(fresh, manifest, "train"):
                key = row_key(row)
                if key in seen:
                    summary["duplicates"] += 1
                    continue
                seen.add(key)
                batch_rows.append(row)
                if len(batch_rows) == batch_size:
                    consume(batch_rows, writer)
                    batch_rows = []
                if max_records and summary["scored"] + len(batch_rows) >= max_records:
                    break
            if batch_rows:
                consume(batch_rows, writer)

        total = summary["priority_1"] + summary["priority_2"]
        effective = defaultdict(Counter)
        with gzip.open(temporary, "rt", encoding="utf-8") as reader, gzip.open(output, "wt", encoding="utf-8") as writer:
            for line in reader:
                row = json.loads(line)
                row["sample_weight"] = balancing_weight(row, counts, total)
                for dimension, value in hard_strata(row).items():
                    effective[dimension][value] += row["sample_weight"]
                writer.write(json.dumps(row, separators=(",", ":")) + "\n")
    finally:
        temporary.unlink(missing_ok=True)

    audit = {
        "version": 1,
        "training_split_only": True,
        "baseline_model": str(baseline_model),
        "baseline_sha256": sha256_file(baseline_model),
        "finalist_model": str(finalist_model),
        "finalist_sha256": sha256_file(finalist_model),
        "fresh_sha256": sha256_file(fresh),
        "output": str(output),
        "output_sha256": sha256_file(output),
        "records": dict(summary),
        "raw_strata": {key: dict(sorted(value.items())) for key, value in counts.items()},
        "effective_weight_strata": {key: dict(sorted(value.items())) for key, value in effective.items()},
        "weight_policy": {
            "both_models_wrong": 2.0,
            "baseline_only_wrong": 1.25,
            "winner_multiplier": 1.25,
            "balance_dimensions": ["seat", "first_order", "team", "context"],
            "balance_cap": [0.5, 3.0],
        },
    }
    audit_path = Path(audit_output)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n")
    return audit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh", required=True)
    parser.add_argument("--split-manifest", required=True)
    parser.add_argument("--baseline-model", required=True)
    parser.add_argument("--finalist-model", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--audit-output", required=True)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda", "mps"), default="auto")
    parser.add_argument("--max-records", type=int, default=0)
    args = parser.parse_args()
    audit = build_hard_examples(
        fresh=args.fresh,
        manifest=json.loads(Path(args.split_manifest).read_text()),
        baseline_model=args.baseline_model,
        finalist_model=args.finalist_model,
        output=args.output,
        audit_output=args.audit_output,
        batch_size=args.batch_size,
        device_name=args.device,
        max_records=args.max_records,
    )
    print(json.dumps(audit, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
