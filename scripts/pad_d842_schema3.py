#!/usr/bin/env python3
"""Create the behavior-preserving schema-3 d842 initialization."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from training.schema3 import pad_schema3


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="artifacts/overnight_grim_20260730/grim_selected.npz")
    parser.add_argument("--output", default="artifacts/recovery_schema3/d842_schema3_zero_init.npz")
    args = parser.parse_args()
    source, output = Path(args.source), Path(args.output)
    pad_schema3(source, output)
    manifest = {
        "source": str(source.resolve()),
        "source_sha256": digest(source),
        "output": str(output.resolve()),
        "output_sha256": digest(output),
        "migration": "append one all-zero numeric_w row for attack-nullification; all other arrays unchanged",
    }
    output.with_suffix(".json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
