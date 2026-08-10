"""Runtime enforcement for compute-heavy Azure-only workloads."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Iterable, Mapping


HARD_INCREMENTAL_SPEND_CAP_USD = 100.0


def is_azure_host(env: dict[str, str] | None = None, vendor_path: str | Path = "/sys/class/dmi/id/sys_vendor") -> bool:
    env = os.environ if env is None else env
    if env.get("PTCG_AZURE_RUN") != "1":
        return False
    try:
        vendor = Path(vendor_path).read_text().strip().lower()
    except OSError:
        return False
    return "microsoft" in vendor


def enforce_azure_workload(
    *,
    allow_local_smoke: bool = False,
    workload_size: int = 0,
    maximum_local_smoke: int = 200,
    env: dict[str, str] | None = None,
    vendor_path: str | Path = "/sys/class/dmi/id/sys_vendor",
) -> str:
    if is_azure_host(env, vendor_path):
        return "azure"
    if allow_local_smoke and workload_size <= maximum_local_smoke:
        return "local_smoke"
    raise RuntimeError(
        "RL workloads are Azure-only. Run on the configured Azure VM with "
        "PTCG_AZURE_RUN=1; local execution is limited to an explicit <=200-item smoke."
    )


def _worker_key(worker: Mapping[str, object]) -> str:
    group = worker.get("rg", worker.get("resource_group"))
    name = worker.get("name")
    if not group or not name:
        raise ValueError("each Azure worker requires rg/resource_group and name")
    return f"{group}/{name}"


def synchronous_azure_deallocator(
    azure_cli: str,
    *,
    cwd: str | Path | None = None,
    timeout_seconds: int = 900,
) -> Callable[[Mapping[str, object]], subprocess.CompletedProcess]:
    """Build a deallocator that waits for Azure to finish the operation."""

    def deallocate(worker: Mapping[str, object]) -> subprocess.CompletedProcess:
        group = str(worker.get("rg", worker.get("resource_group")))
        return subprocess.run(
            [azure_cli, "vm", "deallocate", "-g", group, "-n", str(worker["name"])],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )

    return deallocate


class AzureRunSafety:
    """Hard budget gate plus fail-safe, audited VM deallocation.

    Call ``mark_start_requested`` immediately before each VM start command and
    reserve worst-case worker-seconds before every bounded remote job.  Exiting
    the context synchronously deallocates *all* configured workers, including a
    worker whose start command failed after Azure accepted the request.
    """

    def __init__(
        self,
        *,
        workers: Iterable[Mapping[str, object]],
        manifest_path: str | Path,
        rate_usd_per_worker_hour: float,
        deallocate_worker: Callable[[Mapping[str, object]], object],
        spend_cap_usd: float = HARD_INCREMENTAL_SPEND_CAP_USD,
        prior_incremental_spend_usd: float = 0.0,
        clock: Callable[[], float] = time.time,
        deallocation_attempts: int = 2,
    ) -> None:
        if not 0 < float(spend_cap_usd) <= HARD_INCREMENTAL_SPEND_CAP_USD:
            raise ValueError(
                f"incremental spend cap must be in (0, ${HARD_INCREMENTAL_SPEND_CAP_USD:.2f}]"
            )
        if float(rate_usd_per_worker_hour) <= 0:
            raise ValueError("worker hourly rate must be positive")
        if not 0 <= float(prior_incremental_spend_usd) < float(spend_cap_usd):
            raise ValueError("prior incremental spend must be nonnegative and below the cap")
        self.workers = [dict(worker) for worker in workers]
        if not self.workers:
            raise ValueError("at least one Azure worker is required")
        keys = [_worker_key(worker) for worker in self.workers]
        if len(set(keys)) != len(keys):
            raise ValueError("Azure workers must be unique")
        self._workers_by_key = dict(zip(keys, self.workers))
        self.manifest_path = Path(manifest_path)
        self.rate_usd_per_worker_hour = float(rate_usd_per_worker_hour)
        self.spend_cap_usd = float(spend_cap_usd)
        self.prior_incremental_spend_usd = float(prior_incremental_spend_usd)
        self._deallocate_worker = deallocate_worker
        self._clock = clock
        self._deallocation_attempts = max(1, int(deallocation_attempts))
        self._lock = threading.RLock()
        self._entered_unix: float | None = None
        self._ended_unix: float | None = None
        self._start_requested: dict[str, float] = {}
        self._stop_times: dict[str, float] = {}
        self._reservations: dict[int, dict] = {}
        self._next_reservation = 1
        self._deallocation: dict[str, dict] = {}
        self._status = "created"
        self._error: str | None = None
        self._closed = False

    def __enter__(self) -> "AzureRunSafety":
        with self._lock:
            if self._entered_unix is not None:
                raise RuntimeError("AzureRunSafety cannot be entered twice")
            self._entered_unix = float(self._clock())
            self._status = "running"
            self._write_manifest_locked()
        return self

    def mark_start_requested(self, worker: Mapping[str, object]) -> None:
        """Begin measured cost before issuing ``az vm start`` (fail closed)."""

        key = _worker_key(worker)
        with self._lock:
            if key not in self._workers_by_key:
                raise KeyError(f"worker is outside guarded scope: {key}")
            if self._entered_unix is None or self._closed:
                raise RuntimeError("Azure safety guard is not active")
            self._start_requested.setdefault(key, float(self._clock()))
            self._write_manifest_locked()

    def _elapsed_worker_seconds_locked(self, now: float) -> float:
        total = 0.0
        for key, started in self._start_requested.items():
            stopped = self._stop_times.get(key, now)
            total += max(0.0, stopped - started)
        return total

    def elapsed_spend_estimate_usd(self) -> float:
        with self._lock:
            seconds = self._elapsed_worker_seconds_locked(float(self._clock()))
            return seconds / 3600.0 * self.rate_usd_per_worker_hour

    def projected_spend_usd(self, additional_worker_seconds: float = 0.0) -> float:
        with self._lock:
            now = float(self._clock())
            outstanding = sum(float(row["worker_seconds"]) for row in self._reservations.values())
            seconds = self._elapsed_worker_seconds_locked(now) + outstanding + max(
                0.0, float(additional_worker_seconds)
            )
            return self.prior_incremental_spend_usd + (
                seconds / 3600.0 * self.rate_usd_per_worker_hour
            )

    def reserve(self, *, worker_seconds: float, label: str) -> int:
        """Reserve a worst-case job duration atomically across worker threads."""

        if float(worker_seconds) <= 0:
            raise ValueError("worker_seconds must be positive")
        with self._lock:
            if self._entered_unix is None or self._closed:
                raise RuntimeError("Azure safety guard is not active")
            projected = self.projected_spend_usd(float(worker_seconds))
            if projected > self.spend_cap_usd:
                raise RuntimeError(
                    f"projected incremental Azure spend ${projected:.2f} exceeds "
                    f"hard ${self.spend_cap_usd:.2f} cap"
                )
            token = self._next_reservation
            self._next_reservation += 1
            self._reservations[token] = {
                "label": str(label),
                "worker_seconds": float(worker_seconds),
                "reserved_unix": float(self._clock()),
            }
            self._write_manifest_locked()
            return token

    def release(self, token: int) -> None:
        with self._lock:
            if token not in self._reservations:
                raise KeyError(f"unknown Azure budget reservation: {token}")
            del self._reservations[token]
            self._write_manifest_locked()

    @staticmethod
    def _command_result(result: object) -> tuple[bool, str | None]:
        returncode = getattr(result, "returncode", 0)
        if returncode in (None, 0):
            return True, None
        stderr = str(getattr(result, "stderr", "") or "").strip()
        return False, stderr or f"deallocation command returned {returncode}"

    def close(self, *, status: str = "complete", error: str | None = None) -> dict:
        with self._lock:
            if self._closed:
                return self.report()
            self._status = str(status)
            self._error = error

        # Never hold the budget lock while an Azure CLI operation blocks.
        for worker in self.workers:
            key = _worker_key(worker)
            attempts = []
            succeeded = False
            last_error = None
            for attempt in range(1, self._deallocation_attempts + 1):
                try:
                    result = self._deallocate_worker(worker)
                    succeeded, last_error = self._command_result(result)
                except Exception as exc:  # Continue so every VM is attempted.
                    succeeded = False
                    last_error = f"{type(exc).__name__}: {exc}"
                attempts.append({
                    "attempt": attempt,
                    "succeeded": succeeded,
                    "error": last_error,
                    "completed_unix": float(self._clock()),
                })
                if succeeded:
                    break
            completed = float(self._clock())
            with self._lock:
                self._stop_times[key] = completed
                self._deallocation[key] = {
                    "succeeded": succeeded,
                    "attempts": attempts,
                    "error": last_error,
                }

        with self._lock:
            self._ended_unix = float(self._clock())
            self._closed = True
            failures = [key for key, row in self._deallocation.items() if not row["succeeded"]]
            elapsed_estimate = self._elapsed_worker_seconds_locked(self._ended_unix)
            estimated_spend = elapsed_estimate / 3600.0 * self.rate_usd_per_worker_hour
            if failures:
                self._status = "deallocation_failed"
            if self.prior_incremental_spend_usd + estimated_spend > self.spend_cap_usd:
                self._status = "budget_exceeded"
            self._write_manifest_locked()
            return self._report_locked()

    def _report_locked(self) -> dict:
        now = self._ended_unix if self._ended_unix is not None else float(self._clock())
        worker_rows = []
        for key, worker in self._workers_by_key.items():
            started = self._start_requested.get(key)
            stopped = self._stop_times.get(key, now if started is not None else None)
            elapsed = 0.0 if started is None or stopped is None else max(0.0, stopped - started)
            worker_rows.append({
                "resource_group": worker.get("rg", worker.get("resource_group")),
                "name": worker.get("name"),
                "start_requested_unix": started,
                "cost_observation_ended_unix": stopped,
                "actual_elapsed_seconds": elapsed,
                "estimated_spend_usd": elapsed / 3600.0 * self.rate_usd_per_worker_hour,
                "deallocation": self._deallocation.get(key),
            })
        elapsed_seconds = sum(float(row["actual_elapsed_seconds"]) for row in worker_rows)
        estimate = elapsed_seconds / 3600.0 * self.rate_usd_per_worker_hour
        outstanding_seconds = sum(
            float(row["worker_seconds"]) for row in self._reservations.values()
        )
        combined_estimate = self.prior_incremental_spend_usd + estimate
        return {
            "schema_version": 1,
            "status": self._status,
            "error": self._error,
            "started_unix": self._entered_unix,
            "ended_unix": self._ended_unix,
            "hard_incremental_spend_cap_usd": self.spend_cap_usd,
            "prior_incremental_spend_usd": self.prior_incremental_spend_usd,
            "conservative_rate_usd_per_worker_hour": self.rate_usd_per_worker_hour,
            "actual_elapsed_worker_seconds": elapsed_seconds,
            "estimated_incremental_spend_usd": estimate,
            "combined_estimated_incremental_spend_usd": combined_estimate,
            "projected_with_outstanding_reservations_usd": combined_estimate + (
                outstanding_seconds / 3600.0 * self.rate_usd_per_worker_hour
            ),
            "billing_actual_usd": None,
            "spend_basis": "measured elapsed worker-seconds times conservative configured rate",
            "cap_compliant": combined_estimate <= self.spend_cap_usd,
            "outstanding_reservations": list(self._reservations.values()),
            "all_workers_deallocated": bool(self._deallocation) and all(
                bool(row["succeeded"]) for row in self._deallocation.values()
            ),
            "workers": worker_rows,
        }

    def report(self) -> dict:
        with self._lock:
            return self._report_locked()

    def _write_manifest_locked(self) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.manifest_path.with_name(self.manifest_path.name + ".tmp")
        temporary.write_text(json.dumps(self._report_locked(), indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(self.manifest_path)

    def __exit__(self, exc_type, exc, _traceback) -> bool:
        report = self.close(
            status="complete" if exc_type is None else "failed",
            error=None if exc is None else f"{exc_type.__name__}: {exc}",
        )
        if exc_type is None and not report["all_workers_deallocated"]:
            failed = [
                row["name"] for row in report["workers"]
                if not (row.get("deallocation") or {}).get("succeeded")
            ]
            raise RuntimeError(f"Azure worker deallocation failed: {failed}")
        return False
