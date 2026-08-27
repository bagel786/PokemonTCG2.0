"""Shared fault mechanics, applied identically to both systems (harness layer).

Each primitive mutates an ExecutionSpec consumed by wrappers; wrappers never
re-derive semantics per system. Mechanics-presence tests key off these flags.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

import numpy as np


@dataclass
class ExecutionSpec:
    construction: str = "G01"
    declared_seed: int = 0
    truncate_bits_b: int = 0
    burn_draws_b: int = 0
    event_keyed: bool = False
    policy_blind: bool = False
    think_budget_scale: float = 0.0
    module_cache_contam_b: bool = False
    queue_tax_a: int = 0
    queue_tax_b: int = 0
    drop_rows_mod: int = 0
    duplicate_row_frac: float = 0.0
    persistent_state_cross_proc: bool = False
    stream_collision_b: bool = False
    ontology_drift_b: bool = False
    repeat_pairs: int = 0            # usable paired repeats retained BOTH arms
    repeat_ids_collide: bool = False
    analysis_unit: str = "seed_condition"
    design_justifications: List[str] = field(default_factory=list)
    independent_seeds_b_delta: int = 0
    replay_scope_claimed: str = "within_artifact"
    context_scope: str = "within_artifact"


def spec_from_construction(g: Dict) -> ExecutionSpec:
    m: Dict[str, any] = g["mechanisms"]

    def _flag(prefix):
        for k, v in m.items():
            if k.startswith(prefix):
                return v if isinstance(v, bool) else True
        return False

    def _param(prefix, cast=float):
        for k, v in m.items():
            if k.startswith(prefix + ":"):
                return cast(k.split(":", 1)[1])
        return None

    def _param_key(prefix):
        for k in m.keys():
            if k.startswith(prefix + ":"):
                return k.split(":", 1)[1]
        return None

    qkey = _param_key("queue_tax")
    qa = qb = 0
    if qkey:
        import json as _json
        try:
            qd = _json.loads(qkey.replace("'", '"'))
            qa, qb = int(qd.get("a", 0)), int(qd.get("b", 0))
        except Exception:
            qa = qb = 1

    specs = dict(
        construction=g["id"],
        declared_seed=0,
        truncate_bits_b=int(_param("truncate_bits_b", float) or 0),
        burn_draws_b=int(_param("burn_draws_b", float) or 0),
        event_keyed=bool(_flag("event_keyed_policy_preserving")),
        policy_blind=bool(_flag("event_keyed_policy_blind")),
        think_budget_scale=float(_param("think_budget") or 0.0),
        module_cache_contam_b=bool(_flag("module_cache_contam_b")),
        queue_tax_a=qa, queue_tax_b=qb,
        drop_rows_mod=int(_param("drop_rows_mod", float) or 0),
        duplicate_row_frac=float(_param("duplicate_row_ids", float) or 0.0),
        persistent_state_cross_proc=bool(_flag("persistent_state_cross_proc")),
        stream_collision_b=bool(_flag("stream_collision_b")),
        ontology_drift_b=bool(_flag("ontology_drift_b")),
        repeat_pairs=int(_param("repeat_pairs_k", float) or 0),
        repeat_ids_collide=bool(_flag("repeat_ids_collide")),
        analysis_unit=(_param_key("analysis_unit")
                       or m.get("analysis_unit") or "seed_condition"),
        independent_seeds_b_delta=int(_param("independent_seeds_b", float) or 0),
    )
    scope_key = _param_key("context_scope")
    # context_scope appears either as plain or scoped value; declared scopes:
    cs = "within_artifact"
    if scope_key:
        cs = scope_key
    elif m.get("context_scope"):
        cs = str(m.get("context_scope"))
    specs["replay_scope_claimed"] = cs
    specs["context_scope"] = cs
    designs = m.get("design_declared") or ["matched_paired_units"]
    canon: List[str] = []
    for dname in designs:
        if dname == "matched_paired_units":
            canon += ["probability_sampling_of_unit", "randomized_matched_assignment"]
        elif dname == "independent_arms":
            canon += ["probability_sampling_of_unit", "independent_arms"]
        else:
            canon.append(dname)
    specs["design_justifications"] = sorted(canon)
    return ExecutionSpec(**specs)


class ModuleCache:
    """Harness-level persistent mutable state (S5-style worker reuse)."""

    def __init__(self):
        self.entries: list = []

    def contaminate(self):
        self.entries.append(1)

    @property
    def dirty(self):
        return len(self.entries) > 0

    def clear(self):
        self.entries.clear()


class PersistentStateFile:
    """Small deterministic cross-process state file.

    A fresh process consuming an existing state file derives a different
    substream offset than the first executor -> genuine cross-process divergence
    under G15 mechanics (and only there).
    """

    def __init__(self, path_fn):
        self._path_fn = path_fn

    def path(self, seed, tag="state"):
        import os
        p = self._path_fn()
        os.makedirs(p, exist_ok=True)
        return os.path.join(p, f"{tag}-{seed}.bin")

    def exists(self, seed):
        import os
        return os.path.exists(self.path(seed))

    def touch(self, seed):
        with open(self.path(seed), "wb") as f:
            f.write(b"\x01")

    def offset_if_present(self, seed):
        return 7919 if self.exists(seed) else 0


def child_streams(declared_seed: int, extra_offset: int = 0):
    """Two spawned children of SeedSequence(offset+declared): dealer + agent."""
    ss = np.random.SeedSequence([int(declared_seed), int(extra_offset)])
    dealer, agent = ss.spawn(2)
    return dealer, agent


def truncated_seed(declared_seed: int, bits: int) -> int:
    return int(declared_seed) & ((1 << bits) - 1)


def effective_seed_for(spec: ExecutionSpec, arm: str) -> int:
    s = int(spec.declared_seed)
    # Cross-process persistence shifts the WHOLE execution environment
    # (any arm/context replica running later sees the shifted state):
    if spec.persistent_state_cross_proc:
        ps = getattr(spec, "_persistent_state", None)
        off = ps.offset_if_present(s) if ps is not None else 0
        s += off
    if arm == "B":
        if spec.truncate_bits_b:
            return truncated_seed(s, spec.truncate_bits_b)
        if spec.independent_seeds_b_delta:
            return s + spec.independent_seeds_b_delta
    return s


def row_plan_for(spec: ExecutionSpec, system: str, seed_index: int,
                 n_scheduled: int) -> Dict:
    """Schedule/row accounting incl. G10 drops and G14 duplication corruption."""
    keep = not (spec.drop_rows_mod and seed_index % spec.drop_rows_mod ==
                spec.drop_rows_mod - 1)
    duplicated = bool(spec.duplicate_row_frac > 0 and
                      (seed_index % max(1, int(round(
                          1 / spec.duplicate_row_frac))) == 0))
    present = n_scheduled - sum(
        1 for i in range(n_scheduled)
        if spec.drop_rows_mod and i % spec.drop_rows_mod == spec.drop_rows_mod - 1)
    if duplicated:
        present += 1  # duplicated row_id inflates the apparent denominator
    ids_unique = not duplicated
    return {"rows_present_recorded": present, "ids_unique": ids_unique}
