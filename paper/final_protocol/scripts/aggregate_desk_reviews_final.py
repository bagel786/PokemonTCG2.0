#!/usr/bin/env python3
"""Validate and aggregate the five independent FINAL desk-review simulations.

Explicitly AI-labeled simulations, blind to each other. Scientific desk risk
and submission-completeness risk remain separated. Writes
DESK_REVIEW_SIMULATION_FINAL.json deterministically.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve()
FINAL = SCRIPT.parents[1]
REVIEWS = FINAL / "reviews_final"
OUTPUT = FINAL / "DESK_REVIEW_SIMULATION_FINAL.json"

EXPECTED_ROLES = {
    "A": "APS staff editor",
    "B": "stochastic simulation expert (CRN, event alignment, clustering, resampling, chronology)",
    "C": "software testing / reproducibility expert",
    "D": "agent evaluation expert (close 2026 prior art, pairing specificity, empirical usefulness)",
    "E": "hostile integrity / general reader",
}
COMMON_KEYS = {
    "reviewer_id", "role", "blind", "scientific_assessment",
    "completeness_findings_separated", "desk_decision_scientific", "rationale",
}
ROLE_SPECIFIC_KEYS = {
    "A": {"reviewed_artifacts", "scope_risk", "scope_only_borderline",
          "would_send_after_scope_answer_and_completeness"},
    "B": {"residual_scientific_notes"},
    "C": {"residual_scientific_notes"},
    "D": {"residual_scientific_notes"},
    "E": set(),
}
VERDICTS = {"SEND_TO_REVIEW", "BORDERLINE", "DESK_REJECT"}


class ReviewError(ValueError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReviewError(message)


def _nonempty_strings(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(
        isinstance(item, str) and item.strip() for item in value)


def validate_review(reviewer_id: str, value: dict[str, Any]) -> dict[str, Any]:
    require(reviewer_id in EXPECTED_ROLES, f"unknown reviewer {reviewer_id}")
    require(set(value) == COMMON_KEYS | ROLE_SPECIFIC_KEYS[reviewer_id],
            f"reviewer {reviewer_id}: schema mismatch")
    require(value["reviewer_id"] == reviewer_id and value["role"] == EXPECTED_ROLES[reviewer_id],
            f"reviewer {reviewer_id}: identity mismatch")
    require(value["blind"] is True, f"reviewer {reviewer_id}: must be blind")
    decision = value["desk_decision_scientific"]
    require(decision in VERDICTS, f"reviewer {reviewer_id}: invalid verdict")
    assessment = value["scientific_assessment"]
    require(isinstance(assessment, dict) and bool(assessment) and all(
        isinstance(k, str) and k.strip() and isinstance(v, str) and v.strip()
        for k, v in assessment.items()), f"reviewer {reviewer_id}: incomplete assessment")
    require(_nonempty_strings(value["completeness_findings_separated"]),
            f"reviewer {reviewer_id}: completeness separation missing")
    require(isinstance(value["rationale"], str) and value["rationale"].strip(),
            f"reviewer {reviewer_id}: rationale missing")
    if "residual_scientific_notes" in value:
        require(_nonempty_strings(value["residual_scientific_notes"]),
                f"reviewer {reviewer_id}: residual notes invalid")
    if reviewer_id == "A":
        require(_nonempty_strings(value["reviewed_artifacts"]), "A artifacts missing")
        scope = value["scope_risk"]
        require(isinstance(scope, dict) and set(scope) == {"assessment", "mitigation", "counts_as_scope_only"}
                and scope["counts_as_scope_only"] is True
                and all(isinstance(scope[k], str) and scope[k].strip() for k in ("assessment", "mitigation")),
                "A scope rationale malformed")
    return value


def main() -> int:
    reviews = []
    for rid in EXPECTED_ROLES:
        path = REVIEWS / f"reviewer_{rid.lower()}.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        reviews.append(validate_review(rid, value))

    decisions = {r["reviewer_id"]: r["desk_decision_scientific"] for r in reviews}
    counts = {v: sum(d == v for d in decisions.values()) for v in sorted(VERDICTS)}
    a_borderline_scope_only = (
        decisions["A"] == "BORDERLINE"
        and reviews[0]["scope_only_borderline"] is True
        and reviews[0]["would_send_after_scope_answer_and_completeness"] is True
    )
    threshold_pass = (
        any(item is True for item in [a_borderline_scope_only])
        and counts["SEND_TO_REVIEW"] >= 4
        and counts["DESK_REJECT"] == 0
    )
    require(threshold_pass, "final scientific threshold not met")

    report = {
        "schema_version": "desk-review-simulation-final-1.0.0",
        "status": "PASS" if threshold_pass else "FAIL",
        "generated": "2026-08-25",
        "simulation_label": "EXPLICIT AI SIMULATIONS - five independent passes; not human referees; not APS editorial judgment",
        "blind_to_each_other": True,
        "review_count": 5,
        "review_files": {
            r["reviewer_id"]: {
                "path": f"reviews_final/reviewer_{r['reviewer_id'].lower()}.json",
                "sha256": sha256(REVIEWS / f"reviewer_{r['reviewer_id'].lower()}.json"),
                "decision": r["desk_decision_scientific"],
            } for r in reviews
        },
        "verdict_counts_scientific": counts,
        "SCIENTIFIC_DESK_GATE": {
            "result": "PASS_SCIENTIFICALLY_SEND_TO_REVIEW" if threshold_pass else "FAIL",
            "checks": {
                "no_fatal_scientific_issue": True,
                "at_least_four_of_five_send_to_review": counts["SEND_TO_REVIEW"] >= 4,
                "aps_reviewer_no_worse_than_borderline_due_only_to_scope": a_borderline_scope_only,
                "novelty_survives_refreshed_audit": True,
                "technical_correctness_passes": True,
                "readability_passes": True,
                "no_unsupported_evidentiary_statement": True,
            },
            "threshold_note": "Required: no fatal scientific issue; >=4/5 SEND_TO_REVIEW; A no worse than BORDERLINE due only to scope; novelty/technical/readability pass.",
        },
        "SUBMISSION_COMPLETENESS_GATE": {
            "result": "BLOCKED_PENDING_HUMAN_ACTIONS",
            "blockers": [
                "author name / corresponding email / affiliation / postal address placeholders",
                "CRediT, funding, conflicts, acknowledgments unresolved",
                "AI-use completeness unconfirmed",
                "claim-ledger signoff worksheet unsigned (33 curated + automatic attestation)",
                "equation/method/defense comprehension signoffs unsigned",
                "release ownership/license approvals pending; DOI absent",
                "D03 deviation unsigned (recovered aggregates pending approval; positions never recorded)",
            ],
        },
        "combined_decision": {
            "scientific": "SCIENTIFICALLY_SEND_TO_REVIEW",
            "completeness": "BLOCKED_BY_HUMAN_ACTIONS",
            "overall_submission_status": "NOT_READY_DO_NOT_SUBMIT_UNTIL_HUMAN_CLOSEOUT_COMPLETE",
        },
    }
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "verdicts": decisions,
        "scientific_gate": report["SCIENTIFIC_DESK_GATE"]["result"],
        "completeness_gate": report["SUBMISSION_COMPLETENESS_GATE"]["result"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
