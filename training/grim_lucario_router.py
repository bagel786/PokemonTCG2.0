#!/usr/bin/env python3
"""Build and train the timeboxed Grimmsnarl Lucario specialist."""

from __future__ import annotations

import argparse
import gzip
import json
import os
import random
import sys
import zlib
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

import numpy as np

from ptcg_ai.features import CARD_LIMIT, MAX_SELECT_COUNT, DecisionFeatures
from ptcg_ai.model import NumpyPolicyModel
from ptcg_ai.replay import iter_decisions, load_episode
from training.azure_guard import enforce_azure_workload
from training.lucario_data import canonical_deck, deterministic_gzip_text, load_deck, sha256_file
from training.replay_refresh import evaluate_model_pair, train_candidate


CONTROL_SHA256 = "d842f85abfc44af9f41979f91795e22c92c179b62e04d5a0a2f9c734e70af1c3"
LUCARIO_IDS = frozenset({677, 678})
OPPONENT_PUBLIC_ZONES = frozenset({5, 6, 7, 8, 10})
TRUSTED_SUBMISSION_WEIGHTS = {
    55198084: 1.0,
    55198075: 1.0,
    55189658: 1.0,
    55180261: 1.0,
    55171235: 1.0,
    55114709: 1.0,
    55180215: 0.5,
    55189662: 0.5,
}
TRAINABLE = (
    "option_linear", "score", "count", "value",
    "global_linear", "numeric_linear", "context_embedding",
)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def predicted_action(model: NumpyPolicyModel, row: dict) -> list[int]:
    features = DecisionFeatures.from_json(row["features"])
    logits, count_logits, _ = model.predict(features)
    ranked = np.argsort(-logits).astype(int).tolist()
    minimum = max(0, min(len(count_logits) - 1, round(features.global_features[28] * MAX_SELECT_COUNT)))
    maximum = max(minimum, min(len(count_logits) - 1, len(ranked), round(features.global_features[29] * MAX_SELECT_COUNT)))
    desired = maximum if minimum == maximum else minimum + int(np.argmax(count_logits[minimum : maximum + 1]))
    return ranked[:desired]


def lucario_visible(row: dict) -> bool:
    tokens = row.get("features", {}).get("tokens", [])
    visible = {
        int(token) % CARD_LIMIT
        for token in tokens
        if int(token) // CARD_LIMIT in OPPONENT_PUBLIC_ZONES
    }
    return bool(visible & LUCARIO_IDS)


def _metadata(path: Path) -> dict[int, dict]:
    metadata = path / "episodes_metadata.json"
    if not metadata.exists():
        return {}
    return {int(row["id"]): row for row in json.loads(metadata.read_text()) if "id" in row}


