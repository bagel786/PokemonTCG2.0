"""Command-line entry point for the standalone review package."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from . import admission, evidence, synthetic, synthetic_admission
from .schema_subset import CheckedSchemaError, validate_instance


PACKAGE = Path(__file__).resolve().parent
RELEASE = PACKAGE.parent
DEFAULT_RESULTS = PACKAGE / "results"
DEFAULT_ADMISSION_RESULTS = PACKAGE / "admission_results"


def _load_json(relative: str) -> dict:
    path = RELEASE / relative
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {relative}")
    return value


def _report(protocol: admission.AdmissionProtocol) -> dict:
    preflight = _load_json("data/processed/preflight_summary.json")
    stress = _load_json("data/processed/timed_search_stress.json")
    factorial = _load_json("data/processed/factorial_summary.json")
    historical = _load_json("data/processed/historical_summary.json")
    failures = synthetic.verify_outputs(DEFAULT_RESULTS)
    if failures:
        raise ValueError("synthetic fixture verification failed: " + "; ".join(failures))
    admission_failures = synthetic_admission.verify_outputs(
        DEFAULT_ADMISSION_RESULTS, protocol
    )
    if admission_failures:
        raise ValueError(
            "synthetic admission verification failed: "
            + "; ".join(admission_failures)
        )
    _validate_synthetic_schema(DEFAULT_RESULTS)
    decision_table = protocol.render_decision_table()
    decision_table_path = RELEASE / "docs/ADMISSION_DECISION_TABLE.md"
    if decision_table_path.read_text(encoding="utf-8") != decision_table:
        raise ValueError("generated admission decision table is stale")
    example = evidence.verify_and_admit(
        admission.load_json_document(RELEASE / "examples/example_evidence.json"),
        protocol,
        evidence_root=RELEASE / "examples",
    )
    if not example["input_valid"]:
        raise ValueError("worked admission example is invalid")
    return {
        "package_scope": "processed diagnostics and a synthetic conformance suite; no restricted engine",
        "protocol_commit": preflight["protocol_commit"],
        "synthetic": {"status": "verified", "modes": 5},
        "historical_repeated_control": {
            "units": historical["units"],
            "outcome_record_mismatches": historical["outcome_record_mismatches"],
            "available_record_mismatches": historical["available_record_mismatches"],
        },
        "deterministic_preflight": {
            "status": preflight["status"],
            "trajectory_units": preflight["trajectory_units"],
            "executions": preflight["executions"],
            "trace_mismatch_units": preflight["trace_mismatch_units"],
        },
        "timed_search_stress": {
            "status": stress["status"],
            "clusters": stress["clusters"],
            "trace_disagreement_clusters": stress["trace_disagreement_clusters"],
            "trace_disagreement": stress["trace_disagreement"],
        },
        "factorial": {
            "status": factorial["status"],
            "units": factorial["units"],
            "games": factorial["games"],
            "contrasts": factorial["contrasts"],
        },
        "admission_protocol": {
            "protocol_id": protocol.rules["protocol_id"],
            "formalization_status": protocol.rules["formalization_provenance"]["status"],
            "evidence_gates": len(protocol.gate_order),
            "evidence_states": len(protocol.rules["evidence_states"]),
            "claim_classes": len(protocol.claim_definitions),
            "decision_table_sha256": protocol.decision_table_sha256(),
            "worked_example_claim_class": example["permitted_claim_class"],
            "worked_example_evidence_verified": example["evidence_verified"],
            "worked_example_external_scientific_provenance_verified": example[
                "external_scientific_provenance_verified"
            ],
            "worked_example_trust_anchor": example["evidence_trust_anchor"],
        },
    }


def _validate_synthetic_schema(output_dir: Path) -> None:
    report = admission.load_json_document(output_dir / "pevl_results.json")
    schema = admission.load_json_document(output_dir / "pevl_results.schema.json")
    try:
        validate_instance(report, schema, label="synthetic results")
    except CheckedSchemaError as exc:
        raise ValueError(f"synthetic JSON Schema validation failed: {exc}") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate or verify fixtures, evaluate admission evidence, or report review artifacts."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("generate", "verify"):
        child = subparsers.add_parser(command)
        child.add_argument(
            "--output-dir",
            type=Path,
            default=DEFAULT_RESULTS,
            help="synthetic artifact directory",
        )
        child.add_argument(
            "--admission-output-dir",
            type=Path,
            default=DEFAULT_ADMISSION_RESULTS,
            help="synthetic admission-decision artifact directory",
        )
    admit = subparsers.add_parser("admit", help="emit a machine-readable admission decision")
    admit.add_argument("evidence_file", type=Path)
    explain = subparsers.add_parser("explain", help="explain an admission decision")
    explain.add_argument("evidence_file", type=Path)
    trusted = subparsers.add_parser(
        "classify-trusted",
        help="classify explicitly trusted prevalidated states without claiming evidence verification",
    )
    trusted.add_argument("state_file", type=Path)
    report = subparsers.add_parser("report")
    report_output = report.add_mutually_exclusive_group()
    report_output.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    report_output.add_argument(
        "--decision-table",
        action="store_true",
        help="emit the generated human-readable admission decision table",
    )
    return parser


def _admission_from_file(
    protocol: admission.AdmissionProtocol,
    evidence_file: Path,
) -> dict:
    return evidence.admit_file(evidence_file, protocol)


def _trusted_classification_from_file(
    protocol: admission.AdmissionProtocol,
    state_file: Path,
) -> dict:
    try:
        document = admission.load_json_document(state_file)
    except admission.AdmissionProtocolError as exc:
        return protocol._invalid_decision([str(exc)])
    return protocol.evaluate_trusted_states(document)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "generate":
        synthetic.write_outputs(args.output_dir)
        try:
            protocol = admission.AdmissionProtocol.load()
            synthetic_admission.write_outputs(args.admission_output_dir, protocol)
        except (admission.AdmissionProtocolError, ValueError) as exc:
            print(f"FAIL: admission generation failed: {exc}", file=sys.stderr)
            return 2
        failures = synthetic.verify_outputs(args.output_dir)
        failures.extend(
            synthetic_admission.verify_outputs(args.admission_output_dir, protocol)
        )
        try:
            _validate_synthetic_schema(args.output_dir)
        except (ValueError, admission.AdmissionProtocolError) as exc:
            failures.append(str(exc))
        if failures:
            for failure in failures:
                print(f"FAIL: {failure}", file=sys.stderr)
            return 1
        print(
            f"generated and verified {args.output_dir} and "
            f"{args.admission_output_dir}"
        )
        return 0
    if args.command == "verify":
        failures = synthetic.verify_outputs(args.output_dir)
        try:
            protocol = admission.AdmissionProtocol.load()
            failures.extend(
                synthetic_admission.verify_outputs(args.admission_output_dir, protocol)
            )
            _validate_synthetic_schema(args.output_dir)
        except (admission.AdmissionProtocolError, ValueError) as exc:
            failures.append(str(exc))
        if failures:
            for failure in failures:
                print(f"FAIL: {failure}", file=sys.stderr)
            return 1
        print(f"verified {args.output_dir} and {args.admission_output_dir}")
        return 0
    try:
        protocol = admission.AdmissionProtocol.load()
    except admission.AdmissionProtocolError as exc:
        print(f"FAIL: admission protocol invalid: {exc}", file=sys.stderr)
        return 2
    if args.command in {"admit", "explain"}:
        decision = _admission_from_file(protocol, args.evidence_file)
        if args.command == "admit":
            print(json.dumps(decision, indent=2, sort_keys=True, allow_nan=False))
        else:
            print(protocol.explain(decision), end="")
        return 0 if decision["input_valid"] else 2
    if args.command == "classify-trusted":
        decision = _trusted_classification_from_file(protocol, args.state_file)
        print(json.dumps(decision, indent=2, sort_keys=True, allow_nan=False))
        return 0 if decision["input_valid"] else 2
    if args.decision_table:
        print(protocol.render_decision_table(), end="")
        return 0
    report = _report(protocol)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("Synthetic conformance suite: verified (5 modes)")
        print(
            "Historical repeated-control mismatches: "
            f"{report['historical_repeated_control']['outcome_record_mismatches']}/"
            f"{report['historical_repeated_control']['units']} outcome records; "
            f"{report['historical_repeated_control']['available_record_mismatches']}/"
            f"{report['historical_repeated_control']['units']} available records"
        )
        print(
            "Deterministic preflight: "
            f"{report['deterministic_preflight']['status']}, "
            f"{report['deterministic_preflight']['trace_mismatch_units']} trace mismatches"
        )
        print(
            "Timed-search stress: "
            f"{report['timed_search_stress']['trace_disagreement_clusters']}/"
            f"{report['timed_search_stress']['clusters']} disagreement clusters"
        )
        print(
            "Factorial: "
            f"{report['factorial']['status']}, {report['factorial']['units']} paired units"
        )
        print(
            "Admission protocol: "
            f"{report['admission_protocol']['formalization_status']}, "
            f"{report['admission_protocol']['evidence_gates']} gates, "
            f"{report['admission_protocol']['claim_classes']} claim classes; "
            "worked example -> "
            f"{report['admission_protocol']['worked_example_claim_class']}; "
            f"trust={report['admission_protocol']['worked_example_trust_anchor']}; "
            "external scientific provenance verified="
            f"{str(report['admission_protocol']['worked_example_external_scientific_provenance_verified']).lower()}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
