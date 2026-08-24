from __future__ import annotations

import json
from pathlib import Path

import pytest

from paper.scripts import run_pevl_experiments as pevl


PROTOCOL_COMMIT = "1" * 40
PROVENANCE = {
    "branch": "paper/aps-open-science-202608",
    "execution_commit": "2" * 40,
    "origin_head": "2" * 40,
    "protocol_commit": PROTOCOL_COMMIT,
    "protocol_sha256": "3" * 64,
}


def option(command: tuple[str, ...], name: str) -> str:
    index = command.index(name)
    return command[index + 1]


def test_frozen_job_matrices_and_paths_match_protocol():
    preflight = pevl.preflight_jobs(PROTOCOL_COMMIT)
    assert len(preflight) == 20
    assert preflight[0].key == "c1_b0"
    assert preflight[-1].key == "c4_alakazam_no_search"
    assert preflight[0].public_output == pevl.PUBLIC_ROOT / "preflight/raw/c1_b0.json"
    assert option(preflight[0].command, "--base-seed") == "2026072700"
    assert option(preflight[0].command, "--seeds-per-order") == "25"
    assert option(preflight[0].command, "--parallel-workers") == "8"
    assert option(preflight[0].command, "--trace-mode") == "digest"
    assert "--stress-matrix" not in preflight[0].command
    alakazam = next(job for job in preflight if job.key == "c3_alakazam_no_search")
    assert option(alakazam.command, "--opponent-env") == '{"NO_SEARCH":"1"}'

    stress = pevl.stress_jobs(PROTOCOL_COMMIT)
    assert [job.key for job in stress] == ["starmie", "dipplin"]
    assert stress[0].local_output == pevl.LOCAL_ROOT / "stress/starmie/proof.json"
    assert option(stress[0].command, "--base-seed") == "2026092700"
    assert option(stress[0].command, "--seeds-per-order") == "50"
    assert option(stress[0].command, "--parallel-workers") == "4"
    assert option(stress[0].command, "--trace-mode") == "full"
    assert "--stress-matrix" in stress[0].command

    factorial = pevl.factorial_jobs(PROTOCOL_COMMIT)
    assert len(factorial) == 15
    assert factorial[0].key == "c2_b0"
    assert factorial[-1].key == "c4_alakazam_no_search"
    assert factorial[0].public_output == pevl.PUBLIC_ROOT / "factorial/raw/c2_b0.json"
    assert option(factorial[0].command, "--base-seed") == "2026082700"
    assert option(factorial[0].command, "--pairs-per-order") == "200"
    assert option(factorial[0].command, "--workers") == "8"
    assert option(factorial[0].command, "--actual-order") == "both"


def test_repository_provenance_requires_clean_pushed_protocol(monkeypatch):
    calls = []

    def fake_git(arguments):
        calls.append(arguments)
        if arguments[:2] == ["branch", "--show-current"]:
            return "paper/aps-open-science-202608"
        if arguments[:2] == ["rev-parse", "HEAD"]:
            return "2" * 40
        if arguments[:2] == ["ls-remote", "--heads"]:
            return f"{'2' * 40}\trefs/heads/paper/aps-open-science-202608"
        if arguments and arguments[0] == "log":
            return PROTOCOL_COMMIT
        return ""

    monkeypatch.setattr(pevl, "sha256_file", lambda _path: "3" * 64)
    observed = pevl.validate_repository_provenance(fake_git)
    assert observed == PROVENANCE
    assert any(arguments[0] == "merge-base" for arguments in calls)
    assert sum(arguments[0] == "ls-files" for arguments in calls) == 3
    assert sum(arguments[0] == "status" for arguments in calls) == 3

    def unpushed_git(arguments):
        if arguments[:2] == ["branch", "--show-current"]:
            return "paper/aps-open-science-202608"
        if arguments[:2] == ["rev-parse", "HEAD"]:
            return "2" * 40
        if arguments[:2] == ["ls-remote", "--heads"]:
            return f"{'9' * 40}\trefs/heads/paper/aps-open-science-202608"
        return ""

    with pytest.raises(pevl.ProtocolViolation, match="not the pushed"):
        pevl.validate_repository_provenance(unpushed_git)


