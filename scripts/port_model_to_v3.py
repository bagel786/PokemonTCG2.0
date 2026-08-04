#!/usr/bin/env python3
"""Port a v2 checkpoint to feature schema v3 without changing what it plays.

v3 appends one option feature (attack-nullified) to the end of `numeric`, so a
zero row appended to `numeric_w` makes the new input contribute exactly nothing.
The ported model is behaviourally identical to the v2 original and keeps all of
its PPO training, while PPO can now learn a non-zero weight for the new feature.

Without this, moving to v3 means restarting from a BC prior and throwing away
every game of PPO the incumbent has.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


def port(source: Path, destination: Path) -> dict:
    arrays = dict(np.load(source, allow_pickle=False))
    schema = int(np.asarray(arrays.get("model_schema_version", 1)).item())
    if schema >= 3:
        raise SystemExit(f"{source} is already schema {schema}")
    numeric_w = arrays["numeric_w"]
    if numeric_w.shape[0] != 12:
        raise SystemExit(f"expected 12 numeric inputs, found {numeric_w.shape[0]}")
    arrays["numeric_w"] = np.vstack([numeric_w, np.zeros((1, numeric_w.shape[1]), numeric_w.dtype)])
    arrays["model_schema_version"] = np.asarray(3, dtype=np.int16)
    destination.parent.mkdir(parents=True, exist_ok=True)
    np.savez(destination, **arrays)
    return {"source": str(source), "output": str(destination),
            "numeric_w": list(arrays["numeric_w"].shape), "from_schema": schema}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(port(Path(args.source), Path(args.output)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
