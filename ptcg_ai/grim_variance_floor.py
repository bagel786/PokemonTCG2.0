"""Very narrow insurance rules layered on the frozen Grimmsnarl ranking.

The wrapped ``GrimGuardrailDirector`` remains the policy owner.  This module
only reorders the current legal options for two mechanically provable cases:
useful Punk Up fuel and escaping a dead support Pokemon into a ready Grimmsnarl.
It deliberately does not use opponent identity, search, or raw option indices
as state.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping, Sequence

from cg.api import AreaType, EnergyType, OptionType, SelectContext, SelectType

from .card_ids import (
    DARK_ENERGY,
    FROSLASS_VARIANTS,
    MARNIES_GRIMMSNARL_EX,
    MARNIES_IMPIDIMP,
    MARNIES_MORGREM,
    MUNKIDORI,
    SNORUNT,
)
from .grim_guardrails import GrimGuardrailDirector
from .prevention import attack_nullified
from .view import attack_table, card_table, option_source_card, option_target_pokemon


USEFUL_CAPACITY = {
    MARNIES_IMPIDIMP: 1,
    MARNIES_MORGREM: 2,
    MARNIES_GRIMMSNARL_EX: 2,
}
DEAD_SUPPORT_IDS = frozenset({MUNKIDORI, SNORUNT, *FROSLASS_VARIANTS})
PUNK_UP_REASONS = frozenset(
    {
        "variance_floor:punk_up_activate",
        "variance_floor:punk_up_count",
        "variance_floor:punk_up_target",
    }
)


@dataclass(frozen=True)
class GrimVarianceConfig:
    """Independent ablation switches for the variance-floor candidate family."""

    punk_up_floor: bool = False
    dead_active_escape: bool = False
    # Deliberately unavailable until the B3 mechanism audit justifies it.
    early_poffin_floor: bool = False

    def __post_init__(self) -> None:
        if self.early_poffin_floor:
            raise ValueError("early Poffin floor is disabled pending the B3 audit")


def _integer(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _context_is(select: Any, expected: SelectContext) -> bool:
    value = getattr(select, "context", None)
    return _integer(value) == int(expected) or str(value).replace("_", "").lower().endswith(
        expected.name.replace("_", "").lower()
    )


def _select_type_is(select: Any, expected: SelectType) -> bool:
    value = getattr(select, "type", None)
    return _integer(value) == int(expected) or str(value).replace("_", "").lower().endswith(
        expected.name.replace("_", "").lower()
    )


def _ranked_with(ranked: Sequence[int], preferred: Iterable[int]) -> list[int]:
    prefix: list[int] = []
    for index in preferred:
        if index in ranked and index not in prefix:
            prefix.append(index)
    return prefix + [index for index in ranked if index not in prefix]


def _cards(player: Any, zone: str) -> list[Any]:
    return [card for card in (getattr(player, zone, None) or []) if card is not None]


def _board(player: Any) -> list[Any]:
    return _cards(player, "active") + _cards(player, "bench")


def _energy_count(pokemon: Any) -> int:
    energies = getattr(pokemon, "energies", None)
    if energies is not None:
        return len(energies)
    return len(getattr(pokemon, "energyCards", None) or [])


def _energy_matches(energy: int, required: int) -> bool:
    return (
        required == int(EnergyType.COLORLESS)
        or energy == required
        or energy == int(EnergyType.RAINBOW)
        or (energy == int(EnergyType.TEAM_ROCKET) and required in {
            int(EnergyType.PSYCHIC),
            int(EnergyType.DARKNESS),
        })
    )


def _attack_deficit(energies: Sequence[int], requirements: Sequence[int]) -> int:
    remaining = [int(value) for value in energies]
    typed = [int(value) for value in requirements if int(value) != int(EnergyType.COLORLESS)]
    colorless = sum(int(value) == int(EnergyType.COLORLESS) for value in requirements)
    missing = 0
    for required in typed:
        match = next((i for i, energy in enumerate(remaining) if _energy_matches(energy, required)), None)
        if match is None:
            missing += 1
        else:
            remaining.pop(match)
    return missing + max(0, colorless - len(remaining))


def _minimum_attack_deficit(pokemon: Any) -> int:
    metadata = card_table().get(_integer(getattr(pokemon, "id", 0), 0))
    if metadata is None or not metadata.attacks:
        return 99
    energies = [int(value) for value in (getattr(pokemon, "energies", None) or [])]
    deficits = []
    for attack_id in metadata.attacks:
        attack = attack_table().get(attack_id)
        if attack is not None:
            deficits.append(_attack_deficit(energies, attack.energies))
    return min(deficits) if deficits else 99


def _effect_id(obs: Any) -> int:
    select = getattr(obs, "select", None)
    effect = getattr(select, "effect", None)
    context_card = getattr(select, "contextCard", None)
    return _integer(getattr(effect or context_card, "id", 0), 0)


def _target(obs: Any, index: int) -> Any:
    option = obs.select.option[index]
    return option_target_pokemon(obs, option) or option_source_card(obs, option)


def _option_active(option: Any) -> bool:
    return getattr(option, "inPlayArea", None) == AreaType.ACTIVE or (
        getattr(option, "inPlayArea", None) is None
        and getattr(option, "area", None) == AreaType.ACTIVE
    )


def _option_slot(option: Any) -> int:
    value = getattr(option, "inPlayIndex", None)
    if value is None:
        value = getattr(option, "index", None)
    return _integer(value, 0)


def _valid_ranked(obs: Any, ranked: Sequence[int]) -> bool:
    options = getattr(getattr(obs, "select", None), "option", None)
    try:
        return bool(options) and len(set(ranked)) == len(ranked) and all(
            isinstance(index, int) and 0 <= index < len(options) for index in ranked
        )
    except (TypeError, ValueError):
        return False


def _useful_capacity(player: Any) -> int:
    return sum(
        max(0, USEFUL_CAPACITY[_integer(card.id)] - _energy_count(card))
        for card in _board(player)
        if _integer(getattr(card, "id", 0)) in USEFUL_CAPACITY
    )


def useful_capacity(player: Any) -> int:
    """Return exact attack-readiness fuel capacity for a public board."""

    return _useful_capacity(player)


def _ready_grim_options(obs: Any, ranked: Sequence[int]) -> list[tuple[tuple, int]]:
    choices = []
    for index in ranked:
        target = _target(obs, index)
        if target is None or _integer(getattr(target, "id", 0)) != MARNIES_GRIMMSNARL_EX:
            continue
        if _minimum_attack_deficit(target) != 0:
            continue
        option = obs.select.option[index]
        key = (
            -_integer(getattr(target, "hp", 0), 0),
            -min(_energy_count(target), USEFUL_CAPACITY[MARNIES_GRIMMSNARL_EX]),
            _option_slot(option),
            index,
        )
        choices.append((key, index))
    return choices


def _bench_grim_promotable(obs: Any, target: Any) -> bool:
    state = getattr(obs, "current", None)
    if state is None or bool(getattr(state, "retreated", True)):
        return False
    try:
        active = _cards(state.players[state.yourIndex], "active")
    except (AttributeError, IndexError, TypeError):
        return False
    if not active:
        return True
    metadata = card_table().get(_integer(getattr(active[0], "id", 0), 0))
    retreat_cost = getattr(metadata, "retreatCost", None) if metadata is not None else None
    return retreat_cost is not None and _energy_count(active[0]) >= int(retreat_cost)


class GrimVarianceFloorDirector:
    """Compose narrow variance rules after the existing Grim guardrail."""

    def __init__(
        self,
        config: GrimVarianceConfig | None = None,
        *,
        budgets: Mapping[str, int] | None = None,
    ) -> None:
        self.config = config or GrimVarianceConfig()
        self.base = GrimGuardrailDirector(budgets=budgets)
        self.reset()

    def reset(self) -> None:
        self.escape_stage: str | None = None
        self.escape_root_turn: int | None = None
        self.escape_player: int | None = None
        self.dead_active_serial: int | None = None
        self.intervention_counts: Counter[str] = Counter()
        self.telemetry_counts: Counter[str] = Counter()
        self.last_reason: str | None = None
        self.base.reset()

    def _clear_escape(self) -> None:
        self.escape_stage = None
        self.escape_root_turn = None
        self.escape_player = None
        self.dead_active_serial = None

    def _record(self, reason: str) -> None:
        self.last_reason = reason
        self.intervention_counts[reason] += 1

    def _state_is_current(self, obs: Any) -> bool:
        state = getattr(obs, "current", None)
        if state is None:
            self._clear_escape()
            return False
        turn = _integer(getattr(state, "turn", None), -1)
        player = _integer(getattr(state, "yourIndex", None), -1)
        if self.escape_stage is not None and (
            turn != self.escape_root_turn or player != self.escape_player
        ):
            self._clear_escape()
        return turn >= 0 and player in (0, 1)

    def _dead_active(self, obs: Any) -> Any | None:
        try:
            active = _cards(obs.current.players[obs.current.yourIndex], "active")
        except (AttributeError, IndexError, TypeError):
            return None
        if len(active) != 1 or _integer(getattr(active[0], "id", 0)) not in DEAD_SUPPORT_IDS:
            return None
        return active[0]

    def _has_productive_attack(self, obs: Any) -> bool:
        try:
            for option in obs.select.option:
                if _integer(getattr(option, "type", None)) != int(OptionType.ATTACK):
                    continue
                if not attack_nullified(obs, option):
                    return True
        except (AttributeError, IndexError, TypeError, ValueError):
            return True
        return False

    def _ready_bench_grims(self, obs: Any) -> list[Any]:
        try:
            bench = _cards(obs.current.players[obs.current.yourIndex], "bench")
        except (AttributeError, IndexError, TypeError):
            return []
        return [
            card
            for card in bench
            if _integer(getattr(card, "id", 0)) == MARNIES_GRIMMSNARL_EX
            and _minimum_attack_deficit(card) == 0
        ]

    def _escape_prerequisites(self, obs: Any) -> tuple[Any, list[Any]] | None:
        if not self._state_is_current(obs):
            return None
        select = getattr(obs, "select", None)
        state = getattr(obs, "current", None)
        if (
            select is None
            or state is None
            or not _select_type_is(select, SelectType.MAIN)
            or not _context_is(select, SelectContext.MAIN)
            or _integer(getattr(state, "retreated", None), -1) != 0
        ):
            return None
        active = self._dead_active(obs)
        ready = self._ready_bench_grims(obs)
        if active is None or not ready or self._has_productive_attack(obs):
            return None
        return active, ready

    def _apply_punk_up(self, obs: Any, ranked: list[int], desired: int):
        if not self.config.punk_up_floor or _effect_id(obs) != MARNIES_GRIMMSNARL_EX:
            return None
        select = getattr(obs, "select", None)
        state = getattr(obs, "current", None)
        if select is None or state is None:
            return None
        try:
            me = state.players[state.yourIndex]
            capacity = _useful_capacity(me)
            self.telemetry_counts["punk_up_seen"] += 1
        except (AttributeError, IndexError, TypeError):
            return None

        if _context_is(select, SelectContext.ACTIVATE):
            deck_count = getattr(me, "deckCount", None)
            if deck_count is None:
                return None
            wanted_type = OptionType.YES if capacity > 0 and int(deck_count) > 0 else OptionType.NO
            choices = [
                index
                for index in ranked
                if _integer(getattr(select.option[index], "type", None)) == int(wanted_type)
            ]
            if choices and wanted_type == OptionType.YES:
                self.telemetry_counts["punk_up_forced_yes"] += 1
                self._record("variance_floor:punk_up_activate")
                return _ranked_with(ranked, choices), desired, self.last_reason
            return None

        if _context_is(select, SelectContext.ATTACH_TO):
            if capacity <= 0:
                if int(getattr(select, "maxCount", 0)) > 0:
                    self.telemetry_counts["punk_up_prevented_excess_energy"] += 1
                return None
            maximum = _integer(getattr(select, "maxCount", None), -1)
            minimum = _integer(getattr(select, "minCount", None), -1)
            if minimum < 0 or maximum < minimum:
                return None
            intended = min(maximum, capacity, 5)
            intended = max(minimum, intended)

            number_options = [
                index
                for index in ranked
                if _integer(getattr(select.option[index], "type", None)) == int(OptionType.NUMBER)
                and getattr(select.option[index], "number", None) is not None
            ]
            if number_options:
                choices = [
                    index
                    for index in number_options
                    if _integer(getattr(select.option[index], "number", None), -1) == intended
                ]
                if not choices:
                    return None
                self.telemetry_counts["punk_up_count_changed"] += int(
                    desired != choices[0]
                )
                self._record("variance_floor:punk_up_count")
                return _ranked_with(ranked, choices), max(minimum, min(maximum, 1)), self.last_reason

            if desired == intended:
                return None
            if desired > intended:
                self.telemetry_counts["punk_up_prevented_excess_energy"] += 1
            self.telemetry_counts["punk_up_count_changed"] += 1
            self._record("variance_floor:punk_up_count")
            return ranked, intended, self.last_reason

        if _context_is(select, SelectContext.ATTACH_FROM):
            choices = []
            for index in ranked:
                target = _target(obs, index)
                if target is None:
                    continue
                card_id = _integer(getattr(target, "id", 0))
                energy = _energy_count(target)
                if card_id not in USEFUL_CAPACITY or energy >= USEFUL_CAPACITY[card_id]:
                    continue
                active = _option_active(select.option[index])
                if active and card_id == MARNIES_GRIMMSNARL_EX:
                    tier = 0
                elif not active and card_id == MARNIES_GRIMMSNARL_EX:
                    tier = 1
                elif card_id == MARNIES_MORGREM:
                    tier = 2
                elif card_id == MARNIES_IMPIDIMP and energy == 0:
                    tier = 3
                else:
                    continue
                promotable = 0 if tier == 1 and _bench_grim_promotable(obs, target) else 1
                choices.append((tier, promotable, -energy, _option_slot(select.option[index]), index))
            if choices:
                preferred = min(choices)[-1]
                self.telemetry_counts["punk_up_target_changed"] += int(ranked[0] != preferred)
                self._record("variance_floor:punk_up_target")
                return _ranked_with(ranked, [preferred]), desired, self.last_reason
        return None

    def _attach_escape_option(self, obs: Any, ranked: Sequence[int]) -> int | None:
        for index in ranked:
            option = obs.select.option[index]
            if _integer(getattr(option, "type", None)) != int(OptionType.ATTACH):
                continue
            if not _option_active(option):
                continue
            source = option_source_card(obs, option)
            target = option_target_pokemon(obs, option)
            if (
                source is None
                or target is None
                or _integer(getattr(source, "id", 0)) != DARK_ENERGY
                or _integer(getattr(target, "id", 0)) not in DEAD_SUPPORT_IDS
            ):
                continue
            metadata = card_table().get(_integer(getattr(target, "id", 0)))
            retreat_cost = getattr(metadata, "retreatCost", None) if metadata is not None else None
            if retreat_cost is None or _energy_count(target) + 1 < int(retreat_cost):
                continue
            return index
        return None

    def _apply_escape(self, obs: Any, ranked: list[int], desired: int):
        if not self.config.dead_active_escape or desired != 1:
            return None

        if self.escape_stage == "attached":
            prerequisites = self._escape_prerequisites(obs)
            if prerequisites is None:
                self._clear_escape()
            else:
                active, _ready = prerequisites
                if _integer(getattr(active, "serial", 0), 0) != self.dead_active_serial:
                    self._clear_escape()
                else:
                    retreats = [
                        index
                        for index in ranked
                        if _integer(getattr(obs.select.option[index], "type", None))
                        == int(OptionType.RETREAT)
                    ]
                    if retreats:
                        self._record("variance_floor:complete_escape_retreat")
                        return _ranked_with(ranked, retreats), desired, self.last_reason
                    return None

        if self.escape_stage == "promote":
            if not (
                _context_is(obs.select, SelectContext.TO_ACTIVE)
                or _context_is(obs.select, SelectContext.SWITCH)
            ):
                self._clear_escape()
                return None
            choices = _ready_grim_options(obs, ranked)
            if choices:
                preferred = min(choices)[-1]
                self._record("variance_floor:escape_promote_ready_grim")
                return _ranked_with(ranked, [preferred]), desired, self.last_reason
            self._clear_escape()
            return None

        prerequisites = self._escape_prerequisites(obs)
        if prerequisites is None:
            return None
        _active, ready = prerequisites
        retreat_options = [
            index
            for index in ranked
            if _integer(getattr(obs.select.option[index], "type", None)) == int(OptionType.RETREAT)
        ]
        if retreat_options:
            self._record("variance_floor:dead_support_retreat_to_ready_grim")
            return _ranked_with(ranked, retreat_options), desired, self.last_reason
        if not ready:
            return None
        attach = self._attach_escape_option(obs, ranked)
        if attach is not None:
            self._record("variance_floor:attach_to_escape_dead_support")
            return _ranked_with(ranked, [attach]), desired, self.last_reason
        return None

    def apply(self, obs: Any, ranked: Sequence[int], desired: int):
        original = list(ranked)
        original_desired = int(desired)
        self.last_reason = None
        if not _valid_ranked(obs, original):
            self._clear_escape()
            return original, original_desired, None
        try:
            base_ranked, base_desired, base_reason = self.base.apply(
                obs, original, original_desired
            )
            if base_reason is not None or list(base_ranked) != original or int(base_desired) != original_desired:
                return list(base_ranked), int(base_desired), base_reason
            if self.config.dead_active_escape:
                escape = self._apply_escape(obs, original, original_desired)
                if escape is not None:
                    return escape
            if self.config.punk_up_floor:
                punk = self._apply_punk_up(obs, original, original_desired)
                if punk is not None:
                    return punk
            return original, original_desired, None
        except Exception:
            self._clear_escape()
            raise

    def _selected(self, obs: Any, final_action: int | Iterable[int] | None) -> list[tuple[int, Any]]:
        if final_action is None:
            return []
        values = [final_action] if isinstance(final_action, int) else list(final_action)
        options = getattr(getattr(obs, "select", None), "option", None) or []
        selected = []
        for raw in values:
            index = _integer(raw, -1)
            if 0 <= index < len(options):
                selected.append((index, options[index]))
        return selected

    def commit(self, obs: Any, final_action: int | Iterable[int] | None) -> None:
        """Commit the base state and only semantic escape transitions."""

        self.last_reason = None
        try:
            self.base.commit(obs, final_action)
            if not self.config.dead_active_escape or not self._state_is_current(obs):
                return
            selected = self._selected(obs, final_action)
            if not selected:
                self._clear_escape()
                return
            if self.config.punk_up_floor and _context_is(obs.select, SelectContext.ATTACH_FROM):
                target = _target(obs, selected[0][0]) if len(selected) == 1 else None
                target_id = _integer(getattr(target, "id", 0), 0) if target is not None else 0
                if target_id in USEFUL_CAPACITY:
                    self.telemetry_counts["punk_up_energy_attached"] += 1
                    try:
                        me = obs.current.players[obs.current.yourIndex]
                        ready = sum(
                            _minimum_attack_deficit(card) == 0
                            for card in _board(me)
                            if _integer(getattr(card, "id", 0), 0) in USEFUL_CAPACITY
                        )
                        if _minimum_attack_deficit(target) == 1:
                            ready += 1
                        self.telemetry_counts["post_punk_ready_attackers"] = max(
                            self.telemetry_counts["post_punk_ready_attackers"], ready
                        )
                    except (AttributeError, IndexError, TypeError, ValueError):
                        pass
            selected_types = {_integer(getattr(option, "type", None)) for _, option in selected}
            if self.escape_stage == "attached":
                if (
                    _context_is(obs.select, SelectContext.MAIN)
                    and selected_types == {int(OptionType.RETREAT)}
                    and self._dead_active(obs) is not None
                ):
                    self.escape_stage = "promote"
                    return
                self._clear_escape()
                return
            if self.escape_stage == "promote":
                choices = _ready_grim_options(obs, [index for index, _ in selected])
                if choices:
                    self._clear_escape()
                else:
                    self._clear_escape()
                return

            if _context_is(obs.select, SelectContext.MAIN):
                attach = self._attach_escape_option(obs, [index for index, _ in selected])
                if attach is not None and selected == [(attach, obs.select.option[attach])]:
                    active = self._dead_active(obs)
                    if active is not None:
                        self.escape_stage = "attached"
                        self.escape_root_turn = _integer(obs.current.turn)
                        self.escape_player = _integer(obs.current.yourIndex)
                        self.dead_active_serial = _integer(getattr(active, "serial", 0), 0)
        except Exception:
            self._clear_escape()
            raise

    def telemetry(self) -> dict[str, Any]:
        base = self.base.telemetry()
        return {
            **base,
            "variance_config": asdict(self.config),
            "variance_interventions": dict(sorted(self.intervention_counts.items())),
            "variance_state": {
                "escape_pending": self.escape_stage is not None,
                "escape_stage": self.escape_stage,
                "root_turn": self.escape_root_turn,
                "player": self.escape_player,
                "dead_active_serial": self.dead_active_serial,
            },
            "punk_up_seen": int(self.telemetry_counts["punk_up_seen"]),
            "punk_up_forced_yes": int(self.telemetry_counts["punk_up_forced_yes"]),
            "punk_up_count_changed": int(self.telemetry_counts["punk_up_count_changed"]),
            "punk_up_target_changed": int(self.telemetry_counts["punk_up_target_changed"]),
            "punk_up_energy_attached": int(self.telemetry_counts["punk_up_energy_attached"]),
            "punk_up_prevented_excess_energy": int(
                self.telemetry_counts["punk_up_prevented_excess_energy"]
            ),
            "post_punk_ready_attackers": int(self.telemetry_counts["post_punk_ready_attackers"]),
            "last_reason": self.last_reason,
        }


__all__ = ["GrimVarianceConfig", "GrimVarianceFloorDirector", "useful_capacity"]
