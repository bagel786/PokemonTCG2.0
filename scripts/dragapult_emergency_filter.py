#!/usr/bin/env python3
"""Filter extracted shards to rows from a specific opponent archetype.

Usage:
    python3 scripts/dragapult_emergency_filter.py --tag opponent_grimmsnarl --out data/dragapult_emergency/shards_grim
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SHARD_ROOT = ROOT / "data" / "dragapult_emergency" / "shards"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="opponent_grimmsnarl",
                        choices=["opponent_grimmsnarl", "opponent_starmie",
                                 "opponent_dipplin", "opponent_alakazam"])
    parser.add_argument("--out", required=True)
    parser.add_argument("--split", default="train", choices=["train", "validation"])
    args = parser.parse_args()
    out_root = ROOT / args.out
    total = kept = 0
    for shard in sorted(SHARD_ROOT.glob("*/")):
        source = shard / f"{args.split}.jsonl.gz"
        if not source.exists():
            continue
        rows = []
        with gzip.open(source, "rt", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                total += 1
                if row.get(args.tag):
                    rows.append(row)
        if rows:
            target = out_root / shard.name
            target.mkdir(parents=True, exist_ok=True)
            with gzip.open(target / f"{args.split}.jsonl.gz", "wt", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, separators=(",", ":")) + "\n")
            kept += len(rows)
    print(f"tag={args.tag} split={args.split} kept {kept}/{total} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
