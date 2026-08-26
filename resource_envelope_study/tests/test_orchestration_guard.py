from __future__ import annotations

import math
import os
import platform
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from resource_envelope_study.orchestration_guard import (
    BoundedCancellationRegistry,
    CleanupFailure,
    OrchestratorCancelled,
    ParentDeathProtectionError,
    arm_parent_death_kill,
)


def test_non_linux_parent_death_mode_is_explicitly_fail_closed() -> None:
    if platform.system() == "Linux":
        code = (
            "import os\n"
            "from resource_envelope_study.orchestration_guard import arm_parent_death_kill\n"
            "guard = arm_parent_death_kill(expected_parent_pid=os.getppid(), required=True)\n"
            "assert guard.parent_pid == os.getppid()\n"
            "assert guard.death_signal == 9\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=Path(__file__).parents[2],
            check=False,
            timeout=5.0,
        )
        assert completed.returncode == 0
    else:
        assert arm_parent_death_kill(required=False) is None
        with pytest.raises(ParentDeathProtectionError, match="not Linux"):
            arm_parent_death_kill(required=True)


@pytest.mark.skipif(platform.system() != "Linux", reason="requires Linux prctl")
def test_parent_pid_mismatch_hard_kills_child() -> None:
    code = (
        "import os\n"
        "from resource_envelope_study.orchestration_guard import arm_parent_death_kill\n"
        "arm_parent_death_kill(expected_parent_pid=os.getppid()+1000, required=True)\n"
        "raise SystemExit(99)\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).parents[2],
        check=False,
        timeout=5.0,
    )
    assert completed.returncode == -signal.SIGKILL


def _linux_process_is_gone_or_zombie(pid: int) -> bool:
    stat_path = Path(f"/proc/{pid}/stat")
    try:
        fields = stat_path.read_text(encoding="ascii").split()
    except FileNotFoundError:
        return True
    if len(fields) >= 3 and fields[2] in {"Z", "X"}:
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


@pytest.mark.skipif(platform.system() != "Linux", reason="requires Linux prctl")
def test_armed_child_dies_when_its_parent_exits(tmp_path: Path) -> None:
    ready_path = tmp_path / "guarded-child.pid"
    child_code = (
        "import os, pathlib, sys, time\n"
        "from resource_envelope_study.orchestration_guard import arm_parent_death_kill\n"
        "arm_parent_death_kill(expected_parent_pid=os.getppid(), required=True)\n"
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()), encoding='ascii')\n"
        "while True: time.sleep(0.05)\n"
    )
    parent_code = (
        "import pathlib, subprocess, sys, time\n"
        "ready = pathlib.Path(sys.argv[1])\n"
        "subprocess.Popen([sys.executable, '-c', sys.argv[2], str(ready)])\n"
        "deadline = time.monotonic() + 5\n"
        "while not ready.exists() and time.monotonic() < deadline: time.sleep(0.01)\n"
        "if not ready.exists(): raise SystemExit(4)\n"
    )
    parent = subprocess.Popen(
        [sys.executable, "-c", parent_code, str(ready_path), child_code],
        cwd=Path(__file__).parents[2],
    )
    parent.wait(timeout=7.0)
    assert parent.returncode == 0
    child_pid = int(ready_path.read_text(encoding="ascii"))
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not _linux_process_is_gone_or_zombie(
        child_pid
    ):
        time.sleep(0.02)
    try:
        assert _linux_process_is_gone_or_zombie(child_pid)
    finally:
        if not _linux_process_is_gone_or_zombie(child_pid):
            os.kill(child_pid, signal.SIGKILL)


def test_sigterm_requests_cancellation_and_runs_cleanup_before_propagating() -> None:
    events: list[str] = []
    previous = signal.getsignal(signal.SIGTERM)
    with pytest.raises(OrchestratorCancelled) as caught:
        with BoundedCancellationRegistry(cleanup_timeout_seconds=1.0) as registry:
            registry.register(lambda: events.append("cleanup"), name="append")
            os.kill(os.getpid(), signal.SIGTERM)
            raise AssertionError("signal handler should interrupt the body")
    assert events == ["cleanup"]
    assert caught.value.signal_number == signal.SIGTERM
    assert caught.value.cleanup_report[0].status == "completed"
    assert signal.getsignal(signal.SIGTERM) == previous


def test_cleanup_is_lifo_and_idempotent() -> None:
    events: list[str] = []
    registry = BoundedCancellationRegistry(cleanup_timeout_seconds=1.0)
    with registry:
        registry.register(lambda: events.append("first"), name="first")
        token = registry.register(lambda: events.append("removed"), name="removed")
        registry.register(lambda: events.append("last"), name="last")
        assert registry.unregister(token)
    assert events == ["last", "first"]
    assert registry.run_cleanup() == registry.cleanup_results
    assert events == ["last", "first"]


def test_hanging_cleanup_is_bounded_and_other_handlers_still_run() -> None:
    never = threading.Event()
    events: list[str] = []
    started = time.monotonic()
    with pytest.raises(CleanupFailure) as caught:
        with BoundedCancellationRegistry(cleanup_timeout_seconds=0.15) as registry:
            registry.register(
                lambda: never.wait(),
                name="hang",
                timeout_seconds=0.05,
            )
            registry.register(lambda: events.append("stopped"), name="stop-child")
    elapsed = time.monotonic() - started
    assert elapsed < 0.75
    assert events == ["stopped"]
    by_name = {result.name: result for result in caught.value.results}
    assert by_name["stop-child"].status == "completed"
    assert by_name["hang"].status == "timed_out"


def test_cleanup_errors_are_reported_without_skipping_later_callbacks() -> None:
    events: list[str] = []

    def fail() -> None:
        raise RuntimeError("cleanup broke")

    with pytest.raises(CleanupFailure) as caught:
        with BoundedCancellationRegistry(cleanup_timeout_seconds=1.0) as registry:
            registry.register(lambda: events.append("earlier"), name="earlier")
            registry.register(fail, name="failure")
    assert events == ["earlier"]
    by_name = {result.name: result for result in caught.value.results}
    assert by_name["failure"].status == "error"
    assert by_name["failure"].error == "RuntimeError: cleanup broke"
    assert by_name["earlier"].status == "completed"


@pytest.mark.parametrize("value", [True, 0, -1, math.nan, math.inf, -math.inf])
def test_cleanup_timeout_requires_exact_finite_positive_number(value: object) -> None:
    with pytest.raises(ValueError, match="finite positive number"):
        BoundedCancellationRegistry(cleanup_timeout_seconds=value)  # type: ignore[arg-type]


def test_manual_cancellation_is_visible_to_polling_orchestrators() -> None:
    with BoundedCancellationRegistry(cleanup_timeout_seconds=1.0) as registry:
        registry.request_cancellation(signal.SIGINT)
        assert registry.is_cancelled
        with pytest.raises(OrchestratorCancelled) as caught:
            registry.raise_if_cancelled()
        assert caught.value.signal_number == signal.SIGINT
