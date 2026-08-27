"""Statistical procedures (frozen implementations; fixture-tested)."""
from __future__ import annotations

import math
from itertools import combinations

import numpy as np

Z95 = 1.959964


def wilson_interval(x: int, n: int):
    if n == 0:
        return None, None, None
    if not 0 <= x <= n:
        raise ValueError("numerator outside denominator")
    p = x / n
    den = 1 + Z95 ** 2 / n
    center = (p + Z95 ** 2 / (2 * n)) / den
    half = Z95 * math.sqrt(p * (1 - p) / n + Z95 ** 2 / (4 * n * n)) / den
    return p, max(0.0, center - half), min(1.0, center + half)


def exact_mcnemar(b: int, c: int) -> float:
    """Two-sided exact binomial McNemar on discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def signflip_permutation_p(diffs, n_flips: int = 10000,
                           rng_seed: int = 20260827) -> float:
    d = np.asarray(diffs, dtype=float)
    stat_obs = abs(float(np.mean(d)))
    rng = np.random.default_rng(rng_seed)
    if len(d) <= 20:
        masks = np.array(list(__import__("itertools").product(
            [1, -1], repeat=len(d))), dtype=float)
        stats = np.abs((masks * d).mean(axis=1))
        return float((stats >= stat_obs - 1e-12).mean())
    hits = 0
    for _ in range(n_flips):
        signs = rng.choice([-1.0, 1.0], size=len(d))
        if abs(float((signs * d).mean())) >= stat_obs - 1e-12:
            hits += 1
    return (hits + 1) / (n_flips + 1)


def paired_risk_difference_ci(diffs_bool, n_boot=2000, rng_seed=20260827):
    """Cluster(seed)-bootstrap CI of mean paired risk difference."""
    d = np.asarray(diffs_bool, dtype=float)
    rng = np.random.default_rng(rng_seed)
    n = len(d)
    boots = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.integers(0, n, size=n)
        boots[i] = d[idx].mean()
    return float(d.mean()), float(np.percentile(boots, 2.5)), \
        float(np.percentile(boots, 97.5))


def holm(pvals):
    order = np.argsort(pvals)
    m = len(pvals)
    adj = [0] * m
    prev = 0.0
    for rank, idx in enumerate(order):
        val = min(1.0, (m - rank) * pvals[idx])
        val = max(val, prev)
        adj[idx] = val
        prev = val
    return adj


def variance_ratio_benefit(out_a, out_b, n_boot=2000, rng_seed=20260827):
    """EXPLORATORY CRN benefit: R = Var(A-B)/Var(A-B_cyclic), uncertainty from
    a joint seed-cluster percentile bootstrap (resample seed indices ONCE and
    recompute BOTH variances from the same resample)."""
    a = np.asarray(out_a, dtype=float)
    b = np.asarray(out_b, dtype=float)
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    dp = a - b
    di = a - np.roll(b, -1)

    def ratio(idxA, idxB):
        ap, bp, ai_, bi_ = a[idxA], b[idxA], a[idxB], b[np.roll(idxB, -1)]
        vp = np.var(ap - bp, ddof=1) if len(idxA) > 1 else float("nan")
        vi = np.var(ai_ - bi_, ddof=1) if len(idxB) > 1 else float("nan")
        return vp / vi if vi > 0 else float("nan")

    point = (np.var(dp, ddof=1) / np.var(di, ddof=1)
             if np.var(di, ddof=1) > 0 else None)
    if point is not None and not math.isfinite(point):
        point = {"degenerate": True}
    rng = np.random.default_rng(rng_seed)
    boots = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        r = ratio(idx, idx)   # joint resample — same indices both sides
        if math.isfinite(r):
            boots.append(r)
    lo = hi = None
    if boots:
        lo, hi = float(np.percentile(boots, 2.5)), float(np.percentile(boots,
                                                                      97.5))
    return {"R": point, "ci95_joint_seedcluster": [lo, hi],
            "status": "EXPLORATORY_NOT_CONFIRMATORY",
            "note": "zero-variance numerator => DEGENERATE_NOT_BENEFIT"}
