#!/usr/bin/env python3
"""Write the current top leaderboard team names for replay filtering."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


KAGGLE = ["kaggle"] if shutil.which("kaggle") else [sys.executable, "-m", "kaggle"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--output", default="data/top_teams.txt")
    args = parser.parse_args()
    result = subprocess.run(
        [
            *KAGGLE, "competitions", "leaderboard", "pokemon-tcg-ai-battle",
            "--show", "--page-size", str(min(args.limit, 200)), "--format", "json", "-q",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    start = result.stdout.find("[")
    rows = json.loads(result.stdout[start:])[: args.limit]
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(row["teamName"] for row in rows) + "\n")
    print({"teams": len(rows), "output": str(output)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
