#!/usr/bin/env python3
"""Train the missing blind-encoder/same-data cell of the 2x2 ablation.

The source corpus is the frozen identity-aware corpus.  This script makes one
deterministic transformation only: for ordinary PLAY options whose raw legal
option has no area, ``source_card`` is set to zero.  It then invokes the exact
EXP23 training function and realized settings (including the historical
``fresh_weight=.999`` rounding behavior, which emits no rehearsal examples).
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
PLAY = 7


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_tree(path: Path) -> str:
    """Match the deterministic package-tree convention used by the evaluator."""
    digest = hashlib.sha256()
    children = sorted(
        child for child in path.rglob("*")
        if child.is_file() and "__pycache__" not in child.parts and child.suffix != ".pyc"
    )
    for child in children:
        relative = child.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256_file(child)))
    return digest.hexdigest()


def git_commit() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def ordinary_play_indices(row: dict) -> list[int]:
    legal = row.get("legal_options") or []
    indices = []
    for index, option in enumerate(row["features"]["options"]):
        raw = legal[index] if index < len(legal) else {}
        if int(option["option_type"]) == PLAY and raw.get("area") is None:
            indices.append(index)
    return indices


def derive_blind(source: Path, destination: Path) -> dict:
    rows = options = changed = already_zero = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(source, "rt", encoding="utf-8") as src, destination.open("wb") as raw_out:
        compressed = gzip.GzipFile(fileobj=raw_out, mode="wb", mtime=0)
        out = io.TextIOWrapper(compressed, encoding="utf-8")
        for line in src:
            row = json.loads(line)
            rows += 1
            for index in ordinary_play_indices(row):
                options += 1
                option = row["features"]["options"][index]
                previous = int(option.get("source_card", 0) or 0)
                changed += int(previous != 0)
                already_zero += int(previous == 0)
                option["source_card"] = 0
            out.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
        out.flush()
        out.close()
    return {
        "rows": rows,
        "ordinary_play_options": options,
        "changed_nonzero_to_zero": changed,
        "already_zero": already_zero,
        "source_sha256": sha256_file(source),
        "blind_sha256": sha256_file(destination),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path,
        default=ROOT / "artifacts/final_sprint/identity_train/merged_decisions.jsonl.gz",
    )
    parser.add_argument(
        "--manifest", type=Path,
        default=ROOT / "artifacts/final_sprint/identity_train/train_manifest.json",
    )
    parser.add_argument(
        "--control-model", type=Path,
        default=ROOT / "artifacts/grim_damage_conversion/winner/extracted/policy_weights.npz",
    )
    parser.add_argument(
        "--control-package", type=Path,
        default=ROOT / "artifacts/grim_damage_conversion/winner/extracted",
    )
    parser.add_argument(
        "--work-dir", type=Path, default=ROOT / "artifacts/paper_ablation",
    )
    parser.add_argument(
        "--report", type=Path, default=ROOT / "paper/data/ablation/training_report.json",
    )
    return parser.parse_args()


def main() -> int:
    from training.replay_refresh import DEFAULT_TRAINABLE_MODULES, train_candidate

    args = parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    blind_corpus = args.work_dir / "blind_merged_decisions.jsonl.gz"
    model = args.work_dir / "blind_heads_1e4.npz"
    log = args.work_dir / "train_blind.log"
    package = args.work_dir / "blind_trained_package"
    derivation = derive_blind(args.source, blind_corpus)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    training = train_candidate(
        control_model=args.control_model,
        fresh_path=blind_corpus,
        rehearsal_path=blind_corpus,
        manifest=manifest,
        output=model,
        log_path=log,
        learning_rate=1e-4,
        seed=20260816,
        batch_size=256,
        epochs=3,
        patience=3,
        fresh_weight=0.999,
        distill_weight=0.5,
        trainable_modules=DEFAULT_TRAINABLE_MODULES,
        team_weights={},
        device_name="cpu",
        max_train_records=0,
        max_validation_records=0,
        initial_model=args.control_model,
        module_learning_rates=None,
    )
    if package.exists():
        shutil.rmtree(package)
    shutil.copytree(args.control_package, package)
    policy_paths = [
        package / "policy_weights.npz",
        package / "policy_first.npz",
        package / "policy_second.npz",
    ]
    for path in policy_paths:
        shutil.copy2(model, path)
    model_hashes = {path.name: sha256_file(path) for path in policy_paths}
    if len(set(model_hashes.values())) != 1:
        raise AssertionError("ablation package policy files are not byte-identical")
    report = {
        "schema_version": 1,
        "cell": "blind_encoder_same_training",
        "frozen_protocol_commit": git_commit(),
        "derivation": derivation,
        "source_manifest": str(args.manifest.relative_to(ROOT)),
        "source_manifest_sha256": sha256_file(args.manifest),
        "control_model_sha256": sha256_file(args.control_model),
        "training": training,
        "training_log": str(log.relative_to(ROOT)),
        "training_log_sha256": sha256_file(log),
        "package": str(package.relative_to(ROOT)),
        "package_tree_sha256": sha256_tree(package),
        "package_policy_hashes": model_hashes,
        "script": str(Path(__file__).resolve().relative_to(ROOT)),
        "script_sha256": sha256_file(Path(__file__).resolve()),
        "realized_rehearsal_records": sum(
            int(row["rehearsal_records"]) for row in training["history"]
        ),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "report": str(args.report),
        "model_sha256": training["sha256"],
        "package_tree_sha256": report["package_tree_sha256"],
        "realized_rehearsal_records": report["realized_rehearsal_records"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
