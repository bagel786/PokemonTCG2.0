#!/usr/bin/env python3
"""Validate and aggregate five independent APS desk-review simulations.

The script judges only completeness and decision consistency.  It never turns a
negative reviewer verdict into a pass.  A PASS status means the review gate was
computed correctly; ``desk_gate`` records whether the submission gate itself
passed.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
FINAL = SCRIPT.parents[1]
REVIEWS = FINAL / "reviews"
OUTPUT = FINAL / "DESK_REVIEW_SIMULATION.json"
EXPECTED = {
    "A": "APS staff editor",
    "B": "stochastic simulation expert",
    "C": "software testing and reproducibility expert",
    "D": "agent evaluation expert",
    "E": "hostile integrity and general-reader reviewer",
}
VERDICTS = {"SEND_TO_REVIEW", "BORDERLINE", "DESK_REJECT"}
DECISIONS = {
    "READY_FOR_HUMAN_SIGNOFF_PROTOCOL_ARTICLE",
    "PIVOT_TO_DATA_CODE_ARTICLE",
    "NOT_READY_DO_NOT_SUBMIT",
}


class ReviewError(ValueError):
    pass


def reject_constant(value: str) -> None:
    raise ReviewError(f"non-finite JSON constant: {value}")


def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReviewError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicates,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReviewError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReviewError(f"top-level object required: {path}")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReviewError(message)


def validate_review(reviewer_id: str, value: dict[str, Any]) -> dict[str, Any]:
    required = {
        "reviewer_id", "reviewer_role", "verdict", "confidence",
        "fatal_issues", "major_issues", "minor_issues",
        "exact_manuscript_locations", "required_fixes", "general_reader_answers",
        "reviewed_artifact_hashes", "independence_attestation",
    }
    require(set(value) == required, f"reviewer {reviewer_id}: exact schema required")
    require(value["reviewer_id"] == reviewer_id, f"reviewer {reviewer_id}: identity mismatch")
    require(value["reviewer_role"] == EXPECTED[reviewer_id], f"reviewer {reviewer_id}: role mismatch")
    require(value["verdict"] in VERDICTS, f"reviewer {reviewer_id}: invalid verdict")
    confidence = value["confidence"]
    require(
        isinstance(confidence, (int, float)) and not isinstance(confidence, bool)
        and math.isfinite(float(confidence)) and 0 <= float(confidence) <= 1,
        f"reviewer {reviewer_id}: confidence must be finite in [0,1]",
    )
    for field in ("fatal_issues", "major_issues", "minor_issues", "exact_manuscript_locations", "required_fixes"):
        items = value[field]
        require(isinstance(items, list), f"reviewer {reviewer_id}: {field} must be a list")
        require(all(isinstance(item, str) and item.strip() for item in items), f"reviewer {reviewer_id}: invalid {field}")
    answers = value["general_reader_answers"]
    expected_questions = {
        "problem", "protocol", "contribution", "effectiveness_result", "limitation",
    }
    require(isinstance(answers, dict) and set(answers) == expected_questions, f"reviewer {reviewer_id}: general-reader answers incomplete")
    require(all(isinstance(item, str) and item.strip() for item in answers.values()), f"reviewer {reviewer_id}: blank general-reader answer")
    hashes = value["reviewed_artifact_hashes"]
    current = {
        "main_tex": sha256(FINAL / "main.tex"),
        "main_pdf": sha256(FINAL / "main.pdf"),
        "novelty_audit": sha256(FINAL / "NOVELTY_AUDIT.md"),
        "release_manifest": sha256(FINAL / "release/MANIFEST.sha256"),
    }
    require(hashes == current, f"reviewer {reviewer_id}: review is stale for final artifacts")
    attestation = value["independence_attestation"]
    require(
        isinstance(attestation, str)
        and "without access to another reviewer" in attestation.lower(),
        f"reviewer {reviewer_id}: independence attestation missing",
    )
    return value


def rights_unresolved() -> bool:
    inventory = (FINAL / "RELEASE_COMPONENT_INVENTORY.csv").read_text(encoding="utf-8").lower()
    license_text = (FINAL / "release/LICENSE").read_text(encoding="utf-8").lower()
    return "unresolved" in inventory or "no license granted" in license_text


def main() -> int:
    reviews: list[dict[str, Any]] = []
    for reviewer_id in EXPECTED:
        reviews.append(validate_review(reviewer_id, load(REVIEWS / f"reviewer_{reviewer_id.lower()}.json")))

    send_count = sum(item["verdict"] == "SEND_TO_REVIEW" for item in reviews)
    aps_editor_send = reviews[0]["verdict"] == "SEND_TO_REVIEW"
    fatal_reviews = [
        {"reviewer_id": item["reviewer_id"], "issues": item["fatal_issues"]}
        for item in reviews if item["fatal_issues"]
    ]
    unresolved_rights = rights_unresolved()
    desk_pass = send_count >= 4 and aps_editor_send and not fatal_reviews and not unresolved_rights
    decision = (
        "READY_FOR_HUMAN_SIGNOFF_PROTOCOL_ARTICLE"
        if desk_pass else "NOT_READY_DO_NOT_SUBMIT"
    )
    require(decision in DECISIONS, "internal decision vocabulary error")
    report = {
        "schema_version": "aps-independent-desk-review-v1",
        "status": "PASS",
        "review_count": len(reviews),
        "reviewers_were_independent": True,
        "verdict_counts": {
            verdict: sum(item["verdict"] == verdict for item in reviews)
            for verdict in sorted(VERDICTS)
        },
        "aps_staff_editor_verdict": reviews[0]["verdict"],
        "fatal_review_findings": fatal_reviews,
        "rights_unresolved": unresolved_rights,
        "desk_gate": "PASS" if desk_pass else "FAIL",
        "gate_requirements": {
            "at_least_four_send_to_review": send_count >= 4,
            "aps_staff_editor_send_to_review": aps_editor_send,
            "no_fatal_issue": not fatal_reviews,
            "release_rights_resolved": not unresolved_rights,
        },
        "final_decision": decision,
        "review_files": {
            item["reviewer_id"]: {
                "path": f"reviews/reviewer_{item['reviewer_id'].lower()}.json",
                "sha256": sha256(REVIEWS / f"reviewer_{item['reviewer_id'].lower()}.json"),
                "verdict": item["verdict"],
                "confidence": item["confidence"],
            }
            for item in reviews
        },
    }
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "desk_gate": report["desk_gate"], "final_decision": decision}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
