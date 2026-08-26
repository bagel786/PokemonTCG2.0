"""Controlled, external CPU co-runner intervention.

The confirmatory Linux configuration pins the benchmark and one co-runner to
the same frozen logical CPU.  Idle means that the study launches no co-runner;
it does not assert an otherwise quiescent operating system.  Every episode is
independently spawned and identified by its frozen load seed.
"""

from __future__ import annotations

import math
import multiprocessing as mp
import os
import platform
import queue
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .orchestration_guard import arm_parent_death_kill
from .process_safety import stop_process


@dataclass(frozen=True)
class LoadProfile:
    condition: str
    worker_count: int
    target_cpus: tuple[int, ...]
    chunk_iterations: int = 50_000
    readiness_timeout_s: float = 15.0

    def validate(self) -> None:
        if self.condition not in {"idle", "loaded"}:
            raise ValueError("load condition must be idle or loaded")
        expected = 0 if self.condition == "idle" else self.worker_count
        if expected != self.worker_count or self.worker_count < 0:
            raise ValueError("idle must use zero workers and loaded must use positive workers")
        if self.condition == "loaded" and self.worker_count <= 0:
            raise ValueError("loaded profile requires at least one worker")
        if not self.target_cpus or any(cpu < 0 for cpu in self.target_cpus):
            raise ValueError("at least one non-negative target CPU is required")
        if self.chunk_iterations <= 0:
            raise ValueError("chunk_iterations must be positive")


def _set_affinity(cpus: tuple[int, ...]) -> bool:
    if not hasattr(os, "sched_setaffinity"):
        return False
    os.sched_setaffinity(0, set(cpus))
    return True


def _observed_affinity(pid: int = 0) -> list[int] | None:
    if not hasattr(os, "sched_getaffinity"):
        return None
    return sorted(int(cpu) for cpu in os.sched_getaffinity(pid))


def _linux_process_cpu_ticks(pid: int) -> int | None:
    """Return user+system ticks without sampling the benchmark's own clocks."""

    stat_path = Path(f"/proc/{int(pid)}/stat")
    try:
        fields = stat_path.read_text(encoding="ascii").rsplit(")", 1)[1].split()
        # The split suffix starts at proc(5) field 3; utime/stime are 14/15.
        return int(fields[11]) + int(fields[12])
    except (IndexError, OSError, ValueError):
        return None


def _burn_worker(
    stop_event: Any,
    ready_queue: Any,
    target_cpus: tuple[int, ...],
    seed: int,
    chunk_iterations: int,
    expected_parent_pid: int,
    require_parent_death: bool,
) -> None:
    parent_guard = arm_parent_death_kill(
        expected_parent_pid=expected_parent_pid,
        required=require_parent_death,
    )
    affinity_applied = False
    try:
        affinity_applied = _set_affinity(target_cpus)
        # Integer recurrence keeps the worker CPU-bound without invoking BLAS,
        # filesystem, network, or a second RNG stream.
        word = (int(seed) | 1) & 0xFFFF_FFFF_FFFF_FFFF
        pid = os.getpid()
        ready_queue.put(
            {
                "pid": pid,
                "affinity_applied": affinity_applied,
                "observed_affinity": _observed_affinity(),
                "cpu_ticks_start": _linux_process_cpu_ticks(pid),
                "parent_death_kill_armed": parent_guard is not None,
            }
        )
        while not stop_event.is_set():
            for _ in range(chunk_iterations):
                word ^= (word << 13) & 0xFFFF_FFFF_FFFF_FFFF
                word ^= word >> 7
                word ^= (word << 17) & 0xFFFF_FFFF_FFFF_FFFF
        # Keep recurrence observable to the interpreter.
        if word == -1:  # pragma: no cover - impossible sentinel
            raise RuntimeError("unreachable")
    except BaseException as exc:
        try:
            ready_queue.put({"pid": os.getpid(), "error": f"{type(exc).__name__}: {exc}"})
        finally:
            raise


