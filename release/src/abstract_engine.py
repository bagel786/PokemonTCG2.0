"""Abstract boundary for an independently authorized stochastic game engine.

No competition-engine implementation, API binding, rule logic, card data, or
package loader is included. An authorized reproducer must implement this
interface against an engine obtained under the organizer's own terms.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol


@dataclass(frozen=True)
class MatchSpec:
    """One member of a candidate-control common-random-number pair."""

    seed: int
    actual_order: str
    physical_seat: int
    candidate_package_digest: str
    opponent_package_digest: str
    environment: Mapping[str, str]
    maximum_decisions: int


@dataclass(frozen=True)
class MatchResult:
    """Minimal sanitized terminal result consumed by the analysis package."""

    win: bool
    draw: bool
    hero_policy_errors: int
    opponent_policy_errors: int
    terminal: bool


class AuthorizedEngineAdapter(Protocol):
    """Interface to be implemented only by a separately authorized user."""

    @property
    def engine_sha256(self) -> str:
        """Return the exact executable-engine digest."""

    def run(self, spec: MatchSpec) -> MatchResult:
        """Execute one fixed match without mutating the production engine."""


def validate_pair(candidate: MatchSpec, control: MatchSpec) -> None:
    """Fail closed unless the nuisance conditions defining a pair match."""

    fields = ("seed", "actual_order", "physical_seat", "opponent_package_digest",
              "environment", "maximum_decisions")
    mismatches = [field for field in fields if getattr(candidate, field) != getattr(control, field)]
    if mismatches:
        raise ValueError(f"candidate/control pair mismatch: {', '.join(mismatches)}")
