"""Analysis stage: consumes raw decision/outcome rows, produces frozen-plan aggregates.

Executes ANALYSIS_PLAN.md sections A–F. Run ONLY after final raw rows exist.
"""

import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

Z = 1.959964


def wilson(x, n):
    if n == 0:
        return (float("nan"), float("nan"), float("nan"))
    if not 0 <= x <= n:
        raise ValueError(f"Wilson count outside denominator: x={x}, n={n}")
    p = x / n
    denom = 1 + Z * Z / n
    center = (p + Z * Z / (2 * n)) / denom
    half = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / denom
    return (p, max(0.0, center - half), min(1.0, center + half))


def load_rows(path):
    dec, pairs = [], []
    with open(path) as f:
        for line in f:
            r = json.loads(line)
            (dec if r["level"] == "decision" else pairs).append(r)
    return dec, pairs


def decision_metrics(dec):
    """M1-M3 per method x branch (pooled over systems/scenarios), plus per-system."""
    cells = defaultdict(lambda: defaultdict(int))
    for r in dec:
        key = (r["method"], r["branch"], r["system"])
        gt, d = r["gt"], r["decision"]
        sc = r["score_class"]
        rec = cells[key]
        rec.setdefault("denom_valid", 0)
        rec.setdefault("fs_hard", 0)
        rec.setdefault("fs_soft", 0)
        rec.setdefault("denom_invalid", 0)
        rec.setdefault("detected", 0)
        rec.setdefault("caveat", 0)
        rec.setdefault("missed", 0)
        rec.setdefault("denom_downgrade", 0)
        rec.setdefault("downgrade_missed", 0)
        if gt == "VALID":
            rec["denom_valid"] += 1
            rec["fs_soft"] += sc == "FALSE_SUPPRESSION_SOFT"
            rec["fs_hard"] += sc == "FALSE_SUPPRESSION_HARD"
        elif gt == "INVALID":
            rec["denom_invalid"] += 1
            rec["detected"] += sc in ("CORRECT",)
            rec["caveat"] += sc == "DETECTED_WITH_CAVEAT"
            rec["missed"] += sc == "MISSED_FAILURE"
        elif gt == "DOWNGRADE":
            rec["denom_downgrade"] += 1
            rec["caveat"] += sc == "CORRECT"
            rec["downgrade_missed"] += sc == "MISSED_FAILURE"
    out = []
    for (method, branch, system), rec in sorted(cells.items()):
        row = {"method": method, "branch": branch, "system": system}
        for m, lab, num in (("detection", "denom_invalid", "detected"),
                            ("false_suppression", "denom_valid", None),
                            ("missed_failure", "denom_invalid", "missed")):
            if m == "false_suppression":
                x = rec.get("fs_hard", 0) + rec.get("fs_soft", 0)
                n = rec.get(lab, 0)
            else:
                x = rec.get(num, 0)
                n = rec.get(lab, 0)
            p, lo, hi = wilson(x, n)
            row[f"{m}_est"] = round(p, 4) if n else None
            row[f"{m}_n"] = n
            row[f"{m}_ci"] = [round(lo, 4), round(hi, 4)] if n else None
        row["caveat_blind_n"] = rec.get("denom_downgrade", 0) + rec.get("denom_invalid", 0)
        row["caveat_admitted"] = rec.get("caveat", 0)
        row["downgrade_missed_n"] = rec.get("downgrade_missed", 0)
        row["downgrade_denom_n"] = rec.get("denom_downgrade", 0)
        out.append(row)
    return out


def variance_ratios(pairs):
    """M7: R = Var(paired)/Var(independent) per system x scenario."""
    out = []
    by = defaultdict(lambda: ([], []))
    for r in pairs:
        a, b = by[(r["system"], r["scenario"])]
        a.append(float(r["outcome_a"]))
        b.append(float(r["outcome_b"]))
    for (system, scenario), (A, B) in sorted(by.items()):
        if len(A) < 6:
            continue
        A = np.asarray(A); B = np.asarray(B)
        d = A - B
        # deterministic derangement: pair A_i with B_{i+1 mod n}
        idx = (np.arange(len(A)) + 1) % len(A)
        d_ind = A - B[idx]
        v_p = float(np.var(d, ddof=1))
        v_i = float(np.var(d_ind, ddof=1))
        logR = 0.5 * math.log(v_p) - 0.5 * math.log(v_i) if v_p > 0 and v_i > 0 else float("nan")
        se = math.sqrt(2.0 / (len(d) - 1) + 2.0 / (len(d_ind) - 1))
        out.append({"system": system, "scenario": scenario,
                    "n_pairs": len(A),
                    "var_ratio_R": round(v_p / v_i, 5) if v_i > 0 else None,
                    "logR_ci": [round(logR - Z * se, 4), round(logR + Z * se, 4)]
                    if v_p > 0 and v_i > 0 else None,
                    "corr_paired": round(float(np.corrcoef(A, B)[0, 1]), 4)})
    return out


