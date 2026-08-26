from __future__ import annotations

import json
import math
import multiprocessing as mp
from pathlib import Path
from typing import Any

import pytest

from resource_envelope_study.canonical import canonical_json_bytes
from resource_envelope_study.run_lease import (
    RunAuthorizationError,
    RunLeaseBusyError,
    RunLeaseReuseError,
    RunLeaseStateError,
    acquire_run_lease,
    authorization_document,
    resolved_output_path_hash,
    validate_run_authorization,
    write_resume_audit,
)


NOW = 2_000_000_000
HOST_FINGERPRINT = "a" * 64


def _write_authorization(
    root: Path,
    *,
    output: Path | None = None,
    resume_policy: str = "audited_same_output",
    maximum_resume_count: int = 2,
    maximum_worker_seconds: int = 100,
) -> tuple[Path, Path, Path, dict[str, Any]]:
    manifest = root / "manifest.json"
    manifest.write_bytes(canonical_json_bytes({"manifest": "frozen", "version": 1}))
    output_path = output or (root / "output")
    document = authorization_document(
        run_id="pilot-run-0001",
        nonce="0123456789abcdef0123456789abcdef",
        manifest_path=manifest,
        output_path=output_path,
        host_fingerprint=HOST_FINGERPRINT,
        not_before_unix=NOW - 10,
        expires_at_unix=NOW + 100,
        maximum_total_worker_seconds=maximum_worker_seconds,
        resume_policy=resume_policy,  # type: ignore[arg-type]
        maximum_resume_count=maximum_resume_count,
    )
    authorization = root / "authorization.json"
    authorization.write_bytes(canonical_json_bytes(document))
    return authorization, manifest, output_path, document


def _hold_lease(
    authorization: str,
    manifest: str,
    output: str,
    ready: Any,
    release: Any,
) -> None:
    lease = acquire_run_lease(
        authorization,
        manifest_path=manifest,
        output_path=output,
        requested_worker_seconds=25,
        actual_host_fingerprint=HOST_FINGERPRINT,
        now_unix=NOW,
    )
    ready.set()
    try:
        release.wait(10.0)
    finally:
        lease.close("interrupted", now_unix=NOW + 1)


def test_authorization_is_consumed_once_and_exact_audited_resume_completes(
    tmp_path: Path,
) -> None:
    authorization, manifest, output, _ = _write_authorization(tmp_path)
    with acquire_run_lease(
        authorization,
        manifest_path=manifest,
        output_path=output,
        requested_worker_seconds=60,
        actual_host_fingerprint=HOST_FINGERPRINT,
        now_unix=NOW,
    ) as first:
        assert first.record["status"] == "active"
        assert first.record["claim_count"] == 1
        first.close("interrupted", now_unix=NOW + 1)

    checkpoint = output / "journal.jsonl"
    checkpoint.write_bytes(b'{"completed":1}\n')
    audit = output / "resume-audit-1.json"
    write_resume_audit(
        authorization,
        output_path=output,
        audited_artifact_path=checkpoint,
        audit_path=audit,
        now_unix=NOW + 2,
    )
    with acquire_run_lease(
        authorization,
        manifest_path=manifest,
        output_path=output,
        requested_worker_seconds=40,
        actual_host_fingerprint=HOST_FINGERPRINT,
        now_unix=NOW + 3,
        resume_audit_path=audit,
    ) as resumed:
        assert resumed.record["claim_count"] == 2
        assert resumed.record["resume_count"] == 1
        assert resumed.record["reserved_worker_seconds_total"] == 100
        resumed.mark_completed(actual_worker_seconds=12, now_unix=NOW + 4)

    output_record = output / ".resource-envelope-run-identity.json"
    authorization_record = tmp_path / ".authorization.json.consumed.json"
    assert output_record.read_bytes() == authorization_record.read_bytes()
    record = json.loads(output_record.read_bytes())
    assert record["status"] == "completed"
    assert record["claims"][-1]["actual_worker_seconds"] == 12
    with pytest.raises(RunLeaseReuseError, match="completed"):
        acquire_run_lease(
            authorization,
            manifest_path=manifest,
            output_path=output,
            requested_worker_seconds=1,
            actual_host_fingerprint=HOST_FINGERPRINT,
            now_unix=NOW + 5,
            resume_audit_path=audit,
        )


def test_concurrent_claim_is_rejected_by_cross_process_lock(tmp_path: Path) -> None:
    authorization, manifest, output, _ = _write_authorization(tmp_path)
    context = mp.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    process = context.Process(
        target=_hold_lease,
        args=(str(authorization), str(manifest), str(output), ready, release),
    )
    process.start()
    try:
        assert ready.wait(5.0)
        with pytest.raises(RunLeaseBusyError, match="holds the run lease"):
            acquire_run_lease(
                authorization,
                manifest_path=manifest,
                output_path=output,
                requested_worker_seconds=1,
                actual_host_fingerprint=HOST_FINGERPRINT,
                now_unix=NOW,
            )
    finally:
        release.set()
        process.join(5.0)
        if process.is_alive():
            process.kill()
            process.join(2.0)
    assert process.exitcode == 0


