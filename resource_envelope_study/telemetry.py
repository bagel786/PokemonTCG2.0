"""Versioned, terminally complete telemetry records."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .canonical import hash_json


DECISION_TERMINAL_STATUSES = frozenset(
    {
        "ok",
        "deadline_no_work",
        "search_error",
        "cleanup_error",
        "fixed_work_invalid",
        "illegal_action",
        "infrastructure_error",
    }
)

GAME_TERMINAL_STATUSES = frozenset(
    {
        "completed",
        "agent_timeout",
        "agent_error",
        "illegal_action",
        "engine_error",
        "infrastructure_error",
        "protocol_invalid",
    }
)


@dataclass
class WorkCounters:
    work_units: int = 0
    simulations: int = 0
    nodes: int = 0
    sweeps: int = 0
    forward_model_calls: int = 0

    def add(self, other: "WorkCounters") -> None:
        self.work_units += int(other.work_units)
        self.simulations += int(other.simulations)
        self.nodes += int(other.nodes)
        self.sweeps += int(other.sweeps)
        self.forward_model_calls += int(other.forward_model_calls)


@dataclass
class DecisionTelemetry:
    schema_version: str
    case_id: str
    block_id: str
    decision_index: int
    agent_id: str
    budget_mode: str
    load_condition: str
    lifecycle: str
    lifecycle_id: str
    process_instance_id: str
    worker_pid: int
    sequence_index: int
    load_batch_id: str
    requested_budget_ns: int | None
    requested_work_units: int | None
    completed_work_units: int
    completed_simulations: int
    completed_nodes: int
    completed_sweeps: int
    forward_model_calls: int
    setup_wall_ns: int
    search_wall_ns: int
    selection_wall_ns: int
    cleanup_wall_ns: int
    process_cpu_ns: int
    overshoot_ns: int
    state_hash: str
    agent_seed_hash: str
    selected_action: list[int]
    selected_action_hash: str
    value_estimates: list[float | None]
    timeout_reason: str
    fallback_reason: str
    cleanup_succeeded: bool
    instrumentation_enabled: bool
    work_counters_collected: bool
    terminal_status: str
    error_type: str = ""
    error_message: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.terminal_status not in DECISION_TERMINAL_STATUSES:
            raise ValueError(f"unknown decision terminal status: {self.terminal_status}")
        if self.completed_work_units < 0:
            raise ValueError("completed work cannot be negative")
        if self.worker_pid <= 0:
            raise ValueError("worker_pid must be a positive observed OS process ID")
        for field_name in (
            "completed_simulations",
            "completed_nodes",
            "completed_sweeps",
            "forward_model_calls",
            "setup_wall_ns",
            "search_wall_ns",
            "selection_wall_ns",
            "cleanup_wall_ns",
            "process_cpu_ns",
            "overshoot_ns",
        ):
            if int(getattr(self, field_name)) < 0:
                raise ValueError(f"{field_name} cannot be negative")
        if self.work_counters_collected != self.instrumentation_enabled:
            raise ValueError("work-counter collection must match the instrumentation mode")
        if not self.work_counters_collected and any(
            (
                self.completed_simulations,
                self.completed_nodes,
                self.completed_sweeps,
                self.forward_model_calls,
            )
        ):
            raise ValueError("disabled work counters must use explicit zero sentinels")
        if self.budget_mode == "fixed_work":
            if self.requested_work_units is None:
                raise ValueError("fixed-work row lacks requested_work_units")
            if self.terminal_status == "ok" and self.completed_work_units != self.requested_work_units:
                raise ValueError("successful fixed-work row is not exact")
        if self.budget_mode == "wall_clock" and self.requested_budget_ns is None:
            raise ValueError("wall-clock row lacks requested_budget_ns")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)


@dataclass
class GameTelemetry:
    schema_version: str
    case_id: str
    block_id: str
    agent_id: str
    score: float | None
    winner: int | None
    terminal_status: str
    decision_count: int
    completed_work_units: int
    completed_simulations: int
    completed_nodes: int
    completed_sweeps: int
    forward_model_calls: int
    decision_record_hashes: list[str]
    error_type: str = ""
    error_message: str = ""

    def validate(self) -> None:
        if self.terminal_status not in GAME_TERMINAL_STATUSES:
            raise ValueError(f"unknown game terminal status: {self.terminal_status}")
        if self.score is not None and self.score not in {0.0, 0.5, 1.0}:
            raise ValueError("score must be 0, 0.5, 1, or null")
        if self.decision_count != len(self.decision_record_hashes):
            raise ValueError("decision count does not reconcile with hashes")

    @classmethod
    def from_decisions(
        cls,
        *,
        case_id: str,
        block_id: str,
        agent_id: str,
        decisions: list[DecisionTelemetry],
        score: float | None,
        winner: int | None,
        terminal_status: str,
        error_type: str = "",
        error_message: str = "",
    ) -> "GameTelemetry":
        record = cls(
            schema_version="game-1.0.0",
            case_id=case_id,
            block_id=block_id,
            agent_id=agent_id,
            score=score,
            winner=winner,
            terminal_status=terminal_status,
            decision_count=len(decisions),
            completed_work_units=sum(row.completed_work_units for row in decisions),
            completed_simulations=sum(row.completed_simulations for row in decisions),
            completed_nodes=sum(row.completed_nodes for row in decisions),
            completed_sweeps=sum(row.completed_sweeps for row in decisions),
            forward_model_calls=sum(row.forward_model_calls for row in decisions),
            decision_record_hashes=[hash_json(row.to_dict()) for row in decisions],
            error_type=error_type,
            error_message=error_message,
        )
        record.validate()
        return record