def test_output_roots_refuse_overwrite_and_force_archives(monkeypatch, tmp_path):
    public = tmp_path / "paper/data/pevl"
    local = tmp_path / "artifacts/pevl_20260824"
    existing = public / "preflight/raw/result.json"
    existing.parent.mkdir(parents=True)
    existing.write_text("old", encoding="utf-8")

    with pytest.raises(pevl.ProtocolViolation, match="refusing to overwrite"):
        pevl.prepare_output_roots(
            "preflight", force=False, public_root=public, local_root=local
        )

    monkeypatch.setattr(pevl.uuid, "uuid4", lambda: type("U", (), {"hex": "fixed"})())
    pevl.prepare_output_roots("preflight", force=True, public_root=public, local_root=local)
    archived = local / "superseded/preflight_public_fixed/raw/result.json"
    assert archived.read_text(encoding="utf-8") == "old"
    assert (public / "preflight").is_dir()
    assert not any((public / "preflight").iterdir())


def test_execute_job_uses_monkeypatched_runner_and_sanitizes_paths(tmp_path):
    local = tmp_path / "restricted/result.json"
    public = tmp_path / "public/result.json"
    command = ("python", "runner.py", "prove", "--output", str(local))
    job = pevl.Job("preflight", "c1_b0", "c1", "b0", 7, local, public, command)
    called = []

    def fake_runner(observed):
        called.append(tuple(observed))
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_text(
            json.dumps(
                {
                    "engine": str(pevl.ENGINE),
                    "passed": True,
                    "runs": {"single_a": []},
                    "trace_files": {},
                }
            ),
            encoding="utf-8",
        )

    payload = pevl.execute_job(job, command_runner=fake_runner)
    assert payload["passed"] is True
    assert called == [command]
    safe = json.loads(public.read_text(encoding="utf-8"))
    assert safe["engine"] == "artifacts/deterministic_engine/bin/libcg_seeded.dylib"
    assert safe["redistribution"]["full_trace_payloads_included"] is False


def test_factorial_gate_fails_before_output_or_command(monkeypatch):
    events = []

    def fail_gate(_commit):
        raise pevl.ProtocolViolation("preflight gate failed")

    monkeypatch.setattr(pevl, "require_passing_preflight", fail_gate)
    monkeypatch.setattr(
        pevl,
        "prepare_output_roots",
        lambda *args, **kwargs: events.append("prepared"),
    )
    with pytest.raises(pevl.ProtocolViolation, match="preflight gate failed"):
        pevl.run_factorial(
            PROVENANCE,
            force=False,
            command_runner=lambda _command: events.append("ran"),
        )
    assert events == []


def test_preflight_summary_is_fail_closed_on_trace_mismatch(monkeypatch):
    job = pevl.preflight_jobs(PROTOCOL_COMMIT)[0]
    task_ids = [
        f"{order}-{index:03d}"
        for order in ("first", "second")
        for index in range(25)
    ]

    def rows():
        result = []
        for task_id in task_ids:
            order, index_text = task_id.split("-", 1)
            index = int(index_text)
            seed = job.base_seed + (1_000_000 if order == "second" else 0) + index
            result.append(
                {
                    "task_id": task_id,
                    "scheduled_seed": seed,
                    "engine_seed_uint32": seed,
                    "physical_seat": index % 2,
                    "public_trace_sha256": "a" * 64,
                    "trace_bytes": 100,
                    "hero_policy_errors": 0,
                    "opponent_policy_errors": 0,
                }
            )
        return result

    payload = {
        "engine_sha256": pevl.ENGINE_ARTIFACT.sha256,
        "hero_sha256": pevl.POLICIES["c1"].sha256,
        "opponent_sha256": pevl.DETERMINISTIC_OPPONENTS["b0"].sha256,
        "protocol_id": pevl.PROTOCOL_ID,
        "protocol_commit": PROTOCOL_COMMIT,
        "base_seed": job.base_seed,
        "order_seed_offset": 1_000_000,
        "seeds_per_order": 25,
        "tasks": 50,
        "max_decisions": 2_000,
        "opponent_env": {},
        "trace_mode": "digest",
        "trace_payload_files_written": False,
        "runs": {"single_a": rows(), "single_b": rows(), "workers_8": rows()},
        "trace_files": {},
        "passed": False,
    }
    monkeypatch.setattr(pevl, "sha256_file", lambda _path: "f" * 64)
    summary = pevl.build_preflight_summary([job], {job.key: payload}, PROVENANCE)
    assert summary["status"] == "FAIL"
    assert summary["admission_decision"] == "suppress_factorial"
    assert summary["failures"] == [{"job": "c1_b0", "issues": ["trace_mismatch"]}]
