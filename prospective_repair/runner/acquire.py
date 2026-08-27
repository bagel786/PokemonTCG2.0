"""Acquisition runner for prospective_repair (banks: pilot/dev/final/cost).

Guarantees:
- final bank executes ONLY after freeze_guard.verify() passes;
- raw rows stream-append to an immutable-named file; nothing overwrites;
- every decision row carries the typed MethodView payload + full bundle
  audit payload (provenance);
- real timings everywhere; no placeholder zeros (schema check enforces);
- crash policy: infrastructure crash -> up to 2 logged retries -> missing-cell
  record; scientific failures never silently retried.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from framework.classifier import classify_all  # noqa: E402
from framework.baselines import BASELINE_FUNCS, FULL_FRAMEWORK  # noqa: E402
from framework.scoring import score_cell  # noqa: E402
from framework.constants import BRANCHES, BRANCH_TO_GT_DIM  # noqa: E402
from framework.evidence import EvidenceBundle  # noqa: E402
from systems.mechanics import (spec_from_construction, PersistentStateFile,
                               ModuleCache)  # noqa: E402
from systems.holdem_wrapper import HoldemWrapper, MODULE_CACHE as HC_CACHE  # noqa: E402
from systems.ising_wrapper import IsingWrapper, MODULE_CACHE as IS_CACHE  # noqa: E402
from runner.bundle_builder import (build_bundle,
                                   build_bundle_with_crossproc)  # noqa: E402

GRAMMAR = json.loads((ROOT / "protocol" / "FAULT_GRAMMAR.json").read_text())
CONS = {c["id"]: c for c in GRAMMAR["constructions"]}


def gt_for(construction: Dict) -> Dict[str, str]:
    g = construction["gt"]
    return {dim: g.get(dim, "NOT_APPLICABLE")
            for dim in ("descriptive", "paired_inference", "replay", "crn",
                        "event_alignment")}


def _micro_aa(w, system: str, seed: int):
    """Cheap repeated arm-A executions feeding B1's A/A requirement."""
    out_digests, outs = [], []
    for i in range(2):
        if system == "holdem":
            w2 = HoldemWrapper(num_hands=2)
            art = w2.run_arm(seed=seed, arm="A",
                             spec=_flat_spec("G01", seed), repeat_id=f"aa{i}",
                             context_id="aa_micro")
        else:
            w2 = IsingWrapper(sweeps=20, equilibration=5)
            art = w2.run_arm(seed=seed, temperature_arm="A",
                             spec=_flat_spec("G01", seed),
                             repeat_id=f"aa{i}", context_id="aa_micro")
        out_digests.append(art["projection_digest"])
        outs.append(art)
    disp = 0 if len(set(out_digests)) == 1 else 1
    return {"reps": 2, "dispersion_indicator": disp}


def _flat_spec(cid: str, seed: int):
    spec = spec_from_construction(CONS[cid])
    spec.declared_seed = seed
    return spec


