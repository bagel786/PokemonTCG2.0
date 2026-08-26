from __future__ import annotations

import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

from resource_envelope_study.adapters.synthetic import SyntheticSearchAdapter
from resource_envelope_study.runner import CaseContext, run_decision
from resource_envelope_study.stop_policy import FixedWorkStop


def _artifact_script() -> str:
    return r'''
import json
from resource_envelope_study.adapters.synthetic import SyntheticSearchAdapter
from resource_envelope_study.runner import CaseContext, run_decision
from resource_envelope_study.stop_policy import FixedWorkStop
ctx = CaseContext("c", "b", 0, "idle", "fresh", "f", "p", 0, "l", 12345)
row = run_decision(SyntheticSearchAdapter(), {"state": [4, 5]}, FixedWorkStop(23), ctx)
print(json.dumps({
    "state_hash": row.state_hash,
    "seed_hash": row.agent_seed_hash,
    "action_hash": row.selected_action_hash,
    "work": row.completed_work_units,
    "simulations": row.completed_simulations,
    "nodes": row.completed_nodes,
    "forward_model_calls": row.forward_model_calls,
}, sort_keys=True, separators=(",", ":")))
'''


def test_two_clean_subprocesses_reproduce_fixed_work_artifact() -> None:
    outputs = []
    root = Path(__file__).resolve().parents[2]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = f"{root / 'vendor'}:{root}"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    for _ in range(2):
        completed = subprocess.run(
            [sys.executable, "-B", "-c", _artifact_script()],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
            cwd=root,
        )
        outputs.append(completed.stdout.strip())
    assert outputs[0] == outputs[1]
    assert json.loads(outputs[0])["work"] == 23


def _duration(instrumentation_enabled: bool, units: int = 12_000):
    context = CaseContext(
        "c",
        "b",
        0,
        "idle",
        "fresh",
        "f",
        "p",
        0,
        "l",
        12345,
        instrumentation_enabled,
    )
    started = time.perf_counter()
    row = run_decision(
        SyntheticSearchAdapter(),
        {"instrumentation_comparison": "same_scientific_state"},
        FixedWorkStop(units),
        context,
    )
    elapsed = time.perf_counter() - started
    assert row.completed_work_units == units
    assert row.instrumentation_enabled is instrumentation_enabled
    assert row.work_counters_collected is instrumentation_enabled
    if instrumentation_enabled:
        assert row.completed_simulations == units
        assert row.completed_nodes == units
        assert row.forward_model_calls == 2 * units
    else:
        assert row.completed_simulations == 0
        assert row.completed_nodes == 0
        assert row.forward_model_calls == 0
    return elapsed, row


def test_instrumentation_paths_preserve_action_and_produce_a_real_timing_ratio() -> None:
    # Interleave order so thermal drift cannot systematically favor one mode.
    off: list[float] = []
    on: list[float] = []
    action_hashes: set[str] = set()
    for index in range(7):
        if index % 2:
            on_elapsed, on_row = _duration(True)
            off_elapsed, off_row = _duration(False)
        else:
            off_elapsed, off_row = _duration(False)
            on_elapsed, on_row = _duration(True)
        off.append(off_elapsed)
        on.append(on_elapsed)
        action_hashes.update((off_row.selected_action_hash, on_row.selected_action_hash))
    assert len(action_hashes) == 1
    ratio = statistics.median(on) / statistics.median(off)
    # This intentionally cheap hash adapter makes optional Python counter
    # overhead conspicuous; it is not a proxy for any native search unit.  The
    # binding 0.90--1.10 gate is estimated with paired native/Azure pilot runs.
    assert ratio > 0.0
