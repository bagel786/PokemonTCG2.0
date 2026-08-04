"""Runtime enforcement for compute-heavy Azure-only workloads."""

from __future__ import annotations

import os
from pathlib import Path


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
