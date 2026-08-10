"""Public, search-free proposal recall for the exact Grimmsnarl deck.

This module only constructs legal actions for the current prompt.  It does not
evaluate an engine state, inspect a deck list, choose a winning action, or
retain option indices between calls.  A later offline certifier may evaluate
the returned semantic alternatives.
"""

from __future__ import annotations

from typing import Any, Protocol, Sequence

from cg.api import OptionType, SelectContext

from .card_ids import (
    BUDDY_BUDDY_POFFIN,
    DARK_ENERGY,
    FROSLASS,
    MARNIES_GRIMMSNARL_EX,
    MARNIES_IMPIDIMP,
    MARNIES_MORGREM,
    MUNKIDORI,
    NIGHT_STRETCHER,
    POKE_PAD,
    RARE_CANDY,
    SNORUNT,
    SPIKEMUTH_GYM,
    TEAM_ROCKETS_PETREL,
)
from .proof_search import SemanticCandidate, semantic_action_key, semantic_candidates
from .safety import sanitize_selection
from .view import option_source_card


class FloorController(Protocol):
    """The narrow controller surface needed for an optional proposal."""

    def apply(
        self,
        obs: Any,
        ranked: list[int],
        desired: int,
    ) -> tuple[list[int], int, str | None]: ...


_BASIC_ROLES = frozenset({MARNIES_IMPIDIMP, SNORUNT, MUNKIDORI})
_MAIN_PLAY_ROLES = frozenset({
    *_BASIC_ROLES,
    NIGHT_STRETCHER,
    POKE_PAD,
    RARE_CANDY,
})
_EVOLUTION_ROLES = frozenset({MARNIES_MORGREM, MARNIES_GRIMMSNARL_EX, FROSLASS})
_TO_HAND_ROLES = frozenset({
    *_BASIC_ROLES,
    *_EVOLUTION_ROLES,
    DARK_ENERGY,
    BUDDY_BUDDY_POFFIN,
    NIGHT_STRETCHER,
    POKE_PAD,
    RARE_CANDY,
    SPIKEMUTH_GYM,
    TEAM_ROCKETS_PETREL,
})


