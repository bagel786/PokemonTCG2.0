"""Narrow, development-certified guardrails around frozen Grimmsnarl d842.

The director intentionally does much less than the experimental floor
controller.  It recognizes only three public/legal-option patterns:

* finish the staged turn-zero setup to three Pokemon, in a fixed role order;
* attack with a ready Grimmsnarl instead of retreating;
* attack instead of Boss when the current Active is already the best immediate
  knockout available.

The director may resolve an own-visible hand card only when it is the source of
a current legal option (setup cards and Boss).  It never reads opponent-private
cards, hidden deck identities, or prize identities.

``apply`` never mutates setup state.  The caller must pass the sanitized action
to ``commit`` with the same observation.  This lets the director remember the
semantic cards selected during setup even though the engine does not expose
staged choices on the board.  No temporary option index is retained.
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable, Mapping, Sequence

from cg.api import OptionType, SelectContext, SelectType

from .card_ids import (
    BOSS_ORDERS,
    MARNIES_GRIMMSNARL_EX,
    MARNIES_IMPIDIMP,
    MUNKIDORI,
    SHADOW_BULLET,
    SNORUNT,
)
from .prevention import attack_nullified
from .view import attack_table, option_source_card, prize_value


SETUP_ROLE_ORDER = (MARNIES_IMPIDIMP, SNORUNT, MUNKIDORI)
SETUP_ROLE_TARGETS = {
    MARNIES_IMPIDIMP: 2,
    SNORUNT: 1,
    MUNKIDORI: 1,
}
SETUP_ROLE_NAMES = {
    MARNIES_IMPIDIMP: "impidimp",
    SNORUNT: "snorunt",
    MUNKIDORI: "munkidori",
}

DEFAULT_INTERVENTION_BUDGETS = {
    "setup_active": 1,
    "setup_bench": 3,
    "shadow_over_retreat": 8,
    "shadow_over_boss": 8,
}


def _integer(value, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _context_is(select, expected: SelectContext) -> bool:
    context = getattr(select, "context", None)
    if _integer(context) == int(expected):
        return True
    return str(context).replace("_", "").lower().endswith(
        expected.name.replace("_", "").lower()
    )


def _select_type_is(select, expected: SelectType) -> bool:
    value = getattr(select, "type", None)
    if _integer(value) == int(expected):
        return True
    return str(value).replace("_", "").lower().endswith(
        expected.name.replace("_", "").lower()
    )


def _valid_ranked(obs, ranked: Sequence[int]) -> bool:
    options = getattr(getattr(obs, "select", None), "option", None)
    try:
        unique = len(set(ranked)) == len(ranked)
    except TypeError:
        return False
    if options is None or not ranked or not unique:
        return False
    return all(isinstance(index, int) and 0 <= index < len(options) for index in ranked)


def _promote(ranked: Sequence[int], preferred: int) -> list[int]:
    """Move one current option index first without retaining it anywhere."""

    return [preferred] + [index for index in ranked if index != preferred]


def _promote_many(ranked: Sequence[int], preferred: Sequence[int]) -> list[int]:
    """Move current semantic choices first, preserving all relative order."""

    prefix = list(preferred)
    selected = set(prefix)
    return prefix + [index for index in ranked if index not in selected]


def _source_card_id(obs, index: int) -> int:
    try:
        card = option_source_card(obs, obs.select.option[index])
    except (AttributeError, IndexError, TypeError):
        return 0
    return _integer(getattr(card, "id", 0), 0)


def _attached_energy_count(pokemon) -> int:
    energies = getattr(pokemon, "energies", None)
    if energies is not None:
        return len(energies)
    return len(getattr(pokemon, "energyCards", None) or [])


class GrimGuardrailDirector:
    """Stateful semantic guardrails with fail-closed fallthrough to d842."""

    def __init__(self, budgets: Mapping[str, int] | None = None) -> None:
        configured = dict(DEFAULT_INTERVENTION_BUDGETS)
        if budgets is not None:
            unknown = set(budgets) - set(configured)
            if unknown:
                raise ValueError(f"unknown Grim guardrail budgets: {sorted(unknown)}")
            for name, value in budgets.items():
                if _integer(value) < 0:
                    raise ValueError(f"negative Grim guardrail budget: {name}")
                configured[name] = int(value)
        self.budget_limits = configured
        self.reset()

    def reset(self) -> None:
        self.setup_width = 0
        self.setup_roles: Counter[int] = Counter()
        self.intervention_counts: Counter[str] = Counter()
        self.budget_used: Counter[str] = Counter()
        self.commit_counts: Counter[str] = Counter()
        self.last_reason: str | None = None
        self.last_commit: str | None = None

    def _budget_available(self, name: str) -> bool:
        return self.budget_used[name] < self.budget_limits[name]

    def _record_intervention(self, budget: str, reason: str) -> None:
        self.budget_used[budget] += 1
        self.intervention_counts[reason] += 1
        self.last_reason = reason

    def telemetry(self) -> dict:
        return {
            "last_reason": self.last_reason,
            "last_commit": self.last_commit,
            "setup_width": self.setup_width,
            "setup_roles": {
                SETUP_ROLE_NAMES[card_id]: int(self.setup_roles[card_id])
                for card_id in SETUP_ROLE_ORDER
            },
            "interventions": dict(sorted(self.intervention_counts.items())),
            "commits": dict(sorted(self.commit_counts.items())),
            "budgets": {
                name: {
                    "limit": limit,
                    "used": int(self.budget_used[name]),
                    "remaining": max(0, limit - int(self.budget_used[name])),
                }
                for name, limit in sorted(self.budget_limits.items())
            },
        }

    def _setup_role_options(self, obs, ranked: Sequence[int]) -> dict[int, list[int]]:
        choices = {card_id: [] for card_id in SETUP_ROLE_ORDER}
        for index in ranked:
            option = obs.select.option[index]
            if _integer(getattr(option, "type", None)) != int(OptionType.CARD):
                continue
            card_id = _source_card_id(obs, index)
            if card_id in choices:
                choices[card_id].append(index)
        return choices

    def _missing_legal_role(self, choices: Mapping[int, Sequence[int]]) -> int | None:
        for card_id in SETUP_ROLE_ORDER:
            if (
                self.setup_roles[card_id] < SETUP_ROLE_TARGETS[card_id]
                and choices.get(card_id)
            ):
                return card_id
        return None

    def _setup_role_plan(
        self,
        obs,
        choices: Mapping[int, Sequence[int]],
        ranked: Sequence[int],
        count: int,
    ) -> list[int]:
        """Choose ``count`` setup cards by role without retaining option indices."""

        planned: list[int] = []
        used: set[int] = set()
        roles = Counter(self.setup_roles)
        for card_id in SETUP_ROLE_ORDER:
            for index in choices.get(card_id, ()):  # ranked within each role
                if len(planned) >= count or roles[card_id] >= SETUP_ROLE_TARGETS[card_id]:
                    break
                if index in used:
                    continue
                planned.append(index)
                used.add(index)
                roles[card_id] += 1
        # Width is the hard setup invariant.  If the ideal role mix is not in
        # hand, fill the remaining legal slots in d842 order rather than stop at
        # one card or invent a non-current option.
        for index in ranked:
            if len(planned) >= count:
                break
            if index not in used and _source_card_id(obs, index) in SETUP_ROLE_TARGETS:
                planned.append(index)
                used.add(index)
        return planned

    def _apply_setup(self, obs, ranked: list[int], desired: int):
        state = getattr(obs, "current", None)
        select = getattr(obs, "select", None)
        if (
            state is None
            or select is None
            or _integer(getattr(state, "turn", None)) != 0
            or not _select_type_is(select, SelectType.CARD)
            or desired not in (0, 1)
        ):
            return None

        active_prompt = _context_is(select, SelectContext.SETUP_ACTIVE_POKEMON)
        bench_prompt = _context_is(select, SelectContext.SETUP_BENCH_POKEMON)
        if not active_prompt and not bench_prompt:
            return None
        if active_prompt:
            if _integer(getattr(select, "minCount", None), -1) < 1:
                return None
            budget = "setup_active"
        else:
            # This branch is intentionally limited to the optional staged
            # prompt observed in development.  Mandatory/other CARD prompts
            # fall through unchanged.
            if _integer(getattr(select, "minCount", None), -1) != 0:
                return None
            if self.setup_width >= 3:
                return None
            budget = "setup_bench"
        if not self._budget_available(budget):
            return None

        choices = self._setup_role_options(obs, ranked)
        role = self._missing_legal_role(choices)
        has_any_role = any(choices.values())
        if role is None and not (bench_prompt and self.setup_width < 3 and has_any_role):
            return None
        if active_prompt:
            forced_count = 1
        else:
            forced_count = min(
                max(0, 3 - self.setup_width),
                _integer(getattr(select, "maxCount", None), 0),
                len(ranked),
            )
        new_desired = max(desired, forced_count)
        preferred = self._setup_role_plan(obs, choices, ranked, new_desired)
        if not preferred:
            return None
        promoted = _promote_many(ranked, preferred)
        if new_desired == desired and promoted[:new_desired] == ranked[:new_desired]:
            return None
        planned_roles = [SETUP_ROLE_NAMES[_source_card_id(obs, index)] for index in preferred]
        reason = f"setup:{'active' if active_prompt else 'bench'}_" + "_".join(planned_roles)
        self._record_intervention(budget, reason)
        return promoted, new_desired, reason

    def _shadow_option(self, obs, ranked: Sequence[int]) -> int | None:
        state = getattr(obs, "current", None)
        if state is None:
            return None
        try:
            me = state.players[state.yourIndex]
            active = next(card for card in (me.active or []) if card is not None)
        except (AttributeError, IndexError, StopIteration, TypeError):
            return None
        if int(getattr(active, "id", 0) or 0) != MARNIES_GRIMMSNARL_EX:
            return None
        shadow = attack_table().get(SHADOW_BULLET)
        if shadow is None or _attached_energy_count(active) < len(shadow.energies):
            return None
        for index in ranked:
            option = obs.select.option[index]
            if (
                _integer(getattr(option, "type", None)) == int(OptionType.ATTACK)
                and _integer(getattr(option, "attackId", None)) == SHADOW_BULLET
            ):
                try:
                    if attack_nullified(obs, option):
                        return None
                except (AttributeError, IndexError, TypeError, ValueError):
                    return None
                return index
        return None

    def _opponent_active_is_best_immediate_ko(self, obs) -> bool:
        state = getattr(obs, "current", None)
        shadow = attack_table().get(SHADOW_BULLET)
        if state is None or shadow is None or int(shadow.damage or 0) <= 0:
            return False
        try:
            opponent = state.players[1 - state.yourIndex]
            active = next(card for card in (opponent.active or []) if card is not None)
        except (AttributeError, IndexError, StopIteration, TypeError):
            return False
        hp = _integer(getattr(active, "hp", None), -1)
        if not 0 < hp <= int(shadow.damage):
            return False
        active_prizes = prize_value(active)
        # If Boss exposes a higher-prize immediate knockout, the claimed
        # dominance is uncertain and d842 must retain control.
        for target in getattr(opponent, "bench", None) or []:
            if target is None:
                continue
            target_hp = _integer(getattr(target, "hp", None), -1)
            if 0 < target_hp <= int(shadow.damage) and prize_value(target) > active_prizes:
                return False
        return True

    def _apply_attack(self, obs, ranked: list[int], desired: int):
        select = getattr(obs, "select", None)
        if (
            select is None
            or not _select_type_is(select, SelectType.MAIN)
            or not _context_is(select, SelectContext.MAIN)
            or desired != 1
        ):
            return None
        shadow_index = self._shadow_option(obs, ranked)
        if shadow_index is None:
            return None
        top = obs.select.option[ranked[0]]
        top_type = _integer(getattr(top, "type", None))
        if top_type == int(OptionType.RETREAT):
            budget = "shadow_over_retreat"
            reason = "attack:shadow_over_retreat"
        elif top_type == int(OptionType.PLAY) and _source_card_id(obs, ranked[0]) == BOSS_ORDERS:
            if not self._opponent_active_is_best_immediate_ko(obs):
                return None
            budget = "shadow_over_boss"
            reason = "attack:shadow_over_boss_active_ko"
        else:
            return None
        if ranked[0] == shadow_index or not self._budget_available(budget):
            return None
        self._record_intervention(budget, reason)
        return _promote(ranked, shadow_index), desired, reason

    def apply(self, obs, ranked: Sequence[int], desired: int):
        """Return a reordered current ranking, desired count, and named reason."""

        original = list(ranked)
        original_desired = int(desired)
        self.last_reason = None
        if not _valid_ranked(obs, original):
            return original, original_desired, None
        setup = self._apply_setup(obs, original, original_desired)
        if setup is not None:
            return setup
        attack = self._apply_attack(obs, original, original_desired)
        if attack is not None:
            return attack
        return original, original_desired, None

    def commit(self, obs, final_action: int | Iterable[int] | None) -> None:
        """Commit the sanitized semantic setup choices from the same prompt.

        The method deliberately resolves each index against ``obs`` immediately
        and stores only role counts.  Call it exactly once for each final engine
        action; non-setup actions are harmless no-ops.
        """

        self.last_commit = None
        state = getattr(obs, "current", None)
        select = getattr(obs, "select", None)
        if state is None or select is None or _integer(getattr(state, "turn", None)) != 0:
            return
        active_prompt = _context_is(select, SelectContext.SETUP_ACTIVE_POKEMON)
        bench_prompt = _context_is(select, SelectContext.SETUP_BENCH_POKEMON)
        if not active_prompt and not bench_prompt:
            return
        if final_action is None:
            return
        values = [final_action] if isinstance(final_action, int) else list(final_action)
        committed = []
        options = getattr(select, "option", None) or []
        for value in values:
            index = _integer(value)
            if not 0 <= index < len(options):
                continue
            card_id = _source_card_id(obs, index)
            if card_id not in SETUP_ROLE_TARGETS:
                continue
            self.setup_roles[card_id] += 1
            self.setup_width += 1
            role = SETUP_ROLE_NAMES[card_id]
            key = f"setup:{'active' if active_prompt else 'bench'}_{role}"
            self.commit_counts[key] += 1
            committed.append(role)
        if committed:
            self.last_commit = f"setup:{'active' if active_prompt else 'bench'}:" + ",".join(committed)
