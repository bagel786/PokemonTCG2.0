"""OS-level child containment and bounded orchestrator cancellation.

Child entrypoints can arm Linux ``PR_SET_PDEATHSIG`` before doing any work.
The orchestrator registry converts SIGINT/SIGTERM into structured cancellation,
runs registered cleanup callbacks within one wall-clock budget, and reports any
callback that failed or exceeded its individual share of that budget.
"""

from __future__ import annotations

import ctypes
import math
import os
import platform
import signal
import threading
import time
from dataclasses import dataclass
from types import FrameType
from typing import Any, Callable, Literal


PR_SET_PDEATHSIG = 1


class ParentDeathProtectionError(RuntimeError):
    """The requested kernel parent-death guarantee could not be installed."""


@dataclass(frozen=True)
class ParentDeathProtection:
    parent_pid: int
    death_signal: int


def _exact_positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{label} must be an exact positive integer")
    return value


def _hard_fail_parent_race() -> None:
    """Uncatchably stop a child whose intended parent is already gone."""

    try:
        os.kill(os.getpid(), signal.SIGKILL)
    finally:  # pragma: no cover - SIGKILL cannot return on a conforming kernel
        os._exit(128 + int(signal.SIGKILL))


def arm_parent_death_kill(
    *,
    expected_parent_pid: int | None = None,
    required: bool = True,
) -> ParentDeathProtection | None:
    """Arm Linux to SIGKILL this process when its current parent exits.

    This function must be called at the very start of the child entrypoint.
    Passing the PID captured by the parent before launch closes the race where
    the parent dies before the child calls ``prctl``.  A parent mismatch before
    or after ``prctl`` hard-kills the child, because returning an error could be
    caught accidentally and leave unowned load running.

    On non-Linux systems, ``required=True`` raises before work can begin;
    ``required=False`` returns ``None``.
    """

    if type(required) is not bool:
        raise ValueError("required must be an exact bool")
    expected = (
        None
        if expected_parent_pid is None
        else _exact_positive_int(expected_parent_pid, "expected_parent_pid")
    )
    if platform.system() != "Linux":
        if required:
            raise ParentDeathProtectionError(
                "PR_SET_PDEATHSIG is required but this host is not Linux"
            )
        return None

    parent_before = os.getppid()
    if parent_before <= 1 or (expected is not None and parent_before != expected):
        _hard_fail_parent_race()

    libc = ctypes.CDLL(None, use_errno=True)
    try:
        prctl = libc.prctl
    except AttributeError as exc:
        if required:
            raise ParentDeathProtectionError("libc does not expose prctl") from exc
        return None
    prctl.argtypes = [
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
    ]
    prctl.restype = ctypes.c_int
    result = prctl(PR_SET_PDEATHSIG, int(signal.SIGKILL), 0, 0, 0)
    if result != 0:
        error_number = ctypes.get_errno()
        if required:
            raise ParentDeathProtectionError(
                f"prctl(PR_SET_PDEATHSIG) failed: errno={error_number} "
                f"({os.strerror(error_number)})"
            )
        return None

    parent_after = os.getppid()
    if (
        parent_after <= 1
        or parent_after != parent_before
        or (expected is not None and parent_after != expected)
    ):
        _hard_fail_parent_race()
    return ParentDeathProtection(
        parent_pid=parent_after,
        death_signal=int(signal.SIGKILL),
    )


class OrchestratorCancelled(BaseException):
    """Raised in the main thread after SIGINT or SIGTERM requests shutdown."""

    def __init__(self, signal_number: int) -> None:
        self.signal_number = int(signal_number)
        self.cleanup_report: tuple[CleanupResult, ...] = ()
        super().__init__(f"orchestrator cancelled by signal {self.signal_number}")


CleanupStatus = Literal["completed", "error", "timed_out", "budget_exhausted"]


@dataclass(frozen=True)
class CleanupResult:
    name: str
    status: CleanupStatus
    elapsed_seconds: float
    error: str | None = None


class CleanupFailure(RuntimeError):
    """One or more cleanup callbacks failed to finish cleanly."""

    def __init__(self, results: tuple[CleanupResult, ...]) -> None:
        self.results = results
        failures = [result for result in results if result.status != "completed"]
        detail = ", ".join(f"{item.name}:{item.status}" for item in failures)
        super().__init__(f"bounded cleanup was incomplete: {detail}")


@dataclass(frozen=True)
class _CleanupEntry:
    token: int
    name: str
    callback: Callable[[], Any]
    timeout_seconds: float | None


def _finite_positive_float(value: Any, label: str) -> float:
    if type(value) not in {int, float}:
        raise ValueError(f"{label} must be a finite positive number")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{label} must be a finite positive number")
    return result