def _integer(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _valid_action(select: Any, action: Sequence[int]) -> tuple[int, ...] | None:
    """Normalize one current-prompt action, returning ``None`` on any defect."""

    try:
        normalized = tuple(int(index) for index in action)
        options = list(select.option or [])
        minimum = int(select.minCount)
        maximum = int(select.maxCount)
    except (AttributeError, TypeError, ValueError):
        return None
    if (
        minimum < 0
        or maximum < minimum
        or len(normalized) != len(set(normalized))
        or not minimum <= len(normalized) <= maximum
        or any(index < 0 or index >= len(options) for index in normalized)
    ):
        return None
    return normalized


def _source_id(obs: Any, index: int) -> int | None:
    try:
        card = option_source_card(obs, obs.select.option[index])
        return int(card.id) if card is not None and getattr(card, "id", None) is not None else None
    except (AttributeError, IndexError, TypeError, ValueError):
        return None


def _effect_id(obs: Any) -> int | None:
    try:
        card = obs.select.effect or obs.select.contextCard
        return int(card.id) if card is not None and getattr(card, "id", None) is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


def _is_decline(select: Any, action: Sequence[int]) -> bool:
    """Treat END, NO, zero-number, and an empty optional selection as declines."""

    if not action:
        return True
    try:
        for index in action:
            option = select.option[int(index)]
            option_type = _integer(option.type)
            if option_type in {int(OptionType.END), int(OptionType.NO)}:
                return True
            if option_type == int(OptionType.NUMBER) and _integer(option.number, 0) == 0:
                return True
    except (AttributeError, IndexError, TypeError, ValueError):
        return True
    return False


def _targeted_actions(obs: Any) -> list[tuple[tuple[int, ...], str]]:
    """Return exact-deck role alternatives supported by the development audit."""

    select = obs.select
    options = list(select.option or [])
    context = _integer(select.context)
    result: list[tuple[tuple[int, ...], str]] = []

    def add_singletons(indices: Sequence[int], reason: str) -> None:
        if _integer(select.minCount, 0) <= 1 <= _integer(select.maxCount, -1):
            result.extend(((int(index),), reason) for index in indices)

    if context == int(SelectContext.TO_HAND):
        add_singletons(
            [index for index in range(len(options)) if _source_id(obs, index) in _TO_HAND_ROLES],
            "grim_to_hand_role",
        )

    if context == int(SelectContext.MAIN):
        add_singletons(
            [
                index
                for index, option in enumerate(options)
                if _integer(option.type) == int(OptionType.PLAY)
                and _source_id(obs, index) in _MAIN_PLAY_ROLES
            ],
            "grim_main_role_play",
        )
        add_singletons(
            [
                index
                for index, option in enumerate(options)
                if _integer(option.type) == int(OptionType.EVOLVE)
                and _source_id(obs, index) in _EVOLUTION_ROLES
            ],
            "grim_evolution_progress",
        )

    if (
        context == int(SelectContext.REMOVE_DAMAGE_COUNTER)
        and _effect_id(obs) == MUNKIDORI
    ):
        add_singletons(
            [
                index
                for index, option in enumerate(options)
                if _integer(option.type) == int(OptionType.CARD)
                and _source_id(obs, index) is not None
            ],
            "grim_munkidori_damage_source",
        )

    if context == int(SelectContext.TO_BENCH):
        add_singletons(
            [index for index in range(len(options)) if _source_id(obs, index) in _BASIC_ROLES],
            "grim_to_bench_role",
        )

    if context == int(SelectContext.ATTACH_TO):
        energy_indices = [
            index for index in range(len(options)) if _source_id(obs, index) == DARK_ENERGY
        ]
        # One deterministic semantic prefix for every legal positive count
        # bounds combinatorics while still proposing Punk Up count choices.
        keyed: list[tuple[str, int]] = []
        for index in energy_indices:
            try:
                keyed.append((semantic_action_key(obs, (index,)), index))
            except Exception:
                continue
        ordered = [index for _key, index in sorted(keyed)]
        minimum = max(1, _integer(select.minCount, 1))
        maximum = min(_integer(select.maxCount, 0), len(ordered))
        for count in range(minimum, maximum + 1):
            result.append((tuple(ordered[:count]), "grim_attach_to_count"))

    return result


def grim_semantic_candidates(
    obs: Any,
    baseline_action: Sequence[int],
    *,
    max_candidates: int = 8,
    floor_controller: FloorController | None = None,
    ranked: Sequence[int] | None = None,
    desired: int | None = None,
) -> tuple[SemanticCandidate, ...]:
    """Union bounded public proposals around d842 without evaluating them.

    The baseline is always first.  Every alternative is deduplicated by
    :func:`semantic_action_key` before the final cap, then ordered by that key
    so option-list permutations do not change semantic candidate order.
    Malformed inputs return no candidates; failures in an optional proposer
    retain the already validated baseline and other safe proposals.
    """

    if not isinstance(max_candidates, int) or isinstance(max_candidates, bool) or max_candidates < 1:
        return ()
    select = getattr(obs, "select", None)
    if select is None or getattr(obs, "current", None) is None:
        return ()
    baseline = _valid_action(select, baseline_action)
    if baseline is None:
        return ()
    try:
        baseline_key = semantic_action_key(obs, baseline)
    except Exception:
        return ()

    proposals: dict[str, dict[str, Any]] = {
        baseline_key: {
            "actions": [baseline],
            "reasons": {"d842_baseline"},
            "baseline": True,
        }
    }

    def add(action: Sequence[int], reason: str) -> None:
        normalized = _valid_action(select, action)
        if normalized is None:
            return
        if _is_decline(select, normalized) and normalized != baseline:
            return
        try:
            key = semantic_action_key(obs, normalized)
        except Exception:
            return
        if key == baseline_key:
            return
        item = proposals.setdefault(
            key,
            {"actions": [], "reasons": set(), "baseline": False},
        )
        item["actions"].append(normalized)
        item["reasons"].add(str(reason))

    # Ask the existing generator for its entire bounded-by-options set.  The
    # combined cap is deliberately applied only after cross-source dedup.
    try:
        existing = semantic_candidates(
            obs,
            baseline,
            max_candidates=max(1, len(list(select.option or [])) + 1),
        )
        for candidate in existing:
            if not candidate.is_baseline:
                add(candidate.action, "proof_search:" + candidate.reason)
    except Exception:
        pass

    if floor_controller is not None and ranked is not None and desired is not None:
        try:
            controller_ranked, controller_desired, controller_reason = floor_controller.apply(
                obs,
                [int(index) for index in ranked],
                int(desired),
            )
            controller_action = sanitize_selection(
                select,
                list(controller_ranked),
                int(controller_desired),
            )
            add(
                controller_action,
                "floor_controller:" + str(controller_reason or "proposal"),
            )
        except Exception:
            pass

    try:
        for action, reason in _targeted_actions(obs):
            add(action, reason)
    except Exception:
        pass

    baseline_candidate = SemanticCandidate(
        action=baseline,
        key=baseline_key,
        reason="d842_baseline",
        is_baseline=True,
    )
    alternatives: list[SemanticCandidate] = []
    for key in sorted(item for item in proposals if item != baseline_key):
        item = proposals[key]
        actions = sorted(set(item["actions"]))
        if not actions:
            continue
        alternatives.append(
            SemanticCandidate(
                action=actions[0],
                key=key,
                reason="+".join(sorted(item["reasons"])),
                is_baseline=False,
            )
        )
    return tuple([baseline_candidate, *alternatives[: max_candidates - 1]])


__all__ = ["FloorController", "grim_semantic_candidates"]
