"""A single work-boundary stop interface for fixed-work and deadline runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol


class StopPolicy(Protocol):
    mode: str
    completed_units: int

    def should_start_unit(self) -> bool: ...

    def record_completed_unit(self) -> None: ...


class StopPolicyError(RuntimeError):
    """The stop contract was violated."""


@dataclass
class FixedWorkStop:
    """Permit exactly ``requested_units`` successful atomic work units.

    The class deliberately has no clock field or clock dependency.  A failed
    work unit is not counted; callers must invalidate a fixed-work case instead
    of returning a partial search result.
    """

    requested_units: int
    completed_units: int = 0
    mode: str = "fixed_work"

    def __post_init__(self) -> None:
        if (
            isinstance(self.requested_units, bool)
            or not isinstance(self.requested_units, int)
            or self.requested_units < 0
        ):
            raise ValueError("requested_units must be a non-negative integer")

    def should_start_unit(self) -> bool:
        return self.completed_units < self.requested_units

    def record_completed_unit(self) -> None:
        if self.completed_units >= self.requested_units:
            raise StopPolicyError("fixed-work policy completed more than N units")
        self.completed_units += 1

    def assert_complete(self) -> None:
        if self.completed_units != self.requested_units:
            raise StopPolicyError(
                f"fixed-work case completed {self.completed_units}, expected {self.requested_units}"
            )


@dataclass
class WallClockStop:
    """Check a monotonic deadline at the boundary before every work unit."""

    requested_ns: int
    monotonic_ns: Callable[[], int]
    completed_units: int = 0
    mode: str = "wall_clock"

    def __post_init__(self) -> None:
        if (
            isinstance(self.requested_ns, bool)
            or not isinstance(self.requested_ns, int)
            or self.requested_ns < 0
        ):
            raise ValueError("requested_ns must be a non-negative integer")
        self.started_ns: int | None = None
        self.deadline_ns: int | None = None
        self.last_boundary_ns: int | None = None

    def start(self) -> None:
        if self.started_ns is not None:
            raise StopPolicyError("wall-clock stop policy was started more than once")
        self.started_ns = int(self.monotonic_ns())
        self.deadline_ns = self.started_ns + self.requested_ns
        self.last_boundary_ns = self.started_ns

    def should_start_unit(self) -> bool:
        if self.started_ns is None:
            self.start()
        self.last_boundary_ns = int(self.monotonic_ns())
        assert self.deadline_ns is not None
        return self.last_boundary_ns < self.deadline_ns

    def record_completed_unit(self) -> None:
        self.completed_units += 1

    def overshoot_ns(self, finished_ns: int) -> int:
        if self.deadline_ns is None:
            return 0
        return max(0, int(finished_ns) - self.deadline_ns)
