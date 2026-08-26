"""Baseline methods B0-B7.

Each baseline receives the same artifacts/evidence as the full framework and
returns claim-class decisions using only ITS OWN narrower rules. Baselines are
implemented as competent best-effort alternatives, not strawmen.
"""

from .classifier import DECISIONS


def _b_decisions(a="ADMIT", b="ADMIT", c="ADMIT", d="ADMIT", e="ADMIT"):
    return {"BRANCH_A": a, "BRANCH_B": b, "BRANCH_C": c, "BRANCH_D": d,
            "BRANCH_E": e}


def b0_schedule_matching_only(bundle):
    """Admits descriptive + paired claims whenever declared fields match."""
    if bundle["schedule_fields_match"] and bundle["artifact_identity_ok"]:
        paired = "ADMIT" if bundle["schedule_fields_match"] and not bundle[
            "independent_seeds_declared"] else "SUPPRESS"
        return _b_decisions(a="ADMIT", b=paired)
    return _b_decisions(a="SUPPRESS", b="SUPPRESS")


def b1_outcome_only_aa(bundle, aa_outcome_variance=None):
    """Outcome-only A/A: flags nondeterminism if duplicate outcomes differ."""
    ok = aa_outcome_variance is None or aa_outcome_variance == 0.0
    if bundle["schedule_fields_match"]:
        paired = "ADMIT" if ok and not bundle["independent_seeds_declared"] else "DOWNGRADE"
        return _b_decisions(b=paired, c="DOWNGRADE" if not ok else "ADMIT")
    return _b_decisions(a="SUPPRESS", b="SUPPRESS")


def b2_trace_level_aa(bundle):
    """Trace-level A/A: within-artifact projection equality (single context)."""
    if not bundle["schedule_fields_match"]:
        return _b_decisions(a="SUPPRESS", b="SUPPRESS")
    replay = "ADMIT" if bundle["within_replay_ok"] else "SUPPRESS"
    paired = "ADMIT" if not bundle["independent_seeds_declared"] else "SUPPRESS"
    return _b_decisions(c=replay, b=paired)


def b3_within_seed_replication(bundle, min_repeats=2):
    """Extra within-seed repeats; empirical variability gates claims."""
    enough = bundle["repeats_available"] >= min_repeats
    stable = bundle["within_replay_ok"]
    if not bundle["schedule_fields_match"]:
        return _b_decisions(a="SUPPRESS", b="SUPPRESS")
    replay = "ADMIT" if (enough and stable) else ("FAIL_CLOSED" if not enough else "SUPPRESS")
    paired = "ADMIT" if not bundle["independent_seeds_declared"] else "SUPPRESS"
    return _b_decisions(c=replay, b=paired)


def b4_unpaired_analysis(bundle):
    """Honest independent-arm analysis; makes no pairing/replay claims."""
    # B4 never asserts C/D/E; it downgrades B-pairing to unpaired inference.
    out = _b_decisions()
    if bundle["independent_seeds_declared"] or True:
        pass
    return {
        "BRANCH_A": "ADMIT" if bundle["schedule_fields_match"] or bundle[
            "independent_seeds_declared"] else "DOWNGRADE",
        "BRANCH_B": "DOWNGRADE",  # unpaired wording only
        "BRANCH_C": "DOWNGRADE",
        "BRANCH_D": "SUPPRESS",
        "BRANCH_E": "SUPPRESS",
    }


def b5_clustered_hierarchical(bundle):
    """Models cluster structure; valid under residual randomness; no coupling
    verification. Often the strongest simple competitor."""
    cluster_ok = bundle["unit_is_cluster"]
    justified = (bundle["has_randomized_assignment"] or
                 bundle["has_hierarchical_model"] or
                 bundle["has_repeated_measures"] or
                 bundle["has_defended_joint_model"])
    if bundle["independent_seeds_declared"]:
        return _b_decisions(b="SUPPRESS")
    b = "ADMIT" if (cluster_ok and justified) else (
        "DOWNGRADE" if cluster_ok else "SUPPRESS")
    return _b_decisions(b=b)


def b6_event_keyed_whitebox(bundle):
    """White-box event-keyed coupling: verifies alignment from keyed logs."""
    ek = bundle["coupling_type"] == "event_keyed" and bundle["sync_verified"]
    if bundle["independent_seeds_declared"]:
        return _b_decisions(d="SUPPRESS", e="SUPPRESS")
    return _b_decisions(
        b="ADMIT",
        d="ADMIT" if ek else "DOWNGRADE",
        e="ADMIT" if ek else "DOWNGRADE",
    )


BASELINES = {
    "B0_schedule_only": b0_schedule_matching_only,
    "B1_outcome_aa": lambda bundle: b1_outcome_only_aa(bundle),
    "B2_trace_aa": b2_trace_level_aa,
    "B3_within_seed_reps": lambda bundle: b3_within_seed_replication(bundle),
    "B4_unpaired": b4_unpaired_analysis,
    "B5_cluster_hier": b5_clustered_hierarchical,
    "B6_event_keyed_wb": b6_event_keyed_whitebox,
}
FULL_FRAMEWORK = "B7_csvf_full"


def method_names():
    return list(BASELINES.keys()) + [FULL_FRAMEWORK]
