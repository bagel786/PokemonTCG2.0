#!/usr/bin/env python3
"""Measure conversion from an online Dipplin engine into Prize pressure."""

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
    aggregate_scalar,
    analyze_episode,
    load_local_trace_rows,
    mean,
    parse_dataset_args,
    rate,
    write_json,
)


SCHEMA = "dipplin-engine-conversion-v1"


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    online = [row for row in rows if row.get("first_engine_turn")]
    first_turns = [row["first_engine_turn"] for row in online]
    all_engine_turns = [turn for row in online for turn in row.get("engine_turns") or []]
    first_boards = [row.get("first_engine_board") for row in online if row.get("first_engine_board")]
    wins = sum(bool(row.get("win")) for row in rows)
    completed = sum(bool(row.get("completed")) for row in rows)
    return {
        "episodes": len(rows),
        "completed": completed,
        "wins": wins,
        "win_rate_diagnostic_only": rate(wins, completed),
        "engine_online_episodes": len(online),
        "engine_online_episode_rate": rate(len(online), len(rows)),
        "first_engine_online_own_turn": aggregate_scalar(online, "first_engine_online_own_turn"),
        "first_engine_turn_prize_rate": rate(
            sum(turn["prizes_taken"] >= 1 for turn in first_turns if turn["prizes_taken"] is not None),
            sum(turn["prizes_taken"] is not None for turn in first_turns),
        ),
        "first_hit_ko_rate": rate(sum(bool(turn["first_hit_ko"]) for turn in first_turns), len(first_turns)),
        "double_prize_window_rate": rate(
            sum(bool(turn["double_prize_window"]) for turn in first_turns if turn["double_prize_window"] is not None),
            sum(turn["double_prize_window"] is not None for turn in first_turns),
        ),
        "zero_prize_engine_turn_rate": rate(
            sum(turn["prizes_taken"] == 0 for turn in all_engine_turns if turn["prizes_taken"] is not None),
            sum(turn["prizes_taken"] is not None for turn in all_engine_turns),
        ),
        "prizes_per_engine_turn": mean(turn["prizes_taken"] for turn in all_engine_turns if turn["prizes_taken"] is not None),
        "attacks_per_engine_turn": mean(turn["do_wave_attacks"] for turn in all_engine_turns),
        "replacement_ready_at_first_engine_turn": rate(
            sum(board.get("replacement_state") == "ready_dipplin" for board in first_boards),
            len(first_boards),
        ),
        "mean_bench_at_first_engine_turn": mean(board.get("bench_count") for board in first_boards),
        "engine_turn_count": len(all_engine_turns),
    }


def grouped(rows: Sequence[Mapping[str, Any]], field: str) -> dict[str, Any]:
    values: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        values[str(row.get(field) or "unknown")].append(row)
    return {key: summarize(selected) for key, selected in sorted(values.items())}


def build_report(rows: Sequence[Mapping[str, Any]], *, include_episodes: bool) -> dict[str, Any]:
    by_dataset: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_dataset[str(row["dataset"])].append(row)
    datasets: dict[str, Any] = {}
    for label, selected in sorted(by_dataset.items()):
        datasets[label] = {
            "overall": summarize(selected),
            "by_actual_order": grouped(selected, "actual_order"),
            "by_opening_active": grouped(selected, "opening_bucket"),
            "by_opponent_prize_structure": grouped(selected, "opponent_prize_structure"),
            "by_opponent_archetype": grouped(selected, "opponent_archetype"),
            "opponent_archetype_episode_counts": dict(
                sorted(Counter(str(row.get("opponent_archetype")) for row in selected).items())
            ),
        }
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "engine_online_definition": {
            "active": "Dipplin with Energy",
            "attack": "Do the Wave offered",
            "stadium": "Festival Grounds active",
            "engine": "at least one public Thwackey body; its once-per-turn ability may already have resolved",
        },
        "unit": "episode for rates; engine turn for prizes/attacks per engine turn",
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
    parser.add_argument("--splits", default="DEV,VALIDATION,LIVE")
    parser.add_argument("--opponent-archetype", help="optional exact manifest archetype filter")
    parser.add_argument("--include-episodes", action="store_true")
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
