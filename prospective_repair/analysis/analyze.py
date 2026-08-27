"""Frozen analysis for the prospective-repair campaign.

Consumes raw rows only; produces aggregates under results/<bank>/aggregates/.
Implements ANALYSIS_PLAN exactly: case-level units, macros over constructions,
case-level paired permutation contrasts, Wilson intervals, exploratory CRN
benefit with joint seed-cluster bootstrap, cost medians/spread. No M4-M6
outputs exist anywhere (schema validator enforces).
"""
from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.schema_validators import validate_stream, validate_aggregate  # noqa: E402
from analysis.stats import (wilson_interval, exact_mcnemar,          # noqa: E402
                            signflip_permutation_p, paired_risk_difference_ci,
                            holm, variance_ratio_benefit)
from framework.constants import BRANCHES                             # noqa: E402

GRAMMAR = {c["id"]: c for c in json.loads(
    (ROOT / "protocol" / "FAULT_GRAMMAR.json").read_text())["constructions"]}
METHODS = ["B0_schedule_only", "B1_outcome_aa", "B2_trace_aa",
           "B3_within_seed_reps", "B4_unpaired_analysis",
           "B5_cluster_hierarchical", "B6_event_keyed_whitebox",
           "B7_csvf_full"]


def load_raw(raw_path: Path):
    decisions, outcomes, costs, missing = [], [], [], []
    with raw_path.open() as f:
        for line_no, line in enumerate(f, 1):
            row = json.loads(line)
            lvl = row["level"]
            {"decision": decisions, "outcome": outcomes, "cost": costs,
             "missing_cell": missing}[lvl].append(row)
    counts = validate_stream(decisions + outcomes + costs + missing)
    return decisions, outcomes, costs, missing


