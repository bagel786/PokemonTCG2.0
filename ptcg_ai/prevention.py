"""Does this attack do nothing to the defender?

Answers the question `CalcDamage` answers in C++ (SetProperty.h:388-455) but which
the engine never surfaces to Python: attack options carry only an `attackId`
(ApiJson.h:117), so a blanked attack looks identical to a lethal one.

Damage and damage counters are blocked by *opposite* families. Real damage runs
through CalcDamage and the `noDamage*` flags; counters skip CalcDamage entirely
(EffectInstant.h:802-818) and are instead stopped by `noEffect*` and
`noDamageCounter*`. Both directions matter -- Grimmsnarl ex is blanked by Crustle
while Froslass, being non-ex, is not.

Card data is from `ptcg_ai/prevention.json`; regenerate with
`scripts/gen_prevention_table.py` after an engine sync.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .view import attack_table, card_table

_TABLE_PATH = Path(__file__).with_name("prevention.json")
# "This attack's damage isn't affected by any effects on your opponent's Active
# Pokemon" -- .noTargetEffect() skips the whole defender block (SetProperty.h:309).
_BYPASS_TEXT = "isn’t affected by any effects"


@lru_cache(maxsize=1)
def prevention_table() -> dict[int, dict]:
    return {int(k): v for k, v in json.loads(_TABLE_PATH.read_text()).items()}


def places_counters(attack) -> bool:
    """True for attacks that place damage counters instead of dealing damage."""
    return not (attack.damage or 0) and "damage counter" in (attack.text or "").lower()


def _is_rule_box(card) -> bool:
    return bool(card.ex or card.megaEx or card.tera)


def _entry_protects(entry: dict, defender_card) -> bool:
    """Does this prevention entry actually cover the defender?"""
    if entry.get("not_rule_only") and _is_rule_box(defender_card):
        return False
    if entry.get("basic_only") and not defender_card.basic:
        return False
    if entry.get("condition") == "TeamRocket" and "Team Rocket" not in (defender_card.name or ""):
        return False
    if entry.get("energy_type"):
        # Attached-energy grants are already filtered by the caller collecting
        # them off this Pokemon; the type gate applies to the holder.
        return True
    return True


def _flag_applies(entry: dict, attacker_card, attack, counters: bool, defender_benched: bool) -> bool:
    flag = entry["flag"]
    if flag == "NoEffectEnemyAttack":
        return counters
    if flag == "NoDamageCounterEnemyAttackAbility":
        return counters and defender_benched
    if counters:
        return False  # remaining flags are all damage-only
    if flag == "NoDamageEnemyAttack":
        return True
    if flag == "NoDamageEnemyExAttack":
        return bool(attacker_card.ex or attacker_card.megaEx)
    if flag == "NoDamageEnemyBasicExAttack":
        return bool((attacker_card.ex or attacker_card.megaEx) and attacker_card.basic)
    if flag == "NoDamageEnemyAbilityPokemonAttack":
        return bool(attacker_card.skills)
    if flag == "NoDamageGreaterEqual":
        return (attack.damage or 0) >= entry.get("value", 0)
    return False


def _entries_protecting(obs, defender_pokemon, defender_player, defender_benched):
    """Yield every persistent prevention entry covering this defender."""
    table = prevention_table()
    state = obs.current

    entry = table.get(defender_pokemon.id)
    if entry and entry["scope"] == "self":
        yield entry
    for energy in defender_pokemon.energyCards or []:
        entry = table.get(energy.id)
        if entry and entry["scope"] == "attached":
            yield entry
    for card in state.stadium or []:
        entry = table.get(card.id)
        if entry and entry["scope"] in {"in_play", "bench"}:
            if entry["scope"] == "bench" and not defender_benched:
                continue
            yield entry
    # Board-wide grants from the defender's own side, e.g. TR Articuno's
    # Repelling Veil protecting every Basic Team Rocket mon (CardImpl.h:5060).
    for ally in (defender_player.active or []) + (defender_player.bench or []):
        if ally is None:
            continue
        entry = table.get(ally.id)
        if not entry or not entry.get("owner_only"):
            continue
        if entry["scope"] == "in_play":
            yield entry
        elif entry["scope"] == "bench" and defender_benched:
            yield entry


def attack_damage_nullified(
    obs, attack_id: int, defender, defender_player, defender_benched: bool
) -> bool:
    """True when an attack's damage is publicly known to miss ``defender``."""
    attack = attack_table().get(int(attack_id or 0))
    if attack is None or not (attack.damage or 0):
        return False
    if _BYPASS_TEXT in (attack.text or ""):
        return False

    state = obs.current
    me = state.players[state.yourIndex]
    attacker = (me.active or [None])[0]
    if attacker is None or defender is None:
        return False
    attacker_card = card_table().get(attacker.id)
    defender_card = card_table().get(defender.id)
    if attacker_card is None or defender_card is None:
        return False

    # Tera's rule-box text prevents attack damage while it is on the Bench.
    if defender_benched and bool(defender_card.tera):
        return True
    return any(
        _entry_protects(entry, defender_card)
        and _flag_applies(entry, attacker_card, attack, counters=False,
                          defender_benched=defender_benched)
        for entry in _entries_protecting(
            obs, defender, defender_player, defender_benched=defender_benched
        )
    )


def ability_damage_counter_nullified(
    obs, defender, defender_player, defender_benched: bool
) -> bool:
    """True when public board effects stop ability-placed damage counters."""
    if defender is None:
        return False
    defender_card = card_table().get(defender.id)
    if defender_card is None:
        return False
    # Adrena-Brain is an Ability, so only the counter-prevention flags apply.
    return any(
        _entry_protects(entry, defender_card)
        and entry["flag"] == "NoDamageCounterEnemyAttackAbility"
        and defender_benched
        for entry in _entries_protecting(
            obs, defender, defender_player, defender_benched=defender_benched
        )
    )


def attack_nullified(obs, option) -> bool:
    """True when this attack option provably does nothing to the opposing active."""
    attack = attack_table().get(int(option.attackId or 0))
    if attack is None:
        return False
    if _BYPASS_TEXT in (attack.text or ""):
        return False

    state = obs.current
    me = state.players[state.yourIndex]
    opponent = state.players[1 - state.yourIndex]
    attacker = (me.active or [None])[0]
    defender = (opponent.active or [None])[0]
    if attacker is None or defender is None:
        return False

    attacker_card = card_table().get(attacker.id)
    defender_card = card_table().get(defender.id)
    if attacker_card is None or defender_card is None:
        return False

    counters = places_counters(attack)
    if not counters and not (attack.damage or 0):
        return False  # pure status/utility attack; nothing to blank

    if not counters:
        return attack_damage_nullified(
            obs, int(option.attackId or 0), defender, opponent, defender_benched=False
        )
    return any(
        _entry_protects(entry, defender_card)
        and _flag_applies(entry, attacker_card, attack, counters=True, defender_benched=False)
        for entry in _entries_protecting(obs, defender, opponent, defender_benched=False)
    )
