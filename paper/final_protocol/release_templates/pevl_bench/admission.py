"""Fail-closed statistical-claim classification for the review package.

This module exposes a deliberately named pure trusted-state classifier.  It is
useful for property testing and for callers that have independently validated
every gate state, but it does not claim to authenticate supporting evidence.
The public ``admit`` command instead uses :mod:`pevl_bench.evidence` to validate
a closed, hashed evidence bundle and derive the gate states before classification.
``result_data`` is never dereferenced by either path and cannot affect a decision.

The JSON bundle is a post-acquisition executable formalization of the frozen
protocol's admission logic.  It is not represented as having existed at the
frozen protocol commit.  The bundle records the conservative mapping assumptions
used to translate the frozen eight-level prose ladder into claim classes.
"""

from __future__ import annotations

import hashlib
import json
import re
import string
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .schema_subset import CheckedSchemaError, check_schema_supported, validate_instance


EVIDENCE_STATES = (
    "pass",
    "fail",
    "unavailable",
    "malformed",
    "contradictory",
    "not_applicable",
)
CLAIM_CLASS_ORDER = (
    "suppress",
    "descriptive_unmatched",
    "schedule_matched",
    "execution_repeatable",
    "seed_matched_bounded",
    "event_aligned",
)
INPUT_SCHEMA_VERSION = "admission-evidence-1.0.0"
RULE_SCHEMA_VERSION = "admission-rules-1.0.0"
CLAIM_SCHEMA_VERSION = "claim-classes-1.0.0"
PROTOCOL_ID = "pevl-admission-formalization-2026-08"
TRUSTED_INPUT_KIND = "trusted_prevalidated_gate_states"
FATAL_STATES = frozenset({"malformed", "contradictory"})
BLOCKING_STATES = frozenset({"fail", "unavailable", "not_applicable"})
DEFAULT_PROTOCOL_DIRECTORY = Path(__file__).resolve().parent.parent / "protocol"
# Semantic trust anchor for the canonicalized four-document protocol bundle.
# The build/test workflow verifies this value, so syntactically valid rule edits
# cannot silently change the classifier's meaning.
EXPECTED_PROTOCOL_BUNDLE_SHA256 = "736f180967d34f17a942b895a3e4d4cd99da0a819ae0d0a50d1f0897cc0698a4"
MAX_JSON_BYTES = 64 * 1024 * 1024

_SAFE_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9_.:-]{0,127}\Z")
_REQUIRED_CLAIM_KEYS = frozenset(
    {
        "strength",
        "label",
        "decision_status",
        "required_wording",
        "forbidden_wording",
        "estimand",
        "analysis_unit",
        "uncertainty_procedure",
        "failure_action",
    }
)
_PROHIBITED_RULE_INPUTS = frozenset(
    {
        "outcome",
        "observed_outcome",
        "observed_treatment_effect",
        "effect_estimate",
        "p_value",
        "confidence_interval",
        "confidence_interval_direction",
        "result_favorability",
    }
)
_ALLOWED_TEMPLATE_FIELDS = frozenset(
    {"projection_id", "projection_version", "projection_fields"}
)


class AdmissionProtocolError(ValueError):
    """Raised when the executable protocol bundle is malformed or unsafe."""


def _reject_json_constant(value: str) -> None:
    raise AdmissionProtocolError(f"non-finite JSON constant prohibited: {value}")


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AdmissionProtocolError(f"duplicate JSON key prohibited: {key}")
        result[key] = value
    return result


