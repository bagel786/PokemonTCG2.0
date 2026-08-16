#!/usr/bin/env python3
"""Sterile-extract + complete-game smoke of the final candidate archive.

Extracts the tar.gz into a fresh temp dir, plays seeded full games vs the
Dipplin D1 package with the route forced (evaluation-only env), and reports
policy errors + terminal results. Also runs one non-target game (B0) to
confirm base behavior with rules active but route unlocked.
"""
from __future__ import annotations

import argparse
import json
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

from ptcg_ai.external import ExternalSubmissionAgent  # noqa: E402
from training.evaluate_deterministic_crn import SeededEngine, _policy_errors  # noqa: E402

ENGINE = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/deterministic_engine/bin/libcg_seeded.dylib")
D1 = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/sprint_870/opponents/dipplin_d1")
B0 = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/grim_variance_floor/candidates/B0")


def play_game(engine, hero, opp, seed, hero_seat, forced_order="first"):
    decks = [hero.deck, opp.deck] if hero_seat == 0 else [opp.deck, hero.deck]
    battle_ptr, raw = engine.start(decks[0], decks[1], seed)
    from cg.api import OptionType, to_observation_class
    decisions = 0
    try:
        while True:
            obs = to_observation_class(raw)
            if obs.current is not None and int(obs.current.result) >= 0:
                return int(obs.current.result), decisions
            if obs.select.context == 41:  # IS_FIRST
                seat_zero_first = (forced_order == "first") == (hero_seat == 0)
                desired = OptionType.YES if seat_zero_first else OptionType.NO
                choices = [i for i, o in enumerate(obs.select.option) if o.type == desired]
                action = choices[:1]
            else:
                acting = int(obs.current.yourIndex)
                action = hero(raw) if acting == hero_seat else opp(raw)
            raw = engine.select(battle_ptr, action)
            decisions += 1
            if decisions > 2000:
                return -9, decisions
    finally:
        engine.finish(battle_ptr)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", required=True)
    parser.add_argument("--seed", type=int, default=2026081700)
    parser.add_argument("--games", type=int, default=6)
    args = parser.parse_args()

    engine = SeededEngine(ENGINE)
    with tempfile.TemporaryDirectory(prefix="sterile-") as temp:
        extract = Path(temp) / "extracted"
        extract.mkdir()
        with tarfile.open(args.archive, "r:gz") as tar:
            tar.extractall(extract)
        contents = sorted(p.name for p in extract.iterdir())
        if "main.py" not in contents or "deck.csv" not in contents:
            print("FAIL: missing root files", contents)
            return 1

        hero = ExternalSubmissionAgent(
            extract, {"PTCG_TARGET_ROUTE": "force_dipplin"}
        )
        d1 = ExternalSubmissionAgent(D1, {})
        b0 = ExternalSubmissionAgent(B0, {})
        results = []
        for i in range(args.games):
            seat = i % 2
            result, decisions = play_game(engine, hero, d1, args.seed + i, seat)
            results.append({"game": i, "seat": seat, "result": result, "decisions": decisions})
        non_target = []
        for i in range(3):
            seat = i % 2
            result, decisions = play_game(engine, hero, b0, args.seed + 1000 + i, seat)
            non_target.append({"game": i, "seat": seat, "result": result, "decisions": decisions})
        errors = _policy_errors(hero)
        report = {
            "archive": args.archive,
            "root_files": contents,
            "deck_cards": len(hero.deck),
            "hero_policy_errors": errors,
            "vs_d1": results,
            "vs_b0_non_target": non_target,
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        hero.close()
        d1.close()
        b0.close()
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
