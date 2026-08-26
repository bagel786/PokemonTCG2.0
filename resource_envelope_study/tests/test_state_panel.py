from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
from jsonschema.validators import validator_for

from resource_envelope_study.calibration import (
    CalibrationConfig,
    CalibrationState,
    build_calibration_manifest,
)
from resource_envelope_study.canonical import hash_file, hash_json, write_canonical_json
from resource_envelope_study.repeatability import (
    EnvelopeSpec,
    FrozenStateSpec,
    RepeatabilityConfig,
    build_repeatability_manifest,
)
from resource_envelope_study.state_panel import (
    DEFAULT_SELECTION_BANKS,
    CaptureRequest,
    FrozenResourceProfile,
    PanelRuntime,
    StatePanelError,
    _spawn_capture,
    _spawn_panel_case,
    _terminate_then_kill,
    build_capture_manifest,
    build_state_bank_preallocation,
    build_state_selection_bank,
    capture_states_isolated,
    execute_calibration_manifest,
    execute_repeatability_manifest,
    synthetic_panel_entrypoint,
    validate_disjoint_selection_banks,
    validate_repeatability_execution_inputs,
)


AGENTS = ("one_ply_value_v1", "flat_rollout_v1", "puct_tree_v1")
SCHEMA_ROOT = Path(__file__).resolve().parents[1] / "schemas" / "v1"


