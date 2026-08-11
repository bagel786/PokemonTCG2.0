"""Flat numeric mechanism telemetry for FESTIVAL-D0 and FESTIVAL-D1."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from math import isfinite
from typing import Mapping


_SCALAR_KEYS = (
    "decisions",
    "policy_errors",
    "legal_fallbacks",
    "unknown_contexts",
    "go_first_choices",
    "go_first_yes",
    "go_first_no",
    "quick_sign_offered",
    "quick_sign_taken",
    "festival_plays",
    "festival_available_missed_attack_turns",
    "lillie_before_tutor",
    "lillie_after_tutor",
    "energy_attachments",
    "energy_to_current_attacker",
    "energy_to_replacement_attacker",
    "brave_bangle_attachments",
    "black_belt_uses",
    "black_belt_threshold_crossing_uses",
    "boss_uses",
    "boss_prizes_enabled",
    "productive_attacks_offered",
    "productive_attacks_taken",
    "first_festival_attacks",
    "second_attacks_offered",
    "second_attacks_taken",
    "second_attacks_missed",
    "first_attack_kos",
    "replacement_attacker_ready_end_turn",
    "late_turns_no_productive_attack",
    "search_independent_latency_count",
    "search_independent_latency_ms_total",
    "search_independent_latency_ms_max",
    "malformed_observations",
)


def _safe_fragment(value: object) -> str:
    text = str(value).strip().lower()
    return "".join(character if character.isalnum() else "_" for character in text).strip("_") or "unknown"


@dataclass
class DipplinTelemetry:
    """Mutable counters whose exported representation is numeric and flat.

    Dynamic distributions (phase, card target, target pair) are namespaced into
    scalar keys at export time so ``training/evaluate.py`` never receives nested
    dictionaries, strings, or ``None`` values.
    """

    scalars: Counter[str] = field(default_factory=Counter)
    phases: Counter[str] = field(default_factory=Counter)
    setup_active: Counter[int] = field(default_factory=Counter)
    quick_sign_pairs: Counter[tuple[int, ...]] = field(default_factory=Counter)
    thwackey_tutors: Counter[int] = field(default_factory=Counter)
    energy_targets: Counter[int] = field(default_factory=Counter)
    bangle_targets: Counter[int] = field(default_factory=Counter)
    boss_targets: Counter[int] = field(default_factory=Counter)

    def reset(self) -> None:
        self.scalars.clear()
        self.phases.clear()
        self.setup_active.clear()
        self.quick_sign_pairs.clear()
        self.thwackey_tutors.clear()
        self.energy_targets.clear()
        self.bangle_targets.clear()
        self.boss_targets.clear()

    def clone(self) -> DipplinTelemetry:
        result = type(self)()
        result.scalars.update(self.scalars)
        result.phases.update(self.phases)
        result.setup_active.update(self.setup_active)
        result.quick_sign_pairs.update(self.quick_sign_pairs)
        result.thwackey_tutors.update(self.thwackey_tutors)
        result.energy_targets.update(self.energy_targets)
        result.bangle_targets.update(self.bangle_targets)
        result.boss_targets.update(self.boss_targets)
        return result

    def increment(self, key: str, amount: int | float = 1) -> None:
        value = float(amount)
        if not isfinite(value):
            return
        self.scalars[str(key)] += amount

    inc = increment

    def record_phase(self, phase: object) -> None:
        value = getattr(phase, "value", phase)
        self.phases[_safe_fragment(value)] += 1

    def record_go_first(self, go_first: bool) -> None:
        self.scalars["go_first_choices"] += 1
        self.scalars["go_first_yes" if go_first else "go_first_no"] += 1

    def record_setup_active(self, card_id: int) -> None:
        self.setup_active[int(card_id)] += 1

    def record_quick_sign(self, targets: tuple[int, ...] | list[int]) -> None:
        target_pair = tuple(sorted(int(card_id) for card_id in targets))
        self.scalars["quick_sign_taken"] += 1
        self.quick_sign_pairs[target_pair] += 1

    def record_thwackey_tutor(self, card_id: int) -> None:
        self.thwackey_tutors[int(card_id)] += 1

    def record_energy_attachment(
        self,
        target_card_id: int,
        *,
        current_attacker: bool = False,
        replacement_attacker: bool = False,
    ) -> None:
        self.scalars["energy_attachments"] += 1
        self.energy_targets[int(target_card_id)] += 1
        if current_attacker:
            self.scalars["energy_to_current_attacker"] += 1
        if replacement_attacker:
            self.scalars["energy_to_replacement_attacker"] += 1

    def record_bangle_target(self, card_id: int) -> None:
        self.scalars["brave_bangle_attachments"] += 1
        self.bangle_targets[int(card_id)] += 1

    def record_boss_target(self, card_id: int, *, prizes_enabled: int = 0) -> None:
        self.scalars["boss_uses"] += 1
        self.scalars["boss_prizes_enabled"] += max(0, int(prizes_enabled))
        self.boss_targets[int(card_id)] += 1

    def record_latency(self, milliseconds: float) -> None:
        value = max(0.0, float(milliseconds))
        if not isfinite(value):
            return
        self.scalars["search_independent_latency_count"] += 1
        self.scalars["search_independent_latency_ms_total"] += value
        self.scalars["search_independent_latency_ms_max"] = max(
            float(self.scalars["search_independent_latency_ms_max"]), value
        )

    def merge_flat(self, values: Mapping[str, int | float]) -> None:
        for key, value in values.items():
            if isinstance(value, bool):
                value = int(value)
            if isinstance(value, (int, float)) and isfinite(float(value)):
                self.scalars[str(key)] += value

    def flat(self) -> dict[str, int | float]:
        result: dict[str, int | float] = {
            key: self.scalars.get(key, 0) for key in _SCALAR_KEYS
        }
        for key, value in self.scalars.items():
            if isinstance(value, (int, float)) and isfinite(float(value)):
                result[str(key)] = value
        for phase, value in self.phases.items():
            result[f"phase_{_safe_fragment(phase)}"] = value
        for card_id, value in self.setup_active.items():
            result[f"setup_active_{card_id}"] = value
        for pair, value in self.quick_sign_pairs.items():
            suffix = "_".join(map(str, pair)) if pair else "none"
            result[f"quick_sign_pair_{suffix}"] = value
        for card_id, value in self.thwackey_tutors.items():
            result[f"thwackey_tutor_{card_id}"] = value
        for card_id, value in self.energy_targets.items():
            result[f"energy_target_{card_id}"] = value
        for card_id, value in self.bangle_targets.items():
            result[f"bangle_target_{card_id}"] = value
        for card_id, value in self.boss_targets.items():
            result[f"boss_target_{card_id}"] = value
        return result

    snapshot = flat
    as_flat_dict = flat


# Short name used by the competition agent.
Telemetry = DipplinTelemetry

