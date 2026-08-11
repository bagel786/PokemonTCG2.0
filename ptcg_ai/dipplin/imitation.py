"""Compact public-state behavior ranker for rank-34 Dipplin sequencing.

The model scores only already-legal MAIN options.  Parent-aware search, setup,
promotion, prize, and Festival prompts remain under the explicit resolvers.
Weights are trained from public PP Kawada replay observations and stored as a
plain JSON mapping beside this module; no opponent identity enters the feature
space.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from cg.api import OptionType

from .plan import MacroPlan
from .resolvers import option_card_id, option_source, option_target


def _int(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bucket(value: int, cuts: tuple[int, ...]) -> int:
    return sum(value >= cut for cut in cuts)


def _card_id(card: Any) -> int:
    return _int(getattr(card, "id", None))


def _hero_opponent(obs: Any) -> tuple[Any, Any]:
    state = obs.current
    hero_index = _int(state.yourIndex, 0)
    return state.players[hero_index], state.players[1 - hero_index]


def option_features(obs: Any, plan: MacroPlan, index: int) -> tuple[str, ...]:
    """Return deterministic sparse option/state-cross feature names."""

    hero, opponent = _hero_opponent(obs)
    option = obs.select.option[index]
    option_type = _int(getattr(option, "type", None))
    card_id = option_card_id(obs, index)
    attack_id = _int(getattr(option, "attackId", None))
    source = option_source(obs, option)
    target = option_target(obs, option)
    active = next((card for card in (hero.active or []) if card is not None), None)
    opponent_active = next((card for card in (opponent.active or []) if card is not None), None)
    action = f"o{option_type}:c{card_id}:a{attack_id}"
    target_token = f"t{_card_id(target)}:e{_bucket(len(getattr(target, 'energies', None) or []), (1, 2))}"
    states = [
        f"turn={min(6, plan.own_turn_ordinal)}",
        f"order={plan.actual_order}",
        f"phase={plan.phase.value}",
        f"active={_card_id(active)}",
        f"active_e={_bucket(len(getattr(active, 'energies', None) or []), (1, 2))}",
        f"bench={len(hero.bench or [])}",
        f"hand={_bucket(_int(getattr(hero, 'handCount', None), len(hero.hand or [])), (2, 4, 6, 8))}",
        f"prizes={len(hero.prize or [])}",
        f"opp_prizes={len(opponent.prize or [])}",
        f"opp_active_hp={_bucket(_int(getattr(opponent_active, 'hp', None), 0), (60, 120, 200, 300))}",
        f"festival={int(plan.festival_active)}",
        f"replacement={int(plan.replacement_attacker_ready)}",
        f"energy_attached={int(bool(getattr(obs.current, 'energyAttached', False)))}",
        f"supporter={int(bool(getattr(obs.current, 'supporterPlayed', False)))}",
        f"retreated={int(bool(getattr(obs.current, 'retreated', False)))}",
    ]
    for missing in plan.missing_prerequisites:
        states.append(f"missing={missing}")
    board_counts: dict[int, int] = {}
    for card in list(hero.active or []) + list(hero.bench or []):
        if card is not None:
            board_counts[_card_id(card)] = board_counts.get(_card_id(card), 0) + 1
    for value, count in sorted(board_counts.items()):
        states.append(f"board={value}:{min(3, count)}")
    hand_counts: dict[int, int] = {}
    for card in hero.hand or []:
        hand_counts[_card_id(card)] = hand_counts.get(_card_id(card), 0) + 1
    for value, count in sorted(hand_counts.items()):
        states.append(f"held={value}:{min(3, count)}")
    features = [f"bias|{action}", f"target|{action}|{target_token}"]
    features.extend(f"{state}|{action}" for state in states)
    # Attachment/evolution choices need target-state crosses even when the card
    # action itself is identical across several board lines.
    if option_type in {int(OptionType.ATTACH), int(OptionType.EVOLVE), int(OptionType.RETREAT)}:
        features.extend(f"{state}|{action}|{target_token}" for state in states[:8])
    if source is not None:
        features.append(f"source_area|{action}|s{_card_id(source)}")
    return tuple(features)


@lru_cache(maxsize=1)
def load_weights() -> dict[str, float]:
    path = Path(__file__).with_name("imitation_weights.json")
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {str(key): float(value) for key, value in payload.get("weights", {}).items()}


def rank_main_options(obs: Any, plan: MacroPlan) -> tuple[list[int], float]:
    """Return legal indices by learned score and the top-two margin."""

    weights = load_weights()
    if not weights:
        return [], 0.0
    scored = [
        (sum(weights.get(feature, 0.0) for feature in option_features(obs, plan, index)), -index, index)
        for index in range(len(obs.select.option))
    ]
    scored.sort(reverse=True)
    margin = scored[0][0] - scored[1][0] if len(scored) > 1 else float("inf")
    return [item[2] for item in scored], margin


__all__ = ["option_features", "rank_main_options"]
