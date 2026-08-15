"""Legality and runtime fail-closed behavior."""

from __future__ import annotations

from cg.api import OptionType


def sanitize_selection(select, ranked: list[int], desired_count: int | None = None) -> list[int]:
    """Convert arbitrary policy output into a legal option-index list.

    This is the final boundary before returning to Kaggle. It deliberately knows nothing
    about strategy: it removes duplicates/out-of-range indices and fills required slots
    from deterministic fallbacks.
    """
    option_count = len(select.option)
    unique: list[int] = []
    seen: set[int] = set()
    for raw in ranked:
        if isinstance(raw, int) and 0 <= raw < option_count and raw not in seen:
            unique.append(raw)
            seen.add(raw)

    target = select.maxCount if desired_count is None else desired_count
    target = max(select.minCount, min(select.maxCount, int(target)))
    for index in range(option_count):
        if len(unique) >= target:
            break
        if index not in seen:
            unique.append(index)
            seen.add(index)

    return unique[:target]


def emergency_selection(select) -> list[int]:
    """Return a legal conservative action without consulting policy state."""
    if select.maxCount == 0:
        return []
    if select.minCount == 0:
        end = next(
            (i for i, option in enumerate(select.option) if option.type == OptionType.END),
            None,
        )
        if end is not None:
            return [end]
        return []
    return list(range(min(select.minCount, len(select.option))))

