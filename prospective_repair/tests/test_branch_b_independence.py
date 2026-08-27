"""Branch-B independence regressions (the core conceptual repair).

Mirrors the six demonstrations demanded by the campaign specification.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from framework.evidence import EvidenceBundle, ArmIdentity           # noqa: E402
from framework.classifier import classify_all                        # noqa: E402


def make_bundle(**kw):
    b = EvidenceBundle()
    b.declared_seed = 10
    b.declared_seed_b = 10
    b.effective_seed_a = 10
    b.effective_seed_b = 10
    b.schedule_fields_match = True
    b.rows_present = b.rows_scheduled = 5
    b.identity_arm_a = ArmIdentity("holdem", "v", "2.0.0", "h", "A", "ca")
    b.identity_arm_b = ArmIdentity("holdem", "v", "2.0.0", "h", "B", "cb")
    b.allowed_differences_declared = True
    b.design_justifications = ["probability_sampling_of_unit",
                               "randomized_matched_assignment"]
    b.analysis_unit = "seed_condition"
    for k, v in kw.items():
        setattr(b, k, v)
    return b


def test_valid_B_with_invalid_C_still_admits():
    b = make_bundle(repeats_digests_equal_primary=False,
                    contexts=[{"context_label": "fresh", "pid": 1,
                               "digest": "x1"},
                              {"context_label": "worker2", "pid": 1,
                               "digest": "DIFFERENT"}])
    out = classify_all(b)
    assert out["BRANCH_B"] == "ADMIT", out
    assert out["BRANCH_C"] in ("SUPPRESS", "FAIL_CLOSED"), out


def test_valid_B_with_absent_D_and_E_still_admits():
    b = make_bundle()  # coupling_type defaults to "none"; no event maps at all
    out = classify_all(b)
    assert out["BRANCH_B"] == "ADMIT"
    assert out["BRANCH_D"] == "SUPPRESS" and out["BRANCH_E"] == "SUPPRESS"


def test_shared_seed_alone_without_paired_design_suppresses_pairing():
    b = make_bundle(design_justifications=[])   # no design declarations at all
    out = classify_all(b)
    # shared-seed-only bundles carry NO basis -> fail closed, never admit
    assert out["BRANCH_B"] == "FAIL_CLOSED"
    b2 = make_bundle(design_justifications=["probability_sampling_of_unit"])
    # sampling-of-units alone is still not a pairing basis -> explicit SUPPRESS
    assert classify_all(b2)["BRANCH_B"] == "SUPPRESS"


def test_declared_honest_unpaired_suppresses_paired_wording_only():
    b = make_bundle(
        independent_arms_declared=True,
        design_justifications=["probability_sampling_of_unit",
                               "independent_arms"],
        declared_seed_b=1000013, effective_seed_b=1000013)
    out = classify_all(b)
    assert out["BRANCH_B"] == "SUPPRESS"


def test_pseudoreplicated_units_rejected_as_independent():
    b = make_bundle(analysis_unit="decision")
    assert classify_all(b)["BRANCH_B"] == "SUPPRESS"


def test_unknown_evidence_never_strengthens_claim():
    b = make_bundle()
    # simulate lost predicates: missing design info cannot produce admission
    b.design_justifications = []
    assert classify_all(b)["BRANCH_B"] == "FAIL_CLOSED"
    # replay without any repeat/context knowledge must fail closed
    b2 = make_bundle(repeats_digests_equal_primary=None)
    assert classify_all(b2)["BRANCH_C"] == "FAIL_CLOSED"


def test_sync_context_instability_does_not_downgrade_valid_B():
    b = make_bundle(coupling_type="stateful_sync", sync_verified_stateful=True,
                    context_desync_of_coupled_stream=True)
    assert classify_all(b)["BRANCH_B"] == "ADMIT"
