#!/usr/bin/env python3
"""Benchmark a schema-5 NumPy policy on real replay feature rows."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

import numpy as np

from ptcg_ai.direct import NumpyDirectPolicyModel, NumpyRelationalDirectPolicyModel
from ptcg_ai.features import DecisionFeatures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--stream", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rows", type=int, default=500)
    args = parser.parse_args()
    with np.load(args.model, allow_pickle=False) as artifact:
        version = int(np.asarray(artifact["direct_model_version"]).item())
    model = (NumpyDirectPolicyModel(args.model) if version == 1
             else NumpyRelationalDirectPolicyModel(args.model) if version == 2
             else None)
    if model is None:
        raise RuntimeError(f"unsupported direct model version {version}")
    features = []
    with gzip.open(args.stream, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if int(row.get("features", {}).get("feature_version", -1)) != 5:
                raise RuntimeError("latency stream is not schema 5")
            features.append(DecisionFeatures.from_json(row["features"]))
            if len(features) >= args.rows:
                break
    if len(features) < min(100, args.rows):
        raise RuntimeError("insufficient real feature rows for latency benchmark")
    for value in features[:100]:
        model.predict(value)
    samples = []
    for value in features:
        started = time.perf_counter()
        logits, counts = model.predict(value)
        samples.append((time.perf_counter() - started) * 1000)
        if not np.isfinite(logits).all() or not np.isfinite(counts).all():
            raise RuntimeError("non-finite runtime output")
    digest = hashlib.sha256(args.model.read_bytes()).hexdigest().upper()
    result = {
        "status": "passed" if np.median(samples) < 30 and np.quantile(samples, .99) < 100 else "failed",
        "model_sha256": digest,
        "direct_model_version": version,
        "rows": len(samples),
        "median_ms": float(np.median(samples)),
        "p99_ms": float(np.quantile(samples, .99)),
        "max_ms": float(np.max(samples)),
        "thresholds": {"median_ms_below": 30, "p99_ms_below": 100},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
