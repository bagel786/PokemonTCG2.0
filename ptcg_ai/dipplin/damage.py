"""Exact public-state damage projection for Dipplin's Do the Wave.

The native attack table records attack 115 with zero printed damage because its
damage is calculated from the current Bench.  Generic prevention helpers that
gate on printed damage consequently cannot answer whether the attack is useful.
This module deliberately starts from the live Bench count and mirrors the
engine's relevant ordering: attacker modifiers, Weakness, Resistance, then
defender prevention.

Inputs may be native ``cg.api`` objects, planner dataclasses, dictionaries, or
simple test doubles.  Unknown fields are treated conservatively rather than
making the projection fail open.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import ceil
from typing import Any, Iterable

DO_THE_WAVE_ATTACK_ID = 115
DIPPLIN_CARD_ID = 93
BRAVE_BANGLE_CARD_ID = 1175
BLACK_BELT_CARD_ID = 1211
JAMMING_TOWER_CARD_ID = 1246
NEUTRALIZATION_ZONE_CARD_ID = 1247
CORNERSTONE_MASK_OGERPON_EX_CARD_ID = 117

_GRASS = 1
_MISSING = object()


@dataclass(frozen=True)
class DamageProjection:
    """A one-attack projection plus the same-target Festival ceiling.

    ``base`` is the Bench-derived damage, ``raw`` includes Bangle and Black
    Belt, and ``final`` is post-Weakness/Resistance and prevention.  ``ko`` is
    a first-attack KO; ``turn_ko`` additionally permits the second Festival
    attack against the same target.  Promotion must be projected separately.
    """

    attack_id: int
    base: int
    raw: int
    final: int
    bangle_bonus: int
    black_belt_bonus: int
    weakness_applied: bool
    resistance_applied: bool
    nullified: bool
    productive: bool
    ko: bool
    turn_ko: bool
    attacks_to_ko: int | None
    prize_value: int
    prizes_this_attack: int
    attacks_available: int
    reason: str

    @property
    def base_damage(self) -> int:
        return self.base

    @property
    def raw_damage(self) -> int:
        return self.raw

    @property
    def final_damage(self) -> int:
        return self.final

    @property
    def projected_damage(self) -> int:
        return self.final

    @property
    def damage(self) -> int:
        return self.final

    @property
    def projected_turn_damage(self) -> int:
        """Upper bound against one unchanged Active, not across promotion."""

        return self.final * self.attacks_available


def _field(value: Any, *names: str, default: Any = _MISSING) -> Any:
    if value is None:
        return default
    for name in names:
        if isinstance(value, dict) and name in value:
            return value[name]
        if hasattr(value, name):
            return getattr(value, name)
    return default


def _card_id(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    found = _field(value, "id", "card_id", "cardId", default=None)
    try:
        return int(found) if found is not None else None
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=1)
def _card_table() -> dict[int, Any]:
    """Load native metadata lazily; explicit snapshot fields still take priority."""

    try:
        from cg.api import all_card_data

        return {int(card.cardId): card for card in all_card_data()}
    except Exception:
        # Damage projection is also imported by sterile/package tests where the
        # native library may intentionally be unavailable.
        return {}


def _metadata(value: Any) -> Any | None:
    card_id = _card_id(value)
    return _card_table().get(card_id) if card_id is not None else None


def _fact(value: Any, *names: str, default: Any = None) -> Any:
    explicit = _field(value, *names, default=_MISSING)
    if explicit is not _MISSING:
        return explicit
    return _field(_metadata(value), *names, default=default)


def _truth(value: Any, *names: str, default: bool = False) -> bool:
    found = _fact(value, *names, default=default)
    return bool(found)


def _is_ex(value: Any) -> bool:
    explicit_values = [
        _field(value, name, default=_MISSING)
        for name in ("is_ex", "ex", "mega_ex", "megaEx")
    ]
    known_values = [item for item in explicit_values if item is not _MISSING and item is not None]
    if known_values:
        return any(bool(item) for item in known_values)
    meta = _metadata(value)
    if meta is not None:
        return bool(getattr(meta, "ex", False) or getattr(meta, "megaEx", False))
    # The competition card pool currently uses rule boxes for Pokemon ex.  This
    # alias keeps hand-built public snapshots useful without overriding native
    # metadata when it is available.
    return bool(_field(value, "rule_box", "has_rule_box", default=False))


def _is_rule_box(value: Any) -> bool:
    explicit = _field(value, "rule_box", "has_rule_box", default=_MISSING)
    if explicit is not _MISSING:
        return bool(explicit)
    meta = _metadata(value)
    if meta is not None:
        return bool(
            getattr(meta, "ex", False)
            or getattr(meta, "megaEx", False)
            or getattr(meta, "tera", False)
        )
    return _is_ex(value)


def _is_basic(value: Any) -> bool:
    return _truth(value, "basic", "is_basic", default=False)


def _has_active_ability(value: Any) -> bool:
    active = _field(value, "ability_active", "abilities_active", default=_MISSING)
    if active is not _MISSING and not bool(active):
        return False
    suppressed = _field(
        value,
        "ability_suppressed",
        "abilities_suppressed",
        default=False,
    )
    if suppressed:
        return False
    explicit = _field(value, "has_ability", default=_MISSING)
    if explicit is not _MISSING and explicit is not None:
        return bool(explicit)
    if _card_id(value) in {DIPPLIN_CARD_ID, CORNERSTONE_MASK_OGERPON_EX_CARD_ID}:
        return True
    skills = _fact(value, "skills", default=None)
    return bool(skills)


def _iter_cards(value: Any) -> Iterable[Any]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple, set, frozenset)):
        return value
    return (value,)


def _has_attached_card(pokemon: Any, card_id: int) -> bool:
    tools = _field(pokemon, "tools", "tool_cards", "toolCards", "tool_ids", default=())
    return any(_card_id(tool) == card_id for tool in _iter_cards(tools))


def _stadium_card_id(stadium: Any) -> int | None:
    for card in _iter_cards(stadium):
        found = _card_id(card)
        if found is not None:
            return found
    return None


_ENERGY_NAMES = {
    "colorless": 0,
    "grass": 1,
    "fire": 2,
    "water": 3,
    "lightning": 4,
    "psychic": 5,
    "fighting": 6,
    "darkness": 7,
    "dark": 7,
    "metal": 8,
    "dragon": 9,
    "rainbow": 10,
    "all": 10,
    "team_rocket": 11,
    "team rocket": 11,
}


def _energy_matches(value: Any, attack_type: Any) -> bool:
    if value is None or attack_type is None:
        return False
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_energy_matches(item, attack_type) for item in value)
    if isinstance(attack_type, (list, tuple, set, frozenset)):
        return any(_energy_matches(value, item) for item in attack_type)

    def normalize(item: Any) -> Any:
        if hasattr(item, "name"):
            name = str(getattr(item, "name")).lower()
            if name in _ENERGY_NAMES:
                return _ENERGY_NAMES[name]
        if isinstance(item, str):
            return _ENERGY_NAMES.get(item.strip().lower(), item.strip().lower())
        try:
            return int(item)
        except (TypeError, ValueError):
            return item

    defended = normalize(value)
    attacking = normalize(attack_type)
    if defended == 10:  # Rainbow / all types.
        return attacking != 0
    if defended == 11:  # Team Rocket energy type is Psychic and Darkness.
        return attacking in {5, 7}
    return defended == attacking


def _prevention_fact(defender: Any, *names: str, default: Any = False) -> Any:
    direct = _field(defender, *names, default=_MISSING)
    if direct is not _MISSING:
        return direct
    prevention = _field(defender, "prevention", "effects", default=None)
    if isinstance(prevention, dict):
        return _field(prevention, *names, default=default)
    if isinstance(prevention, (set, frozenset, list, tuple)):
        return any(name in prevention for name in names)
    return default


def _prevention_reason(attacker: Any, defender: Any, damage: int, stadium_id: int | None) -> str | None:
    """Return the public, damage-family prevention that blanks this hit."""

    attacker_ex = _is_ex(attacker)
    attacker_ability = _has_active_ability(attacker)
    defender_id = _card_id(defender)

    if _prevention_fact(defender, "no_damage_enemy_attack", "noDamageEnemyAttack"):
        return "no_damage_enemy_attack"

    explicit_ability_shield = bool(
        _prevention_fact(
            defender,
            "no_damage_enemy_ability_pokemon_attack",
            "noDamageEnemyAbilityPokemonAttack",
        )
    )
    ability_shield = explicit_ability_shield or (
        defender_id == CORNERSTONE_MASK_OGERPON_EX_CARD_ID
        and _has_active_ability(defender)
    )
    if ability_shield and attacker_ability:
        return "cornerstone_stance" if defender_id == CORNERSTONE_MASK_OGERPON_EX_CARD_ID else "ability_attack_immunity"

    # Crustle (345), Mimikyu-style shields (330), and Neutralization Zone are
    # intentionally checked against the attacker.  Dipplin is non-ex, so none
    # of them stop Do the Wave.
    ex_shield = (
        defender_id in {330, 345} and _has_active_ability(defender)
    ) or bool(
        _prevention_fact(defender, "no_damage_enemy_ex_attack", "noDamageEnemyExAttack")
    )
    if ex_shield and attacker_ex:
        return "ex_attack_immunity"

    basic_ex_shield = (
        defender_id == 83 and _has_active_ability(defender)
    ) or bool(
        _prevention_fact(
            defender,
            "no_damage_enemy_basic_ex_attack",
            "noDamageEnemyBasicExAttack",
        )
    )
    if basic_ex_shield and attacker_ex and _is_basic(attacker):
        return "basic_ex_attack_immunity"

    if (
        stadium_id == NEUTRALIZATION_ZONE_CARD_ID
        and not _is_rule_box(defender)
        and attacker_ex
    ):
        return "neutralization_zone"

    threshold = _prevention_fact(
        defender,
        "no_damage_greater_equal",
        "noDamageGreaterEqual",
        default=0,
    )
    if not threshold and defender_id == 158 and _has_active_ability(defender):
        threshold = 200
    try:
        threshold = int(threshold or 0)
    except (TypeError, ValueError):
        threshold = 0
    if threshold > 0 and damage >= threshold:
        return "damage_threshold_immunity"

    return None


def _prize_value(defender: Any) -> int:
    explicit = _field(defender, "prize_value", "prizes", default=_MISSING)
    if explicit is not _MISSING:
        try:
            return max(0, int(explicit))
        except (TypeError, ValueError):
            pass
    mega = _truth(defender, "mega_ex", "megaEx", default=False)
    if mega:
        return 3
    return 2 if _is_ex(defender) else 1


def _remaining_hp(defender: Any) -> int:
    found = _field(defender, "hp", "remaining_hp", "remainingHp", default=_MISSING)
    if found is _MISSING:
        found = _field(defender, "max_hp", "maxHp", default=0)
    try:
        return max(0, int(found))
    except (TypeError, ValueError):
        return 0


def project_do_the_wave(
    attacker: Any,
    defender: Any,
    *,
    bench_count: int,
    black_belt_used: bool = False,
    stadium_id: Any = None,
    festival_active: bool = True,
) -> DamageProjection:
    """Project attack 115 from current public state.

    This function never consults the attack's printed ``damage`` field.  It is
    therefore safe for Do the Wave's metadata value of zero and recalculates
    after every Bench change or promotion.
    """

    try:
        benches = max(0, int(bench_count))
    except (TypeError, ValueError):
        benches = 0
    base = 20 * benches
    active_stadium = _stadium_card_id(stadium_id)
    defender_ex = _is_ex(defender)
    attacker_rule_box = _is_rule_box(attacker)

    bangle_bonus = 0
    if (
        defender_ex
        and not attacker_rule_box
        and active_stadium != JAMMING_TOWER_CARD_ID
        and _has_attached_card(attacker, BRAVE_BANGLE_CARD_ID)
    ):
        bangle_bonus = 30
    black_belt_bonus = 40 if black_belt_used and defender_ex else 0
    raw = base + bangle_bonus + black_belt_bonus

    attack_type = _fact(attacker, "energy_type", "energyType", default=_GRASS)
    weakness = _fact(defender, "weakness", default=None)
    resistance = _fact(defender, "resistance", default=None)
    weakness_applied = raw > 0 and _energy_matches(weakness, attack_type)
    resistance_applied = raw > 0 and _energy_matches(resistance, attack_type)

    adjusted = raw * 2 if weakness_applied else raw
    if resistance_applied:
        adjusted = max(0, adjusted - 30)

    prevention = _prevention_reason(attacker, defender, adjusted, active_stadium)
    final = 0 if prevention is not None else adjusted
    hp = _remaining_hp(defender)
    attacks_available = 2 if festival_active else 1
    productive = final > 0 and hp > 0
    ko = productive and final >= hp
    turn_ko = productive and final * attacks_available >= hp
    attacks_to_ko = ceil(hp / final) if productive else None
    prizes = _prize_value(defender)

    if prevention is not None:
        reason = prevention
    elif hp <= 0:
        reason = "no_live_defender"
    elif final <= 0:
        reason = "no_bench_damage" if base <= 0 else "nonpositive_damage"
    elif ko:
        reason = "knockout"
    elif turn_ko and festival_active:
        reason = "two_attack_knockout"
    else:
        reason = "productive_damage"

    return DamageProjection(
        attack_id=DO_THE_WAVE_ATTACK_ID,
        base=base,
        raw=raw,
        final=final,
        bangle_bonus=bangle_bonus,
        black_belt_bonus=black_belt_bonus,
        weakness_applied=weakness_applied,
        resistance_applied=resistance_applied,
        nullified=prevention is not None,
        productive=productive,
        ko=ko,
        turn_ko=turn_ko,
        attacks_to_ko=attacks_to_ko,
        prize_value=prizes,
        prizes_this_attack=prizes if ko else 0,
        attacks_available=attacks_available,
        reason=reason,
    )


def is_do_the_wave_productive(
    attacker: Any,
    defender: Any,
    *,
    bench_count: int,
    black_belt_used: bool = False,
    stadium_id: Any = None,
    festival_active: bool = True,
) -> bool:
    """Convenience predicate sharing the exact projection path."""

    return project_do_the_wave(
        attacker,
        defender,
        bench_count=bench_count,
        black_belt_used=black_belt_used,
        stadium_id=stadium_id,
        festival_active=festival_active,
    ).productive
