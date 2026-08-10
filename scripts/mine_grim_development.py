#!/usr/bin/env python3
"""Measure board-development trajectories for 5k Grim replays.

The loss-bucket survey showed that the dominant loss signature is a late-game
Active that cannot attack *with nothing on the bench that could either* — a
board-development failure rather than a mis-chosen option.  This script measures
the development itself, so the lever can be identified rather than asserted.

For each game, from the hero's seat, it records when the deck's engine came
online (Grimmsnarl ex in play, Energy in play, first attack) and correlates that
with the outcome.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.mine_grim_loss_buckets import (
    CTX_MAIN,
    GRIMMSNARL_EX,
    OPT_ATTACK,
    as_mon,
    can_attack,
    hero_decisions,
)

MARNIES_LINE = frozenset({646, 647, 648})


def in_play(player: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    mons = [as_mon(player.get("active"))]
    mons.extend(as_mon(slot) for slot in (player.get("bench") or []))
    return [mon for mon in mons if mon is not None]


def analyze(replay: Mapping[str, Any], seat: int) -> dict:
    steps = replay.get("steps") or []
    # State at the *start* of each turn, taken from the first observation
    # carrying that turn number.
    per_turn: dict[int, dict] = {}
    for step in steps:
        for who in (0, 1):
            current = (step[who].get("observation") or {}).get("current")
            if not isinstance(current, Mapping) or len(current.get("players") or []) != 2:
                continue
            turn = int(current.get("turn", -1))
            if turn in per_turn:
                continue
            me = current["players"][seat]
            opponent = current["players"][1 - seat]
            mons = in_play(me)
            per_turn[turn] = {
                "bench": len(me.get("bench") or []),
                "energy_in_play": sum(len(m.get("energies") or []) for m in mons),
                "has_grimmsnarl": any(int(m["id"]) == GRIMMSNARL_EX for m in mons),
                "has_attacker": any(can_attack(m) for m in mons),
                "marnies_bodies": sum(int(m["id"]) in MARNIES_LINE for m in mons),
                "prizes_left": len(me.get("prize") or []),
                "opponent_prizes_left": len(opponent.get("prize") or []),
            }

    first_attack = None
    attacks = 0
    for _, current, select, action in hero_decisions(steps, seat):
        if int(select.get("context", -1)) != CTX_MAIN:
            continue
        options = select.get("option") or []
        if any(int(options[i].get("type", -1)) == OPT_ATTACK for i in action if i < len(options)):
            attacks += 1
            turn = int(current.get("turn", -1))
            first_attack = turn if first_attack is None else min(first_attack, turn)

    ordered = sorted(per_turn.items())
    # Prizes must come from the true terminal observation.  ``per_turn`` holds
    # the state at the *start* of each turn, which misses the final knockouts.
    terminal = None
    for step in steps:
        for who in (0, 1):
            current = (step[who].get("observation") or {}).get("current")
            if isinstance(current, Mapping) and len(current.get("players") or []) == 2:
                terminal = current

    def first_turn_where(key: str) -> int | None:
        return next((t for t, row in ordered if row[key]), None)

    def at_turn(turn: int, key: str):
        candidates = [row for t, row in ordered if t <= turn]
        return candidates[-1][key] if candidates else None

    return {
        "turns": ordered[-1][0] if ordered else 0,
        "first_grimmsnarl_turn": first_turn_where("has_grimmsnarl"),
        "first_attacker_turn": first_turn_where("has_attacker"),
        "first_attack_turn": first_attack,
        "attacks": attacks,
        "bench_at_t2": at_turn(2, "bench"),
        "bench_at_t4": at_turn(4, "bench"),
        "energy_at_t4": at_turn(4, "energy_in_play"),
        "energy_at_t6": at_turn(6, "energy_in_play"),
        "energy_at_t8": at_turn(8, "energy_in_play"),
        "marnies_at_t4": at_turn(4, "marnies_bodies"),
        "marnies_at_t8": at_turn(8, "marnies_bodies"),
        # A player takes cards from *their own* prize pile on a knockout, so the
        # hero's remaining prize count is what measures the hero's knockouts.
        "prizes_taken": (
            6 - len(terminal["players"][seat].get("prize") or []) if terminal else None
        ),
        "prizes_conceded": (
            6 - len(terminal["players"][1 - seat].get("prize") or []) if terminal else None
        ),
    }


def summarize(rows: list[dict], keys: list[str]) -> None:
    losses = [r for r in rows if r["outcome"] < 0]
    wins = [r for r in rows if r["outcome"] > 0]
    print(f"\n{'metric':26s} {'loss median':>12s} {'win median':>12s} {'loss mean':>11s} {'win mean':>10s}")
    for key in keys:
        lv = [r[key] for r in losses if r.get(key) is not None]
        wv = [r[key] for r in wins if r.get(key) is not None]
        if not lv or not wv:
            continue
        print(f"{key:26s} {statistics.median(lv):12.2f} {statistics.median(wv):12.2f}"
              f" {statistics.mean(lv):11.2f} {statistics.mean(wv):10.2f}")
    print(f"\n{'metric':26s} {'losses missing':>15s} {'wins missing':>13s}   (never happened)")
    for key in ("first_grimmsnarl_turn", "first_attack_turn", "first_attacker_turn"):
        ln = sum(r.get(key) is None for r in losses)
        wn = sum(r.get(key) is None for r in wins)
        print(f"{key:26s} {ln:6d}/{len(losses)} ({ln/len(losses):4.0%}) {wn:5d}/{len(wins)} ({wn/len(wins):4.0%})")


def conditional_win_rate(rows: list[dict], key: str, buckets: list) -> None:
    """Print the win rate conditioned on a development metric."""

    print(f"\nwin rate by {key}:")
    for low, high in zip(buckets, buckets[1:] + [None]):
        selected = [
            r for r in rows
            if r.get(key) is not None and r[key] >= low and (high is None or r[key] < high)
        ]
        if not selected:
            continue
        wins = sum(r["outcome"] > 0 for r in selected)
        label = f">={low}" if high is None else f"{low}-{high - 1}"
        print(f"  {label:>8s}  n={len(selected):4d}  win rate {wins / len(selected):5.1%}")
    missing = [r for r in rows if r.get(key) is None]
    if missing:
        wins = sum(r["outcome"] > 0 for r in missing)
        print(f"  {'never':>8s}  n={len(missing):4d}  win rate {wins / len(missing):5.1%}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="artifacts/grim_5k_history/manifest.partial.json")
    parser.add_argument("--extra-games", action="append", default=[])
    parser.add_argument("--output", default="artifacts/grim_loss_buckets/development.json")
    args = parser.parse_args()

    episodes: list[dict] = []
    manifest = json.loads((ROOT / args.manifest).read_text(encoding="utf-8"))
    for submission in manifest["submissions"]:
        if submission.get("deck_class") != "exact_original_grim":
            continue
        for episode in submission.get("episodes") or []:
            if episode.get("replay") and Path(episode["replay"]).exists():
                episodes.append({"submission_id": submission["submission_id"],
                                 "episode_id": episode["episode_id"],
                                 "seat": int(episode["seat"]),
                                 "outcome": float(episode["outcome"]),
                                 "path": episode["replay"]})
    for spec in args.extra_games:
        submission_id, _, games_path = spec.partition("=")
        for row in json.loads((ROOT / games_path).read_text(encoding="utf-8")):
            if row.get("replay_path") and Path(row["replay_path"]).exists():
                episodes.append({"submission_id": int(submission_id),
                                 "episode_id": row["episode_id"],
                                 "seat": int(row["seat"]),
                                 "outcome": float(row["outcome"]),
                                 "path": row["replay_path"]})

    rows: list[dict] = []
    for count, episode in enumerate(episodes, 1):
        try:
            replay = json.loads(Path(episode["path"]).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"skip {episode['episode_id']}: {exc}", file=sys.stderr)
            continue
        rows.append({**{k: v for k, v in episode.items() if k != "path"},
                     **analyze(replay, episode["seat"])})
        if count % 50 == 0:
            print(f"[{count}/{len(episodes)}]", flush=True)

    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    summarize(rows, ["first_grimmsnarl_turn", "first_attacker_turn", "first_attack_turn",
                     "attacks", "bench_at_t2", "bench_at_t4", "energy_at_t4", "energy_at_t6",
                     "energy_at_t8", "marnies_at_t4", "marnies_at_t8", "prizes_taken",
                     "prizes_conceded", "turns"])
    for key, buckets in (("bench_at_t2", [0, 1, 2, 3]),
                         ("energy_at_t6", [0, 2, 4, 6]),
                         ("energy_at_t8", [0, 2, 4, 6, 8]),
                         ("first_grimmsnarl_turn", [1, 5, 7, 9]),
                         ("first_attack_turn", [1, 4, 6, 8])):
        conditional_win_rate(rows, key, buckets)
    print(f"\nwrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
