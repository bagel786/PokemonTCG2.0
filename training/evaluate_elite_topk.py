#!/usr/bin/env python3
"""Evaluate one or more neural rankers on the same held-out elite decisions.

This intentionally evaluates the NPZ ranker, not stateful runtime overrides.  It
therefore answers whether training improved the learned policy while package
gameplay remains a separate promotion gate.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if (ROOT / "vendor").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

import numpy as np

from ptcg_ai.features import DecisionFeatures, MAX_SELECT_COUNT
from ptcg_ai.model import NumpyPolicyModel
from training.train_bc import replay_split


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_model(value: str) -> tuple[str, Path]:
    if "=" in value:
        name, raw_path = value.split("=", 1)
    else:
        raw_path = value
        name = Path(value).stem
    name = name.strip()
    path = Path(raw_path)
    if not name or not path.is_file():
        raise argparse.ArgumentTypeError(f"model must be NAME=existing.npz, got {value!r}")
    return name, path


def option_key(option) -> tuple:
    """Schema-v2 semantic identity, collapsing indistinguishable duplicate cards."""
    return (
        int(option.option_type),
        int(option.context),
        int(option.source_card),
        int(option.target_card),
        int(option.attack_id),
        int(option.area),
        int(option.in_play_area),
        # Numeric slots 9..11 are transient source/target/sub-card list
        # positions.  They distinguish engine indices, not strategic moves.
        tuple(
            round(float(value), 6)
            for index, value in enumerate(option.numeric)
            if index not in (9, 10, 11)
        ),
    )


def unique_semantic_ranking(features: DecisionFeatures, ranked: list[int]) -> list[tuple]:
    seen = set()
    result = []
    for index in ranked:
        key = option_key(features.options[index])
        if key not in seen:
            seen.add(key)
            result.append(key)
    return result


def empty_bucket() -> Counter:
    return Counter()


def update_bucket(bucket: Counter, features: DecisionFeatures, action: list[int], ranked: list[int], predicted: list[int]) -> None:
    bucket["records"] += 1
    bucket["whole_action_exact"] += int(set(action) == set(predicted))
    bucket["count_correct"] += int(len(action) == len(predicted))
    if len(action) != 1:
        bucket["multi_records"] += 1
        return

    label = int(action[0])
    if not 0 <= label < len(features.options):
        bucket["invalid_single_labels"] += 1
        return
    bucket["single"] += 1
    choices = len(features.options)
    bucket["single_forced"] += int(choices <= 1)
    bucket["single_index_top1"] += int(ranked[0] == label)
    bucket["single_index_top3"] += int(label in ranked[:3])

    semantic_ranked = unique_semantic_ranking(features, ranked)
    semantic_label = option_key(features.options[label])
    semantic_choices = len(semantic_ranked)
    bucket["semantic_choices_total"] += semantic_choices
    bucket["single_semantic_top1"] += int(semantic_ranked[0] == semantic_label)
    bucket["single_semantic_top3"] += int(semantic_label in semantic_ranked[:3])
    if semantic_choices >= 2:
        bucket["single_semantic_nonforced"] += 1
        bucket["single_semantic_nonforced_top1"] += int(semantic_ranked[0] == semantic_label)
    if semantic_choices >= 4:
        bucket["single_semantic_top3_eligible"] += 1
        bucket["single_semantic_top3_eligible_correct"] += int(semantic_label in semantic_ranked[:3])


def rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def wilson(numerator: int, denominator: int) -> list[float] | None:
    if not denominator:
        return None
    z = 1.959963984540054
    p = numerator / denominator
    scale = 1.0 + z * z / denominator
    center = (p + z * z / (2.0 * denominator)) / scale
    radius = z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * denominator)) / denominator) / scale
    return [center - radius, center + radius]


def finalize(bucket: Counter) -> dict:
    result = dict(sorted(bucket.items()))
    metrics = {
        "whole_action_exact": (bucket["whole_action_exact"], bucket["records"]),
        "count_accuracy": (bucket["count_correct"], bucket["records"]),
        "single_index_top1": (bucket["single_index_top1"], bucket["single"]),
        "single_index_top3": (bucket["single_index_top3"], bucket["single"]),
        "single_semantic_top1": (bucket["single_semantic_top1"], bucket["single"]),
        "single_semantic_top3": (bucket["single_semantic_top3"], bucket["single"]),
        "single_semantic_nonforced_top1": (
            bucket["single_semantic_nonforced_top1"],
            bucket["single_semantic_nonforced"],
        ),
        "single_semantic_top3_eligible": (
            bucket["single_semantic_top3_eligible_correct"],
            bucket["single_semantic_top3_eligible"],
        ),
    }
    result["rates"] = {
        name: {
            "value": rate(numerator, denominator),
            "wilson_95": wilson(numerator, denominator),
            "numerator": numerator,
            "denominator": denominator,
        }
        for name, (numerator, denominator) in metrics.items()
    }
    return result


def desired_count(features: DecisionFeatures, count_logits: np.ndarray, option_count: int) -> int:
    minimum = int(round(float(features.global_features[28]) * MAX_SELECT_COUNT))
    maximum = int(round(float(features.global_features[29]) * MAX_SELECT_COUNT))
    minimum = max(0, min(minimum, option_count))
    maximum = max(minimum, min(maximum, option_count, len(count_logits) - 1))
    if minimum == maximum:
        return maximum
    return minimum + int(np.argmax(count_logits[minimum : maximum + 1]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shards", nargs="+")
    parser.add_argument("--model", action="append", required=True, type=parse_model)
    parser.add_argument("--split", default="all")
    parser.add_argument("--exact-deck", default="decks/grimmsnarl.csv")
    parser.add_argument("--team-list")
    parser.add_argument("--rank-min", type=int, default=1)
    parser.add_argument("--rank-max", type=int, default=0)
    parser.add_argument("--max-records", type=int, default=0)
    parser.add_argument("--output")
    args = parser.parse_args()

    models = {}
    model_paths = {}
    for name, path in args.model:
        if name in models:
            raise ValueError(f"duplicate model name: {name}")
        models[name] = NumpyPolicyModel(path)
        model_paths[name] = path

    exact_deck_path = Path(args.exact_deck)
    exact_deck = tuple(sorted(int(line) for line in exact_deck_path.read_text().splitlines() if line.strip()))
    team_ranks = {}
    team_list_path = Path(args.team_list) if args.team_list else None
    if team_list_path:
        names = [line.strip() for line in team_list_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        team_ranks = {name: index for index, name in enumerate(names, 1)}

    overall = {name: empty_bucket() for name in models}
    by_context = {name: defaultdict(empty_bucket) for name in models}
    by_team = {name: defaultdict(empty_bucket) for name in models}
    rows_considered = 0
    duplicates = 0
    excluded = Counter()
    seen = set()

    for raw_path in args.shards:
        path = Path(raw_path)
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                key = (str(row.get("episode_id", "")), int(row.get("seat", -1)), int(row.get("step", -1)))
                if key in seen:
                    duplicates += 1
                    continue
                seen.add(key)
                if tuple(sorted(int(card) for card in row.get("deck", []))) != exact_deck:
                    excluded["non_exact_deck"] += 1
                    continue
                if args.split != "all" and replay_split(row) != args.split:
                    excluded["split"] += 1
                    continue
                team = str(row.get("team", "unknown"))
                if team_ranks:
                    rank = team_ranks.get(team)
                    if rank is None or rank < args.rank_min or (args.rank_max and rank > args.rank_max):
                        excluded["team_rank"] += 1
                        continue
                features = DecisionFeatures.from_json(row["features"])
                action = [int(index) for index in row.get("action", [])]
                if not features.options or any(index < 0 or index >= len(features.options) for index in action):
                    excluded["invalid"] += 1
                    continue
                context = str(int(features.options[0].context))
                for name, model in models.items():
                    logits, count_logits, _ = model.predict(features)
                    ranked = np.argsort(-logits, kind="stable").astype(int).tolist()
                    count = desired_count(features, count_logits, len(ranked))
                    predicted = ranked[:count]
                    update_bucket(overall[name], features, action, ranked, predicted)
                    update_bucket(by_context[name][context], features, action, ranked, predicted)
                    update_bucket(by_team[name][team], features, action, ranked, predicted)
                rows_considered += 1
                if args.max_records and rows_considered >= args.max_records:
                    break
        if args.max_records and rows_considered >= args.max_records:
            break

    if not rows_considered:
        raise RuntimeError("no rows matched the requested held-out filters")

    report = {
        "schema_version": 1,
        "evaluation_scope": "stateless_npz_ranker_only; runtime overrides and search are excluded",
        "filters": {
            "split": args.split,
            "exact_deck": str(exact_deck_path),
            "exact_deck_sha256": sha256_file(exact_deck_path),
            "team_list": str(team_list_path) if team_list_path else None,
            "rank_min": args.rank_min,
            "rank_max": args.rank_max or None,
        },
        "sources": [{"path": str(Path(path)), "sha256": sha256_file(Path(path))} for path in args.shards],
        "models": {
            name: {"path": str(path), "sha256": sha256_file(path)} for name, path in model_paths.items()
        },
        "rows_considered": rows_considered,
        "duplicate_rows_skipped": duplicates,
        "excluded": dict(sorted(excluded.items())),
        "results": {
            name: {
                "overall": finalize(overall[name]),
                "main_context_0": finalize(by_context[name]["0"]),
                "by_context": {key: finalize(value) for key, value in sorted(by_context[name].items(), key=lambda item: int(item[0]))},
                "by_team": {key: finalize(value) for key, value in sorted(by_team[name].items())},
            }
            for name in models
        },
    }
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
