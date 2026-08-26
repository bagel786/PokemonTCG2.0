"""Bounded, tested shutdown for study-owned child processes."""

from __future__ import annotations

from typing import Any, Literal


StopDisposition = Literal["already_stopped", "terminated", "killed"]


def stop_process(
    process: Any,
    *,
    terminate_timeout_s: float = 5.0,
    kill_timeout_s: float = 5.0,
) -> StopDisposition:
    """Stop one multiprocessing-compatible child, escalating to hard kill.

    The function never reports success while ``process.is_alive()`` remains
    true.  Scientific acquisition callers treat the final RuntimeError as an
    infrastructure-invalid batch and stop rather than abandoning an orphan.
    """

    if terminate_timeout_s < 0 or kill_timeout_s < 0:
        raise ValueError("process shutdown timeouts must be nonnegative")
    if not process.is_alive():
        try:
            process.join(timeout=0.0)
        except BaseException:
            pass
        return "already_stopped"
    shutdown_errors: list[str] = []
    try:
        process.terminate()
    except ProcessLookupError:
        pass
    except BaseException as exc:
        shutdown_errors.append(f"terminate failed: {type(exc).__name__}: {exc}")
    try:
        process.join(timeout=float(terminate_timeout_s))
    except BaseException as exc:
        shutdown_errors.append(f"post-terminate join failed: {type(exc).__name__}: {exc}")
    if not process.is_alive():
        return "terminated"
    kill = getattr(process, "kill", None)
    if not callable(kill):
        raise RuntimeError(
            f"child process {getattr(process, 'pid', None)} ignored termination "
            "and exposes no hard-kill operation"
        )
    try:
        kill()
    except ProcessLookupError:
        pass
    except BaseException as exc:
        shutdown_errors.append(f"hard kill failed: {type(exc).__name__}: {exc}")
    try:
        process.join(timeout=float(kill_timeout_s))
    except BaseException as exc:
        shutdown_errors.append(f"post-kill join failed: {type(exc).__name__}: {exc}")
    if process.is_alive():
        details = f" ({'; '.join(shutdown_errors)})" if shutdown_errors else ""
        raise RuntimeError(
            f"child process {getattr(process, 'pid', None)} survived hard kill{details}"
        )
    return "killed"
