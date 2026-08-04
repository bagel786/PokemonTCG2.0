#!/usr/bin/env python3
"""Compare a neural policy with held-out elite decisions on identical observations."""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

import numpy as np

from ptcg_ai.features import DecisionFeatures, MAX_SELECT_COUNT
from ptcg_ai.model import NumpyPolicyModel
from training.train_bc import replay_split


def archetype_lookup(path: Path) -> dict[tuple[int, ...], str]:
    league = json.loads(path.read_text())
    result = {}
    for entry in league["opponents"]:
        deck_path = Path(entry["deck"])
        if not deck_path.is_absolute():
            deck_path = ROOT / deck_path
        cards = tuple(int(line) for line in deck_path.read_text().splitlines() if line.strip())
        if entry.get("evaluate"):
            result[cards] = entry["name"]
    return result


def metrics_bucket():
    return {"records": 0, "exact": 0, "count_correct": 0, "single": 0, "top1": 0, "top3": 0, "covered": 0, "covered_top1": 0}


def update(bucket, elite, predicted, ranked, margin, threshold):
    bucket["records"] += 1
    bucket["exact"] += int(set(elite) == set(predicted))
    bucket["count_correct"] += int(len(elite) == len(predicted))
    if len(elite) == 1:
        bucket["single"] += 1
        bucket["top1"] += int(ranked[0] == elite[0])
        bucket["top3"] += int(elite[0] in ranked[:3])
        if margin >= threshold:
            bucket["covered"] += 1
            bucket["covered_top1"] += int(ranked[0] == elite[0])


def finalize(bucket):
    result = dict(bucket)
    result.update({
        "exact_rate": bucket["exact"] / max(1, bucket["records"]),
        "count_accuracy": bucket["count_correct"] / max(1, bucket["records"]),
        "single_top1": bucket["top1"] / max(1, bucket["single"]),
        "single_top3": bucket["top3"] / max(1, bucket["single"]),
        "neural_coverage": bucket["covered"] / max(1, bucket["single"]),
        "covered_top1": bucket["covered_top1"] / max(1, bucket["covered"]),
    })
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("shards", nargs="+")
    parser.add_argument("--model", required=True)
    parser.add_argument("--require-card", type=int, default=0)
    parser.add_argument(
        "--split", choices=("validation", "holdout", "unseen_team", "temporal", "train", "all"),
        default="validation",
    )
    parser.add_argument("--max-records", type=int, default=0)
    parser.add_argument("--confidence-margin", type=float, default=0.15)
    parser.add_argument("--league", default="training/meta_league.json")
    parser.add_argument("--output")
    args = parser.parse_args()

    model = NumpyPolicyModel(args.model)
    archetypes = archetype_lookup(Path(args.league))
    overall = metrics_bucket()
    by_context = defaultdict(metrics_bucket)
    by_archetype = defaultdict(metrics_bucket)

    stop = False
    for shard in map(Path, args.shards):
        with gzip.open(shard, "rt", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                if args.require_card and args.require_card not in row.get("deck", []):
                    continue
                row_split = replay_split(row)
                if args.split != "all" and row_split != args.split:
                    continue
                features = DecisionFeatures.from_json(row["features"])
                logits, count_logits, _ = model.predict(features)
                if len(logits) == 0:
                    continue
                ranked = np.argsort(-logits).astype(int).tolist()
                minimum = int(round(features.global_features[28] * MAX_SELECT_COUNT))
                maximum = int(round(features.global_features[29] * MAX_SELECT_COUNT))
                if minimum == maximum:
                    desired = maximum
                else:
                    upper = min(maximum, len(count_logits) - 1)
                    desired = minimum + int(np.argmax(count_logits[minimum : upper + 1]))
                desired = max(minimum, min(maximum, desired, len(ranked)))
                predicted = ranked[:desired]
                margin = float(np.sort(logits)[-1] - np.sort(logits)[-2]) if len(logits) > 1 else float("inf")
                context = str(features.options[0].context if features.options else -1)
                archetype = archetypes.get(tuple(row.get("deck", [])), "other")
                update(overall, row["action"], predicted, ranked, margin, args.confidence_margin)
                update(by_context[context], row["action"], predicted, ranked, margin, args.confidence_margin)
                update(by_archetype[archetype], row["action"], predicted, ranked, margin, args.confidence_margin)
                if args.max_records and overall["records"] >= args.max_records:
                    stop = True
                    break
        if stop:
            break

    report = {
        "model": str(args.model),
        "split": args.split,
        "confidence_margin": args.confidence_margin,
        "overall": finalize(overall),
        "by_context": {key: finalize(value) for key, value in sorted(by_context.items())},
        "by_archetype": {key: finalize(value) for key, value in sorted(by_archetype.items())},
    }
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
