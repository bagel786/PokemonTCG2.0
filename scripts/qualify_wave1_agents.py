#!/usr/bin/env python3
"""Apply correctness-only promotion gates to the two Wave-1 packages."""

from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts" / "wave1_push"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def smoke(name: str, expected_order: str) -> tuple[dict, list[str]]:
    row = read_json(ARTIFACTS / "smoke" / f"{name}.json")
    failures = []
    if int(row.get("games", 0)) != 10:
        failures.append(f"{name}:games")
    if row.get("actual_order") != expected_order or not row.get("actual_order_accounting_complete"):
        failures.append(f"{name}:order")
    if row.get("physical_seats") != {"0": {"games": 5, "wins": row["physical_seats"]["0"]["wins"]}, "1": {"games": 5, "wins": row["physical_seats"]["1"]["wins"]}}:
        failures.append(f"{name}:physical_seats")
    if int(row.get("hero_policy_errors", 0)) or int(row.get("opponent_policy_errors", 0)):
        failures.append(f"{name}:policy_errors")
    return row, failures


def main() -> int:
    build = read_json(ARTIFACTS / "build_manifest.json")
    failures = []
    packages = {row["mode"]: row for row in build["packages"]}
    if set(packages) != {"fan", "tempo"}:
        failures.append("package_modes")
    for mode, package in packages.items():
        archive = Path(package["archive"])
        if not archive.exists() or sha256(archive) != package["archive_sha256"]:
            failures.append(f"{mode}:archive_hash")
        if not package.get("deterministic_double_build") or not package.get("sterile_validation", {}).get("passed"):
            failures.append(f"{mode}:package_validation")

    base = Counter({int(key): int(value) for key, value in packages["tempo"]["base_deck_multiset"].items()})
    tempo = Counter({int(key): int(value) for key, value in packages["tempo"]["deck_multiset"].items()})
    fan = Counter({int(key): int(value) for key, value in packages["fan"]["deck_multiset"].items()})
    approved_fan = Counter(base)
    approved_fan[1137] -= 1
    approved_fan[1231] -= 1
    approved_fan[1161] += 2
    approved_fan += Counter()
    if tempo != base:
        failures.append("tempo:deck_not_exact")
    if fan != approved_fan:
        failures.append("fan:deck_not_approved_swap")

    smoke_rows = {}
    for mode in ("fan", "tempo"):
        for order in ("first", "second"):
            name = f"{mode}_{order}"
            row, found = smoke(name, order)
            smoke_rows[name] = {
                "wins": row["wins"], "games": row["games"], "win_rate": row["win_rate"],
                "physical_seats": row["physical_seats"], "hero_policy_errors": row["hero_policy_errors"],
            }
            failures.extend(found)

    audits = {}
    for mode in ("fan", "tempo"):
        first = read_json(ARTIFACTS / "audit" / f"{mode}_pass1.json")
        second = read_json(ARTIFACTS / "audit" / f"{mode}_pass2.json")
        audits[mode] = first
        if not first.get("passed") or not second.get("passed"):
            failures.append(f"{mode}:behavior_audit")
        if first.get("decision_digest") != second.get("decision_digest"):
            failures.append(f"{mode}:nondeterministic_replay")
        if int(first.get("unclassified_changes", -1)) != 0:
            failures.append(f"{mode}:unclassified_spill")

    tests = ET.parse(ARTIFACTS / "test-results.xml").getroot()
    suites = [tests] if tests.tag == "testsuite" else list(tests.findall("testsuite"))
    test_count = sum(int(suite.attrib.get("tests", 0)) for suite in suites)
    test_failures = sum(
        int(suite.attrib.get("failures", 0)) + int(suite.attrib.get("errors", 0))
        for suite in suites
    )
    if test_count <= 0:
        failures.append("unit_tests_missing")
    if test_failures:
        failures.append("unit_tests")

    result = {
        "classification": "QUALIFIED_FOR_LIVE_LADDER" if not failures else "REJECTED",
        "upload_allowed": not failures,
        "hard_gate_failures": failures,
        "benchmark_policy": "correctness_and_catastrophic_smoke_only",
        "outcome_smoke_is_diagnostic": True,
        "packages": packages,
        "smoke": smoke_rows,
        "behavior_audits": audits,
        "unit_tests": {"tests": test_count, "failures": test_failures},
        "upload_order": ["fan", "tempo"],
    }
    target = ARTIFACTS / "qualification_manifest.json"
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
