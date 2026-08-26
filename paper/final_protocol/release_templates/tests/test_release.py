"""Checks for the engine-independent release interface and data boundary."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from copy import deepcopy
from itertools import product
from pathlib import Path

import pytest


RELEASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELEASE))


def test_synthetic_expected_outputs_verify() -> None:
    from pevl_bench import synthetic

    assert synthetic.verify_outputs(RELEASE / "pevl_bench/results") == []


def test_processed_evidence_has_expected_analysis_units() -> None:
    historical = json.loads((RELEASE / "data/processed/historical_summary.json").read_text())
    preflight = json.loads((RELEASE / "data/processed/preflight_summary.json").read_text())
    stress = json.loads((RELEASE / "data/processed/timed_search_stress.json").read_text())
    factorial = json.loads((RELEASE / "data/processed/factorial_summary.json").read_text())
    assert historical["units"] == 2_800
    assert preflight["trajectory_units"] == 1_000
    assert preflight["executions"] == 3_000
    assert stress["clusters"] == 200
    assert factorial["units"] == 2_000
    assert factorial["games"] == 12_000


def test_no_restricted_binary_suffixes_or_literal_local_roots() -> None:
    prohibited = {".dylib", ".dll", ".so", ".exe", ".zip", ".gz", ".tar", ".pkl", ".npy", ".npz", ".pt", ".pth"}
    local_root = re.compile(rb"/(?:Users|home|root|private|tmp|var)/")
    for path in RELEASE.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        assert path.suffix.lower() not in prohibited
        if path.suffix.lower() not in {".pdf", ".png"}:
            assert not local_root.search(path.read_bytes())


def _protocol():
    from pevl_bench.admission import AdmissionProtocol

    return AdmissionProtocol.load(RELEASE / "protocol")


def _document(states: list[str] | None = None) -> dict:
    from pevl_bench.admission import INPUT_SCHEMA_VERSION, PROTOCOL_ID, TRUSTED_INPUT_KIND

    protocol = _protocol()
    statuses = states or ["pass"] * len(protocol.gate_order)
    return {
        "schema_version": INPUT_SCHEMA_VERSION,
        "protocol_id": PROTOCOL_ID,
        "input_kind": TRUSTED_INPUT_KIND,
        "evidence": dict(zip(protocol.gate_order, statuses)),
        "trace_projection": {
            "id": "test-public-trace",
            "version": "1.0.0",
            "fields": ["decision_index", "public_state", "selected_action"],
        },
    }


def test_admission_bundle_is_post_acquisition_formalization() -> None:
    protocol = _protocol()
    provenance = protocol.rules["formalization_provenance"]
    assert provenance["status"] == "post_acquisition_executable_formalization"
    assert provenance["created_after_acquisition"] is True
    assert provenance["authority"] == "frozen_experiment_specific_rules_remain_authoritative"
    assert len(provenance["mapping_assumptions"]) >= 7
    frozen = (RELEASE / provenance["frozen_source_protocol"]).read_text(encoding="utf-8")
    assert "repeat and worker parity" in frozen
    assert "cross-arm event alignment" in frozen
    assert "finite-population" in frozen
    assert "McNemar" in frozen
    assert "One mismatch suppresses every planned factorial contrast" in frozen
    assumptions = " ".join(provenance["mapping_assumptions"])
    assert "later post-acquisition conservative reporting restriction" in assumptions
    assert "not evidence that this taxonomy was prospectively validated" in assumptions
    assert "before data acquisition" in assumptions


def test_protocol_deviation_is_explicit_and_unsigned() -> None:
    deviation = (RELEASE / "docs/PROTOCOL_DEVIATIONS.md").read_text(encoding="utf-8")
    deviation_words = " ".join(deviation.split())
    stress = json.loads((RELEASE / "data/processed/timed_search_stress.json").read_text())
    assert "PENDING_HUMAN_SIGNOFF_UNSIGNED" in deviation
    assert "first-divergence positions" in deviation
    assert "timing summaries" in deviation
    assert "Raw trace lines are absent" in deviation_words or "raw trace payloads are restricted" in deviation_words
    assert "reporting/access deviation" in deviation or "reporting and access deviation" in deviation
    assert "99 among 200" in deviation
    assert stress["first_divergence_actor_counts_included"] is True
    assert stress["first_divergence_actor_counts"]["opponent"] == 99
    assert sum(stress["first_divergence_actor_counts"].values()) == stress["trace_disagreement_clusters"]
    assert stress["first_divergence_position_included"] is False
    assert stress["timing_summaries_included"] is True
    assert set(stress["timing_summaries"]) == {"timed-search-A", "timed-search-B"}
    for opponent, profiles in stress["timing_summaries"].items():
        assert set(profiles) == {
            "serial_forward",
            "serial_reverse",
            "parallel_forward",
            "parallel_reverse",
        }
        for summary in profiles.values():
            assert summary["games"] == 100
            assert summary["median_seconds"] > 0.0
    provenance = stress["recovered_secondary_outputs_provenance"]
    assert len(provenance["source_sha256"]) == 64
    assert stress["protocol_deviation_status"] == (
        "PENDING_HUMAN_SIGNOFF_UNSIGNED_POSITIONS_UNRECOVERED"
    )


def test_environment_specs_are_direct_only_with_clean_build_evidenced() -> None:
    readme = (RELEASE / "README.md").read_text(encoding="utf-8")
    readme_words = " ".join(readme.split())
    requirements = (RELEASE / "requirements-lock.txt").read_text(encoding="utf-8")
    environment = (RELEASE / "environment.yml").read_text(encoding="utf-8")
    status = json.loads((RELEASE / "RELEASE_STATUS.json").read_text())
    assert "conda env create --file environment.yml" in readme
    assert "python3 -m venv ../trace-validation-review-venv" in readme
    assert "neither is a transitive dependency lock" in readme_words
    assert "Clean-environment verification passed" in readme_words
    assert "not a transitive dependency lock" in requirements
    assert "not a transitive dependency lock" in environment
    assert status["clean_environment_build_evidenced"] is True


def test_admission_decision_table_is_generated_from_rules() -> None:
    protocol = _protocol()
    generated = protocol.render_decision_table()
    retained = (RELEASE / "docs/ADMISSION_DECISION_TABLE.md").read_text(encoding="utf-8")
    assert retained == generated
    assert protocol.decision_table_sha256() == __import__("hashlib").sha256(retained.encode()).hexdigest()
    property_names = (
        "result independence",
        "prerequisite monotonicity",
        "failure dominance",
        "projection scoping",
        "stateless determinism",
        "unknown-state fail-closedness",
        "strict claim ordering",
    )
    assert all(retained.count(f"`{name}`") == 1 for name in property_names)


def test_result_independence_replaces_all_result_values() -> None:
    from pevl_bench.admission import BLOCKING_STATES

    protocol = _protocol()
    document = _document(["pass"] * 6 + ["unavailable"])
    variants = [
        {
            "observed_outcome": [1, 1, 1],
            "observed_treatment_effect": 99.0,
            "p_value": 1e-100,
            "confidence_interval": [98.0, 100.0],
            "result_favorability": "favorable",
        },
        {
            "observed_outcome": [0, 0, 0],
            "observed_treatment_effect": -99.0,
            "p_value": 1.0,
            "confidence_interval": [-100.0, -98.0],
            "result_favorability": "unfavorable",
        },
        {
            "observed_outcome": {"arbitrary": "replacement"},
            "observed_treatment_effect": None,
            "p_value": "not supplied",
            "confidence_interval": {"direction": "arbitrary"},
            "result_favorability": False,
        },
    ]
    decisions = []
    for index, result_data in enumerate(variants):
        candidate = deepcopy(document)
        candidate["result_data"] = result_data
        decisions.append(protocol.evaluate_trusted_states(candidate))
    assert decisions[0] == decisions[1] == decisions[2]
    assert decisions[0]["permitted_claim_class"] == "seed_matched_bounded"
    serialized = json.dumps(decisions[0], sort_keys=True)
    assert "must-not-leak" not in serialized
    assert "99.0" not in serialized

    # Exercise every coherent gate-state combination, not only the worked case.
    gate_count = len(protocol.gate_order)
    for prefix in range(gate_count + 1):
        for suffix in product(sorted(BLOCKING_STATES), repeat=gate_count - prefix):
            candidate = _document(list(("pass",) * prefix + suffix))
            left = deepcopy(candidate)
            right = deepcopy(candidate)
            left["result_data"] = variants[0]
            right["result_data"] = variants[1]
            assert protocol.evaluate_trusted_states(left) == protocol.evaluate_trusted_states(right)


def test_prerequisite_monotonicity_exhaustive_for_coherent_evidence() -> None:
    from pevl_bench.admission import BLOCKING_STATES

    protocol = _protocol()
    strengths = {
        claim_id: definition["strength"]
        for claim_id, definition in protocol.claim_definitions.items()
    }
    gate_count = len(protocol.gate_order)
    for prefix in range(gate_count + 1):
        for suffix in product(sorted(BLOCKING_STATES), repeat=gate_count - prefix):
            states = ("pass",) * prefix + suffix
            baseline = protocol.classify_status_vector(states)
            assert baseline.reason == "rule_match"
            for index in range(prefix):
                for replacement in BLOCKING_STATES:
                    weakened = list(states)
                    weakened[index] = replacement
                    result = protocol.classify_status_vector(weakened)
                    assert strengths[result.claim_class] <= strengths[baseline.claim_class]


def test_failure_dominance_ignores_extreme_favorability() -> None:
    protocol = _protocol()
    favorable = {
        "observed_treatment_effect": 1e300,
        "p_value": 0.0,
        "confidence_interval": [1e299, 1e300],
        "result_favorability": "maximal",
    }
    for failed_gate in range(len(protocol.gate_order)):
        states = ["pass"] * failed_gate + ["fail"] + ["unavailable"] * (
            len(protocol.gate_order) - failed_gate - 1
        )
        document = _document(states)
        document["result_data"] = favorable
        decision = protocol.evaluate_trusted_states(document)
        maximum_strength = protocol._maximum_strength_for_prefix(failed_gate)
        assert decision["claim_strength"] <= maximum_strength
        assert decision["decision_status"] != "admit" or failed_gate >= 6
    preflight_failure = _document(
        ["pass", "pass", "pass", "pass", "fail", "unavailable", "not_applicable"]
    )
    preflight_failure["result_data"] = favorable
    decision = protocol.evaluate_trusted_states(preflight_failure)
    assert decision["permitted_claim_class"] == "schedule_matched"
    assert "paired treatment effect" in " ".join(decision["forbidden_wording"])


def test_projection_scoping_and_unscoped_repeatability_suppression() -> None:
    protocol = _protocol()
    document = _document(["pass"] * 5 + ["unavailable", "not_applicable"])
    document["result_data"] = {"private_hidden_state": "never scoped"}
    decision = protocol.evaluate_trusted_states(document)
    assert decision["permitted_claim_class"] == "execution_repeatable"
    assert decision["trace_projection_scope"] == document["trace_projection"]
    assert "test-public-trace@1.0.0" in decision["required_wording"]
    for field in document["trace_projection"]["fields"]:
        assert field in decision["required_wording"]
    assert "private_hidden_state" not in json.dumps(decision)

    missing = deepcopy(document)
    missing["trace_projection"] = None
    suppressed = protocol.evaluate_trusted_states(missing)
    assert suppressed["input_valid"] is False
    assert suppressed["classification_reason"] == "unscoped_repeatability"
    assert suppressed["permitted_claim_class"] == "suppress"

    malformed = deepcopy(document)
    malformed["trace_projection"]["fields"] = []
    assert protocol.evaluate_trusted_states(malformed)["permitted_claim_class"] == "suppress"

    result_scoped = deepcopy(document)
    result_scoped["trace_projection"]["fields"] = ["public_state", "outcome"]
    result_scoped_decision = protocol.evaluate_trusted_states(result_scoped)
    assert result_scoped_decision["input_valid"] is False
    assert result_scoped_decision["permitted_claim_class"] == "suppress"


def test_stateless_repeat_run_determinism() -> None:
    from pevl_bench.evidence import verify_and_admit

    protocol = _protocol()
    document = json.loads((RELEASE / "examples/example_evidence.json").read_text())
    decisions = [
        verify_and_admit(
            deepcopy(document), protocol, evidence_root=RELEASE / "examples"
        )
        for _ in range(25)
    ]
    assert all(decision == decisions[0] for decision in decisions)
    assert decisions[0]["permitted_claim_class"] == "schedule_matched"
    assert decisions[0]["decision_sha256"] == decisions[-1]["decision_sha256"]
    assert protocol.render_decision_table() == protocol.render_decision_table()


def test_public_admit_binds_declared_artifact_and_trace_bytes(tmp_path: Path) -> None:
    from pevl_bench.evidence import admit_file

    example_dir = tmp_path / "examples"
    shutil.copytree(RELEASE / "examples", example_dir)
    evidence_path = example_dir / "example_evidence.json"
    baseline = admit_file(evidence_path, _protocol())
    assert baseline["input_valid"] is True
    assert baseline["evidence_verified"] is True
    assert baseline["permitted_claim_class"] == "schedule_matched"

    trace = example_dir / "evidence/control_trace_fresh.txt"
    trace.write_text(trace.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")
    rejected = admit_file(evidence_path, _protocol())
    assert rejected["input_valid"] is False
    assert rejected["evidence_verified"] is False
    assert rejected["permitted_claim_class"] == "suppress"
    assert "SHA-256 mismatch" in " ".join(rejected["validation_errors"])
    assert rejected["evidence_trust_anchor"] == "none_verification_failed"
    assert rejected["verification_scope"].startswith("Verification failed")


def test_public_admit_rejects_undeclared_support_files_and_links(tmp_path: Path) -> None:
    from pevl_bench.evidence import admit_file

    example_dir = tmp_path / "examples"
    shutil.copytree(RELEASE / "examples", example_dir)
    evidence_path = example_dir / "example_evidence.json"
    (example_dir / "evidence/undeclared.txt").write_text("undeclared\n")
    rejected_extra = admit_file(evidence_path, _protocol())
    assert rejected_extra["input_valid"] is False
    assert "closed set" in " ".join(rejected_extra["validation_errors"])

    (example_dir / "evidence/undeclared.txt").unlink()
    support = example_dir / "evidence"
    actual = example_dir / "actual-evidence"
    support.rename(actual)
    support.symlink_to(actual, target_is_directory=True)
    rejected_link = admit_file(evidence_path, _protocol())
    assert rejected_link["input_valid"] is False
    assert "support directory" in " ".join(rejected_link["validation_errors"])


def test_public_admit_rejects_missing_hardlinked_and_traversal_support(tmp_path: Path) -> None:
    from pevl_bench.evidence import admit_file, compute_admission_evidence_sha256

    missing_root = tmp_path / "missing"
    shutil.copytree(RELEASE / "examples", missing_root)
    (missing_root / "evidence/candidate_agent.txt").unlink()
    missing = admit_file(missing_root / "example_evidence.json", _protocol())
    assert missing["input_valid"] is False

    hardlink_root = tmp_path / "hardlink"
    shutil.copytree(RELEASE / "examples", hardlink_root)
    os.link(
        hardlink_root / "evidence/candidate_agent.txt",
        hardlink_root / "candidate-agent-alias.txt",
    )
    hardlinked = admit_file(hardlink_root / "example_evidence.json", _protocol())
    assert hardlinked["input_valid"] is False
    assert "hard-linked" in " ".join(hardlinked["validation_errors"])

    traversal_root = tmp_path / "traversal"
    shutil.copytree(RELEASE / "examples", traversal_root)
    document = json.loads((traversal_root / "example_evidence.json").read_text())
    document["gate_evidence"]["artifact_identity"]["artifacts"][0]["path"] = "../outside"
    document["admission_evidence_sha256"] = compute_admission_evidence_sha256(document)
    (traversal_root / "example_evidence.json").write_text(json.dumps(document))
    traversal = admit_file(traversal_root / "example_evidence.json", _protocol())
    assert traversal["input_valid"] is False


def test_public_admit_rejects_unavailable_external_evidence_root() -> None:
    from pevl_bench.evidence import verify_and_admit

    document = json.loads((RELEASE / "examples/example_evidence.json").read_text())
    rejected = verify_and_admit(document, _protocol())
    assert rejected["input_valid"] is False
    assert rejected["evidence_verified"] is False
    assert rejected["permitted_claim_class"] == "suppress"
    assert "evidence_root is required" in " ".join(rejected["validation_errors"])
    assert rejected["verification_scope"].startswith("Verification failed")


def test_unknown_state_fail_closedness() -> None:
    protocol = _protocol()
    cases = []

    missing_gate = _document()
    del missing_gate["evidence"][protocol.gate_order[2]]
    cases.append(missing_gate)

    extra_gate = _document()
    extra_gate["evidence"]["effect_is_favorable"] = "pass"
    cases.append(extra_gate)

    unknown_state = _document()
    unknown_state["evidence"][protocol.gate_order[2]] = "unknown"
    cases.append(unknown_state)

    extra_member = _document()
    extra_member["p_value"] = 0.001
    cases.append(extra_member)

    wrong_protocol = _document()
    wrong_protocol["protocol_id"] = "unknown-protocol"
    cases.append(wrong_protocol)

    wrong_schema = _document()
    wrong_schema["schema_version"] = "unknown-schema"
    cases.append(wrong_schema)

    for candidate in cases:
        decision = protocol.evaluate_trusted_states(candidate)
        assert decision["input_valid"] is False
        assert decision["decision_status"] == "suppress"
        assert decision["permitted_claim_class"] == "suppress"

    explicit_malformed = _document(
        ["pass", "pass", "malformed", "unavailable", "unavailable", "unavailable", "not_applicable"]
    )
    explicit_contradictory = _document(
        ["pass", "pass", "pass", "contradictory", "unavailable", "unavailable", "not_applicable"]
    )
    structural_contradiction = _document(
        ["pass", "fail", "pass", "unavailable", "unavailable", "unavailable", "not_applicable"]
    )
    for candidate in (explicit_malformed, explicit_contradictory, structural_contradiction):
        decision = protocol.evaluate_trusted_states(candidate)
        assert decision["input_valid"] is True
        assert decision["evidence_coherent"] is False
        assert decision["permitted_claim_class"] == "suppress"


def test_strict_claim_ordering_and_complete_state_space() -> None:
    from pevl_bench.admission import CLAIM_CLASS_ORDER, EVIDENCE_STATES, FATAL_STATES

    protocol = _protocol()
    strengths = [protocol.claim_definitions[name]["strength"] for name in CLAIM_CLASS_ORDER]
    assert strengths == list(range(len(CLAIM_CLASS_ORDER)))
    assert (
        strengths[CLAIM_CLASS_ORDER.index("schedule_matched")]
        < strengths[CLAIM_CLASS_ORDER.index("execution_repeatable")]
        < strengths[CLAIM_CLASS_ORDER.index("event_aligned")]
    )
    expected_by_prefix = {
        0: "suppress",
        1: "descriptive_unmatched",
        2: "descriptive_unmatched",
        3: "schedule_matched",
        4: "schedule_matched",
        5: "execution_repeatable",
        6: "seed_matched_bounded",
        7: "event_aligned",
    }
    observed = 0
    for states in product(EVIDENCE_STATES, repeat=len(protocol.gate_order)):
        observed += 1
        result = protocol.classify_status_vector(states)
        prefix = next((index for index, state in enumerate(states) if state != "pass"), len(states))
        fatal = any(state in FATAL_STATES for state in states)
        pass_after_blocker = any(state == "pass" for state in states[prefix + 1 :])
        if fatal or pass_after_blocker:
            assert result.claim_class == "suppress"
        else:
            assert result.reason == "rule_match"
            assert result.claim_class == expected_by_prefix[prefix]
            assert protocol.claim_definitions[result.claim_class]["strength"] <= protocol._maximum_strength_for_prefix(prefix)
    assert observed == len(EVIDENCE_STATES) ** len(protocol.gate_order)


def test_protocol_tamper_and_malformed_json_are_rejected(tmp_path: Path) -> None:
    from pevl_bench.admission import AdmissionProtocol, AdmissionProtocolError, load_json_document

    protocol_copy = tmp_path / "protocol"
    shutil.copytree(RELEASE / "protocol", protocol_copy)

    tampered_rules = json.loads((protocol_copy / "admission_rules.json").read_text())
    tampered_rules["result_independence"]["rule_inputs"].append("p_value")
    (protocol_copy / "admission_rules.json").write_text(json.dumps(tampered_rules))
    with pytest.raises(AdmissionProtocolError):
        AdmissionProtocol.load(protocol_copy)

    shutil.rmtree(protocol_copy)
    shutil.copytree(RELEASE / "protocol", protocol_copy)
    tampered_claims = json.loads((protocol_copy / "claim_classes.json").read_text())
    tampered_claims["claim_classes"]["schedule_matched"]["strength"] = 5
    (protocol_copy / "claim_classes.json").write_text(json.dumps(tampered_claims))
    with pytest.raises(AdmissionProtocolError):
        AdmissionProtocol.load(protocol_copy)

    shutil.rmtree(protocol_copy)
    shutil.copytree(RELEASE / "protocol", protocol_copy)
    tampered_schema = json.loads((protocol_copy / "admission_schema.json").read_text())
    tampered_schema["properties"]["evidence"]["properties"]["outcome_is_favorable"] = {
        "$ref": "#/$defs/evidenceState"
    }
    (protocol_copy / "admission_schema.json").write_text(json.dumps(tampered_schema))
    with pytest.raises(AdmissionProtocolError):
        AdmissionProtocol.load(protocol_copy)

    malformed = tmp_path / "malformed.json"
    malformed.write_text('{"evidence": ')
    with pytest.raises(AdmissionProtocolError):
        load_json_document(malformed)

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema_version":"a","schema_version":"b"}')
    with pytest.raises(AdmissionProtocolError):
        load_json_document(duplicate)

    oversized_integer = tmp_path / "oversized-integer.json"
    oversized_integer.write_text('{"value":' + "9" * 5000 + "}")
    with pytest.raises(AdmissionProtocolError):
        load_json_document(oversized_integer)


def test_admit_and_explain_cli() -> None:
    evidence = "examples/example_evidence.json"
    admitted = subprocess.run(
        [sys.executable, "-B", "-m", "pevl_bench", "admit", evidence],
        cwd=RELEASE,
        text=True,
        capture_output=True,
        check=True,
    )
    decision = json.loads(admitted.stdout)
    assert decision["permitted_claim_class"] == "schedule_matched"
    explained = subprocess.run(
        [sys.executable, "-B", "-m", "pevl_bench", "explain", evidence],
        cwd=RELEASE,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "Blocking gate: Level 5 repeat-and-worker parity is fail." in explained.stdout
    assert "Additional evidence required:" in explained.stdout
    assert "Redesign recommendation:" in explained.stdout

    malformed = subprocess.run(
        [sys.executable, "-B", "-m", "pevl_bench", "admit", "examples/does-not-exist.json"],
        cwd=RELEASE,
        text=True,
        capture_output=True,
        check=False,
    )
    assert malformed.returncode == 2
    malformed_decision = json.loads(malformed.stdout)
    assert malformed_decision["input_valid"] is False
    assert malformed_decision["permitted_claim_class"] == "suppress"
