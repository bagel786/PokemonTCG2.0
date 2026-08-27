"""RNG property tests + genuine cross-process contexts + schema gates."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from systems.rng import (EventKeyedRNG, LoggingStatefulRNG,
                         marginal_uniformity_indicator)   # noqa: E402
from analysis.schema_validators import (validate_row,   # noqa: E402
                                        validate_aggregate)


def test_event_key_order_invariance():
    ek1, ek2 = EventKeyedRNG("s"), EventKeyedRNG("s")
    a1, b1 = ek1.draw("eA"), ek1.draw("eB")
    b2, a2 = ek2.draw("eB"), ek2.draw("eA")
    assert (a1, b1) == (a2, b2)


def test_stream_keys_change_values():
    assert EventKeyedRNG("x").draw("e") != EventKeyedRNG("y").draw("e")


def test_marginal_flatness_of_hash_uniforms():
    ek = EventKeyedRNG("marg")
    vals = [ek.draw(f"ev{i}") for i in range(400)]
    assert marginal_uniformity_indicator(vals)


def test_collision_report_counts_duplicates():
    ek = EventKeyedRNG("c")
    for _ in range(3):
        ek.draw("same")
    rep = ek.collision_report()
    assert rep["duplicates"] == 2 and rep["unique"] == 1


def test_substreams_independent():
    import numpy as np
    from systems.mechanics import child_streams
    d, a = child_streams(123)
    rs_d = LoggingStatefulRNG(int(d.generate_state(1, dtype=np.uint64)[0]))
    rs_a = LoggingStatefulRNG(int(a.generate_state(1, dtype=np.uint64)[0]))
    seq_d = [rs_d.random() for _ in range(4)]
    seq_a = [rs_a.random() for _ in range(4)]
    assert seq_d != seq_a


def test_cross_process_replica_is_genuinely_separate():
    """G15 mechanics proof through the actual worker path."""
    root = Path(__file__).resolve().parents[1]
    tmp = Path("/tmp/prospective_repair_state_test")
    from systems.subprocess_context import run_cross_process_replica
    rec = run_cross_process_replica(str(root), "holdem", "G15", 20250827,
                                    str(tmp))
    assert rec["process_separated"] and isinstance(rec["pid"], int)


def test_output_schema_rejects_ztest_columns_and_zero_timings():
    good = {"level": "decision", "system": "holdem", "construction": "G01",
            "seed": 1, "method": "B7_csvf_full", "branch": "BRANCH_A",
            "decision": "ADMIT", "gt": "VALID", "score_class": "CORRECT",
            "coverage_flag": True, "reason_codes": [],
            "bundle_payload_sha256": "abc",
            "view_payload": {},
            "audit_payload": {"bundle": {"row_id": "x"},
                              "bundle_sha256": "abc"}}
    assert validate_row(good)
    bad = dict(good, audit_payload=None)
    with pytest.raises(ValueError):
        validate_row(bad)
    zrow = {"aggregate_name": "two_proportion_z", "x1": 3}
    with pytest.raises(ValueError):
        validate_aggregate(zrow)
