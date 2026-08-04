#!/usr/bin/env python3
"""Extract model-ready decisions from one or more public Kaggle episodes."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

from ptcg_ai.replay import iter_decisions, load_episode, write_decisions  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", help="episode JSON/JSON.GZ files or directories")
    parser.add_argument("--output", required=True, help="output .jsonl.gz shard")
    parser.add_argument("--teams", help="optional newline-delimited team allowlist")
    parser.add_argument("--feature-version", type=int, default=2)
    args = parser.parse_args()
    allowed = None
    if args.teams:
        allowed = {line.strip() for line in Path(args.teams).read_text().splitlines() if line.strip()}

    paths: list[Path] = []
    for value in args.inputs:
        path = Path(value)
        if path.is_dir():
            paths.extend(sorted(path.glob("*.json")))
            paths.extend(sorted(path.glob("*.json.gz")))
        else:
            paths.append(path)

    def records():
        for path in paths:
            yield from iter_decisions(load_episode(path), allowed, args.feature_version)

    count = write_decisions(records(), args.output)
    print({"episodes": len(paths), "decisions": count, "output": args.output})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
