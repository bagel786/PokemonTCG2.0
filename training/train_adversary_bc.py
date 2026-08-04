#!/usr/bin/env python3
"""Train audited specialist BC seeds without claiming gameplay strength.

This is a generic adversary bootstrap stage.  It trains fresh and optionally
initialized policies on one exact-deck replay view, evaluates disjoint replay
splits, and emits every fidelity-eligible checkpoint for downstream game
qualification.  Imitation metrics never select or qualify the final opponent.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from training.azure_guard import enforce_azure_workload  # noqa: E402
from training.lucario_data import sha256_file  # noqa: E402


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def split_counts(path: str | Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            split = str(json.loads(line).get("split", "legacy"))
            counts[split] = counts.get(split, 0) + 1
    return counts


def candidate_specifications(seed: int, initial_model: str | Path | None) -> list[dict]:
    result = [
        {"name": f"fresh_seed{seed + offset}", "seed": seed + offset, "initial_model": None}
        for offset in range(3)
    ]
    if initial_model:
        result.extend(
            {
                "name": f"initialized_seed{seed + offset}",
                "seed": seed + offset,
                "initial_model": str(initial_model),
            }
            for offset in range(3)
        )
    return result


def fidelity_gate(reports: dict[str, dict]) -> dict:
    """Reject corrupt/unsupported policies, not merely imperfect imitators."""
    checks = {
        "validation_records": reports["validation"]["records"] >= 100,
        "validation_count": reports["validation"]["count_accuracy"] >= 0.90,
        "validation_top3": reports["validation"]["single_top3"] >= 0.60,
        "unseen_present": reports["unseen_team"]["records"] > 0,
        "temporal_present": reports["temporal"]["records"] > 0,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "purpose": "fidelity_filter_only_gameplay_strength_unproven",
    }


def evaluate_imitation(model: Path, shard: Path, required_card: int, split: str, output: Path) -> dict:
    command = [
        sys.executable,
        str(ROOT / "training/evaluate_imitation.py"),
        str(shard),
        "--model", str(model),
        "--require-card", str(required_card),
        "--split", split,
        "--output", str(output),
    ]
    subprocess.run(command, cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    return json.loads(output.read_text())["overall"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard", required=True)
    parser.add_argument("--required-card", required=True, type=int)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--initial-model", default="")
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--seed", type=int, default=20260803)
    parser.add_argument("--allow-local-smoke", action="store_true")
    args = parser.parse_args()

    shard = Path(args.shard).resolve()
    if not shard.exists():
        parser.error(f"missing audited replay shard: {shard}")
    initial = Path(args.initial_model).resolve() if args.initial_model else None
    if initial is not None and not initial.exists():
        parser.error(f"missing initialization checkpoint: {initial}")
    counts = split_counts(shard)
    for required in ("train", "validation", "unseen_team", "temporal"):
        if not counts.get(required):
            parser.error(f"audited shard has no {required!r} records")
    execution_host = enforce_azure_workload(
        allow_local_smoke=args.allow_local_smoke,
        workload_size=counts["train"],
    )

    output_dir = Path(args.output_dir).resolve()
    candidates = []
    for specification in candidate_specifications(args.seed, initial):
        candidate_dir = output_dir / specification["name"]
        model = candidate_dir / "policy_weights.npz"
        log_path = candidate_dir / "train.log"
        command = [
            sys.executable,
            str(ROOT / "training/train_bc.py"),
            str(shard),
            "--output", str(model),
            "--epochs", str(args.epochs),
            "--batch-size", str(args.batch_size),
            "--feature-version", "2",
            "--require-card", str(args.required_card),
            "--seed", str(specification["seed"]),
        ]
        if specification["initial_model"]:
            command.extend(["--initial-model", specification["initial_model"]])
        result = subprocess.run(command, cwd=ROOT, check=True, text=True, capture_output=True)
        candidate_dir.mkdir(parents=True, exist_ok=True)
        log_path.write_text(result.stdout + result.stderr)
        reports = {
            split: evaluate_imitation(
                model, shard, args.required_card, split, candidate_dir / f"{split}.json"
            )
            for split in ("validation", "unseen_team", "temporal")
        }
        candidates.append({
            **specification,
            "model": str(model),
            "sha256": sha256_file(model),
            "imitation": reports,
            "fidelity_gate": fidelity_gate(reports),
            "gameplay_strength": "unproven_requires_game_qualification",
        })

    eligible = [candidate for candidate in candidates if candidate["fidelity_gate"]["passed"]]
    report = {
        "version": 1,
        "kind": "specialist_adversary_bc_candidates",
        "execution_host": execution_host,
        "source": {"path": str(shard), "sha256": sha256_file(shard), "split_counts": counts},
        "required_card": args.required_card,
        "candidates": candidates,
        "eligible_models": [candidate["model"] for candidate in eligible],
        "selection_rule": "downstream_game_qualification_only",
        "qualified": False,
        "grim_training_started": False,
        "package_created": False,
        "submitted": False,
    }
    write_json(output_dir / "candidate_manifest.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
