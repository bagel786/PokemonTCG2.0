#!/usr/bin/env python3
"""Run the frozen PEVL acquisitions with fail-closed provenance and gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable


ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = ROOT / "paper/protocol/PEVL_PROSPECTIVE_PROTOCOL.md"
RUNNER = ROOT / "training/evaluate_deterministic_crn.py"
ORCHESTRATOR = Path(__file__).resolve()
PUBLIC_ROOT = ROOT / "paper/data/pevl"
LOCAL_ROOT = ROOT / "artifacts/pevl_20260824"
ENGINE = ROOT / "artifacts/deterministic_engine/bin/libcg_seeded.dylib"
PRODUCTION_ENGINE = ROOT / "vendor/cg/libcg.dylib"
PROTOCOL_ID = "PEVL_PROSPECTIVE_PROTOCOL_20260824"
ORDER_SEED_OFFSET = 1_000_000
MAX_DECISIONS = 2_000


class ProtocolViolation(RuntimeError):
    """Raised before or during acquisition when a frozen requirement is violated."""


@dataclass(frozen=True)
class Artifact:
    label: str
    path: Path
    sha256: str


@dataclass(frozen=True)
class Opponent:
    label: str
    path: Path
    sha256: str
    env: dict[str, str]
    preflight_seed: int | None = None
    stress_seed: int | None = None
    factorial_seed: int | None = None


@dataclass(frozen=True)
class Job:
    stage: str
    key: str
    policy: str
    opponent: str
    base_seed: int
    local_output: Path
    public_output: Path | None
    command: tuple[str, ...]


POLICIES = {
    "c1": Artifact(
        "c1",
        ROOT / "artifacts/grim_damage_conversion/winner/extracted",
        "13426288358d597ead809e45c364c7f7b9274a6eebf55ddd942142e3326535c3",
    ),
    "c2": Artifact(
        "c2",
        ROOT / "artifacts/grim_play_identity/candidates/p0",
        "36e804ae6c593db57b595bfca9fd48592da10957f0e5f840a7e390edbeb39b63",
    ),
    "c3": Artifact(
        "c3",
        ROOT / "artifacts/paper_ablation/blind_trained_package",
        "236afa20b4ced63169736fea616849fa564281c05e9435e4dd77ecfb4ae5fd54",
    ),
    "c4": Artifact(
        "c4",
        ROOT / "artifacts/final_sprint/exp23_identity_trained",
        "83489e0c80c631763c65375d2a7a34d28d6aa9fbb1d11e89d130c83b1e27f1c0",
    ),
}

ENGINE_ARTIFACT = Artifact(
    "engine", ENGINE, "867e3f9bb87e0b48889a44b5d4b04f5d2d434b2a0788d1b2bcfe0caebcb5ab78"
)
PRODUCTION_ARTIFACT = Artifact(
    "production_engine",
    PRODUCTION_ENGINE,
    "7a157f045d333f99d1996d49c12bdbdd148072a619af246385c7295518776e30",
)

DETERMINISTIC_OPPONENTS = {
    "b0": Opponent(
        "b0",
        ROOT / "artifacts/grim_variance_floor/candidates/B0",
        "0c15b56adf3b09c654505a152309fdc9f8401579a495da714347d98ae735003c",
        {},
        preflight_seed=2026072700,
        factorial_seed=2026082700,
    ),
    "d842": Opponent(
        "d842",
        ROOT / "artifacts/overnight_20260816/d842_runtime",
        "7db753d6610930d8bd9694b4b9bece5ac48733b825422a3e399c18077b55e64e",
        {},
        preflight_seed=2026073700,
        factorial_seed=2026083700,
    ),
    "master": Opponent(
        "master",
        ROOT / "artifacts/grim_damage_conversion/opponents/master_v1",
        "8a06ebab47cc60ed981dfada85972eb8a62e732e349f01c2a3085262079f06e8",
        {},
        preflight_seed=2026074700,
        factorial_seed=2026084700,
    ),
    "replay": Opponent(
        "replay",
        ROOT / "artifacts/grim_damage_conversion/opponents/replay_refresh",
        "30e45955b67893514c8ee077cac15d46fc207efe781cbce1b94242defda4cbdc",
        {},
        preflight_seed=2026075700,
        factorial_seed=2026085700,
    ),
    "alakazam_no_search": Opponent(
        "alakazam_no_search",
        ROOT / "artifacts/sprint_870/opponents/alakazam_2_4a",
        "5d44338891094988ca15f0c26d5187316549facd64a7bfbac04aa0048424e8c7",
        {"NO_SEARCH": "1"},
        preflight_seed=2026078700,
        factorial_seed=2026086700,
    ),
}

STRESS_OPPONENTS = {
    "starmie": Opponent(
        "starmie",
        ROOT / "artifacts/sprint_870/opponents/starmie_v2_boss_atk",
        "1b73779da7dcc93c8f121090bb0f1ae2d9b10b798ca4c70447b0ce1d6d01c0db",
        {},
        stress_seed=2026092700,
    ),
    "dipplin": Opponent(
        "dipplin",
        ROOT / "artifacts/sprint_870/opponents/dipplin_d1",
        "076ae8de12d2d6c4a170b47b2d2f9cf538c1d318a05bb2e81f13da9be2cd2026",
        {},
        stress_seed=2026093700,
    ),
}


def emit(event: str, **fields: Any) -> None:
    print(json.dumps({"event": event, **fields}, sort_keys=True), flush=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_path(path: Path) -> str:
    if path.is_file():
        return sha256_file(path)
    digest = hashlib.sha256()
    for child in sorted(
        item
        for item in path.rglob("*")
        if item.is_file() and "__pycache__" not in item.parts and item.suffix != ".pyc"
    ):
        relative = child.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256_file(child)))
    return digest.hexdigest()


def _git_output(arguments: list[str]) -> str:
    environment = dict(os.environ)
    environment["GIT_TERMINAL_PROMPT"] = "0"
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProtocolViolation(f"git {' '.join(arguments)} failed: {exc}") from exc
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ProtocolViolation(f"git {' '.join(arguments)} failed: {detail}")
    return completed.stdout.strip()


def validate_repository_provenance(
    git_output: Callable[[list[str]], str] | None = None,
) -> dict[str, str]:
    git = git_output or _git_output
    required = (PROTOCOL, RUNNER, ORCHESTRATOR)
    for path in required:
        relative = path.relative_to(ROOT).as_posix()
        git(["ls-files", "--error-unmatch", relative])
        status = git(["status", "--porcelain", "--", relative])
        if status:
            raise ProtocolViolation(f"execution input is not committed and clean: {relative}")

    branch = git(["branch", "--show-current"])
    if not branch:
        raise ProtocolViolation("PEVL acquisition cannot run from a detached HEAD")
    head = git(["rev-parse", "HEAD"])
    remote = git(["ls-remote", "--heads", "origin", f"refs/heads/{branch}"])
    remote_lines = [line.split() for line in remote.splitlines() if line.strip()]
    if len(remote_lines) != 1 or len(remote_lines[0]) != 2:
        raise ProtocolViolation(f"origin/{branch} is absent or ambiguous")
    remote_head = remote_lines[0][0]
    if remote_head != head:
        raise ProtocolViolation(
            f"local HEAD {head} is not the pushed origin/{branch} tip {remote_head}"
        )

    protocol_relative = PROTOCOL.relative_to(ROOT).as_posix()
    additions = git(
        ["log", "--diff-filter=A", "--format=%H", "--reverse", "--", protocol_relative]
    ).splitlines()
    if not additions:
        raise ProtocolViolation("cannot identify the commit that first froze the PEVL protocol")
    protocol_commit = additions[0]
    git(["merge-base", "--is-ancestor", protocol_commit, head])
    return {
        "branch": branch,
        "execution_commit": head,
        "origin_head": remote_head,
        "protocol_commit": protocol_commit,
        "protocol_sha256": sha256_file(PROTOCOL),
    }


def validate_protocol_contract() -> None:
    if not PROTOCOL.is_file():
        raise ProtocolViolation(f"missing frozen protocol: {PROTOCOL}")
    text = PROTOCOL.read_text(encoding="utf-8")
    required_literals = {
        PROTOCOL_ID.split("_20260824")[0]: "Paired Evaluation Validity Ladder",
        "seed conversion": "scheduled_seed & 0xffffffff",
        "second-order offset": "base_seed + 1_000_000 + i",
        "Alakazam environment": '{"NO_SEARCH":"1"}',
    }
    for artifact in (ENGINE_ARTIFACT, PRODUCTION_ARTIFACT, *POLICIES.values()):
        required_literals[f"{artifact.label} hash"] = artifact.sha256
    for opponent in (*DETERMINISTIC_OPPONENTS.values(), *STRESS_OPPONENTS.values()):
        required_literals[f"{opponent.label} hash"] = opponent.sha256
        for seed in (opponent.preflight_seed, opponent.stress_seed, opponent.factorial_seed):
            if seed is not None:
                required_literals[f"{opponent.label} seed {seed}"] = str(seed)
    missing = [label for label, literal in required_literals.items() if literal not in text]
    if missing:
        raise ProtocolViolation(f"orchestrator constants drift from protocol: {missing}")


def _stage_artifacts(stage: str) -> list[Artifact]:
    artifacts: list[Artifact] = [ENGINE_ARTIFACT]
    if stage in {"preflight", "all"}:
        artifacts.extend(POLICIES.values())
        artifacts.extend(
            Artifact(item.label, item.path, item.sha256)
            for item in DETERMINISTIC_OPPONENTS.values()
        )
    if stage in {"stress", "all"}:
        artifacts.append(POLICIES["c1"])
        artifacts.extend(
            Artifact(item.label, item.path, item.sha256) for item in STRESS_OPPONENTS.values()
        )
    if stage in {"factorial", "all"}:
        artifacts.extend((PRODUCTION_ARTIFACT, *POLICIES.values()))
        artifacts.extend(
            Artifact(item.label, item.path, item.sha256)
            for item in DETERMINISTIC_OPPONENTS.values()
        )
    unique = {artifact.path.resolve(): artifact for artifact in artifacts}
    return list(unique.values())


def validate_artifacts(stage: str) -> dict[str, str]:
    observed: dict[str, str] = {}
    for artifact in _stage_artifacts(stage):
        if not artifact.path.exists():
            raise ProtocolViolation(f"missing frozen artifact {artifact.label}: {artifact.path}")
        digest = sha256_path(artifact.path)
        emit("artifact_checked", label=artifact.label, sha256=digest)
        if digest != artifact.sha256:
            raise ProtocolViolation(
                f"artifact hash drift for {artifact.label}: expected {artifact.sha256}, got {digest}"
            )
        observed[artifact.label] = digest
    return observed


def validate_output_policy(
    git_output: Callable[[list[str]], str] | None = None,
) -> None:
    git = git_output or _git_output
    local_relative = (LOCAL_ROOT / "stress/probe").relative_to(ROOT).as_posix()
    public_relative = (PUBLIC_ROOT / "probe").relative_to(ROOT).as_posix()
    ignored = git(["check-ignore", "-v", local_relative])
    if not ignored:
        raise ProtocolViolation("restricted PEVL artifact root is not ignored by Git")
    try:
        git(["check-ignore", "-v", public_relative])
    except ProtocolViolation:
        return
    raise ProtocolViolation("public PEVL data root is unexpectedly ignored by Git")


def _archive_existing(
    root: Path, *, stage: str, role: str, archive_root: Path
) -> None:
    destination = (
        archive_root
        / "superseded"
        / f"{stage}_{role}_{uuid.uuid4().hex}"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(root), str(destination))
    emit("existing_output_archived", source=str(root), destination=str(destination))


def prepare_output_roots(
    stage: str,
    *,
    force: bool,
    public_root: Path | None = None,
    local_root: Path | None = None,
) -> None:
    public_root = public_root or PUBLIC_ROOT
    local_root = local_root or LOCAL_ROOT
    roots = {
        "preflight": (
            (public_root / "preflight", "public"),
            (local_root / "staging/preflight", "restricted_staging"),
        ),
        "stress": (
            (public_root / "stress", "public"),
            (local_root / "stress", "restricted"),
        ),
        "factorial": (
            (public_root / "factorial", "public"),
            (local_root / "staging/factorial", "restricted_staging"),
        ),
    }[stage]
    for root, role in roots:
        occupied = root.is_file() or (root.is_dir() and any(root.iterdir()))
        if occupied:
            if not force:
                raise ProtocolViolation(
                    f"refusing to overwrite existing {stage} output root: {root}; use --force"
                )
            _archive_existing(root, stage=stage, role=role, archive_root=local_root)
        root.mkdir(parents=True, exist_ok=True)


def _json_env(value: dict[str, str]) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def preflight_jobs(protocol_commit: str) -> list[Job]:
    jobs: list[Job] = []
    for arm, policy in POLICIES.items():
        for label, opponent in DETERMINISTIC_OPPONENTS.items():
            assert opponent.preflight_seed is not None
            key = f"{arm}_{label}"
            local_output = LOCAL_ROOT / "staging/preflight" / f"{key}.json"
            public_output = PUBLIC_ROOT / "preflight/raw" / f"{key}.json"
            command = (
                sys.executable,
                str(RUNNER),
                "prove",
                "--engine",
                str(ENGINE),
                "--hero",
                str(policy.path),
                "--opponent",
                str(opponent.path),
                "--output",
                str(local_output),
                "--base-seed",
                str(opponent.preflight_seed),
                "--seeds-per-order",
                "25",
                "--parallel-workers",
                "8",
                "--max-decisions",
                str(MAX_DECISIONS),
                "--hero-env",
                "{}",
                "--opponent-env",
                _json_env(opponent.env),
                "--trace-mode",
                "digest",
                "--protocol-id",
                PROTOCOL_ID,
                "--protocol-commit",
                protocol_commit,
                "--audit",
            )
            jobs.append(
                Job("preflight", key, arm, label, opponent.preflight_seed, local_output, public_output, command)
            )
    return jobs


def stress_jobs(protocol_commit: str) -> list[Job]:
    jobs: list[Job] = []
    policy = POLICIES["c1"]
    for label, opponent in STRESS_OPPONENTS.items():
        assert opponent.stress_seed is not None
        output = LOCAL_ROOT / "stress" / label / "proof.json"
        public_output = PUBLIC_ROOT / "stress/raw" / f"{label}.json"
        command = (
            sys.executable,
            str(RUNNER),
            "prove",
            "--engine",
            str(ENGINE),
            "--hero",
            str(policy.path),
            "--opponent",
            str(opponent.path),
            "--output",
            str(output),
            "--base-seed",
            str(opponent.stress_seed),
            "--seeds-per-order",
            "50",
            "--parallel-workers",
            "4",
            "--max-decisions",
            str(MAX_DECISIONS),
            "--hero-env",
            "{}",
            "--opponent-env",
            _json_env(opponent.env),
            "--trace-mode",
            "full",
            "--stress-matrix",
            "--protocol-id",
            PROTOCOL_ID,
            "--protocol-commit",
            protocol_commit,
            "--audit",
        )
        jobs.append(Job("stress", label, "c1", label, opponent.stress_seed, output, public_output, command))
    return jobs


def factorial_jobs(protocol_commit: str) -> list[Job]:
    jobs: list[Job] = []
    control = POLICIES["c1"]
    for cell in ("c2", "c3", "c4"):
        candidate = POLICIES[cell]
        for label, opponent in DETERMINISTIC_OPPONENTS.items():
            assert opponent.factorial_seed is not None
            key = f"{cell}_{label}"
            local_output = LOCAL_ROOT / "staging/factorial" / f"{key}.json"
            public_output = PUBLIC_ROOT / "factorial/raw" / f"{key}.json"
            command = (
                sys.executable,
                str(RUNNER),
                "paired",
                "--engine",
                str(ENGINE),
                "--candidate",
                str(candidate.path),
                "--control",
                str(control.path),
                "--opponent",
                str(opponent.path),
                "--production-engine",
                str(PRODUCTION_ENGINE),
                "--output",
                str(local_output),
                "--base-seed",
                str(opponent.factorial_seed),
                "--pairs-per-order",
                "200",
                "--actual-order",
                "both",
                "--workers",
                "8",
                "--max-decisions",
                str(MAX_DECISIONS),
                "--hero-env",
                "{}",
                "--opponent-env",
                _json_env(opponent.env),
                "--protocol-id",
                PROTOCOL_ID,
                "--protocol-commit",
                protocol_commit,
            )
            jobs.append(
                Job("factorial", key, cell, label, opponent.factorial_seed, local_output, public_output, command)
            )
    return jobs


def run_command(command: Iterable[str]) -> None:
    completed = subprocess.run(list(command), cwd=ROOT, check=False)
    if completed.returncode:
        raise ProtocolViolation(f"evaluation command exited {completed.returncode}")


def _repository_relative(value: str) -> str:
    path = Path(value)
    if not path.is_absolute():
        return value
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise ProtocolViolation(f"result contains a path outside the repository: {value}") from exc


def redistribution_safe(payload: dict[str, Any], *, stage: str) -> dict[str, Any]:
    safe = json.loads(json.dumps(payload))
    for key in ("engine", "production_engine", "hero", "candidate", "control", "opponent"):
        if isinstance(safe.get(key), str):
            safe[key] = _repository_relative(safe[key])
    for runs in (safe.get("runs", {}),):
        for rows in runs.values():
            for row in rows:
                if "trace" in row:
                    raise ProtocolViolation("restricted trace payload appeared in JSON row output")
    for row in safe.get("rows", []):
        if "trace" in row:
            raise ProtocolViolation("restricted trace payload appeared in JSON row output")
    safe["redistribution"] = {
        "safe_row_metadata_and_trace_digests_only": True,
        "full_trace_payloads_included": False,
        "restricted_full_traces_location": (
            "artifacts/pevl_20260824/stress" if stage == "stress" else None
        ),
    }
    return safe


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def execute_job(
    job: Job,
    *,
    command_runner: Callable[[Iterable[str]], None] = run_command,
) -> dict[str, Any]:
    job.local_output.parent.mkdir(parents=True, exist_ok=True)
    emit(
        "job_start",
        stage=job.stage,
        key=job.key,
        policy=job.policy,
        opponent=job.opponent,
        base_seed=job.base_seed,
        output=str(job.local_output),
    )
    command_runner(job.command)
    if not job.local_output.is_file():
        raise ProtocolViolation(f"evaluation produced no result: {job.local_output}")
    payload = json.loads(job.local_output.read_text(encoding="utf-8"))
    if job.public_output is not None:
        write_json(job.public_output, redistribution_safe(payload, stage=job.stage))
    emit("job_complete", stage=job.stage, key=job.key, passed=payload.get("passed"))
    return payload


def _expected_task_ids(count: int) -> set[str]:
    return {
        f"{order}-{index:03d}"
        for order in ("first", "second")
        for index in range(count)
    }


def _proof_issues(job: Job, payload: dict[str, Any], *, stress: bool) -> list[str]:
    opponent = (STRESS_OPPONENTS if stress else DETERMINISTIC_OPPONENTS)[job.opponent]
    policy = POLICIES[job.policy]
    count = 50 if stress else 25
    expected_runs = (
        {"serial_forward", "serial_reverse", "parallel_forward", "parallel_reverse"}
        if stress
        else {"single_a", "single_b", "workers_8"}
    )
    checks = {
        "engine_hash": payload.get("engine_sha256") == ENGINE_ARTIFACT.sha256,
        "policy_hash": payload.get("hero_sha256") == policy.sha256,
        "opponent_hash": payload.get("opponent_sha256") == opponent.sha256,
        "protocol": payload.get("protocol_id") == PROTOCOL_ID,
        "base_seed": payload.get("base_seed") == job.base_seed,
        "order_offset": payload.get("order_seed_offset") == ORDER_SEED_OFFSET,
        "seed_count": payload.get("seeds_per_order") == count,
        "tasks": payload.get("tasks") == count * 2,
        "max_decisions": payload.get("max_decisions") == MAX_DECISIONS,
        "opponent_env": payload.get("opponent_env") == opponent.env,
        "trace_mode": payload.get("trace_mode") == ("full" if stress else "digest"),
        "trace_retention": payload.get("trace_payload_files_written") is stress,
        "run_names": set(payload.get("runs", {})) == expected_runs,
    }
    issues = [name for name, passed in checks.items() if not passed]
    task_ids = _expected_task_ids(count)
    for run, rows in payload.get("runs", {}).items():
        row_ids = {str(row.get("task_id")) for row in rows}
        if row_ids != task_ids or len(rows) != len(task_ids):
            issues.append(f"{run}:incomplete_schedule")
        by_task = {str(row.get("task_id")): row for row in rows}
        for task_id in task_ids & set(by_task):
            order, index_text = task_id.split("-", 1)
            index = int(index_text)
            expected_seed = job.base_seed + (ORDER_SEED_OFFSET if order == "second" else 0) + index
            row = by_task[task_id]
            if (
                int(row.get("scheduled_seed", -1)) != expected_seed
                or int(row.get("engine_seed_uint32", -1)) != expected_seed
                or int(row.get("physical_seat", -1)) != index % 2
                or not row.get("public_trace_sha256")
                or int(row.get("trace_bytes", 0)) <= 0
            ):
                issues.append(f"{run}:schedule_or_trace_metadata")
        if not stress and any(
            int(row.get("hero_policy_errors", 0)) or int(row.get("opponent_policy_errors", 0))
            for row in rows
        ):
            issues.append(f"{run}:policy_errors")
    if stress:
        inventory = payload.get("trace_files", {})
        for run in expected_runs:
            if set(inventory.get(run, {})) != task_ids:
                issues.append(f"{run}:trace_inventory")
                continue
            rows = {
                str(row["task_id"]): row
                for row in payload.get("runs", {}).get(run, [])
            }
            for task_id, expected_digest in inventory[run].items():
                trace_path = job.local_output.parent / "determinism_traces" / run / f"{task_id}.jsonl"
                if (
                    not trace_path.is_file()
                    or sha256_file(trace_path) != expected_digest
                    or rows.get(task_id, {}).get("public_trace_sha256") != expected_digest
                ):
                    issues.append(f"{run}:trace_payload_hash")
                    break
    elif payload.get("trace_files"):
        issues.append("digest_preflight_wrote_trace_payload_files")
    return sorted(set(issues))


def build_preflight_summary(
    jobs: list[Job], payloads: dict[str, dict[str, Any]], provenance: dict[str, str]
) -> dict[str, Any]:
    rows = []
    failures = []
    for job in jobs:
        payload = payloads.get(job.key)
        if payload is None:
            failures.append({"job": job.key, "issues": ["missing_result"]})
            continue
        issues = _proof_issues(job, payload, stress=False)
        if payload.get("protocol_commit") != provenance["protocol_commit"]:
            issues.append("protocol_commit")
        if not payload.get("passed"):
            issues.append("trace_mismatch")
        if issues:
            failures.append({"job": job.key, "issues": sorted(set(issues))})
        rows.append(
            {
                "job": job.key,
                "arm": job.policy,
                "opponent": job.opponent,
                "passed": not issues,
                "source": job.public_output.relative_to(ROOT).as_posix(),
                "source_sha256": sha256_file(job.public_output),
            }
        )
    passed = len(rows) == len(jobs) and not failures
    return {
        "schema_version": 1,
        "stage": "preflight",
        "status": "PASS" if passed else "FAIL",
        "passed": passed,
        "complete": len(rows) == len(jobs),
        "admission_decision": "admit_factorial_acquisition" if passed else "suppress_factorial",
        "protocol_commit": provenance["protocol_commit"],
        "execution_commit": provenance["execution_commit"],
        "expected_jobs": len(jobs),
        "completed_jobs": len(rows),
        "trajectory_units": len(rows) * 50,
        "executions": len(rows) * 150,
        "failures": failures,
        "rows": rows,
    }


def require_passing_preflight(
    protocol_commit: str,
    *,
    public_root: Path | None = None,
) -> dict[str, Any]:
    public_root = public_root or PUBLIC_ROOT
    summary_path = public_root / "preflight/summary.json"
    if not summary_path.is_file():
        raise ProtocolViolation("factorial suppressed: preflight summary is missing")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if (
        summary.get("status") != "PASS"
        or summary.get("passed") is not True
        or summary.get("complete") is not True
        or summary.get("expected_jobs") != 20
        or summary.get("completed_jobs") != 20
        or summary.get("protocol_commit") != protocol_commit
        or summary.get("failures")
    ):
        raise ProtocolViolation("factorial suppressed: complete passing preflight gate not established")
    for row in summary.get("rows", []):
        source = ROOT / str(row["source"])
        if not source.is_file() or sha256_file(source) != row.get("source_sha256"):
            raise ProtocolViolation(f"factorial suppressed: preflight source drift at {source}")
    if len(summary.get("rows", [])) != 20:
        raise ProtocolViolation("factorial suppressed: preflight source inventory is incomplete")
    return summary


def _factorial_issues(job: Job, payload: dict[str, Any], protocol_commit: str) -> list[str]:
    opponent = DETERMINISTIC_OPPONENTS[job.opponent]
    checks = {
        "engine_hash": payload.get("engine_sha256") == ENGINE_ARTIFACT.sha256,
        "production_before": payload.get("production_engine_sha256_before") == PRODUCTION_ARTIFACT.sha256,
        "production_after": payload.get("production_engine_sha256_after") == PRODUCTION_ARTIFACT.sha256,
        "production_preserved": payload.get("production_engine_preserved") is True,
        "candidate_hash": payload.get("candidate_sha256") == POLICIES[job.policy].sha256,
        "control_hash": payload.get("control_sha256") == POLICIES["c1"].sha256,
        "opponent_hash": payload.get("opponent_sha256") == opponent.sha256,
        "protocol": payload.get("protocol_id") == PROTOCOL_ID,
        "protocol_commit": payload.get("protocol_commit") == protocol_commit,
        "base_seed": payload.get("base_seed") == job.base_seed,
        "order_offset": payload.get("order_seed_offset") == ORDER_SEED_OFFSET,
        "pairs": payload.get("pairs_per_order") == 200,
        "orders": payload.get("actual_orders") == ["first", "second"],
        "games": payload.get("games") == 800,
        "workers": payload.get("workers") == 8,
        "max_decisions": payload.get("max_decisions") == MAX_DECISIONS,
        "opponent_env": payload.get("opponent_env") == opponent.env,
        "rows": len(payload.get("rows", [])) == 800,
    }
    issues = [name for name, passed in checks.items() if not passed]
    rows = payload.get("rows", [])
    if any(
        int(row.get("hero_policy_errors", 0)) or int(row.get("opponent_policy_errors", 0))
        for row in rows
    ):
        issues.append("policy_errors")
    expected_keys = {
        (order, index, arm)
        for order in ("first", "second")
        for index in range(200)
        for arm in ("candidate", "control")
    }
    observed_keys = {
        (str(row.get("actual_order")), int(row.get("pair_index", -1)), str(row.get("arm")))
        for row in rows
    }
    if observed_keys != expected_keys:
        issues.append("incomplete_or_duplicate_schedule")
    for row in rows:
        order = str(row.get("actual_order"))
        index = int(row.get("pair_index", -1))
        expected_seed = job.base_seed + (ORDER_SEED_OFFSET if order == "second" else 0) + index
        if (
            index not in range(200)
            or order not in {"first", "second"}
            or int(row.get("scheduled_seed", -1)) != expected_seed
            or int(row.get("engine_seed_uint32", -1)) != expected_seed
            or int(row.get("physical_seat", -1)) != index % 2
        ):
            issues.append("schedule_metadata")
            break
    return sorted(set(issues))


def _control_parity(payloads: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    fields = (
        "scheduled_seed",
        "engine_seed_uint32",
        "actual_order",
        "physical_seat",
        "win",
        "draw",
        "hero_policy_errors",
        "opponent_policy_errors",
        "decisions",
    )
    mismatches: list[dict[str, Any]] = []
    for opponent in DETERMINISTIC_OPPONENTS:
        controls: dict[str, dict[tuple[str, int], tuple[Any, ...]]] = {}
        for cell in ("c2", "c3", "c4"):
            rows = [row for row in payloads[f"{cell}_{opponent}"]["rows"] if row.get("arm") == "control"]
            controls[cell] = {
                (str(row["actual_order"]), int(row["pair_index"])): tuple(row[field] for field in fields)
                for row in rows
            }
        expected = {(order, index) for order in ("first", "second") for index in range(200)}
        if any(set(rows) != expected for rows in controls.values()):
            mismatches.append({"opponent": opponent, "reason": "incomplete_control_schedule"})
            continue
        for key in sorted(expected):
            signatures = {controls[cell][key] for cell in controls}
            if len(signatures) != 1:
                mismatches.append(
                    {"opponent": opponent, "actual_order": key[0], "pair_index": key[1]}
                )
    return mismatches


def build_factorial_summary(
    jobs: list[Job], payloads: dict[str, dict[str, Any]], provenance: dict[str, str]
) -> dict[str, Any]:
    rows = []
    failures = []
    for job in jobs:
        payload = payloads.get(job.key)
        if payload is None:
            failures.append({"job": job.key, "issues": ["missing_result"]})
            continue
        issues = _factorial_issues(job, payload, provenance["protocol_commit"])
        if issues:
            failures.append({"job": job.key, "issues": issues})
        rows.append(
            {
                "job": job.key,
                "cell": job.policy,
                "opponent": job.opponent,
                "passed": not issues,
                "source": job.public_output.relative_to(ROOT).as_posix(),
                "source_sha256": sha256_file(job.public_output),
            }
        )
    parity_mismatches = [] if failures or len(payloads) != len(jobs) else _control_parity(payloads)
    passed = len(rows) == len(jobs) and not failures and not parity_mismatches
    return {
        "schema_version": 1,
        "stage": "factorial",
        "status": "PASS" if passed else "SUPPRESSED",
        "passed": passed,
        "complete": len(rows) == len(jobs),
        "admission_decision": "admit_analysis" if passed else "suppress_all_factorial_contrasts",
        "protocol_commit": provenance["protocol_commit"],
        "execution_commit": provenance["execution_commit"],
        "expected_jobs": len(jobs),
        "completed_jobs": len(rows),
        "paired_units": len(rows) * 400,
        "games": len(rows) * 800,
        "c1_control_parity_passed": not parity_mismatches,
        "c1_control_mismatch_units": len(parity_mismatches),
        "first_c1_control_mismatches": parity_mismatches[:20],
        "failures": failures,
        "rows": rows,
    }


def _write_incomplete_summary(
    stage: str,
    provenance: dict[str, str],
    completed: list[str],
    error: Exception,
) -> None:
    filename = "summary.json" if stage == "preflight" else "acquisition_summary.json"
    write_json(
        PUBLIC_ROOT / stage / filename,
        {
            "schema_version": 1,
            "stage": stage,
            "status": "INCOMPLETE",
            "passed": False,
            "complete": False,
            "protocol_commit": provenance["protocol_commit"],
            "execution_commit": provenance["execution_commit"],
            "completed_jobs": completed,
            "error": str(error),
        },
    )


def run_preflight(
    provenance: dict[str, str],
    *,
    force: bool,
    command_runner: Callable[[Iterable[str]], None] = run_command,
) -> dict[str, Any]:
    prepare_output_roots("preflight", force=force)
    jobs = preflight_jobs(provenance["protocol_commit"])
    payloads: dict[str, dict[str, Any]] = {}
    try:
        for index, job in enumerate(jobs, start=1):
            emit("stage_progress", stage="preflight", job=index, total=len(jobs))
            payloads[job.key] = execute_job(job, command_runner=command_runner)
    except Exception as exc:
        _write_incomplete_summary("preflight", provenance, list(payloads), exc)
        raise
    summary = build_preflight_summary(jobs, payloads, provenance)
    write_json(PUBLIC_ROOT / "preflight/summary.json", summary)
    emit("stage_complete", stage="preflight", status=summary["status"])
    return summary


def run_stress(
    provenance: dict[str, str],
    *,
    force: bool,
    command_runner: Callable[[Iterable[str]], None] = run_command,
) -> dict[str, Any]:
    prepare_output_roots("stress", force=force)
    jobs = stress_jobs(provenance["protocol_commit"])
    payloads: dict[str, dict[str, Any]] = {}
    try:
        for index, job in enumerate(jobs, start=1):
            emit("stage_progress", stage="stress", job=index, total=len(jobs))
            payload = execute_job(job, command_runner=command_runner)
            issues = _proof_issues(job, payload, stress=True)
            if payload.get("protocol_commit") != provenance["protocol_commit"]:
                issues.append("protocol_commit")
            if issues:
                raise ProtocolViolation(f"{job.key}: invalid stress acquisition: {issues}")
            payloads[job.key] = payload
    except Exception as exc:
        _write_incomplete_summary("stress", provenance, list(payloads), exc)
        raise
    exact_parity = all(payload.get("passed") is True for payload in payloads.values())
    summary = {
        "schema_version": 1,
        "stage": "stress",
        "status": "TRACE_PARITY" if exact_parity else "TRACE_DIVERGENCE",
        "complete": len(payloads) == len(jobs),
        "protocol_commit": provenance["protocol_commit"],
        "execution_commit": provenance["execution_commit"],
        "expected_jobs": len(jobs),
        "completed_jobs": len(payloads),
        "exact_reproducibility_passed": exact_parity,
        "rows": [
            {
                "opponent": job.opponent,
                "passed": bool(payloads[job.key].get("passed")),
                "restricted_source": job.local_output.relative_to(ROOT).as_posix(),
                "restricted_source_sha256": sha256_file(job.local_output),
                "safe_source": job.public_output.relative_to(ROOT).as_posix(),
                "safe_source_sha256": sha256_file(job.public_output),
            }
            for job in jobs
        ],
    }
    write_json(PUBLIC_ROOT / "stress/acquisition_summary.json", summary)
    emit("stage_complete", stage="stress", status=summary["status"])
    return summary


def run_factorial(
    provenance: dict[str, str],
    *,
    force: bool,
    command_runner: Callable[[Iterable[str]], None] = run_command,
) -> dict[str, Any]:
    require_passing_preflight(provenance["protocol_commit"])
    prepare_output_roots("factorial", force=force)
    jobs = factorial_jobs(provenance["protocol_commit"])
    payloads: dict[str, dict[str, Any]] = {}
    try:
        for index, job in enumerate(jobs, start=1):
            emit("stage_progress", stage="factorial", job=index, total=len(jobs))
            payloads[job.key] = execute_job(job, command_runner=command_runner)
    except Exception as exc:
        _write_incomplete_summary("factorial", provenance, list(payloads), exc)
        raise
    summary = build_factorial_summary(jobs, payloads, provenance)
    write_json(PUBLIC_ROOT / "factorial/acquisition_summary.json", summary)
    emit("stage_complete", stage="factorial", status=summary["status"])
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("preflight", "stress", "factorial", "all"))
    parser.add_argument(
        "--force",
        action="store_true",
        help="archive existing stage outputs under ignored artifacts and acquire the stage again",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        validate_protocol_contract()
        provenance = validate_repository_provenance()
        validate_output_policy()
        validate_artifacts(args.stage)
        emit("provenance_passed", **provenance)

        if args.stage == "preflight":
            summary = run_preflight(provenance, force=args.force)
            return 0 if summary["passed"] else 1
        if args.stage == "stress":
            run_stress(provenance, force=args.force)
            return 0
        if args.stage == "factorial":
            summary = run_factorial(provenance, force=args.force)
            return 0 if summary["passed"] else 1

        preflight = run_preflight(provenance, force=args.force)
        run_stress(provenance, force=args.force)
        if not preflight["passed"]:
            raise ProtocolViolation("factorial suppressed by failed preflight; stress stage completed")
        factorial = run_factorial(provenance, force=args.force)
        return 0 if factorial["passed"] else 1
    except ProtocolViolation as exc:
        emit("acquisition_refused", reason=str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