def test_authorization_rejects_alternate_output_and_copied_file_reuse(
    tmp_path: Path,
) -> None:
    authorization, manifest, output, _ = _write_authorization(tmp_path)
    with pytest.raises(RunAuthorizationError, match="resolved output path"):
        acquire_run_lease(
            authorization,
            manifest_path=manifest,
            output_path=tmp_path / "other-output",
            requested_worker_seconds=10,
            actual_host_fingerprint=HOST_FINGERPRINT,
            now_unix=NOW,
        )

    with acquire_run_lease(
        authorization,
        manifest_path=manifest,
        output_path=output,
        requested_worker_seconds=10,
        actual_host_fingerprint=HOST_FINGERPRINT,
        now_unix=NOW,
    ) as first:
        first.close("interrupted", now_unix=NOW + 1)
    copied = tmp_path / "copied-authorization.json"
    copied.write_bytes(authorization.read_bytes())
    with pytest.raises(RunLeaseStateError, match="only one"):
        acquire_run_lease(
            copied,
            manifest_path=manifest,
            output_path=output,
            requested_worker_seconds=10,
            actual_host_fingerprint=HOST_FINGERPRINT,
            now_unix=NOW + 1,
        )


def test_forbid_policy_refuses_every_second_claim(tmp_path: Path) -> None:
    authorization, manifest, output, _ = _write_authorization(
        tmp_path,
        resume_policy="forbid",
        maximum_resume_count=0,
    )
    with acquire_run_lease(
        authorization,
        manifest_path=manifest,
        output_path=output,
        requested_worker_seconds=10,
        actual_host_fingerprint=HOST_FINGERPRINT,
        now_unix=NOW,
    ) as first:
        first.close("interrupted", now_unix=NOW + 1)
    with pytest.raises(RunLeaseReuseError, match="forbids reuse"):
        acquire_run_lease(
            authorization,
            manifest_path=manifest,
            output_path=output,
            requested_worker_seconds=10,
            actual_host_fingerprint=HOST_FINGERPRINT,
            now_unix=NOW + 1,
        )


def test_resume_requires_unchanged_real_checkpoint_and_cumulative_budget(
    tmp_path: Path,
) -> None:
    authorization, manifest, output, _ = _write_authorization(tmp_path)
    with acquire_run_lease(
        authorization,
        manifest_path=manifest,
        output_path=output,
        requested_worker_seconds=60,
        actual_host_fingerprint=HOST_FINGERPRINT,
        now_unix=NOW,
    ) as first:
        first.close("interrupted", now_unix=NOW + 1)
    checkpoint = output / "journal.jsonl"
    checkpoint.write_bytes(b"before\n")
    audit = output / "resume-audit.json"
    write_resume_audit(
        authorization,
        output_path=output,
        audited_artifact_path=checkpoint,
        audit_path=audit,
        now_unix=NOW + 1,
    )
    checkpoint.write_bytes(b"after\n")
    with pytest.raises(RunLeaseReuseError, match="changed after audit"):
        acquire_run_lease(
            authorization,
            manifest_path=manifest,
            output_path=output,
            requested_worker_seconds=40,
            actual_host_fingerprint=HOST_FINGERPRINT,
            now_unix=NOW + 2,
            resume_audit_path=audit,
        )

    checkpoint.write_bytes(b"before\n")
    with pytest.raises(RunLeaseReuseError, match="worker-second ceiling"):
        acquire_run_lease(
            authorization,
            manifest_path=manifest,
            output_path=output,
            requested_worker_seconds=41,
            actual_host_fingerprint=HOST_FINGERPRINT,
            now_unix=NOW + 2,
            resume_audit_path=audit,
        )


def test_missing_or_divergent_durable_record_fails_closed(tmp_path: Path) -> None:
    authorization, manifest, output, _ = _write_authorization(tmp_path)
    with acquire_run_lease(
        authorization,
        manifest_path=manifest,
        output_path=output,
        requested_worker_seconds=10,
        actual_host_fingerprint=HOST_FINGERPRINT,
        now_unix=NOW,
    ) as first:
        first.close("interrupted", now_unix=NOW + 1)
    authorization_record = tmp_path / ".authorization.json.consumed.json"
    authorization_record.unlink()
    with pytest.raises(RunLeaseStateError, match="only one"):
        acquire_run_lease(
            authorization,
            manifest_path=manifest,
            output_path=output,
            requested_worker_seconds=10,
            actual_host_fingerprint=HOST_FINGERPRINT,
            now_unix=NOW + 1,
        )


