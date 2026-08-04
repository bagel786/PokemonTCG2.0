#!/usr/bin/env python3
"""Train one Candidate B supervised replay-refresh checkpoint.

This is experiment-only.  It starts from the exact frozen d842 5k model and
cannot package or submit a Kaggle agent.  Recent elite wins are the improvement
labels; historical elite data and exact-checkpoint ladder play are separately
weighted anti-forgetting sources.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from training.replay_refresh import (
    DEFAULT_TRAINABLE_MODULES,
    _verify_control,
    evaluate_model_pair,
    heldout_gate,
    load_team_weights,
    sha256_file,
    train_candidate,
)


REPRESENTATION_MODULES = ("context_embedding", "global_linear", "numeric_linear")
EXPECTED_CONTROL_SHA256 = "d842f85abfc44af9f41979f91795e22c92c179b62e04d5a0a2f9c734e70af1c3"


def candidate_b_decision_gate(reports: dict[str, dict]) -> dict:
    """Gate elite generalization and bounded drift from d842 ladder behavior.

    The temporal set is self-labeled by d842, so its baseline exact rate is
    necessarily 1.0.  It is a retention/drift audit, not another elite target.
    """
    reasons = []
    elite = reports["team_holdout"]
    if any(elite["policy_errors"].values()):
        reasons.append("team_holdout: policy errors")
    for metric in ("exact_rate", "count_accuracy"):
        if elite["delta"][metric] < -0.0025:
            reasons.append(f"team_holdout: {metric} delta {elite['delta'][metric]:.6f}")

    temporal = reports["temporal"]
    if any(temporal["policy_errors"].values()):
        reasons.append("temporal: policy errors")
    if temporal["delta"]["exact_rate"] < -0.04:
        reasons.append(f"temporal: exact drift {temporal['delta']['exact_rate']:.6f}")
    if temporal["delta"]["count_accuracy"] < -0.005:
        reasons.append(f"temporal: count drift {temporal['delta']['count_accuracy']:.6f}")
    for grouping in ("by_seat", "by_first_order"):
        for key, baseline in temporal[grouping]["baseline"].items():
            candidate = temporal[grouping]["candidate"][key]
            delta = candidate["exact_rate"] - baseline["exact_rate"]
            if delta < -0.04:
                reasons.append(f"temporal: {grouping} {key} exact drift {delta:.6f}")
    for context, baseline in temporal["by_context"]["baseline"].items():
        if baseline["records"] < 500:
            continue
        delta = temporal["by_context"]["candidate"][context]["exact_rate"] - baseline["exact_rate"]
        if delta < -0.05:
            reasons.append(f"temporal: context {context} exact drift {delta:.6f}")
    return {
        "passed": not reasons,
        "reasons": reasons,
        "semantics": {
            "team_holdout": "elite non-regression",
            "temporal": "bounded drift from self-labeled d842 ladder behavior",
            "temporal_limits": {"overall_and_seat_exact": 0.04, "large_context_exact": 0.05, "count": 0.005},
        },
    }


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def parameter_delta(before_path: Path, after_path: Path) -> dict:
    before = np.load(before_path)
    after = np.load(after_path)
    changed = []
    squared_delta = 0.0
    squared_base = 0.0
    maximum = 0.0
    for name in before.files:
        left = before[name].astype(np.float64)
        right = after[name].astype(np.float64)
        delta = right - left
        norm = float(np.linalg.norm(delta.ravel()))
        if norm:
            changed.append({"name": name, "l2": norm, "max_abs": float(np.max(np.abs(delta)))})
        squared_delta += float(np.sum(delta * delta))
        squared_base += float(np.sum(left * left))
        maximum = max(maximum, float(np.max(np.abs(delta))))
    return {
        "changed_arrays": len(changed),
        "relative_l2": squared_delta**0.5 / max(1e-12, squared_base**0.5),
        "max_abs": maximum,
        "arrays": changed,
    }


def run(args: argparse.Namespace) -> dict:
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    final_path = output_dir / "candidate.json"
    if final_path.exists() and args.resume:
        result = json.loads(final_path.read_text())
        if sha256_file(result["training"]["output"]) != result["training"]["sha256"]:
            raise RuntimeError("resumed Candidate B checkpoint hash mismatch")
        return result

    control = Path(args.control_model).resolve()
    anchor = Path(args.anchor_model).resolve()
    fresh = Path(args.fresh).resolve()
    historical = Path(args.historical).resolve()
    own = Path(args.own_rehearsal).resolve()
    if sha256_file(anchor) != EXPECTED_CONTROL_SHA256:
        raise RuntimeError("Candidate B anchor must be the original d842 5k checkpoint")
    verification = _verify_control(Path(args.control_archive).resolve(), control, Path(args.deck).resolve())
    manifest = json.loads(Path(args.split_manifest).read_text())
    if manifest["inputs"]["model"]["sha256"] != EXPECTED_CONTROL_SHA256:
        raise RuntimeError("split manifest was not built for the d842 checkpoint")

    team_weights, _ = load_team_weights(args.team_ranks)
    trainable = list(DEFAULT_TRAINABLE_MODULES)
    module_lrs = {}
    if args.train_representation:
        trainable = [*REPRESENTATION_MODULES, *trainable]
        module_lrs.update({name: args.representation_learning_rate for name in REPRESENTATION_MODULES})
    module_lrs.update({name: args.head_learning_rate for name in DEFAULT_TRAINABLE_MODULES})
    weights = {
        "fresh": args.fresh_weight,
        "rehearsal": args.historical_weight,
        "hard": args.own_weight,
    }
    if abs(sum(weights.values()) - 1.0) > 1e-9:
        raise ValueError("fresh, historical, and own source weights must sum to one")

    training = train_candidate(
        control_model=control,
        initial_model=anchor,
        fresh_path=fresh,
        rehearsal_path=historical,
        hard_path=own,
        source_weights=weights,
        epoch_records=args.epoch_records,
        manifest=manifest,
        output=output_dir / "policy_weights.npz",
        log_path=output_dir / "training.jsonl",
        learning_rate=args.head_learning_rate,
        module_learning_rates=module_lrs,
        seed=args.seed,
        batch_size=args.batch_size,
        epochs=args.epochs,
        patience=args.patience,
        fresh_weight=args.fresh_weight,
        distill_weight=args.distill_weight,
        trainable_modules=tuple(trainable),
        team_weights=team_weights,
        device_name=args.device,
        max_train_records=0,
        max_validation_records=args.max_evaluation_records,
        shuffle_buffer=args.shuffle_buffer,
    )
    reports = {
        split: evaluate_model_pair(
            control,
            training["output"],
            fresh,
            manifest,
            split,
            args.batch_size,
            args.device,
            args.max_evaluation_records,
        )
        for split in ("internal_validation", "team_holdout", "temporal")
    }
    result = {
        "version": 1,
        "name": args.name,
        "experiment_only": True,
        "package_created": False,
        "submitted": False,
        "anchor": {"path": str(anchor), "sha256": sha256_file(anchor)},
        "inputs": {
            "fresh_elite": {"path": str(fresh), "sha256": sha256_file(fresh)},
            "historical_elite": {"path": str(historical), "sha256": sha256_file(historical)},
            "own_5k_rehearsal": {"path": str(own), "sha256": sha256_file(own)},
            "split_manifest": {
                "path": str(Path(args.split_manifest).resolve()),
                "sha256": sha256_file(args.split_manifest),
            },
        },
        "configuration": {
            "source_weights": weights,
            "trainable_modules": trainable,
            "module_learning_rates": module_lrs,
            "distill_weight": args.distill_weight,
            "epoch_records": args.epoch_records,
            "epochs": args.epochs,
            "seed": args.seed,
        },
        "control_verification": verification,
        "training": training,
        "parameter_delta": parameter_delta(anchor, Path(training["output"])),
        "decision_reports": reports,
        "heldout_gate": candidate_b_decision_gate(reports),
        "generic_elite_gate_not_applicable": heldout_gate(reports),
    }
    write_json(final_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--control-archive", default="grimmsnarl_5k_reference.tar.gz")
    parser.add_argument("--control-model", default="artifacts/grimmsnarl_5k_reference.npz")
    parser.add_argument("--anchor-model", default="artifacts/overnight_grim_20260730/grim_selected.npz")
    parser.add_argument("--deck", default="freshstart/decklists/grimmsnarl_marnie.deck.csv")
    parser.add_argument("--fresh", default="artifacts/candidate_b_20260804/refresh_data/fresh_train_and_holdouts.jsonl.gz")
    parser.add_argument("--split-manifest", default="artifacts/candidate_b_20260804/refresh_data/split_manifest.json")
    parser.add_argument(
        "--historical",
        default="artifacts/candidate_b_20260804/refresh_data/historical_exact_rehearsal.jsonl.gz",
    )
    parser.add_argument("--own-rehearsal", default="artifacts/candidate_b_20260804/data/own_5k_rehearsal.jsonl.gz")
    parser.add_argument("--team-ranks", default="data/top_teams.txt")
    parser.add_argument("--fresh-weight", type=float, default=0.55)
    parser.add_argument("--historical-weight", type=float, default=0.30)
    parser.add_argument("--own-weight", type=float, default=0.15)
    parser.add_argument("--head-learning-rate", type=float, default=3e-5)
    parser.add_argument("--representation-learning-rate", type=float, default=1e-5)
    parser.add_argument("--train-representation", action="store_true")
    parser.add_argument("--distill-weight", type=float, default=0.75)
    parser.add_argument("--epoch-records", type=int, default=300_000)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--patience", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--shuffle-buffer", type=int, default=20_000)
    parser.add_argument("--max-evaluation-records", type=int, default=0)
    parser.add_argument("--seed", type=int, default=20260804)
    parser.add_argument("--device", choices=("auto", "cpu", "mps", "cuda"), default="cpu")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    result = run(args)
    print(json.dumps({
        "name": result["name"],
        "checkpoint": result["training"]["output"],
        "heldout_gate": result["heldout_gate"],
        "package_created": False,
        "submitted": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
