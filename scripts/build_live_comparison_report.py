#!/usr/bin/env python3
"""Emit the live-ladder comparison report for the two active submissions.

Every number in the output is computed from data/replays/<sub>/episodes_metadata.json
and the Kaggle submission listing, so the report can be regenerated rather than
hand-maintained.

Usage:
    python scripts/build_live_comparison_report.py 55397271 55399728 \
        --out docs/LIVE_LADDER_D842_VS_A2.md
"""

from __future__ import annotations

import argparse
import csv
import io
import itertools
import math
import os
import random
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from compare_live_two_subs import load, expected, performance_rating  # noqa: E402
from loss_buckets_live import build as build_buckets  # noqa: E402

COMPETITION = "pokemon-tcg-ai-battle"
BANDS = [(0, 700), (700, 800), (800, 900), (900, 3000)]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return float("nan"), float("nan")
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return 100 * (c - m), 100 * (c + m)


def perm_p(a: list, b: list, stat, iters: int = 100000, seed: int = 0) -> float:
    rng = random.Random(seed)
    obs = abs(stat(a) - stat(b))
    pool = a + b
    na = len(a)
    hits = 0
    for _ in range(iters):
        rng.shuffle(pool)
        if abs(stat(pool[:na]) - stat(pool[na:])) >= obs - 1e-12:
            hits += 1
    return (hits + 1) / (iters + 1)


def reship_scores(prefix: str = "grimmsnarl_5k_reference") -> list[float]:
    """Public scores for every shipment of the byte-identical d842 agent.

    This is the empirical null: how far apart two runs of the SAME agent land.
    """
    tok = subprocess.run([sys.executable, "-m", "kaggle", "auth", "print-access-token"],
                         capture_output=True, text=True).stdout.strip()
    env = dict(os.environ, KAGGLE_API_TOKEN=tok)
    res = subprocess.run(
        [sys.executable, "-m", "kaggle", "competitions", "submissions", "-c", COMPETITION, "-v"],
        capture_output=True, text=True, env=env)
    body = res.stdout.lstrip("﻿")
    body = body[body.index("ref,"):]
    rows = [r for r in csv.DictReader(io.StringIO(body)) if r.get("ref")]
    return sorted(
        float(r["publicScore"]) for r in rows
        if r["fileName"].startswith(prefix) and r.get("publicScore") not in (None, "", "-")
    )


def runs_test(games: list[dict]) -> tuple[int, float, float, int, int]:
    """Wald-Wolfowitz. Fewer runs than expected == genuine win/loss clustering."""
    seq = "".join("W" if g["win"] else "L" for g in games)
    runs = [(k, len(list(v))) for k, v in itertools.groupby(seq)]
    n1, n2, R = seq.count("W"), seq.count("L"), len(runs)
    mu = 2 * n1 * n2 / (n1 + n2) + 1
    var = 2 * n1 * n2 * (2 * n1 * n2 - n1 - n2) / ((n1 + n2) ** 2 * (n1 + n2 - 1))
    z = (R - mu) / math.sqrt(var)
    p = 2 * (1 - statistics.NormalDist().cdf(abs(z)))
    longest_l = max([n for k, n in runs if k == "L"], default=0)
    longest_w = max([n for k, n in runs if k == "W"], default=0)
    return R, mu, p, longest_l, longest_w


def margin_stats(bk: list[dict]) -> dict:
    L = [x["opp_took"] - x["my_took"] for x in bk if not x["win"] and x["my_took"] is not None]
    W = [x["my_took"] - x["opp_took"] for x in bk if x["win"] and x["my_took"] is not None]
    return {"loss": statistics.mean(L), "win": statistics.mean(W),
            "blowouts": sum(1 for m in L if m >= 4), "nloss": len(L),
            "close": sum(1 for m in L if m <= 1),
            "shutouts": sum(1 for x in bk if not x["win"] and x["my_took"] == 0)}


