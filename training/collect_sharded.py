#!/usr/bin/env python3
"""Resume-safe rollout collection using atomic fixed-size gzip shards."""

from __future__ import annotations

import argparse
import gzip
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def valid_gzip(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return any(True for _ in handle)
    except (EOFError, OSError, json.JSONDecodeError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--hero-deck", required=True)
    parser.add_argument("--league", required=True)
    parser.add_argument("--games", type=int, default=5000)
    parser.add_argument("--shard-size", type=int, default=500)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--temperature", type=float, default=0.70)
    parser.add_argument("--gae-lambda", type=float, default=0.95)
    parser.add_argument("--seat-1-ratio", type=float, default=0.50)
    parser.add_argument("--turn1-bench-reward", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=20260730)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--allow-local-smoke", action="store_true")
    args = parser.parse_args()
    if args.games % args.shard_size:
        parser.error("games must be divisible by shard-size")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    shards = []
    for shard_index in range(args.games // args.shard_size):
        shard = output_dir / f"rollouts-{shard_index:03d}.jsonl.gz"
        if not valid_gzip(shard):
            shard.unlink(missing_ok=True)
            command = [
                sys.executable,
                "training/collect_selfplay.py",
                "--model", args.model,
                "--hero-deck", args.hero_deck,
                "--league", args.league,
                "--games", str(args.shard_size),
                "--workers", str(args.workers),
                "--temperature", str(args.temperature),
                "--gae-lambda", str(args.gae_lambda),
                "--seat-1-ratio", str(args.seat_1_ratio),
                "--turn1-bench-reward", str(args.turn1_bench_reward),
                "--seed", str(args.seed + shard_index * 100_000),
                "--output", str(shard),
            ]
            if args.allow_local_smoke:
                command.append("--allow-local-smoke")
            subprocess.run(command, cwd=ROOT, check=True)
        if not valid_gzip(shard):
            raise RuntimeError(f"invalid rollout shard: {shard}")
        shards.append(shard)
        temporary = manifest_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({
            "version": 1,
            "requested_games": args.games,
            "shard_size": args.shard_size,
            "completed_shards": [str(path) for path in shards],
            "model": args.model,
            "league": args.league,
        }, indent=2) + "\n")
        os.replace(temporary, manifest_path)
    combined = output_dir / "rollouts.jsonl.gz"
    temporary = combined.with_name(combined.name + ".tmp")
    with gzip.open(temporary, "wt", encoding="utf-8", compresslevel=6) as destination:
        for shard in shards:
            with gzip.open(shard, "rt", encoding="utf-8") as source:
                for line in source:
                    destination.write(line)
    os.replace(temporary, combined)
    print(json.dumps({"games": args.games, "shards": len(shards), "combined": str(combined)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
