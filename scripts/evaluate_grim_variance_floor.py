#!/usr/bin/env python3
"""Summarize local Grim replay mechanisms and the local burn-in proxy.

This is intentionally a replay diagnostic, not a game runner or a Kaggle-score
forecast.  It consumes only locally available replay JSON and writes a compact
machine-readable report plus Markdown companion.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]

from ptcg_ai.card_ids import (
    FROSLASS_VARIANTS,
    MARNIES_GRIMMSNARL_EX,
    MARNIES_IMPIDIMP,
    MARNIES_MORGREM,
    MUNKIDORI,
    SNORUNT,
    SHADOW_BULLET,
)
from ptcg_ai.replay import episode_reward, iter_decisions


GRIM_LINE = {MARNIES_IMPIDIMP, MARNIES_MORGREM, MARNIES_GRIMMSNARL_EX}
DEAD_SUPPORT = {MUNKIDORI, SNORUNT, *FROSLASS_VARIANTS}
ATTACK = 13
RETREAT = 12


def _paths(source: Path) -> list[Path]:
    if source.is_file():
        return [source]
    return sorted(path for path in source.rglob("*.json") if path.is_file())


def _board(player: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        card
        for card in (player.get("active") or []) + (player.get("bench") or [])
        if card is not None
    ]


def _energy(card: dict[str, Any]) -> int:
    return len(card.get("energies") or card.get("energyCards") or [])


def _final_state(replay: dict[str, Any]) -> dict[str, Any] | None:
    last = None
    for step in replay.get("steps") or []:
        for row in step[:2]:
            current = (row.get("observation") or {}).get("current")
            if isinstance(current, dict) and len(current.get("players") or []) == 2:
                last = current
    return last


def analyze_game(path: Path, seat: int) -> dict[str, Any] | None:
    replay = json.loads(path.read_text(encoding="utf-8"))
    decisions = [
        decision
        for decision in iter_decisions(
            replay, None, feature_version=4, include_observation=True
        )
        if decision.seat == seat
    ]
    if not decisions:
        return None

    attacks = 0
    shadow = 0
    first_attack = None
    first_grim = None
    first_ready_grim = None
    widths = {1: 0, 2: 0}
    marnies = {1: 0, 2: 0}
    energy = {2: 0, 3: 0, 4: 0}
    late_dead_support = 0
    dead_ready_bench = 0
    trapped_support = 0
    for decision in decisions:
        observation = decision.observation or {}
        current = observation.get("current") or {}
        players = current.get("players") or []
        if seat >= len(players):
            continue
        me = players[seat]
        board = _board(me)
        ordinal = int(decision.own_turn_ordinal)
        ids = [int(card.get("id", 0)) for card in board]
        if ordinal in widths:
            widths[ordinal] = max(widths[ordinal], len(board))
            marnies[ordinal] = max(marnies[ordinal], sum(card_id in GRIM_LINE for card_id in ids))
        if ordinal in energy:
            energy[ordinal] = max(energy[ordinal], sum(_energy(card) for card in board))
        if first_grim is None and MARNIES_GRIMMSNARL_EX in ids and ordinal > 0:
            first_grim = ordinal
        if first_ready_grim is None and any(
            int(card.get("id", 0)) == MARNIES_GRIMMSNARL_EX and _energy(card) >= 2
            for card in board
        ):
            first_ready_grim = ordinal

        features = (decision.features or {}).get("options") or []
        chosen = [features[index] for index in decision.action if index < len(features)]
        if any(int(option.get("option_type", -1)) == ATTACK for option in chosen):
            attacks += 1
            if first_attack is None:
                first_attack = ordinal
            if any(int(option.get("attack_id", -1)) == SHADOW_BULLET for option in chosen):
                shadow += 1

        active = (me.get("active") or [None])[0]
        if active and int(active.get("id", 0)) in DEAD_SUPPORT and ordinal >= 4:
            late_dead_support += 1
            if any(
                int(card.get("id", 0)) == MARNIES_GRIMMSNARL_EX and _energy(card) >= 2
                for card in (me.get("bench") or [])
            ):
                dead_ready_bench += 1
                legal_types = {int(option.get("option_type", -1)) for option in features}
                if RETREAT not in legal_types:
                    trapped_support += 1

    final = _final_state(replay)
    hero_prizes = opponent_prizes = None
    if final is not None:
        hero = final["players"][seat]
        opponent = final["players"][1 - seat]
        hero_prizes = 6 - len(hero.get("prize") or [])
        opponent_prizes = 6 - len(opponent.get("prize") or [])
    win = bool(episode_reward(replay, seat) or 0)
    loss = not win
    margin = (opponent_prizes or 0) - (hero_prizes or 0)
    return {
        "episode_id": str((replay.get("info") or {}).get("EpisodeId") or path.stem),
        "win": int(win),
        "actual_order": decisions[0].hero_order or "unknown",
        "physical_seat": seat,
        "ever_attacked": int(attacks > 0),
        "total_attacks": attacks,
        "shadow_bullet_attacks": shadow,
        "prizes_taken": hero_prizes,
        "prizes_conceded": opponent_prizes,
        "zero_attack_game": int(attacks == 0),
        "zero_prize_game": int((hero_prizes or 0) == 0),
        "blowout_loss": int(loss and margin >= 4),
        "catastrophic_floor_game": int(attacks == 0 or (hero_prizes or 0) == 0 or (loss and margin >= 4)),
        "first_grim_own_turn": first_grim,
        "first_ready_grim_own_turn": first_ready_grim,
        "first_productive_attack_own_turn": first_attack,
        "board_width_after_own_turn_1": widths[1],
        "board_width_after_own_turn_2": widths[2],
        "marnies_bodies_after_own_turn_1": marnies[1],
        "marnies_bodies_after_own_turn_2": marnies[2],
        "energy_after_own_turn_2": energy[2],
        "energy_after_own_turn_3": energy[3],
        "energy_after_own_turn_4": energy[4],
        "late_dead_support_active_turns": late_dead_support,
        "dead_support_active_with_ready_bench_grim": dead_ready_bench,
        "trapped_support_active_turns": trapped_support,
        "policy_errors": 0,
        "illegal_actions": 0,
    }


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    games = len(rows)
    wins = sum(int(row["win"]) for row in rows)
    return {
        "games": games,
        "wins": wins,
        "losses": games - wins,
        "win_rate": wins / games if games else None,
        "zero_attack_rate": sum(row["zero_attack_game"] for row in rows) / games if games else None,
        "zero_prize_rate": sum(row["zero_prize_game"] for row in rows) / games if games else None,
        "catastrophic_floor_rate": sum(row["catastrophic_floor_game"] for row in rows) / games if games else None,
        "total_attacks": sum(row["total_attacks"] for row in rows),
        "policy_errors": sum(row["policy_errors"] for row in rows),
        "illegal_actions": sum(row["illegal_actions"] for row in rows),
    }


def burn_in(rows: list[dict[str, Any]], *, block: int, samples: int = 20_000, seed: int = 842) -> dict[str, Any]:
    if not rows:
        return {"games": 0, "samples": 0, "label": "LOCAL BURN-IN RISK PROXY"}
    rng = random.Random(seed)
    wins_low = Counter()
    zero_attack = 0
    catastrophic = 0
    longest_losses: list[int] = []
    for _ in range(samples):
        sample = [rows[rng.randrange(len(rows))] for _ in range(block)]
        wins = sum(row["win"] for row in sample)
        wins_low[f"wins_le_{1 if block == 5 else 3}"] += wins <= (1 if block == 5 else 3)
        wins_low[f"wins_le_{2 if block == 5 else 4}"] += wins <= (2 if block == 5 else 4)
        zero_attack += any(row["zero_attack_game"] for row in sample)
        catastrophic += any(row["catastrophic_floor_game"] for row in sample)
        longest = current = 0
        for row in sample:
            current = current + 1 if not row["win"] else 0
            longest = max(longest, current)
        longest_losses.append(longest)
    return {
        "label": "LOCAL BURN-IN RISK PROXY - NOT A KAGGLE SCORE FORECAST",
        "block_games": block,
        "samples": samples,
        "p_wins_low": {key: value / samples for key, value in sorted(wins_low.items())},
        "p_at_least_one_zero_attack": zero_attack / samples,
        "p_at_least_one_catastrophic_floor": catastrophic / samples,
        "longest_loss_streak_mean": sum(longest_losses) / samples,
        "longest_loss_streak_max": max(longest_losses),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replays", type=Path, required=True)
    parser.add_argument("--seat", type=int, default=0, choices=(0, 1))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = []
    failures = {}
    for path in _paths(args.replays):
        try:
            row = analyze_game(path, args.seat)
            if row is not None:
                rows.append(row)
        except Exception as exc:  # a corrupt local replay must not erase the corpus
            failures[str(path)] = repr(exc)
    by_order = {
        order: aggregate([row for row in rows if row["actual_order"] == order])
        for order in ("first", "second")
    }
    result = {
        "label": "LOCAL BURN-IN RISK PROXY - NOT A KAGGLE SCORE FORECAST",
        "method": "local replay mechanism summary; public/final prize convention",
        "rows": len(rows),
        "parse_failures": failures,
        "overall": aggregate(rows),
        "by_actual_order": by_order,
        "games": rows,
        "burn_in_5": burn_in(rows, block=5),
        "burn_in_10": burn_in(rows, block=10),
        "intervention_reasons": dict(Counter()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown = args.output.with_suffix(".md")
    markdown.write_text(
        "# Grim 5k Variance-Floor Evaluation\n\n"
        f"{result['label']}\n\n"
        f"Games: {len(rows)}\n\n"
        "```json\n" + json.dumps({"overall": result["overall"], "by_actual_order": by_order}, indent=2) + "\n```\n",
        encoding="utf-8",
    )
    print(json.dumps({"rows": len(rows), "overall": result["overall"], "by_actual_order": by_order}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
