#!/usr/bin/env python3
"""Train/evaluate the sparse Dipplin MAIN-action behavior ranker."""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT / "scripts"))

from cg.api import SelectType, to_observation_class  # noqa: E402
from ptcg_ai.dipplin.imitation import option_features  # noqa: E402
from ptcg_ai.dipplin.plan import build_macro_plan  # noqa: E402
from audit_pp_kawada_dipplin import (  # noqa: E402
    _episode_seats,
    _int,
    _semantic_option,
    SUBMISSION_ID,
)


def examples(replays: Path, cache: dict) -> list[tuple[int, object, object, int]]:
    result = []
    for path in sorted(replays.glob("episode-*-replay.json")):
        replay = json.loads(path.read_text(encoding="utf-8"))
        episode = _int((replay.get("info") or {}).get("EpisodeId"))
        steps = replay.get("steps") or []
        for seat in _episode_seats(cache, episode):
            for step in range(max(0, len(steps) - 1)):
                current = steps[step][seat]
                following = steps[step + 1][seat]
                raw = current.get("observation") or {}
                action = list(following.get("action") or [])
                if current.get("status") != "ACTIVE" or raw.get("select") is None or len(action) != 1:
                    continue
                obs = to_observation_class(raw)
                if int(obs.select.type) != int(SelectType.MAIN):
                    continue
                selected_semantic = _semantic_option(obs, action[0])
                selected = next(
                    (index for index in range(len(obs.select.option)) if _semantic_option(obs, index) == selected_semantic),
                    None,
                )
                if selected is None:
                    continue
                result.append((episode, obs, build_macro_plan(obs), selected))
    return result


def train(rows, *, epochs: int, seed: int) -> dict[str, float]:
    rng = random.Random(seed)
    weights: dict[str, float] = defaultdict(float)
    squares: dict[str, float] = defaultdict(float)
    order = list(range(len(rows)))
    for _ in range(epochs):
        rng.shuffle(order)
        for row_index in order:
            _, obs, plan, selected = rows[row_index]
            feature_sets = [option_features(obs, plan, index) for index in range(len(obs.select.option))]
            scores = [sum(weights[f] for f in features) for features in feature_sets]
            peak = max(scores)
            exps = [math.exp(max(-30.0, min(30.0, score - peak))) for score in scores]
            total = sum(exps)
            for index, features in enumerate(feature_sets):
                gradient = (1.0 if index == selected else 0.0) - exps[index] / total
                for feature in features:
                    squares[feature] += gradient * gradient
                    weights[feature] += 0.35 * gradient / math.sqrt(squares[feature] + 1.0)
    return dict(weights)


def accuracy(rows, weights: dict[str, float]) -> float:
    correct = 0
    for _, obs, plan, selected in rows:
        scores = [
            sum(weights.get(feature, 0.0) for feature in option_features(obs, plan, index))
            for index in range(len(obs.select.option))
        ]
        correct += max(range(len(scores)), key=lambda index: (scores[index], -index)) == selected
    return correct / len(rows) if rows else 0.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replays", type=Path, required=True)
    parser.add_argument("--crawl-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=18)
    parser.add_argument("--seed", type=int, default=55408594)
    args = parser.parse_args()
    cache = json.loads(args.crawl_cache.read_text(encoding="utf-8"))
    rows = examples(args.replays, cache)
    episodes = sorted({row[0] for row in rows})
    holdout = set(episodes[::5])
    training = [row for row in rows if row[0] not in holdout]
    validation = [row for row in rows if row[0] in holdout]
    validation_weights = train(training, epochs=args.epochs, seed=args.seed)
    heldout_accuracy = accuracy(validation, validation_weights)
    weights = train(rows, epochs=args.epochs, seed=args.seed)
    payload = {
        "schema": "dipplin-public-replay-main-ranker-v1",
        "submission_id": SUBMISSION_ID,
        "examples": len(rows),
        "episodes": len(episodes),
        "heldout_episodes": len(holdout),
        "heldout_accuracy": heldout_accuracy,
        "training_accuracy": accuracy(rows, weights),
        "weights": {key: round(value, 7) for key, value in sorted(weights.items()) if abs(value) >= 0.015},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps({key: payload[key] for key in payload if key != "weights"} | {"weight_count": len(payload["weights"])}, indent=2))


if __name__ == "__main__":
    main()