def build_dataset(args) -> dict:
    control = Path(args.control_model)
    if sha256_file(control) != CONTROL_SHA256:
        raise RuntimeError("live 5k control hash mismatch")
    model = NumpyPolicyModel(control)
    grim = load_deck(args.grim_deck)
    lucario = {load_deck(path) for path in args.lucario_deck}
    replay_root = Path(args.replay_root)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    wins_path = output / "winning_decisions.jsonl.gz"
    anchors_path = output / "loss_teacher_anchors.jsonl.gz"
    seen = set()
    counters = Counter()
    episodes = {}

    with deterministic_gzip_text(wins_path) as wins, deterministic_gzip_text(anchors_path) as anchors:
        for submission, source_weight in sorted(TRUSTED_SUBMISSION_WEIGHTS.items()):
            directory = replay_root / str(submission)
            metadata = _metadata(directory)
            for path in sorted(directory.glob("episode-*-replay.json")):
                episode = load_episode(path)
                steps = episode.get("steps") or []
                if len(steps) < 2:
                    continue
                decks = [canonical_deck(row.get("action", [])) for row in steps[1][:2]]
                if len(decks) != 2 or grim not in decks or not any(deck in lucario for deck in decks):
                    continue
                episode_id = int((episode.get("info") or {}).get("EpisodeId") or path.name.split("-")[1])
                agents = metadata.get(episode_id, {}).get("agents", [])
                grim_seat = next(
                    (seat for seat, agent in enumerate(agents) if agent.get("submissionId") == submission),
                    decks.index(grim),
                )
                if decks[grim_seat] != grim or decks[1 - grim_seat] not in lucario:
                    continue
                visible = False
                episode_rows = []
                for decision in iter_decisions(episode, None, feature_version=2):
                    if decision.seat != grim_seat:
                        continue
                    row = decision.to_json()
                    visible = visible or lucario_visible(row)
                    if not visible:
                        counters["pre_detection_decisions"] += 1
                        continue
                    key = (str(row["episode_id"]), int(row["seat"]), int(row["step"]))
                    if key in seen:
                        counters["duplicates"] += 1
                        continue
                    seen.add(key)
                    episode_rows.append(row)
                if not episode_rows:
                    counters["undetected_games"] += 1
                    continue
                reward = float(episode_rows[0]["reward"])
                # The corpus is tiny.  A sixth-bucket keeps several wins and losses
                # out of optimization while leaving enough successful labels to train.
                gen4_novel_holdout = (
                    submission == 55180215
                    and reward > 0
                    and zlib.crc32(str(episode_id).encode()) % 5 == 4
                )
                split = "validation" if (
                    zlib.crc32(str(episode_id).encode()) % 6 == 0 or gen4_novel_holdout
                ) else "train"
                episodes[str(episode_id)] = {
                    "submission_id": submission, "reward": reward, "split": split,
                    "decisions": len(episode_rows),
                }
                counters["games"] += 1
                counters[f"{split}_games"] += 1
                counters["winning_games" if reward > 0 else "losing_games"] += 1
                for row in episode_rows:
                    row["split"] = split
                    row["source_submission_id"] = submission
                    if reward > 0:
                        disagreement = predicted_action(model, row) != list(row["action"])
                        row["sample_weight"] = source_weight * (2.0 if disagreement else 1.0)
                        row["teacher_disagreement"] = disagreement
                        wins.write(json.dumps(row, separators=(",", ":")) + "\n")
                        counters["winning_decisions"] += 1
                        counters["teacher_disagreements"] += int(disagreement)
                    else:
                        row["action"] = predicted_action(model, row)
                        row["reward"] = 0.0
                        row["sample_weight"] = source_weight
                        row["teacher_anchor"] = True
                        anchors.write(json.dumps(row, separators=(",", ":")) + "\n")
                        counters["anchor_decisions"] += 1

    if counters["winning_decisions"] == 0 or counters["anchor_decisions"] == 0:
        raise RuntimeError("specialist dataset needs both winning labels and loss-state teacher anchors")
    manifest = {
        "version": 1,
        "feature_version": 2,
        "required_card": 0,
        "heldout_teams": [],
        "temporal_episode_ids": [],
        "control": {"path": str(control), "sha256": sha256_file(control)},
        "wins": {"path": str(wins_path), "sha256": sha256_file(wins_path)},
        "anchors": {"path": str(anchors_path), "sha256": sha256_file(anchors_path)},
        "counts": dict(counters),
        "episodes": episodes,
        "split_rule": (
            "validation iff crc32(str(episode_id)) % 6 == 0, plus the stable "
            "crc32 % 5 == 4 Gen4 winning holdout containing non-5k actions"
        ),
        "detection": {"card_ids": sorted(LUCARIO_IDS), "public_zones": sorted(OPPONENT_PUBLIC_ZONES)},
    }
    write_json(output / "manifest.json", manifest)
    return manifest


