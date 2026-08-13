#!/usr/bin/env python3
"""Capture a second-opening MAIN prompt fixture (hero actual-second, turn 1,
Volbeat active, Quick Sign legal) for the S1 regression/unit tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from cg.api import OptionType, SelectContext, SelectType, to_observation_class
from cg.game import battle_finish, battle_select, battle_start

from ptcg_ai.dipplin.cards import APPLIN_GRASS, APPLIN_DRAGON, EXACT_DECK, QUICK_SIGN, VOLBEAT
from ptcg_ai.dipplin.plan import build_macro_plan
from ptcg_ai.dipplin.policy import DipplinCompetitionAgent


def main() -> int:
    out_dir = ROOT / "artifacts" / "dipplin_prompt_audit"
    captured = None
    for attempt in range(200):
        hero = DipplinCompetitionAgent(search_enabled=False)
        raw, started = battle_start(list(EXACT_DECK), list(EXACT_DECK))
        if started.errorType:
            battle_finish()
            continue
        decisions = 0
        try:
            while True:
                obs = to_observation_class(raw)
                if obs.current is not None and int(obs.current.result) >= 0:
                    break
                if obs.select.context == SelectContext.IS_FIRST:
                    # force the hero to go second
                    hero_seat = int(obs.current.yourIndex)
                    seat_zero_first = (hero_seat == 0)
                    desired = OptionType.NO if seat_zero_first else OptionType.YES
                    choices = [i for i, o in enumerate(obs.select.option) if o.type == desired]
                    action = choices
                else:
                    plan = build_macro_plan(obs)
                    attacks = [o for o in obs.select.option if o.type == OptionType.ATTACK]
                    attack_ids = [int(o.attackId) for o in attacks]
                    if (
                        int(obs.select.type) == int(SelectType.MAIN)
                        and plan.actual_order == "second"
                        and plan.own_turn_ordinal == 1
                        and plan.active is not None
                        and plan.active.card_id == VOLBEAT
                        and QUICK_SIGN in attack_ids
                    ):
                        captured = raw
                        out_dir.mkdir(parents=True, exist_ok=True)
                        (out_dir / "second_opening_quick_sign.json").write_text(
                            json.dumps({"observation": raw}, indent=2, sort_keys=True) + "\n"
                        )
                        print("captured second-opening fixture", flush=True)
                        return 0
                    action = hero(raw)
                raw = battle_select(action)
                decisions += 1
                if decisions > 3000:
                    break
        finally:
            battle_finish()
            hero.reset()
    print("no second-opening state found in 200 games", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
