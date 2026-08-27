"""Generate EXPECTED_DECISION_TABLE.json mechanically from the frozen fault
grammar: construction×branch ground truth + reference decisions for every
method over COMPLETE outcome-free synthetic evidence bundles.

This doubles as a classifier regression fixture: tests assert B7's reference
decisions match grammar truth wherever semantics are unambiguous, and assert
the repaired independence properties directly.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from framework.classifier import classify_all            # noqa: E402
from framework.baselines import BASELINE_FUNCS           # noqa: E402
from framework.evidence import MethodView                # noqa: E402
from runner.bundle_builder import (build_bundle,
                                   build_bundle_with_crossproc)  # noqa: E402
from systems.mechanics import spec_from_construction     # noqa: E402

GRAMMAR = json.loads((ROOT / "protocol" / "FAULT_GRAMMAR.json").read_text())

SYNC_TAIL = [{"stream": "model", "kind": "random", "index": i, "value": 0.1 * i}
             for i in range(6)]
SYNC_TAIL_SHIFTED = [dict(e, value=e["value"] + 0.05)
                     for e in SYNC_TAIL]


def _replay_breaking(spec) -> bool:
    return bool(spec.truncate_bits_b or spec.burn_draws_b or
                spec.module_cache_contam_b or spec.queue_tax_a or
                spec.queue_tax_b or spec.persistent_state_cross_proc or
                spec.think_budget_scale > 0)


def _tail_shifting(spec) -> bool:
    """Mechanisms that alter the COUPLED/model stream itself."""
    return bool(spec.truncate_bits_b or spec.burn_draws_b or
                spec.module_cache_contam_b or spec.queue_tax_a or
                spec.queue_tax_b)


def synthetic_artifacts(spec):
    brk = _replay_breaking(spec)

    def _base(arm, cfg, shift=False, digest_shift=False):
        return {"system": "holdem", "system_version": "x",
                "adapter_version": "2.0.0", "adapter_hash": "h",
                "agent_id": arm, "agent_config_hash": cfg,
                "effective_seed": (
                    spec.declared_seed & ((1 << spec.truncate_bits_b) - 1))
                if (arm == "B" and spec.truncate_bits_b) else (
                    spec.declared_seed + (spec.independent_seeds_b_delta or 0)
                    if (arm == "B" and spec.independent_seeds_b_delta) else
                    spec.declared_seed),
                "declared_seed": (
                    spec.declared_seed +
                    ((spec.independent_seeds_b_delta or 0)
                     if (arm == "B" and spec.independent_seeds_b_delta)
                     else 0)),
                "repeat_id": "r0", "context_id": "primary",
                "wall_s": 0.01, "cpu_s": 0.01,
                "projection_digest":
                    f"d-{arm}" + ("-x" if (digest_shift or
                                           spec.module_cache_contam_b or
                                           spec.persistent_state_cross_proc)
                                  else ""),
                "draw_log_tail": SYNC_TAIL_SHIFTED if shift else SYNC_TAIL,
                "n_draws_logged": 6,
                "artifact_bytes": 128, "ontology_version": "v1",
                "event_keys": [f"e{i}" for i in range(8)],
                "dealer_first_fp": 777,
                "marginals_ok": True, "events_unique": 8,
                "event_duplicates": (3 if (spec.stream_collision_b and
                                           arm == "B") else 0)}
    a = _base("A", "cfg-a")
    b = _base("B", "cfg-b", shift=_tail_shifting(spec),
              digest_shift=_replay_breaking(spec))
    return a, b


def repeat_set(spec, art, digest_shift):
    out = []
    for i in range(max(spec.repeat_pairs, 0)):
        rid = f"dup{i}" if spec.repeat_ids_collide else f"r{i+1}"
        d = dict(art)
        d["repeat_id"] = rid
        d["projection_digest"] = (f"{art['projection_digest']}-{i}"
                                  if digest_shift or spec.repeat_ids_collide
                                  else art["projection_digest"])
        out.append(d)
    return out


def context_records(spec, art_a):
    """Arm-A same-process re-executions diverge ONLY under mechanisms that
    alter every execution of the arm (deadline consumption / queue tax);
    arm-B-targeted corruption leaves them identical."""
    diverges = bool(spec.think_budget_scale > 0 or spec.queue_tax_a or
                    spec.queue_tax_b or spec.module_cache_contam_b)
    recs = []
    for label in ("fresh", "worker2"):
        recs.append({"context_label": label, "pid": 42,
                     "digest": f"{art_a['projection_digest']}"
                               f"{'-ctx' if diverges else ''}",
                     "primary_digest": art_a["projection_digest"],
                     "process_separated": False,
                     "dealer_fp": art_a.get("dealer_first_fp")})
    return recs


def make_row(cid: str) -> list:
    cdef = next(c for c in GRAMMAR["constructions"] if c["id"] == cid)
    rows = []
    for system in ("holdem", "ising"):
        applicable = ("both" in cdef.get("systems", ["both"])
                      or system in cdef.get("systems", []))
        if not applicable:
            continue
        spec = spec_from_construction(cdef)
        spec.declared_seed = 123456789
        art_a, art_b = synthetic_artifacts(spec)
        brk = _replay_breaking(spec)
        drops = bool(spec.drop_rows_mod)
        duplicated = bool(spec.duplicate_row_frac > 0)
        row_plan = {"rows_scheduled": 10,
                    "rows_present_recorded": (7 if drops else 10) +
                                             (1 if duplicated else 0),
                    "ids_unique": not duplicated}
        bundle = build_bundle(
            system, spec, art_a, art_b,
            repeat_set(spec, art_a, brk),
            repeat_set(spec, art_b, brk),
            context_records(spec, art_a), row_plan, cdef, aa_bank_reps=2,
            aa_dispersion_indicator=0,
            ontology_version_a="v1",
            ontology_version_b=("v2" if spec.ontology_drift_b else "v1"))
        if spec.context_scope == "cross_process":
            xd = art_a["projection_digest"]
            bundle = build_bundle_with_crossproc(bundle, [{
                "pid": 99, "context_label": "xproc-99",
                "digest": f"{xd}-x" if spec.persistent_state_cross_proc else xd}],
                xd)
        row = {"system": system, "construction": cid,
               "gt": {k: cdef["gt"].get(k, "NOT_APPLICABLE") for k in
                      ("descriptive", "paired_inference", "replay", "crn",
                       "event_alignment")},
               "B7_csvf_full": classify_all(bundle)}
        for m, fn in BASELINE_FUNCS.items():
            extras = {"aa_bank_reps_available": 2,
                      "aa_outcome_dispersion_indicator": 0} \
                if m == "B1_outcome_aa" else {}
            v = MethodView(m, bundle, extras)
            row[m] = fn(bundle, extras) if m == "B1_outcome_aa" else fn(v)
        rows.append(row)
    return rows


def main():
    rows = []
    for c in GRAMMAR["constructions"]:
        rows.extend(make_row(c["id"]))
    out = {"kind": "EXPECTED_DECISION_TABLE",
           "campaign": "prospective-repair",
           "source": "generated by runner/gen_expected_table.py — do not edit",
           "rows": rows}
    (ROOT / "protocol" / "EXPECTED_DECISION_TABLE.json").write_text(
        json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(f"wrote {len(rows)} expected-decision rows")


if __name__ == "__main__":
    main()
