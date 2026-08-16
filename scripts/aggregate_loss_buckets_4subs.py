#!/usr/bin/env python3
"""Aggregate loss buckets across the last 4 live submissions.

Usage: python scripts/aggregate_loss_buckets_4subs.py
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from loss_buckets_live import build  # noqa: E402

SUBS = (55513649, 55513642, 55491471, 55491464)

games = []
for sub in SUBS:
    for g in build(sub):
        g["sub"] = sub
        games.append(g)

losses = [g for g in games if not g["win"]]
wins = [g for g in games if g["win"]]
n = len(games)
print(f"TOTAL: {n} games, {len(wins)}W {len(losses)}L "
      f"({100 * len(wins) / n:.1f}% WR) across {len(SUBS)} submissions\n")

print("=" * 72)
print("PER-SUB")
print(f"{'sub':>10} {'W':>3} {'L':>3} {'WR':>6} {'WR first':>9} {'WR second':>10} {'final rtg':>10}")
for sub in SUBS:
    sg = [g for g in games if g["sub"] == sub]
    w = sum(g["win"] for g in sg)
    first = [g for g in sg if g["seat"] == 0]
    second = [g for g in sg if g["seat"] == 1]
    fw = 100 * sum(g["win"] for g in first) / max(1, len(first))
    sw = 100 * sum(g["win"] for g in second) / max(1, len(second))
    print(f"{sub:>10} {w:>3} {len(sg)-w:>3} {100*w/len(sg):>5.1f}% "
          f"{fw:>8.1f}% {sw:>9.1f}% {sg[-1]['my_after']:>10.1f}")

print("\n" + "=" * 72)
print("GOING FIRST vs GOING SECOND (all 4 subs combined)")
for seat, label in ((0, "first"), (1, "second")):
    sg = [g for g in games if g["seat"] == seat]
    w = sum(g["win"] for g in sg)
    print(f"  {label:<7} {w}/{len(sg)}  {100*w/max(1,len(sg)):.1f}% WR   "
          f"({len(sg)} games, {len(sg)-w} losses)")
first_l = [g for g in losses if g["seat"] == 0]
second_l = [g for g in losses if g["seat"] == 1]
print(f"  losses when going second: {len(second_l)}/{len(losses)} "
      f"({100*len(second_l)/max(1,len(losses)):.0f}% of all losses)")

print("\n" + "=" * 72)
print("LOSS BUCKETS BY ARCHETYPE (all 4 subs)")
by = defaultdict(list)
for g in games:
    by[g["arch"]].append(g)
for k, v in sorted(by.items(), key=lambda kv: -len(kv[1])):
    w = sum(x["win"] for x in v)
    f = [x for x in v if x["seat"] == 0]
    s = [x for x in v if x["seat"] == 1]
    fw = 100 * sum(x["win"] for x in f) / max(1, len(f))
    sw = 100 * sum(x["win"] for x in s) / max(1, len(s))
    print(f"  {k:<24} {w}/{len(v):>3}  {100*w/len(v):>5.1f}% WR   "
          f"first {len(f)-sum(x['win'] for x in f)}L/{len(f)} ({fw:.0f}%)   "
          f"second {len(s)-sum(x['win'] for x in s)}L/{len(s)} ({sw:.0f}%)")

print("\n" + "=" * 72)
print("LOSSES BY ARCHETYPE x SEAT (going second focus)")
arch_seat = defaultdict(list)
for g in losses:
    arch_seat[(g["arch"], g["seat"])].append(g)
print(f"{'archetype':<24} {'second':>7} {'first':>6} {'share of all losses':>20}")
tot = len(losses)
rows = defaultdict(lambda: [0, 0])
for (arch, seat), v in arch_seat.items():
    rows[arch][seat] = len(v)
for arch, (snd, fst) in sorted(rows.items(), key=lambda kv: -sum(kv[1])):
    print(f"  {arch:<24} {snd:>6}L {fst:>5}L "
          f"{100*(snd+fst)/tot:>19.0f}%")

print("\n" + "=" * 72)
print("PRIZE MARGIN OF LOSSES (their prizes minus ours)")
marg = [g["opp_took"] - g["my_took"] for g in losses if g["my_took"] is not None]
c = Counter(marg)
for k in sorted(c):
    tag = "blowout" if k >= 4 else "clear" if k >= 2 else "close"
    print(f"  {k:+d}  {c[k]:>3}   {tag}")
blow = sum(1 for m in marg if m >= 4)
close = sum(1 for m in marg if m <= 1)
print(f"  blowouts (>=4): {blow}/{len(marg)} ({100*blow/len(marg):.0f}%)   "
      f"close (<=1): {close}/{len(marg)} ({100*close/len(marg):.0f}%)")

sm = [g["opp_took"] - g["my_took"] for g in losses
      if g["my_took"] is not None and g["seat"] == 1]
fm = [g["opp_took"] - g["my_took"] for g in losses
      if g["my_took"] is not None and g["seat"] == 0]
if sm and fm:
    print(f"  mean margin going second: {sum(sm)/len(sm):+.2f}  "
          f"going first: {sum(fm)/len(fm):+.2f}")

turns_l = [g["turns"] for g in losses if g["turns"]]
turns_w = [g["turns"] for g in wins if g["turns"]]
print(f"\n  game length: losses {sum(turns_l)/len(turns_l):.1f} turns, "
      f"wins {sum(turns_w)/len(turns_w):.1f} turns")
