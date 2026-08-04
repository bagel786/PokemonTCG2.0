#!/usr/bin/env python3
"""Fit and validate a hierarchical deterministic prior from elite replay rows."""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

from ptcg_ai.elite_prior import option_keys  # noqa: E402
from ptcg_ai.features import DecisionFeatures  # noqa: E402
from training.train_bc import split_bucket  # noqa: E402


def rate(selected: float, available: float, parent: float, strength: float = 20.0) -> float:
    return (selected + strength * parent) / (available + strength)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("shards", nargs="+")
    parser.add_argument("--require-card", type=int, default=648)
    parser.add_argument("--feature-version", type=int, default=2)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    levels = [defaultdict(lambda: [0, 0]) for _ in range(3)]
    count_hist = defaultdict(Counter)
    validation = []
    train_records = 0
    for path in map(Path, args.shards):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                if args.require_card not in row.get("deck", []):
                    continue
                features = DecisionFeatures.from_json(row["features"])
                if features.feature_version != args.feature_version or not features.options:
                    continue
                if split_bucket(row.get("episode_id", "")) == 0:
                    validation.append(row)
                    continue
                train_records += 1
                selected = set(row["action"])
                context = features.options[0].context
                for index, option in enumerate(features.options):
                    for level, key in enumerate(option_keys(context, option)):
                        levels[level][key][0] += int(index in selected)
                        levels[level][key][1] += 1
                minimum = round(features.global_features[28] * 9)
                maximum = round(features.global_features[29] * 9)
                count_hist[f"{context}|{len(features.options)}|{minimum}|{maximum}"][len(row["action"])] += 1
    coarse = {key: (selected + 1) / (available + 2) for key, (selected, available) in levels[2].items()}
    middle = {}
    for key, (selected, available) in levels[1].items():
        context, option_type, *_ = key.split("|")
        middle[key] = rate(selected, available, coarse.get(f"{context}|{option_type}", 0.5))
    exact = {}
    for key, (selected, available) in levels[0].items():
        context, option_type, source, _, attack, _, _ = key.split("|")
        exact[key] = rate(selected, available, middle.get(f"{context}|{option_type}|{source}|{attack}", 0.5))
    counts = {key: values.most_common(1)[0][0] for key, values in count_hist.items()}
    payload = {"version": 1, "exact": exact, "middle": middle, "coarse": coarse, "counts": counts}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, separators=(",", ":")) + "\n")

    correct = records = 0
    by_context = defaultdict(lambda: [0, 0])
    for row in validation:
        features = DecisionFeatures.from_json(row["features"])
        context = features.options[0].context
        scored = []
        for index, option in enumerate(features.options):
            e, m, c = option_keys(context, option)
            scored.append((exact.get(e, middle.get(m, coarse.get(c, 0.5))), index))
        ranked = [index for _, index in sorted(scored, key=lambda pair: (pair[0], -pair[1]), reverse=True)]
        minimum = round(features.global_features[28] * 9)
        maximum = round(features.global_features[29] * 9)
        key = f"{context}|{len(features.options)}|{minimum}|{maximum}"
        desired = maximum if minimum == maximum else int(counts.get(key, minimum))
        predicted = ranked[: max(minimum, min(maximum, desired))]
        ok = set(predicted) == set(row["action"])
        records += 1
        correct += ok
        by_context[context][0] += ok
        by_context[context][1] += 1
    print(json.dumps({
        "output": str(output),
        "train_records": train_records,
        "validation_records": records,
        "validation_exact": correct / max(1, records),
        "by_context": {str(key): {"records": value[1], "exact": value[0] / value[1]} for key, value in by_context.items()},
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
