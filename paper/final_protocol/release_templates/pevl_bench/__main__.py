"""Command-line entry point for the standalone review package."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from . import synthetic


PACKAGE = Path(__file__).resolve().parent
RELEASE = PACKAGE.parent
DEFAULT_RESULTS = PACKAGE / "results"


def _load_json(relative: str) -> dict:
    path = RELEASE / relative
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {relative}")
    return value


def _report() -> dict:
    preflight = _load_json("data/processed/preflight_summary.json")
    stress = _load_json("data/processed/timed_search_stress.json")
    factorial = _load_json("data/processed/factorial_summary.json")
    historical = _load_json("data/processed/historical_summary.json")
    failures = synthetic.verify_outputs(DEFAULT_RESULTS)
    if failures:
        raise ValueError("synthetic fixture verification failed: " + "; ".join(failures))
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
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate, verify, or summarize trace-validation review artifacts."
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
    report = subparsers.add_parser("report")
    report.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "generate":
        synthetic.write_outputs(args.output_dir)
        failures = synthetic.verify_outputs(args.output_dir)
        if failures:
            for failure in failures:
                print(f"FAIL: {failure}", file=sys.stderr)
            return 1
        print(f"generated and verified {args.output_dir}")
        return 0
    if args.command == "verify":
        failures = synthetic.verify_outputs(args.output_dir)
        if failures:
            for failure in failures:
                print(f"FAIL: {failure}", file=sys.stderr)
            return 1
        print(f"verified {args.output_dir}")
        return 0
    report = _report()
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