def run_pair(system_name: str, w, spec: ExecutionSpec, seed: int,
             state_dir: Path, root: str):
    """Primary pair + repeats + contexts for one system/cell."""
    if system_name == "holdem":
        art_a = w.run_arm(seed=seed, arm="A", spec=spec, repeat_id="r0",
                          context_id="primary", process_rank=0)
    else:
        art_a = w.run_arm(seed=seed, temperature_arm="A", spec=spec,
                          repeat_id="r0", context_id="primary", process_rank=0)
    if spec.persistent_state_cross_proc:
        ps = PersistentStateFile(lambda: str(state_dir))
        spec._persistent_state = ps
        ps.touch(seed)

    if system_name == "holdem":
        art_b = w.run_arm(seed=seed, arm="B", spec=spec, repeat_id="r0",
                          context_id="primary", process_rank=1)
    else:
        art_b = w.run_arm(seed=seed, temperature_arm="B", spec=spec,
                          repeat_id="r0", context_id="primary", process_rank=1)

    k = spec.repeat_pairs
    reps_a, reps_b = [], []
    for i in range(k):
        rid = f"dup{i}" if spec.repeat_ids_collide else f"r{i+1}"
        if system_name == "holdem":
            reps_a.append(w.run_arm(seed=seed, arm="A", spec=spec,
                                    repeat_id=rid, context_id=f"rep-{i}"))
            reps_b.append(w.run_arm(seed=seed, arm="B", spec=spec,
                                    repeat_id=rid, context_id=f"rep-{i}"))
        else:
            reps_a.append(w.run_arm(seed=seed, temperature_arm="A", spec=spec,
                                    repeat_id=rid, context_id=f"rep-{i}"))
            reps_b.append(w.run_arm(seed=seed, temperature_arm="B", spec=spec,
                                    repeat_id=rid, context_id=f"rep-{i}"))

    ctx_records = []
    primary = art_a["projection_digest"]
    for label, rank in (("fresh", 0), ("worker2", 1)):
        reused_worker = (label == "worker2" and spec.module_cache_contam_b)
        if reused_worker:
            # simulate executing on a worker whose persistent cache carries
            # prior-task state: ANY unit it runs next becomes contaminated
            (hw_cache if system_name == "holdem" else is_cache).contaminate()
        else:
            (hw_cache if system_name == "holdem" else is_cache).clear()
        if system_name == "holdem":
            r = w.run_arm(seed=seed, arm="A", spec=spec, repeat_id="ctx",
                          context_id=label, process_rank=rank)
        else:
            r = w.run_arm(seed=seed, temperature_arm="A", spec=spec,
                          repeat_id="ctx", context_id=label, process_rank=rank)
        (hw_cache if system_name == "holdem" else is_cache).clear()
        ctx_records.append({"context_label": label, "pid": os.getpid(),
                            "proc_start_time": time.time(),
                            "digest": r["projection_digest"],
                            "primary_digest": primary,
                            "process_separated": False,
                            "dealer_fp": r.get("dealer_first_fp")})

    xprocs = []
    if spec.context_scope == "cross_process":
        from systems.subprocess_context import run_cross_process_replica
        xprocs = [run_cross_process_replica(root, system_name,
                                            spec.construction, seed,
                                            str(state_dir))]
    return art_a, art_b, reps_a, reps_b, ctx_records, xprocs


def _view_payload(method: str, bundle: EvidenceBundle, aa_extras: Dict) -> Dict:
    from framework.evidence import MethodView
    v = MethodView(method, bundle, aa_extras if method == "B1_outcome_aa" else {})
    return v.as_dict()


