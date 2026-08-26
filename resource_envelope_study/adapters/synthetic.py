"""Deterministic adapter used to validate scheduler and stop mechanics."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Callable

from ..canonical import hash_json
from ..telemetry import WorkCounters


@dataclass
class SyntheticSearchAdapter:
    agent_id: str = "synthetic_counter_search"
    unit_hook: Callable[[int], None] | None = None
    selection_hook: Callable[[], None] | None = None
    cleanup_hook: Callable[[], None] | None = None
    fail_on_unit: int | None = None
    cleanup_raises: bool = False

    def configure_instrumentation(self, enabled: bool) -> None:
        self._instrumentation_enabled = bool(enabled)

    def reset_case(self, state: Any, agent_seed: int) -> None:
        self._state = state
        self._seed = int(agent_seed)
        self._units = 0
        self._scores = [0, 0, 0]
        self.cleaned = False

    def prepare(self) -> None:
        self._state_digest = hash_json(self._state)

    def perform_unit(self) -> WorkCounters | None:
        if self.fail_on_unit is not None and self._units == self.fail_on_unit:
            raise RuntimeError("injected work-unit failure")
        if self.unit_hook is not None:
            self.unit_hook(self._units)
        material = f"{self._state_digest}:{self._seed}:{self._units}".encode("ascii")
        word = int.from_bytes(hashlib.sha256(material).digest()[:8], "big")
        self._scores[word % len(self._scores)] += 1 + ((word >> 8) & 7)
        self._units += 1
        if not self._instrumentation_enabled:
            return None
        return WorkCounters(work_units=1, simulations=1, nodes=1, forward_model_calls=2)

    def select_action(self) -> tuple[list[int], list[float], str]:
        if self.selection_hook is not None:
            self.selection_hook()
        best = max(range(len(self._scores)), key=lambda index: (self._scores[index], -index))
        return [best], [float(score) for score in self._scores], ""

    def cleanup(self) -> None:
        if self.cleanup_hook is not None:
            self.cleanup_hook()
        self.cleaned = True
        if self.cleanup_raises:
            raise RuntimeError("injected cleanup failure")

    def state_hash(self) -> str:
        return self._state_digest
