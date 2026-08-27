"""Abstention-aware scoring (frozen semantics).

GT VALID:      ADMIT->CORRECT; DOWNGRADE->FALSE_SUPPRESSION_SOFT;
               SUPPRESS/FAIL_CLOSED->FALSE_SUPPRESSION_HARD; ABSTAIN->ABSTAINED
GT DOWNGRADE:  DOWNGRADE->CORRECT; ADMIT->MISSED_CAVEAT(caveat-blind);
               SUPPRESS/FAIL_CLOSED->FALSE_SUPPRESSION_HARD; ABSTAIN->ABSTAINED
GT INVALID:    SUPPRESS/FAIL_CLOSED->CORRECT(strict detection);
               DOWNGRADE->DETECTED_WITH_CAVEAT(non-strict);
               ADMIT->MISSED_FAILURE; ABSTAIN->ABSTAINED
GT NOT_APPLICABLE -> NOT_APPLICABLE (excluded from every denominator).
"""
from __future__ import annotations

from .constants import DECISIONS

_STRICT_DETECT = {"SUPPRESS", "FAIL_CLOSED"}
_ABSTAIN = "ABSTAIN_NOT_EVALUATED"


def score_cell(decision: str, gt: str) -> str:
    if decision not in DECISIONS:
        raise ValueError(f"unknown decision {decision!r}")
    if gt == "NOT_APPLICABLE":
        return "NOT_APPLICABLE"
    if decision == _ABSTAIN:
        return "ABSTAINED"
    if gt == "VALID":
        if decision == "ADMIT":
            return "CORRECT"
        if decision == "DOWNGRADE":
            return "FALSE_SUPPRESSION_SOFT"
        return "FALSE_SUPPRESSION_HARD"
    if gt == "DOWNGRADE":
        if decision == "DOWNGRADE":
            return "CORRECT"
        if decision == "ADMIT":
            return "CAVEAT_ONLY_MISS"
        return "FALSE_SUPPRESSION_HARD"
    if gt == "INVALID":
        if decision in _STRICT_DETECT:
            return "CORRECT"
        if decision == "DOWNGRADE":
            return "DETECTED_WITH_CAVEAT"
        return "MISSED_FAILURE"
    raise ValueError(gt)


def is_detected_strict(cls: str, gt: str) -> bool:
    """Strict detection for M1: GT=INVALID with SUPPRESS/FAIL_CLOSED."""
    return gt == "INVALID" and cls == "CORRECT"


def is_false_suppression(cls: str) -> bool:
    return cls.startswith("FALSE_SUPPRESSION")