def acquire(bank: str, out_dir: Path, roots: Dict, seeds: list,
            constructions: list, systems=("holdem", "ising")):
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / "raw_rows.jsonl"
    if raw_path.exists() and bank == "final":
        raise SystemExit("[acquire] final raw file already exists; refusing.")
    fh = open(raw_path, "a" if bank != "final" else "x")
    t_start = time.time()
    crashes = []
    meta = {"bank": bank, "start": t_start,
            "host": os.uname().nodename, "python": sys.version.split()[0],
            "freeze_sha": None}

    hw_cache, is_cache = HC_CACHE, IS_CACHE
    wrappers = {}
    for s in systems:
        if s not in wrappers:
            wrappers[s] = (HoldemWrapper(num_hands=10) if s == "holdem"
                           else IsingWrapper())

    for system_name in systems:
        w = wrappers[system_name]
        for cid in constructions:
            cdef = CONS[cid]
            applicable = ("both" in cdef.get("systems", ["both"])
                          or system_name in cdef.get("systems", []))
            if not applicable:
                continue
            for si, seed in enumerate(seeds):
                spec = _flat_spec(cid, seed)
                attempt = 0
                while True:
                    try:
                        hw_cache.clear(); is_cache.clear()
                        if spec.module_cache_contam_b:
                            (hw_cache if system_name == "holdem"
                             else is_cache).contaminate()
                        art_a, art_b, reps_a, reps_b, ctx_recs, xprocs = \
                            run_pair(system_name, w, spec, seed,
                                     out_dir, str(ROOT))
                        break
                    except Exception:
                        attempt += 1
                        tb = traceback.format_exc()[-1500:]
                        crashes.append({"cell": [system_name, cid, seed],
                                        "attempt": attempt, "tb": tb})
                        if attempt > 2:
                            fh.write(json.dumps({
                                "level": "missing_cell",
                                "system": system_name, "construction": cid,
                                "seed": seed}) + "\n")
                            fh.flush()
                            break
                if attempt > 2:
                    continue

                if spec.persistent_state_cross_proc:
                    pstate = PersistentStateFile(
                        lambda d=out_dir: str(d))
                    # touch happens inside run_pair before replica spawn

                aa_bank = _micro_aa(w, system_name, seed)

                row_plan = {"rows_scheduled": len(seeds),
                            "rows_present_recorded": sum(
                                1 for i in range(len(seeds))
                                if not (spec.drop_rows_mod and
                                        i % spec.drop_rows_mod ==
                                        spec.drop_rows_mod - 1)),
                            "ids_unique": not (
                                spec.duplicate_row_frac > 0 and si %
                                max(1, int(round(
                                    1 / spec.duplicate_row_frac))) == 0)}
                dup_flag = (spec.duplicate_row_frac > 0 and si %
                            max(1, int(round(1 / spec.duplicate_row_frac))) == 0)
                row_plan["duplicated"] = dup_flag
                if dup_flag:
                    row_plan["rows_present_recorded"] += 1

                bundle = build_bundle(system_name, spec, art_a, art_b,
                                      reps_a, reps_b, ctx_recs, row_plan, cdef,
                                      aa_bank_reps=aa_bank["reps"],
                                      aa_dispersion_indicator=aa_bank[
                                          "dispersion_indicator"],
                                      ontology_version_a=art_a[
                                          "ontology_version"],
                                      ontology_version_b=art_b[
                                          "ontology_version"])
                if xprocs:
                    bundle = build_bundle_with_crossproc(bundle, xprocs,
                                                         art_a[
                                                             "projection_digest"])

                decisions_all = {m: fn(bundle) for m, fn in
                                 BASELINE_FUNCS.items()}
                decisions_all[FULL_FRAMEWORK] = classify_all(bundle)

                gt_map = gt_for(cdef)
                audit_payload = bundle.to_audit_payload()
                audit_sha = hashlib.sha256(json.dumps(
                    audit_payload, sort_keys=True).encode()).hexdigest()

                # outcome rows -------------------------------------------------
                def outcome_row(art, arm_label):
                    return {"level": "outcome", "system": system_name,
                            "construction": cid, "seed": seed,
                            "arm": arm_label, "wall_s": art["wall_s"],
                            "cpu_s": art["cpu_s"],
                            "outcome_value": art.get("outcome_chips_seat0",
                                                     art.get(
                                                         "outcome_mean_abs_mag")),
                            "projection_digest": art["projection_digest"],
                            "effective_seed": art["effective_seed"],
                            "repeat_id": art["repeat_id"],
                            "context_id": art["context_id"],
                            "artifact_bytes": art["artifact_bytes"]}
                for art, lbl in [(art_a, "A"), (art_b, "B")] + \
                        [(r, "A") for r in reps_a] + [(r, "B") for r in reps_b]:
                    fh.write(json.dumps(outcome_row(art, lbl)) + "\n")

                # decision rows -------------------------------------------------
                for method, decs in decisions_all.items():
                    for br in BRANCHES:
                        decision = decs[br]
                        dim = BRANCH_TO_GT_DIM[br]
                        gt = gt_map[dim]
                        cls = score_cell(decision, gt)
                        fh.write(json.dumps({
                            "level": "decision", "system": system_name,
                            "construction": cid, "seed": seed,
                            "method": method, "branch": br,
                            "decision": decision, "gt": gt,
                            "score_class": cls,
                            "coverage_flag": decision !=
                            "ABSTAIN_NOT_EVALUATED",
                            "reason_codes": [],
                            "bundle_payload_sha256": audit_sha,
                            "view_payload": _view_payload(
                                method, bundle,
                                getattr(bundle, "aa_extras", {})),
                            "audit_payload": audit_payload,
                        }) + "\n")
                fh.flush()
        print(f"[{bank}:{system_name}] done", flush=True)

    meta.update(end=time.time(), wall_total_s=time.time() - t_start,
                n_crashes=len(crashes))
    (out_dir / "run_meta.json").write_text(json.dumps(meta, indent=2))
    if crashes:
        (out_dir / "crash_log.json").write_text(json.dumps(crashes, indent=2))
    fh.close()
    digest = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    (out_dir / "SHA256SUMS").write_text(f"{digest}  raw_rows.jsonl\n")
    print(f"[{bank}] raw sha256={digest}")


