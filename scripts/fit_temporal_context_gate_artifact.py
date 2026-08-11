#!/usr/bin/env python3
"""Fit the already-selected Aug-4 temporal context gate and freeze its arrays."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if (ROOT / "vendor").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

import numpy as np
import torch

from ptcg_ai.model import NumpyPolicyModel
from scripts.screen_temporal_context_gate import (
    DEFAULT_A2,
    DEFAULT_CONTINUATION,
    DEFAULT_OUTPUT,
    DEFAULT_TRAIN,
    fit_logistic,
    load_rows,
    sha256_file,
)


DEFAULT_GATE = ROOT / "artifacts/elite_policy_candidates/temporal_context_gate_screen/context_gate_weights.npz"
DEFAULT_MANIFEST = ROOT / "artifacts/elite_policy_candidates/temporal_context_gate_screen/context_gate_weights.manifest.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--a2", type=Path, default=DEFAULT_A2)
    parser.add_argument("--continuation", type=Path, default=DEFAULT_CONTINUATION)
    parser.add_argument("--train", type=Path, default=DEFAULT_TRAIN)
    parser.add_argument("--screen-report", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_GATE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()

    report = json.loads(args.screen_report.read_text(encoding="utf-8"))
    selected = report["selected_candidate"]
    if (
        selected["feature_set"] != "full_public_model"
        or int(selected["feature_count"]) != 858
        or float(selected["l2"]) != 0.1
        or float(selected["validation"]["threshold"]) != 0.5
    ):
        raise RuntimeError("screen selection differs from the locked gate recipe")

    torch.manual_seed(20260825)
    torch.set_num_threads(1)
    a2 = NumpyPolicyModel(args.a2)
    continuation = NumpyPolicyModel(args.continuation)
    _, disagreements, slices, duplicates = load_rows(
        [args.train], a2, continuation, allowed_dates={"2026-08-04"}
    )
    records = [record for record in disagreements if record.target >= 0]
    x = np.stack([record.features[:858] for record in records])
    y = np.asarray([record.target for record in records], dtype=np.float32)
    if slices["full_public_model"] != 858 or len(records) != 1992:
        raise RuntimeError(f"unexpected fit corpus: width={slices}, records={len(records)}")
    packed, mean, std = fit_logistic(x, y, 0.1)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.output,
        coef=packed[:-1].astype(np.float32),
        bias=np.asarray(packed[-1], dtype=np.float32),
        mean=mean.astype(np.float32),
        std=std.astype(np.float32),
        threshold=np.asarray(0.5, dtype=np.float32),
        schema_version=np.asarray(1, dtype=np.int64),
    )
    manifest = {
        "schema_version": 1,
        "kind": "a2_temporal_continuation_public_context_gate",
        "fit_date": "2026-08-04",
        "fit_decisive_disagreements": len(records),
        "fit_fixes": int(y.sum()),
        "fit_harms": int(len(y) - y.sum()),
        "duplicate_rows_skipped": duplicates,
        "feature_transform": "ptcg_ai.temporal_context_gate.public_gate_features",
        "feature_count": 858,
        "classifier": "L2-regularized linear logistic",
        "l2": 0.1,
        "threshold": 0.5,
        "seed": 20260825,
        "screen_report": {"path": str(args.screen_report), "sha256": sha256_file(args.screen_report)},
        "a2": {"path": str(args.a2), "sha256": sha256_file(args.a2)},
        "continuation": {"path": str(args.continuation), "sha256": sha256_file(args.continuation)},
        "train": {"path": str(args.train), "sha256": sha256_file(args.train)},
        "gate": {"path": str(args.output), "sha256": sha256_file(args.output)},
        "array_shapes": {
            "coef": [858], "bias": [], "mean": [858], "std": [858],
            "threshold": [], "schema_version": [],
        },
        "metadata_excluded_from_features": report["protocol"]["metadata_excluded_from_features"],
    }
    args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
