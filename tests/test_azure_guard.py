import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from training.azure_guard import AzureRunSafety, enforce_azure_workload, is_azure_host


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


class FakeClock:
    def __init__(self, value=1_000.0):
        self.value = float(value)

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += float(seconds)


def test_azure_run_safety_enforces_hard_cap_and_records_elapsed_spend(tmp_path):
    workers = [
        {"name": "one", "rg": "rg"},
        {"name": "two", "rg": "rg"},
    ]
    clock = FakeClock()
    calls = []

    def deallocate(worker):
        calls.append(worker["name"])
        return SimpleNamespace(returncode=0, stderr="")

    manifest = tmp_path / "azure-safety.json"
    safety = AzureRunSafety(
        workers=workers,
        manifest_path=manifest,
        rate_usd_per_worker_hour=1.0,
        spend_cap_usd=1.0,
        deallocate_worker=deallocate,
        clock=clock,
    )
    with safety:
        safety.mark_start_requested(workers[0])
        reservation = safety.reserve(worker_seconds=1_800, label="bounded-job")
        with pytest.raises(RuntimeError, match=r"hard \$1.00 cap"):
            safety.reserve(worker_seconds=3_601, label="too-large")
        clock.advance(900)
        safety.release(reservation)

    report = safety.report()
    assert calls == ["one", "two"]
    assert report["all_workers_deallocated"] is True
    assert report["actual_elapsed_worker_seconds"] == 900
    assert report["estimated_incremental_spend_usd"] == pytest.approx(0.25)
    assert report["hard_incremental_spend_cap_usd"] == 1.0
    assert manifest.exists()


def test_azure_run_safety_retries_failures_and_deallocates_every_worker(tmp_path):
    workers = [
        {"name": "one", "rg": "rg"},
        {"name": "two", "rg": "rg"},
    ]
    calls = []

    def deallocate(worker):
        calls.append(worker["name"])
        if worker["name"] == "one":
            raise RuntimeError("CLI unavailable")
        return SimpleNamespace(returncode=0, stderr="")

    safety = AzureRunSafety(
        workers=workers,
        manifest_path=tmp_path / "azure-safety.json",
        rate_usd_per_worker_hour=0.5,
        deallocate_worker=deallocate,
        deallocation_attempts=2,
    )
    with pytest.raises(ValueError, match="job failed"):
        with safety:
            safety.mark_start_requested(workers[0])
            raise ValueError("job failed")

    report = safety.report()
    assert calls == ["one", "one", "two"]
    assert report["status"] == "deallocation_failed"
    assert report["all_workers_deallocated"] is False
    assert len(report["workers"][0]["deallocation"]["attempts"]) == 2


def test_azure_run_safety_rejects_cap_above_authorization(tmp_path):
    with pytest.raises(ValueError, match="incremental spend cap"):
        AzureRunSafety(
            workers=[{"name": "one", "rg": "rg"}],
            manifest_path=tmp_path / "azure-safety.json",
            rate_usd_per_worker_hour=0.5,
            spend_cap_usd=100.01,
            deallocate_worker=lambda worker: None,
        )


def test_azure_run_safety_counts_prior_incremental_spend(tmp_path):
    safety = AzureRunSafety(
        workers=[{"name": "one", "rg": "rg"}],
        manifest_path=tmp_path / "azure-safety.json",
        rate_usd_per_worker_hour=1.0,
        spend_cap_usd=100.0,
        prior_incremental_spend_usd=99.0,
        deallocate_worker=lambda worker: SimpleNamespace(returncode=0, stderr=""),
    )
    with safety:
        with pytest.raises(RuntimeError, match=r"hard \$100.00 cap"):
            safety.reserve(worker_seconds=3_601, label="over-remaining-budget")

    assert safety.report()["combined_estimated_incremental_spend_usd"] == 99.0
