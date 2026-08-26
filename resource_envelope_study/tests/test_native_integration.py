from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from resource_envelope_study.canonical import hash_json, sha256_bytes
from resource_envelope_study.capture import (
    CAPTURE_SCHEMA_VERSION,
    CapturedDecisionState,
    assert_independent_recapture_semantics,
    assert_semantic_replay,
    load_frozen_captured_state,
    write_frozen_captured_state,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENGINE = ROOT / "artifacts/deterministic_engine/bin/libcg_seeded.dylib"
ENGINE = Path(os.environ.get("RESOURCE_ENVELOPE_ENGINE", DEFAULT_ENGINE))
DECK = ROOT / "artifacts/grim_final_escape/candidate/deck.csv"
MODEL = ROOT / "artifacts/grim_final_escape/candidate/policy_weights.npz"
REQUIRE_NATIVE = os.environ.get("RESOURCE_ENVELOPE_REQUIRE_NATIVE_TESTS") == "1"
FIXED_REPLAY_UNITS = 8
REPLAY_AGENT_SEEDS = (778_899, 778_900, 778_901, 778_902, 778_903)


def _native_available() -> bool:
    return ENGINE.is_file() and DECK.is_file() and MODEL.is_file()


native_test = pytest.mark.skipif(
    not _native_available() and not REQUIRE_NATIVE,
    reason="evaluation-only seeded engine is unavailable",
)


CAPTURE_SCRIPT = r'''
import json, os
from pathlib import Path
from resource_envelope_study.capture import capture_anchor_state, write_frozen_captured_state
root=Path(os.environ["RESOURCE_ENVELOPE_ROOT"])
engine=Path(os.environ["RESOURCE_ENVELOPE_ENGINE"])
artifact=Path(os.environ["RESOURCE_ENVELOPE_CAPTURE"])
deck=root/"artifacts/grim_final_escape/candidate/deck.csv"
model=root/"artifacts/grim_final_escape/candidate/policy_weights.npz"
state=capture_anchor_state(engine_path=engine,deck_path=deck,model_path=model,source_environment_seed=424242,target_eligible_index=0,physical_seat=0,play_order=0)
file_sha256=write_frozen_captured_state(artifact,state)
print(json.dumps({"artifact_hash":state.artifact_hash,"file_sha256":file_sha256,"public_semantic_hash":state.public_semantic_hash,"opaque_sha256":state.search_begin_input_hash,"opaque_byte_count":state.search_begin_input_byte_count},sort_keys=True,separators=(",",":")))
'''


REPLAY_SCRIPT = r'''
import json, os
from pathlib import Path
from resource_envelope_study.adapters.native_backend import SeededGameBackend
from resource_envelope_study.adapters.pokemon import PokemonSearchAdapter, default_agent_configs
from resource_envelope_study.capture import load_frozen_captured_state
from resource_envelope_study.runner import CaseContext, run_decision
from resource_envelope_study.stop_policy import FixedWorkStop
root=Path(os.environ["RESOURCE_ENVELOPE_ROOT"])
engine=Path(os.environ["RESOURCE_ENVELOPE_ENGINE"])
artifact=Path(os.environ["RESOURCE_ENVELOPE_CAPTURE"])
expected_sha256=os.environ["RESOURCE_ENVELOPE_CAPTURE_SHA256"]
deck=root/"artifacts/grim_final_escape/candidate/deck.csv"
model=root/"artifacts/grim_final_escape/candidate/policy_weights.npz"
state=load_frozen_captured_state(artifact,expected_file_sha256=expected_sha256)
bootstrap=SeededGameBackend(engine)
configs=default_agent_configs(hero_deck_path=str(deck),hero_model_path=str(model),opponent_deck_path=str(deck),opponent_model_path=str(model),seeded_engine_path=str(engine),initialize_engine=False)
seeds=(778899,778900,778901,778902,778903)
rows=[]
for config in configs:
    adapter=PokemonSearchAdapter(config)
    for repeat_index, seed in enumerate(seeds):
        result=run_decision(adapter,state.raw_state,FixedWorkStop(8),CaseContext(f"replay-{config.agent_id}-{seed}","frozen-replay",repeat_index,"idle","fresh",f"fresh-{repeat_index}",f"process-{repeat_index}",0,"load-none",seed,True))
        rows.append({"agent_id":config.agent_id,"agent_seed":seed,"state_hash":result.state_hash,"selected_action_hash":result.selected_action_hash,"completed_work_units":result.completed_work_units,"terminal_status":result.terminal_status,"cleanup_succeeded":result.cleanup_succeeded})
print(json.dumps({"artifact_hash":state.artifact_hash,"file_sha256":expected_sha256,"public_semantic_hash":state.public_semantic_hash,"opaque_sha256":state.search_begin_input_hash,"opaque_byte_count":state.search_begin_input_byte_count,"results":rows},sort_keys=True,separators=(",",":")))
'''


INSTRUMENTATION_SCRIPT = r'''
import json, os
from pathlib import Path
from resource_envelope_study.adapters.native_backend import SeededGameBackend
from resource_envelope_study.adapters.pokemon import PokemonSearchAdapter, default_agent_configs
from resource_envelope_study.capture import load_frozen_captured_state
from resource_envelope_study.runner import CaseContext, run_decision
from resource_envelope_study.stop_policy import FixedWorkStop
root=Path(os.environ["RESOURCE_ENVELOPE_ROOT"])
engine=Path(os.environ["RESOURCE_ENVELOPE_ENGINE"])
artifact=Path(os.environ["RESOURCE_ENVELOPE_CAPTURE"])
state=load_frozen_captured_state(artifact,expected_file_sha256=os.environ["RESOURCE_ENVELOPE_CAPTURE_SHA256"])
deck=root/"artifacts/grim_final_escape/candidate/deck.csv"
model=root/"artifacts/grim_final_escape/candidate/policy_weights.npz"
bootstrap=SeededGameBackend(engine)
configs=default_agent_configs(hero_deck_path=str(deck),hero_model_path=str(model),opponent_deck_path=str(deck),opponent_model_path=str(model),seeded_engine_path=str(engine),initialize_engine=False)
config=next(value for value in configs if value.agent_id=="puct_tree_v1")
on=run_decision(PokemonSearchAdapter(config),state.raw_state,FixedWorkStop(3),CaseContext("c-on","b",0,"idle","fresh","f","p-on",0,"l",778899,True))
off=run_decision(PokemonSearchAdapter(config),state.raw_state,FixedWorkStop(3),CaseContext("c-off","b",0,"idle","fresh","f","p-off",0,"l",778899,False))
print(json.dumps({"state":on.state_hash,"on_action":on.selected_action_hash,"off_action":off.selected_action_hash,"on_work":on.completed_work_units,"off_work":off.completed_work_units,"on_simulations":on.completed_simulations,"off_simulations":off.completed_simulations,"on_status":on.terminal_status,"off_status":off.terminal_status,"on_cleanup":on.cleanup_succeeded,"off_cleanup":off.cleanup_succeeded},sort_keys=True,separators=(",",":")))
'''


def _run_script(
    script: str,
    artifact: Path,
    *,
    expected_sha256: str | None = None,
) -> str:
    if not _native_available():
        pytest.fail("native integration was required but artifacts are unavailable")
    environment = dict(os.environ)
    environment.update(
        {
            "PYTHONPATH": f"{ROOT / 'vendor'}:{ROOT}",
            "PYTHONDONTWRITEBYTECODE": "1",
            "RESOURCE_ENVELOPE_ROOT": str(ROOT),
            "RESOURCE_ENVELOPE_ENGINE": str(ENGINE),
            "RESOURCE_ENVELOPE_CAPTURE": str(artifact),
        }
    )
    if expected_sha256 is not None:
        environment["RESOURCE_ENVELOPE_CAPTURE_SHA256"] = expected_sha256
    return subprocess.run(
        [sys.executable, "-B", "-c", script],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
    ).stdout.strip()


def _capture_to(path: Path) -> dict[str, object]:
    return json.loads(_run_script(CAPTURE_SCRIPT, path))


def _replay(path: Path, file_sha256: str) -> dict[str, object]:
    return json.loads(_run_script(REPLAY_SCRIPT, path, expected_sha256=file_sha256))


@pytest.fixture(scope="module")
def frozen_capture(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, object]]:
    path = tmp_path_factory.mktemp("frozen-native-state") / "captured-state.json"
    return path, _capture_to(path)


