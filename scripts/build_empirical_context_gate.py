#!/usr/bin/env python3
"""Build a tiny outcome-grounded context/order gate for A2 vs temporal."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "artifacts/emergency_strength_sprint/temporal_single_interventions/manifest.json"

FEATURE_COUNT = 858
CONFIDENCE_COUNT = 21
GLOBAL_COUNT = 118
CONTEXT_OFFSET = CONFIDENCE_COUNT + GLOBAL_COUNT
ACTUAL_FIRST_INDEX = CONFIDENCE_COUNT + 3


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(output: Path, contexts: list[int], actual_order: str, source: Path) -> dict:
    if not contexts or any(not 0 <= value < 64 for value in contexts):
        raise ValueError("contexts must be a non-empty subset of 0..63")
    if len(set(contexts)) != len(contexts):
        raise ValueError("contexts must be unique")
    if actual_order not in {"both", "first", "second"}:
        raise ValueError("actual_order must be both, first, or second")
    source_manifest = json.loads(source.read_text(encoding="utf-8"))
    if source_manifest.get("summary", {}).get("policy_errors") != {
        "baseline_hero": 0,
        "baseline_opponent": 0,
        "intervention_hero": 0,
        "intervention_opponent": 0,
        "proposal": 0,
    }:
        raise ValueError("source intervention corpus contains policy errors")

    coef = np.zeros(FEATURE_COUNT, dtype=np.float32)
    for context in contexts:
        coef[CONTEXT_OFFSET + context] = 2.0
    if actual_order == "both":
        bias = -1.0
    elif actual_order == "first":
        coef[ACTUAL_FIRST_INDEX] = 2.0
        bias = -3.0
    else:
        coef[ACTUAL_FIRST_INDEX] = -2.0
        bias = -1.0

    output.mkdir(parents=True, exist_ok=False)
    gate = output / "context_gate_weights.npz"
    np.savez_compressed(
        gate,
        coef=coef,
        bias=np.asarray(bias, dtype=np.float32),
        mean=np.zeros(FEATURE_COUNT, dtype=np.float32),
        std=np.ones(FEATURE_COUNT, dtype=np.float32),
        threshold=np.asarray(0.5, dtype=np.float32),
        schema_version=np.asarray(1, dtype=np.int64),
    )
    selected_candidate = {
        "kind": "outcome_grounded_context_order_gate",
        "contexts": sorted(contexts),
        "actual_order": actual_order,
        "feature_count": FEATURE_COUNT,
        "context_offset": CONTEXT_OFFSET,
        "actual_first_feature_index": ACTUAL_FIRST_INDEX,
        "selection_source": str(source.resolve()),
    }
    report = {
        "schema_version": 1,
        "selected_candidate": selected_candidate,
        "source_interventions": {
            "path": str(source.resolve()),
            "sha256": sha256_file(source),
            "rows_sha256": source_manifest["rows_sha256"],
            "complete": source_manifest["summary"]["status"].get("complete", 0),
        },
        "warning": "Selected on intervention data; requires selection-independent gameplay.",
    }
    gate_manifest = {
        "schema_version": 1,
        "gate": str(gate.resolve()),
        "gate_sha256": sha256_file(gate),
        "selected_candidate": selected_candidate,
        "runtime_private_information": False,
        "uploaded": False,
    }
    (output / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output / "context_gate_weights.manifest.json").write_text(
        json.dumps(gate_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return gate_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--contexts", type=int, nargs="+", required=True)
    parser.add_argument("--actual-order", choices=("both", "first", "second"), default="both")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args()
    result = build(args.output, args.contexts, args.actual_order, args.source)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
