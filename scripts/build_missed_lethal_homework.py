#!/usr/bin/env python3
"""Missed-lethal homework set over EXP23 live games (submission 55556726).

For every EXP23 decision with remaining prizes <= 2, run the runtime solver
offline on the ORIGINAL live observation (including its search_begin_input)
and label the decision:

- MISSED_LETHAL: solver finds a current-turn terminal win whose first action
  differs from what EXP23 actually played in that game.
- BASE_LETHAL: solver finds a terminal win; EXP23 played it.
- NO_LETHAL: no provable current-turn win found by the runtime solver.

Per-game rescue metric: a LOST game contains >= 1 MISSED_LETHAL decision.
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

from cg.api import OptionType

from ptcg_ai.endgame_lethal import EndgameLethal

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


def chosen_wins(obs, action, hero_deck: list[int], solver: EndgameLethal) -> bool:
    """True if the chosen action itself is the first step of a current-turn
    terminal win (same DFS used by the runtime solver)."""
    try:
        from ptcg_ai.search import (
            determinize_state,
            search_begin,
            search_end,
            search_release,
            search_step,
        )
        import random

        opponent = 1 - int(obs["current"]["yourIndex"])
        from ptcg_ai.search import visible_zone_cards

        state = None
        root = None
        visible = set(visible_zone_cards(obs["current"], opponent, include_hand=False))
        _, opp_deck, _ = solver.registry.match(visible)
        if opp_deck is None:
            opp_deck = hero_deck
        kwargs = determinize_state(obs, hero_deck, list(opp_deck), random.Random(2026081601))
        root = search_begin(obs, **kwargs)
        me = int(obs["current"]["yourIndex"])
        root_turn = int(obs["current"]["turn"])

        def dfs(child_state, depth):
            if depth > 6:
                return False
            cobs = child_state.observation
            cur = cobs.current
            if cur is not None and int(cur.result) >= 0:
                return int(cur.result) == me
            if cobs.select is None or cur is None:
                return False
            if int(cur.yourIndex) != me or int(cur.turn) != root_turn:
                return False
            for index, option in enumerate(cobs.select.option):
                if option.type == OptionType.PLAY:
                    hand = (cur.players[me].hand or []) if me < len(cur.players) else []
                    if option.index is not None and 0 <= option.index < len(hand):
                        card = hand[option.index]
                        if card is not None and int(card.id) in {
                            1122, 1152, 1086, 1227, 1080, 1219, 1231,
                        }:
                            continue
                child = None
                try:
                    child = search_step(int(child_state.searchId), [index])
                except Exception:
                    continue
                try:
                    if dfs(child, depth + 1):
                        return True
                finally:
                    try:
                        search_release(int(child.searchId))
                    except Exception:
                        pass
            return False

        state = search_step(int(root.searchId), [int(action[0])])
        try:
            return dfs(state, 1)
        finally:
            try:
                search_release(int(state.searchId))
            except Exception:
                pass
    except Exception:
        return False
    finally:
        try:
            search_end()
        except Exception:
            pass


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
        decisions = []
        skipped_no_sbi = 0
        for step_list in episode.get("steps", []):
            for entry in step_list:
                obs = entry.get("observation") or {}
                if not obs.get("select"):
                    continue
                current = obs.get("current") or {}
                if current.get("yourIndex") is None:
                    continue
                if int(current["yourIndex"]) != our_seat:
                    continue
                players = current.get("players") or []
                me = players[our_seat] if our_seat < len(players) else None
                if me is None:
                    continue
                prizes = len(me.get("prize") or [])
                if prizes > 2:
                    continue
                if not obs.get("search_begin_input"):
                    skipped_no_sbi += 1
                    continue
                fire = solver.try_override(obs)
                chosen = action_family(obs, entry.get("action") or [])
                if fire is None:
                    label = "NO_LETHAL"
                    override_family = None
                else:
                    override_family = action_family(obs, fire)
                    if chosen_wins(obs, entry.get("action") or [], deck, solver):
                        label = "BASE_LETHAL"
                    else:
                        label = "MISSED_LETHAL" if override_family != chosen else "BASE_LETHAL"
                decisions.append(
                    {
                        "ctx": int(obs["select"].get("context", -1)),
                        "prizes": prizes,
                        "label": label,
                        "chosen": chosen,
                        "override": override_family,
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
    rescued_lost = [
        g for g in lost_games if any(d["label"] == "MISSED_LETHAL" for d in g["decisions"])
    ]
    labels = Counter(d["label"] for g in games for d in g["decisions"])
    family = Counter(
        (json.dumps(d["chosen"], sort_keys=True), json.dumps(d["override"], sort_keys=True))
        for g in lost_games
        for d in g["decisions"]
        if d["label"] == "MISSED_LETHAL"
    )
    summary = {
        "games": len(games),
        "lost_games": len(lost_games),
        "won_games": len(won_games),
        "labels": dict(labels),
        "rescued_losses": len(rescued_lost),
        "rescue_rate": len(rescued_lost) / max(1, len(lost_games)),
        "missed_lethal_in_wins": sum(
            1 for g in won_games if any(d["label"] == "MISSED_LETHAL" for d in g["decisions"])
        ),
        "family_breakdown": dict(family.most_common(30)),
        "games": [
            {
                "episode": g["episode"],
                "won": g["won"],
                "n_decisions": len(g["decisions"]),
                "missed": sum(1 for d in g["decisions"] if d["label"] == "MISSED_LETHAL"),
                "base": sum(1 for d in g["decisions"] if d["label"] == "BASE_LETHAL"),
                "no_lethal": sum(1 for d in g["decisions"] if d["label"] == "NO_LETHAL"),
                "decisions": [
                    d
                    for d in g["decisions"]
                    if d["label"] in ("MISSED_LETHAL", "BASE_LETHAL")
                ],
            }
            for g in games
        ],
    }
    Path(args.output).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "games"}, indent=2)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
