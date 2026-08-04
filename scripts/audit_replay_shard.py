#!/usr/bin/env python3
"""Write a deterministic integrity and coverage manifest for replay training data."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from collections import Counter
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("shards", nargs="+")
    parser.add_argument("--raw-dir")
    parser.add_argument("--require-card", type=int, default=648)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    totals = Counter()
    episodes = set()
    teams = Counter()
    outcomes = Counter()
    versions = Counter()
    shard_rows = {}
    for value in args.shards:
        path = Path(value)
        rows = 0
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                rows += 1
                totals["rows"] += 1
                if args.require_card in row.get("deck", []):
                    totals["required_card_rows"] += 1
                episodes.add(str(row.get("episode_id")))
                teams[str(row.get("team"))] += 1
                outcomes[str(row.get("reward"))] += 1
                versions[str(row.get("features", {}).get("feature_version", 1))] += 1
        shard_rows[str(path)] = rows
    raw = None
    if args.raw_dir:
        directory = Path(args.raw_dir)
        digest = hashlib.sha256()
        count = size = 0
        for path in sorted(directory.glob("*.json*")):
            stat = path.stat()
            digest.update(f"{path.name}\0{stat.st_size}\n".encode())
            count += 1
            size += stat.st_size
        raw = {"directory": str(directory), "files": count, "bytes": size, "name_size_sha256": digest.hexdigest()}
    payload = {
        "shards": shard_rows,
        "rows": totals["rows"],
        "required_card_rows": totals["required_card_rows"],
        "episodes": len(episodes),
        "outcomes": dict(outcomes),
        "feature_versions": dict(versions),
        "top_teams": teams.most_common(25),
        "raw": raw,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, output)
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