def _capture_request(bank_name: str, index: int) -> CaptureRequest:
    repeatability = bank_name.startswith("repeatability_")
    history_length = 1 if repeatability else 0
    state_bytes = f"opaque-state::{bank_name}\n".encode("ascii")
    history_bytes = (
        f"opaque-history::{bank_name}\n".encode("ascii") if repeatability else b""
    )
    return CaptureRequest(
        capture_id=f"capture-{bank_name}",
        state_id=f"state-{bank_name}",
        source_game_id=f"source-{bank_name}",
        state_seed=100_000 + index,
        history_seed=200_000 + index,
        history_length=history_length,
        capture_kwargs={
            "target_eligible_index": history_length,
            "physical_seat": index % 2,
            "play_order": (index // 2) % 2,
            "state_bytes_hex": state_bytes.hex(),
            "history_bytes_hex": history_bytes.hex(),
        },
    )


def _profiles(root: Path) -> tuple[dict[str, Path], tuple[EnvelopeSpec, ...], Path, str]:
    cells = [
        (budget, load, lifecycle)
        for budget in ("wall_clock", "fixed_work")
        for load in ("idle", "loaded")
        for lifecycle in ("fresh", "persistent")
    ]
    files: dict[str, Path] = {}
    envelopes: list[EnvelopeSpec] = []
    for budget, load, lifecycle in cells:
        envelope_id = f"{budget}-{load}-{lifecycle}"
        profile = FrozenResourceProfile(
            schema_version="state-panel-resource-profile-1.0.0",
            envelope_id=envelope_id,
            budget_mode=budget,
            load_condition=load,
            lifecycle=lifecycle,
            target_cpus=(0,),
            worker_count=0 if load == "idle" else 1,
            chunk_iterations=100,
            readiness_timeout_s=1.0,
        )
        profile.validate()
        path = root / f"profile-{envelope_id}.json"
        digest = write_canonical_json(path, asdict(profile))
        files[envelope_id] = path
        envelopes.append(EnvelopeSpec(envelope_id, budget, load, lifecycle, digest))
    calibration_profile = FrozenResourceProfile(
        schema_version="state-panel-resource-profile-1.0.0",
        envelope_id="calibration-idle-fresh-wall",
        budget_mode="wall_clock",
        load_condition="idle",
        lifecycle="fresh",
        target_cpus=(0,),
        worker_count=0,
        chunk_iterations=100,
        readiness_timeout_s=1.0,
    )
    calibration_path = root / "profile-calibration.json"
    calibration_hash = write_canonical_json(calibration_path, asdict(calibration_profile))
    return files, tuple(envelopes), calibration_path, calibration_hash


def _build_execution_manifest(
    bank_name: str,
    request: CaptureRequest,
    inventory: dict[str, Any],
    envelopes: tuple[EnvelopeSpec, ...],
    index: int,
) -> dict[str, Any]:
    capture = inventory["captured_states"][0]
    if bank_name.endswith("calibration"):
        role = "deadline_selection" if bank_name == "deadline_calibration" else "fixed_work"
        config = CalibrationConfig(
            bank_id=bank_name,
            role=role,
            master_seed=1_000_000 + index,
            agents=AGENTS,
            deadline_ms=None if role == "deadline_selection" else 50,
            deadline_selection_hash=None if role == "deadline_selection" else "d" * 64,
        )
        exclusions: dict[str, tuple[int, ...]] = {
            "gate": (),
            "final": (),
            "reserve": (),
        }
        if role == "fixed_work":
            exclusions["deadline_calibration"] = ()
        return build_calibration_manifest(
            config,
            [
                CalibrationState(
                    state_id=request.state_id,
                    source_game_id=request.source_game_id,
                    state_artifact_sha256=capture["state_artifact_sha256"],
                    state_seed=request.state_seed,
                    eligibility_sha256=hash_json({"eligible": request.state_id}),
                )
            ],
            excluded_seed_ledger=exclusions,
        )
    return build_repeatability_manifest(
        RepeatabilityConfig(
            bank_id=bank_name,
            master_seed=2_000_000 + index,
            agents=AGENTS,
            envelopes=envelopes,
            wall_clock_budget_ns=1_000,
            fixed_work_by_agent={agent: number for agent, number in zip(AGENTS, (2, 3, 4))},
            target_state_count=1,
            load_batch_count=10,
            persistent_sequence_length=8,
        ),
        [
            FrozenStateSpec(
                state_id=request.state_id,
                source_game_id=request.source_game_id,
                state_artifact_sha256=capture["state_artifact_sha256"],
                state_seed=request.state_seed,
                history_prefix_sha256=capture["history_prefix_sha256"],
                history_seed=request.history_seed,
                history_length=request.history_length,
                pseudo_sequence_slot=request.history_length,
            )
        ],
        excluded_seed_ledger={
            "calibration": (),
            "gate": (),
            "final": (),
            "reserve": (),
        },
    )


def _full_ledger(root: Path) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    requests = {
        bank_name: [_capture_request(bank_name, index)]
        for index, bank_name in enumerate(DEFAULT_SELECTION_BANKS)
    }
    purposes = {
        bank_name: (
            "calibration" if bank_name.endswith("calibration") else "repeatability"
        )
        for bank_name in DEFAULT_SELECTION_BANKS
    }
    preallocation = build_state_bank_preallocation(requests, purposes=purposes)
    preallocation_path = root / "state-bank-preallocation.json"
    preallocation_hash = write_canonical_json(preallocation_path, preallocation)
    profile_files, envelopes, calibration_profile, calibration_profile_hash = _profiles(root)
    inventories: dict[str, dict[str, Any]] = {}
    inventory_paths: dict[str, Path] = {}
    execution_manifests: dict[str, dict[str, Any]] = {}
    execution_paths: dict[str, Path] = {}
    wrapper_paths: dict[str, str] = {}
    wrapper_hashes: dict[str, str] = {}
    for index, bank_name in enumerate(DEFAULT_SELECTION_BANKS):
        capture_manifest = build_capture_manifest(
            bank_name,
            purposes[bank_name],
            requests[bank_name],
            preallocation_manifest=preallocation,
            preallocation_file_sha256=preallocation_hash,
        )
        capture_manifest_path = root / f"capture-{bank_name}.json"
        capture_manifest_hash = write_canonical_json(capture_manifest_path, capture_manifest)
        capture_output = root / f"captures-{bank_name}"
        inventory = capture_states_isolated(
            capture_manifest_path,
            expected_manifest_sha256=capture_manifest_hash,
            preallocation_path=preallocation_path,
            output_dir=capture_output,
            entrypoint=(
                "resource_envelope_study.state_panel:synthetic_capture_entrypoint"
            ),
            entrypoint_payload={"bank": bank_name},
            execution_enabled=True,
            test_mode=True,
            worker_timeout_s=30.0,
        )
        inventory_path = capture_output / "capture_inventory.json"
        inventories[bank_name] = inventory
        inventory_paths[bank_name] = inventory_path
        execution = _build_execution_manifest(
            bank_name,
            requests[bank_name][0],
            inventory,
            envelopes,
            index,
        )
        execution_path = root / f"execution-{bank_name}.json"
        execution_hash = write_canonical_json(execution_path, execution)
        execution_manifests[bank_name] = execution
        execution_paths[bank_name] = execution_path
        wrapper = build_state_selection_bank(
            bank_name,
            execution_manifest_path=execution_path,
            execution_manifest_sha256=execution_hash,
            capture_inventory_path=inventory_path,
            capture_inventory_sha256=hash_file(inventory_path),
        )
        wrapper_path = root / f"bank-{bank_name}.json"
        wrapper_hash = write_canonical_json(wrapper_path, wrapper)
        wrapper_paths[bank_name] = str(wrapper_path)
        wrapper_hashes[bank_name] = wrapper_hash
    return {
        "requests": requests,
        "preallocation": preallocation,
        "preallocation_path": preallocation_path,
        "inventories": inventories,
        "inventory_paths": inventory_paths,
        "execution_manifests": execution_manifests,
        "execution_paths": execution_paths,
        "wrapper_paths": wrapper_paths,
        "wrapper_hashes": wrapper_hashes,
        "profile_files": profile_files,
        "calibration_profile": calibration_profile,
        "calibration_profile_hash": calibration_profile_hash,
    }


def _runtime(bundle: dict[str, Any], *, enabled: bool) -> PanelRuntime:
    return PanelRuntime(
        entrypoint="resource_envelope_study.state_panel:synthetic_panel_entrypoint",
        entrypoint_payload={"unit_ns": 10},
        target_cpus=(0,),
        load_workers=1,
        worker_timeout_s=30.0,
        execution_enabled=enabled,
        test_mode=True,
        require_linux_affinity=False,
        selection_bank_files=bundle["wrapper_paths"],
        selection_bank_sha256=bundle["wrapper_hashes"],
    )


def _state_files(bundle: dict[str, Any], bank_name: str) -> tuple[dict[str, Path], dict[str, Path]]:
    request = bundle["requests"][bank_name][0]
    capture_dir = bundle["inventory_paths"][bank_name].parent / request.state_id
    return ({request.state_id: capture_dir / "state.raw"}, {request.state_id: capture_dir / "history.raw"})


def test_preallocation_capture_execution_ledger_builds_without_cycles(tmp_path: Path) -> None:
    bundle = _full_ledger(tmp_path / "ledger")
    observed = validate_disjoint_selection_banks(
        bundle["wrapper_paths"], bundle["wrapper_hashes"]
    )
    assert observed == bundle["wrapper_hashes"]
    assert bundle["preallocation"]["required_banks"] == list(DEFAULT_SELECTION_BANKS)

    bank_name = "repeatability_pilot"
    state_files, history_files = _state_files(bundle, bank_name)
    prepared = validate_repeatability_execution_inputs(
        bundle["execution_paths"][bank_name],
        expected_manifest_sha256=hash_file(bundle["execution_paths"][bank_name]),
        state_files=state_files,
        history_files=history_files,
        resource_profile_files=bundle["profile_files"],
        runtime=_runtime(bundle, enabled=False),
    )
    assert prepared["state_bank_name"] == bank_name


def test_capture_is_once_only_and_tamper_does_not_recapture(tmp_path: Path) -> None:
    bundle = _full_ledger(tmp_path / "ledger")
    bank_name = "repeatability_pilot"
    request = bundle["requests"][bank_name][0]
    capture_dir = bundle["inventory_paths"][bank_name].parent / request.state_id
    commit_path = capture_dir / "capture_commit.json"
    first_commit = commit_path.read_bytes()
    state_path = capture_dir / "state.raw"
    state_path.write_bytes(state_path.read_bytes() + b"tampered")
    capture_manifest_path = tmp_path / "ledger" / f"capture-{bank_name}.json"
    with pytest.raises(StatePanelError, match="captured raw bytes changed"):
        capture_states_isolated(
            capture_manifest_path,
            expected_manifest_sha256=hash_file(capture_manifest_path),
            preallocation_path=bundle["preallocation_path"],
            output_dir=bundle["inventory_paths"][bank_name].parent,
            entrypoint=(
                "resource_envelope_study.state_panel:synthetic_capture_entrypoint"
            ),
            entrypoint_payload={"bank": bank_name},
            execution_enabled=True,
            test_mode=True,
            worker_timeout_s=30.0,
        )
    assert commit_path.read_bytes() == first_commit


class _FakeEnvelope:
    compliance_checks = 0

    def __init__(self, profile, load_seed, load_batch_id, *, require_affinity=False):
        self.profile = profile
        self.load_seed = load_seed
        self.load_batch_id = load_batch_id
        self.metadata: dict[str, Any] = {}

    def __enter__(self):
        self.metadata = {
            "schema_version": "resource-episode-1.0.0",
            "load_batch_id": self.load_batch_id,
            "load_seed": self.load_seed,
            "profile": asdict(self.profile),
            "workers": [],
            "benchmark_workers": [],
            "cleanup_succeeded": False,
            "cleanup_errors": [],
        }
        return self

    def assert_compliant(self, *, period_complete=False):
        type(self).compliance_checks += 1

    def record_benchmark_worker(self, runtime):
        self.metadata["benchmark_workers"].append(dict(runtime))

    def __exit__(self, exc_type, exc, traceback):
        self.metadata["cleanup_succeeded"] = True


def _fake_spawn_factory(*, fail_case: str | None = None):
    calls: list[str] = []

    def fake_spawn(row, *, state_path, history_path, runtime):
        case_id = row.get("repeatability_case_id", row.get("calibration_case_id"))
        calls.append(case_id)
        if case_id == fail_case:
            raise StatePanelError("synthetic child failure")
        state_bytes = state_path.read_bytes()
        history_bytes = None if history_path is None else history_path.read_bytes()
        result = synthetic_panel_entrypoint(
            row, state_bytes, history_bytes, runtime.entrypoint_payload
        )
        pid = 50_000 + len(calls)
        return {
            "ok": True,
            "result": result,
            "state_bytes_sha256": hash_file(state_path),
            "history_bytes_sha256": (
                None if history_path is None else hash_file(history_path)
            ),
            "runtime": {
                "observed_process_id": pid,
                "spawned_process_id": pid,
                "observed_affinity": [0],
                "exitcode": 0,
            },
        }

    return calls, fake_spawn


def test_repeatability_executes_all_eight_envelopes_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import resource_envelope_study.state_panel as panel

    bundle = _full_ledger(tmp_path / "ledger")
    bank_name = "repeatability_pilot"
    state_files, history_files = _state_files(bundle, bank_name)
    calls, fake_spawn = _fake_spawn_factory()
    _FakeEnvelope.compliance_checks = 0
    monkeypatch.setattr(panel, "ResourceEnvelope", _FakeEnvelope)
    monkeypatch.setattr(panel, "_spawn_panel_case", fake_spawn)
    summary = execute_repeatability_manifest(
        bundle["execution_paths"][bank_name],
        expected_manifest_sha256=hash_file(bundle["execution_paths"][bank_name]),
        state_files=state_files,
        history_files=history_files,
        resource_profile_files=bundle["profile_files"],
        output_dir=tmp_path / "repeat-output",
        runtime=_runtime(bundle, enabled=True),
    )
    assert summary["terminal_cases"] == 240
    assert summary["committed_groups"] == 10
    assert summary["resource_episode_count"] == 20
    assert len(calls) == len(set(calls)) == 240
    assert _FakeEnvelope.compliance_checks == 2 * 240 + 20


def test_invalid_pair_is_terminally_committed_then_resume_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import resource_envelope_study.state_panel as panel

    bundle = _full_ledger(tmp_path / "ledger")
    bank_name = "repeatability_pilot"
    manifest = bundle["execution_manifests"][bank_name]
    first_case = min(manifest["rows"], key=lambda row: row["execution_index"])[
        "repeatability_case_id"
    ]
    state_files, history_files = _state_files(bundle, bank_name)
    _calls, fake_spawn = _fake_spawn_factory(fail_case=first_case)
    monkeypatch.setattr(panel, "ResourceEnvelope", _FakeEnvelope)
    monkeypatch.setattr(panel, "_spawn_panel_case", fake_spawn)
    arguments = {
        "manifest_path": bundle["execution_paths"][bank_name],
        "expected_manifest_sha256": hash_file(bundle["execution_paths"][bank_name]),
        "state_files": state_files,
        "history_files": history_files,
        "resource_profile_files": bundle["profile_files"],
        "output_dir": tmp_path / "invalid-output",
        "runtime": _runtime(bundle, enabled=True),
    }
    with pytest.raises(StatePanelError, match="stopped after invalid atomic group"):
        execute_repeatability_manifest(**arguments)
    commits = (tmp_path / "invalid-output" / "panel_batch_commits.jsonl").read_text()
    results = (tmp_path / "invalid-output" / "panel_results.jsonl").read_text()
    assert '"batch_status":"infrastructure_invalid"' in commits
    assert '"terminal_status":"infrastructure_error"' in results
    with pytest.raises(StatePanelError, match="infrastructure_invalid"):
        execute_repeatability_manifest(**arguments)


def test_calibration_executor_emits_selector_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import resource_envelope_study.state_panel as panel

    bundle = _full_ledger(tmp_path / "ledger")
    bank_name = "fixed_work_calibration"
    state_files, _history_files = _state_files(bundle, bank_name)
    calls, fake_spawn = _fake_spawn_factory()
    monkeypatch.setattr(panel, "ResourceEnvelope", _FakeEnvelope)
    monkeypatch.setattr(panel, "_spawn_panel_case", fake_spawn)
    summary = execute_calibration_manifest(
        bundle["execution_paths"][bank_name],
        expected_manifest_sha256=hash_file(bundle["execution_paths"][bank_name]),
        state_files=state_files,
        resource_profile_file=bundle["calibration_profile"],
        resource_profile_sha256=bundle["calibration_profile_hash"],
        output_dir=tmp_path / "calibration-output",
        runtime=_runtime(bundle, enabled=True),
    )
    assert summary["terminal_cases"] == 3
    assert len(calls) == 3
    assert (tmp_path / "calibration-output" / "calibration_records.json").is_file()


def test_scientific_runtime_rejects_non_native_entrypoint() -> None:
    runtime = PanelRuntime(
        entrypoint="resource_envelope_study.state_panel:synthetic_panel_entrypoint",
        entrypoint_payload={},
        target_cpus=(0,),
        load_workers=1,
        test_mode=False,
        selection_bank_files={name: "missing" for name in DEFAULT_SELECTION_BANKS},
        selection_bank_sha256={name: "0" * 64 for name in DEFAULT_SELECTION_BANKS},
    )
    with pytest.raises(ValueError, match="test-only|study-owned Pokémon entrypoint"):
        runtime.validate()


def test_state_panel_json_schemas_are_valid() -> None:
    names = (
        "state-bank-preallocation.schema.json",
        "state-capture-manifest.schema.json",
        "state-selection-bank.schema.json",
        "state-panel-resource-profile.schema.json",
        "state-panel-result.schema.json",
        "state-panel-resource-episode.schema.json",
        "state-panel-batch-commit.schema.json",
        "state-panel-summary.schema.json",
        "state-panel-run-config.schema.json",
        "state-panel-history-prefix.schema.json",
        "state-panel-invalid-attempt.schema.json",
    )
    for name in names:
        schema = json.loads((SCHEMA_ROOT / name).read_text(encoding="utf-8"))
        validator_for(schema).check_schema(schema)


def test_failed_worker_escalates_terminate_to_kill_before_return() -> None:
    class StubbornProcess:
        def __init__(self) -> None:
            self.alive = True
            self.events: list[str] = []

        def is_alive(self) -> bool:
            return self.alive

        def terminate(self) -> None:
            self.events.append("terminate")

        def kill(self) -> None:
            self.events.append("kill")
            self.alive = False

        def join(self, timeout: float) -> None:
            self.events.append(f"join:{timeout}")

    process = StubbornProcess()
    _terminate_then_kill(process, label="test worker")
    assert process.events == ["terminate", "join:5.0", "kill", "join:5.0"]
    assert not process.is_alive()


@pytest.mark.parametrize("spawn_kind", ["capture", "panel"])
def test_parent_exception_kills_child_before_queue_cleanup(
    spawn_kind: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import resource_envelope_study.state_panel as panel

    events: list[str] = []

    class FakeProcess:
        pid = 4242
        exitcode = None

        def __init__(self) -> None:
            self.alive = False

        def start(self) -> None:
            self.alive = True
            events.append("start")

        def is_alive(self) -> bool:
            return self.alive

        def terminate(self) -> None:
            events.append("terminate")

        def kill(self) -> None:
            events.append("kill")
            self.alive = False

        def join(self, timeout: float) -> None:
            events.append(f"join:{timeout}")

    process = FakeProcess()

    class FakeQueue:
        def get(self, timeout: float):
            events.append("get")
            raise KeyboardInterrupt()

        def close(self) -> None:
            assert not process.is_alive()
            events.append("queue-close")

        def join_thread(self) -> None:
            assert not process.is_alive()
            events.append("queue-join")

    class FakeContext:
        def Queue(self):
            return FakeQueue()

        def Process(self, **kwargs):
            return process

    monkeypatch.setattr(panel.mp, "get_context", lambda _method: FakeContext())
    with pytest.raises(KeyboardInterrupt):
        if spawn_kind == "capture":
            _spawn_capture(
                {"state_id": "state-x"},
                entrypoint="resource_envelope_study.state_panel:synthetic_capture_entrypoint",
                payload={},
                timeout_s=1.0,
            )
        else:
            state_path = tmp_path / "state.raw"
            state_path.write_bytes(b"x")
            _spawn_panel_case(
                {
                    "calibration_case_id": "case-x",
                    "state_id": "state-x",
                },
                state_path=state_path,
                history_path=None,
                runtime=PanelRuntime(
                    entrypoint=(
                        "resource_envelope_study.state_panel:synthetic_panel_entrypoint"
                    ),
                    entrypoint_payload={},
                    target_cpus=(0,),
                    load_workers=1,
                    test_mode=True,
                    require_linux_affinity=False,
                    selection_bank_files={name: "x" for name in DEFAULT_SELECTION_BANKS},
                    selection_bank_sha256={name: "0" * 64 for name in DEFAULT_SELECTION_BANKS},
                ),
            )
    assert events[-4:] == ["kill", "join:5.0", "queue-close", "queue-join"]
