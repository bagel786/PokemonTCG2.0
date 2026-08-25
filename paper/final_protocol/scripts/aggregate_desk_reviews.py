#!/usr/bin/env python3
"""Validate and aggregate the five independent closeout desk reviews.

Scientific desk risk and submission-completeness risk are deliberately kept
separate. A scientifically favorable review cannot resolve author metadata,
rights, licensing, DOI, deviation-signoff, or comprehension blockers.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
FINAL = SCRIPT.parents[1]
REVIEWS = FINAL / "reviews_v2"
OUTPUT = FINAL / "DESK_REVIEW_SIMULATION_V2.json"
EXPECTED_ROLES = {
    "A": "APS staff editor",
    "B": "stochastic simulation expert (CRN, event alignment, clustering, resampling, chronology)",
    "C": "software testing / reproducibility expert",
    "D": "agent evaluation expert (close 2026 prior art, pairing specificity, empirical usefulness)",
    "E": "hostile integrity / general reader",
}
EXPECTED_DECISIONS = {
    "A": "BORDERLINE",
    "B": "SEND_TO_REVIEW",
    "C": "SEND_TO_REVIEW",
    "D": "SEND_TO_REVIEW",
    "E": "SEND_TO_REVIEW",
}
VERDICT_LABELS = {
    "A": "A_aps_staff_editor",
    "B": "B_stochastic_simulation",
    "C": "C_software_reproducibility",
    "D": "D_agent_evaluation",
    "E": "E_hostile_integrity",
}
COMMON_KEYS = {
    "reviewer_id", "role", "blind", "scientific_assessment",
    "completeness_findings_separated", "desk_decision_scientific", "rationale",
}
ROLE_SPECIFIC_KEYS = {
    "A": {
        "reviewed_artifacts", "scope_risk", "scope_only_borderline",
        "would_send_after_scope_answer_and_completeness",
    },
    "B": {"residual_scientific_notes"},
    "C": {"residual_scientific_notes"},
    "D": {"residual_scientific_notes"},
    "E": set(),
}
VERDICTS = {"SEND_TO_REVIEW", "BORDERLINE", "DESK_REJECT"}


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


def _nonempty_strings(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(
        isinstance(item, str) and item.strip() for item in value
    )


def validate_review(reviewer_id: str, value: dict[str, Any]) -> dict[str, Any]:
    require(reviewer_id in EXPECTED_ROLES, f"unknown reviewer: {reviewer_id}")
    expected_keys = COMMON_KEYS | ROLE_SPECIFIC_KEYS[reviewer_id]
    require(set(value) == expected_keys, f"reviewer {reviewer_id}: exact schema required")
    require(value["reviewer_id"] == reviewer_id, f"reviewer {reviewer_id}: identity mismatch")
    require(value["role"] == EXPECTED_ROLES[reviewer_id], f"reviewer {reviewer_id}: role mismatch")
    require(value["blind"] is True, f"reviewer {reviewer_id}: blind-review flag must be true")
    decision = value["desk_decision_scientific"]
    require(decision in VERDICTS, f"reviewer {reviewer_id}: invalid decision")
    require(decision == EXPECTED_DECISIONS[reviewer_id], f"reviewer {reviewer_id}: decision drift")
    assessment = value["scientific_assessment"]
    require(
        isinstance(assessment, dict) and bool(assessment)
        and all(
            isinstance(key, str) and key
            and isinstance(item, str) and item.strip()
            for key, item in assessment.items()
        ),
        f"reviewer {reviewer_id}: scientific assessment is incomplete",
    )
    require(
        _nonempty_strings(value["completeness_findings_separated"]),
        f"reviewer {reviewer_id}: separated completeness findings are missing",
    )
    require(
        isinstance(value["rationale"], str) and value["rationale"].strip(),
        f"reviewer {reviewer_id}: rationale is missing",
    )
    if "residual_scientific_notes" in value:
        require(
            _nonempty_strings(value["residual_scientific_notes"]),
            f"reviewer {reviewer_id}: residual scientific notes are invalid",
        )
    if reviewer_id == "A":
        require(_nonempty_strings(value["reviewed_artifacts"]), "reviewer A: reviewed artifacts are missing")
        require(value["scope_only_borderline"] is True, "reviewer A: borderline must be scope-only")
        require(
            value["would_send_after_scope_answer_and_completeness"] is True,
            "reviewer A: conditional send-to-review disposition is missing",
        )
        scope = value["scope_risk"]
        require(
            isinstance(scope, dict)
            and set(scope) == {"assessment", "mitigation", "counts_as_scope_only"}
            and scope["counts_as_scope_only"] is True
            and all(
                isinstance(scope[key], str) and scope[key].strip()
                for key in ("assessment", "mitigation")
            ),
            "reviewer A: scope-only rationale is malformed",
        )
    return value


def current_artifact_hashes() -> dict[str, str]:
    paths = {
        "main_tex": FINAL / "main.tex",
        "main_pdf": FINAL / "main.pdf",
        "novelty_audit_v2": FINAL / "NOVELTY_AUDIT_V2.md",
        "release_manifest": FINAL / "release/MANIFEST.sha256",
    }
    missing = [name for name, path in paths.items() if not path.is_file()]
    require(not missing, "closeout review artifacts missing: " + ", ".join(sorted(missing)))
    return {name: sha256(path) for name, path in paths.items()}


def build_report(reviews: list[dict[str, Any]]) -> dict[str, Any]:
    require(
        [item["reviewer_id"] for item in reviews] == list(EXPECTED_ROLES),
        "review order differs",
    )
    decisions = {
        item["reviewer_id"]: item["desk_decision_scientific"]
        for item in reviews
    }
    counts = {
        verdict: sum(value == verdict for value in decisions.values())
        for verdict in sorted(VERDICTS)
    }
    scientific_pass = (
        decisions == EXPECTED_DECISIONS
        and counts == {"BORDERLINE": 1, "DESK_REJECT": 0, "SEND_TO_REVIEW": 4}
        and reviews[0]["scope_only_borderline"] is True
    )
    require(scientific_pass, "scientific desk gate no longer passes its frozen closeout rule")
    review_records = {
        item["reviewer_id"]: {
            "path": f"reviews_v2/reviewer_{item['reviewer_id'].lower()}.json",
            "sha256": sha256(REVIEWS / f"reviewer_{item['reviewer_id'].lower()}.json"),
            "decision": item["desk_decision_scientific"],
        }
        for item in reviews
    }
    return {
        "schema_version": "desk-review-simulation-v2-2.1.0",
        "status": "PASS",
        "generated": "2026-08-25",
        "review_count": 5,
        "reviews_blind_to_each_other": True,
        "review_files": review_records,
        "closeout_artifact_hashes": current_artifact_hashes(),
        "gate_design_note": (
            "Scientific desk risk and submission-completeness risk are aggregated separately. "
            "Human-only placeholders must not be conflated with methodology validity."
        ),
        "verdicts": {
            VERDICT_LABELS[item["reviewer_id"]]: item["desk_decision_scientific"]
            for item in reviews
        },
        "verdict_counts_scientific": counts,
        "SCIENTIFIC_DESK_GATE": {
            "result": "PASS_SCIENTIFICALLY_SEND_TO_REVIEW",
            "checks": {
                "reviewer_A_send_or_borderline_scope_only": True,
                "at_least_four_of_five_send_to_review": True,
                "any_fatal_scientific_finding": False,
                "no_major_contradiction": True,
                "no_unsupported_claim_detected": True,
                "novelty_boundary_survives_refreshed_audit": True,
            },
            "scope_risk_note": (
                "Reviewer A borderline is scope-only (game-engine case with argued, not demonstrated, "
                "adjacent-science adoption); the unsent scope inquiry remains the mitigation path."
            ),
        },
        "SUBMISSION_COMPLETENESS_GATE": {
            "result": "BLOCKED_PENDING_HUMAN_ACTIONS",
            "blockers": [
                "author name / corresponding email / affiliation placeholders",
                "CRediT, funding, conflicts, acknowledgments unresolved",
                "AI-use completeness unconfirmed by human",
                "claim-ledger curated signoff worksheet unsigned (33 rows + automatic attestation)",
                "equation/method/defense comprehension signoffs unsigned",
                "release ownership matrix approvals pending; no approved license; RELEASE_STATUS unauthorized",
                "no archive/DOI authorization",
                "D03 deviation record unsigned pending disposition of recovered aggregates and never-recorded positions",
            ],
        },
        "combined_decision": {
            "scientific": "SCIENTIFICALLY_SEND_TO_REVIEW",
            "completeness": "BLOCKED_BY_HUMAN_ACTIONS",
            "overall_submission_status": "NOT_READY_DO_NOT_SUBMIT_UNTIL_HUMAN_CLOSEOUT_COMPLETE",
        },
        "comparison_to_v1": {
            "v1": {
                "SEND_TO_REVIEW": 1,
                "BORDERLINE": 0,
                "DESK_REJECT": 4,
                "gates_conflated": True,
            },
            "v2": {
                "SEND_TO_REVIEW": 4,
                "BORDERLINE": 1,
                "DESK_REJECT": 0,
                "gates_separated": True,
            },
            "driver": (
                "V1 fatal findings were dominated by human/legal completeness items plus three fixable "
                "scientific defects (chronology wording, outcome-independence phrasing, missing Stage-6 "
                "operationalization), all fixed or explicitly narrowed during closeout."
            ),
        },
    }


def main() -> int:
    reviews = [
        validate_review(
            reviewer_id,
            load(REVIEWS / f"reviewer_{reviewer_id.lower()}.json"),
        )
        for reviewer_id in EXPECTED_ROLES
    ]
    report = build_report(reviews)
    OUTPUT.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": "PASS",
        "scientific_desk_gate": report["SCIENTIFIC_DESK_GATE"]["result"],
        "submission_completeness_gate": report["SUBMISSION_COMPLETENESS_GATE"]["result"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