def typeI_power(pairs):
    """M5/M6 via constructed banks: holdem mirror nulls; ising equal-T nulls are
    not stored separately -> use within-arm resampling as declared fallback:
    null = A vs shuffled-A (same marginals, broken coupling documented);
    alt = frozen arm contrasts where scenario defines them."""
    out = []
    by = defaultdict(lambda: ([], []))
    for r in pairs:
        a, b = by[(r["system"], r["scenario"])]
        a.append(float(r["outcome_a"]))
        b.append(float(r["outcome_b"]))
    rng = np.random.default_rng(20260826)
    B = 2000
    for (system, scenario), (A, Bv) in sorted(by.items()):
        A = np.asarray(A); Bv = np.asarray(Bv)
        d = A - Bv
        if len(d) < 10:
            continue
        # Type-I proxy under H0 via sign-flip symmetry of differences
        rejects = 0
        for _ in range(B):
            s = rng.choice([-1.0, 1.0], size=len(d))
            tstat = abs(s @ d / math.sqrt(len(d)))
            sd = np.std(s * d, ddof=1)
            if sd > 0 and tstat / (sd / math.sqrt(len(d))) > 1.959964 * 1.0:
                pass
            # paired t one-sample against 0
            m = float(np.mean(s * d)); se = float(np.std(s * d, ddof=1)) / math.sqrt(len(d))
            if se > 0 and abs(m / se) > 1.959964:
                rejects += 1
        alpha_hat = rejects / B
        mcse = math.sqrt(max(alpha_hat * (1 - alpha_hat), 1e-9) / B)
        # Power: paired t against observed effect (nonzero scenarios)
        power_rejects = 0
        m0 = float(np.mean(d)); se_full = float(np.std(d, ddof=1)) / math.sqrt(len(d))
        if se_full > 0 and abs(m0 / se_full) > 1.959964:
            power_rejects = None  # computed via subsampling below instead
        pw = []
        for nsub in (10, 20, 40):
            hits = 0
            trials = 0
            for _ in range(400):
                if len(d) < nsub:
                    break
                sub = rng.choice(d, size=nsub, replace=False)
                se = np.std(sub, ddof=1) / math.sqrt(nsub)
                if se > 0 and abs(np.mean(sub) / se) > 1.959964:
                    hits += 1
                trials += 1
            if trials:
                pw.append({"n": nsub, "power": round(hits / trials, 4)})
        out.append({"system": system, "scenario": scenario,
                    "typeI_signflip": round(alpha_hat, 4),
                    "typeI_mcse": round(mcse, 4),
                    "power_curve": pw})
    return out


def costs(dec, pairs):
    rt = defaultdict(list)
    bt = defaultdict(list)
    for r in pairs:
        rt[r["system"]].append(r["runtime_a"] + r["runtime_b"])
        bt[r["system"]].append(r["bytes_a"] + r["bytes_b"])
    out = {}
    for s in rt:
        arr = np.asarray(rt[s]); brr = np.asarray(bt[s])
        out[s] = {"median_row_seconds": round(float(np.median(arr)), 4),
                  "p95_row_seconds": round(float(np.percentile(arr, 95)), 4),
                  "median_bytes_per_pair": int(np.median(brr)),
                  "p95_bytes_per_pair": int(np.percentile(brr, 95))}
    return out


def kendall_tau(xs, ys):
    n = len(xs)
    c = 0
    for i in range(n):
        for j in range(i + 1, n):
            s = (xs[i] - xs[j]) * (ys[i] - ys[j])
            c += 1 if s > 0 else (-1 if s < 0 else 0)
    return 2 * c / (n * (n - 1))


def cross_system(dm):
    """M13: rank methods per system by detection-then-suppression tradeoff."""
    def score(rows, system):
        vals = {}
        for r in rows:
            if r["system"] != system or r["branch"] != "BRANCH_B":
                continue
            det = r["detection_est"] or 0
            fs = r["false_suppression_est"] or 0
            vals[r["method"]] = det - fs
        return vals
    sh = score(dm, "holdem"); si = score(dm, "ising")
    common = sorted(set(sh) & set(si))
    if len(common) < 3:
        return {"note": "insufficient overlap"}
    tau = kendall_tau([sh[m] for m in common], [si[m] for m in common])
    return {"kendall_tau_branchB": round(tau, 4), "methods_ranked": common}


def main():
    raw = os.path.join(HERE, "..", "results", "final", "raw",
                       "decisions_and_pairs.jsonl")
    agg_dir = os.path.join(HERE, "..", "results", "final", "aggregates")
    os.makedirs(agg_dir, exist_ok=True)
    dec, pairs = load_rows(raw)

    dm = decision_metrics(dec)
    json.dump(dm, open(os.path.join(agg_dir, "decision_metrics.json"), "w"), indent=2)

    vr = variance_ratios(pairs)
    json.dump(vr, open(os.path.join(agg_dir, "variance_ratios.json"), "w"), indent=2)

    tp = typeI_power(pairs)
    json.dump(tp, open(os.path.join(agg_dir, "typeI_power.json"), "w"), indent=2)

    cs = costs(dec, pairs)
    json.dump(cs, open(os.path.join(agg_dir, "costs.json"), "w"), indent=2)

    xs = cross_system(dm)
    json.dump(xs, open(os.path.join(agg_dir, "cross_system.json"), "w"), indent=2)

    print("aggregates written:", sorted(os.listdir(agg_dir)))
    print("\nheadline (BRANCH_B, pooled across systems):")
    pooled = defaultdict(lambda: [0, 0, 0, 0])
    for r in dm:
        if r["branch"] != "BRANCH_B":
            continue
        p = pooled[r["method"]]
        p[0] += r["detection_n"]; p[1] += round((r["detection_est"] or 0) * r["detection_n"])
        p[2] += r["false_suppression_n"]
        p[3] += round((r["false_suppression_est"] or 0) * r["false_suppression_n"])
    for m, (nd, xd, nf, xf) in sorted(pooled.items()):
        dp, _, _ = wilson(xd, nd)
        fp, _, _ = wilson(xf, nf)
        print(f"  {m:22s} detection={dp:.3f} (n={nd})  false_supp={fp:.3f} (n={nf})")


if __name__ == "__main__":
    main()
