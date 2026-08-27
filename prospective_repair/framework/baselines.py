"""Competent baselines with typed views + explicit abstention.

Repairs: no default-ADMIT (T12), real A/A consumption (T02), no dead paths
(T13), scope-limited B6 (D-R1), string-free cluster logic (T14).
"""
from __future__ import annotations

from typing import Callable, Dict

from .evidence import EvidenceBundle, MethodView
from .constants import UNIT_DECISION, MF_HIERARCHICAL

ABSTAIN = "ABSTAIN_NOT_EVALUATED"


def _all_branches(a=ABSTAIN, b=ABSTAIN, c=ABSTAIN, d=ABSTAIN, e=ABSTAIN):
    return {"BRANCH_A": a, "BRANCH_B": b, "BRANCH_C": c,
            "BRANCH_D": d, "BRANCH_E": e}


def make_view(method: str, bundle: EvidenceBundle, extras: Dict | None = None):
    return MethodView(method, bundle, extras or {})


# ------------------------------- B0 -----------------------------------------
def b0_schedule_matching_only(bundle: EvidenceBundle) -> Dict[str, str]:
    v = make_view("B0_schedule_only", bundle)
    fields_ok = (v.schedule_fields_match and v.effective_seed_a == v.declared_seed
                 and v.effective_seed_b == v.declared_seed)
    complete = v.rows_present == v.rows_scheduled and v.row_ids_unique
    if not fields_ok:
        return _all_branches(a="SUPPRESS")
    if not complete:
        return _all_branches(a="SUPPRESS")
    return _all_branches(a="ADMIT")


# ------------------------------- B1 -----------------------------------------
def b1_outcome_only_aa(bundle: EvidenceBundle, aa_extras: Dict) -> Dict[str, str]:
    """Requires REAL retained A/A repetitions via extras; fails closed w/o bank."""
    v = make_view("B1_outcome_aa", bundle, aa_extras)
    reps = int(v.aa_bank_reps_available)
    disp = v.aa_outcome_dispersion_indicator  # 0 stable .. >0 varying (indicator)
    if reps < 2:
        out = {"BRANCH_A": "ADMIT" if v.schedule_fields_match else "SUPPRESS"}
        # cannot do its own C/B noise check without the bank -> fail closed on those
        out.update({"BRANCH_B": ABSTAIN, "BRANCH_C": "FAIL_CLOSED",
                    "BRANCH_D": ABSTAIN, "BRANCH_E": ABSTAIN})
        if out["BRANCH_A"] == "SUPPRESS":
            out["BRANCH_B"] = "SUPPRESS"
        return out
    stable = disp == 0
    out = {
        "BRANCH_A": "ADMIT" if v.schedule_fields_match else "SUPPRESS",
        # outcome stability alone can never certify pairing -> wording capped at DOWNGRADE
        "BRANCH_B": "DOWNGRADE" if v.schedule_fields_match else "SUPPRESS",
        "BRANCH_C": "ADMIT" if (stable and v.schedule_fields_match) else (
            "SUPPRESS" if v.schedule_fields_match else ABSTAIN),
    }
    return {**_all_branches(), **out}


# ------------------------------- B2 -----------------------------------------
def b2_trace_level_aa(bundle: EvidenceBundle) -> Dict[str, str]:
    v = make_view("B2_trace_aa", bundle)
    if not v.schedule_fields_match:
        return _all_branches(a="SUPPRESS", b="SUPPRESS", c="SUPPRESS")
    within_ok = bool(v.repeats_digests_equal_primary)
    if str(v.replay_scope_claimed) != "within_artifact":
        # claims beyond its single-context view -> fail closed rather than guess
        c_decision = "FAIL_CLOSED"
    elif within_ok:
        c_decision = "ADMIT"
    else:
        c_decision = "SUPPRESS"
    return _all_branches(c=c_decision)


# ------------------------------- B3 -----------------------------------------
def b3_within_seed_replication(bundle: EvidenceBundle, min_repeats: int = 2,
                               digests_present: bool = True) -> Dict[str, str]:
    v = make_view("B3_within_seed_reps", bundle,
                  extras={"digests_present": digests_present})
    if not getattr(v, "digests_present"):
        return _all_branches(c="FAIL_CLOSED")
    enough = bool(v.repeats_digests_equal_primary)
    unit_cluster = v.analysis_unit != UNIT_DECISION
    if not enough:
        return _all_branches(c="FAIL_CLOSED")
    rm_planned = any(x in (v.design_justifications or [])
                     for x in ("repeated_measures",)) or \
        v.within_cluster_variation_present is True
    b_dec = "ADMIT" if (unit_cluster and rm_planned) else "DOWNGRADE"
    return _all_branches(b=b_dec)


