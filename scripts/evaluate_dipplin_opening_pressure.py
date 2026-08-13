#!/usr/bin/env python3
"""Compare opening bucket and time-to-pressure metrics across Dipplin corpora."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.dipplin_eval_common import (  # noqa: E402
    OPENING_BUCKETS,
    aggregate_scalar,
    analyze_episode,
    load_local_trace_rows,
    mean,
    parse_dataset_args,
    rate,
    write_json,
)


SCHEMA = "dipplin-opening-pressure-v1"


def _first_attack_board(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    boards = [row.get("first_attack_board") for row in rows if row.get("first_attack_board")]
    return {
        "observed": len(boards),
        "mean_bench_count": mean(board.get("bench_count") for board in boards),
        "mean_applin_lines": mean(board.get("applin_lines") for board in boards),
        "mean_dipplin_count": mean(board.get("dipplin_count") for board in boards),
        "mean_engine_lines": mean(board.get("engine_lines") for board in boards),
        "mean_thwackey_count": mean(board.get("thwackey_count") for board in boards),
        "festival_active_rate": rate(sum(bool(board.get("festival_active")) for board in boards), len(boards)),
        "replacement_ready_rate": rate(
            sum(board.get("replacement_state") == "ready_dipplin" for board in boards),
            len(boards),
        ),
    }


def _first_attack_resources(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    resources = [row.get("first_attack_resources") for row in rows if row.get("first_attack_resources")]
    important_ids = sorted({
        card_id
        for resource in resources
        for field in ("hand_important_counts", "discard_important_counts")
        for card_id in (resource.get(field) or {})
    })
    return {
        "observed": len(resources),
        "mean_hand_count": mean(resource.get("hand_count") for resource in resources),
        "mean_deck_count": mean(resource.get("deck_count") for resource in resources),
        "mean_discard_count": mean(resource.get("discard_count") for resource in resources),
        "mean_prizes_remaining": mean(resource.get("prizes_remaining") for resource in resources),
        "mean_hand_important_counts": {
            card_id: mean((resource.get("hand_important_counts") or {}).get(card_id, 0) for resource in resources)
            for card_id in important_ids
        },
        "mean_discard_important_counts": {
            card_id: mean((resource.get("discard_important_counts") or {}).get(card_id, 0) for resource in resources)
            for card_id in important_ids
        },
    }


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    wins = sum(bool(row.get("win")) for row in rows)
    completed = sum(bool(row.get("completed")) for row in rows)
    return {
        "episodes": len(rows),
        "completed": completed,
        "wins": wins,
        "win_rate_diagnostic_only": rate(wins, completed),
        "actual_order": dict(sorted(Counter(str(row.get("actual_order")) for row in rows).items())),
        "quick_sign": {
            "legal_episodes": sum(bool(row.get("quick_sign_legal")) for row in rows),
            "used_episodes": sum(bool(row.get("quick_sign_used")) for row in rows),
        },
        "first_do_wave_own_turn": aggregate_scalar(rows, "first_do_wave_own_turn"),
        "first_prize_own_turn": aggregate_scalar(rows, "first_prize_own_turn"),
        "first_festival_double_attack_own_turn": aggregate_scalar(
            rows, "first_festival_double_attack_own_turn"
        ),
        "no_do_wave_rate": rate(sum(row.get("first_do_wave_own_turn") is None for row in rows), len(rows)),
        "first_do_wave_board": _first_attack_board(rows),
        "first_do_wave_resources": _first_attack_resources(rows),
    }


def build_report(rows: Sequence[Mapping[str, Any]], *, include_episodes: bool) -> dict[str, Any]:
    by_dataset: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_dataset[str(row["dataset"])].append(row)
    datasets: dict[str, Any] = {}
    for label, selected in sorted(by_dataset.items()):
        buckets = {
            bucket: summarize([row for row in selected if row.get("opening_bucket") == bucket])
            for bucket in OPENING_BUCKETS
        }
        datasets[label] = {
            "overall": summarize(selected),
            "opening_buckets": buckets,
            "opponent_archetype_episode_counts": dict(
                sorted(Counter(str(row.get("opponent_archetype")) for row in selected).items())
            ),
        }
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "method": {
            "unit": "episode",
            "pressure_clock": "hero own-turn ordinal",
            "win_rate_role": "diagnostic_only_for_expert_or_live_samples",
            "information": "hero public observation plus aligned recorded action only",
        },
        "episode_count": len(rows),
        "datasets": datasets,
    }
    if include_episodes:
        payload["episodes"] = list(rows)
    return payload


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", action="append", required=True, help="LABEL=manifest.json or LABEL=replay_directory")
    parser.add_argument("--local-evaluation", action="append", default=[], help="LABEL=evaluation.json with second_bucket_trace rows")
    parser.add_argument("--splits", default="DEV,VALIDATION,LIVE", help="comma-separated manifest splits")
    parser.add_argument("--opponent-archetype", help="optional exact manifest archetype filter")
    parser.add_argument("--include-episodes", action="store_true", help="include per-episode rows; forbidden with SEALED")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    splits = {value.strip().upper() for value in args.splits.split(",") if value.strip()}
    if args.include_episodes and "SEALED" in splits:
        raise SystemExit("per-episode SEALED output is forbidden")
    specs = parse_dataset_args(args.dataset, splits=splits)
    if args.opponent_archetype:
        specs = [spec for spec in specs if spec.opponent_archetype == args.opponent_archetype]
    rows = [analyze_episode(spec) for spec in specs]
    rows.extend(load_local_trace_rows(args.local_evaluation))
    report = build_report(rows, include_episodes=args.include_episodes)
    write_json(args.output, report)
    print(json.dumps({"schema": SCHEMA, "episodes": len(rows), "output": str(args.output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
