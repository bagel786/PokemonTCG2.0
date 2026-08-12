#!/usr/bin/env python3
"""Capture auditable D0 decision traces and classify completed losses.

This runner intentionally uses the in-tree D0 directly and an authentic external
opponent package.  It is a forensic tool, not the strength evaluator: schedules
are serial, every hero prompt is retained, and order is forced in balanced blocks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

from cg.api import to_observation_class  # noqa: E402
from cg.game import battle_finish, battle_select, battle_start  # noqa: E402

from ptcg_ai.dipplin.cards import (  # noqa: E402
    APPLIN_DRAGON,
    APPLIN_GRASS,
    DIPPLIN,
    DO_THE_WAVE,
    FESTIVAL,
    GROOKEY,
    QUICK_SIGN,
    THWACKEY,
    VOLBEAT,
)
from ptcg_ai.dipplin.plan import build_macro_plan  # noqa: E402
from ptcg_ai.dipplin.policy import (  # noqa: E402
    DipplinCompetitionAgent,
    semantic_final_action,
)
from ptcg_ai.external import ExternalSubmissionAgent  # noqa: E402


def _deck(path: Path) -> list[int]:
    return [int(line) for line in path.read_text().splitlines() if line.strip()]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _card(card: Any) -> dict[str, Any] | None:
    if card is None:
        return None
    return {
        "id": int(getattr(card, "id", -1)),
        "serial": int(getattr(card, "serial", -1)),
        "hp": int(getattr(card, "hp", 0) or 0),
        "max_hp": int(getattr(card, "maxHp", 0) or 0),
        "energy": len(getattr(card, "energies", None) or []),
        "tools": [int(getattr(item, "id", -1)) for item in (getattr(card, "tools", None) or [])],
    }


def _state(obs: Any, hero_seat: int) -> dict[str, Any]:
    current = obs.current
    hero = current.players[hero_seat]
    opponent = current.players[1 - hero_seat]
    stadium = list(getattr(current, "stadium", None) or [])
    return {
        "turn": int(current.turn),
        "selector": int(current.yourIndex),
        "hero_prizes": len(hero.prize or []),
        "opponent_prizes": len(opponent.prize or []),
        "stadium": int(stadium[0].id) if stadium else None,
        "hero_active": _card((hero.active or [None])[0]),
        "hero_bench": [_card(card) for card in (hero.bench or [])],
        "opponent_active": _card((opponent.active or [None])[0]),
        "opponent_bench": [_card(card) for card in (opponent.bench or [])],
        "hero_hand_ids": [int(card.id) for card in (hero.hand or [])],
    }


def _decision(obs: Any, hero: DipplinCompetitionAgent, action: list[int]) -> dict[str, Any]:
    memory = hero.memory.clone()
    plan = build_macro_plan(obs, memory)
    proposal = hero.planner.propose(obs, None, memory)
    semantic = semantic_final_action(obs, action, proposal.intent.resolver, proposal.intent.reason)
    return {
        "state": _state(obs, int(obs.current.yourIndex)),
        "select_type": int(obs.select.type),
        "context": int(obs.select.context),
        "action": list(action),
        "kind": semantic.kind,
        "card_id": semantic.card_id,
        "target_lineage": semantic.target_lineage,
        "attack_id": semantic.attack_id,
        "resolver": proposal.intent.resolver,
        "reason": proposal.intent.reason,
        "phase": str(plan.phase.value),
        "own_turn_ordinal": plan.own_turn_ordinal,
        "missing": list(plan.missing_prerequisites),
        "festival_active": plan.festival_active,
        "replacement_ready": plan.replacement_attacker_ready,
    }


def _external_decision(obs: Any, action: list[int]) -> dict[str, Any]:
    """Capture an isolated package action without importing its private policy."""

    semantic = semantic_final_action(obs, action, "external_package", "isolated runtime")
    plan = build_macro_plan(obs)
    return {
        "state": _state(obs, int(obs.current.yourIndex)),
        "select_type": int(obs.select.type),
        "context": int(obs.select.context),
        "action": list(action),
        "kind": semantic.kind,
        "card_id": semantic.card_id,
        "target_lineage": semantic.target_lineage,
        "attack_id": semantic.attack_id,
        "resolver": "external_package",
        "reason": "isolated runtime",
        "phase": str(plan.phase.value),
        "own_turn_ordinal": plan.own_turn_ordinal,
        "missing": list(plan.missing_prerequisites),
        "festival_active": plan.festival_active,
        "replacement_ready": plan.replacement_attacker_ready,
    }


def _classify(trace: list[dict[str, Any]]) -> tuple[str, list[str]]:
    decisions = [item for item in trace if item.get("actor") == "hero"]
    resolvers = [str(item["decision"]["resolver"]) for item in decisions]
    first_attack = next(
        (item["decision"] for item in decisions if item["decision"].get("attack_id") == DO_THE_WAVE),
        None,
    )
    quick = [item["decision"] for item in decisions if item["decision"]["resolver"] == "quick_sign"]
    flags: list[str] = []
    if quick:
        flags.append("quick_sign_opening")
    if first_attack is None:
        flags.append("never_attacked")
    elif int(first_attack["own_turn_ordinal"]) >= 4:
        flags.append("late_first_attack")
    if any(r == "quick_sign_attack" for r in resolvers):
        flags.append("quick_sign_ended_setup")
    if any(r in {"end", "fallback_attack"} for r in resolvers[:12]):
        flags.append("early_dead_turn")
    if not any(r.startswith("evolve_thwackey") or r.startswith("thwackey") for r in resolvers):
        flags.append("no_thwackey_engine")
    if first_attack and not bool(first_attack["festival_active"]):
        flags.append("first_attack_without_festival")
    if first_attack and not bool(first_attack["replacement_ready"]):
        flags.append("first_attack_without_replacement")
    if "never_attacked" in flags:
        bucket = "never_established_attacker"
    elif "late_first_attack" in flags or "early_dead_turn" in flags:
        bucket = "setup_and_attachment_delay"
    elif "first_attack_without_replacement" in flags:
        bucket = "brittle_single_attacker"
    elif "no_thwackey_engine" in flags:
        bucket = "engine_not_established"
    else:
        bucket = "prize_race_or_targeting"
    return bucket, flags


def run_game(
    opponent_path: Path,
    *,
    hero_seat: int,
    go_first: bool,
    cap: int,
    opponent_env: dict[str, str] | None = None,
    hero_submission: Path | None = None,
) -> dict[str, Any]:
    hero = (
        ExternalSubmissionAgent(hero_submission, {})
        if hero_submission is not None
        else DipplinCompetitionAgent(search_enabled=False, go_first=go_first)
    )
    opponent = ExternalSubmissionAgent(opponent_path, dict(opponent_env or {}))
    decks = [list(hero.deck), list(opponent.deck)] if hero_seat == 0 else [list(opponent.deck), list(hero.deck)]
    raw, started = battle_start(decks[0], decks[1])
    if raw is None or int(started.errorType) != 0:
        opponent.close()
        raise RuntimeError(f"battle_start error {int(started.errorType)}")
    trace: list[dict[str, Any]] = []
    first_player: int | None = None
    try:
        for step in range(cap):
            obs = to_observation_class(raw)
            if first_player is None and int(obs.current.firstPlayer) in (0, 1):
                first_player = int(obs.current.firstPlayer)
            if int(obs.current.result) >= 0:
                result = int(obs.current.result)
                order = "first" if first_player == hero_seat else "second"
                outcome = "win" if result == hero_seat else "loss"
                bucket, flags = _classify(trace) if outcome == "loss" else ("win", [])
                return {
                    "hero_seat": hero_seat,
                    "requested_order": "first" if go_first else "second",
                    "first_player": first_player,
                    "actual_order": order,
                    "result_seat": result,
                    "outcome": outcome,
                    "loss_bucket": bucket,
                    "loss_flags": flags,
                    "trace": trace,
                }
            actor = int(obs.current.yourIndex)
            if actor == hero_seat:
                action = hero(raw)
                decision = (
                    _external_decision(obs, action)
                    if hero_submission is not None
                    else _decision(obs, hero, action)
                )
                item = {"step": step, "actor": "hero", "decision": decision}
            else:
                action = opponent(raw)
                item = {"step": step, "actor": "opponent", "state": _state(obs, hero_seat), "action": list(action)}
            trace.append(item)
            raw = battle_select(action)
        raise RuntimeError(f"decision cap {cap} exceeded")
    finally:
        battle_finish()
        if isinstance(hero, ExternalSubmissionAgent):
            hero.close()
        opponent.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--opponent", type=Path, required=True)
    parser.add_argument("--games-per-order", type=int, default=20)
    parser.add_argument("--max-decisions", type=int, default=2000)
    parser.add_argument("--opponent-env", default="{}", help="JSON object of explicit opponent environment overrides")
    parser.add_argument("--hero-submission", type=Path, help="optional extracted isolated hero package for diagnostics")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    opponent_env = json.loads(args.opponent_env)
    if not isinstance(opponent_env, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in opponent_env.items()
    ):
        raise ValueError("--opponent-env must be a JSON object of string pairs")
    rows: list[dict[str, Any]] = []
    # Alternate physical seats inside each forced-order block.
    for go_first in (True, False):
        for index in range(args.games_per_order):
            rows.append(
                run_game(
                    args.opponent,
                    hero_seat=index % 2,
                    go_first=go_first,
                    cap=args.max_decisions,
                    opponent_env=opponent_env,
                    hero_submission=args.hero_submission,
                )
            )
    losses = [row for row in rows if row["outcome"] == "loss"]
    report = {
        "schema": "dipplin-loss-forensics-v1",
        "opponent": str(args.opponent.resolve()),
        "opponent_deck_sha256": _sha(args.opponent / "deck.csv"),
        "games": len(rows),
        "wins": sum(row["outcome"] == "win" for row in rows),
        "losses": len(losses),
        "actual_order": {
            order: {
                "games": sum(row["actual_order"] == order for row in rows),
                "wins": sum(row["actual_order"] == order and row["outcome"] == "win" for row in rows),
            }
            for order in ("first", "second")
        },
        "loss_buckets": dict(Counter(row["loss_bucket"] for row in losses)),
        "loss_flags": dict(Counter(flag for row in losses for flag in row["loss_flags"])),
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: report[key] for key in ("games", "wins", "losses", "actual_order", "loss_buckets", "loss_flags")}, indent=2))


if __name__ == "__main__":
    main()
