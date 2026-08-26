"""Complete the frozen P13 analysis and emit audit-friendly source tables.

This script does not change the frozen classifications or thresholds. It adds
the outputs omitted by the prospectively written ``analyze.py`` and marks
metrics that cannot be estimated as predeclared from the retained raw schema.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import stats


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "results/final/raw/decisions_and_pairs.jsonl"
AGG = ROOT / "results/final/aggregates"
SEEDS = ROOT / "protocol/SEED_MANIFEST.json"
EXPECTED = ROOT / "protocol/EXPECTED_DECISION_TABLE.json"
Z = 1.959964
METHODS = [
    "B0_schedule_only", "B1_outcome_aa", "B2_trace_aa",
    "B3_within_seed_reps", "B4_unpaired", "B5_cluster_hier",
    "B6_event_keyed_wb", "B7_csvf_full",
]
BRANCHES = [f"BRANCH_{x}" for x in "ABCDE"]
SCENARIOS = [f"S{i}" for i in range(11)]
PRIMARY_SCENARIOS = {"S0", "S3", "S4", "S8"}


def dump_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def wilson(x: int, n: int) -> tuple[float | None, float | None, float | None]:
    if n == 0:
        return None, None, None
    if not 0 <= x <= n:
        raise ValueError(f"Wilson numerator outside denominator: {x}/{n}")
    p = x / n
    den = 1 + Z * Z / n
    center = (p + Z * Z / (2 * n)) / den
    half = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / den
    return p, max(0.0, center - half), min(1.0, center + half)


def load() -> tuple[list[dict], list[dict]]:
    decisions, pairs = [], []
    with RAW.open() as stream:
        for line_no, line in enumerate(stream, 1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON at line {line_no}") from exc
            if row.get("level") == "decision":
                decisions.append(row)
            elif row.get("level") == "outcome_pair":
                pairs.append(row)
            else:
                raise ValueError(f"unknown row level at line {line_no}: {row.get('level')}")
    return decisions, pairs


def validate_raw(decisions: list[dict], pairs: list[dict]) -> dict:
    seed_manifest = json.loads(SEEDS.read_text())
    expected_table = json.loads(EXPECTED.read_text())["scenarios"]
    seeds = seed_manifest["final"]["values"]
    pair_keys = [(r["system"], r["scenario"], r["seed"]) for r in pairs]
    decision_keys = [
        (r["system"], r["scenario"], r["seed"], r["method"], r["branch"])
        for r in decisions
    ]
    if len(pair_keys) != len(set(pair_keys)):
        raise ValueError("duplicate outcome-pair keys")
    if len(decision_keys) != len(set(decision_keys)):
        raise ValueError("duplicate decision keys")

    expected_pair_keys = set()
    cell_checks = []
    for system in ("holdem", "ising"):
        for scenario in SCENARIOS:
            retained = [
                seed for i, seed in enumerate(seeds)
                if not (scenario == "S7" and i % 3 == 2)
            ]
            expected_pair_keys.update((system, scenario, seed) for seed in retained)
            observed = sum(1 for x in pair_keys if x[:2] == (system, scenario))
            cell_checks.append({
                "system": system,
                "scenario": scenario,
                "expected_pairs": len(retained),
                "observed_pairs": observed,
                "status": "PASS" if observed == len(retained) else "FAIL",
            })
    missing_pairs = sorted(expected_pair_keys - set(pair_keys))
    extra_pairs = sorted(set(pair_keys) - expected_pair_keys)

    pair_decision_counts = defaultdict(int)
    gt_mismatches = []
    dim = dict(zip(BRANCHES, [
        "descriptive", "paired_inference", "replay", "crn", "event_alignment"
    ]))
    for row in decisions:
        pair_decision_counts[(row["system"], row["scenario"], row["seed"])] += 1
        expected_gt = expected_table[row["scenario"]]["gt"][dim[row["branch"]]]
        if row["gt"] != expected_gt:
            gt_mismatches.append({"key": decision_keys[len(gt_mismatches)],
                                  "expected": expected_gt, "observed": row["gt"]})
    bad_cell_counts = [
        {"key": list(key), "count": count}
        for key, count in sorted(pair_decision_counts.items()) if count != 40
    ]
    raw_hash = hashlib.sha256(RAW.read_bytes()).hexdigest()
    status = "PASS" if not (missing_pairs or extra_pairs or bad_cell_counts or gt_mismatches) else "FAIL"
    return {
        "status": status,
        "raw_sha256": raw_hash,
        "raw_rows": len(decisions) + len(pairs),
        "decision_rows": len(decisions),
        "outcome_pair_rows": len(pairs),
        "expected_outcome_pair_rows": 854,
        "expected_decision_rows": 34160,
        "s7_note": "27/40 retained per system by frozen drop-every-third injection",
        "cell_checks": cell_checks,
        "missing_pair_keys": missing_pairs,
        "extra_pair_keys": extra_pairs,
        "bad_decision_cell_counts": bad_cell_counts,
        "ground_truth_mismatches": gt_mismatches,
    }


def summarize_decision_group(rows: list[dict]) -> dict:
    counts = defaultdict(int)
    for row in rows:
        counts[(row["gt"], row["score_class"])] += 1
    valid_n = sum(v for (gt, _), v in counts.items() if gt == "VALID")
    invalid_n = sum(v for (gt, _), v in counts.items() if gt == "INVALID")
    downgrade_n = sum(v for (gt, _), v in counts.items() if gt == "DOWNGRADE")
    fs_soft = counts[("VALID", "FALSE_SUPPRESSION_SOFT")]
    fs_hard = counts[("VALID", "FALSE_SUPPRESSION_HARD")]
    detected = counts[("INVALID", "CORRECT")]
    detected_caveat = counts[("INVALID", "DETECTED_WITH_CAVEAT")]
    missed = counts[("INVALID", "MISSED_FAILURE")]
    downgrade_correct = counts[("DOWNGRADE", "CORRECT")]
    downgrade_missed = counts[("DOWNGRADE", "MISSED_FAILURE")]
    downgrade_over = counts[("DOWNGRADE", "FALSE_SUPPRESSION_HARD")]
    out = {
        "valid_n": valid_n,
        "false_suppression_n": fs_soft + fs_hard,
        "false_suppression_soft_n": fs_soft,
        "false_suppression_hard_n": fs_hard,
        "invalid_n": invalid_n,
        "detected_n": detected,
        "detected_with_caveat_n": detected_caveat,
        "missed_failure_n": missed,
        "downgrade_n": downgrade_n,
        "downgrade_correct_n": downgrade_correct,
        "downgrade_missed_n": downgrade_missed,
        "downgrade_over_suppressed_n": downgrade_over,
        "not_applicable_n": sum(1 for r in rows if r["gt"] == "NOT_APPLICABLE"),
    }
    for stem, x, n in (
        ("detection", detected, invalid_n),
        ("false_suppression", fs_soft + fs_hard, valid_n),
        ("false_suppression_soft", fs_soft, valid_n),
        ("false_suppression_hard", fs_hard, valid_n),
        ("missed_failure", missed, invalid_n),
        ("caveat_blindness", downgrade_missed, downgrade_n),
    ):
        est, lo, hi = wilson(x, n)
        out[f"{stem}_est"] = None if est is None else round(est, 6)
        out[f"{stem}_lo"] = None if lo is None else round(lo, 6)
        out[f"{stem}_hi"] = None if hi is None else round(hi, 6)
    return out


def decision_outputs(decisions: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    scenario_rows, system_rows, pooled_rows = [], [], []
    grouped = defaultdict(list)
    for row in decisions:
        grouped[(row["system"], row["scenario"], row["method"], row["branch"])].append(row)
    for (system, scenario, method, branch), rows in sorted(grouped.items()):
        scenario_rows.append({"system": system, "scenario": scenario,
                              "method": method, "branch": branch,
                              **summarize_decision_group(rows)})

    grouped = defaultdict(list)
    for row in decisions:
        grouped[(row["system"], row["method"], row["branch"])].append(row)
    for (system, method, branch), rows in sorted(grouped.items()):
        system_rows.append({"system": system, "method": method, "branch": branch,
                            **summarize_decision_group(rows)})

    grouped = defaultdict(list)
    for row in decisions:
        grouped[(row["method"], row["branch"])].append(row)
    for (method, branch), rows in sorted(grouped.items()):
        pooled_rows.append({"system": "pooled", "method": method, "branch": branch,
                            **summarize_decision_group(rows)})
    return scenario_rows, system_rows, pooled_rows


def two_prop_p(x1: int, n1: int, x2: int, n2: int) -> float | None:
    if not n1 or not n2:
        return None
    pooled = (x1 + x2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0 if x1 / n1 == x2 / n2 else 0.0
    return float(2 * stats.norm.sf(abs((x1 / n1 - x2 / n2) / se)))


def newcombe_mover(x1: int, n1: int, x2: int, n2: int) -> tuple[float, float]:
    p1, l1, u1 = wilson(x1, n1)
    p2, l2, u2 = wilson(x2, n2)
    if p1 is None or p2 is None:
        return math.nan, math.nan
    d = p1 - p2
    lo = d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    hi = d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return max(-1.0, lo), min(1.0, hi)


def holm_adjust(rows: list[dict]) -> None:
    eligible = sorted(
        [(i, row["p_value"]) for i, row in enumerate(rows) if row["p_value"] is not None],
        key=lambda x: x[1],
    )
    m = len(eligible)
    running = 0.0
    for rank, (idx, pvalue) in enumerate(eligible):
        adjusted = min(1.0, (m - rank) * pvalue)
        running = max(running, adjusted)
        rows[idx]["p_holm"] = round(running, 10)


def contrasts(pooled_rows: list[dict]) -> list[dict]:
    lookup = {(r["method"], r["branch"]): r for r in pooled_rows}
    out = []
    for branch in BRANCHES:
        ref = lookup[("B7_csvf_full", branch)]
        for method in METHODS[:-1]:
            row = lookup[(method, branch)]
            for metric, xkey, nkey in (
                ("M1_detection", "detected_n", "invalid_n"),
                ("M2_false_suppression", "false_suppression_n", "valid_n"),
            ):
                x1, n1 = row[xkey], row[nkey]
                x2, n2 = ref[xkey], ref[nkey]
                pvalue = two_prop_p(x1, n1, x2, n2)
                lo, hi = newcombe_mover(x1, n1, x2, n2) if n1 and n2 else (None, None)
                out.append({
                    "branch": branch,
                    "metric": metric,
                    "method": method,
                    "reference": "B7_csvf_full",
                    "method_x": x1,
                    "method_n": n1,
                    "reference_x": x2,
                    "reference_n": n2,
                    "risk_difference_method_minus_B7": None if not n1 or not n2 else round(x1 / n1 - x2 / n2, 6),
                    "newcombe_lo": None if lo is None else round(lo, 6),
                    "newcombe_hi": None if hi is None else round(hi, 6),
                    "p_value": None if pvalue is None else round(pvalue, 10),
                    "p_holm": None,
                    "test_note": "Frozen two-proportion z-test; cells are matched, so dependence is a limitation.",
                })
    holm_adjust(out)
    return out


def variance_outputs(pairs: list[dict]) -> list[dict]:
    grouped = defaultdict(list)
    for row in pairs:
        if row["scenario"] in PRIMARY_SCENARIOS:
            grouped[(row["system"], row["scenario"])].append(row)
    out = []
    for (system, scenario), rows in sorted(grouped.items()):
        rows = sorted(rows, key=lambda r: r["seed"])
        a = np.asarray([float(r["outcome_a"]) for r in rows])
        b = np.asarray([float(r["outcome_b"]) for r in rows])
        n = len(a)
        paired = a - b
        independent = a - np.roll(b, -1)
        vp = float(np.var(paired, ddof=1))
        vi = float(np.var(independent, ddof=1))
        ratio = vp / vi if vi > 0 else math.nan
        se = math.sqrt(4 / (n - 1))
        log_ratio = math.log(ratio) if ratio > 0 else math.nan
        half = Z * se
        split = n // 2
        vp_split = float(np.var(paired[:split], ddof=1))
        ind_split = a[split:] - np.roll(b[split:], -1)
        vi_split = float(np.var(ind_split, ddof=1))
        out.append({
            "system": system, "scenario": scenario, "n_pairs": n,
            "paired_variance": round(vp, 8),
            "independent_variance": round(vi, 8),
            "var_ratio_R": round(ratio, 8),
            "ratio_ci_lo": round(math.exp(log_ratio - half), 8) if ratio > 0 else None,
            "ratio_ci_hi": round(math.exp(log_ratio + half), 8) if ratio > 0 else None,
            "corr_paired": round(float(np.corrcoef(a, b)[0, 1]), 6),
            "marginals_preserved_by_repairing": True,
            "split_half_ratio_sensitivity": round(vp_split / vi_split, 8) if vi_split > 0 else None,
        })
    return out


def paired_test(values: np.ndarray) -> tuple[float, float, float]:
    n = len(values)
    mean = float(np.mean(values))
    se = float(np.std(values, ddof=1) / math.sqrt(n))
    pvalue = float(2 * stats.t.sf(abs(mean / se), n - 1)) if se > 0 else (0.0 if mean else 1.0)
    half = float(stats.t.ppf(0.975, n - 1) * se) if se > 0 else 0.0
    return mean, pvalue, half


def welch_test(a: np.ndarray, b: np.ndarray) -> tuple[float, float, float]:
    n1, n2 = len(a), len(b)
    mean = float(np.mean(a) - np.mean(b))
    v1, v2 = float(np.var(a, ddof=1)), float(np.var(b, ddof=1))
    se2 = v1 / n1 + v2 / n2
    if se2 == 0:
        return mean, 0.0 if mean else 1.0, 0.0
    df = se2 * se2 / ((v1 / n1) ** 2 / (n1 - 1) + (v2 / n2) ** 2 / (n2 - 1))
    se = math.sqrt(se2)
    pvalue = float(2 * stats.t.sf(abs(mean / se), df))
    return mean, pvalue, float(stats.t.ppf(0.975, df) * se)


def statistical_diagnostics(pairs: list[dict], boot: int = 2000) -> tuple[list[dict], list[dict]]:
    grouped = defaultdict(list)
    for row in pairs:
        if row["scenario"] in PRIMARY_SCENARIOS:
            grouped[(row["system"], row["scenario"])].append(row)
    rng = np.random.default_rng(20260826)
    curves, changes = [], []
    for (system, scenario), rows in sorted(grouped.items()):
        a = np.asarray([float(r["outcome_a"]) for r in rows])
        b = np.asarray([float(r["outcome_b"]) for r in rows])
        d = a - b
        truth = float(np.mean(d))
        d0 = d - truth
        a0, b0 = a - np.mean(a), b - np.mean(b)
        for n in (10, 20, 40, 80):
            counters = defaultdict(int)
            for _ in range(boot):
                idx = rng.integers(0, len(d), size=n)
                pa = a[idx]
                pb = b[idx]
                pd = d[idx]
                _, pp, ph = paired_test(pd)
                counters["paired_power"] += pp < 0.05
                counters["paired_alt_coverage"] += (np.mean(pd) - ph <= truth <= np.mean(pd) + ph)
                nd = d0[rng.integers(0, len(d0), size=n)]
                nm, npv, nh = paired_test(nd)
                counters["paired_typeI"] += npv < 0.05
                counters["paired_null_coverage"] += nm - nh <= 0 <= nm + nh

                ia = rng.integers(0, len(a), size=n)
                ib = rng.integers(0, len(b), size=n)
                wa, wb = a[ia], b[ib]
                wm, wp, wh = welch_test(wa, wb)
                counters["welch_power"] += wp < 0.05
                counters["welch_alt_coverage"] += wm - wh <= truth <= wm + wh
                na = a0[rng.integers(0, len(a0), size=n)]
                nb = b0[rng.integers(0, len(b0), size=n)]
                nwm, nwp, nwh = welch_test(na, nb)
                counters["welch_typeI"] += nwp < 0.05
                counters["welch_null_coverage"] += nwm - nwh <= 0 <= nwm + nwh
            for procedure in ("paired_t", "welch"):
                prefix = "paired" if procedure == "paired_t" else "welch"
                for metric in ("power", "typeI", "alt_coverage", "null_coverage"):
                    estimate = counters[f"{prefix}_{metric}"] / boot
                    curves.append({
                        "system": system, "scenario": scenario, "procedure": procedure,
                        "n": n, "metric": metric, "estimate": round(estimate, 6),
                        "mcse": round(math.sqrt(max(estimate * (1 - estimate), 1e-12) / boot), 6),
                        "B": boot, "status": "POST_FREEZE_DIAGNOSTIC_NOT_CONFIRMATORY",
                    })

        disagreement = 0
        nboot = min(40, len(d))
        for _ in range(boot):
            ip = rng.integers(0, len(d), size=nboot)
            pa, pb, pd = a[ip], b[ip], d[ip]
            pm, pp, _ = paired_test(pd)
            wm, wp, _ = welch_test(
                a[rng.integers(0, len(a), size=nboot)],
                b[rng.integers(0, len(b), size=nboot)],
            )
            pclass = (int(np.sign(pm)), pp < 0.05)
            wclass = (int(np.sign(wm)), wp < 0.05)
            disagreement += pclass != wclass
        changes.append({
            "system": system, "scenario": scenario, "n": nboot, "B": boot,
            "paired_vs_welch_conclusion_change": round(disagreement / boot, 6),
            "status": "EXPLORATORY_BOOTSTRAP",
        })
    return curves, changes


def cost_outputs(pairs: list[dict]) -> list[dict]:
    grouped = defaultdict(list)
    for row in pairs:
        grouped[(row["system"], row["scenario"])].append(row)
        grouped[(row["system"], "ALL")].append(row)
    out = []
    for (system, scenario), rows in sorted(grouped.items()):
        runtime = np.asarray([r["runtime_a"] + r["runtime_b"] for r in rows], dtype=float)
        storage = np.asarray([r["bytes_a"] + r["bytes_b"] for r in rows], dtype=float)
        draws = np.asarray([r["n_draws_a"] + r["n_draws_b"] for r in rows], dtype=float)
        out.append({
            "system": system, "scenario": scenario, "n_pairs": len(rows),
            "runtime_median_s": round(float(np.median(runtime)), 6),
            "runtime_p95_s": round(float(np.percentile(runtime, 95)), 6),
            "storage_median_bytes": int(np.median(storage)),
            "storage_p95_bytes": int(np.percentile(storage, 95)),
            "draws_median": int(np.median(draws)),
            "draws_p95": int(np.percentile(draws, 95)),
        })
    return out


METHOD_FIELDS = {
    "B0_schedule_only": ["declared_seed", "context", "row_id"],
    "B1_outcome_aa": ["declared_seed", "context", "row_id", "terminal_outcome", "aa_repeat"],
    "B2_trace_aa": ["declared_seed", "context", "row_id", "trace_projection", "projection_rule", "aa_repeat"],
    "B3_within_seed_reps": ["declared_seed", "context", "row_id", "repeat_count", "within_seed_variability", "analysis_unit"],
    "B4_unpaired": ["arm_identity", "independent_seed_rule", "analysis_unit", "unpaired_estimator"],
    "B5_cluster_hier": ["cluster_id", "analysis_unit", "model_family", "random_effect", "resampling_unit", "uncertainty_rule"],
    "B6_event_keyed_wb": ["event_ontology", "event_id", "event_value", "stream_key", "marginal_check", "dependence_assumption", "white_box_hook"],
    "B7_csvf_full": ["claim_class", "artifact_identity", "schedule_identity", "row_completeness", "analysis_unit", "design_justification", "trace_projection", "repeat_rule", "context_test", "coupling_construction", "marginal_check", "covariance", "variance_ratio", "event_ontology", "event_value", "dependence_assumption"],
}


def complexity_outputs() -> list[dict]:
    out = []
    for method, fields in METHOD_FIELDS.items():
        out.append({
            "method": method,
            "required_field_count": len(fields),
            "required_fields": "|".join(fields),
            "needs_white_box_rng": method in {"B6_event_keyed_wb", "B7_csvf_full"},
            "needs_repeats": method in {"B1_outcome_aa", "B2_trace_aa", "B3_within_seed_reps", "B7_csvf_full"},
            "needs_event_ontology": method in {"B6_event_keyed_wb", "B7_csvf_full"},
            "count_status": "CODE_FACT_FROM_EXHAUSTIVE_CONSTANT",
        })
    return out


def kendall_tau_b(x: list[float], y: list[float]) -> float:
    return float(stats.kendalltau(x, y, variant="b").statistic)


def cross_system(system_rows: list[dict], variance_rows: list[dict]) -> dict:
    overall = {}
    for system in ("holdem", "ising"):
        for method in METHODS:
            selected = [r for r in system_rows if r["system"] == system and r["method"] == method]
            invalid = sum(r["invalid_n"] for r in selected)
            detected = sum(r["detected_n"] for r in selected)
            valid = sum(r["valid_n"] for r in selected)
            suppressed = sum(r["false_suppression_n"] for r in selected)
            det = detected / invalid
            fs = suppressed / valid
            overall[(system, method)] = {"detection": det, "false_suppression": fs,
                                         "tradeoff": det - fs}
    tau = kendall_tau_b(
        [overall[("holdem", method)]["tradeoff"] for method in METHODS],
        [overall[("ising", method)]["tradeoff"] for method in METHODS],
    )
    signs = []
    for row in variance_rows:
        signs.append({"contrast": f"R<1 {row['scenario']}", "system": row["system"],
                      "sign": row["var_ratio_R"] < 1})
    for system in ("holdem", "ising"):
        b0, b5, b7 = (overall[(system, m)] for m in
                      ("B0_schedule_only", "B5_cluster_hier", "B7_csvf_full"))
        signs.extend([
            {"contrast": "B7_detection_gt_B0", "system": system,
             "sign": b7["detection"] > b0["detection"]},
            {"contrast": "B5_detection_within_5pp_B7", "system": system,
             "sign": abs(b5["detection"] - b7["detection"]) <= 0.05},
        ])
    return {
        "kendall_tau_b_tradeoff": round(tau, 6),
        "method_scores": [
            {"system": system, "method": method,
             **{k: round(v, 6) for k, v in overall[(system, method)].items()}}
            for system in ("holdem", "ising") for method in METHODS
        ],
        "sign_agreement_rows": signs,
        "warning": "M1-M2 is a predeclared ordering device, not a probability or utility estimate.",
    }


def success_criteria(pooled_rows: list[dict]) -> dict:
    b7 = [r for r in pooled_rows if r["method"] == "B7_csvf_full"]
    branch_detection = {
        r["branch"]: {
            "estimate": r["detection_est"], "n": r["invalid_n"],
            "pass": r["invalid_n"] < 5 or r["detection_est"] >= 0.95,
        }
        for r in b7
    }
    total_valid = sum(r["valid_n"] for r in b7)
    total_fs = sum(r["false_suppression_n"] for r in b7)
    pooled_fs = total_fs / total_valid
    overall = {}
    for method in METHODS:
        rows = [r for r in pooled_rows if r["method"] == method]
        invalid = sum(r["invalid_n"] for r in rows)
        detected = sum(r["detected_n"] for r in rows)
        valid = sum(r["valid_n"] for r in rows)
        suppressed = sum(r["false_suppression_n"] for r in rows)
        overall[method] = {"detection": detected / invalid,
                           "false_suppression": suppressed / valid}
    b7o = overall["B7_csvf_full"]
    dominators = [
        method for method in METHODS[:-1]
        if overall[method]["detection"] >= b7o["detection"]
        and overall[method]["false_suppression"] <= b7o["false_suppression"]
        and (overall[method]["detection"] > b7o["detection"]
             or overall[method]["false_suppression"] < b7o["false_suppression"])
    ]
    detection_pass = all(x["pass"] for x in branch_detection.values())
    fs_pass = pooled_fs <= 0.10
    return {
        "framework_branch_detection": branch_detection,
        "framework_pooled_false_suppression": round(pooled_fs, 6),
        "framework_pooled_false_suppression_n": total_fs,
        "framework_pooled_valid_n": total_valid,
        "detection_threshold_pass": detection_pass,
        "false_suppression_threshold_pass": fs_pass,
        "simpler_detection_suppression_dominators_before_cost": dominators,
        "overall_method_metrics": overall,
        "worth_recommending_gate": detection_pass and fs_pass and not dominators,
        "reporting_consequence": "Do not recommend B7 as a universal strategy; report branch-specific simpler-method wins." if not (detection_pass and fs_pass and not dominators) else "Framework gate passed.",
    }


def macros(pooled_rows: list[dict], success: dict, integrity: dict,
           variance_rows: list[dict], costs: list[dict], cross: dict) -> dict:
    lookup = {(r["method"], r["branch"]): r for r in pooled_rows}
    branch_b = lookup[("B7_csvf_full", "BRANCH_B")]
    b5b = lookup[("B5_cluster_hier", "BRANCH_B")]
    return {
        "raw_rows": integrity["raw_rows"],
        "outcome_pairs": integrity["outcome_pair_rows"],
        "decision_rows": integrity["decision_rows"],
        "systems": 2,
        "scenarios": 11,
        "final_seeds": 40,
        "s7_retained_per_system": 27,
        "b7_branch_b_detection_pct": round(100 * branch_b["detection_est"], 1),
        "b7_branch_b_detection_n": branch_b["invalid_n"],
        "b7_branch_b_false_suppression_pct": round(100 * branch_b["false_suppression_est"], 1),
        "b7_branch_b_valid_n": branch_b["valid_n"],
        "b5_branch_b_detection_pct": round(100 * b5b["detection_est"], 1),
        "b5_branch_b_false_suppression_pct": round(100 * b5b["false_suppression_est"], 1),
        "b7_pooled_false_suppression_pct": round(100 * success["framework_pooled_false_suppression"], 1),
        "cross_system_tau": cross["kendall_tau_b_tradeoff"],
        "raw_sha256": integrity["raw_sha256"],
    }


def write_tex_macros(values: dict) -> None:
    lines = ["% Generated by complete_analysis.py; do not edit manually."]
    for key, value in values.items():
        command = "".join(piece.capitalize() for piece in key.split("_"))
        escaped = str(value).replace("_", "\\_").replace("%", "\\%")
        lines.append(f"\\newcommand{{\\{command}}}{{{escaped}}}")
    (ROOT / "results/final/aggregates/results_macros.tex").write_text("\n".join(lines) + "\n")


def main() -> None:
    AGG.mkdir(parents=True, exist_ok=True)
    decisions, pairs = load()
    integrity = validate_raw(decisions, pairs)
    if integrity["status"] != "PASS":
        raise SystemExit("raw integrity validation failed")
    scenario_rows, system_rows, pooled_rows = decision_outputs(decisions)
    contrast_rows = contrasts(pooled_rows)
    variance_rows = variance_outputs(pairs)
    diagnostic_rows, conclusion_rows = statistical_diagnostics(pairs)
    cost_rows = cost_outputs(pairs)
    complexity_rows = complexity_outputs()
    cross = cross_system(system_rows, variance_rows)
    success = success_criteria(pooled_rows)
    estimability = {
        "M1_M3": {"status": "CONFIRMATORY_COMPLETE", "source": "decision rows"},
        "M4_coverage": {"status": "NOT_ESTIMABLE_AS_PREDECLARED", "reason": "Runner retained no A/A mirror/equal-temperature banks and no construction-fixed effects; emitted centered empirical-bootstrap diagnostic is not confirmatory coverage."},
        "M5_typeI": {"status": "NOT_ESTIMABLE_AS_PREDECLARED", "reason": "No stored known-zero A/A outcome pairs; centered empirical-bootstrap diagnostic is labeled post-freeze proxy."},
        "M6_power": {"status": "PARTIAL_DIAGNOSTIC_ONLY", "reason": "Alternative outcomes exist, but frozen N=80 subsampling without replacement is impossible from N=40 and no fixed-effect construction was stored; replacement bootstrap reported."},
        "M7_variance": {"status": "CONFIRMATORY_COMPLETE_WITH_DECLARED_SHARED_BANK_LIMITATION", "source": "outcome-pair rows"},
        "M8_conclusion_changes": {"status": "EXPLORATORY_COMPLETE", "source": "paired-vs-Welch bootstrap"},
        "M9_method_runtime": {"status": "NOT_ESTIMABLE_FROM_RAW_SCHEMA", "reason": "No per-method acquisition or classifier timers were retained."},
        "M10_method_storage": {"status": "PARTIAL_SYSTEM_ARTIFACT_ONLY", "reason": "Artifact bytes retained; per-method bundle bytes absent."},
        "M11_trace_overhead": {"status": "COMPLETE_ANALYSIS_MICROBENCHMARK" if (AGG / "overhead.json").exists() else "PENDING_ANALYSIS_MICROBENCHMARK"},
        "M12_complexity": {"status": "COMPLETE_CODE_FACT"},
        "M13_cross_system": {"status": "COMPLETE_WITH_TWO_SYSTEM_LIMITATION"},
    }

    dump_json(AGG / "raw_integrity.json", integrity)
    write_csv(AGG / "scenario_decision_metrics.csv", scenario_rows)
    write_csv(AGG / "decision_metrics.csv", system_rows + pooled_rows)
    dump_json(AGG / "decision_metrics.json", system_rows + pooled_rows)
    write_csv(AGG / "method_contrasts.csv", contrast_rows)
    dump_json(AGG / "method_contrasts.json", contrast_rows)
    write_csv(AGG / "variance_ratios.csv", variance_rows)
    dump_json(AGG / "variance_ratios.json", variance_rows)
    write_csv(AGG / "statistical_diagnostics.csv", diagnostic_rows)
    dump_json(AGG / "statistical_diagnostics.json", diagnostic_rows)
    write_csv(AGG / "conclusion_changes.csv", conclusion_rows)
    dump_json(AGG / "conclusion_changes.json", conclusion_rows)
    write_csv(AGG / "costs.csv", cost_rows)
    dump_json(AGG / "costs.json", cost_rows)
    write_csv(AGG / "complexity_counts.csv", complexity_rows)
    dump_json(AGG / "complexity_counts.json", complexity_rows)
    dump_json(AGG / "cross_system.json", cross)
    dump_json(AGG / "success_criteria.json", success)
    dump_json(AGG / "estimability.json", estimability)
    macro_values = macros(pooled_rows, success, integrity, variance_rows, cost_rows, cross)
    dump_json(AGG / "results_macros.json", macro_values)
    write_tex_macros(macro_values)
    print(json.dumps({
        "raw_integrity": integrity["status"],
        "framework_gate": success["worth_recommending_gate"],
        "framework_pooled_false_suppression": success["framework_pooled_false_suppression"],
        "simpler_dominators_before_cost": success["simpler_detection_suppression_dominators_before_cost"],
        "confirmatory_gap": ["M4", "M5", "M6", "M9", "M10"],
    }, indent=2))


if __name__ == "__main__":
    main()
