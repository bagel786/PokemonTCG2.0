"""Fail-closed tests for the V2 closeout desk-review aggregate."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest


FINAL = Path(__file__).resolve().parents[1]
SCRIPT = FINAL / "scripts/aggregate_desk_reviews.py"


@pytest.fixture(scope="module")
def review_module():
    spec = importlib.util.spec_from_file_location("aggregate_desk_reviews", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def current_reviews(review_module):
    return [
        review_module.validate_review(
            reviewer_id,
            review_module.load(FINAL / f"reviews_v2/reviewer_{reviewer_id.lower()}.json"),
        )
        for reviewer_id in review_module.EXPECTED_ROLES
    ]


def test_current_reviews_produce_separated_fail_closed_gates(review_module) -> None:
    report = review_module.build_report(current_reviews(review_module))
    assert report["status"] == "PASS"
    assert report["review_count"] == 5
    assert report["verdict_counts_scientific"] == {
        "BORDERLINE": 1,
        "DESK_REJECT": 0,
        "SEND_TO_REVIEW": 4,
    }
    assert report["SCIENTIFIC_DESK_GATE"]["result"] == "PASS_SCIENTIFICALLY_SEND_TO_REVIEW"
    assert report["SUBMISSION_COMPLETENESS_GATE"]["result"] == "BLOCKED_PENDING_HUMAN_ACTIONS"
    assert (
        report["combined_decision"]["overall_submission_status"]
        == "NOT_READY_DO_NOT_SUBMIT_UNTIL_HUMAN_CLOSEOUT_COMPLETE"
    )
    assert set(report["review_files"]) == set("ABCDE")
    assert set(report["closeout_artifact_hashes"]) == {
        "main_tex", "main_pdf", "novelty_audit_v2", "release_manifest",
    }


@pytest.mark.parametrize(
    ("reviewer_id", "field", "replacement"),
    (
        ("A", "blind", False),
        ("A", "scope_only_borderline", False),
        ("B", "desk_decision_scientific", "BORDERLINE"),
        ("C", "role", "generic reviewer"),
        ("D", "completeness_findings_separated", []),
        ("E", "scientific_assessment", {}),
    ),
)
def test_review_schema_and_decisions_fail_closed(
    review_module,
    reviewer_id: str,
    field: str,
    replacement,
) -> None:
    value = review_module.load(FINAL / f"reviews_v2/reviewer_{reviewer_id.lower()}.json")
    mutated = copy.deepcopy(value)
    mutated[field] = replacement
    with pytest.raises(review_module.ReviewError):
        review_module.validate_review(reviewer_id, mutated)


def test_aggregate_rejects_missing_or_reordered_review(review_module) -> None:
    reviews = current_reviews(review_module)
    with pytest.raises(review_module.ReviewError):
        review_module.build_report(reviews[:-1])
    with pytest.raises(review_module.ReviewError):
        review_module.build_report(list(reversed(reviews)))