def system_snapshot() -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "logical_cpu_count": os.cpu_count(),
        "pid": os.getpid(),
        "loadavg": list(os.getloadavg()) if hasattr(os, "getloadavg") else None,
        "affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
    }
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        for line in meminfo.read_text().splitlines():
            if line.startswith("MemTotal:"):
                snapshot["memory_total_kib"] = int(line.split()[1])
                break
    frequencies: list[int] = []
    for path in sorted(Path("/sys/devices/system/cpu").glob("cpu[0-9]*/cpufreq/scaling_cur_freq")):
        try:
            frequencies.append(int(path.read_text().strip()))
        except (OSError, ValueError):
            pass
    snapshot["cpu_frequency_khz"] = frequencies or None
    temperatures: list[float] = []
    for path in sorted(Path("/sys/class/thermal").glob("thermal_zone*/temp")):
        try:
            temperatures.append(float(path.read_text().strip()) / 1000.0)
        except (OSError, ValueError):
            pass
    snapshot["temperature_c"] = temperatures or None
    return snapshot


class ResourceEnvelope:
    """Context manager for benchmark affinity and an external load episode."""

    def __init__(
        self,
        profile: LoadProfile,
        load_seed: int,
        load_batch_id: str,
        *,
        require_affinity: bool = False,
    ):
        profile.validate()
        self.profile = profile
        self.load_seed = int(load_seed)
        self.load_batch_id = str(load_batch_id)
        self.require_affinity = bool(require_affinity)
        self._processes: list[Any] = []
        self._stop_event: Any | None = None
        self._previous_affinity: set[int] | None = None
        self._orchestrator_cpus: tuple[int, ...] | None = None
        self._closed = False
        self._cleanup_errors: list[str] = []
        self.metadata: dict[str, Any] = {}

    def __enter__(self) -> "ResourceEnvelope":
        if self.require_affinity and platform.system() != "Linux":
            raise RuntimeError("scientific acquisition requires Linux CPU affinity")
        cpu_count = os.cpu_count()
        if cpu_count is not None and any(cpu >= cpu_count for cpu in self.profile.target_cpus):
            raise ValueError(
                f"target CPUs {self.profile.target_cpus} exceed logical CPU count {cpu_count}"
            )
        before = system_snapshot()
        if hasattr(os, "sched_getaffinity"):
            self._previous_affinity = set(os.sched_getaffinity(0))
            unavailable = set(self.profile.target_cpus) - self._previous_affinity
            if unavailable:
                raise RuntimeError(
                    f"target CPUs are outside the authorized affinity set: {sorted(unavailable)}"
                )
            complement = self._previous_affinity - set(self.profile.target_cpus)
            if self.require_affinity and not complement:
                raise RuntimeError(
                    "scientific acquisition requires at least one non-target orchestrator CPU"
                )
            self._orchestrator_cpus = tuple(sorted(complement or self._previous_affinity))
        orchestrator_affinity_applied = (
            _set_affinity(self._orchestrator_cpus)
            if self._orchestrator_cpus is not None
            else False
        )
        observed_orchestrator_affinity = _observed_affinity()
        if self.require_affinity and (
            not orchestrator_affinity_applied
            or observed_orchestrator_affinity != list(self._orchestrator_cpus or ())
        ):
            if self._previous_affinity is not None and hasattr(os, "sched_setaffinity"):
                os.sched_setaffinity(0, self._previous_affinity)
            raise RuntimeError(
                "orchestrator affinity was not applied exactly: "
                f"requested={list(self._orchestrator_cpus or ())}, "
                f"observed={observed_orchestrator_affinity}"
            )
        self.metadata = {
            "schema_version": "resource-episode-1.0.0",
            "load_batch_id": self.load_batch_id,
            "load_seed": self.load_seed,
            "profile": asdict(self.profile),
            "orchestrator_affinity_applied": orchestrator_affinity_applied,
            "orchestrator_pid": os.getpid(),
            "orchestrator_target_cpus": list(self._orchestrator_cpus or ()),
            "orchestrator_observed_affinity": observed_orchestrator_affinity,
            "benchmark_target_cpus": list(self.profile.target_cpus),
            "before": before,
            "workers": [],
            "benchmark_workers": [],
            "clock_ticks_per_second": (
                int(os.sysconf("SC_CLK_TCK")) if hasattr(os, "sysconf") else None
            ),
            "started_monotonic_ns": time.monotonic_ns(),
        }
        if self.profile.condition == "idle":
            return self

        context = mp.get_context("spawn")
        self._stop_event = context.Event()
        ready_queue = context.Queue()
        try:
            for index in range(self.profile.worker_count):
                process = context.Process(
                    target=_burn_worker,
                    args=(
                        self._stop_event,
                        ready_queue,
                        self.profile.target_cpus,
                        self.load_seed + index * 1_000_003,
                        self.profile.chunk_iterations,
                        os.getpid(),
                        self.require_affinity,
                    ),
                    name=f"resource-load-{self.load_batch_id}-{index}",
                )
                try:
                    process.start()
                except BaseException:
                    # Some multiprocessing failures occur after a PID has been
                    # allocated.  Retain that handle so cleanup can still kill
                    # the partially started child.
                    if process.pid is not None:
                        self._processes.append(process)
                    raise
                self._processes.append(process)
            deadline = time.monotonic() + self.profile.readiness_timeout_s
            while len(self.metadata["workers"]) < self.profile.worker_count:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("CPU co-runner readiness timeout")
                try:
                    message = ready_queue.get(timeout=remaining)
                except queue.Empty as exc:
                    raise TimeoutError("CPU co-runner readiness timeout") from exc
                if "error" in message:
                    raise RuntimeError(f"CPU co-runner failed: {message['error']}")
                if self.require_affinity and (
                    not message.get("affinity_applied")
                    or message.get("parent_death_kill_armed") is not True
                    or message.get("observed_affinity")
                    != sorted(self.profile.target_cpus)
                ):
                    raise RuntimeError(
                        "CPU co-runner affinity was not applied exactly: "
                        f"requested={list(self.profile.target_cpus)}, "
                        f"observed={message.get('observed_affinity')}"
                    )
                self.metadata["workers"].append(message)
            if any(not process.is_alive() for process in self._processes):
                raise RuntimeError("CPU co-runner exited during startup")
            return self
        except BaseException:
            # Cleanup errors are intentionally allowed to supersede the
            # startup error: an un-killed child is the stronger safety failure.
            self.close()
            raise
        finally:
            ready_queue.close()
            ready_queue.join_thread()

    def record_benchmark_worker(self, runtime: dict[str, Any]) -> None:
        """Attach observed child-process identity and CPU evidence to the episode."""

        self.metadata.setdefault("benchmark_workers", []).append(dict(runtime))

    def assert_compliant(self, *, period_complete: bool = False) -> None:
        if self._closed:
            raise RuntimeError("resource envelope is already closed")
        observed = _observed_affinity()
        self.metadata["orchestrator_observed_affinity_latest"] = observed
        if self.require_affinity and observed != list(self._orchestrator_cpus or ()):
            raise RuntimeError(
                "orchestrator affinity changed during episode: "
                f"requested={list(self._orchestrator_cpus or ())}, observed={observed}"
            )
        if self.profile.condition == "loaded":
            dead = [process.pid for process in self._processes if not process.is_alive()]
            if dead:
                raise RuntimeError(f"CPU co-runner died during episode: {dead}")
            no_progress: list[int] = []
            workers_by_pid = {
                int(worker["pid"]): worker for worker in self.metadata.get("workers", [])
            }
            for process in self._processes:
                pid = int(process.pid)
                latest = _linux_process_cpu_ticks(pid)
                worker = workers_by_pid[pid]
                worker["cpu_ticks_latest"] = latest
                start = worker.get("cpu_ticks_start")
                worker["cpu_ticks_delta"] = (
                    None if start is None or latest is None else int(latest) - int(start)
                )
                if period_complete and (
                    worker["cpu_ticks_delta"] is None or worker["cpu_ticks_delta"] <= 0
                ):
                    no_progress.append(pid)
            if no_progress:
                raise RuntimeError(
                    f"CPU co-runner lacks positive CPU-time evidence: {no_progress}"
                )

    def close(self) -> None:
        if self._closed and not self._processes:
            return
        self._closed = True
        if self._processes:
            workers_by_pid = {
                int(worker["pid"]): worker for worker in self.metadata.get("workers", [])
            }
            for process in self._processes:
                pid = int(process.pid)
                final_ticks = _linux_process_cpu_ticks(pid)
                worker = workers_by_pid.get(pid, {})
                worker["cpu_ticks_before_stop"] = final_ticks
                start = worker.get("cpu_ticks_start")
                worker["cpu_ticks_delta"] = (
                    None if start is None or final_ticks is None else int(final_ticks) - int(start)
                )
            if self._stop_event is None:
                self._cleanup_errors.append("CPU co-runner stop event was never initialized")
            else:
                try:
                    self._stop_event.set()
                except BaseException as exc:
                    self._cleanup_errors.append(
                        f"CPU co-runner cooperative stop failed: {type(exc).__name__}: {exc}"
                    )
            for process in self._processes:
                try:
                    process.join(timeout=5.0)
                except BaseException as exc:
                    self._cleanup_errors.append(
                        f"CPU co-runner initial join failed for PID {process.pid}: "
                        f"{type(exc).__name__}: {exc}"
                    )
            survivors: list[Any] = []
            for process in self._processes:
                if process.is_alive():
                    try:
                        disposition = stop_process(
                            process,
                            terminate_timeout_s=2.0,
                            kill_timeout_s=2.0,
                        )
                        workers_by_pid.setdefault(int(process.pid), {})[
                            "stop_disposition"
                        ] = disposition
                    except BaseException as exc:
                        self._cleanup_errors.append(
                            f"CPU co-runner shutdown failed for PID {process.pid}: "
                            f"{type(exc).__name__}: {exc}"
                        )
                if process.is_alive():
                    survivors.append(process)
            exitcodes = {str(process.pid): process.exitcode for process in self._processes}
            self.metadata["worker_exitcodes"] = exitcodes
            self.metadata["surviving_worker_pids"] = [
                int(process.pid) for process in survivors
            ]
            nonzero = [pid for pid, code in exitcodes.items() if code != 0]
            if nonzero:
                self._cleanup_errors.append(
                    f"CPU co-runner nonzero exit codes: "
                    f"{ {pid: exitcodes[pid] for pid in nonzero} }"
                )
            # Dead handles can be released.  Live handles are deliberately
            # retained so a caller/debugger can retry or inspect them; never
            # report a closed envelope with an untracked worker.
            self._processes = survivors
        if self._previous_affinity is not None and hasattr(os, "sched_setaffinity"):
            try:
                os.sched_setaffinity(0, self._previous_affinity)
            except BaseException as exc:
                self._cleanup_errors.append(
                    f"orchestrator affinity restoration failed: {type(exc).__name__}: {exc}"
                )
        if self.metadata:
            self.metadata["finished_monotonic_ns"] = time.monotonic_ns()
            self.metadata["after"] = system_snapshot()
            self.metadata["cleanup_errors"] = list(self._cleanup_errors)
            self.metadata["cleanup_succeeded"] = not self._cleanup_errors
        if self._cleanup_errors:
            raise RuntimeError("; ".join(self._cleanup_errors))

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
