"""Canonical shared constants: producer and consumer MUST import from here.

Repairs T22 (string-mismatch predicate bug) and vocabulary drift.
"""
from __future__ import annotations

DECISIONS = ("ADMIT", "DOWNGRADE", "SUPPRESS", "FAIL_CLOSED", "ABSTAIN_NOT_EVALUATED")
# Five DECISION branches; CRN *benefit* is a separate measurement output, never a
# decision cell (no construction-level ground truth exists for 'benefit').
BRANCHES = ("BRANCH_A", "BRANCH_B", "BRANCH_C", "BRANCH_D", "BRANCH_E")
GT_LEVELS = ("VALID", "DOWNGRADE", "INVALID", "NOT_APPLICABLE")
SCORE_CLASSES = (
    "CORRECT", "MISSED_FAILURE", "CAVEAT_ONLY_MISS", "FALSE_SUPPRESSION_SOFT",
    "FALSE_SUPPRESSION_HARD", "DETECTED_WITH_CAVEAT", "NOT_APPLICABLE", "ABSTAINED",
)
ANALYSIS_UNITS = ("seed_condition", "hand_cluster", "decision")
MODEL_FAMILIES = ("none", "hierarchical", "cluster_robust", "defended_joint_stochastic_model")
DESIGN_JUSTIFICATIONS = (
    "probability_sampling_of_unit", "randomized_matched_assignment",
    "repeated_measures", "hierarchical_model_declared",
    "defended_joint_stochastic_model", "independent_arms",
)
COUPLING_TYPES = ("stateful_sync", "event_keyed_policy_preserving",
                  "event_keyed_policy_blind", "independent_seeds", "none")

# Canonical enum values — exact equality matching everywhere:
UNIT_SEED_CONDITION = ANALYSIS_UNITS[0]
UNIT_DECISION = ANALYSIS_UNITS[2]
MF_HIERARCHICAL = MODEL_FAMILIES[1]
DJ_DESIGN = DESIGN_JUSTIFICATIONS[4]
RM_DESIGN = DESIGN_JUSTIFICATIONS[2]
RMA_DESIGN = DESIGN_JUSTIFICATIONS[3]

BRANCH_TO_GT_DIM = {
    "BRANCH_A": "descriptive",
    "BRANCH_B": "paired_inference",
    "BRANCH_C": "replay",
    "BRANCH_D": "crn",
    "BRANCH_E": "event_alignment",
}
GT_DIMS = ("descriptive", "paired_inference", "replay", "crn", "event_alignment")
