import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from paper.synthetic import pevl_synthetic as pevl


ROOT = Path(__file__).resolve().parents[1]
SOURCE_RESULTS = ROOT / "paper" / "synthetic" / "results"
RELEASE_DIR = ROOT / "paper" / "release" / "synthetic"
RELEASE_RESULTS = RELEASE_DIR / "results"

EXPECTED_JSON_SHA256 = "d34a2ea1546a0a88e90a5ca58b49f1085edfcaf753f70ed49e0f04202e9ba6f9"
EXPECTED_CSV_SHA256 = "bb79fd2f4f70415948f659b3837b68371814da63a3942ab9bf672cc5e11ec465"
EXPECTED_SCHEMA_SHA256 = "d173b3255a19b985bf5d0c102b67bfebcddcec6911b38d18a77048b74f63aafb"


def _modes():
    return {mode["mode"]: mode for mode in pevl.build_report()["modes"]}


def test_validity_ladder_catches_expected_modes():
    modes = _modes()
    assert set(modes) == set(pevl.EXPECTED_CATCHES)
    assert {
        name: mode["caught_by_levels"] for name, mode in modes.items()
    } == pevl.EXPECTED_CATCHES
    assert modes["clean_deterministic"]["first_catching_level"] is None
    assert modes["stateful_draw_shift"]["first_catching_level"] == 7
    assert modes["uint32_seed_conversion"]["first_catching_level"] == 2


def test_level_8_is_an_admission_decision_not_an_evidence_gate():
    report = pevl.build_report()
    level_8 = report["levels"][7]
    assert level_8["kind"] == "admission_decision"
    assert level_8["valid_statuses"] == ["admit", "downgrade", "suppress"]
    statuses = {
        mode["mode"]: mode["audit"][7]["status"] for mode in report["modes"]
    }
    assert statuses == {
        "clean_deterministic": "admit",
        "stateful_draw_shift": "downgrade",
        "wall_clock_search": "suppress",
        "process_global_state": "suppress",
        "uint32_seed_conversion": "suppress",
    }


def test_stateful_draw_shift_passes_repeats_but_fails_event_alignment():
    mode = _modes()["stateful_draw_shift"]
    statuses = {row["level"]: row["status"] for row in mode["audit"]}
    assert statuses[4] == "pass"
    assert statuses[5] == "pass"
    assert statuses[7] == "fail"
    level_7 = mode["audit"][6]["evidence"]
    assert level_7["mismatched_count"] == 4
    assert level_7["shared_event_count"] == 5


def test_event_keyed_hashing_repairs_draw_shift_for_shared_events():
    stateful_control = pevl.simulate_random_stream(
        pevl.DEFAULT_SEED, intervention_draw=False, event_keyed=False
    )
    stateful_treatment = pevl.simulate_random_stream(
        pevl.DEFAULT_SEED, intervention_draw=True, event_keyed=False
    )
    assert (
        stateful_control["shared_event_values"]
        != stateful_treatment["shared_event_values"]
    )

    keyed_control = pevl.simulate_random_stream(
        pevl.DEFAULT_SEED, intervention_draw=False, event_keyed=True
    )
    keyed_treatment = pevl.simulate_random_stream(
        pevl.DEFAULT_SEED, intervention_draw=True, event_keyed=True
    )
    assert keyed_control["shared_event_values"] == keyed_treatment[
        "shared_event_values"
    ]
    assert keyed_control["trace_sha256"] == keyed_treatment["trace_sha256"]
    assert keyed_control["event_log_sha256"] != keyed_treatment[
        "event_log_sha256"
    ]

    remediation = _modes()["stateful_draw_shift"]["evidence"][
        "event_keyed_remediation"
    ]
    assert remediation["aligned_common_events"] is True
    assert remediation["mismatched_common_event_keys"] == []
    assert remediation["level_7_status_after_remediation"] == "pass"


def test_wall_clock_and_process_modes_have_deterministic_failure_fixtures():
    modes = _modes()
    wall = modes["wall_clock_search"]["evidence"]
    assert wall["reference_serial"]["trace_sha256"] != wall["repeated_serial"][
        "trace_sha256"
    ]
    assert wall["reference_serial"]["trace_sha256"] != wall[
        "contended_worker_profile"
    ]["trace_sha256"]

    process = modes["process_global_state"]["evidence"]
    assert process["fresh_a"]["trace_sha256"] == process["fresh_b"][
        "trace_sha256"
    ]
    assert process["fresh_a"]["trace_sha256"] != process["reused_worker"][
        "trace_sha256"
    ]


def test_uint32_conversion_records_collision_and_exact_engine_seed():
    assert pevl.uint32_seed(17) == 17
    assert pevl.uint32_seed((1 << 32) + 17) == 17
    mode = _modes()["uint32_seed_conversion"]
    assert mode["evidence"]["collision"] is True
    rows = mode["evidence"]["conversion_rows"]
    assert [row["requested_seed"] for row in rows] == [17, (1 << 32) + 17]
    assert [row["engine_seed_uint32"] for row in rows] == [17, 17]
    assert rows[0]["trace_sha256"] == rows[1]["trace_sha256"]


def test_machine_readable_matrix_matches_json_report():
    outputs = pevl.rendered_outputs()
    report = json.loads(outputs["pevl_results.json"])
    rows = list(csv.DictReader(io.StringIO(outputs["pevl_matrix.csv"])))
    assert len(rows) == len(report["modes"]) * len(report["levels"]) == 40
    expected = {
        (mode["mode"], str(audit["level"])): (
            report["levels"][audit["level"] - 1]["kind"],
            audit["status"],
            str(audit["catches_failure"]).lower(),
            audit["evidence_sha256"],
        )
        for mode in report["modes"]
        for audit in mode["audit"]
    }
    actual = {
        (row["mode"], row["level"]): (
            row["level_kind"],
            row["status"],
            row["catches_failure"],
            row["evidence_sha256"],
        )
        for row in rows
    }
    assert actual == expected


