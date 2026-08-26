"""Fail-closed execution of one search decision under one stop policy."""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass
from typing import Any, Protocol

from .canonical import hash_json
from .stop_policy import FixedWorkStop, StopPolicy, WallClockStop
from .telemetry import DecisionTelemetry, WorkCounters


class DecisionAdapter(Protocol):
    agent_id: str

    def configure_instrumentation(self, enabled: bool) -> None: ...

    def reset_case(self, state: Any, agent_seed: int) -> None: ...

    def prepare(self) -> None: ...

    def perform_unit(self) -> WorkCounters | None: ...

    def select_action(self) -> tuple[list[int], list[float], str]: ...

    def cleanup(self) -> None: ...

    def state_hash(self) -> str: ...


@dataclass(frozen=True)
class CaseContext:
    case_id: str
    block_id: str
    decision_index: int
    load_condition: str
    lifecycle: str
    lifecycle_id: str
    process_instance_id: str
    sequence_index: int
    load_batch_id: str
    agent_seed: int
    instrumentation_enabled: bool = True


class DecisionRunError(RuntimeError):
    pass


def run_decision(
    adapter: DecisionAdapter,
    state: Any,
    stop: StopPolicy,
    context: CaseContext,
    *,
    monotonic_ns=time.monotonic_ns,
    process_time_ns=time.process_time_ns,
) -> DecisionTelemetry:
    """Execute one case; cleanup runs on every path and exactly one row returns."""

    counters = WorkCounters()
    selected_action: list[int] = []
    values: list[float] = []
    fallback_reason = ""
    timeout_reason = ""
    error_type = ""
    error_message = ""
    terminal_status = "ok"
    cleanup_succeeded = True
    instrumentation_enabled = bool(context.instrumentation_enabled)

    fallback_state_hash = hash_json(state)
    resolved_state_hash = fallback_state_hash
    setup_start = monotonic_ns()
    try:
        configure_instrumentation = getattr(adapter, "configure_instrumentation", None)
        if configure_instrumentation is None:
            if not instrumentation_enabled:
                raise DecisionRunError(
                    "adapter does not implement the required uninstrumented execution path"
                )
        else:
            configure_instrumentation(instrumentation_enabled)
        adapter.reset_case(state, context.agent_seed)
        adapter.prepare()
        resolved_state_hash = adapter.state_hash()
    except Exception as exc:
        terminal_status = "search_error"
        error_type = type(exc).__name__
        error_message = str(exc)
    setup_end = monotonic_ns()

    if isinstance(stop, WallClockStop):
        stop.start()
    search_start = monotonic_ns()
    cpu_start = process_time_ns()
    loop_finished_ns = search_start
    cpu_finished_ns = cpu_start
    selection_wall_ns = 0
    if terminal_status == "ok":
        try:
            while stop.should_start_unit():
                delta = adapter.perform_unit()
                if instrumentation_enabled:
                    if not isinstance(delta, WorkCounters):
                        raise DecisionRunError(
                            "instrumented adapter unit did not return WorkCounters"
                        )
                    if delta.work_units != 1:
                        raise DecisionRunError(
                            f"adapter unit reported {delta.work_units} work units; expected exactly one"
                        )
                    counters.add(delta)
                elif delta is not None:
                    raise DecisionRunError(
                        "uninstrumented adapter unit returned counters instead of None"
                    )
                stop.record_completed_unit()
            if isinstance(stop, FixedWorkStop):
                stop.assert_complete()
        except Exception as exc:
            terminal_status = "fixed_work_invalid" if isinstance(stop, FixedWorkStop) else "search_error"
            error_type = type(exc).__name__
            error_message = str(exc)
        finally:
            # This boundary is the scientific deadline finish.  Selection and
            # cleanup are measured separately and cannot inflate overshoot.
            loop_finished_ns = monotonic_ns()
            cpu_finished_ns = process_time_ns()

        if terminal_status == "ok":
            selection_start = monotonic_ns()
            try:
                selected_action, values, fallback_reason = adapter.select_action()
                if isinstance(stop, WallClockStop) and stop.completed_units == 0:
                    terminal_status = "deadline_no_work"
                    timeout_reason = "deadline_before_first_completed_unit"
            except Exception as exc:
                terminal_status = (
                    "fixed_work_invalid" if isinstance(stop, FixedWorkStop) else "search_error"
                )
                error_type = type(exc).__name__
                error_message = str(exc)
            finally:
                selection_wall_ns = max(0, monotonic_ns() - selection_start)
    else:
        cpu_finished_ns = process_time_ns()

    cleanup_start = monotonic_ns()
    try:
        adapter.cleanup()
    except Exception as exc:
        cleanup_succeeded = False
        if terminal_status in {"ok", "deadline_no_work"}:
            terminal_status = "cleanup_error"
            error_type = type(exc).__name__
            error_message = str(exc)
    finally:
        cleanup_wall_ns = max(0, monotonic_ns() - cleanup_start)

    if (
        isinstance(stop, FixedWorkStop)
        and stop.completed_units != stop.requested_units
        and terminal_status != "fixed_work_invalid"
    ):
        terminal_status = "fixed_work_invalid"
        error_type = error_type or "StopPolicyError"
        error_message = error_message or (
            f"fixed-work case completed {stop.completed_units}, expected {stop.requested_units}"
        )
    requested_budget_ns = stop.requested_ns if isinstance(stop, WallClockStop) else None
    requested_work_units = stop.requested_units if isinstance(stop, FixedWorkStop) else None
    overshoot_ns = stop.overshoot_ns(loop_finished_ns) if isinstance(stop, WallClockStop) else 0
    if hasattr(adapter, "action_identity"):
        action_identity = adapter.action_identity(selected_action)  # type: ignore[attr-defined]
    else:
        action_identity = {"option_indexes": selected_action}
    record = DecisionTelemetry(
        schema_version="decision-1.1.0",
        case_id=context.case_id,
        block_id=context.block_id,
        decision_index=context.decision_index,
        agent_id=adapter.agent_id,
        budget_mode=stop.mode,
        load_condition=context.load_condition,
        lifecycle=context.lifecycle,
        lifecycle_id=context.lifecycle_id,
        process_instance_id=context.process_instance_id,
        worker_pid=os.getpid(),
        sequence_index=context.sequence_index,
        load_batch_id=context.load_batch_id,
        requested_budget_ns=requested_budget_ns,
        requested_work_units=requested_work_units,
        completed_work_units=stop.completed_units,
        completed_simulations=counters.simulations,
        completed_nodes=counters.nodes,
        completed_sweeps=counters.sweeps,
        forward_model_calls=counters.forward_model_calls,
        setup_wall_ns=max(0, setup_end - setup_start),
        search_wall_ns=max(0, loop_finished_ns - search_start),
        selection_wall_ns=selection_wall_ns,
        cleanup_wall_ns=cleanup_wall_ns,
        process_cpu_ns=max(0, cpu_finished_ns - cpu_start),
        overshoot_ns=overshoot_ns,
        state_hash=resolved_state_hash,
        agent_seed_hash=hash_json({"agent_seed": context.agent_seed}),
        selected_action=selected_action,
        selected_action_hash=hash_json(action_identity),
        value_estimates=[
            float(value) if value is not None and math.isfinite(float(value)) else None
            for value in values
        ],
        timeout_reason=timeout_reason,
        fallback_reason=fallback_reason,
        cleanup_succeeded=cleanup_succeeded,
        instrumentation_enabled=instrumentation_enabled,
        work_counters_collected=instrumentation_enabled,
        terminal_status=terminal_status,
        error_type=error_type,
        error_message=error_message,
        extra={
            "stop_completed_units": stop.completed_units,
            "selected_action_identity": action_identity,
        },
    )
    record.validate()
    return record
