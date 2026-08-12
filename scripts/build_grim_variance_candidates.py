#!/usr/bin/env python3
"""Materialize distinct local B0/B1/B2/B3 evaluation trees.

This creates directories only.  It never creates a submission archive, uploads,
or changes the frozen model/deck.  B0 is a direct extraction of the pinned
reference; B1-B3 use the existing guarded builder with explicit flags.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]

from scripts import build_grim_guardrail_candidate as builder


DEFAULT_OUTPUT = ROOT / "artifacts" / "grim_variance_floor" / "candidates"


def build_candidates(
    *,
    output: str | Path = DEFAULT_OUTPUT,
    base_archive: str | Path = builder.DEFAULT_BASE,
) -> dict:
    output = Path(output).resolve()
    base_archive = Path(base_archive).resolve()
    if not base_archive.is_file():
        raise FileNotFoundError(base_archive)
    if builder.sha256_file(base_archive) != builder.FROZEN_ARCHIVE_SHA256:
        raise builder.BuildError("base archive is not the pinned frozen d842 archive")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise builder.BuildError(f"candidate output must be empty: {output}")

    results = {}
    for variant in ("B0", "B1", "B2", "B3"):
        destination = output / variant
        destination.mkdir()
        if variant == "B0":
            builder.safe_extract(base_archive, destination)
            frozen = builder.verify_frozen_tree(destination)
            results[variant] = {
                "variant": variant,
                "directory": str(destination),
                "runtime": "exact frozen d842",
                "variance_config": {"punk_up_floor": False, "dead_active_escape": False},
                "frozen": frozen,
            }
        else:
            results[variant] = builder.stage_candidate(
                base_archive,
                destination,
                variant=variant,
            )
            results[variant]["directory"] = str(destination)

    manifest = {
        "schema_version": 1,
        "purpose": "local variance-floor evaluation trees; not a submission package",
        "base_archive_sha256": builder.sha256_file(base_archive),
        "frozen_model_sha256": builder.FROZEN_MODEL_SHA256,
        "frozen_raw_deck_sha256": builder.FROZEN_RAW_DECK_SHA256,
        "candidates": results,
    }
    (output / "candidate_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--base-archive", type=Path, default=builder.DEFAULT_BASE)
    args = parser.parse_args()
    print(json.dumps(build_candidates(output=args.output, base_archive=args.base_archive), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
