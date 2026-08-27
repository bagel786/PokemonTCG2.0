"""Hold'em wrapper mechanics: policy preservation, cross-policy divergence,
event alignment, same-policy reproducibility, degenerate-contrast ban."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from systems.mechanics import spec_from_construction      # noqa: E402
from systems.holdem_wrapper import HoldemWrapper          # noqa: E402
from runner.gen_expected_table import GRAMMAR             # noqa: E402

CONS = {c["id"]: c for c in GRAMMAR["constructions"]}
W = HoldemWrapper(num_hands=4)


def _spec(cid, seed=777):
    s = spec_from_construction(CONS[cid])
    s.declared_seed = seed
    return s


def test_same_policy_runs_are_reproducible_stateful():
    spec = _spec("G01")
    a1 = W.run_arm(seed=spec.declared_seed, arm="A", spec=spec,
                   repeat_id="t1")
    a2 = W.run_arm(seed=spec.declared_seed, arm="A", spec=spec,
                   repeat_id="t2")
    assert a1["projection_digest"] == a2["projection_digest"]


def test_event_keyed_preserves_policy_and_arms_diverge():
    spec = _spec("G02")
    a = W.run_arm(seed=spec.declared_seed, arm="A", spec=spec)
    b = W.run_arm(seed=spec.declared_seed, arm="B", spec=spec)
    # different policies => genuinely different play (contrast NOT collapsed)
    assert a["agent_id"] != b["agent_id"]
    assert a["outcome_chips_seat0"] is not None
    # dealer deck events align exactly across arms (semantic event equality)
    ka, kb = set(a["event_keys"]), set(b["event_keys"])
    common = {k for k in ka & kb if "act" not in k}
    assert common, "no non-action keyed events to compare"
    assert a["marginals_ok"] and b["marginals_ok"]


def test_policy_blind_construction_collapses_contrast_by_design():
    """G19 replants the historical defect as a LABELED fault: trajectories
    identical -> any variance-benefit output must be flagged DEGENERATE."""
    spec = _spec("G19")
    a = W.run_arm(seed=spec.declared_seed, arm="A", spec=spec)
    b = W.run_arm(seed=spec.declared_seed, arm="B", spec=spec)
    assert a["projection_digest"] == b["projection_digest"], \
        "policy-blind path should collapse the contrast by construction"


def test_truncation_changes_effective_seed_only_for_b():
    spec = _spec("G03")
    a = W.run_arm(seed=spec.declared_seed, arm="A", spec=spec)
    b = W.run_arm(seed=spec.declared_seed, arm="B", spec=spec)
    assert a["effective_seed"] == spec.declared_seed
    assert b["effective_seed"] == (spec.declared_seed & 0xFFFF)


def test_queue_tax_desyncs_stateful_coupling():
    spec = _spec("G09")
    spec.queue_tax_a, spec.queue_tax_b = 1, 2
    fa = W.run_arm(seed=spec.declared_seed, arm="A", spec=spec)
    fb = W.run_arm(seed=spec.declared_seed, arm="B", spec=spec)
    vpa = [e for e in fa["draw_log_tail"] if e.get("stream") == "dealer"]
    vpb = [e for e in fb["draw_log_tail"] if e.get("stream") == "dealer"]
    assert vpa and vpb and vpa[0]["value"] != vpb[0]["value"], \
        "queue tax must desync coupled stream"


def test_real_timings_never_zero():
    spec = _spec("G07", seed=555)
    art = W.run_arm(seed=spec.declared_seed, arm="A", spec=spec)
    assert art["wall_s"] > 0.0 and art["cpu_s"] > 0.0


def test_think_budget_contexts_diverge_but_dealer_fp_stable():
    spec = _spec("G07", seed=42)
    r0 = W.run_arm(seed=spec.declared_seed, arm="A", spec=spec,
                   context_id="fresh", process_rank=0)
    r1 = W.run_arm(seed=spec.declared_seed, arm="A", spec=spec,
                   context_id="worker2", process_rank=1)
    assert r0["projection_digest"] != r1["projection_digest"], \
        "deadline-driven draws must make contexts diverge"


def test_module_cache_contamination_is_detectable():
    from systems.holdem_wrapper import MODULE_CACHE
    spec = _spec("G08", seed=63)
    MODULE_CACHE.clear()
    clean = W.run_arm(seed=spec.declared_seed, arm="B", spec=spec)
    MODULE_CACHE.clear()
    MODULE_CACHE.contaminate()
    dirty = W.run_arm(seed=spec.declared_seed, arm="B", spec=spec)
    MODULE_CACHE.clear()
    assert clean["projection_digest"] != dirty["projection_digest"]
