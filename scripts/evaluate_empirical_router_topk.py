#!/usr/bin/env python3
"""Evaluate the packaged empirical A2/temporal router on held-out elite decisions.

This reproduces the router's stateless choice from recorded public features.  It
is a replay-agreement diagnostic; seeded gameplay remains the strength gate.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if (ROOT / "vendor").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

import numpy as np

from ptcg_ai.features import DecisionFeatures
from ptcg_ai.model import NumpyPolicyModel
from training.evaluate_elite_topk import (
    desired_count,
    empty_bucket,
    finalize,
    option_key,
    sha256_file,
    update_bucket,
)
from training.train_bc import replay_split


def route_matches(routes: list[dict[str, int]], cell: dict[str, int]) -> bool:
    return any(all(cell[key] == value for key, value in route.items()) for route in routes)


def rank(model: NumpyPolicyModel, features: DecisionFeatures) -> tuple[list[int], int]:
    logits, count_logits, _ = model.predict(features)
    ranked = np.argsort(-logits, kind="stable").astype(int).tolist()
    return ranked, desired_count(features, count_logits, len(ranked))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shards", nargs="+")
    parser.add_argument("--a2-model", required=True)
    parser.add_argument("--temporal-model", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--exact-deck", default="decks/grimmsnarl.csv")
    parser.add_argument("--split", default="all")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    a2_path = Path(args.a2_model)
    temporal_path = Path(args.temporal_model)
    config_path = Path(args.config)
    deck_path = Path(args.exact_deck)
    a2 = NumpyPolicyModel(a2_path)
    temporal = NumpyPolicyModel(temporal_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if int(config.get("schema_version", 0)) != 1:
        raise ValueError("unsupported empirical router schema")
    actual_order = str(config.get("actual_order", ""))
    if actual_order not in {"first", "second", "both"}:
        raise ValueError("invalid actual_order")
    routes = [
        {key: int(value) for key, value in raw.items()}
        for raw in config.get("temporal_routes", [])
    ]
    exact_deck = tuple(sorted(int(line) for line in deck_path.read_text().splitlines() if line.strip()))

    buckets = {name: empty_bucket() for name in ("router", "a2", "temporal")}
    by_order = {
        name: defaultdict(empty_bucket) for name in ("router", "a2", "temporal")
    }
    excluded = Counter()
    route_counts = Counter()
    seen: set[tuple[str, int, int]] = set()
    rows_considered = 0
    duplicates = 0

    for raw_path in args.shards:
        with gzip.open(Path(raw_path), "rt", encoding="utf-8") as handle:
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
                features = DecisionFeatures.from_json(row["features"])
                action = [int(index) for index in row.get("action", [])]
                if not features.options or any(index < 0 or index >= len(features.options) for index in action):
                    excluded["invalid"] += 1
                    continue

                order = "first" if float(features.global_features[3]) >= 0.5 else "second"
                a2_ranked, a2_count = rank(a2, features)
                temporal_ranked, temporal_count = rank(temporal, features)
                routed = False
                if (
                    actual_order in {"both", order}
                    and a2_count == 1
                    and temporal_count == 1
                    and option_key(features.options[a2_ranked[0]])
                    != option_key(features.options[temporal_ranked[0]])
                ):
                    cell = {
                        "context": int(features.options[0].context),
                        "a2_option_type": int(features.options[a2_ranked[0]].option_type),
                        "temporal_option_type": int(features.options[temporal_ranked[0]].option_type),
                    }
                    routed = route_matches(routes, cell)
                    if routed:
                        route_counts[json.dumps(cell, sort_keys=True)] += 1
                router_ranked = temporal_ranked if routed else a2_ranked
                router_count = temporal_count if routed else a2_count
                route_counts["all_rows"] += 1
                route_counts["routed_rows"] += int(routed)

                for name, ranked, count in (
                    ("router", router_ranked, router_count),
                    ("a2", a2_ranked, a2_count),
                    ("temporal", temporal_ranked, temporal_count),
                ):
                    predicted = ranked[:count]
                    update_bucket(buckets[name], features, action, ranked, predicted)
                    update_bucket(by_order[name][order], features, action, ranked, predicted)
                rows_considered += 1

    if not rows_considered:
        raise RuntimeError("no held-out rows matched")
    report = {
        "schema_version": 1,
        "evaluation_scope": (
            "stateless held-out replay agreement for the packaged router; "
            "not a gameplay strength estimate"
        ),
        "rows_considered": rows_considered,
        "duplicate_rows_skipped": duplicates,
        "excluded": dict(sorted(excluded.items())),
        "sources": [
            {"path": str(Path(path)), "sha256": file_sha256(Path(path))}
            for path in args.shards
        ],
        "artifacts": {
            "a2_model": {"path": str(a2_path), "sha256": file_sha256(a2_path)},
            "temporal_model": {"path": str(temporal_path), "sha256": file_sha256(temporal_path)},
            "config": {"path": str(config_path), "sha256": file_sha256(config_path)},
            "exact_deck": {"path": str(deck_path), "sha256": sha256_file(deck_path)},
        },
        "router": {
            "actual_order": actual_order,
            "routes": routes,
            "route_counts": dict(sorted(route_counts.items())),
        },
        "results": {
            name: {
                "overall": finalize(buckets[name]),
                "by_actual_order": {
                    order: finalize(by_order[name][order]) for order in ("first", "second")
                },
            }
            for name in ("router", "a2", "temporal")
        },
    }
    rendered = json.dumps(report, indent=2, sort_keys=True)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