class BoundedCancellationRegistry:
    """Context manager for signal-driven, bounded LIFO cleanup.

    Callbacks should still implement their own strongest cleanup semantics
    (for example terminate-then-kill).  The registry adds an outer wall-clock
    bound so a defective callback cannot indefinitely trap the orchestrator.
    Timed-out callback threads are daemons and are reported as failures.
    """

    def __init__(
        self,
        *,
        cleanup_timeout_seconds: float = 15.0,
        raise_on_cleanup_failure: bool = True,
    ) -> None:
        self.cleanup_timeout_seconds = _finite_positive_float(
            cleanup_timeout_seconds, "cleanup_timeout_seconds"
        )
        if type(raise_on_cleanup_failure) is not bool:
            raise ValueError("raise_on_cleanup_failure must be an exact bool")
        self.raise_on_cleanup_failure = raise_on_cleanup_failure
        self.cancel_event = threading.Event()
        self._lock = threading.RLock()
        self._entries: list[_CleanupEntry] = []
        self._next_token = 1
        self._entered = False
        self._closed = False
        self._cleaning = False
        self._signal_raised = False
        self._signal_number: int | None = None
        self._cancel_requested_monotonic: float | None = None
        self._previous_handlers: dict[int, Any] = {}
        self._cleanup_results: tuple[CleanupResult, ...] | None = None

    @property
    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()

    @property
    def signal_number(self) -> int | None:
        return self._signal_number

    @property
    def cleanup_results(self) -> tuple[CleanupResult, ...] | None:
        return self._cleanup_results

    def register(
        self,
        callback: Callable[[], Any],
        *,
        name: str | None = None,
        timeout_seconds: float | None = None,
    ) -> int:
        if not callable(callback):
            raise TypeError("cleanup callback must be callable")
        callback_name = name or getattr(callback, "__name__", "cleanup")
        if type(callback_name) is not str or not callback_name:
            raise ValueError("cleanup callback name must be a nonempty string")
        timeout = (
            None
            if timeout_seconds is None
            else _finite_positive_float(timeout_seconds, "timeout_seconds")
        )
        with self._lock:
            if self._closed or self._cleaning:
                raise RuntimeError("cleanup registry is already closing")
            token = self._next_token
            self._next_token += 1
            self._entries.append(
                _CleanupEntry(
                    token=token,
                    name=callback_name,
                    callback=callback,
                    timeout_seconds=timeout,
                )
            )
            return token

    def unregister(self, token: int) -> bool:
        token_value = _exact_positive_int(token, "token")
        with self._lock:
            if self._cleaning:
                return False
            for index, entry in enumerate(self._entries):
                if entry.token == token_value:
                    del self._entries[index]
                    return True
        return False

    def request_cancellation(self, reason_signal: int = signal.SIGTERM) -> None:
        if isinstance(reason_signal, signal.Signals):
            signal_value = int(reason_signal)
        else:
            signal_value = _exact_positive_int(reason_signal, "reason_signal")
        with self._lock:
            self.cancel_event.set()
            if self._cancel_requested_monotonic is None:
                self._cancel_requested_monotonic = time.monotonic()
            if self._signal_number is None:
                self._signal_number = signal_value

    def raise_if_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise OrchestratorCancelled(self._signal_number or int(signal.SIGTERM))

    def _handle_signal(self, signum: int, frame: FrameType | None) -> None:
        del frame
        with self._lock:
            self.cancel_event.set()
            if self._cancel_requested_monotonic is None:
                self._cancel_requested_monotonic = time.monotonic()
            if self._signal_number is None:
                self._signal_number = int(signum)
            if self._cleaning or self._signal_raised:
                return
            self._signal_raised = True
        raise OrchestratorCancelled(signum)

    def __enter__(self) -> "BoundedCancellationRegistry":
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("signal registry must be entered in the main thread")
        with self._lock:
            if self._entered or self._closed:
                raise RuntimeError("cleanup registry cannot be reused")
            self._entered = True
            try:
                for signum in (signal.SIGINT, signal.SIGTERM):
                    self._previous_handlers[int(signum)] = signal.getsignal(signum)
                    signal.signal(signum, self._handle_signal)
            except BaseException:
                self._restore_handlers()
                self._entered = False
                raise
        return self

    def _restore_handlers(self) -> None:
        for signum, handler in self._previous_handlers.items():
            signal.signal(signum, handler)
        self._previous_handlers.clear()

    @staticmethod
    def _run_one(entry: _CleanupEntry, holder: dict[str, Any]) -> None:
        try:
            entry.callback()
        except BaseException as exc:  # cleanup must report even SystemExit/KeyboardInterrupt
            holder["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            holder["finished"] = True

    def run_cleanup(self) -> tuple[CleanupResult, ...]:
        with self._lock:
            if self._cleanup_results is not None:
                return self._cleanup_results
            self._cleaning = True
            entries = list(reversed(self._entries))
            cancellation_started = self._cancel_requested_monotonic
        now = time.monotonic()
        deadline = now + self.cleanup_timeout_seconds
        if cancellation_started is not None:
            deadline = min(
                deadline, cancellation_started + self.cleanup_timeout_seconds
            )
        results: list[CleanupResult] = []
        for entry in entries:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                results.append(
                    CleanupResult(
                        name=entry.name,
                        status="budget_exhausted",
                        elapsed_seconds=0.0,
                    )
                )
                continue
            callback_budget = (
                remaining
                if entry.timeout_seconds is None
                else min(remaining, entry.timeout_seconds)
            )
            holder: dict[str, Any] = {"finished": False, "error": None}
            started = time.monotonic()
            worker = threading.Thread(
                target=self._run_one,
                args=(entry, holder),
                name=f"bounded-cleanup-{entry.token}-{entry.name}",
                daemon=True,
            )
            worker.start()
            worker.join(callback_budget)
            elapsed = time.monotonic() - started
            if worker.is_alive():
                status: CleanupStatus = "timed_out"
                error = None
            elif holder["error"] is not None:
                status = "error"
                error = str(holder["error"])
            else:
                status = "completed"
                error = None
            results.append(
                CleanupResult(
                    name=entry.name,
                    status=status,
                    elapsed_seconds=elapsed,
                    error=error,
                )
            )
        result_tuple = tuple(results)
        with self._lock:
            self._cleanup_results = result_tuple
            self._closed = True
        return result_tuple

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        del traceback
        try:
            results = self.run_cleanup()
        finally:
            self._restore_handlers()
        if isinstance(exc, OrchestratorCancelled):
            exc.cleanup_report = results
            return False
        failed = any(result.status != "completed" for result in results)
        if exc_type is None and failed and self.raise_on_cleanup_failure:
            raise CleanupFailure(results)
        return False
