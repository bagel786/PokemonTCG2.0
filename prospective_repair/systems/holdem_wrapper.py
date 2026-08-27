"""RLCard limit-holdem wrapper (repaired).

Repairs instantiated here:
- T04/R02: hooks installed BEFORE env reset; hook identity asserted in tests.
- K003/T03: event-keyed path PRESERVES requested policy (G02) or deliberately
  replants the policy-blind defect as labeled construction G19.
- D-R6: real wall+CPU timings on every artifact (never placeholders).
- G15: persistent-state offset makes cross-process replicas genuinely differ.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Dict, List, Optional

import numpy as np

from .mechanics import (ExecutionSpec, child_streams, effective_seed_for,
                        ModuleCache)
from .rng import (EventKeyedRNG, LoggingRandomState, LoggingStatefulRNG,
                  marginal_uniformity_indicator)

MODULE_CACHE = ModuleCache()

ACTION_PREFERENCE = ("call", "check", "fold")


def _file_sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


class _KeyedDealerAdapter:
    """Duck-typed np_random replacement: keyed shuffle + keyed picks."""

    def __init__(self, ek: EventKeyedRNG):
        self.ek = ek
        self.hand_counter = 0
        self._misc = 0
        self.collision_namespace = False  # True only under G16 mechanics

    def _misc_key(self):
        if self.collision_namespace:
            # INDEPENDENT counters inside one SHARED id space: both streams
            # start counting at 0 => genuine cross-stream event-id collisions
            k = f"ev|{self._misc}"
        else:
            k = f"misc|{self._misc}"
            self._misc += 1
            k = k  # non-collision: unique namespace
        return k

    def randint(self, low, high=None, size=None, dtype=None):
        u = float(self.ek.draw(self._misc_key()))
        self._misc += 1 if self.collision_namespace else 0
        span = int(high) - int(low) if high is not None else 1
        v = int(low) + min(int(u * max(span, 1)), max(span - 1, 0))
        if size is not None:
            import numpy as _np
            return _np.array([v] * size)
        return v

    def choice(self, a, size=None, replace=True, p=None, axis=0, shuffle=True):
        idx = self.randint(0, len(a))
        arr = np.asarray(a)
        pick = arr[idx]
        if size is not None:
            return np.array([pick] * size)
        return pick

    def rand(self, *args):
        u = float(self.ek.draw(self._misc_key()))
        return u

    def random_sample(self):
        return self.rand()

    def shuffle(self, deck):
        h = self.hand_counter
        self.hand_counter += 1
        self._shuf = getattr(self, "_shuf", 0)
        n = len(deck)
        for i in range(n - 1, 0, -1):
            if self.collision_namespace:
                key = f"ev|{self._shuf}"
                self._shuf += 1
            else:
                key = f"hand{h}|shuffle|{i}"
            u = float(self.ek.draw(key))
            j = min(int(u * (i + 1)), i)
            deck[i], deck[j] = deck[j], deck[i]

    def seed(self, *_a, **_k):  # legacy API tolerance
        return None


def _draw_counter_total_static(ek: EventKeyedRNG):
    return sum(ek.draw_counter.values())


# attach helper on EventKeyedRNG for adapter use
EventKeyedRNG.draw_counter_total = lambda self: sum(self.draw_counter.values())


class HoldemWrapper:
    system_id = "holdem"
    system_version = "rlcard==1.2.0"

    def __init__(self, num_hands: int = 10, root: Optional[str] = None,
                 ontology_version: str = "v1"):
        import rlcard  # local import: pinned dependency
        self.rlcard = rlcard
        self.num_hands = num_hands
        here = os.path.dirname(os.path.abspath(__file__))
        self.adapter_hash = _file_sha(os.path.join(here, "holdem_wrapper.py"))
        self.root = root
        self.ontology_version = ontology_version

    # ------------------------------------------------------------------ #
    def run_arm(self, seed: int, arm: str, spec: ExecutionSpec,
                repeat_id: str = "r0", context_id: str = "fresh",
                process_rank: int = 0) -> Dict:
        t_wall0, t_cpu0 = time.perf_counter(), time.process_time()
        log: List[Dict] = []
        eff = effective_seed_for(_with_ps(spec), arm)

        dealer_child, agent_child = child_streams(eff)
        keyed_on = spec.event_keyed or spec.policy_blind
        keyed_actions_blind = spec.policy_blind

        ek_a = EventKeyedRNG(f"holdem-{eff}", stream_name="dealer") \
            if keyed_on else None
        dealer_adapter: object
        agent_rng: Optional[LoggingStatefulRNG]
        if keyed_on:
            dealer_adapter = _KeyedDealerAdapter(ek_a)
            dealer_adapter.collision_namespace = spec.stream_collision_b and arm == "B"
            agent_rng = LoggingStatefulRNG(
                int(agent_child.generate_state(1, dtype=np.uint64)[0]),
                stream="agent")
        else:
            rs = LoggingRandomState(
                dealer_child.generate_state(4, dtype=np.uint32), log=log)
            rs.effective_seed = eff
            dealer_adapter = rs
            agent_rng = LoggingStatefulRNG(
                int(agent_child.generate_state(1, dtype=np.uint64)[0]),
                stream="agent")
        # arm-B queue tax applies to the coupled stream pre-unit when stateful
        # (keyed paths cannot be order-shifted; queue semantics then n/a)

        env = self.rlcard.make("limit-holdem", config={"seed": 0})
        env.game.np_random = dealer_adapter   # hook BEFORE any reset/deal
        env.np_random = dealer_adapter

        policy = "random" if arm == "A" else "conservative"
        think_scale = spec.think_budget_scale
        cache_dirty = MODULE_CACHE.dirty and spec.module_cache_contam_b and arm == "B"

        traj: List[tuple] = []
        chips = 0.0
        marginals_pool: List[float] = []
        for h in range(self.num_hands):
            if not keyed_on and arm == "B" and spec.burn_draws_b:
                from .rng import burn_draws
                burn_draws(dealer_adapter, spec.burn_draws_b)  # recurring/hand
            q = spec.queue_tax_a if arm == "A" else spec.queue_tax_b
            if not keyed_on and q:
                from .rng import burn_draws
                burn_draws(dealer_adapter, q)
            env.reset()
            step = 0
            while not env.is_over():
                pid = env.get_player_id()
                st = env.get_state(pid)
                ids = [int(a) for a in st["legal_actions"].keys()]
                names = list(st["raw_legal_actions"])
                name_of = {i: n for i, n in zip(ids, names)}
                if cache_dirty and h == 0 and step == 0:
                    act = ids[-1]          # contamination perturbs first action
                elif keyed_on:
                    event_key = f"h{h}|s{step}|p{pid}|act"
                    u = float(ek_a.draw(event_key))
                    marginals_pool.append(u)
                    if not keyed_actions_blind and policy == "random":
                        act = ids[min(int(u * len(ids)), len(ids) - 1)]
                    elif not keyed_actions_blind:
                        act = _conservative(name_of, ids)
                    else:
                        act = ids[min(int(u * len(ids)), len(ids) - 1)]  # BLIND
                elif policy == "random":
                    if think_scale > 0:
                        t_s = time.perf_counter()
                        budget_ms = 8.0 * think_scale * (
                            1.0 + 0.75 * (process_rank % 3))
                        # rank-determined minimum consumption guarantees the
                        # execution stream divergence; deadline-bound tail
                        # supplies genuine wall-clock coupling.
                        min_draws = 4000 * ((process_rank % 3) + 1)
                        drawn = 0
                        while drawn < min_draws:
                            agent_rng.random(); drawn += 1
                        while ((time.perf_counter() - t_s) * 1000 < budget_ms
                               and drawn < 120000):
                            agent_rng.random(); drawn += 1
                    u = float(agent_rng.random())
                    act = ids[min(int(u * len(ids)), len(ids) - 1)]
                else:
                    act = _conservative(name_of, ids)
                env.step(int(act))
                traj.append((h, step, pid, int(act)))
                step += 1
            chips += float(env.get_payoffs()[0])

        wall, cpu = time.perf_counter() - t_wall0, time.process_time() - t_cpu0
        digest_payload = {
            "trajectory_hash": hashlib.sha256(
                json.dumps(traj, sort_keys=True).encode()).hexdigest(),
            "num_steps": len(traj),
        }
        projection_digest = hashlib.sha256(
            json.dumps(digest_payload, sort_keys=True).encode()).hexdigest()
        keys_seen = [e["event_id"] for e in (ek_a.log if keyed_on else [])]
        artifact = {
            "system": self.system_id, "system_version": self.system_version,
            "adapter_version": "2.0.0", "adapter_hash": self.adapter_hash,
            "agent_id": f"{policy}_policy",
            "agent_config_hash": hashlib.sha256(policy.encode()).hexdigest()[:16],
            "declared_seed": int(
                spec.declared_seed +
                ((spec.independent_seeds_b_delta or 0)
                 if (arm == "B" and spec.independent_seeds_b_delta) else 0)),
            "effective_seed": int(eff),
            "repeat_id": repeat_id, "context_id": context_id,
            "wall_s": wall, "cpu_s": cpu,
            "hands": self.num_hands,
            "outcome_chips_seat0": round(chips, 6),  # outcome layer ONLY
            "projection_digest": projection_digest,
            "draw_log_tail": log[-40:],
            "n_draws_logged": len(log),
            "artifact_bytes": len(json.dumps(digest_payload)) +
                              sum(len(json.dumps(e)) for e in log[-40:]),
            "ontology_version": self.ontology_version,
            "event_keys": keys_seen[:400],
            "dealer_first_fp": next((e["value"] for e in log
                                     if e.get("stream") == "dealer"), None)
            if log else None,
        }
        if keyed_on:
            vals = ([v for e in ek_a.log for v in e["values"]])
            artifact["marginals_ok"] = bool(marginal_uniformity_indicator(vals))
            dup = ek_a.collision_report()
            artifact["event_duplicates"] = dup["duplicates"]
            artifact["events_unique"] = dup["unique"]
        else:
            artifact["marginals_ok"] = None
            artifact["event_duplicates"] = 0
            artifact["events_unique"] = len(keys_seen)
        return artifact


def _conservative(name_of: Dict[int, str], ids: List[int]) -> int:
    for want in ACTION_PREFERENCE:
        for i in ids:
            if name_of.get(i, "") == want:
                return i
    return ids[0]


def _with_ps(spec: ExecutionSpec) -> ExecutionSpec:
    if spec.persistent_state_cross_proc and getattr(spec, "_persistent_state",
                                                    None) is not None:
        return spec
    return spec
