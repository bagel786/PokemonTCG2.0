#!/usr/bin/env python3
"""Write the exact candidate/control shard mapping for authentic probe gates."""

from __future__ import annotations

import json
import glob
from pathlib import Path


def has_complete_shards(pattern: str, expected: int = 4) -> bool:
    return len(glob.glob(pattern)) == expected


def main() -> int:
    root = Path("artifacts/recovery_azure/shards")
    payload = {}
    for candidate in ("a1", "a2"):
        candidate_rows = {
            opponent: {
                "candidate": str(root / f"auth_{candidate}_{opponent}_shard_*.json"),
                "control": str(root / f"auth_control_{opponent}_shard_*.json"),
            }
            for opponent in ("alakazam_2_4a", "alakazam_2_7")
        }
        # A mirror-disqualified candidate does not need expensive authentic games.
        payload[candidate] = candidate_rows if all(
            has_complete_shards(paths["candidate"])
            and has_complete_shards(paths["control"])
            for paths in candidate_rows.values()
        ) else {}
    output = Path("artifacts/recovery_probes/authentic_manifest.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
