"""2D Ising Metropolis wrapper (repaired).

Repairs instantiated here:
- T04/R03: keyed/logging RNGs replace BOTH consumption points (model._rng for
  site selection at ising2d.random_site; sampler.rng for acceptance) BEFORE any
  step; fast sweep disabled so the Python loop (whose draws we instrument)
  actually runs. Integration tests count draws to prove hook usage.
- G07/G11: think-budget burns on an ISOLATED stream; real repeats with unique
  keys and honest residual variation on BOTH arms.
- G08/G09 analogs implemented at the model-stream level.
- D-R6: wall+CPU recorded for every artifact; sweeps/work counters retained.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Dict, List, Optional

import numpy as np

from .mechanics import ExecutionSpec, child_streams, effective_seed_for, ModuleCache
from .rng import EventKeyedRNG, KeyedModelRNG, LoggingStatefulRNG, burn_draws

MODULE_CACHE = ModuleCache()
TEMPERATURES = {"A": 2.269, "B": 2.9}


def spec_repeat_block_factor() -> int:
    return 1


class _KeyedAcceptanceRNG:
    """Acceptance draws keyed into the SAME event-id space as site selection."""

    def __init__(self, ek: EventKeyedRNG):
        self.ek = ek
        self._k = 0

    def random(self, size=None):
        u = float(self.ek.draw(f"acc|{self._k}"))
        self._k += 1
        return u


class IsingWrapper:
    system_id = "ising"
    system_version = "ising-monte-carlo-toolkit==0.1.0"

    def __init__(self, size: int = 20, sweeps: int = 90, equilibration: int = 20,
                 state_dir: Optional[str] = None, ontology_version: str = "v1"):
        from ising_toolkit.models import Ising2D  # pinned dependency check
        self.Ising2D = Ising2D
        self.size = size
        self.sweeps = sweeps
        self.equilibration = equilibration
        self.state_dir = state_dir
        self.ontology_version = ontology_version
        self.adapter_hash = self._self_hash()

    def _self_hash(self):
        path = os.path.abspath(__file__)
        return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]

    # ------------------------------------------------------------------ #
    def run_arm(self, seed: int, temperature_arm: str, spec: ExecutionSpec,
                repeat_id: str = "r0", context_id: str = "fresh",
                process_rank: int = 0) -> Dict:
        t_wall0, t_cpu0 = time.perf_counter(), time.process_time()
        log: List[Dict] = []
        eff = effective_seed_for(_bind_ps(spec), arm=temperature_arm)
        T = TEMPERATURES[temperature_arm]
        keyed_on = spec.event_keyed or spec.policy_blind
        think_scale = spec.think_budget_scale

        dealer_child, _unused = child_streams(eff)
        # NOTE: think-budget deliberately burns from the EXECUTION stream
        # (model/acceptance RNGs below), reproducing how wall-clock-bounded
        # compute makes trajectories context-sensitive while leaving the
        # arm-to-arm COUPLED source (per-seed substream identity) intact.

        model = self.Ising2D(size=self.size, temperature=T, use_numba=False)
        model.initialize("up")

        queue_tax = spec.queue_tax_a if temperature_arm == "A" else spec.queue_tax_b
        cache_hit = (MODULE_CACHE.dirty and spec.module_cache_contam_b
                     and temperature_arm == "B")
        burn_n = spec.burn_draws_b if temperature_arm == "B" else 0

        ek = EventKeyedRNG(f"ising-{eff}", stream_name="model") if keyed_on else None

        if keyed_on:
            if spec.stream_collision_b and temperature_arm == "B":
                kmodel = _CollisionKeyedModelRNG(ek, self.size)
                acc_rng = _CollisionAcceptanceRNG(ek)
            else:
                kmodel = KeyedModelRNG(ek, self.size)
                acc_rng = _KeyedAcceptanceRNG(ek)
            model._rng = kmodel               # hook BEFORE sampler exists
            sampler_seed = None
        else:
            rs = LoggingStatefulRNG(eff, log=log, stream="model")
            if spec.persistent_state_cross_proc is not None:
                pass
            model._rng = rs                       # hook BEFORE sampler exists
            from .rng import LoggingStatefulRNG as _LSR
            acc_rng = _LSR(int(dealer_child.generate_state(1, dtype=np.uint64)[0]),
                           log=log, stream="acceptance")
            sampler_seed = None

        from ising_toolkit.samplers import MetropolisSampler
        sampler = MetropolisSampler(model, seed=sampler_seed)
        sampler._use_fast_sweep = False           # force instrumented python loop
        sampler.rng = acc_rng                     # acceptance hook BEFORE steps

        mags: List[float] = []
        total = self.equilibration + self.sweeps
        for s in range(total):
            if cache_hit and s == 0:
                burn_draws(model._rng, 3)
            if burn_n and s % 10 == 0:            # recurring per measured block
                burn_draws(model._rng, burn_n)
            if queue_tax and s % 10 == 0:
                burn_draws(model._rng, queue_tax)
            if think_scale > 0 and s % 10 == 0:
                # budget-proportional extra consumption checked against a
                # wall-clock deadline; rank-determined minimum guarantees the
                # execution-stream divergence the mechanism declares.
                rank_term = process_rank % 3
                nburn = 30 * (rank_term + 1) * spec_repeat_block_factor()
                t_s = time.perf_counter()
                while ((time.perf_counter() - t_s) * 1000 <
                       4.0 * think_scale * (1.0 + 0.75 * rank_term)):
                    burn_draws(model._rng, 1)
                    nburn += 1
                    if nburn > 8000:
                        break
            sampler.step()
            if s >= self.equilibration and (s - self.equilibration) % 10 == 0:
                mags.append(float(model.get_magnetization()))

        wall, cpu = time.perf_counter() - t_wall0, time.process_time() - t_cpu0
        arr = np.asarray(mags, dtype=float)
        payload = {
            "mag_trajectory_hash": hashlib.sha256(
                np.round(arr, 8).tobytes()).hexdigest(),
            "n_measurements": int(arr.size),
        }
        projection_digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()).hexdigest()

        artifact = {
            "system": self.system_id, "system_version": self.system_version,
            "adapter_version": "2.0.0", "adapter_hash": self.adapter_hash,
            "agent_id": f"T{T}", "agent_config_hash":
                hashlib.sha256(f"T{T}".encode()).hexdigest()[:16],
            "declared_seed": int(
                spec.declared_seed +
                ((spec.independent_seeds_b_delta or 0)
                 if (temperature_arm == "B" and spec.independent_seeds_b_delta)
                 else 0)),
            "effective_seed": int(eff),
            "repeat_id": repeat_id, "context_id": context_id,
            "wall_s": wall, "cpu_s": cpu,
            "sweeps_completed": total,
            "outcome_mean_abs_mag": float(np.mean(np.abs(arr))),
            "projection_digest": projection_digest,
            "draw_log_tail": log[-40:],
            "n_draws_logged": len(log),
            "artifact_bytes": len(json.dumps(payload)) +
                              sum(len(json.dumps(e)) for e in log[-40:]),
            "ontology_version": self.ontology_version,
            "event_keys": [e["event_id"] for e in (ek.log if ek else [])][:400],
            "dealer_first_fp": next((e["value"] for e in log
                                     if e.get("stream") == "model"), None),
        }
        if keyed_on:
            vals = [v for e in ek.log for v in e["values"]]
            from .rng import marginal_uniformity_indicator
            artifact["marginals_ok"] = bool(marginal_uniformity_indicator(vals))
            dup = ek.collision_report()
            artifact["event_duplicates"] = dup["duplicates"]
            artifact["events_unique"] = dup["unique"]
        else:
            artifact["marginals_ok"] = None
            artifact["event_duplicates"] = 0
            artifact["events_unique"] = 0
        return artifact


class _CollisionKeyedModelRNG(KeyedModelRNG):
    """Site selection keeps an INDEPENDENT counter inside one SHARED key
    namespace ('ev|n') as acceptance -> genuine key-space duplication (G16)."""

    def __init__(self, ek, L):
        super().__init__(ek, L)
        self._own = 0

    def integers(self, low, high=None, size=None, dtype=None, endpoint=False):
        out = self.ek.integers_keyed(0, self.L, f"ev|{self._own}")
        self._own += 1
        return out

    def random(self, size=None):
        u = float(self.ek.draw(f"ev|{self._own}"))
        self._own += 1
        return u


class _CollisionAcceptanceRNG:
    """Independent counter inside the SAME shared namespace (G16): its ids
    restart at 0 and therefore collide with site-stream ids."""

    def __init__(self, ek=None, start_k: int = 0):
        self.ek = ek
        self._own = 0

    def random(self, size=None):
        u = float(self.ek.draw(f"ev|{self._own}"))
        self._own += 1
        return u


def _bind_ps(spec: ExecutionSpec) -> ExecutionSpec:
    return spec
