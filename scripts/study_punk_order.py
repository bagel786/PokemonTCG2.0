#!/usr/bin/env python3
"""Punk-Up sequencing study (turn-level).

Group MAIN decisions by (episode, seat, turn) in step order. A turn is eligible
when it contains both a Rare Candy (1079) play and a Marnie's Impidimp (646)
play. Reports bench-first vs candy-first order across MAIN decisions.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

IMIDIMP = 646
RARE_CANDY = 1079


def scan(path: Path) -> Counter:
    counts = Counter()
    turns: dict[tuple, list] = defaultdict(list)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            features = row.get("features") or {}
            options = features.get("options") or []
            if not options or not any(o.get("context") == 0 for o in options):
                continue
            action = row.get("action") or []
            if not action:
                continue
            played = set(action)
            key = (str(row.get("episode_id")), int(row.get("seat", -1)), int(row.get("turn", -1)))
            for i, option in enumerate(options):
                if option.get("option_type") == 7 and option.get("context") == 0:
                    card = int(option.get("source_card", 0))
                    if card in (IMIDIMP, RARE_CANDY) and i in played:
                        turns[key].append((int(row.get("step", 0)), card))
    for key, events in turns.items():
        cards = {c for _, c in events}
        if RARE_CANDY not in cards or IMIDIMP not in cards:
            continue
        counts["eligible_turns"] += 1
        first_candy = min(s for s, c in events if c == RARE_CANDY)
        first_impidimp = min(s for s, c in events if c == IMIDIMP)
        if first_impidimp < first_candy:
            counts["bench_first"] += 1
        else:
            counts["candy_first"] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paths", nargs="+", required=True)
    args = parser.parse_args()
    total = Counter()
    for raw in args.paths:
        path = Path(raw)
        counts = scan(path)
        print(path.name, dict(counts), flush=True)
        for key, value in counts.items():
            total[key] += value
    print("TOTAL", dict(total))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