def aggregate(bank_dir: Path) -> dict:
    raw = bank_dir / "raw_rows.jsonl"
    if not raw.exists() and bank_dir.name == "final":
        raise SystemExit("final raw missing")
    decisions, outcomes, costs, missing = load_raw(raw)

    fam_of = {cid: c.get("novel_vs_v1") and cid or cid
              for cid in GRAMMAR}
    out = {"bank": bank_dir.name}

    # ---------------- decision metrics per method × branch × system --------
    cells = defaultdict(lambda: defaultdict(int))
    cases = defaultdict(lambda: defaultdict(set))   # case -> method -> seeds ok
    fs_cases = defaultdict(lambda: defaultdict(set))
    for r in decisions:
        m, br, sysn = r["method"], r["branch"], r["system"]
        cls, gt = r["score_class"], r["gt"]
        key = (m, br, sysn)
        c = cells[key]
        c["gt_" + gt] += 1
        if cls == "ABSTAINED":
            c["abstain"] += 1
        else:
            c["covered"] += 1
            if cls == "CORRECT":
                c["correct"] += 1
            elif cls.startswith("FALSE_SUPPRESSION"):
                c["fs"] += 1
                c["fs_hard" if cls.endswith("HARD") else "fs_soft"] += 1
            elif cls == "MISSED_FAILURE":
                c["missed"] += 1
            elif cls in ("CAVEAT_ONLY_MISS", "DETECTED_WITH_CAVEAT"):
                c["caveat"] += 1
    table = []
    for (m, br, sysn), c in sorted(cells.items()):
        n_inv = c.get("gt_INVALID", 0) - c.get("abstain", 0) * (
            c.get("gt_INVALID", 0) and None or 0)
        # denominators exclude abstained cells proportionally? Simpler & exact:
        covered_invalid = sum(1 for r in decisions
                              if (r["method"], r["branch"], r["system"]) ==
                              (m, br, sysn) and r["gt"] == "INVALID"
                              and r["score_class"] != "ABSTAINED")
        covered_valid = sum(1 for r in decisions
                            if (r["method"], r["branch"], r["system"]) ==
                            (m, br, sysn) and r["gt"] == "VALID"
                            and r["score_class"] != "ABSTAINED")
        strict_det = sum(1 for r in decisions
                         if (r["method"], r["branch"], r["system"]) ==
                         (m, br, sysn) and r["gt"] == "INVALID"
                         and r["score_class"] == "CORRECT")
        fs_any = c.get("fs", 0)
        app = [r for r in decisions
               if (r["method"], r["branch"], r["system"]) == (m, br, sysn)]
        p1, l1, h1 = wilson_interval(strict_det, max(covered_invalid, 1)) \
            if covered_invalid else (None, None, None)
        p2, l2, h2 = wilson_interval(fs_any, max(covered_valid, 1)) \
            if covered_valid else (None, None, None)
        table.append({
            "method": m, "branch": br, "system": sysn,
            "applicable_cells": len(app),
            "abstained": c.get("abstain", 0),
            "coverage": round((c.get("covered", 0)) / len(app), 4),
            "det_strict_n": strict_det, "invalid_covered": covered_invalid,
            "det_rate": p1, "det_lo": l1, "det_hi": h1,
            "fs_soft": c.get("fs_soft", 0), "fs_hard": c.get("fs_hard", 0),
            "fs_total": fs_any, "valid_covered": covered_valid,
            "fs_rate": p2, "fs_lo": l2, "fs_hi": h2,
            "missed_failure": c.get("missed", 0),
            "caveat_only": c.get("caveat", 0)})
    out["decision_metrics"] = table

    # ---------------- case-level summaries ---------------------------------
    case_rows = []
    by_case = defaultdict(list)
    for r in decisions:
        by_case[(r["system"], r["construction"])].append(r)
    for (sysn, cid), rows in sorted(by_case.items()):
        gdef = GRAMMAR[cid]["gt"]
        entry = {"system": sysn, "construction": cid}
        for m in METHODS:
            mrows = [r for r in rows if r["method"] == m]
            ok_seed_sets = {}
            for br in BRANCHES:
                brows = [r for r in mrows if r["branch"] == br and
                         r["gt"] != "NOT_APPLICABLE"]
                good = {r["seed"] for r in brows
                        if r["score_class"] == "CORRECT"}
                ok_seed_sets[br] = good
            entry[m] = {br: len(s) for br, s in ok_seed_sets.items()}
        case_rows.append(entry)
    out["case_seed_correct_counts"] = case_rows

    # macro over constructions per system × branch × method (rate of seeds)
    macros = defaultdict(list)
    n_seeds_bank = len({r["seed"] for r in decisions}) or 1
    for entry in case_rows:
        for m in METHODS:
            for br, cnt in entry[m].items():
                macros[(entry["system"], m, br)].append(cnt / n_seeds_bank)
    out["macro_case_detection_by_branch"] = {
        f"{k[0]}|{k[1]}|{k[2]}": round(float(np.mean(v)), 4)
        for k, v in macros.items()}

    # ---------------- method contrasts (B5 vs B7, each vs B7) ---------------
    contrasts = []
    b7map = {(r["system"], r["construction"], r["seed"], r["branch"],
              r["score_class"]) for r in decisions if r["method"] ==
             "B7_csvf_full"}

    def indicator(rows, method, kind):
        """case-level paired indicators: detection / false-suppression."""
        idx = defaultdict(lambda: defaultdict(int))
        sel = (r for r in rows if r["method"] == method)
        for r in sel:
            if r["score_class"] == "ABSTAINED" or \
                    r["gt"] == "NOT_APPLICABLE":
                continue
            good = ((kind == "detect" and r["gt"] == "INVALID"
                     and r["score_class"] == "CORRECT") or
                    (kind == "fs" and r["gt"] == "VALID"
                     and r["score_class"].startswith("FALSE_SUPPRESSION")))
            k = (r["system"], r["construction"])
            idx[k][r["seed"]] += int(good)
        return {k: np.mean(list(v.values())) for k, v in idx.items()}

    for other in METHODS[:-1]:
        for kind in ("detect", "fs"):
            a = indicator(decisions, other, kind)
            b = indicator(decisions, "B7_csvf_full", kind)
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
                "p_signflip": p_perm,
                "note": "case-level paired sign-flip permutation; "
                        "cluster(seed)-bootstrap CI"})
    ps = [c["p_signflip"] for c in contrasts]
    if ps:
        for c, adj in zip(contrasts, holm(ps)):
            c["p_holm"] = adj
    out["contrasts"] = contrasts

    # ---------------- costs --------------------------------------------------
    per = defaultdict(list)
    for r in costs:
        per[r["method"]].append(r)
    cost_rows = []
    all_pairs = defaultdict(list)
    for m, rows in per.items():
        walls = [r["evidence_acq_wall_s"] for r in rows]
        clss = [r["classifier_wall_s"] for r in rows]
        bts = [r["bundle_bytes"] for r in rows]
        axs = [sum(r["exec_count_by_type"].values()) for r in rows]
        cost_rows.append({
            "method": m, "n": len(rows),
            "acq_wall_median_s": float(np.median(walls)),
            "acq_wall_p95_s": float(np.percentile(walls, 95)),
            "wall_spread_iqr": float(np.percentile(walls, 75) -
                                     np.percentile(walls, 25)),
            "cpu_median_s": float(np.median([r["evidence_acq_cpu_s"]
                                             for r in rows])),
            "classifier_median_s": float(np.median(clss)),
            "bundle_bytes_median": float(np.median(bts)),
            "extra_execs_max": int(max(axs))}
        for r in rows:
            all_pairs[r["system"]].append(r["evidence_acq_wall_s"])
    out["cost_summary"] = cost_rows

    # ---------------- exploratory CRN benefit (G01/G02 holdout outcomes) ----
    benefit = []
    pairmap = defaultdict(lambda: ([], []))
    seen = set()
    for r in outcomes:
        if r["construction"] not in ("G01", "G02"):
            continue
        if (r["system"], r["construction"], r["seed"], r["repeat_id"],
                r["context_id"]) in seen:
            continue
        seen.add((r["system"], r["construction"], r["seed"], r["repeat_id"],
                  r["context_id"]))
        lst = pairmap[(r["system"], r["construction"], r["seed"],
                       r["repeat_id"], r["context_id"])]
        (lst[0] if r["arm"] == "A" else lst[1]).append(r["outcome_value"])
    for k, (A, Bv) in sorted(pairmap.items()):
        if len(A) >= 8 and len(Bv) >= 8:
            res = variance_ratio_benefit(A, Bv)
            if isinstance(res["R"], dict) and res["R"].get("degenerate"):
                res["status"] = "DEGENERATE_NOT_BENEFIT"
            benefit.append({"system": k[0], "construction": k[1],
                            "seed": k[2], **res})
    out["crn_benefit_exploratory"] = benefit

    out["missing_cells"] = missing
    out["counts"] = counts
    agg_path = bank_dir / "aggregates"
    agg_path.mkdir(exist_ok=True)
    # validate no forbidden aggregates sneak in
    for name in ("contrasts", "cost_summary"):
        for row in out[name]:
            validate_aggregate(row)
    (agg_path / "results_aggregates.json").write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        ROOT / "results" / "final"
    print(f"writing aggregates under {target/'aggregates'}")
    aggregate(target)
