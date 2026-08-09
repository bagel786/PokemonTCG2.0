#!/usr/bin/env python3
"""Combine untouched Ajay/Treecko qualification episodes for M0 screening."""

from __future__ import annotations

import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SUBMISSIONS = (55308008, 55316998)
SOURCE_ROOT = ROOT / "data" / "grim_breakthrough_v5" / "clones"
OUTPUT = ROOT / "data" / "grim_breakthrough_v5" / "policy_identity_holdout.jsonl.gz"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_rows(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if int(row.get("features", {}).get("feature_version", -1)) != 5:
                raise RuntimeError(f"non-schema-5 row in {path}")
            yield row


def main() -> int:
    rows, seen, episodes, orders = [], set(), set(), Counter()
    for submission in SUBMISSIONS:
        path = SOURCE_ROOT / str(submission) / "qualification.jsonl.gz"
        for row in read_rows(path):
            if int(row.get("source_submission_id", -1)) != submission:
                raise RuntimeError(f"submission identity mismatch in {path}")
            key = (str(row["episode_id"]), int(row.get("seat", -1)), int(row.get("step", -1)))
            if key in seen:
                continue
            seen.add(key)
            row["split"] = "policy_identity_holdout"
            row["training_eligible"] = False
            rows.append(row)
            episodes.add(str(row["episode_id"]))
            orders[str(row.get("hero_order") or "unknown")] += 1
    rows.sort(key=lambda row: (str(row["episode_id"]), int(row.get("seat", -1)), int(row.get("step", -1))))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as handle:
            for row in rows:
                handle.write((json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8"))
    result = {
        "status": "complete",
        "feature_version": 5,
        "training_eligible": False,
        "submission_ids": list(SUBMISSIONS),
        "rows": len(rows),
        "episodes": len(episodes),
        "actual_order": dict(orders),
        "path": str(OUTPUT.resolve()),
        "sha256": sha256(OUTPUT),
    }
    OUTPUT.with_suffix(OUTPUT.suffix + ".json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