def test_report_has_published_schema_and_valid_internal_digests():
    outputs = pevl.rendered_outputs()
    report = json.loads(outputs["pevl_results.json"])
    schema = json.loads(outputs["pevl_results.schema.json"])
    assert pevl.validate_report(report) == []
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["properties"]["schema_version"]["const"] == pevl.SCHEMA_VERSION
    assert schema["properties"]["modes"]["minItems"] == 5
    assert schema["properties"]["levels"]["minItems"] == 8


def test_dependency_free_validator_rejects_duplicate_modes_and_digest_drift():
    report = json.loads(pevl.render_json(pevl.build_report()))
    report["modes"][4] = report["modes"][0]
    assert "modes must contain each fixture exactly once" in pevl.validate_report(
        report
    )

    report = json.loads(pevl.render_json(pevl.build_report()))
    report["modes"][0]["audit"][0]["evidence"]["protocol_id"] = "tampered"
    assert (
        "clean_deterministic: level-1 evidence digest mismatch"
        in pevl.validate_report(report)
    )


def test_levels_one_through_four_expose_minimum_audit_evidence():
    modes = _modes()
    clean = modes["clean_deterministic"]["audit"]
    level_1 = clean[0]["evidence"]
    assert {
        "candidate_policy_sha256",
        "control_policy_sha256",
        "engine_sha256",
        "implementation_sha256",
        "opponent_sha256",
        "protocol_sha256",
    } <= set(level_1["artifact_hashes"])
    assert level_1["protocol_id"]
    assert level_1["configuration"]["worker_count"] == 1

    level_2 = clean[1]["evidence"]
    assert level_2["conversion_rule"] == "requested_seed modulo 2**32"
    assert level_2["rng_stream_id"]
    assert level_2["unique_engine_seeds"] is True

    level_3 = clean[2]["evidence"]
    assert level_3["complete_expected_cells"] is True
    assert level_3["candidate"]["schedule_fingerprint_sha256"]
    assert level_3["candidate"] == level_3["control"]

    level_4 = clean[3]["evidence"]
    assert level_4["all_compared_fields_equal"] is True
    assert level_4["compared_fields_in_strength_order"] == [
        "outcome",
        "errors",
        "decision_count",
        "action_sequence",
        "public_state_sequence",
        "trace_sha256",
    ]
    assert level_4["first_trace_divergence"] is None


def test_outputs_have_stable_hashes_and_round_trip_verification(tmp_path):
    pevl.write_outputs(tmp_path)
    assert pevl.verify_outputs(tmp_path) == []

    json_bytes = (tmp_path / "pevl_results.json").read_bytes()
    csv_bytes = (tmp_path / "pevl_matrix.csv").read_bytes()
    schema_bytes = (tmp_path / "pevl_results.schema.json").read_bytes()
    assert hashlib.sha256(json_bytes).hexdigest() == EXPECTED_JSON_SHA256
    assert hashlib.sha256(csv_bytes).hexdigest() == EXPECTED_CSV_SHA256
    assert hashlib.sha256(schema_bytes).hexdigest() == EXPECTED_SCHEMA_SHA256
    assert (tmp_path / "MANIFEST.sha256").read_text(encoding="utf-8") == (
        f"{EXPECTED_CSV_SHA256}  pevl_matrix.csv\n"
        f"{EXPECTED_JSON_SHA256}  pevl_results.json\n"
        f"{EXPECTED_SCHEMA_SHA256}  pevl_results.schema.json\n"
    )

    first = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    pevl.write_outputs(tmp_path)
    second = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    assert first == second


def test_verifier_rejects_modified_and_unexpected_entries(tmp_path):
    pevl.write_outputs(tmp_path)
    result_path = tmp_path / "pevl_results.json"
    result_path.write_bytes(result_path.read_bytes() + b"\r\n")
    assert "content mismatch: pevl_results.json" in pevl.verify_outputs(tmp_path)

    pevl.write_outputs(tmp_path)
    (tmp_path / "unexpected").mkdir()
    assert "unexpected entry: unexpected" in pevl.verify_outputs(tmp_path)


def test_generator_and_verifier_reject_expected_name_symlink(tmp_path):
    pevl.write_outputs(tmp_path)
    result_path = tmp_path / "pevl_results.json"
    target = tmp_path / "target.json"
    target.write_bytes(result_path.read_bytes())
    result_path.unlink()
    try:
        result_path.symlink_to(target)
    except (NotImplementedError, OSError):
        pytest.skip("symbolic links are unavailable on this platform")
    assert "symlink not allowed: pevl_results.json" in pevl.verify_outputs(tmp_path)
    with pytest.raises(ValueError, match="refusing to overwrite symlink"):
        pevl.write_outputs(tmp_path)


def test_checked_in_source_and_release_artifacts_verify():
    assert pevl.verify_outputs(SOURCE_RESULTS) == []
    assert pevl.verify_outputs(RELEASE_RESULTS) == []


def test_standalone_release_cli_verifies_without_project_imports(tmp_path):
    standalone = tmp_path / "synthetic"
    shutil.copytree(RELEASE_DIR, standalone)
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "pevl_synthetic.py", "verify"],
        cwd=standalone,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "verified" in completed.stdout
