"""Adversarial checks for evidence binding, schema execution, and exact trees."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest


RELEASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELEASE))


def _protocol():
    from pevl_bench.admission import AdmissionProtocol

    return AdmissionProtocol.load(RELEASE / "protocol")


def _bundle() -> dict:
    return json.loads((RELEASE / "examples/example_evidence.json").read_text())


def _verify(document: dict, protocol=None, evidence_root: Path | None = None) -> dict:
    from pevl_bench.evidence import verify_and_admit

    return verify_and_admit(
        document,
        protocol or _protocol(),
        evidence_root=evidence_root or RELEASE / "examples",
    )


def test_display_sources_use_descriptive_quantile_headers() -> None:
    expected = {
        "figure_4_timed_search.csv": (
            "stratum",
            "clusters",
            "estimate",
            "quantile_2_5",
            "quantile_97_5",
        ),
        "figure_5_factorial.csv": (
            "contrast",
            "estimate_pp",
            "quantile_2_5_pp",
            "quantile_97_5_pp",
            "units",
            "reweighting_draws",
        ),
    }
    for name, fields in expected.items():
        with (RELEASE / "source_data" / name).open(encoding="utf-8", newline="") as handle:
            assert tuple(csv.DictReader(handle).fieldnames or ()) == fields


def _rehash(document: dict) -> None:
    from pevl_bench.evidence import compute_admission_evidence_sha256

    document["admission_evidence_sha256"] = compute_admission_evidence_sha256(document)


def test_public_admit_derives_states_and_emits_certificates() -> None:
    from pevl_bench.evidence import VERIFIER_ID, verify_and_admit

    protocol = _protocol()
    decision = _verify(_bundle(), protocol)
    assert decision["input_valid"] is True
    assert decision["evidence_verified"] is True
    assert (
        decision["input_assurance"]
        == "declared_bundle_files_verified_and_record_checks_evaluated"
    )
    assert decision["external_scientific_provenance_verified"] is False
    assert decision["evidence_trust_anchor"] == "self_asserted_internal_consistency"
    assert decision["evidence_verifier"] == VERIFIER_ID
    assert decision["permitted_claim_class"] == "schedule_matched"
    assert [row["state"] for row in decision["gate_report"]] == [
        "pass",
        "pass",
        "pass",
        "pass",
        "fail",
        "unavailable",
        "not_applicable",
    ]
    assert [row["gate"] for row in decision["gate_certificates"]] == list(
        protocol.gate_order
    )
    assert all(row["verifier_id"] == VERIFIER_ID for row in decision["gate_certificates"])


def test_result_data_is_neither_hashed_nor_read_by_public_admit() -> None:
    from pevl_bench.evidence import compute_admission_evidence_sha256, verify_and_admit

    protocol = _protocol()
    left = _bundle()
    right = deepcopy(left)
    left["result_data"] = {
        "observed_treatment_effect": 10**200,
        "p_value": 0.0,
        "result_favorability": "maximally_favorable",
    }
    right["result_data"] = {
        "observed_treatment_effect": -(10**200),
        "p_value": 1.0,
        "result_favorability": "maximally_unfavorable",
    }
    assert compute_admission_evidence_sha256(left) == compute_admission_evidence_sha256(right)
    assert _verify(left, protocol) == _verify(right, protocol)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.pop("gate_evidence"),
        lambda value: value["gate_evidence"]["execution_profiles"]["records"].pop(),
        lambda value: value.update({"evidence": {"artifact_identity": "pass"}}),
        lambda value: value.update({"schema_version": "future-schema"}),
    ],
)
def test_missing_malformed_or_caller_asserted_public_evidence_fails_closed(mutation) -> None:
    from pevl_bench.evidence import verify_and_admit

    document = _bundle()
    mutation(document)
    decision = _verify(document)
    assert decision["input_valid"] is False
    assert decision["evidence_verified"] is False
    assert decision["decision_status"] == "suppress"
    assert decision["permitted_claim_class"] == "suppress"


def test_hash_mismatch_and_semantically_duplicate_records_fail_closed() -> None:
    from pevl_bench.evidence import verify_and_admit

    protocol = _protocol()
    hash_mismatch = _bundle()
    hash_mismatch["gate_evidence"]["schedule"]["rows"][0]["requested_seed"] = 18
    rejected = _verify(hash_mismatch, protocol)
    assert rejected["input_valid"] is False
    assert "contradicts" in " ".join(rejected["validation_errors"])

    duplicate_key = _bundle()
    duplicate = deepcopy(duplicate_key["gate_evidence"]["schedule"]["rows"][0])
    duplicate["physical_seat"] = 1
    duplicate_key["gate_evidence"]["schedule"]["rows"].append(duplicate)
    _rehash(duplicate_key)
    suppressed = _verify(duplicate_key, protocol)
    assert suppressed["decision_status"] == "suppress"
    assert suppressed["evidence_coherent"] is False
    assert any(
        row["state"] == "malformed" for row in suppressed["gate_certificates"]
    )


def test_record_order_and_result_direction_cannot_strengthen_claim() -> None:
    from pevl_bench.evidence import verify_and_admit

    protocol = _protocol()
    baseline = _bundle()
    reordered = deepcopy(baseline)
    reordered["gate_evidence"]["artifact_identity"]["artifacts"].reverse()
    reordered["gate_evidence"]["execution_profiles"]["records"].reverse()
    for record in reordered["gate_evidence"]["execution_profiles"]["records"]:
        record["outcome"] = "draw"
    _rehash(reordered)
    first = _verify(baseline, protocol)
    second = _verify(reordered, protocol)
    assert first["permitted_claim_class"] == second["permitted_claim_class"]
    assert [row["state"] for row in first["gate_report"]] == [
        row["state"] for row in second["gate_report"]
    ]
    assert first["evidence_binding_sha256"] != second["evidence_binding_sha256"]


def test_bundle_cannot_claim_unimplemented_high_level_evidence(tmp_path: Path) -> None:
    from pevl_bench.evidence import verify_and_admit

    example_root = tmp_path / "examples"
    __import__("shutil").copytree(RELEASE / "examples", example_root)
    document = json.loads((example_root / "example_evidence.json").read_text())
    records = document["gate_evidence"]["execution_profiles"]["records"]
    worker = next(
        row for row in records if row["arm"] == "control" and row["profile"] == "workers-8-reverse"
    )
    fresh = next(
        row for row in records if row["arm"] == "control" and row["profile"] == "fresh-process-1"
    )
    worker_file = example_root / worker["trace_path"]
    fresh_file = example_root / fresh["trace_path"]
    worker_file.write_bytes(fresh_file.read_bytes())
    for field in ("trace_sha256", "trace_bytes", "outcome", "error_count", "decision_count"):
        worker[field] = fresh[field]
    _rehash(document)
    decision = _verify(document, evidence_root=example_root)
    assert decision["permitted_claim_class"] == "execution_repeatable"
    assert decision["decision_status"] == "downgrade"
    assert decision["gate_report"][5]["state"] == "unavailable"
    assert decision["gate_report"][6]["state"] == "not_applicable"


def test_pure_classifier_is_explicitly_unverified() -> None:
    from pevl_bench.admission import INPUT_SCHEMA_VERSION, PROTOCOL_ID, TRUSTED_INPUT_KIND

    protocol = _protocol()
    assert not hasattr(protocol, "evaluate")
    document = {
        "schema_version": INPUT_SCHEMA_VERSION,
        "protocol_id": PROTOCOL_ID,
        "input_kind": TRUSTED_INPUT_KIND,
        "evidence": {gate: "pass" for gate in protocol.gate_order},
        "trace_projection": {
            "id": "trusted-test-trace",
            "version": "1.0.0",
            "fields": ["public_state"],
        },
    }
    decision = protocol.evaluate_trusted_states(document)
    assert decision["input_valid"] is True
    assert decision["input_assurance"] == "caller_asserted_prevalidated_states"
    assert decision["evidence_verified"] is False
    assert decision["classifier_scope"] == "classification_only"


def test_synthetic_fixtures_are_all_routed_through_common_engine() -> None:
    from pevl_bench.synthetic_admission import ADAPTER_ID, build_report

    report = build_report(_protocol())
    assert len(report["modes"]) == 5
    assert {row["mode"] for row in report["modes"]} == {
        "clean_deterministic",
        "stateful_draw_shift",
        "wall_clock_search",
        "process_global_state",
        "uint32_seed_conversion",
    }
    for row in report["modes"]:
        assert row["frozen_level_8_disposition"] == row["derived_fixture_disposition"]
        decision = row["admission_decision"]
        assert decision["evidence_verifier"] == ADAPTER_ID
        assert len(decision["gate_certificates"]) == 7
        assert decision["input_assurance"] == "synthetic_fixture_adapter_checks_evaluated"
        assert (
            decision["evidence_trust_anchor"]
            == "self_asserted_synthetic_fixture_consistency"
        )
        assert "in-memory synthetic fixture" in decision["verification_scope"]
        assert "regular single-link files matched" not in decision["verification_scope"]


def test_checked_schema_subset_executes_and_rejects_drift() -> None:
    from pevl_bench.admission import load_json_document
    from pevl_bench.schema_subset import (
        CheckedSchemaError,
        check_schema_supported,
        validate_instance,
    )

    report = load_json_document(RELEASE / "pevl_bench/results/pevl_results.json")
    schema = load_json_document(RELEASE / "pevl_bench/results/pevl_results.schema.json")
    validate_instance(report, schema, label="synthetic report")
    invalid = deepcopy(report)
    invalid.pop("modes")
    with pytest.raises(CheckedSchemaError):
        validate_instance(invalid, schema)
    unsupported = deepcopy(schema)
    unsupported["minProperties"] = 1
    with pytest.raises(CheckedSchemaError):
        check_schema_supported(unsupported)


def test_semantically_valid_protocol_tamper_hits_bundle_anchor(tmp_path: Path) -> None:
    from pevl_bench.admission import AdmissionProtocol, AdmissionProtocolError

    protocol_copy = tmp_path / "protocol"
    __import__("shutil").copytree(RELEASE / "protocol", protocol_copy)
    claims_path = protocol_copy / "claim_classes.json"
    claims = json.loads(claims_path.read_text())
    claims["claim_classes"]["schedule_matched"]["label"] += " altered"
    claims_path.write_text(json.dumps(claims))
    with pytest.raises(AdmissionProtocolError, match="semantic hash"):
        AdmissionProtocol.load(protocol_copy)


def _verify_release_module():
    path = RELEASE / "scripts/verify_release.py"
    spec = importlib.util.spec_from_file_location("release_verifier_for_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_tiny_manifest(root: Path) -> str:
    payload = root / "payload.txt"
    payload.write_text("payload\n")
    digest = hashlib.sha256(payload.read_bytes()).hexdigest()
    manifest = root / "MANIFEST.sha256"
    manifest.write_text(f"{digest}  payload.txt\n")
    return hashlib.sha256(manifest.read_bytes()).hexdigest()


def test_manifest_verification_is_exact_tree_and_optionally_pinned(tmp_path: Path) -> None:
    verifier = _verify_release_module()
    root = tmp_path / "release"
    root.mkdir()
    pin = _write_tiny_manifest(root)
    verifier.RELEASE = root
    internal = verifier.verify_manifest()
    assert internal["trust_anchor"] == "internal_consistency_only"
    pinned = verifier.verify_manifest(pin)
    assert pinned["trust_anchor"] == "caller_supplied_manifest_pin"
    with pytest.raises(verifier.VerificationError, match="external manifest pin"):
        verifier.verify_manifest("0" * 64)


@pytest.mark.parametrize("relative", ["extra.txt", "cache.pyc", "cache.pyo", "__pycache__/x.pyc"])
def test_manifest_rejects_every_extra_file(tmp_path: Path, relative: str) -> None:
    verifier = _verify_release_module()
    root = tmp_path / "release"
    root.mkdir()
    _write_tiny_manifest(root)
    extra = root / relative
    extra.parent.mkdir(parents=True, exist_ok=True)
    extra.write_text("extra")
    verifier.RELEASE = root
    with pytest.raises(verifier.VerificationError, match="manifest entry set"):
        verifier.verify_manifest()


def test_manifest_rejects_empty_extra_directory(tmp_path: Path) -> None:
    verifier = _verify_release_module()
    root = tmp_path / "release"
    root.mkdir()
    _write_tiny_manifest(root)
    (root / "unexpected-empty-directory").mkdir()
    verifier.RELEASE = root
    with pytest.raises(verifier.VerificationError, match="manifest directory set"):
        verifier.verify_manifest()


def test_manifest_rejects_symlink(tmp_path: Path) -> None:
    verifier = _verify_release_module()
    root = tmp_path / "release"
    root.mkdir()
    _write_tiny_manifest(root)
    os.symlink(root / "payload.txt", root / "linked.txt")
    verifier.RELEASE = root
    with pytest.raises(verifier.VerificationError, match="symlink prohibited"):
        verifier.verify_manifest()


def test_manifest_rejects_hard_linked_payload(tmp_path: Path) -> None:
    verifier = _verify_release_module()
    root = tmp_path / "release"
    root.mkdir()
    _write_tiny_manifest(root)
    os.link(root / "payload.txt", root / "payload-alias.txt")
    verifier.RELEASE = root
    with pytest.raises(verifier.VerificationError, match="hard-linked file prohibited"):
        verifier.verify_manifest()


def test_public_cli_rejects_trusted_state_envelope(tmp_path: Path) -> None:
    from pevl_bench.admission import INPUT_SCHEMA_VERSION, PROTOCOL_ID, TRUSTED_INPUT_KIND

    protocol = _protocol()
    trusted = {
        "schema_version": INPUT_SCHEMA_VERSION,
        "protocol_id": PROTOCOL_ID,
        "input_kind": TRUSTED_INPUT_KIND,
        "evidence": {gate: "pass" for gate in protocol.gate_order},
        "trace_projection": {
            "id": "trusted-test-trace",
            "version": "1.0.0",
            "fields": ["public_state"],
        },
    }
    path = tmp_path / "trusted.json"
    path.write_text(json.dumps(trusted))
    public = subprocess.run(
        [sys.executable, "-B", "-m", "pevl_bench", "admit", str(path)],
        cwd=RELEASE,
        text=True,
        capture_output=True,
        check=False,
    )
    assert public.returncode == 2
    assert json.loads(public.stdout)["input_valid"] is False
    classified = subprocess.run(
        [sys.executable, "-B", "-m", "pevl_bench", "classify-trusted", str(path)],
        cwd=RELEASE,
        text=True,
        capture_output=True,
        check=True,
    )
    decision = json.loads(classified.stdout)
    assert decision["input_assurance"] == "caller_asserted_prevalidated_states"
    assert decision["evidence_verified"] is False
