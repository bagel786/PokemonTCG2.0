from __future__ import annotations

import multiprocessing as mp
import signal
import time

import pytest

from resource_envelope_study.process_safety import stop_process


def _ignore_sigterm(ready) -> None:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    ready.set()
    while True:
        time.sleep(0.01)


class _FakeProcess:
    pid = 321

    def __init__(self, *, survives_kill: bool = False) -> None:
        self.alive = True
        self.survives_kill = survives_kill
        self.terminate_calls = 0
        self.kill_calls = 0

    def is_alive(self) -> bool:
        return self.alive

    def terminate(self) -> None:
        self.terminate_calls += 1

    def kill(self) -> None:
        self.kill_calls += 1
        if not self.survives_kill:
            self.alive = False

    def join(self, timeout: float) -> None:
        del timeout


def test_terminate_and_join_exceptions_do_not_skip_hard_kill() -> None:
    class ErroringProcess(_FakeProcess):
        def terminate(self) -> None:
            self.terminate_calls += 1
            raise RuntimeError("terminate transport failed")

        def join(self, timeout: float) -> None:
            if self.kill_calls == 0:
                raise RuntimeError("join transport failed")
            del timeout

    process = ErroringProcess()
    assert stop_process(
        process, terminate_timeout_s=0.0, kill_timeout_s=0.0
    ) == "killed"
    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert not process.is_alive()


def test_shutdown_refuses_to_abandon_a_surviving_child() -> None:
    process = _FakeProcess(survives_kill=True)
    with pytest.raises(RuntimeError, match="survived hard kill"):
        stop_process(process, terminate_timeout_s=0.0, kill_timeout_s=0.0)
    assert process.terminate_calls == 1
    assert process.kill_calls == 1


@pytest.mark.skipif("fork" not in mp.get_all_start_methods(), reason="requires POSIX fork")
def test_child_that_ignores_sigterm_is_hard_killed() -> None:
    context = mp.get_context("fork")
    ready = context.Event()
    process = context.Process(target=_ignore_sigterm, args=(ready,))
    process.start()
    try:
        assert ready.wait(timeout=2.0)
        assert stop_process(
            process,
            terminate_timeout_s=0.05,
            kill_timeout_s=2.0,
        ) == "killed"
        assert not process.is_alive()
        assert process.exitcode is not None
    finally:
        if process.is_alive():
            process.kill()
            process.join(timeout=2.0)
