"""Checks for the engine-independent release interface and data boundary."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


RELEASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELEASE))


def test_synthetic_expected_outputs_verify() -> None:
    from pevl_bench import synthetic

    assert synthetic.verify_outputs(RELEASE / "pevl_bench/results") == []


def test_processed_evidence_has_expected_analysis_units() -> None:
    historical = json.loads((RELEASE / "data/processed/historical_summary.json").read_text())
    preflight = json.loads((RELEASE / "data/processed/preflight_summary.json").read_text())
    stress = json.loads((RELEASE / "data/processed/timed_search_stress.json").read_text())
    factorial = json.loads((RELEASE / "data/processed/factorial_summary.json").read_text())
    assert historical["units"] == 2_800
    assert preflight["trajectory_units"] == 1_000
    assert preflight["executions"] == 3_000
    assert stress["clusters"] == 200
    assert factorial["units"] == 2_000
    assert factorial["games"] == 12_000


def test_no_restricted_binary_suffixes_or_literal_local_roots() -> None:
    prohibited = {".dylib", ".dll", ".so", ".exe", ".zip", ".gz", ".tar", ".pkl", ".npy", ".npz", ".pt", ".pth"}
    local_root = re.compile(rb"/(?:Users|home|root|private|tmp|var)/")
    for path in RELEASE.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        assert path.suffix.lower() not in prohibited
        if path.suffix.lower() not in {".pdf", ".png"}:
            assert not local_root.search(path.read_bytes())
