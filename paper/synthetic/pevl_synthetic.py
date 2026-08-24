#!/usr/bin/env python3
"""Development-tree entry point for the standalone released PEVL testbed."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Sequence


def _load_implementation() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[1]
        / "release"
        / "synthetic"
        / "pevl_synthetic.py"
    )
    spec = importlib.util.spec_from_file_location("_pevl_release_impl", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load PEVL implementation from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_IMPL = _load_implementation()

SCHEMA_VERSION = _IMPL.SCHEMA_VERSION
UINT32_MODULUS = _IMPL.UINT32_MODULUS
DEFAULT_SEED = _IMPL.DEFAULT_SEED
LEVELS = _IMPL.LEVELS
EXPECTED_CATCHES = _IMPL.EXPECTED_CATCHES
canonical_json_bytes = _IMPL.canonical_json_bytes
sha256_bytes = _IMPL.sha256_bytes
object_sha256 = _IMPL.object_sha256
uint32_seed = _IMPL.uint32_seed
event_keyed_uint64 = _IMPL.event_keyed_uint64
simulate_random_stream = _IMPL.simulate_random_stream
simulate_wall_clock_search = _IMPL.simulate_wall_clock_search
simulate_process_global_state = _IMPL.simulate_process_global_state
build_report = _IMPL.build_report
validate_report = _IMPL.validate_report
results_schema = _IMPL.results_schema
render_json = _IMPL.render_json
render_csv = _IMPL.render_csv
rendered_outputs = _IMPL.rendered_outputs
write_outputs = _IMPL.write_outputs
verify_outputs = _IMPL.verify_outputs


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] in {"generate", "verify"}:
        has_output_dir = any(
            item == "--output-dir" or item.startswith("--output-dir=")
            for item in arguments[1:]
        )
        if not has_output_dir:
            arguments.extend(
                ["--output-dir", str(Path(__file__).resolve().parent / "results")]
            )
    return _IMPL.main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