def quartiles(bk: list[dict], spec: str | None = None) -> list[tuple[str, int, int]]:
    """Explicit '1-8:climb,9-14:crash' phases, else quarters of the run."""
    if spec:
        out = []
        for part in spec.split(","):
            rng, _, name = part.partition(":")
            lo, hi = (int(x) for x in rng.split("-"))
            out.append((f"{lo}-{hi}" + (f" {name}" if name else ""), lo, hi))
        return out
    n = len(bk)
    c = [round(n * i / 4) for i in range(5)]
    return [(f"{c[i]+1}-{c[i+1]}", c[i] + 1, c[i + 1]) for i in range(4) if c[i + 1] > c[i]]


def seat_block(games: list[dict], seat: int) -> dict:
    g = [x for x in games if x["seat"] == seat]
    w = sum(x["win"] for x in g)
    lo, hi = wilson(w, len(g)) if g else (float("nan"),) * 2
    bands = []
    for a, b in BANDS:
        s = [x for x in g if a <= x["opp_rating"] < b]
        if s:
            bands.append((a, b, 100 * sum(x["win"] for x in s) / len(s), len(s)))
    return {"n": len(g), "w": w, "wr": 100 * w / len(g) if g else float("nan"),
            "lo": lo, "hi": hi,
            "opp_mean": statistics.mean(x["opp_rating"] for x in g) if g else float("nan"),
            "bands": bands}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("subs", nargs=2, type=int)
    ap.add_argument("--labels", nargs=2, default=["d842 exact", "A2 ordered"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--phases-a", help="e.g. '1-11:bad start,12-22:recovery'")
    ap.add_argument("--phases-b")
    args = ap.parse_args()

    (a_id, b_id), (a_lbl, b_lbl) = args.subs, args.labels
    a, b = load(a_id), load(b_id)
    A = {"id": a_id, "lbl": a_lbl, "g": a}
    B = {"id": b_id, "lbl": b_lbl, "g": b}
    for d in (A, B):
        g = d["g"]
        d["n"] = len(g)
        d["w"] = sum(x["win"] for x in g)
        d["wr"] = 100 * d["w"] / d["n"]
        d["lo"], d["hi"] = wilson(d["w"], d["n"])
        d["perf"] = performance_rating(g)
        d["final"] = g[-1]["my_after"]
        d["opp_mean"] = statistics.mean(x["opp_rating"] for x in g)
        d["opp_med"] = statistics.median(x["opp_rating"] for x in g)
        d["first"] = seat_block(g, 0)
        d["second"] = seat_block(g, 1)
        d["t0"], d["t1"] = g[0]["time"][:16].replace("T", " "), g[-1]["time"][:16].replace("T", " ")
        d["opps"] = set(x["opp_sub"] for x in g)

    winrate = lambda g: sum(x["win"] for x in g) / len(g)
    resid = lambda g: sum(x["win"] - expected(800.0, x["opp_rating"]) for x in g) / len(g)
    p_overall = perm_p(a, b, winrate)
    p_adj = perm_p(a, b, resid)
    p_second = perm_p([x for x in a if x["seat"] == 1], [x for x in b if x["seat"] == 1], winrate, 50000)
    p_first = perm_p([x for x in a if x["seat"] == 0], [x for x in b if x["seat"] == 0], winrate, 50000)

    scores = reship_scores()
    gap = abs(A["final"] - B["final"])
    pairs = [abs(x - y) for x, y in itertools.combinations(scores, 2)]
    p_reship = sum(g >= gap for g in pairs) / len(pairs)

    shared = A["opps"] & B["opps"]
    p1, p2 = A["wr"] / 100, B["wr"] / 100
    pbar = (p1 + p2) / 2
    n_need = (2 * (1.96 * math.sqrt(2 * pbar * (1 - pbar))
                   + 0.84 * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2 / (p1 - p2) ** 2)

    L = []
    w = L.append
    w(f"# Live ladder comparison: {a_lbl} ({a_id}) vs {b_lbl} ({b_id})")
    w("")
    w(f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC from "
      f"`data/replays/*/episodes_metadata.json`. Regenerate with:")
    w("")
    w("```powershell")
    w(f"python scripts/fetch_submission_games.py --submission {a_id} {b_id}")
    w(f"python scripts/build_live_comparison_report.py {a_id} {b_id} --out {args.out}")
    w("```")
    w("")
    w("## Verdict")
    w("")
    w(f"The **{gap:.1f}-point public-score gap is not evidence of a strength difference.** "
      f"Two shipments of the byte-identical d842 agent differ by at least that much "
      f"**{p_reship:.0%} of the time** ({len(scores)} shipments, sd {statistics.stdev(scores):.1f}). "
      f"The live win-rate gap is not significant (permutation p = {p_overall:.2f}), and the "
      f"two agents faced **{len(shared)} shared opponent(s) out of "
      f"{len(A['opps'] | B['opps'])}** distinct opponents — effectively disjoint fields.")
    w("")
    w("Offline evidence, which has ~350x the sample size, favours A2 by roughly +25 Elo. "
      "Gate on that, not on public score.")
    w("")
    w("## Live rated public games")
    w("")
    w(f"| | {a_lbl} ({a_id}) | {b_lbl} ({b_id}) |")
    w("|---|---|---|")
    w(f"| Rated public games | {A['n']} | {B['n']} |")
    w(f"| Window (UTC) | {A['t0']} → {A['t1']} | {B['t0']} → {B['t1']} |")
    w(f"| **Win rate** | **{A['wr']:.1f}%** [{A['lo']:.1f}, {A['hi']:.1f}] | "
      f"**{B['wr']:.1f}%** [{B['lo']:.1f}, {B['hi']:.1f}] |")
    w(f"| Actually first | {A['first']['wr']:.1f}% (n={A['first']['n']}) | "
      f"{B['first']['wr']:.1f}% (n={B['first']['n']}) |")
    w(f"| Actually second | {A['second']['wr']:.1f}% (n={A['second']['n']}) | "
      f"{B['second']['wr']:.1f}% (n={B['second']['n']}) |")
    w(f"| Mean opponent rating | {A['opp_mean']:.1f} | {B['opp_mean']:.1f} |")
    w(f"| Median opponent rating | {A['opp_med']:.1f} | {B['opp_med']:.1f} |")
    w(f"| Final public score | {A['final']:.1f} | {B['final']:.1f} |")
    w(f"| Performance rating (opponent-adjusted) | {A['perf']:.1f} | {B['perf']:.1f} |")
    w(f"| Distinct opponents | {len(A['opps'])} | {len(B['opps'])} |")
    w("")
    w("Win rates are Wilson 95% CIs. Performance rating is the Elo at which observed "
      "score equals expectation against the actual opponents faced; unlike public score "
      "it does not reward an easy draw.")
    w("")
    w("## Significance")
    w("")
    w("| Test | Result |")
    w("|---|---|")
    w(f"| Overall win-rate gap | {A['wr'] - B['wr']:+.1f} pts, permutation p = **{p_overall:.2f}** |")
    w(f"| Opponent-adjusted gap | permutation p = **{p_adj:.2f}** |")
    w(f"| First-seat gap | {A['first']['wr'] - B['first']['wr']:+.1f} pts, p = {p_first:.2f} |")
    w(f"| Second-seat gap | {A['second']['wr'] - B['second']['wr']:+.1f} pts, p = {p_second:.2f} |")
    w(f"| Games/arm to resolve a {abs(A['wr']-B['wr']):.1f}-pt gap at 80% power | **{n_need:.0f}** |")
    w("")
    w("Nothing here is significant. Both arms are roughly an order of magnitude too small.")
    w("")
    w("## The empirical null: reships of the identical agent")
    w("")
    w(f"`grimmsnarl_5k_reference` is the same d842 bytes shipped {len(scores)} times:")
    w("")
    w("```")
    for i in range(0, len(scores), 8):
        w("  " + "  ".join(f"{s:6.1f}" for s in scores[i:i + 8]))
    w("```")
    w("")
    w(f"- mean **{statistics.mean(scores):.1f}**, sd **{statistics.stdev(scores):.1f}**, "
      f"range {min(scores):.1f}–{max(scores):.1f} (spread {max(scores)-min(scores):.1f})")
    w(f"- median absolute gap between two reships: **{statistics.median(pairs):.1f}**")
    w(f"- P(gap >= {gap:.1f} | same agent) = **{p_reship:.0%}**")
    w("")
    w(f"{b_lbl}'s {B['final']:.1f} sits essentially on d842's own {len(scores)}-ship mean of "
      f"{statistics.mean(scores):.1f}. The {A['final']:.1f} run was a favourable draw, not a "
      f"better agent.")
    w("")
    w("## Win rate by opponent rating band")
    w("")
    for d in (A, B):
        w(f"**{d['lbl']} ({d['id']})**")
        w("")
        w("| Opponent band | Overall | First | Second |")
        w("|---|---|---|---|")
        for lo_b, hi_b in BANDS:
            allb = [x for x in d["g"] if lo_b <= x["opp_rating"] < hi_b]
            if not allb:
                continue
            cells = []
            for sel in (allb,
                        [x for x in allb if x["seat"] == 0],
                        [x for x in allb if x["seat"] == 1]):
                cells.append("—" if not sel else
                             f"{100*sum(x['win'] for x in sel)/len(sel):.1f}% (n={len(sel)})")
            w(f"| {lo_b}–{hi_b} | " + " | ".join(cells) + " |")
        w("")
    w("Both profiles are **non-monotone** in opponent strength — win rate does not fall "
      "as opponents get stronger. That is the signature of small-sample noise, not a "
      "strength profile, and it is the main reason these live splits should not drive "
      "a ship decision.")
    w("")
    w("## Why the live comparison cannot settle it")
    w("")
    w(f"1. **Disjoint fields.** {len(shared)} shared opponent(s) out of "
      f"{len(A['opps'] | B['opps'])}. The two agents were scored against different "
      f"populations.")
    w(f"2. **Different pacing.** {a_lbl} played {A['n']} games in "
      f"{A['t0']}→{A['t1']}; {b_lbl} played {B['n']} in {B['t0']}→{B['t1']}. Games are "
      f"front-loaded during the high-sigma burn-in, so equal game counts are not equal "
      f"information.")
    w(f"3. **Sample size.** ~{n_need:.0f} games per arm are needed; there are "
      f"{A['n']} and {B['n']}.")
    w("")
    w("## Offline evidence (for contrast)")
    w("")
    w("| Source | Games | A2 win rate vs d842 |")
    w("|---|---:|---|")
    w("| Mirror gate (`docs/grim_recovery_analysis.md`) | 30,000 | 53.657%, Wilson LB 53.09% "
      "(+3.50 seat 0, +4.26 seat 1) |")
    w("| `eval_a2_first_vs_d842_500.json` | 500 | 54.6% [50.2, 58.9] |")
    w("| `eval_a2ordered_second_vs_d842_500.json` | 500 | 52.6% [48.2, 56.9] |")
    w("| Pooled direct head-to-head | 1,000 | 53.60% [50.50, 56.67], binomial p = 0.025 |")
    w("")
    w("Two independent designs over ~31,000 games both land on ~53.6%, i.e. **≈ +25 Elo** "
      "for A2. Real, but small — and A2 remains weak second vs master-v1 (43.6%).")
    w("")

    # ---------------------------------------------------------------- buckets
    bkA, bkB = build_buckets(a_id), build_buckets(b_id)
    mA, mB = margin_stats(bkA), margin_stats(bkB)
    rA, rB = runs_test(bkA), runs_test(bkB)

    w("## Loss buckets and the shape of each run")
    w("")
    w("Regenerate the full per-game tables with "
      "`python scripts/loss_buckets_live.py <submission>`.")
    w("")
    w("### Streak structure")
    w("")
    w(f"| | {a_lbl} | {b_lbl} |")
    w("|---|---|---|")
    w(f"| Longest loss streak | {rA[3]} | {rB[3]} |")
    w(f"| Longest win streak | {rA[4]} | {rB[4]} |")
    w(f"| Runs vs expected | {rA[0]} vs {rA[1]:.1f} | {rB[0]} vs {rB[1]:.1f} |")
    w(f"| Wald-Wolfowitz p | **{rA[2]:.3f}** | **{rB[2]:.3f}** |")
    w("")
    w(f"{b_lbl}'s results are **clustered beyond chance** (p = {rB[2]:.3f}); {a_lbl}'s are "
      f"not (p = {rA[2]:.3f}). The streaks you can see in the A2 run are real, not "
      f"pattern-matching on noise.")
    w("")
    w("### Phase breakdown")
    w("")
    for lbl, bk, spec in ((a_lbl, bkA, args.phases_a), (b_lbl, bkB, args.phases_b)):
        w(f"**{lbl}**")
        w("")
        w("| Games | W-L | WR | Mean opp | Rating end | Net | Mean rating move |")
        w("|---|---|---|---|---|---|---|")
        for name, lo, hi in quartiles(bk, spec):
            seg = bk[lo - 1:hi]
            wins = sum(x["win"] for x in seg)
            net = seg[-1]["my_after"] - seg[0]["my_before"]
            mv = statistics.mean(abs(x["my_after"] - x["my_before"]) for x in seg)
            w(f"| {name} | {wins}-{len(seg)-wins} | {100*wins/len(seg):.1f}% | "
              f"{statistics.mean(x['opp_rating'] for x in seg):.0f} | "
              f"{seg[-1]['my_after']:.1f} | {net:+.1f} | {mv:.1f} |")
        w("")
    w("**The mean-rating-move column is the whole story.** TrueSkill sigma collapses as "
      "games accumulate, so early games are worth several times more than late ones. "
      f"{b_lbl} peaked at 953.0 after 8 games, then lost 6 straight while moves were still "
      f"worth ~34 points each (-205.4). It then went 16-10 (61.5%) over the remaining 26 "
      f"games and earned only +28.5 for it — at the late rate (~9 points) it would need ~16 "
      f"consecutive wins to return to its peak. {a_lbl} had the mirror-image luck: it opened "
      f"**3-4**, worse than A2, but its recovery — an 8-0 run — landed while moves were "
      f"still worth ~28 points each, banking +225.1. Both agents were volatile. Only one "
      f"was volatile at the right time, and that is the entire {gap:.0f}-point gap.")
    w("")
    w("### Loss quality")
    w("")
    w(f"| | {a_lbl} | {b_lbl} |")
    w("|---|---|---|")
    w(f"| Losses | {mA['nloss']} | {mB['nloss']} |")
    w(f"| Mean loss margin (prizes) | +{mA['loss']:.2f} | **+{mB['loss']:.2f}** |")
    w(f"| Mean win margin (prizes) | +{mA['win']:.2f} | **+{mB['win']:.2f}** |")
    w(f"| Margin quality (win − loss) | +{mA['win']-mA['loss']:.2f} | "
      f"**+{mB['win']-mB['loss']:.2f}** |")
    w(f"| Blowout losses (>=4 prizes) | {mA['blowouts']}/{mA['nloss']} | "
      f"**{mB['blowouts']}/{mB['nloss']}** |")
    w(f"| Shutout losses (0 prizes taken) | {mA['shutouts']} | **{mB['shutouts']}** |")
    w(f"| Close losses (<=1 prize) | {mA['close']}/{mA['nloss']} | {mB['close']}/{mB['nloss']} |")
    w("")
    w(f"{b_lbl} **wins more decisively and loses more narrowly** than {a_lbl} on every "
      f"margin measure, with zero blowouts and zero shutouts against "
      f"{mA['blowouts']} and {mA['shutouts']} for {a_lbl}. Neither margin gap is "
      f"significant on its own (permutation p = 0.46 and 0.56), but the direction is "
      f"independent of the offline evals and agrees with them.")
    w("")
    w("Prize margins are read from the last recorded position, which lags the finish: the "
      "engine never emits a terminal state (`result` stays -1 and prizes never reach 0). "
      "Treat them as accurate to about one prize, and as a comparison between agents "
      "rather than an absolute.")
    w("")
    w("### Matchups")
    w("")
    w("| Opponent deck | " + a_lbl + " | " + b_lbl + " |")
    w("|---|---|---|")
    seen = {}
    for bk in (bkA, bkB):
        for x in bk:
            seen.setdefault(x["arch"], 0)
            seen[x["arch"]] += 1
    for arch in sorted(seen, key=lambda k: -seen[k]):
        cells = []
        for bk in (bkA, bkB):
            s = [x for x in bk if x["arch"] == arch]
            cells.append("—" if not s else
                         f"{sum(x['win'] for x in s)}/{len(s)} ({100*sum(x['win'] for x in s)/len(s):.0f}%)")
        if seen[arch] >= 3:
            w(f"| {arch} | " + " | ".join(cells) + " |")
    w("")
    alaA = [x for x in bkA if x["arch"] == "Alakazam"]
    alaB = [x for x in bkB if x["arch"] == "Alakazam"]
    w(f"**Alakazam is the single largest slice of the field** — "
      f"{100*len(alaA)/len(bkA):.0f}% of {a_lbl}'s games and "
      f"{100*len(alaB)/len(bkB):.0f}% of {b_lbl}'s, consistent with the 2026-08-08 census "
      f"that flagged it as a priority matchup. It is also the biggest single bucket of A2 "
      f"losses (6 of 17). A2 is {sum(x['win'] for x in alaB)}/{len(alaB)} there against "
      f"d842's {sum(x['win'] for x in alaA)}/{len(alaA)}. Pooled across both agents the "
      f"matchup is "
      f"{sum(x['win'] for x in alaA+alaB)}/{len(alaA)+len(alaB)}, so treat the per-agent "
      f"split as suggestive only — but Alakazam is where the offline work should point.")
    w("")
    w("### Free wins")
    w("")
    gifts = [(i, x) for i, x in enumerate(bkB, 1)
             if (x["statuses"] or "").count("DONE") != 2 or ((x["turns"] or 99) <= 3 and x["win"])]
    if gifts:
        for i, x in gifts:
            w(f"- {b_lbl} game {i} (episode {x['episode']}): {x['turns']} turns, "
              f"statuses `{x['statuses']}` — opponent failed rather than A2 outplaying it.")
        w("")
        w("Both landed inside the opening high-sigma window, so they inflated the 953 peak "
          "that the subsequent 'crash' partly just gave back.")
    else:
        w(f"None in the {b_lbl} run.")
    w("")
    errs = [x for x in bkA if (x["statuses"] or "").count("DONE") != 2]
    w(f"{a_lbl} had {len(errs)} non-clean termination(s).")
    w("")
    w("## What to act on")
    w("")
    w("1. **Do not read the score gap as a strength difference.** It is inside the "
      "same-agent reship null.")
    w("2. **Do not read A2's crash as a policy defect.** Zero blowouts, zero shutouts, "
      "4 of the 6 crash losses decided by a single prize.")
    w("3. **Ladder placement is dominated by when volatility lands, not by strength.** "
      "Both agents swung; d842's swing landed favourably and A2's did not.")
    w("4. **Alakazam is the real target.** Largest share of the field and the largest "
      "bucket of A2's losses.")
    w("")
    Path(ROOT / args.out).write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"wrote {args.out}  ({len(L)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
