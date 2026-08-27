"""Frozen analysis for the prospective-repair campaign.

Consumes raw rows only; produces aggregates under results/<bank>/aggregates/.
Implements ANALYSIS_PLAN exactly: case-level units, macros over constructions,
case-level paired permutation contrasts, Wilson intervals, exploratory CRN
benefit with joint seed-cluster bootstrap, cost medians/spread. No M4-M6
outputs exist anywhere (schema validator enforces).
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.schema_validators import validate_stream, validate_aggregate  # noqa: E402
from analysis.stats import (wilson_interval,                     # noqa: E402
                            signflip_permutation_p,
                            paired_risk_difference_ci, holm,
                            variance_ratio_benefit)
from framework.constants import BRANCHES                         # noqa: E402

METHODS = ["B0_schedule_only", "B1_outcome_aa", "B2_trace_aa",
           "B3_within_seed_reps", "B4_unpaired_analysis",
           "B5_cluster_hierarchical", "B6_event_keyed_whitebox",
           "B7_csvf_full"]


def load_raw(raw_path: Path):
    decisions, outcomes, costs, missing = [], [], [], []
    with raw_path.open() as f:
        for line in f:
            row = json.loads(line)
            lvl = row["level"]
            {"decision": decisions, "outcome": outcomes, "cost": costs,
             "missing_cell": missing}[lvl].append(row)
    counts = validate_stream(decisions + outcomes + costs + missing)
    return decisions, outcomes, costs, missing


def metric_rows(decisions) -> list:
    per_key = defaultdict(list)
    for r in decisions:
        per_key[(r["method"], r["branch"], r["system"])].append(r)
    rows = []
    for (m, br, sysn), app in sorted(per_key.items()):
        covered = [r for r in app if r["score_class"] != "ABSTAINED"]
        inv = [r for r in covered if r["gt"] == "INVALID"]
        val = [r for r in covered if r["gt"] == "VALID"]
        strict = [r for r in inv if r["score_class"] == "CORRECT"]
        fs_rows = [r for r in val
                   if r["score_class"].startswith("FALSE_SUPPRESSION")]
        p1, l1, h1 = wilson_interval(len(strict), len(inv)) if inv else \
            (None, None, None)
        p2, l2, h2 = wilson_interval(len(fs_rows), len(val)) if val else \
            (None, None, None)
        rows.append({
            "method": m, "branch": br, "system": sysn,
            "applicable_cells": len(app),
            "abstained": len(app) - len(covered),
            "coverage": round(len(covered) / len(app), 4) if app else 0.0,
            "det_strict_n": len(strict), "invalid_covered": len(inv),
            "det_rate": p1, "det_lo": l1, "det_hi": h1,
            "fs_soft": sum(1 for r in fs_rows
                           if r["score_class"].endswith("SOFT")),
            "fs_hard": sum(1 for r in fs_rows
                           if r["score_class"].endswith("HARD")),
            "fs_total": len(fs_rows), "valid_covered": len(val),
            "fs_rate": p2, "fs_lo": l2, "fs_hi": h2,
            "missed_failure": sum(1 for r in inv
                                  if r["score_class"] == "MISSED_FAILURE"),
            "caveat_only": sum(1 for r in covered if
                               r["score_class"] in ("CAVEAT_ONLY_MISS",
                                                    "DETECTED_WITH_CAVEAT"))})
    return rows


def case_table(decisions) -> list:
    by_case = defaultdict(list)
    for r in decisions:
        by_case[(r["system"], r["construction"])].append(r)
    out = []
    for (sysn, cid), rows in sorted(by_case.items()):
        entry = {"system": sysn, "construction": cid}
        for m in METHODS:
            counts = {}
            for br in BRANCHES:
                brows = [r for r in rows if r["method"] == m and
                         r["branch"] == br and r["gt"] != "NOT_APPLICABLE"]
                counts[br] = len({r["seed"] for r in brows
                                  if r["score_class"] == "CORRECT"})
            entry[m] = counts
        out.append(entry)
    return out


def macro_block(case_rows, n_seeds: int) -> dict:
    acc = defaultdict(list)
    for e in case_rows:
        for m in METHODS:
            for br, cnt in e[m].items():
                acc[(e["system"], m, br)].append(cnt / max(n_seeds, 1))
    return {f"{k[0]}|{k[1]}|{k[2]}": round(float(np.mean(v)), 4)
            for k, v in acc.items()}


def contrasts_block(decisions) -> list:
    def indicator(method, kind):
        idx = defaultdict(dict)
        for r in decisions:
            if r["method"] != method or r["gt"] == "NOT_APPLICABLE" or \
                    r["score_class"] == "ABSTAINED":
                continue
            good = ((kind == "detect" and r["gt"] == "INVALID" and
                     r["score_class"] == "CORRECT") or
                    (kind == "fs" and r["gt"] == "VALID" and
                     r["score_class"].startswith("FALSE_SUPPRESSION")))
            idx[(r["system"], r["construction"])][r["seed"]] = \
                idx[(r["system"], r["construction"])].get(r["seed"], 0) + \
                int(good)
        return {k: float(np.mean(list(v.values()))) for k, v in idx.items()}

    contrasts = []
    for other in METHODS[:-1]:
        for kind in ("detect", "fs"):
            a = indicator(other, kind)
            b = indicator("B7_csvf_full", kind)
            keys = sorted(set(a) & set(b))
            diffs = np.array([a[k] - b[k] for k in keys])
            if len(diffs) < 3 or not np.any(diffs):
                continue
            p_perm = signflip_permutation_p(diffs, rng_seed=20260827)
            mean, lo, hi = paired_risk_difference_ci(diffs)
            contrasts.append({
                "contrast": f"{other} - B7 [{kind}]",
                "n_cases": len(keys),
                "mean_risk_diff": round(mean, 4), "ci_lo": lo, "ci_hi": hi,
                "p_signflip": p_perm})
    ps = [c["p_signflip"] for c in contrasts]
    if ps:
        for c, adj in zip(contrasts, holm(ps)):
            c["p_holm"] = adj
    return contrasts


def cost_block(costs) -> list:
    per = defaultdict(list)
    for r in costs:
        per[r["method"]].append(r)
    rows = []
    for m in METHODS:
        rs = per.get(m, [])
        if not rs:
            continue
        walls = [r["evidence_acq_wall_s"] for r in rs]
        bts = [r["bundle_bytes"] for r in rs]
        axs = [sum(r["exec_count_by_type"].values()) for r in rs]
        rows.append({"method": m, "n": len(rs),
                     "acq_wall_median_s": round(float(np.median(walls)), 6),
                     "acq_wall_p95_s": round(float(np.percentile(walls, 95)),
                                             6),
                     "wall_spread_iqr": round(float(np.percentile(walls, 75) -
                                                   np.percentile(walls, 25)),
                                              6),
                     "cpu_median_s": round(float(np.median(
                         [r["evidence_acq_cpu_s"] for r in rs])), 6),
                     "classifier_median_s": round(float(np.median(
                         [r["classifier_wall_s"] for r in rs])), 8),
                     "bundle_bytes_median": float(np.median(bts)),
                     "extra_execs_max": int(max(axs))})
    return rows


def benefit_block(outcomes) -> list:
    pairmap = defaultdict(lambda: ([], []))
    seen = set()
    for r in outcomes:
        if r["construction"] not in ("G01", "G02") or \
                r["context_id"] != "primary":
            continue
        k = (r["system"], r["construction"], r["seed"], r["repeat_id"])
        if k in seen:
            continue
        seen.add(k)
        lst = pairmap[k]
        (lst[0] if r["arm"] == "A" else lst[1]).append(r["outcome_value"])
    rows = []
    for k in sorted(pairmap):
        A, Bv = pairmap[k]
        if min(len(A), len(Bv)) >= 8:
            res = variance_ratio_benefit(A, Bv)
            status = res.pop("status")
            R = res["R"]
            if isinstance(R, dict) and R.get("degenerate"):
                status = "DEGENERATE_NOT_BENEFIT"
                R = None
            rows.append({"system": k[0], "construction": k[1],
                         "seed": k[2], "repeat": k[3], **res,
                         "status": status})
    return rows


def aggregate(bank_dir: Path) -> dict:
    raw = bank_dir / "raw_rows.jsonl"
    if not raw.exists():
        raise SystemExit(f"raw missing: {raw}")
    decisions, outcomes, costs, missing = load_raw(raw)
    n_seeds = len({(r["system"], r["seed"]) for r in decisions}) // 2

    out = {
        "bank": bank_dir.name,
        "counts": {"decision": len(decisions), "outcome": len(outcomes),
                   "cost": len(costs), "missing_cell": len(missing)},
        "decision_metrics": metric_rows(decisions),
        "case_seed_correct_counts": case_table(decisions),
    }
    out["macro_case_detection_by_branch"] = macro_block(
        out["case_seed_correct_counts"],
        len({r["seed"] for r in decisions}))
    out["contrasts"] = contrasts_block(decisions)
    out["cost_summary"] = cost_block(costs)
    out["crn_benefit_exploratory"] = benefit_block(outcomes)
    out["missing_cells"] = missing

    for section in ("contrasts", "cost_summary"):
        for row in out[section]:
            validate_aggregate(row)

    agg_path = bank_dir / "aggregates"
    agg_path.mkdir(exist_ok=True)
    (agg_path / "results_aggregates.json").write_text(
        json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        ROOT / "results" / "final"
    aggregate(target)
    print("aggregates written:", target / "aggregates")
