#!/usr/bin/env python3
"""Mine recurring, mechanically-checkable failure buckets from 5k Grim replays.

Every detector below reads only what the engine actually offered the agent at a
decision (the ``select.option`` list) plus the public board state, so a flagged
turn is a situation the agent could have played differently, not a hypothetical.

Each bucket is tagged with the *lookahead depth* a search would need to fix it:

``1-ply``
    The remedy is a single legal option at the flagged decision.  A correctly
    implemented one-step search that scores each option can find it.
``n-ply``
    The remedy is a sequence of main-phase actions within one turn (for example
    attach, then retreat, then attack).  A one-step search cannot find it,
    because no single option improves the position on its own.
``structural``
    No legal remedy existed at the flagged decision.  Search cannot help; only
    earlier play or deck/draw luck could.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterator, Mapping

ROOT = Path(__file__).resolve().parents[1]

# Engine enums (freshstart/ENGINE.md).
OPT_CARD = 3
OPT_ATTACH = 8
OPT_EVOLVE = 9
OPT_RETREAT = 12
OPT_ATTACK = 13
OPT_END = 14
CTX_MAIN = 0
AREA_ACTIVE = 4
AREA_BENCH = 5

GRIMMSNARL_EX = 648
MORGREM = 647
IMPIDIMP = 646
BOSS_ORDERS = 1182
SHADOW_BULLET = 937
SHADOW_BULLET_BENCH_DAMAGE = 30
SHADOW_BULLET_DAMAGE = 180

# Attack cost in Basic {D} Energy for the Marnie's line.  Every other Pokemon in
# the deck (Snorunt, Froslass, Munkidori) has an attack cost this deck cannot pay
# at all, so it can never attack regardless of how much Energy is attached.
DARK_ATTACK_COST = {GRIMMSNARL_EX: 2, MORGREM: 2, IMPIDIMP: 1}


def as_mon(value: Any) -> Mapping[str, Any] | None:
    """Return the single Pokemon in an active/bench slot, or ``None`` if empty."""

    if isinstance(value, list):
        value = value[0] if value else None
    return value if isinstance(value, Mapping) else None


def can_attack(mon: Mapping[str, Any] | None) -> bool:
    cost = DARK_ATTACK_COST.get(int(mon["id"])) if mon else None
    return cost is not None and len(mon.get("energies") or []) >= cost


def hero_decisions(steps: list, seat: int) -> Iterator[tuple[int, dict, dict, list]]:
    """Yield ``(step, current, select, action)`` for each active hero decision."""

    for index in range(len(steps) - 1):
        row = steps[index][seat]
        if str(row.get("status", "")).upper() != "ACTIVE":
            continue
        observation = row.get("observation") or {}
        current, select = observation.get("current"), observation.get("select")
        if not isinstance(current, Mapping) or not isinstance(select, Mapping):
            continue
        action = steps[index + 1][seat].get("action")
        yield index, current, select, action if isinstance(action, list) else []


def analyze(replay: Mapping[str, Any], seat: int) -> dict:
    """Return per-bucket turn counts for one episode from the hero's seat."""

    steps = replay.get("steps") or []
    turns: dict[int, dict] = defaultdict(
        lambda: {
            "attack_offered": False,
            "attacked": False,
            "attach_active_offered": False,
            "retreat_offered": False,
            "final": None,
        }
    )
    buckets: Counter = Counter()
    details: list[dict] = []

    for index, current, select, action in hero_decisions(steps, seat):
        options = select.get("option") or []
        chosen = [options[i] for i in action if i < len(options)]
        turn = int(current.get("turn", -1))
        me = current["players"][seat]
        opponent = current["players"][1 - seat]

        if int(select.get("context", -1)) == CTX_MAIN:
            types = {int(o.get("type", -1)) for o in options}
            record = turns[turn]
            record["attack_offered"] |= OPT_ATTACK in types
            record["retreat_offered"] |= OPT_RETREAT in types
            # Scan the whole turn: an Energy that could have freed the Active is
            # gone from the option list by the time the agent ends the turn.
            record["attach_active_offered"] |= any(
                int(o.get("type", -1)) == OPT_ATTACH
                and int(o.get("inPlayArea", -1)) == AREA_ACTIVE
                for o in options
            )
            if any(int(o.get("type", -1)) == OPT_ATTACK for o in chosen):
                record["attacked"] = True
            if any(int(o.get("type", -1)) == OPT_END for o in chosen):
                record["final"] = {"step": index, "options": options, "me": me}

        # Shadow Bullet's 30-damage bench snipe is a standalone selection whose
        # value is fully visible one step ahead: a target at <=30 HP is a prize.
        if chosen and all(int(o.get("type", -1)) == OPT_CARD for o in chosen):
            targets = [
                o
                for o in options
                if int(o.get("type", -1)) == OPT_CARD
                and int(o.get("playerIndex", seat)) != seat
                and int(o.get("area", -1)) == AREA_BENCH
            ]
            if len(targets) > 1 and len(targets) == len(options):
                bench = opponent.get("bench") or []

                def hp_of(option: Mapping[str, Any]) -> int | None:
                    slot = int(option.get("index", -1))
                    mon = as_mon(bench[slot]) if 0 <= slot < len(bench) else None
                    return int(mon["hp"]) if mon else None

                lethal = [o for o in targets if (hp_of(o) or 999) <= SHADOW_BULLET_BENCH_DAMAGE]
                took = [o for o in chosen if (hp_of(o) or 999) <= SHADOW_BULLET_BENCH_DAMAGE]
                if lethal and not took:
                    buckets["B4_bench_snipe_ko_declined"] += 1
                    details.append({"bucket": "B4", "turn": turn, "step": index})

    for turn, record in sorted(turns.items()):
        final = record["final"]
        if final is None:
            continue
        if record["attack_offered"] and not record["attacked"]:
            buckets["B1_attack_offered_but_turn_ended"] += 1
            details.append({"bucket": "B1", "turn": turn, "step": final["step"]})
            continue
        if record["attacked"]:
            continue

        # No attack was ever offered this turn.  Was the Active simply unable to
        # attack while a fuelled attacker sat on the bench?
        me = final["me"]
        active = as_mon(me.get("active"))
        bench = [as_mon(b) for b in (me.get("bench") or [])]
        if active is None or can_attack(active):
            continue
        if not any(can_attack(b) for b in bench):
            buckets["B3_dead_active_no_bench_attacker"] += 1
            details.append({"bucket": "B3", "turn": turn, "step": final["step"]})
            continue
        if record["retreat_offered"]:
            buckets["B2a_dead_active_retreat_was_legal"] += 1
            details.append({"bucket": "B2a", "turn": turn, "step": final["step"]})
        elif record["attach_active_offered"]:
            buckets["B2b_dead_active_attach_would_free"] += 1
            details.append({"bucket": "B2b", "turn": turn, "step": final["step"]})
        else:
            buckets["B3_dead_active_stranded"] += 1
            details.append({"bucket": "B3", "turn": turn, "step": final["step"]})

    return {"buckets": dict(buckets), "details": details, "hero_turns": len(turns)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="artifacts/grim_5k_history/manifest.partial.json")
    parser.add_argument("--extra-games", action="append", default=[],
                        help="submission_id=path/to/games.json for corpora outside the manifest")
    parser.add_argument("--output", default="artifacts/grim_loss_buckets/report.json")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    episodes: list[dict] = []
    manifest = json.loads((ROOT / args.manifest).read_text(encoding="utf-8"))
    for submission in manifest["submissions"]:
        if submission.get("deck_class") != "exact_original_grim":
            continue
        for episode in submission.get("episodes") or []:
            path = episode.get("replay")
            if path and Path(path).exists():
                episodes.append({
                    "submission_id": submission["submission_id"],
                    "episode_id": episode["episode_id"],
                    "seat": int(episode["seat"]),
                    "outcome": float(episode["outcome"]),
                    "path": path,
                })
    for spec in args.extra_games:
        submission_id, _, games_path = spec.partition("=")
        rows = json.loads((ROOT / games_path).read_text(encoding="utf-8"))
        for row in rows:
            path = row.get("replay_path")
            if path and Path(path).exists():
                episodes.append({
                    "submission_id": int(submission_id),
                    "episode_id": row["episode_id"],
                    "seat": int(row["seat"]),
                    "outcome": float(row["outcome"]),
                    "path": path,
                })
    if args.limit:
        episodes = episodes[: args.limit]

    per_outcome: dict[str, Counter] = {"loss": Counter(), "win": Counter()}
    turns_seen = {"loss": 0, "win": 0}
    games_seen = {"loss": 0, "win": 0}
    per_episode: list[dict] = []
    for count, episode in enumerate(episodes, 1):
        try:
            replay = json.loads(Path(episode["path"]).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"skip {episode['episode_id']}: {exc}", file=sys.stderr)
            continue
        result = analyze(replay, episode["seat"])
        key = "loss" if episode["outcome"] < 0 else "win"
        per_outcome[key].update(result["buckets"])
        turns_seen[key] += result["hero_turns"]
        games_seen[key] += 1
        per_episode.append({**{k: v for k, v in episode.items() if k != "path"}, **result})
        if count % 25 == 0:
            print(f"[{count}/{len(episodes)}]", flush=True)

    report = {
        "games": games_seen,
        "hero_turns": turns_seen,
        "buckets_by_outcome": {k: dict(v) for k, v in per_outcome.items()},
        "per_episode": per_episode,
    }
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"\ngames: {games_seen}   hero turns: {turns_seen}")
    names = sorted(set(per_outcome["loss"]) | set(per_outcome["win"]))
    print(f"\n{'bucket':40s} {'loss':>8s} {'/turn':>8s} {'win':>8s} {'/turn':>8s}")
    for name in names:
        loss, win = per_outcome["loss"][name], per_outcome["win"][name]
        lr = loss / turns_seen["loss"] if turns_seen["loss"] else 0
        wr = win / turns_seen["win"] if turns_seen["win"] else 0
        print(f"{name:40s} {loss:8d} {lr:8.4f} {win:8d} {wr:8.4f}")
    print(f"\nwrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
