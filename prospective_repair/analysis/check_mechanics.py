"""Result-excluded pilot/dev mechanics-verification gate.

Inspects ONLY: crash records, schema legality, timing positivity, and whether
each labeled fault mechanism is actually PRESENT in retained structural
evidence. Never computes detection/false-suppression/rankings/effects.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.schema_validators import validate_stream  # noqa: E402


def check(bank_dir: Path):
    problems = []
    meta = json.loads((bank_dir / "run_meta.json").read_text())
    if meta.get("n_crashes", 0) > 0:
        problems.append(f"crashes recorded: {meta['n_crashes']}")

    decisions, outcomes = [], []
    with (bank_dir / "raw_rows.jsonl").open() as f:
        for line in f:
            r = json.loads(line)
            (decisions if r["level"] == "decision" else outcomes).append(r)
    try:
        validate_stream(decisions + outcomes)
    except Exception as e:
        problems.append(f"schema validation failed: {e}")

    pairs = defaultdict(dict)
    for r in outcomes:
        if r["context_id"] == "primary":
            pairs[(r["system"], r["construction"], r["seed"])][r["arm"]] = r

    def bundle(system, cid, seed):
        for r in decisions:
            if (r["system"], r["construction"], r["seed"]) == \
                    (system, cid, seed) and r["method"] == "B7_csvf_full":
                return r["audit_payload"]["bundle"]
        return None

    presence = defaultdict(list)

    def note(cond, sysname, cid, what):
        presence[(cid, what)].append((sysname, bool(cond)))

    for (s, cid, seed), arms in list(pairs.items()):
        A, Bv = arms.get("A"), arms.get("B")
        if not A or not Bv:
            problems.append(f"missing primary arm {s},{cid},{seed}")
            continue
        b = bundle(s, cid, seed)
        if b is None:
            continue
        if cid == "G03":
            note(Bv["effective_seed"] < 65536, s, cid, "trunc16_bites")
        if cid == "G04":
            note(Bv["effective_seed"] < 2 ** 24, s, cid, "trunc24_bites")
        if cid in ("G02", "G19"):
            same = A["projection_digest"] == Bv["projection_digest"]
            note((not same) if cid == "G02" else same, s, cid,
                 "policy_contrast_" + ("preserved" if cid == "G02"
                                       else "collapsed_by_design"))
        if cid in ("G07", "G11"):
            ctxs = json.loads(json.dumps(decisions and [
                rr for rr in decisions
                if rr["method"] == "B7_csvf_full" and
                (rr["system"], rr["construction"], rr["seed"]) ==
                (s, cid, seed)][0]["audit_payload"]["bundle"]["contexts"]))
            digests = {c["digest"] for c in ctxs}
            note(len(digests) > 1, s, cid, "context_digests_diverge")
        if cid == "G11":
            import re as _re
            reps = [r for r in outcomes if (r["system"], r["construction"],
                                            r["seed"]) == (s, cid, seed)
                    if _re.fullmatch(r"r\d+", str(r["repeat_id"]))
                    and str(r["repeat_id"]) != "r0"]
            uniq_rids = {r["repeat_id"] for r in reps}
            n_arm = {r["arm"] for r in reps}
            note(len(reps) == 8 and len(uniq_rids) == 4 and
                 n_arm == {"A", "B"}, s, cid,
                 "paired_repeats_retained_both_arms")
        if cid == "G15":
            x = [r for r in json.loads(json.dumps(
                [rr for rr in decisions
                 if rr["method"] == "B7_csvf_full" and
                 (rr["system"], rr["construction"], rr["seed"]) ==
                 (s, cid, seed)][0]["audit_payload"]["bundle"]["contexts"]))
                if r.get("process_separated")]
            note(bool(x) and any(c["pid"] != 42 for c in x), s, cid,
                 "cross_process_replica_recorded")
            note(any(c["digest"] != c["primary_digest"] for c in x)
                 if x else False, s, cid, "cross_process_diverges")
        if cid == "G16":
            kc = int(b.get("key_collision_count") or 0)
            note(kc > 0, s, cid, "collision_count_positive")

    fail_presence = {k: v for k, v in presence.items()
                     if not all(x[1] for x in v)}
    report = {
        "bank": bank_dir.name,
        "raw_sha256": (bank_dir / "SHA256SUMS").read_text().split()[0],
        "rows_decision": len(decisions),
        "rows_outcome": len(outcomes),
        "missing_cells": meta.get("n_crashes", 0),
        "problems": problems,
        "mechanism_checks_total": sum(len(v) for v in presence.values()),
        "mechanism_check_failures": {f"{k[0]}::{k[1]}": v
                                     for k, v in fail_presence.items()},
        "status": ("PASS" if not problems and not fail_presence else "FAIL"),
    }
    return report


if __name__ == "__main__":
    for d in sys.argv[1:]:
        rep = check(Path(d))
        outp = Path(d) / "aggregates" / "mechanics_verification.json"
        outp.parent.mkdir(exist_ok=True)
        outp.write_text(json.dumps(rep, indent=2))
        print(json.dumps({k: rep[k] for k in
                          ("bank", "status", "rows_decision",
                           "rows_outcome",
                           "mechanism_checks_total",
                           "mechanism_check_failures")}, indent=1))
