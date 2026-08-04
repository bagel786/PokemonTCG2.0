#!/usr/bin/env python3
"""Convert v1 replay rows into v2-compatible rows with explicitly missing additions."""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

from ptcg_ai.features import V2_GLOBAL_SIZE


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    rows = 0
    with gzip.open(args.input, "rt", encoding="utf-8") as source, gzip.open(temporary, "wt", encoding="utf-8", compresslevel=6) as destination:
        for line in source:
            row = json.loads(line)
            features = row["features"]
            if int(features.get("feature_version", 1)) != 1:
                raise ValueError("input contains a non-v1 replay row")
            features["global"] = list(features["global"]) + [0.0] * (V2_GLOBAL_SIZE - len(features["global"]))
            features["feature_version"] = 2
            features["source_feature_version"] = 1
            destination.write(json.dumps(row, separators=(",", ":")) + "\n")
            rows += 1
    os.replace(temporary, output)
    print({"rows": rows, "output": str(output), "feature_version": 2, "source_feature_version": 1})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
