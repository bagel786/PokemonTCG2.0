import tempfile
from pathlib import Path

import pytest

from training.azure_guard import enforce_azure_workload, is_azure_host


def test_azure_host_requires_marker_and_microsoft_vendor():
    with tempfile.TemporaryDirectory() as directory:
        vendor = Path(directory) / "vendor"
        vendor.write_text("Microsoft Corporation\n")
        assert is_azure_host({"PTCG_AZURE_RUN": "1"}, vendor)
        assert not is_azure_host({}, vendor)


def test_local_rl_is_limited_to_explicit_small_smoke():
    with tempfile.TemporaryDirectory() as directory:
        vendor = Path(directory) / "vendor"
        vendor.write_text("Apple Inc.\n")
        assert enforce_azure_workload(
            allow_local_smoke=True, workload_size=200, env={}, vendor_path=vendor
        ) == "local_smoke"
        with pytest.raises(RuntimeError):
            enforce_azure_workload(
                allow_local_smoke=True, workload_size=201, env={}, vendor_path=vendor
            )
