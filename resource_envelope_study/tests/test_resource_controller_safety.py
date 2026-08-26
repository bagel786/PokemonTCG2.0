from __future__ import annotations

import os

import pytest

import resource_envelope_study.resource_controller as controller
from resource_envelope_study.resource_controller import LoadProfile, ResourceEnvelope


class _Event:
    def __init__(self) -> None:
        self.set_called = False

    def set(self) -> None:
        self.set_called = True


class _Queue:
    def __init__(self) -> None:
        self.closed = False
        self.joined = False

    def close(self) -> None:
        self.closed = True

    def join_thread(self) -> None:
        self.joined = True


class _FakeProcess:
    def __init__(
        self,
        pid: int,
        *,
        start_error: bool = False,
        survives_kill: bool = False,
    ) -> None:
        self.pid = pid
        self.exitcode = None
        self.start_error = start_error
        self.survives_kill = survives_kill
        self.alive = False
        self.terminate_calls = 0
        self.kill_calls = 0

    def start(self) -> None:
        self.alive = True
        if self.start_error:
            raise RuntimeError("partial process start failure")

    def is_alive(self) -> bool:
        return self.alive

    def join(self, timeout: float) -> None:
        del timeout

    def terminate(self) -> None:
        self.terminate_calls += 1
        if not self.survives_kill:
            self.alive = False
            self.exitcode = -15

    def kill(self) -> None:
        self.kill_calls += 1
        if not self.survives_kill:
            self.alive = False
            self.exitcode = -9


def _target_cpu() -> int:
    if hasattr(os, "sched_getaffinity"):
        return min(os.sched_getaffinity(0))
    return 0


def test_kill_survivor_handle_is_retained_and_cleanup_never_succeeds() -> None:
    process = _FakeProcess(98765, survives_kill=True)
    process.alive = True
    envelope = ResourceEnvelope(
        LoadProfile("loaded", 1, (_target_cpu(),)),
        17,
        "safety-test",
    )
    envelope._stop_event = _Event()
    envelope._processes = [process]
    envelope.metadata = {
        "workers": [{"pid": process.pid, "cpu_ticks_start": None}],
    }

    with pytest.raises(RuntimeError, match="survived hard kill"):
        envelope.close()
    assert envelope._closed is True
    assert envelope._processes == [process]
    assert envelope.metadata["surviving_worker_pids"] == [process.pid]
    assert envelope.metadata["cleanup_succeeded"] is False
    assert process.terminate_calls == 1
    assert process.kill_calls == 1


def test_partial_startup_failure_stops_every_allocated_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _FakeProcess(10101)
    partial = _FakeProcess(20202, start_error=True)
    queue = _Queue()
    event = _Event()

    class _Context:
        def __init__(self) -> None:
            self.processes = iter((first, partial))

        def Event(self):
            return event

        def Queue(self):
            return queue

        def Process(self, **kwargs):
            del kwargs
            return next(self.processes)

    monkeypatch.setattr(controller.mp, "get_context", lambda _method: _Context())
    envelope = ResourceEnvelope(
        LoadProfile("loaded", 2, (_target_cpu(),)),
        18,
        "partial-start-test",
    )
    with pytest.raises(RuntimeError, match="nonzero exit codes"):
        envelope.__enter__()
    assert event.set_called
    assert first.terminate_calls == partial.terminate_calls == 1
    assert not first.is_alive() and not partial.is_alive()
    assert envelope._processes == []
    assert queue.closed and queue.joined
    assert envelope.metadata["cleanup_succeeded"] is False


def test_cleanup_failure_supersedes_an_inflight_benchmark_exception() -> None:
    process = _FakeProcess(30303, survives_kill=True)
    process.alive = True
    envelope = ResourceEnvelope(
        LoadProfile("loaded", 1, (_target_cpu(),)),
        19,
        "exception-cleanup-test",
    )
    envelope._stop_event = _Event()
    envelope._processes = [process]
    envelope.metadata = {
        "workers": [{"pid": process.pid, "cpu_ticks_start": None}],
    }
    with pytest.raises(RuntimeError, match="survived hard kill"):
        envelope.__exit__(ValueError, ValueError("benchmark failed"), None)
    assert envelope._processes == [process]


def test_cooperative_stop_and_initial_join_errors_still_reach_hard_shutdown() -> None:
    class ErrorEvent(_Event):
        def set(self) -> None:
            super().set()
            raise RuntimeError("event channel failed")

    class JoinErrorProcess(_FakeProcess):
        def __init__(self) -> None:
            super().__init__(40404)
            self.join_calls = 0

        def join(self, timeout: float) -> None:
            del timeout
            self.join_calls += 1
            if self.join_calls == 1:
                raise RuntimeError("initial join failed")

    process = JoinErrorProcess()
    process.alive = True
    envelope = ResourceEnvelope(
        LoadProfile("loaded", 1, (_target_cpu(),)),
        20,
        "cooperative-error-test",
    )
    envelope._stop_event = ErrorEvent()
    envelope._processes = [process]
    envelope.metadata = {
        "workers": [{"pid": process.pid, "cpu_ticks_start": None}],
    }
    with pytest.raises(RuntimeError, match="cooperative stop failed.*initial join failed"):
        envelope.close()
    assert process.terminate_calls == 1
    assert not process.is_alive()
    assert envelope._processes == []
