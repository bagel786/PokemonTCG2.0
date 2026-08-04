#!/usr/bin/env python3
"""Derive the damage/effect-prevention card table from the engine source.

The engine's `noDamage*` / `noEffect*` flags are ground truth (Card.h:219-313,
enforced in SetProperty.h:388-455 and State.h:1392-1458). Regenerate after
`scripts/sync_engine.py` pulls a new card set.

Only *persistent* prevention is emitted -- abilities, stadiums and attached
energy, which are readable from card identity. The `*NextEnemyTurn` family is
turn state, not card identity, and is deliberately excluded.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARD_IMPL = ROOT / "freshstart" / "engine" / "ptcgProgram" / "CardImpl.h"

FLAGS = (
    "NoDamageEnemyExAttack",
    "NoDamageEnemyBasicExAttack",
    "NoDamageEnemyAbilityPokemonAttack",
    "NoDamageEnemyAttack",
    "NoDamageGreaterEqual",
    "NoEffectEnemyAttack",
    "NoDamageCounterEnemyAttackAbility",
)
CREATE_CARD = re.compile(r"CreateCard\((\d+),")
EFFECT = re.compile(r"\.(effectMe|effectEnergyContinual|effect)\(\s*(" + "|".join(FLAGS) + r")\b")
E_VAL = re.compile(r"\.eVal\((\d+)\)")


def scope_of(kind: str, line: str) -> str:
    """Who the prevention protects."""
    if kind == "effectEnergyContinual":
        return "attached"  # protects the Pokemon this energy is attached to
    if kind == "effectMe":
        return "self"
    if ".targetBench()" in line:
        return "bench"
    return "in_play"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="ptcg_ai/prevention.json")
    args = parser.parse_args()

    lines = CARD_IMPL.read_text(encoding="utf-8").splitlines()
    table: dict[str, dict] = {}
    card_id = None
    for line in lines:
        found = CREATE_CARD.search(line)
        if found:
            card_id = int(found.group(1))
            continue
        match = EFFECT.search(line)
        if not match or card_id is None:
            continue
        kind, flag = match.group(1), match.group(2)
        entry = {
            "flag": flag,
            "scope": scope_of(kind, line),
            "owner_only": kind != "effect" or ", Me)" in line,
        }
        if ".targetNotRulePokemon()" in line:
            entry["not_rule_only"] = True
        if ".targetBasicPokemon()" in line:
            entry["basic_only"] = True
        condition = re.search(r"targetCondition\(TargetType::(\w+)\)", line)
        if condition:
            entry["condition"] = condition.group(1)
        energy = re.search(r"targetEnergyType\((\w+)\)", line)
        if energy:
            entry["energy_type"] = energy.group(1)
        value = E_VAL.search(line)
        if value:
            entry["value"] = int(value.group(1))
        table[str(card_id)] = entry

    out = ROOT / args.output
    out.write_text(json.dumps(table, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"cards": len(table), "output": str(out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
