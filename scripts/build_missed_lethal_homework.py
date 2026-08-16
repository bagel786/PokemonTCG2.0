#!/usr/bin/env python3
"""Missed-lethal homework set over EXP23 live games (submission 55556726).

Replay alignment follows the canonical walker (replay_disagreement.py): the
action answering the observation at steps[t][seat] is stored at
steps[t+1][seat]["action"].

For every EXP23 decision with remaining prizes <= 2, run the hardened runtime
solver offline on the ORIGINAL live observation (including its
search_begin_input) with the base-first API and classify:

- NO_PROVED_LETHAL : no terminal continuation proven for EXP23's action and
                     no alternative proven.
- BASE_ALREADY_LETHAL : EXP23's own action has a proven terminal continuation.
- MISSED_LETHAL_RESCUE : EXP23's action is not proven terminal but an
                     alternative action is (in all determinization worlds).

Per-game rescue metric: a LOST game counts once if it contains >= 1
MISSED_LETHAL_RESCUE state.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from cg.api import OptionType, to_observation_class

from ptcg_ai.endgame_lethal import EndgameLethal, WORLD_SEEDS

SUBMISSION = 55556726


def action_family(obs, action) -> dict | None:
    if not action:
        return None
    options = (obs.get("select") or {}).get("option") or []
    index = int(action[0])
    if index >= len(options):
        return None
    option = options[index]
    record = {"type": int(option.get("type", -1))}
    if record["type"] == int(OptionType.PLAY):
        current = obs.get("current") or {}
        players = current.get("players") or []
        me = int(current.get("yourIndex", 0))
        hand = (players[me].get("hand") or []) if me < len(players) else []
        oi = option.get("index")
        if oi is not None and 0 <= oi < len(hand):
            card = hand[oi]
            if card:
                record["card_id"] = int(card.get("id", 0))
    if record["type"] == int(OptionType.ATTACK):
        record["attack_id"] = int(option.get("attackId", 0) or 0)
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-dir", required=True)
    parser.add_argument("--deck", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    replay_dir = Path(args.replay_dir)
    deck = [int(line) for line in Path(args.deck).read_text().splitlines() if line.strip()]
    metadata = json.loads((replay_dir / "episodes_metadata.json").read_text())

    solver = EndgameLethal(deck)
    games = []
    for meta in metadata:
        episode_id = meta["id"]
        agents = meta["agents"]
        ours = [a for a in agents if a.get("submissionId") == SUBMISSION]
        if not ours:
            continue
        our_seat = int(ours[0].get("index", agents.index(ours[0])))
        won = int(ours[0].get("reward", 0)) > 0
        replay_path = replay_dir / f"episode-{episode_id}-replay.json"
        if not replay_path.exists():
            continue
        episode = json.loads(replay_path.read_text())
        steps = episode.get("steps") or []
        decisions = []
        skipped_no_sbi = 0
        for step_index in range(len(steps) - 1):
            row = steps[step_index]
            if our_seat >= len(row):
                continue
            obs = (row[our_seat].get("observation") or {}) or {}
            if not obs.get("select"):
                continue
            current = obs.get("current") or {}
            if current.get("yourIndex") is None or int(current["yourIndex"]) != our_seat:
                continue
            me = (current.get("players") or [None] * (our_seat + 1))[our_seat] or {}
            prizes = len(me.get("prize") or [])
            if prizes > 2:
                continue
            if not obs.get("search_begin_input"):
                skipped_no_sbi += 1
                continue
            following = steps[step_index + 1]
            action = following[our_seat].get("action") if our_seat < len(following) else None
            if not isinstance(action, list):
                continue
            try:
                parsed = to_observation_class(obs)
            except Exception:
                continue
            base_wins = any(solver.action_wins(parsed, list(action), seed) for seed in WORLD_SEEDS)
            fire = solver.try_override(obs, list(action))
            if fire is None:
                label = "BASE_ALREADY_LETHAL" if base_wins else "NO_PROVED_LETHAL"
                override_family = None
                winning_line = None
            else:
                label = "MISSED_LETHAL_RESCUE"
                override_family = action_family(obs, fire)
                line: list = []
                for seed in WORLD_SEEDS:
                    if solver.action_wins(parsed, list(fire), seed, trace=line):
                        break
                    line = []
                winning_line = [{"ctx": ctx, "action": act} for ctx, act in line]
            decisions.append(
                {
                    "ctx": int(obs["select"].get("context", -1)),
                    "prizes": prizes,
                    "label": label,
                    "chosen": action_family(obs, action),
                    "override": override_family,
                    "winning_line": winning_line,
                }
            )
        solver.reset()
        games.append(
            {
                "episode": episode_id,
                "won": won,
                "decisions": decisions,
                "skipped_no_sbi": skipped_no_sbi,
            }
        )

    lost_games = [g for g in games if not g["won"]]
    won_games = [g for g in games if g["won"]]
    rescued = [
        g for g in lost_games if any(d["label"] == "MISSED_LETHAL_RESCUE" for d in g["decisions"])
    ]
    labels = Counter(d["label"] for g in games for d in g["decisions"])
    family = Counter(
        (
            json.dumps(d["chosen"], sort_keys=True),
            json.dumps(d["override"], sort_keys=True),
        )
        for g in lost_games
        for d in g["decisions"]
        if d["label"] == "MISSED_LETHAL_RESCUE"
    )
    summary = {
        "games": len(games),
        "lost_games": len(lost_games),
        "won_games": len(won_games),
        "lost_games_reaching_endgame": sum(1 for g in lost_games if g["decisions"]),
        "eligible_decisions": sum(len(g["decisions"]) for g in games),
        "labels": dict(labels),
        "distinct_lost_games_rescuable": len(rescued),
        "rescue_rate": len(rescued) / max(1, len(lost_games)),
        "missed_lethal_in_wins": sum(
            1 for g in won_games if any(d["label"] == "MISSED_LETHAL_RESCUE" for d in g["decisions"])
        ),
        "family_breakdown_lost_games": dict(family.most_common(30)),
        "games": [
            {
                "episode": g["episode"],
                "won": g["won"],
                "n_decisions": len(g["decisions"]),
                "missed": sum(1 for d in g["decisions"] if d["label"] == "MISSED_LETHAL_RESCUE"),
                "base": sum(1 for d in g["decisions"] if d["label"] == "BASE_ALREADY_LETHAL"),
                "no_lethal": sum(1 for d in g["decisions"] if d["label"] == "NO_PROVED_LETHAL"),
                "rescues": [
                    d
                    for d in g["decisions"]
                    if d["label"] == "MISSED_LETHAL_RESCUE"
                ],
            }
            for g in games
        ],
    }
    Path(args.output).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "games"}, indent=2)[:5000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
