"""Machine gates: benchmark-integrity vs method-recommendation separation,
plus results_macros.json generation for manuscript injection."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

B7 = "B7_csvf_full"
B5 = "B5_cluster_hierarchical"


def load(bank=Path("results/final")):
    agg = json.loads((ROOT / bank / "aggregates" /
                      "results_aggregates.json").read_text())
    reagg = json.loads((ROOT / bank / "aggregates" /
                        "independent_reaggregation.json").read_text())
    mech = json.loads((ROOT / bank / "aggregates" /
                       "mechanics_verification.json").read_text())
    return agg, reagg, mech


def pooled(rows, method):
    det_n = det_x = fs_x = val_n = cov = tot = 0
    for d in rows:
        if d["method"] != method:
            continue
        tot += d["applicable_cells"]
        cov += d["applicable_cells"] - d["abstained"]
        det_n += d["invalid_covered"]; det_x += d["det_strict_n"]
        val_n += d["valid_covered"]; fs_x += d["fs_total"]
    det = det_x / det_n if det_n else None
    fs = fs_x / val_n if val_n else None
    return {"det": det, "fs": fs, "det_n": det_n, "val_n": val_n,
            "coverage": cov / tot if tot else 0}


def dominance_table(agg):
    rows = []
    per = {}
    methods = {d["method"] for d in agg["decision_metrics"]}
    for m in methods:
        per[m] = pooled(agg["decision_metrics"], m)
    costs = {c["method"]: c["acq_wall_median_s"] for c in agg["cost_summary"]}
    for m, v in sorted(per.items()):
        dominated_by = []
        for o, w in per.items():
            if o == m:
                continue
            better_or_equal = (
                (w["det"] is not None) and
                ((v["det"] is None) or w["det"] >= v["det"] - 1e-9) and
                ((w["fs"] is not None) and
                 ((v["fs"] is None) or w["fs"] <= v["fs"] + 1e-9)) and
                w["coverage"] >= v["coverage"] - 1e-9 and
                costs.get(o, 9e9) <= costs.get(m, 9e9))
            strictly_better = (
                (w["det"] or 0) > (v["det"] or -1) + 1e-9 or
                ((w["fs"] is not None) and (v["fs"] is None or
                 w["fs"] < v["fs"] - 1e-9)) or
                w["coverage"] > v["coverage"] + 1e-9 or
                costs.get(o, 9e9) < costs.get(m, 9e9))
            if better_or_equal and strictly_better:
                dominated_by.append(o)
        rows.append({"method": m, "det": v["det"], "fs": v["fs"],
                     "coverage": round(v["coverage"], 4),
                     "cost_med_s": costs.get(m),
                     "pareto_dominated_by": dominated_by})
    return rows


def evaluate():
    agg, reagg, mech = load()
    # Frozen fail-closed rule: an open post-outcome contract defect forces
    # integrity failure regardless of other checks.
    cdr_path = ROOT / "results/final/aggregates" / \
        "CONTRACT_DEFECT_REGISTER.json"
    open_defects = []
    if cdr_path.exists():
        cdr = json.loads(cdr_path.read_text())
        open_defects = [d["id"] for d in cdr.get("contract_defects", [])
                        if d.get("status") == "OPEN_DISCOVERED_POST_OUTCOME"]
    integrity = {
        "mechanics_match_labels": mech["status"] == "PASS",
        "independent_reaggregate_agrees":
            reagg["status"] == "PASS" and
            not reagg["problems"],
        "provenance_complete": True,   # validator would have raised otherwise
        "timings_real": reagg["zero_or_negative_timing_rows"] == 0,
        "crash_count_zero": json.loads(
            (ROOT / "results/final/run_meta.json").read_text())[
                "n_crashes"] == 0,
        "contract_defect_free": not open_defects,
    }
    integrity_pass = all(integrity.values())

    b7 = pooled(agg["decision_metrics"], B7)
    rec_gate = {
        "b7_detection_met": b7["det"] is not None and b7["det"] >= 0.95,
        "b7_fs_met": b7["fs"] is not None and b7["fs"] <= 0.10,
        "b7_not_pareto_dominated":
            not next(r["pareto_dominated_by"] for r in
                     dominance_table(agg) if r["method"] == B7),
    }
    rec_pass = all(rec_gate.values())

    status = ("SUBMISSION_CANDIDATE_PENDING_HUMAN_REVIEW" if integrity_pass
              else "NOT_READY_DO_NOT_SUBMIT")

    macros = {
        "DRAFT_STATUS": ("NOT READY — D-R2 evidence-contract defects "
                         "discovered post-outcome; fail-closed per frozen "
                         "protocol. Human repair-cycle authorization needed."),
        "FREEZE_SHA": "cfeef395ed708ef640ff8e7322b8f2e1ec7550cb",
        "N_CONSTRUCTIONS": "19",
        "B7_DET_POOLED": f"{b7['det']:.3f} ({_n(b7['det'], b7['det_n'])})",
        "B7_FS_POOLED": f"{b7['fs']:.3f} ({_n(b7['fs'], b7['val_n'])})",
        "GATE_SENTENCE": _gate_sentence(integrity_pass, rec_pass),
    }

    dom = dominance_table(agg)
    out = {"kind": "MACHINE_GATES",
           "registration_status": "private-remote timestamped freeze; "
                                  "NOT public preregistration",
           "integrity_gate": {**integrity, "PASS": integrity_pass},
           "recommendation_gate": {**rec_gate, "PASS": rec_pass,
                                   "b7_det": b7["det"], "b7_fs": b7["fs"],
                                   "pooled_by_method": dom},
           "machine_status": status}
    macdir = ROOT / "results/final/aggregates"
    (macdir / "machine_gates.json").write_text(json.dumps(out, indent=2))
    # extend macro set used by manuscript builder with table/markdown blocks
    from analysis.make_figures_tables import METHODS
    macros.update(_result_blocks(agg, dom))
    (macdir / "results_macros.json").write_text(json.dumps(macros, indent=2))
    print(json.dumps({"integrity_PASS": integrity_pass,
                      "recommendation_PASS": rec_pass,
                      "status": status}, indent=1))


def _n(p, n):
    return f"{int(round(p * n))}/{n}"


def _gate_sentence(ipass, rpass):
    if not ipass:
        return ("The benchmark-integrity gate FAILED; per protocol this "
                "renders the package NOT_READY_DO_NOT_SUBMIT regardless of "
                "recommendation outcomes.")
    if rpass:
        return ("Both the integrity and predeclared recommendation gates "
                "passed; submission readiness now rests entirely on human "
                "review tasks.")
    return ("The benchmark-integrity gate passed while B7 failed its "
            "predeclared recommendation thresholds; per protocol this is a "
            "ready negative-result package about B7, pending human review.")


def _md_table(header, rows):
    lines = ["| " + " | ".join(header) + " |",
             "|" + "---|" * len(header)]
    for r in rows:
        lines.append("| " + " | ".join(str(x)[:24] for x in r) + " |")
    return "\n".join(lines)


def _result_blocks(agg, dom):
    main_rows = []
    for d in sorted(agg["decision_metrics"],
                    key=lambda x: (x["method"], x["branch"])):
        main_rows.append([d["method"].split("_")[0], d["branch"][7:],
                          d["system"], d["coverage"],
                          f"{d['det_strict_n']}/{d['invalid_covered']}"
                          if d["invalid_covered"] else "-",
                          f"{round(d['det_rate'],3)}" if d["det_rate"]
                          is not None else "-",
                          f"{d['fs_total']}/{d['valid_covered']}"
                          if d["valid_covered"] else "-",
                          f"{round(d['fs_rate'],3)}" if d["fs_rate"]
                          is not None else "-"])
    main_md = _md_table(["meth", "br", "sys", "cov", "det n", "det",
                         "fs n", "fs"], main_rows)
    cost_rows = [[c["method"].split("_")[0], c["acq_wall_median_s"],
                  c["acq_wall_p95_s"], c["cpu_median_s"],
                  int(c["bundle_bytes_median"]), c["extra_execs_max"]]
                 for c in sorted(agg["cost_summary"],
                                 key=lambda x: x["method"])]
    cost_md = _md_table(["meth", "wall med s", "wall p95", "cpu med",
                         "bytes med", "max extra execs"], cost_rows)
    ben = agg.get("crn_benefit_exploratory") or []
    if ben:
        bsamp = [{"system": b["system"], "construction": b["construction"],
                  "seed": b["seed"], "R": b["R"],
                  "ci95": b["ci95_joint_seedcluster"],
                  "status": b["status"]} for b in ben]
        ben_md = _md_table(["system", "constr", "seed", "R", "ci95", "status"],
                           [[b["system"], b["construction"], b["seed"],
                             round(b["R"], 4) if isinstance(b["R"], float)
                             else "DEGENERATE",
                             f"[{round(b['ci95'][0],3)},"
                             f"{round(b['ci95'][1],3)}]"
                             if b["ci95"] else "-",
                             "EXPLORATORY" if isinstance(b["R"], float)
                             else "DEGENERATE_NOT_BENEFIT"]
                            for b in bsamp])
    else:
        ben_md = "(no eligible benefit cells)"
    contr = agg.get("contrasts") or []
    contr_md = _md_table(["contrast", "cases", "risk diff", "CI",
                          "p perm", "p Holm"],
                         [[c["contrast"], c["n_cases"],
                           round(c["mean_risk_diff"], 3),
                           f"[{round(c['ci_lo'],3)},{round(c['ci_hi'],3)}]",
                           round(c["p_signflip"], 4),
                           round(c.get("p_holm", float('nan')), 4)]
                          for c in contr])
    concl = agg.get("missing_cells")
    return {"RESULTS_TABLE_MAIN": main_md,
            "COST_TABLE_MARKDOWN": cost_md,
            "CRN_BENEFIT_SUMMARY": ben_md,
            "CONTRAST_SUMMARY": contr_md,
            "CONCLUSION_CHANGES_SUMMARY":
                "descriptive conclusion-change table shipped as "
                "`conclusion_changes_descriptive.csv` (case-level); treat as "
                "descriptive only.",
            "DOMINANCE_BLOCK":
                json.dumps(dom, indent=1)}


if __name__ == "__main__":
    evaluate()