def load_json_document(path: Path) -> dict[str, Any]:
    """Load one strict JSON object, rejecting links, duplicates, and NaN/Inf."""

    if (
        not path.is_file()
        or path.is_symlink()
        or path.stat().st_nlink != 1
        or path.stat().st_size > MAX_JSON_BYTES
    ):
        raise AdmissionProtocolError(f"regular JSON file required: {path}")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_pairs,
        )
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise AdmissionProtocolError(f"cannot load JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AdmissionProtocolError(f"JSON object required: {path}")
    return value


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _object_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AdmissionProtocolError(message)


def _require_exact_keys(value: Mapping[str, Any], keys: Iterable[str], label: str) -> None:
    expected = set(keys)
    observed = set(value)
    _require(
        observed == expected,
        f"{label} keys differ: missing={sorted(expected - observed)}, "
        f"extra={sorted(observed - expected)}",
    )


def _template_fields(template: str) -> set[str]:
    try:
        return {
            field_name
            for _, field_name, _, _ in string.Formatter().parse(template)
            if field_name is not None
        }
    except ValueError as exc:
        raise AdmissionProtocolError(f"malformed wording template: {exc}") from exc


@dataclass(frozen=True)
class StatusClassification:
    """Small, allocation-light result used by exhaustive property tests."""

    claim_class: str
    pass_prefix: int
    reason: str
    rule_id: str | None


@dataclass(frozen=True)
class AdmissionProtocol:
    """Validated machine-readable admission rules and claim definitions."""

    rules: dict[str, Any]
    claims: dict[str, Any]
    schema: dict[str, Any]
    evidence_schema: dict[str, Any]
    evidence_verifier_sha256: str
    bundle_sha256: str

    @classmethod
    def load(cls, directory: Path = DEFAULT_PROTOCOL_DIRECTORY) -> "AdmissionProtocol":
        directory = Path(directory)
        rules = load_json_document(directory / "admission_rules.json")
        claims = load_json_document(directory / "claim_classes.json")
        schema = load_json_document(directory / "admission_schema.json")
        evidence_schema = load_json_document(directory / "evidence_bundle_schema.json")
        evidence_verifier_sha256 = hashlib.sha256(
            Path(__file__).with_name("evidence.py").read_bytes()
        ).hexdigest()
        instance = cls(
            rules=rules,
            claims=claims,
            schema=schema,
            evidence_schema=evidence_schema,
            evidence_verifier_sha256=evidence_verifier_sha256,
            bundle_sha256=_object_sha256(
                {
                    "admission_rules": rules,
                    "claim_classes": claims,
                    "admission_schema": schema,
                    "evidence_bundle_schema": evidence_schema,
                    "evidence_verifier_sha256": evidence_verifier_sha256,
                }
            ),
        )
        try:
            instance._validate_bundle()
        except AdmissionProtocolError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise AdmissionProtocolError(
                f"malformed admission protocol bundle: {type(exc).__name__}: {exc}"
            ) from exc
        return instance

    @property
    def gate_order(self) -> tuple[str, ...]:
        return tuple(self.rules["gate_order"])

    @property
    def claim_definitions(self) -> dict[str, dict[str, Any]]:
        return self.claims["claim_classes"]

    @property
    def gate_definitions(self) -> dict[str, dict[str, Any]]:
        return {gate["id"]: gate for gate in self.rules["gates"]}

    @property
    def ordered_rules(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            sorted(self.rules["admission_rules"], key=lambda row: row["priority"], reverse=True)
        )

    def _validate_bundle(self) -> None:
        _require_exact_keys(
            self.rules,
            {
                "schema_version",
                "input_schema_version",
                "protocol_id",
                "formalization_provenance",
                "evidence_states",
                "gate_order",
                "gates",
                "admission_rules",
                "fail_closed",
                "result_independence",
                "projection_scope",
            },
            "admission rules",
        )
        _require(self.rules["schema_version"] == RULE_SCHEMA_VERSION, "unknown rule schema version")
        _require(self.rules["input_schema_version"] == INPUT_SCHEMA_VERSION, "input schema mismatch")
        _require(self.rules["protocol_id"] == PROTOCOL_ID, "unknown admission protocol id")
        _require(tuple(self.rules["evidence_states"]) == EVIDENCE_STATES, "evidence states drifted")

        provenance = self.rules["formalization_provenance"]
        _require(isinstance(provenance, dict), "formalization_provenance must be an object")
        _require_exact_keys(
            provenance,
            {
                "status",
                "frozen_source_protocol",
                "frozen_protocol_commit",
                "created_after_acquisition",
                "authority",
                "mapping_assumptions",
            },
            "formalization provenance",
        )
        _require(
            provenance["status"] == "post_acquisition_executable_formalization",
            "the executable rules must not be represented as prospectively frozen",
        )
        _require(provenance["created_after_acquisition"] is True, "post-acquisition flag required")
        _require(
            provenance["authority"] == "frozen_experiment_specific_rules_remain_authoritative",
            "frozen-rule authority statement missing",
        )
        assumptions = provenance["mapping_assumptions"]
        _require(isinstance(assumptions, list) and assumptions, "mapping assumptions required")
        _require(all(isinstance(item, str) and item.strip() for item in assumptions), "invalid mapping assumption")

        gate_order = self.rules["gate_order"]
        _require(isinstance(gate_order, list) and len(gate_order) == 7, "seven ordered evidence gates required")
        _require(len(set(gate_order)) == len(gate_order), "duplicate evidence gate")
        _require(all(isinstance(item, str) and _SAFE_IDENTIFIER.fullmatch(item) for item in gate_order), "unsafe gate id")
        gates = self.rules["gates"]
        _require(isinstance(gates, list) and len(gates) == len(gate_order), "gate definitions incomplete")
        _require([gate.get("id") for gate in gates if isinstance(gate, dict)] == gate_order, "gate order mismatch")
        for index, gate in enumerate(gates, 1):
            _require(isinstance(gate, dict), f"gate {index} must be an object")
            _require_exact_keys(
                gate,
                {"id", "level", "title", "question", "evidence_required", "blocked_action"},
                f"gate {index}",
            )
            _require(gate["level"] == index, f"gate level must be {index}")
            for field in ("title", "question", "evidence_required", "blocked_action"):
                _require(isinstance(gate[field], str) and gate[field].strip(), f"gate {index} {field} missing")

        fail_closed = self.rules["fail_closed"]
        _require(isinstance(fail_closed, dict), "fail_closed must be an object")
        _require_exact_keys(
            fail_closed,
            {
                "fatal_evidence_states",
                "blocking_evidence_states",
                "structural_contradiction",
                "invalid_input_claim_class",
                "unrecognized_input_claim_class",
                "missing_input_claim_class",
            },
            "fail_closed",
        )
        _require(frozenset(fail_closed["fatal_evidence_states"]) == FATAL_STATES, "fatal-state policy drifted")
        _require(frozenset(fail_closed["blocking_evidence_states"]) == BLOCKING_STATES, "blocking-state policy drifted")
        _require(fail_closed["structural_contradiction"] == "pass_after_non_pass", "contradiction rule drifted")
        for key in ("invalid_input_claim_class", "unrecognized_input_claim_class", "missing_input_claim_class"):
            _require(fail_closed[key] == "suppress", f"{key} must fail closed")

        independence = self.rules["result_independence"]
        _require(isinstance(independence, dict), "result_independence must be an object")
        _require_exact_keys(
            independence,
            {"rule_inputs", "ignored_envelope_members", "prohibited_rule_inputs"},
            "result_independence",
        )
        _require(independence["rule_inputs"] == ["evidence", "trace_projection"], "rule input projection drifted")
        _require(
            set(independence["ignored_envelope_members"]) == {"result_data"},
            "ignored input envelope drifted",
        )
        _require(
            frozenset(independence["prohibited_rule_inputs"]) == _PROHIBITED_RULE_INPUTS,
            "prohibited result inputs drifted",
        )

        projection_scope = self.rules["projection_scope"]
        _require_exact_keys(
            projection_scope,
            {"required_minimum_claim_strength", "wording_must_name_projection", "unscoped_repeatability_action"},
            "projection_scope",
        )
        _require(projection_scope["required_minimum_claim_strength"] == 3, "projection strength must be three")
        _require(projection_scope["wording_must_name_projection"] is True, "projection wording must be explicit")
        _require(projection_scope["unscoped_repeatability_action"] == "suppress", "unscoped repeatability must suppress")

        _require_exact_keys(
            self.claims,
            {"schema_version", "protocol_id", "ordering", "claim_classes"},
            "claim classes",
        )
        _require(self.claims["schema_version"] == CLAIM_SCHEMA_VERSION, "claim schema version mismatch")
        _require(self.claims["protocol_id"] == PROTOCOL_ID, "claim protocol id mismatch")
        _require(tuple(self.claims["ordering"]) == CLAIM_CLASS_ORDER, "claim-class ordering drifted")
        claim_definitions = self.claims["claim_classes"]
        _require(isinstance(claim_definitions, dict), "claim_classes must be an object")
        _require(set(claim_definitions) == set(CLAIM_CLASS_ORDER), "claim class set drifted")
        for strength, claim_id in enumerate(CLAIM_CLASS_ORDER):
            claim = claim_definitions[claim_id]
            _require(isinstance(claim, dict), f"claim class {claim_id} must be an object")
            _require_exact_keys(claim, _REQUIRED_CLAIM_KEYS, f"claim class {claim_id}")
            _require(claim["strength"] == strength, f"claim class {claim_id} strength drifted")
            expected_status = "suppress" if strength == 0 else ("admit" if strength >= 4 else "downgrade")
            _require(claim["decision_status"] == expected_status, f"claim class {claim_id} decision status drifted")
            for field in (
                "label",
                "required_wording",
                "estimand",
                "analysis_unit",
                "uncertainty_procedure",
                "failure_action",
            ):
                _require(isinstance(claim[field], str) and claim[field].strip(), f"claim class {claim_id} {field} missing")
            forbidden = claim["forbidden_wording"]
            _require(isinstance(forbidden, list) and forbidden, f"claim class {claim_id} forbidden wording missing")
            _require(all(isinstance(item, str) and item.strip() for item in forbidden), f"claim class {claim_id} invalid forbidden wording")
            fields = _template_fields(claim["required_wording"])
            _require(fields <= _ALLOWED_TEMPLATE_FIELDS, f"claim class {claim_id} has unsafe wording placeholder")
            if strength >= projection_scope["required_minimum_claim_strength"]:
                _require(fields == _ALLOWED_TEMPLATE_FIELDS, f"claim class {claim_id} must name the trace projection")
            else:
                _require(not fields, f"claim class {claim_id} must not imply a trace projection")

        rules = self.rules["admission_rules"]
        _require(isinstance(rules, list) and len(rules) == len(CLAIM_CLASS_ORDER), "one admission rule per claim class required")
        priorities: set[int] = set()
        covered_prefixes: dict[int, str] = {}
        seen_claims: set[str] = set()
        for rule in rules:
            _require(isinstance(rule, dict), "admission rule must be an object")
            _require_exact_keys(
                rule,
                {"id", "priority", "min_pass_prefix", "max_pass_prefix", "claim_class"},
                "admission rule",
            )
            _require(isinstance(rule["id"], str) and _SAFE_IDENTIFIER.fullmatch(rule["id"]), "unsafe rule id")
            _require(isinstance(rule["priority"], int) and not isinstance(rule["priority"], bool), "integer rule priority required")
            _require(rule["priority"] not in priorities, "duplicate rule priority")
            priorities.add(rule["priority"])
            claim_id = rule["claim_class"]
            _require(claim_id in claim_definitions and claim_id not in seen_claims, "invalid or duplicate rule claim class")
            seen_claims.add(claim_id)
            minimum = rule["min_pass_prefix"]
            maximum = rule["max_pass_prefix"]
            _require(
                isinstance(minimum, int)
                and not isinstance(minimum, bool)
                and isinstance(maximum, int)
                and not isinstance(maximum, bool)
                and 0 <= minimum <= maximum <= len(gate_order),
                "invalid pass-prefix range",
            )
            for prefix in range(minimum, maximum + 1):
                _require(prefix not in covered_prefixes, f"pass prefix {prefix} covered twice")
                covered_prefixes[prefix] = rule["id"]
            strength = claim_definitions[claim_id]["strength"]
            maximum_evidence_strength = self._maximum_strength_for_prefix(maximum)
            _require(strength <= maximum_evidence_strength, f"rule {rule['id']} strengthens beyond its evidence")
        _require(set(covered_prefixes) == set(range(len(gate_order) + 1)), "pass-prefix rules are not exhaustive")
        _require(seen_claims == set(CLAIM_CLASS_ORDER), "not every claim class is mapped")

        self._validate_schema()
        try:
            check_schema_supported(self.schema)
            check_schema_supported(self.evidence_schema)
        except CheckedSchemaError as exc:
            raise AdmissionProtocolError(f"unsupported checked JSON Schema: {exc}") from exc
        _require(
            self.bundle_sha256 == EXPECTED_PROTOCOL_BUNDLE_SHA256,
            "protocol bundle semantic hash differs from the embedded trust anchor",
        )

    @staticmethod
    def _maximum_strength_for_prefix(prefix: int) -> int:
        if prefix == 0:
            return 0
        if prefix <= 2:
            return 1
        if prefix <= 4:
            return 2
        if prefix == 5:
            return 3
        if prefix == 6:
            return 4
        return 5

    def _validate_schema(self) -> None:
        schema = self.schema
        _require(schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema", "JSON Schema draft mismatch")
        _require(schema.get("type") == "object", "admission input schema must describe an object")
        _require(schema.get("additionalProperties") is False, "admission input schema must reject unknown members")
        _require(
            set(schema.get("required", []))
            == {"schema_version", "protocol_id", "input_kind", "evidence", "trace_projection"},
            "admission schema required members drifted",
        )
        properties = schema.get("properties")
        _require(isinstance(properties, dict), "admission schema properties missing")
        _require(
            set(properties)
            == {"schema_version", "protocol_id", "input_kind", "evidence", "trace_projection", "result_data"},
            "admission schema property set drifted",
        )
        _require(properties["schema_version"].get("const") == INPUT_SCHEMA_VERSION, "admission schema version constant drifted")
        _require(properties["protocol_id"].get("const") == PROTOCOL_ID, "admission schema protocol constant drifted")
        _require(properties["input_kind"].get("const") == TRUSTED_INPUT_KIND, "trusted input-kind constant drifted")
        evidence = properties["evidence"]
        _require(evidence.get("type") == "object" and evidence.get("additionalProperties") is False, "evidence schema must be closed")
        _require(evidence.get("required") == list(self.gate_order), "evidence schema gate order drifted")
        _require(set(evidence.get("properties", {})) == set(self.gate_order), "evidence schema gates drifted")
        for gate_schema in evidence["properties"].values():
            _require(gate_schema == {"$ref": "#/$defs/evidenceState"}, "gate schema must reference evidenceState")
        definitions = schema.get("$defs")
        _require(isinstance(definitions, dict), "admission schema definitions missing")
        _require(definitions.get("evidenceState", {}).get("enum") == list(EVIDENCE_STATES), "evidence-state schema drifted")
        trace_projection = definitions.get("traceProjection", {})
        _require(set(trace_projection.get("required", [])) == {"id", "version", "fields"}, "trace projection schema incomplete")
        field_items = trace_projection.get("properties", {}).get("fields", {}).get("items", {})
        _require(
            frozenset(field_items.get("not", {}).get("enum", [])) == _PROHIBITED_RULE_INPUTS,
            "trace projection must exclude all prohibited result fields",
        )

    def classify_status_vector(self, states: Sequence[str]) -> StatusClassification:
        """Classify an ordered gate-state vector without reading any result data."""

        if len(states) != len(self.gate_order):
            return StatusClassification("suppress", 0, "invalid_status_vector_length", None)
        if any(state not in EVIDENCE_STATES for state in states):
            return StatusClassification("suppress", 0, "unrecognized_evidence_state", None)
        first_fatal = next((index for index, state in enumerate(states) if state in FATAL_STATES), None)
        if first_fatal is not None:
            prefix = next((index for index, state in enumerate(states) if state != "pass"), len(states))
            return StatusClassification("suppress", prefix, "fatal_evidence_state", None)
        prefix = next((index for index, state in enumerate(states) if state != "pass"), len(states))
        if any(state == "pass" for state in states[prefix + 1 :]):
            return StatusClassification("suppress", prefix, "pass_after_non_pass", None)
        for rule in self.ordered_rules:
            if rule["min_pass_prefix"] <= prefix <= rule["max_pass_prefix"]:
                return StatusClassification(rule["claim_class"], prefix, "rule_match", rule["id"])
        return StatusClassification("suppress", prefix, "uncovered_status_vector", None)

    def evaluate_trusted_states(self, document: Mapping[str, Any] | Any) -> dict[str, Any]:
        """Classify caller-asserted, prevalidated gate states.

        This pure interface intentionally does not verify scientific records.
        Use :func:`pevl_bench.evidence.verify_and_admit` for public admission.
        """

        try:
            validate_instance(document, self.schema, label="trusted gate-state input")
        except CheckedSchemaError as exc:
            return self._invalid_decision([str(exc)])
        projected, errors = self._project_input(document)
        if errors:
            return self._invalid_decision(errors)
        assert projected is not None
        states = tuple(projected["evidence"][gate] for gate in self.gate_order)
        classification = self.classify_status_vector(states)
        projection = projected["trace_projection"]
        claim = self.claim_definitions[classification.claim_class]
        required_projection_strength = self.rules["projection_scope"]["required_minimum_claim_strength"]
        if claim["strength"] >= required_projection_strength and projection is None:
            return self._invalid_decision(
                ["a declared trace projection is required for repeatability or stronger wording"],
                classification_reason="unscoped_repeatability",
                states=states,
            )
        return self._materialize_decision(projected, states, classification)

    def _evaluate_verifier_states(
        self,
        document: Mapping[str, Any] | Any,
        *,
        evidence_binding_sha256: str,
        verifier_id: str,
        gate_certificates: Sequence[Mapping[str, Any]],
        input_assurance: str = "declared_bundle_files_verified_and_record_checks_evaluated",
        classifier_scope: str = "classification_after_file_hash_verification_and_record_checks",
        evidence_trust_anchor: str | None = None,
        verification_scope: str | None = None,
        verifier_implementation_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Internal adapter hook for states derived by a named verifier."""

        decision = self.evaluate_trusted_states(document)
        return self._set_assurance(
            decision,
            input_assurance=input_assurance,
            classifier_scope=classifier_scope,
            evidence_verified=bool(decision["input_valid"]),
            evidence_binding_sha256=evidence_binding_sha256,
            verifier_id=verifier_id,
            gate_certificates=gate_certificates,
            evidence_trust_anchor=evidence_trust_anchor,
            verification_scope=verification_scope,
            verifier_implementation_sha256=verifier_implementation_sha256,
        )

    def invalid_verified_evidence(
        self,
        errors: Sequence[str],
        *,
        evidence_binding_sha256: str | None = None,
        verifier_id: str,
        gate_certificates: Sequence[Mapping[str, Any]] = (),
    ) -> dict[str, Any]:
        """Return a fail-closed decision for a rejected evidence bundle."""

        return self._set_assurance(
            self._invalid_decision(errors, classification_reason="evidence_verification_failed"),
            input_assurance="machine_evidence_rejected",
            classifier_scope="verification_failed_before_classification",
            evidence_verified=False,
            evidence_binding_sha256=evidence_binding_sha256,
            verifier_id=verifier_id,
            gate_certificates=gate_certificates,
            evidence_trust_anchor=None,
            verification_scope=None,
            verifier_implementation_sha256=None,
        )

    def _project_input(self, document: Any) -> tuple[dict[str, Any] | None, list[str]]:
        if not isinstance(document, Mapping):
            return None, ["input must be a JSON object"]
        required = {"schema_version", "protocol_id", "input_kind", "evidence", "trace_projection"}
        allowed = required | {"result_data"}
        observed = set(document)
        errors = []
        if required - observed:
            errors.append(f"missing input members: {', '.join(sorted(required - observed))}")
        if observed - allowed:
            errors.append(f"unrecognized input members: {', '.join(sorted(observed - allowed))}")
        if document.get("schema_version") != INPUT_SCHEMA_VERSION:
            errors.append("unrecognized input schema_version")
        if document.get("protocol_id") != PROTOCOL_ID:
            errors.append("unrecognized protocol_id")
        if document.get("input_kind") != TRUSTED_INPUT_KIND:
            errors.append("unrecognized trusted-state input_kind")
        evidence = document.get("evidence")
        if not isinstance(evidence, Mapping):
            errors.append("evidence must be an object")
            return None, errors
        observed_gates = set(evidence)
        expected_gates = set(self.gate_order)
        if expected_gates - observed_gates:
            errors.append(f"missing evidence gates: {', '.join(sorted(expected_gates - observed_gates))}")
        if observed_gates - expected_gates:
            errors.append(f"unrecognized evidence gates: {', '.join(sorted(observed_gates - expected_gates))}")
        for gate in self.gate_order:
            if gate in evidence and evidence[gate] not in EVIDENCE_STATES:
                errors.append(f"unrecognized evidence state for {gate}")
        projection, projection_errors = self._validate_projection(document.get("trace_projection"))
        errors.extend(projection_errors)
        if errors:
            return None, errors
        return {
            "schema_version": INPUT_SCHEMA_VERSION,
            "protocol_id": PROTOCOL_ID,
            "input_kind": TRUSTED_INPUT_KIND,
            "evidence": {gate: evidence[gate] for gate in self.gate_order},
            "trace_projection": projection,
        }, []

    @staticmethod
    def _validate_projection(value: Any) -> tuple[dict[str, Any] | None, list[str]]:
        if value is None:
            return None, []
        if not isinstance(value, Mapping):
            return None, ["trace_projection must be null or an object"]
        expected = {"id", "version", "fields"}
        observed = set(value)
        if observed != expected:
            return None, [
                "trace_projection members differ: "
                f"missing={sorted(expected - observed)}, extra={sorted(observed - expected)}"
            ]
        projection_id = value["id"]
        version = value["version"]
        fields = value["fields"]
        errors = []
        if not isinstance(projection_id, str) or not _SAFE_IDENTIFIER.fullmatch(projection_id):
            errors.append("trace_projection.id is invalid")
        if not isinstance(version, str) or not _SAFE_IDENTIFIER.fullmatch(version):
            errors.append("trace_projection.version is invalid")
        if (
            not isinstance(fields, list)
            or not fields
            or any(not isinstance(field, str) or not _SAFE_IDENTIFIER.fullmatch(field) for field in fields)
            or len(set(fields)) != len(fields)
        ):
            errors.append("trace_projection.fields must be a nonempty unique list of identifiers")
        elif any(field in _PROHIBITED_RULE_INPUTS for field in fields):
            errors.append("trace_projection.fields contains a result field excluded from admission")
        if errors:
            return None, errors
        return {"id": projection_id, "version": version, "fields": list(fields)}, []

    def _materialize_decision(
        self,
        projected: dict[str, Any],
        states: tuple[str, ...],
        classification: StatusClassification,
    ) -> dict[str, Any]:
        claim = self.claim_definitions[classification.claim_class]
        projection = projected["trace_projection"]
        template_values = {
            "projection_id": projection["id"] if projection else "not-applicable",
            "projection_version": projection["version"] if projection else "not-applicable",
            "projection_fields": ", ".join(projection["fields"]) if projection else "not-applicable",
        }
        blockers = [
            {"gate": gate, "state": state}
            for gate, state in zip(self.gate_order, states)
            if state != "pass"
        ]
        first_blocker = blockers[0] if blockers else None
        gate_report = []
        for index, (gate, state) in enumerate(zip(self.gate_order, states)):
            if state in FATAL_STATES:
                effect = "fatal evidence state; all comparative claims suppressed"
            elif classification.reason == "pass_after_non_pass" and state == "pass" and index > classification.pass_prefix:
                effect = "contradicts an unsatisfied prerequisite"
            elif state == "pass":
                effect = "satisfied prerequisite"
            elif index == classification.pass_prefix:
                effect = "first gate blocking stronger wording"
            else:
                effect = "downstream gate does not repair an earlier blocker"
            gate_report.append(
                {
                    "gate": gate,
                    "level": index + 1,
                    "state": state,
                    "effect": effect,
                }
            )
        coherent = classification.reason == "rule_match"
        if first_blocker:
            gate = self.gate_definitions[first_blocker["gate"]]
            why = (
                f"Stronger wording is prohibited because Level {gate['level']} "
                f"({gate['title']}) is {first_blocker['state']}."
            )
            additional = gate["evidence_required"]
        else:
            why = "No stronger claim class exists in this admission specification."
            additional = "No additional gate is required for this claim class."
        if not coherent:
            why = "Stronger wording is prohibited because the evidence is malformed or structurally contradictory."
            additional = "Repair the malformed or contradictory gate record and rerun admission from the original evidence."
        decision = {
            "protocol_id": PROTOCOL_ID,
            "formalization_status": self.rules["formalization_provenance"]["status"],
            "rules_schema_version": RULE_SCHEMA_VERSION,
            "input_schema_version": INPUT_SCHEMA_VERSION,
            "protocol_bundle_sha256": self.bundle_sha256,
            "admission_input_sha256": _object_sha256(projected),
            "input_assurance": "caller_asserted_prevalidated_states",
            "classifier_scope": "classification_only",
            "evidence_verified": False,
            "evidence_binding_sha256": None,
            "evidence_verifier": None,
            "gate_certificates": [],
            "excluded_input_members": ["result_data"],
            "input_valid": True,
            "evidence_coherent": coherent,
            "classification_reason": classification.reason,
            "matched_rule": classification.rule_id,
            "decision_status": claim["decision_status"],
            "permitted_claim_class": classification.claim_class,
            "claim_strength": claim["strength"],
            "required_wording": claim["required_wording"].format(**template_values),
            "forbidden_wording": list(claim["forbidden_wording"]),
            "estimand": claim["estimand"],
            "analysis_unit": claim["analysis_unit"],
            "uncertainty_procedure": claim["uncertainty_procedure"],
            "failure_action": claim["failure_action"],
            "gate_report": gate_report,
            "blocking_gates": blockers,
            "first_blocking_gate": first_blocker,
            "why_stronger_prohibited": why,
            "additional_evidence_required": additional,
            "trace_projection_scope": projection if claim["strength"] >= 3 else None,
        }
        decision["decision_sha256"] = _object_sha256(decision)
        return decision

    def _invalid_decision(
        self,
        errors: Sequence[str],
        *,
        classification_reason: str = "invalid_input",
        states: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        claim = self.claim_definitions["suppress"]
        decision = {
            "protocol_id": PROTOCOL_ID,
            "formalization_status": self.rules["formalization_provenance"]["status"],
            "rules_schema_version": RULE_SCHEMA_VERSION,
            "input_schema_version": INPUT_SCHEMA_VERSION,
            "protocol_bundle_sha256": self.bundle_sha256,
            "admission_input_sha256": None,
            "input_assurance": "caller_asserted_prevalidated_states",
            "classifier_scope": "classification_only",
            "evidence_verified": False,
            "evidence_binding_sha256": None,
            "evidence_verifier": None,
            "gate_certificates": [],
            "excluded_input_members": ["result_data"],
            "input_valid": False,
            "evidence_coherent": False,
            "classification_reason": classification_reason,
            "matched_rule": None,
            "decision_status": "suppress",
            "permitted_claim_class": "suppress",
            "claim_strength": 0,
            "required_wording": claim["required_wording"],
            "forbidden_wording": list(claim["forbidden_wording"]),
            "estimand": claim["estimand"],
            "analysis_unit": claim["analysis_unit"],
            "uncertainty_procedure": claim["uncertainty_procedure"],
            "failure_action": claim["failure_action"],
            "gate_report": [],
            "blocking_gates": [],
            "first_blocking_gate": None,
            "why_stronger_prohibited": "Stronger wording is prohibited because the admission input is invalid.",
            "additional_evidence_required": "Supply a complete, recognized, internally coherent gate record.",
            "trace_projection_scope": None,
            "validation_errors": list(errors),
        }
        if states is not None:
            decision["recognized_status_vector_length"] = len(states)
        decision["decision_sha256"] = _object_sha256(decision)
        return decision

    def _set_assurance(
        self,
        decision: Mapping[str, Any],
        *,
        input_assurance: str,
        classifier_scope: str,
        evidence_verified: bool,
        evidence_binding_sha256: str | None,
        verifier_id: str,
        gate_certificates: Sequence[Mapping[str, Any]],
        evidence_trust_anchor: str | None,
        verification_scope: str | None,
        verifier_implementation_sha256: str | None,
    ) -> dict[str, Any]:
        updated = dict(decision)
        updated.pop("decision_sha256", None)
        updated.update(
            {
                "input_assurance": input_assurance,
                "classifier_scope": classifier_scope,
                "evidence_verified": evidence_verified,
                "external_scientific_provenance_verified": False,
                "evidence_trust_anchor": (
                    evidence_trust_anchor
                    if evidence_verified and evidence_trust_anchor is not None
                    else (
                        "self_asserted_internal_consistency"
                        if evidence_verified
                        else "none_verification_failed"
                    )
                ),
                "verification_scope": (
                    verification_scope
                    if evidence_verified and verification_scope is not None
                    else (
                        "Bundle-relative regular single-link files matched declared SHA-256 values "
                        "and trace byte counts; record checks produced the reported gate states. "
                        "File roles, execution-profile provenance, and trace-content semantics remain "
                        "caller assertions and require an external trust anchor. Verification assumes "
                        "a quiescent bundle with no concurrent local filesystem mutation."
                    )
                    if evidence_verified
                    else "Verification failed before file binding and record consistency were established."
                ),
                "evidence_binding_sha256": evidence_binding_sha256,
                "evidence_verifier": verifier_id,
                "evidence_verifier_sha256": (
                    verifier_implementation_sha256 or self.evidence_verifier_sha256
                ),
                "gate_certificates": [dict(item) for item in gate_certificates],
            }
        )
        updated["decision_sha256"] = _object_sha256(updated)
        return updated

    def explain(self, decision: Mapping[str, Any]) -> str:
        """Render a deterministic human explanation of one admission decision."""

        lines = [
            f"Decision: {decision['decision_status']}",
            f"Permitted claim class: {decision['permitted_claim_class']}",
            f"Input assurance: {decision['input_assurance']}",
            f"Evidence verified: {str(decision['evidence_verified']).lower()}",
            f"Required wording: {decision['required_wording']}",
        ]
        first = decision.get("first_blocking_gate")
        if first:
            gate = self.gate_definitions[first["gate"]]
            lines.append(
                f"Blocking gate: Level {gate['level']} {gate['title']} is {first['state']}."
            )
        elif not decision.get("input_valid"):
            lines.append("Blocking gate: the input record is missing, malformed, or unrecognized.")
        else:
            lines.append("Blocking gate: none.")
        lines.extend(
            [
                f"Why stronger wording is prohibited: {decision['why_stronger_prohibited']}",
                f"Additional evidence required: {decision['additional_evidence_required']}",
                f"Redesign recommendation: {decision['failure_action']}",
                "Forbidden wording:",
            ]
        )
        lines.extend(f"- {item}" for item in decision["forbidden_wording"])
        projection = decision.get("trace_projection_scope")
        if projection:
            lines.append(
                "Recorded trace projection: "
                f"{projection['id']}@{projection['version']} "
                f"[{', '.join(projection['fields'])}]"
            )
        return "\n".join(lines) + "\n"

    def render_decision_table(self) -> str:
        """Generate the human decision table solely from the validated JSON rules."""

        provenance = self.rules["formalization_provenance"]
        lines = [
            "# Admission decision table",
            "",
            "Generated from `protocol/admission_rules.json` and "
            "`protocol/claim_classes.json`; do not edit this table independently.",
            "",
            f"Formalization status: `{provenance['status']}`. This executable map was "
            "created after acquisition. The frozen experiment-specific protocol remains authoritative.",
            "",
            "## Interfaces and trust boundary",
            "",
            "`AdmissionProtocol.evaluate_trusted_states` is a pure classifier for explicitly trusted, "
            "prevalidated gate states. It does not inspect or authenticate scientific records and its "
            "decision reports `caller_asserted_prevalidated_states`. The public `admit` command accepts "
            "the separate closed file-bound record schema, checks its hash and declared support bytes, "
            "derives every gate state that the included records can establish, and reports file-verification "
            "certificates. Roles, profile provenance, and trace semantics remain caller assertions. The "
            "included bundle deliberately marks the source audit unavailable and event alignment not "
            "applicable; it cannot manufacture stronger evidence.",
            "",
            "## Ordered evidence gates",
            "",
            "| Level | Gate | Question | Evidence required when blocked |",
            "|---:|---|---|---|",
        ]
        for gate in self.rules["gates"]:
            lines.append(
                f"| {gate['level']} | `{gate['id']}` | {gate['question']} | {gate['evidence_required']} |"
            )
        lines.extend(
            [
                "",
                "## Complete rule partition",
                "",
                "A pass prefix is the number of consecutive `pass` states from Level 1. "
                "After the first non-pass state, any later `pass` is contradictory and suppresses the claim.",
                "",
                "| Pass prefix | Permitted class | Decision | Required wording | Estimand | Analysis unit | Uncertainty | Failure action |",
                "|---:|---|---|---|---|---|---|---|",
            ]
        )
        for rule in sorted(self.ordered_rules, key=lambda row: row["min_pass_prefix"]):
            minimum = rule["min_pass_prefix"]
            maximum = rule["max_pass_prefix"]
            span = str(minimum) if minimum == maximum else f"{minimum}--{maximum}"
            claim = self.claim_definitions[rule["claim_class"]]
            wording = claim["required_wording"].replace("|", "\\|")
            lines.append(
                f"| {span} | `{rule['claim_class']}` | {claim['decision_status']} | "
                f"{wording} | {claim['estimand']} | {claim['analysis_unit']} | "
                f"{claim['uncertainty_procedure']} | {claim['failure_action']} |"
            )
        lines.extend(
            [
                "",
                "## Fail-closed cases",
                "",
                "Missing gates, extra gates, unknown states, malformed projections, and unknown "
                "schema or protocol identifiers produce `suppress`. Explicit `malformed` or "
                "`contradictory` states also produce `suppress`. `fail`, `unavailable`, and "
                "`not_applicable` never count as a passed prerequisite.",
                "",
                "The rule matcher receives only gate states and the declared trace projection. "
                "Result data—including effect estimates, "
                "p-values, interval direction, and favorability—are outside the rule projection.",
                "",
                "## Mapping assumptions",
                "",
            ]
        )
        lines.extend(f"- {item}" for item in provenance["mapping_assumptions"])
        return "\n".join(lines) + "\n"

    def decision_table_sha256(self) -> str:
        return hashlib.sha256(self.render_decision_table().encode("utf-8")).hexdigest()

    def exhaustive_status_vectors(self) -> Iterable[tuple[str, ...]]:
        """Yield the complete finite state space in deterministic order."""

        return product(EVIDENCE_STATES, repeat=len(self.gate_order))


def classify_trusted_file(path: Path, protocol: AdmissionProtocol | None = None) -> dict[str, Any]:
    protocol = protocol or AdmissionProtocol.load()
    return protocol.evaluate_trusted_states(load_json_document(Path(path)))