# ------------------------------- B4 -----------------------------------------
def b4_unpaired_analysis(bundle: EvidenceBundle) -> Dict[str, str]:
    v = make_view("B4_unpaired_analysis", bundle)
    if not v.schedule_fields_match:
        return _all_branches(a="SUPPRESS", b="SUPPRESS")
    if v.independent_arms_declared:
        # genuinely independent arms -> unpaired inference valid; paired word SUPPRESSed
        return _all_branches(b="SUPPRESS")
    if v.denominator_corrupt:
        return _all_branches(b="SUPPRESS")  # cannot defend denominators -> quiet
    # independence undeclared and pairing unproven here: refuse to choose
    return _all_branches(b="FAIL_CLOSED")


# ------------------------------- B5 -----------------------------------------
def b5_clustered_hierarchical(bundle: EvidenceBundle) -> Dict[str, str]:
    v = make_view("B5_cluster_hierarchical", bundle)
    bases = v.pairing_bases  # only declared design refs are visible in this view
    clusters_usable = bool(v.repeat_ids_unique_within_units) and \
        (int(getattr(v, "repeats_per_unit_pairs")) >= 2 or
         bases.get("matched_assignment"))
    unit_ok = v.analysis_unit != UNIT_DECISION
    model_declared = v.model_family == MF_HIERARCHICAL or \
        bases.get("repeated_measures") or bases.get("defended_joint_model")
    resid_var_known = v.within_cluster_variation_present
    if not unit_ok:
        return _all_branches(b="SUPPRESS")
    if not clusters_usable:
        return _all_branches(b="FAIL_CLOSED" if repeats_missing_signature(v)
                             else "SUPPRESS")
    resid_ok = resid_var_known is None or bool(resid_var_known)
    if model_declared and resid_ok:
        return _all_branches(b="ADMIT")
    if resid_ok:
        return _all_branches(b="DOWNGRADE")
    return _all_branches(b="SUPPRESS")


def repeats_missing_signature(view) -> bool:
    # clusters unusable because repeat ids collide / zero repeats recorded
    return int(getattr(view, "repeats_per_unit_pairs", 0)) < 2


# ------------------------------- B6 -----------------------------------------
def b6_event_keyed_whitebox(bundle: EvidenceBundle) -> Dict[str, str]:
    v = make_view("B6_event_keyed_whitebox", bundle)
    ctype = v.coupling_type
    keyed = ctype in ("event_keyed_policy_preserving", "event_keyed_policy_blind")
    if not keyed:
        return _all_branches()  # fully abstain outside its scope
    onto = bool(v.ontology_match)
    uniq = bool(v.key_uniqueness_ok)
    coll = int(v.key_collision_count)
    marg = bool(v.marginals_preserved)
    sep = bool(v.stream_separation_ok)
    pol_blind = ctype == "event_keyed_policy_blind"
    d_ok = onto and uniq and coll == 0 and marg and sep and not pol_blind
    e_ok = onto and uniq and coll == 0 and marg and not pol_blind
    d_dec = "ADMIT" if d_ok else "SUPPRESS"
    e_dec = "ADMIT" if e_ok else "SUPPRESS"
    # pairing basis visible but NOT measurable by this method -> honest cap
    bases = v.pairing_bases
    if bases.get("matched_assignment"):
        b_dec = "DOWNGRADE"
    else:
        b_dec = ABSTAIN
    return _all_branches(d=d_dec, e=e_dec, b=b_dec)


BASELINE_FUNCS: Dict[str, Callable] = {
    "B0_schedule_only": b0_schedule_matching_only,
    "B1_outcome_aa": b1_outcome_only_aa,
    "B2_trace_aa": b2_trace_level_aa,
    "B3_within_seed_reps": b3_within_seed_replication,
    "B4_unpaired_analysis": b4_unpaired_analysis,
    "B5_cluster_hierarchical": b5_clustered_hierarchical,
    "B6_event_keyed_whitebox": b6_event_keyed_whitebox,
}
FULL_FRAMEWORK = "B7_csvf_full"


def method_names():
    return list(BASELINE_FUNCS.keys()) + [FULL_FRAMEWORK]