def test_first_claim_requires_pristine_output_directory(tmp_path: Path) -> None:
    authorization, manifest, output, _ = _write_authorization(tmp_path)
    output.mkdir()
    (output / "stale-result.jsonl").write_text("stale\n", encoding="ascii")
    with pytest.raises(RunLeaseStateError, match="pristine output directory"):
        acquire_run_lease(
            authorization,
            manifest_path=manifest,
            output_path=output,
            requested_worker_seconds=10,
            actual_host_fingerprint=HOST_FINGERPRINT,
            now_unix=NOW,
        )


@pytest.mark.parametrize(
    ("field", "bad_value", "message"),
    [
        ("not_before_unix", True, "exact JSON integer"),
        ("expires_at_unix", 2_000_000_100.0, "exact JSON integer"),
        ("maximum_total_worker_seconds", False, "exact JSON integer"),
        ("maximum_resume_count", 1.0, "exact JSON integer"),
        ("manifest_sha256", "A" * 64, "lowercase SHA-256"),
        ("run_id", "short", "invalid format"),
    ],
)
def test_exact_authorization_types_are_enforced(
    tmp_path: Path, field: str, bad_value: Any, message: str
) -> None:
    authorization, manifest, output, document = _write_authorization(tmp_path)
    document[field] = bad_value
    authorization.write_bytes(canonical_json_bytes(document))
    with pytest.raises(RunAuthorizationError, match=message):
        validate_run_authorization(
            authorization,
            manifest_path=manifest,
            output_path=output,
            requested_worker_seconds=1,
            actual_host_fingerprint=HOST_FINGERPRINT,
            now_unix=NOW,
        )


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_json_numbers_are_rejected(tmp_path: Path, constant: str) -> None:
    authorization, manifest, output, document = _write_authorization(tmp_path)
    document["expires_at_unix"] = constant
    raw = canonical_json_bytes(document).replace(
        json.dumps(constant).encode("ascii"), constant.encode("ascii"), 1
    )
    authorization.write_bytes(raw)
    with pytest.raises(RunAuthorizationError, match="non-finite JSON number"):
        validate_run_authorization(
            authorization,
            manifest_path=manifest,
            output_path=output,
            requested_worker_seconds=1,
            actual_host_fingerprint=HOST_FINGERPRINT,
            now_unix=NOW,
        )


@pytest.mark.parametrize("now", [math.nan, math.inf, -math.inf])
def test_nonfinite_runtime_time_is_rejected(tmp_path: Path, now: float) -> None:
    authorization, manifest, output, _ = _write_authorization(tmp_path)
    with pytest.raises(RunAuthorizationError, match="now_unix must be finite"):
        validate_run_authorization(
            authorization,
            manifest_path=manifest,
            output_path=output,
            requested_worker_seconds=1,
            actual_host_fingerprint=HOST_FINGERPRINT,
            now_unix=now,
        )


def test_expiry_manifest_host_and_request_ceiling_are_bound(tmp_path: Path) -> None:
    authorization, manifest, output, _ = _write_authorization(tmp_path)
    with pytest.raises(RunAuthorizationError, match="expired"):
        validate_run_authorization(
            authorization,
            manifest_path=manifest,
            output_path=output,
            requested_worker_seconds=1,
            actual_host_fingerprint=HOST_FINGERPRINT,
            now_unix=NOW + 100,
        )
    with pytest.raises(RunAuthorizationError, match="host fingerprint"):
        validate_run_authorization(
            authorization,
            manifest_path=manifest,
            output_path=output,
            requested_worker_seconds=1,
            actual_host_fingerprint="b" * 64,
            now_unix=NOW,
        )
    manifest.write_bytes(b"changed\n")
    with pytest.raises(RunAuthorizationError, match="manifest SHA-256"):
        validate_run_authorization(
            authorization,
            manifest_path=manifest,
            output_path=output,
            requested_worker_seconds=1,
            actual_host_fingerprint=HOST_FINGERPRINT,
            now_unix=NOW,
        )


def test_resolved_path_hash_accepts_alias_only_when_target_is_identical(
    tmp_path: Path,
) -> None:
    target = tmp_path / "real-output"
    target.mkdir()
    alias = tmp_path / "output-alias"
    try:
        alias.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks unavailable")
    assert resolved_output_path_hash(alias) == resolved_output_path_hash(target)
    authorization, manifest, _, _ = _write_authorization(tmp_path, output=target)
    with acquire_run_lease(
        authorization,
        manifest_path=manifest,
        output_path=alias,
        requested_worker_seconds=10,
        actual_host_fingerprint=HOST_FINGERPRINT,
        now_unix=NOW,
    ) as lease:
        lease.mark_completed(now_unix=NOW + 1)
