#!/usr/bin/env python3
"""Evaluate every completed M0 seed on the untouched policy-identity holdout."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def evaluate(item: tuple[str, Path], output_root: Path) -> dict:
    label, model = item
    output = output_root / label / "identity_evaluation.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, str(ROOT / "scripts" / "evaluate_schema5_policy.py"),
        str(ROOT / "data" / "grim_breakthrough_v5" / "policy_identity_holdout.jsonl.gz"),
        "--direct", str(model), "--output", str(output), "--batch-size", "256",
    ]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=600)
    if result.returncode:
        return {"label": label, "model": str(model), "status": "failed", "error": result.stderr[-2000:]}
    report = json.loads(output.read_text(encoding="utf-8"))
    branching = report.get("strata", {}).get("category:branching", {})
    return {
        "label": label,
        "model": str(model.resolve()),
        "model_sha256": report["direct_model_sha256"],
        "status": "complete",
        "overall_agreement": report["overall"]["direct_complete_agreement"],
        "overall_uplift_points": report["overall"]["uplift_points"],
        "branching_agreement": branching.get("direct_complete_agreement"),
        "branching_uplift_points": branching.get("uplift_points"),
        "bootstrap_uplift_95_points": report["episode_bootstrap_uplift_95_points"],
        "report": str(output.resolve()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models-root", type=Path, default=ROOT / "artifacts" / "schema5_azure" / "candidate")
    parser.add_argument("--output-root", type=Path, default=ROOT / "artifacts" / "schema5_matrix_screen")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    models = sorted(args.models_root.glob("*/seed_*/direct.npz"))
    if len(models) != 60:
        raise RuntimeError(f"incomplete M0 candidate matrix: expected 60 models, found {len(models)}")
    items = [(f"{model.parent.parent.name}/{model.parent.name}", model) for model in models]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(lambda item: evaluate(item, args.output_root), items))
    complete = [row for row in rows if row["status"] == "complete"]
    if len(complete) != len(rows):
        raise RuntimeError("one or more M0 replay screens failed")
    ranked = sorted(complete, key=lambda row: float(row["branching_uplift_points"]), reverse=True)
    passes = [row for row in ranked if float(row["branching_uplift_points"]) >= 8.0]
    result = {
        "status": "passed" if passes else "failed",
        "gate": "branching complete-action uplift over R0 >= 8 points",
        "models": len(rows),
        "passing_models": len(passes),
        "best": ranked[0],
        "ranked": ranked,
    }
    args.output_root.mkdir(parents=True, exist_ok=True)
    (args.output_root / "matrix_screen.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: result[key] for key in ("status", "gate", "models", "passing_models", "best")}, indent=2))
    return 0 if passes else 2


if __name__ == "__main__":
    raise SystemExit(main())