def _synthetic_capture(opaque: str) -> CapturedDecisionState:
    raw_state = {
        "current": {"yourIndex": 0, "turn": 4},
        "select": {"context": 3, "minCount": 1, "maxCount": 1},
        "search_begin_input": opaque,
    }
    opaque_bytes = opaque.encode("ascii")
    return CapturedDecisionState(
        schema_version=CAPTURE_SCHEMA_VERSION,
        state_id="state-test",
        source_game_id="source-test",
        source_environment_seed=123,
        source_physical_seat=0,
        source_play_order=0,
        target_eligible_index=0,
        observed_eligible_index=0,
        history_prefix=(),
        public_semantic_hash=hash_json(
            {key: value for key, value in raw_state.items() if key != "search_begin_input"}
        ),
        search_begin_input_hash=sha256_bytes(opaque_bytes),
        search_begin_input_byte_count=len(opaque_bytes),
        raw_state=raw_state,
    )


def test_capture_contract_separates_frozen_bytes_from_independent_recapture(
    tmp_path: Path,
) -> None:
    frozen = _synthetic_capture("AAAA-tail-one")
    recaptured = _synthetic_capture("AAAA-tail-two")

    assert_independent_recapture_semantics(frozen, recaptured)
    with pytest.raises(RuntimeError, match="semantic replay mismatch"):
        assert_semantic_replay(frozen, recaptured)

    artifact = tmp_path / "frozen-capture.json"
    file_sha256 = write_frozen_captured_state(artifact, frozen)
    loaded = load_frozen_captured_state(
        artifact,
        expected_file_sha256=file_sha256,
    )
    assert_semantic_replay(frozen, loaded)
    assert loaded.search_begin_input_bytes == b"AAAA-tail-one"

    payload = json.loads(artifact.read_text(encoding="ascii"))
    artifact.write_text(json.dumps(payload, indent=2), encoding="ascii")
    with pytest.raises(RuntimeError, match="not canonical JSON bytes"):
        load_frozen_captured_state(artifact)


