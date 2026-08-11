#!/usr/bin/env python3
"""Interpolate a fine-tuned policy back toward its anchor with an auditable manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def interpolate(anchor: Path, candidate: Path, alpha: float, output: Path) -> dict:
    if not 0.0 <= alpha <= 1.0:
        raise ValueError("alpha must be between zero and one")
    with np.load(anchor, allow_pickle=False) as left, np.load(candidate, allow_pickle=False) as right:
        if set(left.files) != set(right.files):
            raise ValueError("policy checkpoints contain different arrays")
        arrays = {}
        for name in sorted(left.files):
            a = np.asarray(left[name])
            b = np.asarray(right[name])
            if a.shape != b.shape:
                raise ValueError(f"shape mismatch for {name}: {a.shape} != {b.shape}")
            if name == "model_schema_version":
                if int(a.item()) != int(b.item()):
                    raise ValueError("model schema versions differ")
                arrays[name] = a.astype(np.int16)
            else:
                arrays[name] = ((1.0 - alpha) * a.astype(np.float32) + alpha * b.astype(np.float32)).astype(np.float16)
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output, **arrays)
    manifest = {
        "operation": "parameter_linear_interpolation",
        "alpha_candidate": alpha,
        "alpha_anchor": 1.0 - alpha,
        "anchor": str(anchor.resolve()),
        "anchor_sha256": sha256(anchor),
        "candidate": str(candidate.resolve()),
        "candidate_sha256": sha256(candidate),
        "output": str(output.resolve()),
        "output_sha256": sha256(output),
    }
    output.with_suffix(".json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anchor", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--alpha", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(interpolate(args.anchor, args.candidate, args.alpha, args.output), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
