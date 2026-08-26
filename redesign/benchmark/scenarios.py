"""Scenarios S0-S10 with ground-truth labels known by construction.

Each scenario specifies:
  mechanics: how the harness produces/analyzes paired runs
  gt: ground-truth labels for the six claim dimensions
  gt_framework: expected CSVF decision per branch (for EXPECTED_DECISION_TABLE)

Labels use: VALID, INVALID, DOWNGRADE (valid only under weaker wording),
NOT_APPLICABLE.
"""

SCENARIOS = {
    "S0": {
        "name": "clean control",
        "invalid_claim_expected": False,
        "mechanics": {"stateful_sync": True},
        "gt": {
            "descriptive": "VALID",
            "paired_inference": "VALID",
            "replay": "VALID",
            "crn": "VALID",
            "event_alignment": "NOT_APPLICABLE",
            "wording": "full_no_event_claims",
        },
        "expected": {"A": "ADMIT", "B": "ADMIT", "C": "ADMIT", "D": "ADMIT",
                     "E": "NOT_APPLICABLE"},
    },
    "S1": {
        "name": "seed namespace conversion (16-bit truncation)",
        "invalid_claim_expected": True,
        "mechanics": {"truncate_arm_b_seed_bits": 16},
        "gt": {
            "descriptive": "INVALID",
            "paired_inference": "DOWNGRADE",
            "replay": "VALID",
            "crn": "INVALID",
            "event_alignment": "INVALID",
            "wording": "randomized_design_only",
        },
        "expected": {"A": "SUPPRESS_OR_DOWNGRADE", "B": "DOWNGRADE",
                     "C": "ADMIT", "D": "SUPPRESS_OR_DOWNGRADE",
                     "E": "SUPPRESS_OR_DOWNGRADE"},
    },
    "S2": {
        "name": "stateful draw shift (one extra burn draw in arm B)",
        "invalid_claim_expected": True,
        "mechanics": {"extra_draw_arm_b": 1},
        "gt": {
            "descriptive": "VALID",
            "paired_inference": "DOWNGRADE",
            "replay": "VALID",
            "crn": "INVALID",
            "event_alignment": "INVALID",
            "wording": "statistical_pairing_no_coupling",
        },
        "expected": {"A": "ADMIT", "B": "DOWNGRADE", "C": "ADMIT",
                     "D": "SUPPRESS_OR_DOWNGRADE", "E": "SUPPRESS_OR_DOWNGRADE"},
    },
    "S3": {
        "name": "event-keyed repair",
        "invalid_claim_expected": False,
        "mechanics": {"event_keyed": True},
        "gt": {
            "descriptive": "VALID",
            "paired_inference": "VALID",
            "replay": "VALID",
            "crn": "VALID",
            "event_alignment": "VALID",
            "wording": "full",
        },
        "expected": {"A": "ADMIT", "B": "ADMIT", "C": "ADMIT", "D": "ADMIT",
                     "E": "ADMIT"},
    },
    "S4": {
        "name": "clock-bounded computation (wall-clock think budget)",
        "invalid_claim_expected": True,
        "mechanics": {"clock_budget_jitter": True},
        "gt": {
            "descriptive": "VALID",
            "paired_inference": "VALID",
            "replay": "INVALID",
            "crn": "VALID",
            "event_alignment": "INVALID",
            "wording": "no_replay_or_event_claims",
        },
        "expected": {"A": "ADMIT", "B": "ADMIT", "C": "SUPPRESS_OR_DOWNGRADE",
                     "D": "ADMIT", "E": "SUPPRESS_OR_DOWNGRADE"},
    },
    "S5": {
        "name": "process-global mutable state (worker reuse)",
        "invalid_claim_expected": True,
        "mechanics": {"worker_state_reuse": True},
        "gt": {
            "descriptive": "VALID",
            "paired_inference": "DOWNGRADE",
            "replay": "INVALID",
            "crn": "INVALID",
            "event_alignment": "INVALID",
            "wording": "hierarchical_residual_only",
        },
        "expected": {"A": "ADMIT", "B": "DOWNGRADE", "C": "SUPPRESS_OR_DOWNGRADE",
                     "D": "SUPPRESS_OR_DOWNGRADE", "E": "SUPPRESS_OR_DOWNGRADE"},
    },
    "S6": {
        "name": "queue/enqueue order dependence",
        "invalid_claim_expected": True,
        "mechanics": {"queue_order_seeding": True},
        "gt": {
            "descriptive": "VALID",
            "paired_inference": "DOWNGRADE",
            "replay": "INVALID",
            "crn": "INVALID",
            "event_alignment": "INVALID",
            "wording": "hierarchical_residual_only",
        },
        "expected": {"A": "ADMIT", "B": "DOWNGRADE", "C": "SUPPRESS_OR_DOWNGRADE",
                     "D": "SUPPRESS_OR_DOWNGRADE", "E": "SUPPRESS_OR_DOWNGRADE"},
    },
    "S7": {
        "name": "missing/dropped schedule rows before analysis",
        "invalid_claim_expected": True,
        "mechanics": {"drop_rows_mod": 3},
        "gt": {
            "descriptive": "INVALID",
            "paired_inference": "DOWNGRADE",
            "replay": "VALID",
            "crn": "VALID",
            "event_alignment": "NOT_APPLICABLE",
            "wording": "after_denominator_repair",
        },
        "expected": {"A": "SUPPRESS_OR_DOWNGRADE", "B": "DOWNGRADE",
                     "C": "ADMIT", "D": "ADMIT", "E": "NOT_APPLICABLE"},
    },
    "S8": {
        "name": "benign residual randomness, valid repeated-measures design",
        "invalid_claim_expected": False,
        "mechanics": {"clock_budget_jitter": True, "repeats_per_seed": 3},
        "gt": {
            "descriptive": "VALID",
            "paired_inference": "VALID",
            "replay": "INVALID",
            "crn": "VALID",
            "event_alignment": "INVALID",
            "wording": "no_replay_or_event_claims",
        },
        "expected": {"A": "ADMIT", "B": "ADMIT", "C": "SUPPRESS_OR_DOWNGRADE",
                     "D": "ADMIT", "E": "SUPPRESS_OR_DOWNGRADE"},
    },
    "S9": {
        "name": "pseudoreplication (decisions treated as independent replicates)",
        "invalid_claim_expected": True,
        "mechanics": {"pseudoreplication_analysis": True},
        "gt": {
            "descriptive": "VALID",
            "paired_inference": "INVALID",
            "replay": "VALID",
            "crn": "VALID",
            "event_alignment": "NOT_APPLICABLE",
            "wording": "cluster_aware_only",
        },
        "expected": {"A": "ADMIT", "B": "SUPPRESS_OR_DOWNGRADE", "C": "ADMIT",
                     "D": "ADMIT", "E": "NOT_APPLICABLE"},
    },
    "S10": {
        "name": "valid unpaired design (independent seeds, declared)",
        "invalid_claim_expected": True,
        "mechanics": {"independent_seeds": True},
        "gt": {
            "descriptive": "VALID",
            "paired_inference": "INVALID",
            "replay": "VALID",
            "crn": "INVALID",
            "event_alignment": "INVALID",
            "wording": "unpaired_only",
        },
        "expected": {"A": "ADMIT", "B": "SUPPRESS_OR_DOWNGRADE",
                     "C": "ADMIT", "D": "SUPPRESS_OR_DOWNGRADE",
                     "E": "SUPPRESS_OR_DOWNGRADE"},
    },
}

# Dimensions along which methods are scored (metric definitions in ANALYSIS_PLAN)
GT_DIMENSIONS = ["descriptive", "paired_inference", "replay", "crn",
                 "event_alignment", "wording"]
