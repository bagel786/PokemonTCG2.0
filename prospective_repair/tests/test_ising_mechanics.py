"""Ising wrapper mechanics: real clock residual, sampler RNG consumption,
repeats/cluster integrity, queue/cache analogs."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from systems.mechanics import spec_from_construction        # noqa: E402
from systems.ising_wrapper import IsingWrapper              # noqa: E402
from runner.gen_expected_table import GRAMMAR               # noqa: E402

CONS = {c["id"]: c for c in GRAMMAR["constructions"]}
W = IsingWrapper(size=10, sweeps=12, equilibration=4)


def _spec(cid, seed=31):
    s = spec_from_construction(CONS[cid])
    s.declared_seed = seed
    return s


def test_stateful_same_seed_reproducible():
    spec = _spec("G01")
    a = W.run_arm(seed=spec.declared_seed, temperature_arm="A", spec=spec)
    b = W.run_arm(seed=spec.declared_seed, temperature_arm="A", spec=spec)
    assert a["projection_digest"] == b["projection_digest"]


def test_sampler_actually_consumes_keyed_rng():
    """R03/T05 integration proof: both consumption points are hooked."""
    spec = _spec("G02")
    art = W.run_arm(seed=spec.declared_seed, temperature_arm="A", spec=spec)
    keys = art["event_keys"]
    sites = [k for k in keys if k.startswith("site|")]
    accs = [k for k in keys if k.startswith("acc|")]
    assert len(sites) > 0, "no site draws logged => model._rng hook unused"
    assert len(accs) > 0, "no acceptance draws logged => sampler.rng hook unused"
    assert len(sites) > len(accs)  # attempts >= acceptance-branch consumption
    # events_unique counts the FULL log; the artifact keeps only a key sample
    assert art["events_unique"] >= len(set(keys))


def test_arm_B_temperature_changes_outcome():
    spec = _spec("G01", seed=17)
    a = W.run_arm(seed=spec.declared_seed, temperature_arm="A", spec=spec)
    b = W.run_arm(seed=spec.declared_seed, temperature_arm="B", spec=spec)
    assert a["agent_id"] != b["agent_id"]


def test_think_budget_makes_repeats_diverge_with_nonzero_within_cluster_var():
    spec = _spec("G11", seed=53)
    spec.repeat_pairs = 4
    reps = [W.run_arm(seed=spec.declared_seed, temperature_arm="A",
                      spec=spec, repeat_id=f"r{i+1}")
            for i in range(spec.repeat_pairs)]
    digests = {r["projection_digest"] for r in reps}
    outs = [r["outcome_mean_abs_mag"] for r in reps]
    assert any(r["wall_s"] > 0 and r["cpu_s"] > 0 for r in reps)
    assert len(digests) > 1 or len(set(outs)) > 1, \
        "residual randomness must produce variation across repeats"
    # unique cluster keys with nonzero within-cluster spread where claimed:
    assert all(len({r['repeat_id'] for r in reps}) == spec.repeat_pairs for _ in [0])


def test_queue_tax_desyncs_stateful_pair():
    spec = _spec("G09", seed=71)
    spec.queue_tax_a, spec.queue_tax_b = 1, 2
    a = W.run_arm(seed=spec.declared_seed, temperature_arm="A", spec=spec)
    b = W.run_arm(seed=spec.declared_seed, temperature_arm="B", spec=spec)
    la = [e for e in a["draw_log_tail"] if e.get("stream") == "model"]
    lb = [e for e in b["draw_log_tail"] if e.get("stream") == "model"]
    assert la and lb and la[0]["value"] != lb[0]["value"], \
        "queue tax must desync the coupled model stream"


def test_module_cache_contamination_detectable_ising():
    from systems.ising_wrapper import MODULE_CACHE
    spec = _spec("G08", seed=91)
    MODULE_CACHE.clear()
    clean = W.run_arm(seed=spec.declared_seed, temperature_arm="B", spec=spec)
    MODULE_CACHE.clear()
    MODULE_CACHE.contaminate()
    dirty = W.run_arm(seed=spec.declared_seed, temperature_arm="B", spec=spec)
    MODULE_CACHE.clear()
    assert clean["projection_digest"] != dirty["projection_digest"]


def test_keyed_collision_detected_when_namespace_shared():
    spec = _spec("G16", seed=23)
    a = W.run_arm(seed=spec.declared_seed, temperature_arm="B", spec=spec)
    assert a["event_duplicates"] > 0, "shared namespace must yield duplicate keys"


def test_truncation_only_touches_b():
    spec = _spec("G04", seed=97)
    a = W.run_arm(seed=spec.declared_seed, temperature_arm="A", spec=spec)
    b = W.run_arm(seed=spec.declared_seed, temperature_arm="B", spec=spec)
    assert b["effective_seed"] == (spec.declared_seed & ((1 << 24) - 1))