@native_test
def test_native_instrumentation_preserves_fixed_work_action(
    frozen_capture: tuple[Path, dict[str, object]],
) -> None:
    path, metadata = frozen_capture
    row = json.loads(
        _run_script(
            INSTRUMENTATION_SCRIPT,
            path,
            expected_sha256=str(metadata["file_sha256"]),
        )
    )
    assert row["on_status"] == row["off_status"] == "ok"
    assert row["on_work"] == row["off_work"] == 3
    assert row["on_action"] == row["off_action"]
    assert row["on_simulations"] == 3 and row["off_simulations"] == 0
    assert row["on_cleanup"] and row["off_cleanup"]


@native_test
def test_two_clean_processes_replay_same_frozen_native_artifact(
    frozen_capture: tuple[Path, dict[str, object]],
) -> None:
    path, metadata = frozen_capture
    outputs = [_replay(path, str(metadata["file_sha256"])) for _ in range(2)]
    assert outputs[0] == outputs[1]
    assert len(outputs[0]["results"]) == 3 * len(REPLAY_AGENT_SEEDS)
    for row in outputs[0]["results"]:
        assert row["completed_work_units"] == FIXED_REPLAY_UNITS
        assert row["terminal_status"] == "ok"
        assert row["cleanup_succeeded"] is True


@native_test
def test_independent_recapture_compares_semantics_and_fixed_work_outputs(
    frozen_capture: tuple[Path, dict[str, object]],
) -> None:
    first_path, first_metadata = frozen_capture
    second_path = first_path.with_name("independent-recapture.json")
    second_metadata = _capture_to(second_path)

    first_state = load_frozen_captured_state(
        first_path,
        expected_file_sha256=str(first_metadata["file_sha256"]),
    )
    second_state = load_frozen_captured_state(
        second_path,
        expected_file_sha256=str(second_metadata["file_sha256"]),
    )
    assert_independent_recapture_semantics(first_state, second_state)

    first_replay = _replay(first_path, str(first_metadata["file_sha256"]))
    second_replay = _replay(second_path, str(second_metadata["file_sha256"]))
    assert first_replay["public_semantic_hash"] == second_replay["public_semantic_hash"]
    assert first_replay["results"] == second_replay["results"]
