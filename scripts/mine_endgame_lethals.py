#!/usr/bin/env python3
"""Offline mine: play EXP23 against an opponent with the seeded engine and, at
every hero decision where remaining prizes <= 2, run the EndgameLethal solver
on the live observation. Report eligibility, fire rate, missed lethals (fires
whose action differs semantically from EXP23's action), action families, and
solver latency percentiles.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from cg.api import OptionType, SelectContext, to_observation_class

from ptcg_ai.endgame_lethal import EndgameLethal
from ptcg_ai.external import ExternalSubmissionAgent
from ptcg_ai.safety import sanitize_selection
from training.evaluate_deterministic_crn import SeededEngine, get_engine


def _forced_order(select, hero_seat: int, order: str) -> list[int]:
    seat_zero_first = (order == "first") == (hero_seat == 0)
    desired = OptionType.YES if seat_zero_first else OptionType.NO
    choices = [index for index, option in enumerate(select.option) if option.type == desired]
    return sanitize_selection(select, choices, 1)


def _action_family(obs, action) -> dict | None:
    try:
        if not action:
            return None
        index = int(action[0])
        option = obs.select.option[index]
        record = {"type": int(option.type)}
        if option.type == OptionType.PLAY:
            me = int(obs.current.yourIndex)
            hand = obs.current.players[me].hand or []
            if option.index is not None and 0 <= option.index < len(hand):
                card = hand[option.index]
                if card is not None:
                    record["card_id"] = int(card.id)
        if option.type == OptionType.ATTACK:
            record["attack_id"] = int(getattr(option, "attackId", 0) or 0)
        return record
    except Exception:
        return None


def _run_game(task: dict) -> dict:
    seed = int(task["seed"])
    engine = get_engine(task["engine"])
    hero = ExternalSubmissionAgent(task["hero"])
    opponent = ExternalSubmissionAgent(task["opponent"])
    hero_seat = int(task["physical_seat"])
    order = str(task["actual_order"])
    agents = {hero_seat: hero, 1 - hero_seat: opponent}
    decks = [hero.deck, opponent.deck] if hero_seat == 0 else [opponent.deck, hero.deck]
    solver = EndgameLethal(hero.deck)
    rows = []
    eligible = 0
    overrides = 0
    base_abstentions = 0
    no_proof = 0
    latencies: list[float] = []
    battle_ptr = 0
    try:
        battle_ptr, raw = engine.start(decks[0], decks[1], seed)
        while True:
            obs = to_observation_class(raw)
            if obs.current is not None and int(obs.current.result) >= 0:
                return {
                    "seed": seed,
                    "rows": rows,
                    "latencies": latencies,
                    "eligible": eligible,
                    "overrides": overrides,
                    "base_abstentions": base_abstentions,
                    "no_proof": no_proof,
                }
            if obs.select.context == SelectContext.IS_FIRST:
                action = _forced_order(obs.select, hero_seat, order)
            else:
                acting = int(obs.current.yourIndex)
                if acting == hero_seat:
                    action = hero(raw)
                    prizes = len(obs.current.players[hero_seat].prize or [])
                    if prizes <= 2 and obs.select.option:
                        eligible += 1
                        before = len(solver.fires)
                        override = solver.try_override(raw, list(action))
                        after = len(solver.fires)
                        if override is not None:
                            overrides += 1
                            chosen_family = _action_family(obs, list(action))
                            override_family = _action_family(obs, list(override))
                            rows.append(
                                {
                                    "ctx": int(obs.select.context),
                                    "prizes": prizes,
                                    "differs": chosen_family != override_family,
                                    "chosen": chosen_family,
                                    "override": override_family,
                                }
                            )
                        elif solver.last_abstain == "base_already_lethal":
                            base_abstentions += 1
                        else:
                            no_proof += 1
                        for fire in solver.fires[before:after]:
                            latencies.append(float(fire.get("elapsed_ms", 0.0)))
                else:
                    action = opponent(raw)
            raw = engine.select(battle_ptr, action)
    finally:
        if battle_ptr:
            engine.finish(battle_ptr)
        hero.close()
        opponent.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", required=True)
    parser.add_argument("--hero", required=True)
    parser.add_argument("--opponent", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--base-seed", type=int, default=2026081661)
    parser.add_argument("--games-per-order", type=int, default=40)
    parser.add_argument("--orders", default="first,second")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    tasks = []
    for order in args.orders.split(","):
        order_index = 0 if order == "first" else 1
        for index in range(args.games_per_order):
            tasks.append(
                {
                    "seed": args.base_seed + order_index * 100_000 + index,
                    "engine": args.engine,
                    "hero": args.hero,
                    "opponent": args.opponent,
                    "physical_seat": index % 2,
                    "actual_order": order,
                }
            )
    started = time.time()
    ctx = mp.get_context("spawn")
    all_rows: list[dict] = []
    latencies: list[float] = []
    eligible = overrides = base_abstentions = no_proof = 0
    with ctx.Pool(args.workers) as pool:
        for result in pool.imap_unordered(_run_game, tasks, chunksize=1):
            all_rows.extend(result["rows"])
            latencies.extend(result["latencies"])
            eligible += result["eligible"]
            overrides += result["overrides"]
            base_abstentions += result["base_abstentions"]
            no_proof += result["no_proof"]
    latencies.sort()
    missed = [row for row in all_rows if row["differs"]]
    from collections import Counter

    family_breakdown = Counter(
        (
            int(row["ctx"]),
            row["chosen"] or {},
            row["override"] or {},
        ).__str__()
        for row in missed
    )
    n = len(latencies)
    summary = {
        "games": len(tasks),
        "elapsed_seconds": round(time.time() - started, 1),
        "eligible_decisions": eligible,
        "successful_proofs": len(latencies),
        "actual_overrides": overrides,
        "base_already_lethal_abstentions": base_abstentions,
        "no_proof_abstentions": no_proof,
        "missed_lethals": len(missed),
        "family_breakdown": dict(family_breakdown),
        "latency_ms": {
            "p50": latencies[n // 2] if n else None,
            "p95": latencies[int(n * 0.95)] if n else None,
            "max": latencies[-1] if n else None,
        },
        "missed_examples": missed[:15],
    }
    Path(args.output).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "missed_examples"}, indent=2))
    print("missed count:", len(missed))
    for row in missed[:10]:
        print(" ", json.dumps(row, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
