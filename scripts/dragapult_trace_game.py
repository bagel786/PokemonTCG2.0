#!/usr/bin/env python3
"""Trace hero decisions in live games with card names (fixed field access)."""
import csv
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))

from cg import sim as cg_sim
from cg.game import battle_finish, battle_select, battle_start
from cg.api import to_observation_class
from ptcg_ai.external import ExternalSubmissionAgent

NAMES = {}
for row in csv.DictReader((ROOT / "freshstart" / "data" / "EN_Card_Data.csv").read_text(encoding="utf-8-sig").splitlines()):
    NAMES[int(row["Card ID"])] = row["Card Name"]

CTX = {7: "CHOOSE_ACTIVE", 8: "CHOOSE_BENCH", 9: "ATTACH", 10: "EVOLVE", 11: "PLAY",
       12: "ABILITY", 18: "SEARCH", 19: "DISCARD", 20: "RECOVER", 21: "DRAW",
       22: "PRIZE", 23: "ENERGY_SEARCH", 24: "REVEAL", 25: "DAMAGE", 26: "SHUFFLE",
       28: "BENCH_PLACE", 30: "COIN", 31: "ATTACK", 32: "RETREAT", 33: "EVOLVE2",
       34: "TARGET", 35: "RETREAT_ENERGY", 36: "HAND_DISCARD", 37: "DECK_PLACE",
       38: "PLACE", 39: "SWITCH", 40: "MOVE_ENERGY", 0: "ROOT", 41: "IS_FIRST"}


def active_of(player):
    acts = getattr(player, "active", None)
    if isinstance(acts, list) and acts:
        return acts[0]
    return None


def pname(pokemon):
    return NAMES.get(getattr(pokemon, "id", None), "?")


def main() -> int:
    hero = ExternalSubmissionAgent(str(ROOT / "artifacts" / "dragapult_eval"), {})
    opp_agent = ExternalSubmissionAgent(str(ROOT / "artifacts" / "dragapult_opponents"), {})
    deck_a = [int(x) for x in (ROOT / "artifacts" / "dragapult_eval" / "deck.csv").read_text().splitlines()]
    deck_b = [int(x) for x in (ROOT / "artifacts" / "dragapult_opponents" / "deck.csv").read_text().splitlines()]
    for game in range(2):
        random.seed(202608161900 + game)
        raw, start = battle_start(deck_a, deck_b)
        print(f"=== game {game} ===")
        step = 0
        while True:
            obs = to_observation_class(raw)
            cur = obs.current
            if cur is None or (getattr(cur, "result", -1) != -1):
                winner = "HERO" if cur is not None and cur.result == 0 else "OPP"
                print(f"  FINAL result={getattr(cur, 'result', '?')} {winner}")
                break
            me = cur.players[cur.yourIndex]
            opp_p = cur.players[1 - cur.yourIndex]
            if cur.yourIndex == 0:
                act = active_of(me)
                sel = obs.select
                ctx = getattr(sel, "context", None)
                options = getattr(sel, "option", None) or []
                if ctx is not None:
                    names = []
                    chosen = hero(raw)
                    for idx in chosen[:4]:
                        if idx < len(options):
                            o = options[idx]
                            names.append(f"{NAMES.get(getattr(o, 'source_card', 0), '?')}->{NAMES.get(getattr(o, 'target_card', 0), '?')}")
                    turn = getattr(cur, "turn", -1)
                    opp_prizes = len(getattr(opp_p, "prize", []) or [])
                    print(f"  t{turn} st{step} {CTX.get(ctx, ctx)} active={pname(act)} "
                          f"prize={len(getattr(me, 'prize', []) or [])} "
                          f"opp_act={pname(active_of(opp_p))} opp_prize={opp_prizes} "
                          f"sel={names}")
                    raw = battle_select(chosen)
                else:
                    raw = battle_select(hero(raw))
            else:
                raw = battle_select(opp_agent(raw))
            step += 1
            if step > 500:
                print("  CAP")
                break
        battle_finish()
        hero.close()
        opp.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
