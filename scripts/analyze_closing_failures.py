#!/usr/bin/env python3
"""Was a losing streak bad luck, or an inability to close won positions?

Reads the prize trajectory of every live game and asks the only question that
separates the two: when we got to one prize from winning, how often did we
actually win -- and how often did the opponent convert the same position
against us? A symmetric conversion rate is variance. An asymmetric one is a
closing defect.

The engine never emits the terminal state (`result` stays -1 and the winning
prize is never recorded), so "prizes taken" is read from the last recorded
position and lags the finish by exactly the game-winning prize.

Usage:
    python scripts/analyze_closing_failures.py 55399728 55397271
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import NormalDist

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from compare_live_two_subs import load  # noqa: E402

PRIZES = 6


def trajectory(replay: dict, seat: int) -> list[tuple[int, int, int, int]]:
    """(turn, our prizes taken, their prizes taken, our deck count), de-duped.

    Each seat's observation only refreshes on its own turn, so merge both
    views and keep the furthest-along record for each turn number.
    """
    by_turn: dict[int, tuple[int, int, int]] = {}
    for step in replay.get("steps", []):
        for agent in step:
            cur = (agent.get("observation") or {}).get("current")
            if not cur:
                continue
            mine, theirs = cur["players"][seat], cur["players"][1 - seat]
            if not mine["prize"] or not theirs["prize"]:
                continue  # setup-phase view: prizes not dealt yet, not a 6-0 lead
            took = (PRIZES - len(mine["prize"]), PRIZES - len(theirs["prize"]))
            # a fresh view of the same turn can only be further along
            turn = cur["turn"]
            best = by_turn.get(turn)
            cand = (*took, mine["deckCount"])
            if best is None or cand[:2] >= best[:2]:
                by_turn[turn] = cand
    return [(t, *by_turn[t]) for t in sorted(by_turn)]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return float("nan"), float("nan")
    p, d = k / n, 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return 100 * (c - h), 100 * (c + h)


def two_proportion_p(k1: int, n1: int, k2: int, n2: int) -> float:
    """Two-sided z-test on the difference of two proportions."""
    if not n1 or not n2:
        return float("nan")
    p1, p2 = k1 / n1, k2 / n2
    p = (k1 + k2) / (n1 + n2)
    se = (p * (1 - p) * (1 / n1 + 1 / n2)) ** 0.5
    if se == 0:
        return 1.0
    return 2 * (1 - NormalDist().cdf(abs(p1 - p2) / se))


def build(sub_id: int) -> list[dict]:
    rep_dir = ROOT / "data" / "replays" / str(sub_id)
    out = []
    for g in load(sub_id):
        path = rep_dir / f"episode-{g['episode']}-replay.json"
        if not path.exists():
            continue
        replay = json.loads(path.read_text(encoding="utf-8"))
        traj = trajectory(replay, g["seat"])
        if not traj:
            continue
        turn, mine, theirs, deck = traj[-1]
        # peak position we ever held, and the peak they ever held
        my_peak = max(t[1] for t in traj)
        their_peak = max(t[2] for t in traj)
        my_best_lead = max(t[1] - t[2] for t in traj)
        their_best_lead = max(t[2] - t[1] for t in traj)
        out.append({
            **g,
            "turns": turn,
            "my_took": mine,
            "opp_took": theirs,
            "my_peak": my_peak,
            "their_peak": their_peak,
            "my_best_lead": my_best_lead,
            "their_best_lead": their_best_lead,
            "min_deck": min(t[3] for t in traj),
            "statuses": replay.get("statuses"),
        })
    return out


def report(sub_id: int, games: list[dict]) -> None:
    wins = sum(g["win"] for g in games)
    print("=" * 88)
    print(f"CLOSING ANALYSIS - submission {sub_id}  ({len(games)} games, {wins}W-{len(games)-wins}L)")
    print("=" * 88)

    # 1. Conversion from one prize away, both directions.
    print("\nCONVERSION FROM ONE PRIZE AWAY  (peak prizes taken == 5)")
    ours = [g for g in games if g["my_peak"] >= PRIZES - 1]
    theirs = [g for g in games if g["their_peak"] >= PRIZES - 1]
    ok = sum(g["win"] for g in ours)
    them_ok = sum(not g["win"] for g in theirs)
    print(f"  we reached 5 prizes in {len(ours):>3} games, won {ok:>3}"
          f"  = {100*ok/max(len(ours),1):5.1f}%  {wilson(ok, len(ours))}")
    print(f"  they reached 5 prizes in {len(theirs):>3} games, won {them_ok:>3}"
          f"  = {100*them_ok/max(len(theirs),1):5.1f}%  {wilson(them_ok, len(theirs))}")
    print(f"  asymmetry p = {two_proportion_p(ok, len(ours), them_ok, len(theirs)):.3f}"
          "   (low p = closing defect, high p = variance)")

    # 2. Losses from a position that was ahead.
    print("\nLOSSES FROM AHEAD")
    losses = [g for g in games if not g["win"]]
    for lead in (1, 2, 3):
        blown = [g for g in losses if g["my_best_lead"] >= lead]
        held = [g for g in games if g["my_best_lead"] >= lead]
        print(f"  ever led by >={lead}: {len(held):>3} games, lost {len(blown):>3}"
              f"  = {100*len(blown)/max(len(held),1):5.1f}%")
    for lead in (1, 2, 3):
        blown = [g for g in games if g["win"] and g["their_best_lead"] >= lead]
        held = [g for g in games if g["their_best_lead"] >= lead]
        print(f"  they ever led by >={lead}: {len(held):>3} games, they lost {len(blown):>3}"
              f"  = {100*len(blown)/max(len(held),1):5.1f}%")

    # 3. Loss shape.
    print("\nLOSS SHAPE")
    if losses:
        never = [g for g in losses if g["my_took"] <= 2]
        stalled = [g for g in losses if g["my_peak"] >= PRIZES - 1]
        print(f"  losses where we took <=2 prizes (crushed):      {len(never):>3}/{len(losses)}")
        print(f"  losses where we reached 5 prizes (stalled out): {len(stalled):>3}/{len(losses)}")
        print(f"  mean turns: losses {sum(g['turns'] for g in losses)/len(losses):.1f}, "
              f"wins {sum(g['turns'] for g in games if g['win'])/max(wins,1):.1f}")
        print(f"  min deck count seen across all games: {min(g['min_deck'] for g in games)}"
              "  (0 would mean deck-out)")

    # 4. The streaks themselves.
    print("\nSTREAKS  (>=3 losses)")
    seq = [g["win"] for g in games]
    i = 0
    while i < len(seq):
        j = i
        while j < len(seq) and seq[j] == seq[i]:
            j += 1
        if not seq[i] and j - i >= 3:
            print(f"  games {i+1}-{j} ({j-i} losses)")
            print("    #  seat   opp  turns  prizes  peak  best-lead")
            for k in range(i, j):
                g = games[k]
                print(f"    {k+1:>2}  {'first' if g['seat']==0 else 'second':<6}"
                      f"{g['opp_rating']:>6.0f}  {g['turns']:>5}  {g['my_took']}-{g['opp_took']}"
                      f"    {g['my_peak']}     {g['my_best_lead']:+d}")
        i = j


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("submissions", nargs="+", type=int)
    args = ap.parse_args()
    for sub in args.submissions:
        report(sub, build(sub))
        print()
    return 0


def _selfcheck() -> None:
    """Trajectory reading must survive the lagging second-seat view."""
    fake = {"steps": [
        [{"observation": {"current": {"turn": 3, "players": [
            {"prize": [0] * 4, "deckCount": 20}, {"prize": [0] * 5, "deckCount": 22}]}}},
         {"observation": {"current": {"turn": 2, "players": [
             {"prize": [0] * 5, "deckCount": 21}, {"prize": [0] * 5, "deckCount": 22}]}}}],
    ]}
    seat0 = trajectory(fake, 0)
    assert seat0 == [(2, 1, 1, 21), (3, 2, 1, 20)], seat0
    seat1 = trajectory(fake, 1)
    assert seat1[-1][1:3] == (1, 2), seat1


if __name__ == "__main__":
    _selfcheck()
    raise SystemExit(main())