def train(args) -> dict:
    enforce_azure_workload(
        allow_local_smoke=args.allow_local_smoke,
        workload_size=args.max_train_records or 10_000,
        maximum_local_smoke=512,
    )
    manifest_path = Path(args.data_dir) / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if sha256_file(args.control_model) != CONTROL_SHA256:
        raise RuntimeError("live 5k control hash mismatch")
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    module_lrs = {
        "global_linear": 1e-5, "numeric_linear": 1e-5, "context_embedding": 1e-5,
    }
    result = train_candidate(
        control_model=args.control_model,
        initial_model=args.control_model,
        fresh_path=manifest["wins"]["path"],
        rehearsal_path=manifest["anchors"]["path"],
        manifest=manifest,
        output=output / "policy_weights.npz",
        log_path=output / "training.jsonl",
        learning_rate=1e-4,
        module_learning_rates=module_lrs,
        seed=args.seed,
        batch_size=args.batch_size,
        epochs=3,
        patience=1,
        fresh_weight=0.75,
        distill_weight=0.50,
        trainable_modules=TRAINABLE,
        team_weights={},
        device_name=args.device,
        max_train_records=args.max_train_records,
        max_validation_records=0,
    )
    decision = evaluate_model_pair(
        args.control_model, result["output"], manifest["wins"]["path"], manifest,
        "internal_validation", args.batch_size, args.device, 0,
    )
    report = {
        "version": 1, "seed": args.seed, "training": result,
        "validation": decision,
        "control_sha256": sha256_file(args.control_model),
        "experiment_only": True, "package_created": False, "submitted": False,
    }
    write_json(output / "candidate.json", report)
    return report


def select(args) -> dict:
    candidates = []
    for path in sorted(Path(args.candidates_dir).glob("seed*/candidate.json")):
        report = json.loads(path.read_text())
        comparison = report["validation"]
        overall = comparison.get("overall", comparison)
        baseline = overall["baseline"]
        candidate = overall["candidate"]
        candidates.append({
            "path": str(path), "model": report["training"]["output"],
            "seed": report["seed"],
            "exact_lift": candidate["exact_rate"] - baseline["exact_rate"],
            "count_lift": candidate["count_accuracy"] - baseline["count_accuracy"],
            "policy_errors": 0,
        })
    if len(candidates) != 3:
        raise RuntimeError(f"expected three candidates, found {len(candidates)}")
    ranked = sorted(candidates, key=lambda row: (row["exact_lift"], row["count_lift"]), reverse=True)
    best = ranked[0]
    passed = best["exact_lift"] > 0 and best["count_lift"] >= -0.0025
    report = {
        "version": 1, "candidates": ranked, "selected": best if passed else None,
        "passed": passed, "gates": {"exact_lift_positive": best["exact_lift"] > 0,
        "count_lift_minimum": best["count_lift"] >= -0.0025, "policy_errors": 0},
        "experiment_only": True, "package_created": False, "submitted": False,
    }
    write_json(Path(args.output), report)
    return report


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build-data")
    build.add_argument("--replay-root", default="data/replays")
    build.add_argument("--control-model", default="artifacts/grimmsnarl_5k_reference.npz")
    build.add_argument("--grim-deck", default="freshstart/decklists/grimmsnarl_marnie.deck.csv")
    build.add_argument("--lucario-deck", action="append", default=[
        "freshstart/decklists/mega_lucario_ex.deck.csv",
        "freshstart/decklists/mega_lucario_ex_variant_2.deck.csv",
    ])
    build.add_argument("--output-dir", default="artifacts/grim_lucario_router_20260803/data")
    training = commands.add_parser("train")
    training.add_argument("--data-dir", default="artifacts/grim_lucario_router_20260803/data")
    training.add_argument("--control-model", default="artifacts/grimmsnarl_5k_reference.npz")
    training.add_argument("--output-dir", required=True)
    training.add_argument("--seed", type=int, required=True)
    training.add_argument("--batch-size", type=int, default=128)
    training.add_argument("--max-train-records", type=int, default=0)
    training.add_argument("--device", choices=("auto", "cpu", "cuda", "mps"), default="auto")
    training.add_argument("--allow-local-smoke", action="store_true")
    choose = commands.add_parser("select")
    choose.add_argument("--candidates-dir", default="artifacts/grim_lucario_router_20260803/candidates")
    choose.add_argument("--output", default="artifacts/grim_lucario_router_20260803/selection.json")
    return result


def main() -> int:
    args = parser().parse_args()
    report = build_dataset(args) if args.command == "build-data" else train(args) if args.command == "train" else select(args)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
