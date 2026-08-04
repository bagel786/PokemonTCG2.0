#!/usr/bin/env python3
"""Train one resumable hard-example Grimmsnarl candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from training.replay_refresh import (
    _verify_control,
    evaluate_model_pair,
    heldout_gate,
    load_team_weights,
    sha256_file,
    train_candidate,
)


TRAINABLE = (
    "context_embedding",
    "global_linear",
    "numeric_linear",
    "option_linear",
    "score",
    "count",
    "value",
)
REPRESENTATION = {"context_embedding", "global_linear", "numeric_linear"}


def write_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def run_candidate(args: argparse.Namespace) -> dict:
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    final_path = output_dir / "candidate.json"
    if args.resume and final_path.exists():
        result = json.loads(final_path.read_text())
        if sha256_file(result["training"]["output"]) != result["training"]["sha256"]:
            raise ValueError("resume candidate hash mismatch")
        return result

    control = Path(args.control_model).resolve()
    anchor = Path(args.anchor_model).resolve()
    fresh = Path(args.fresh).resolve()
    rehearsal = Path(args.rehearsal).resolve()
    hard = Path(args.hard).resolve()
    _verify_control(Path(args.control_archive).resolve(), control, Path(args.deck).resolve())
    manifest = json.loads(Path(args.split_manifest).read_text())
    team_weights, _ = load_team_weights(args.team_ranks)
    module_lrs = {name: args.representation_learning_rate for name in REPRESENTATION}
    module_lrs.update({name: args.head_learning_rate for name in set(TRAINABLE) - REPRESENTATION})
    training_path = output_dir / "training_result.json"
    if args.resume and training_path.exists():
        training = json.loads(training_path.read_text())
        if sha256_file(training["output"]) != training["sha256"]:
            raise ValueError("resume training hash mismatch")
    else:
        training = train_candidate(
            control_model=control,
            initial_model=anchor,
            fresh_path=fresh,
            rehearsal_path=rehearsal,
            hard_path=hard,
            source_weights={"hard": 0.50, "fresh": 0.25, "rehearsal": 0.25},
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
            fresh_weight=0.75,
            distill_weight=args.distill_weight,
            trainable_modules=TRAINABLE,
            team_weights=team_weights,
            device_name=args.device,
            max_train_records=args.max_train_records,
            max_validation_records=args.max_evaluation_records,
            shuffle_buffer=args.shuffle_buffer,
        )
        write_json(training_path, training)

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
        "name": f"{args.anchor_name}_seed{args.seed}",
        "recommendation_only": True,
        "package_created": False,
        "submitted": False,
        "anchor": {"name": args.anchor_name, "path": str(anchor), "sha256": sha256_file(anchor)},
        "hard_examples": {"path": str(hard), "sha256": sha256_file(hard)},
        "training": training,
        "decision_reports": reports,
        "heldout_gate": heldout_gate(reports),
    }
    write_json(final_path, result)
    return result


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--control-archive", default="grimmsnarl_5k_reference.tar.gz")
    result.add_argument("--control-model", default="artifacts/grimmsnarl_5k_reference.npz")
    result.add_argument("--deck", default="freshstart/decklists/grimmsnarl_marnie.deck.csv")
    result.add_argument("--anchor-model", required=True)
    result.add_argument("--anchor-name", required=True)
    result.add_argument("--fresh", default="data/processed/elite-2026-07-30-31-v2ctl.jsonl.gz")
    result.add_argument("--rehearsal", default="data/processed/elite-2026-07-28-v2ctl.jsonl.gz")
    result.add_argument("--hard", required=True)
    result.add_argument("--split-manifest", required=True)
    result.add_argument("--team-ranks", default="data/top_teams.txt")
    result.add_argument("--output-dir", required=True)
    result.add_argument("--seed", type=int, required=True)
    result.add_argument("--head-learning-rate", type=float, default=1e-4)
    result.add_argument("--representation-learning-rate", type=float, default=1e-5)
    result.add_argument("--distill-weight", type=float, default=0.50)
    result.add_argument("--epoch-records", type=int, default=572_904)
    result.add_argument("--batch-size", type=int, default=256)
    result.add_argument("--epochs", type=int, default=3)
    result.add_argument("--patience", type=int, default=1)
    result.add_argument("--device", choices=("auto", "cpu", "cuda", "mps"), default="cpu")
    result.add_argument("--shuffle-buffer", type=int, default=20_000)
    result.add_argument("--max-train-records", type=int, default=0)
    result.add_argument("--max-evaluation-records", type=int, default=0)
    result.add_argument("--resume", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    result = run_candidate(args)
    print(json.dumps({
        "name": result["name"],
        "heldout_gate": result["heldout_gate"],
        "output": result["training"]["output"],
        "recommendation_only": True,
        "package_created": False,
        "submitted": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
