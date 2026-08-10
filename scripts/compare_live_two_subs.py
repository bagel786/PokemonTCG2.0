#!/usr/bin/env python3
"""Compare the two live submissions on strength-adjusted ladder performance.

Public score is a TrueSkill-style rating that depends on *who you drew*. Two
agents on the same ladder at the same time do not face the same opponents, so
the raw score gap is not a strength comparison. This script controls for
opponent rating and seat, which are the two confounders we can actually measure
from episode metadata.

Usage:
    python scripts/compare_live_two_subs.py 55397271 55399728
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPLAYS = ROOT / "data" / "replays"


def load(sub_id: int) -> list[dict]:
    """One record per completed public ladder game for this submission."""
    meta = json.loads((REPLAYS / str(sub_id) / "episodes_metadata.json").read_text())
    games = []
    for ep in meta:
        if ep.get("state") != "COMPLETED":
            continue
        if ep.get("type") != "EPISODE_TYPE_PUBLIC":
            continue  # validation episodes are not rated and not vs the field
        me = next((a for a in ep["agents"] if a.get("submissionId") == sub_id), None)
        opp = next((a for a in ep["agents"] if a.get("submissionId") != sub_id), None)
        if me is None or opp is None:
            continue
        if me.get("reward") is None or opp.get("initialScore") is None:
            continue
        games.append({
            "episode": ep["id"],
            "time": ep.get("createTime", ""),
            # index absent == seat 0 == moves first
            "seat": me.get("index", 0),
            "win": me["reward"] > 0,
            "draw": me["reward"] == 0,
            "opp_rating": opp["initialScore"],
            "opp_sub": opp.get("submissionId"),
            "my_before": me.get("initialScore"),
            "my_after": me.get("updatedScore"),
        })
    games.sort(key=lambda g: g["time"])
    return games


def wr(games: list[dict]) -> tuple[float, int]:
    if not games:
        return float("nan"), 0
    return 100.0 * sum(g["win"] for g in games) / len(games), len(games)


def expected(my_rating: float, opp_rating: float) -> float:
    """Elo expectation. Kaggle scores are TrueSkill-ish but monotone in skill;
    a 400-point logistic is a serviceable common yardstick for both agents."""
    return 1.0 / (1.0 + 10 ** ((opp_rating - my_rating) / 400.0))


def performance_rating(games: list[dict]) -> float:
    """Rating R such that sum of Elo expectations equals the observed score.
    Opponent-adjusted: unlike public score, it does not reward an easy draw."""
    if not games:
        return float("nan")
    score = sum(1.0 if g["win"] else (0.5 if g["draw"] else 0.0) for g in games)
    lo, hi = 0.0, 3000.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if sum(expected(mid, g["opp_rating"]) for g in games) < score:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return float("nan"), float("nan")
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return 100 * (c - m), 100 * (c + m)


BANDS = [(0, 700), (700, 800), (800, 900), (900, 3000)]


def report(sub_id: int, games: list[dict]) -> dict:
    print(f"\n{'=' * 72}\nSUBMISSION {sub_id}   ({len(games)} rated public games)\n{'=' * 72}")
    if not games:
        return {}

    o, n = wr(games)
    lo, hi = wilson(sum(g["win"] for g in games), n)
    print(f"  overall      {o:5.1f}%  n={n:<4} 95% CI [{lo:.1f}, {hi:.1f}]")
    for seat, label in ((0, "first"), (1, "second")):
        s = [g for g in games if g["seat"] == seat]
        sw, sn = wr(s)
        print(f"  actually {label:<6} {sw:5.1f}%  n={sn}")

    opps = [g["opp_rating"] for g in games]
    opps_sorted = sorted(opps)
    med = opps_sorted[len(opps_sorted) // 2]
    print(f"\n  opponent rating  mean {sum(opps)/len(opps):7.1f}   median {med:7.1f}"
          f"   min {min(opps):.0f}  max {max(opps):.0f}")

    print("\n  win rate by opponent rating band:")
    for lo_b, hi_b in BANDS:
        band = [g for g in games if lo_b <= g["opp_rating"] < hi_b]
        bw, bn = wr(band)
        bar = "" if bn == 0 else f"{bw:5.1f}%"
        print(f"    {lo_b:>4}-{hi_b:<4}  n={bn:<4} {bar}")

    pr = performance_rating(games)
    final = games[-1]["my_after"]
    print(f"\n  final public score      {final:7.1f}")
    print(f"  performance rating      {pr:7.1f}   <- opponent-adjusted")
    return {"games": games, "perf": pr, "final": final}


def head_to_head(a_id: int, a: list[dict], b_id: int, b: list[dict]) -> None:
    direct = [g for g in a if g["opp_sub"] == b_id]
    if direct:
        w, n = wr(direct)
        print(f"\nHEAD TO HEAD: {a_id} vs {b_id}: {w:.1f}% over {n} games")
    else:
        print(f"\nHEAD TO HEAD: none -- {a_id} and {b_id} never played each other")

    # Shared opponents are the cleanest available control.
    a_by = defaultdict(list)
    b_by = defaultdict(list)
    for g in a:
        a_by[g["opp_sub"]].append(g)
    for g in b:
        b_by[g["opp_sub"]].append(g)
    shared = sorted(set(a_by) & set(b_by))
    if not shared:
        print("SHARED OPPONENTS: none")
        return
    print(f"\nSHARED OPPONENTS ({len(shared)} submissions both agents faced):")
    print(f"  {'opp sub':>10}  {'opp rtg':>8}  {a_id:>16}  {b_id:>16}")
    ta = tb = na = nb = 0
    for s in shared:
        aw, an = wr(a_by[s])
        bw, bn = wr(b_by[s])
        rtg = sum(g["opp_rating"] for g in a_by[s] + b_by[s]) / (an + bn)
        ta += sum(g["win"] for g in a_by[s]); na += an
        tb += sum(g["win"] for g in b_by[s]); nb += bn
        print(f"  {s:>10}  {rtg:8.0f}  {aw:9.1f}% n={an:<3}  {bw:9.1f}% n={bn:<3}")
    print(f"  {'TOTAL':>10}  {'':>8}  {100*ta/na:9.1f}% n={na:<3}  {100*tb/nb:9.1f}% n={nb:<3}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("subs", nargs=2, type=int)
    args = ap.parse_args()
    a_id, b_id = args.subs
    a, b = load(a_id), load(b_id)

    ra = report(a_id, a)
    rb = report(b_id, b)
    head_to_head(a_id, a, b_id, b)

    print(f"\n{'=' * 72}\nVERDICT INPUTS\n{'=' * 72}")
    print(f"  public score gap      {ra['final'] - rb['final']:+8.1f}  (favours "
          f"{a_id if ra['final'] > rb['final'] else b_id})")
    print(f"  perf rating gap       {ra['perf'] - rb['perf']:+8.1f}  (favours "
          f"{a_id if ra['perf'] > rb['perf'] else b_id})")
    oa = sum(g["opp_rating"] for g in a) / len(a)
    ob = sum(g["opp_rating"] for g in b) / len(b)
    print(f"  mean opponent gap     {oa - ob:+8.1f}  ({a_id} faced "
          f"{'stronger' if oa > ob else 'weaker'} opposition)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