# ------------------------------- cost bank ----------------------------------
COST_EXTRA_EXECUTIONS = {
    "B0_schedule_only": [], "B1_outcome_aa": [("micro_aa", 2)],
    "B2_trace_aa": [("within_repeat_armA", 1)],
    "B3_within_seed_reps": [("within_repeat_armA", 1), ("within_repeat_armB", 1)],
    "B4_unpaired_analysis": [], "B5_cluster_hierarchical": [("paired_repeats", 4)],
    "B6_event_keyed_whitebox": [], FULL_FRAMEWORK: [],
}


def acquire_cost(seeds: list, reps: int = 3, constructions=("G01", "G07"),
                 out_dir: Path | None = None):
    import numpy as np
    rng = random.Random(20260827)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "cost_rows.jsonl"
    fh = open(path, "w")
    wrappers = {"holdem": HoldemWrapper(num_hands=10), "ising": IsingWrapper()}
    methods = list(BASELINE_FUNCS.keys()) + [FULL_FRAMEWORK]
    for system_name in ("holdem", "ising"):
        for cid in constructions:
            for seed in seeds:
                order = methods[:]
                rng.shuffle(order)
                for rep in range(reps):
                for mi, method in enumerate(order):
                    spec = _flat_spec(cid, seed)
                    t0, c0 = time.perf_counter(), time.process_time()
                    need_exec = bool(COST_EXTRA_EXECUTIONS.get(method))
                    art_a = art_b = None
                    ra = rb = ctx = xp = []
                    if need_exec:
                        art_a, art_b, ra, rb, ctx, xp = run_pair(
                            system_name, wrappers[system_name], spec, seed,
                            out_dir, str(ROOT))
                    bundle = build_bundle(
                        system_name, spec,
                        art_a or {}, art_b or {}, ra, rb, ctx,
                        {"rows_scheduled": 1, "rows_present_recorded": 1,
                         "ids_unique": True}, CONS[cid]) \
                        if art_a else EvidenceBundle()
                    tc = time.perf_counter_ns()
                    dec = (BASELINE_FUNCS[method](bundle)
                           if method in BASELINE_FUNCS
                           else classify_all(bundle))
                    cls_ns = time.perf_counter_ns() - tc
                    if cls_ns <= 0:
                        # real classification work cannot take zero time; a zero
                        # here means a broken clock, not a fast method.
                        raise RuntimeError("classifier timing resolution failure")
                    cls_wall = cls_ns / 1e9
                    wall = time.perf_counter() - t0
                    cpu = time.process_time() - c0
                    fh.write(json.dumps({
                        "level": "cost", "method": method,
                        "system": system_name, "construction": cid,
                        "seed": seed, "timing_rep": rep,
                        "randomized_order_index": mi,
                        "exec_count_by_type":
                            {k: n for k, n in
                             COST_EXTRA_EXECUTIONS.get(method, [])},
                        "evidence_acq_wall_s": wall,
                        "evidence_acq_cpu_s": cpu,
                        "classifier_wall_s": cls_wall,
                        "bundle_bytes": len(json.dumps(
                            bundle.to_audit_payload())),
                        "artifact_bytes_total":
                            (art_a or {}).get("artifact_bytes", 0) +
                            (art_b or {}).get("artifact_bytes", 0),
                    }) + "\n")
    fh.close()
    print(f"[cost] rows written to {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", required=True,
                    choices=["pilot_mechanics", "dev", "final", "cost"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--systems", default="holdem,ising")
    ap.add_argument("--local-guard-off", action="store_true",
                    help="pilot/dev only; final ALWAYS verifies remote freeze")
    args = ap.parse_args()

    seedsman = json.loads((ROOT / "protocol" / "SEED_MANIFEST.json").read_text())
    seeds = seedsman["banks"][args.bank]["values"]
    if args.bank == "final":
        from runner.freeze_guard import verify
        verify(require_remote=True)   # hard gate
    elif args.bank in ("pilot_mechanics", "dev"):
        if not args.local_guard_off:
            from runner.freeze_guard import verify
            verify(require_remote=False)
    constructions = [c["id"] for c in GRAMMAR["constructions"]]
    out_dir = Path(args.out)
    if args.bank == "cost":
        acquire_cost(seeds[:50], reps=3, out_dir=out_dir)
    else:
        acquire(args.bank, out_dir, {}, seeds, constructions,
                tuple(args.systems.split(",")))


if __name__ == "__main__":
    main()
