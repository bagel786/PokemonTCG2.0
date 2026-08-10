#!/usr/bin/env python3
"""Bucket every live loss for a submission, in ladder order.

Answers "what actually went wrong" rather than "how often": game length,
prize margin at the end, opponent archetype, seat, and whether the loss was
a blowout or a coin-flip. Also splits the run into ladder phases so a
climb-then-crash shape can be read directly.

Usage:
    python scripts/loss_buckets_live.py 55399728
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import NormalDist

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from compare_live_two_subs import load  # noqa: E402

CARD_DB = ROOT / "freshstart" / "elite_submissions" / "alakazam_2_7" / "agent" / "card_db.json"

# Archetype fingerprints, derived from the decks actually seen on this ladder.
# Card names are owner-prefixed ("Marnie's Grimmsnarl ex"), so match on substring.
# First match wins, so the defining attacker must come before its support line.
FINGERPRINTS = [
    ("Mega Lucario ex", ("Mega Lucario ex",)),
    ("Mega Kangaskhan ex", ("Mega Kangaskhan ex",)),
    ("Mega Starmie ex", ("Mega Starmie ex",)),
    ("Mega Froslass ex", ("Mega Froslass ex",)),
    ("Grimmsnarl ex (mirror)", ("Grimmsnarl ex",)),
    ("Cynthia's Garchomp ex", ("Cynthia's Garchomp ex",)),
    ("Archaludon ex", ("Archaludon ex", "Duraludon")),
    ("Iono's Bellibolt ex", ("Bellibolt ex",)),
    ("Espeon ex", ("Espeon ex",)),
    ("Ogerpon ex", ("Ogerpon ex",)),
    ("Alakazam", ("Alakazam", "Kadabra", "Abra")),
    ("Crustle", ("Crustle", "Dwebble")),
    ("Hariyama", ("Hariyama", "Makuhita")),
    ("Cinderace", ("Cinderace",)),
    ("Lunatone/Solrock", ("Lunatone", "Solrock")),
]

# Generic support/tech Pokemon that appear across many decks and must never
# be used to name an archetype.
SUPPORT = {
    "Munkidori", "Fezandipiti ex", "Fezandipiti", "Dunsparce", "Dudunsparce",
    "Shaymin", "Relicanth", "Dedenne", "Snorunt", "Froslass", "Riolu",
    "Sylveon", "Eevee", "Staryu", "Lillie's Clefairy ex",
}


def card_names() -> tuple[dict[int, str], dict[int, bool]]:
    """id -> name, and id -> is-a-Pokemon (only Pokemon carry hp)."""
    db = json.loads(CARD_DB.read_text(encoding="utf-8"))
    return ({int(k): v["name"] for k, v in db.items()},
            {int(k): v.get("hp") is not None for k, v in db.items()})


def final_state(replay: dict) -> dict | None:
    """Latest game state across BOTH agents.

    Each agent's observation only refreshes on its own turn, so one seat's view
    lags the other by a turn. Take whichever is furthest along. Note the engine
    never emits a terminal state: `result` stays -1 and prizes never reach 0,
    so this is the position shortly before the finish, not the final position.
    """
    best, best_turn = None, -1
    for step in replay.get("steps", []):
        for agent in step:
            cur = (agent.get("observation") or {}).get("current")
            if cur and cur.get("turn", 0) > best_turn:
                best, best_turn = cur, cur["turn"]
    return best


def pokemon_seen(cur: dict, idx: int, names: dict[int, str],
                 ismon: dict[int, bool]) -> set[str]:
    """Every Pokemon that player revealed, from board and discard."""
    seen = set()
    pl = cur["players"][idx]
    for slot in list(pl.get("active") or []) + list(pl.get("bench") or []):
        for c in [slot] + list(slot.get("preEvolution") or []):
            if ismon.get(c.get("id")):
                seen.add(names.get(c["id"], str(c["id"])))
    for c in pl.get("discard") or []:
        if ismon.get(c.get("id")):
            seen.add(names.get(c["id"], str(c["id"])))
    return seen


def archetype(seen: set[str]) -> str:
    core = {s for s in seen if s not in SUPPORT}
    for label, keys in FINGERPRINTS:
        if any(k in s for s in core for k in keys):
            return label
    return "unknown" if not core else f"other ({sorted(core)[0]})"


def build(sub_id: int) -> list[dict]:
    names, ismon = card_names()
    rep_dir = ROOT / "data" / "replays" / str(sub_id)
    out = []
    for g in load(sub_id):
        path = rep_dir / f"episode-{g['episode']}-replay.json"
        rec = dict(g)
        rec.update(turns=None, my_took=None, opp_took=None, arch="no-replay",
                   statuses=None, my_deck=None)
        if path.exists():
            try:
                rep = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                out.append(rec)
                continue
            rec["statuses"] = ",".join(rep.get("statuses") or [])
            cur = final_state(rep)
            if cur:
                # players[] is globally indexed (card playerIndex fields confirm),
                # so use the seat derived from episode metadata, not yourIndex,
                # which is relative to whichever agent recorded the observation.
                mine, opp = g["seat"], 1 - g["seat"]
                rec["turns"] = cur.get("turn")
                # Prizes TAKEN is the readable direction: 6 minus those remaining.
                rec["my_took"] = 6 - len(cur["players"][mine].get("prize") or [])
                rec["opp_took"] = 6 - len(cur["players"][opp].get("prize") or [])
                rec["arch"] = archetype(pokemon_seen(cur, opp, names, ismon))
                rec["my_deck"] = archetype(pokemon_seen(cur, mine, names, ismon))
        out.append(rec)
    return out


def phases(games: list[dict], spec: str | None) -> list[tuple[str, int, int]]:
    """Explicit '1-8,9-14,...' boundaries, else quarters of the run."""
    if spec:
        out = []
        for part in spec.split(","):
            lo, hi = (int(x) for x in part.split("-"))
            out.append((f"{lo}-{hi}", lo, hi))
        return out
    n = len(games)
    cuts = [round(n * i / 4) for i in range(5)]
    return [(f"{cuts[i]+1}-{cuts[i+1]}", cuts[i] + 1, cuts[i + 1])
            for i in range(4) if cuts[i + 1] > cuts[i]]


def streaks(games: list[dict]) -> None:
    """Run-length structure plus a Wald-Wolfowitz test for real clustering."""
    seq = "".join("W" if g["win"] else "L" for g in games)
    runs = [(k, len(list(v))) for k, v in itertools.groupby(seq)]
    print(f"\n  sequence: {seq}")
    print(f"  runs: {' '.join(f'{k}{n}' for k, n in runs)}")
    print(f"  longest loss streak {max([n for k, n in runs if k=='L'], default=0)}, "
          f"longest win streak {max([n for k, n in runs if k=='W'], default=0)}")
    n1, n2, R = seq.count("W"), seq.count("L"), len(runs)
    if n1 and n2 and n1 + n2 > 1:
        mu = 2 * n1 * n2 / (n1 + n2) + 1
        var = (2 * n1 * n2 * (2 * n1 * n2 - n1 - n2)
               / ((n1 + n2) ** 2 * (n1 + n2 - 1)))
        z = (R - mu) / math.sqrt(var)
        p = 2 * (1 - NormalDist().cdf(abs(z)))
        verdict = "clustered beyond chance" if p < 0.05 else "consistent with chance"
        print(f"  runs test: R={R} vs {mu:.1f} expected, z={z:+.2f}, p={p:.3f} -> {verdict}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sub", type=int)
    ap.add_argument("--phases", help="e.g. '1-8,9-14,15-32,33-40'; default quarters")
    args = ap.parse_args()
    games = build(args.sub)

    print(f"\n{'='*100}\nLOSS BUCKETS - submission {args.sub}  ({len(games)} rated games)\n{'='*100}")
    hdr = (f"{'#':>3} {'res':<4} {'seat':<6} {'opp':>5} {'rating':>7} {'turns':>5} "
           f"{'prizes me-opp':>13}  {'opponent deck':<24} {'status'}")
    print(hdr)
    for i, g in enumerate(games, 1):
        pm = ("  -" if g["my_took"] is None else f"{g['my_took']}-{g['opp_took']}")
        bad = "" if (g["statuses"] or "").count("DONE") == 2 else f"  <- {g['statuses']}"
        print(f"{i:>3} {'WIN' if g['win'] else 'LOSS':<4} "
              f"{'first' if g['seat']==0 else 'second':<6} {g['opp_rating']:>5.0f} "
              f"{g['my_after']:>7.1f} {str(g['turns'] or '-'):>5} {pm:>13}  "
              f"{g['arch']:<24}{bad}")

    losses = [g for g in games if not g["win"]]
    wins = [g for g in games if g["win"]]

    print(f"\n{'='*100}\nSTREAK STRUCTURE\n{'='*100}")
    streaks(games)

    print(f"\n{'='*100}\nPHASE BREAKDOWN\n{'='*100}")
    print(f"{'phase':<14} {'W-L':>7} {'WR':>7} {'opp rtg':>8} {'avg turns':>10} "
          f"{'rating end':>11} {'net rating':>11} {'mean |move|':>12}")
    for label, lo, hi in phases(games, args.phases):
        seg = games[lo - 1:hi]
        if not seg:
            continue
        w = sum(x["win"] for x in seg)
        t = [x["turns"] for x in seg if x["turns"]]
        net = seg[-1]["my_after"] - seg[0]["my_before"]
        mv = statistics.mean(abs(x["my_after"] - x["my_before"]) for x in seg)
        print(f"{label:<14} {f'{w}-{len(seg)-w}':>7} {100*w/len(seg):>6.1f}% "
              f"{statistics.mean(x['opp_rating'] for x in seg):>8.0f} "
              f"{(statistics.mean(t) if t else 0):>10.1f} "
              f"{seg[-1]['my_after']:>11.1f} {net:>+11.1f} {mv:>12.1f}")

    print(f"\n{'='*100}\nLOSS ANATOMY  ({len(losses)} losses)\n{'='*100}")

    def dist(sel, key, label):
        c = Counter(x[key] for x in sel)
        print(f"\n  {label}")
        for k, n in c.most_common():
            print(f"    {str(k):<18} {n:>3}  ({100*n/len(sel):.0f}%)")

    dist(losses, "arch", "opponent deck in losses:")
    print("\n  same, as a win rate per deck faced:")
    by = defaultdict(list)
    for g in games:
        by[g["arch"]].append(g)
    for k, v in sorted(by.items(), key=lambda kv: -len(kv[1])):
        w = sum(x["win"] for x in v)
        print(f"    {k:<18} {w}/{len(v)}  {100*w/len(v):>5.1f}%")

    # Prize margin: how close were the losses? Positive = we were behind.
    marg = [(g["opp_took"] - g["my_took"]) for g in losses if g["my_took"] is not None]
    if marg:
        print("\n  loss margin (their prizes taken minus ours; higher = more one-sided):")
        c = Counter(marg)
        for k in sorted(c):
            tag = ("blowout" if k >= 4 else "clear" if k >= 2 else "close")
            print(f"    {k:+d} prizes  {c[k]:>3}   {tag}")
        print(f"    mean {statistics.mean(marg):+.2f}")
        blow = sum(1 for m in marg if m >= 4)
        close = sum(1 for m in marg if m <= 1)
        print(f"    blowouts (>=4): {blow}/{len(marg)} ({100*blow/len(marg):.0f}%)   "
              f"close (<=1): {close}/{len(marg)} ({100*close/len(marg):.0f}%)")
        wm = [(g["my_took"] - g["opp_took"]) for g in wins if g["my_took"] is not None]
        if wm:
            print(f"    for contrast, win margin mean {statistics.mean(wm):+.2f}")

    lt = [g["turns"] for g in losses if g["turns"]]
    wt = [g["turns"] for g in wins if g["turns"]]
    if lt and wt:
        print(f"\n  game length: losses mean {statistics.mean(lt):.1f} turns "
              f"(median {statistics.median(lt):.0f}), wins mean {statistics.mean(wt):.1f} "
              f"(median {statistics.median(wt):.0f})")

    errs = [g for g in games if (g["statuses"] or "").count("DONE") != 2]
    print(f"\n  non-clean terminations: {len(errs)}"
          + ("" if not errs else "  <- INVESTIGATE"))
    for g in errs:
        print(f"    episode {g['episode']}  {g['statuses']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
