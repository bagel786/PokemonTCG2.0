"""Modular Blunder Detector for Reinforcement Learning Policy Penalty Isolation (Invariant 1.6).

Detects tactically suboptimal choices during self-play rollouts so they can be
regularized via policy loss penalties L_penalty rather than polluting state-value
baseline targets V(s).
"""

from __future__ import annotations

from cg.api import AreaType, OptionType
from ptcg_ai.prevention import attack_nullified
from ptcg_ai.view import card_table, option_source_card, option_target_pokemon


def is_nullified_attack_action(obs, selected_option) -> bool:
    """True if selected action declares an attack that is fully nullified by defender abilities/effects."""
    if not selected_option:
        return False
    opt_type = getattr(selected_option, "type", None)
    if opt_type not in (OptionType.ATTACK, 13):
        return False
    return bool(attack_nullified(obs, selected_option))


def is_futile_retreat_action(obs, selected_option) -> bool:
    """True if selected action pays energy to retreat to an active that has 0 attacks available and lower survival."""
    if not selected_option:
        return False
    opt_type = getattr(selected_option, "type", None)
    if opt_type not in (OptionType.RETREAT, 12):
        return False
    
    # Check if active is already healthy and new target has 0 energy
    target = option_target_pokemon(obs, selected_option)
    if target is not None:
        energy_count = len(getattr(target, "energy", []) or [])
        hp = getattr(target, "hp", 0) or 0
        damage = getattr(target, "damage", 0) or 0
        remaining_hp = hp - damage
        if energy_count == 0 and remaining_hp <= 60:
            return True
    return False


def is_blunder(obs, selected_option) -> bool:
    """Unified predicate returning True if the taken option is a recognized tactical blunder."""
    if not selected_option:
        return False
    if is_nullified_attack_action(obs, selected_option):
        return True
    if is_futile_retreat_action(obs, selected_option):
        return True
    return False
