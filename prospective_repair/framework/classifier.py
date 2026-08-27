"""Repaired claim-specific classifier (fail-closed, branch-independent B).

Key repairs vs historical implementation (see P0 audit):
- Branch B admits from pairing-basis evidence alone; replay/coupling/event
  alignment NEVER enter unless model_consumes_sync is explicitly true.
- Sync-context instability no longer downgrades B.
- Canonical enums via exact equality; artifact identity records per-arm agent/
  config with allowed-differences declaration; D checks marginals/uniqueness/
  collisions; E validates ontology/version/coverage rather than bare overlap.
Every decision emits a predicate-level trace for provenance.
"""
from __future__ import annotations

from typing import Any, Dict

from .evidence import EvidenceBundle
from .constants import UNIT_DECISION, MF_HIERARCHICAL


def _trace(store: Dict[str, Any], key: str, value: Any) -> Any:
    store[key] = value
    return value


def classify_branch(b: EvidenceBundle, branch: str) -> str:
    t: Dict[str, Any] = {}
    b.predicate_trace[branch] = t

    # ---------------- Branch A: matched description ------------------------
    if branch == "BRANCH_A":
        identity_ok = _trace(t, "artifact_identity_ok", b.artifact_identity_ok())
        fields_ok = _trace(t, "schedule_fields_match", b.schedule_fields_match)
        eff_ok = _trace(t, "effective_matches_declared", b.effective_matches_declared())
        complete = _trace(t, "rows_complete", b.rows_present == b.rows_scheduled)
        unique = _trace(t, "row_ids_unique", b.row_ids_unique)
        if not identity_ok or not fields_ok or not eff_ok or not complete or not unique:
            return "SUPPRESS"
        return "ADMIT"

    # ---------------- Branch B: statistically paired inference -------------
    if branch == "BRANCH_B":
        unit_ok = _trace(t, "unit_cluster_respecting",
                         b.analysis_unit in ("seed_condition", "hand_cluster"))
        if not unit_ok:
            return "SUPPRESS"  # pseudoreplication guard (decision-unit etc.)
        if _trace(t, "independent_arms_worded_paired", b.independent_arms_declared):
            return "SUPPRESS"  # paired wording unsupported; unpaired analysis remains valid
        bases = b.pairing_bases
        rm_usable = (_trace(t, "repeat_clusters_usable",
                            bool(b.repeat_ids_unique_within_units)
                            and b.repeats_per_unit_pairs >= 2))
        bases["repeated_measures"] = bases["repeated_measures"] and rm_usable
        if not any([bases["matched_assignment"], bases["repeated_measures"],
                    bases["hierarchical_model"], bases["defended_joint_model"]]):
            if len(b.design_justifications) == 0 and b.model_family == "none":
                _trace(t, "fail_closed_no_basis", True)
                return "FAIL_CLOSED"
            return "SUPPRESS"
        # Matched-realization wording quality (does NOT require C/D/E evidence):
        intact = _trace(t, "matched_conditions_intact", b.matched_conditions_intact)
        denom_ok = _trace(t, "denominator_sound", not b.denominator_corrupt)
        if b.model_consumes_sync:
            sync_needed_ok = _trace(t, "model_requires_sync_and_verified",
                                    bool(b.sync_verified_stateful))
            if not sync_needed_ok:
                return "DOWNGRADE"
        if intact and denom_ok:
            return "ADMIT"
        return "DOWNGRADE"  # weaker statistical wording still sound

    # ---------------- Branch C: scoped deterministic replay -----------------
    if branch == "BRANCH_C":
        scope = _trace(t, "scope_claimed", b.replay_scope_claimed)
        repeats_known = _trace(t, "repeats_evidence_present",
                               b.repeats_digests_equal_primary is not None)
        if not repeats_known:
            return "FAIL_CLOSED"
        ok = bool(b.repeats_digests_equal_primary)
        if scope == "within_artifact":
            return "ADMIT" if ok else "SUPPRESS"
        ctxs = list(b.contexts or [])
        labels = {c.get("context_label") for c in ctxs}
        ctx_done = _trace(t, "context_testing_done", len(labels) >= 2)
        if scope == "cross_context_inproc":
            if not ctx_done:
                return "FAIL_CLOSED"
            cross_ok = all(c.get("digest") == c.get("primary_digest")
                           for c in ctxs) if ctxs else False
            _trace(t, "cross_context_digests_equal", cross_ok)
            return "ADMIT" if (ok and cross_ok) else "SUPPRESS"
        # scope == cross_process
        proc_sep = _trace(t, "has_process_separated_replica",
                          bool(b.has_process_separated_replica))
        if not proc_sep:
            return "FAIL_CLOSED"
        proc_ok = all(c.get("digest") == c.get("primary_digest")
                      for c in ctxs if c.get("process_separated"))
        proc_seen = any(c.get("process_separated") for c in ctxs)
        _trace(t, "cross_process_digests_equal", proc_ok)
        return "ADMIT" if (ok and proc_ok and proc_seen) else "SUPPRESS"

    # ---------------- Branch D: CRN coupling validity -----------------------
    if branch == "BRANCH_D":
        ctype = _trace(t, "coupling_type", b.coupling_type)
        if ctype in ("none", "independent_seeds", "", None):
            return "SUPPRESS"
        if ctype == "stateful_sync":
            verified = _trace(t, "stateful_sync_values_equal",
                              bool(b.sync_verified_stateful))
            desync = _trace(t, "coupled_stream_desync_across_contexts",
                            bool(b.context_desync_of_coupled_stream))
            if not verified:
                return "SUPPRESS"
            if desync:
                return "SUPPRESS"  # coupling cannot be trusted across contexts
            return "ADMIT"
        # event-keyed family
        onto = _trace(t, "ontology_match", b.ontology_match)
        uniq = _trace(t, "key_uniqueness_ok", b.key_uniqueness_ok)
        coll = _trace(t, "key_collision_count", b.key_collision_count)
        marg = _trace(t, "marginals_preserved", b.marginals_preserved)
        sep = _trace(t, "stream_separation_ok", b.stream_separation_ok)
        pol_blind = (ctype == "event_keyed_policy_blind")
        _trace(t, "policy_preserved_required", not pol_blind)
        vals_eq = _trace(t, "matched_event_values_equal", b.events_values_equal_matched)
        if onto is None or uniq is None or marg is None:
            return "FAIL_CLOSED"
        required = [onto, uniq, marg] + ([vals_eq] if vals_eq is not None else [])
        if not all(bool(x) for x in required) or int(coll) > 0 or pol_blind:
            return "SUPPRESS"
        return "ADMIT"

    # ---------------- Branch E: event-aligned coupling ----------------------
    if branch == "BRANCH_E":
        ctype = _trace(t, "coupling_type", b.coupling_type)
        if ctype not in ("event_keyed_policy_preserving", "event_keyed_policy_blind"):
            return "SUPPRESS"
        onto = _trace(t, "ontology_match", b.ontology_match)
        uniq = _trace(t, "key_uniqueness_ok", b.key_uniqueness_ok)
        coll = _trace(t, "key_collision_count", b.key_collision_count)
        matched = _trace(t, "matched_event_count", b.matched_event_count)
        unmatched = _trace(t, "unmatched_event_count", b.unmatched_event_count)
        vals_eq = _trace(t, "values_equal_on_matched", b.events_values_equal_matched)
        pol_blind = (ctype == "event_keyed_policy_blind")
        if onto is None or uniq is None:
            return "FAIL_CLOSED"
        if not onto or not uniq or coll > 0 or pol_blind:
            return "SUPPRESS"
        coverage_ok = (unmatched == 0) or _trace(
            t, "partial_ontology_declared", b.partial_ontology_declared)
        if not coverage_ok:
            return "SUPPRESS"
        if matched <= 0:
            return "FAIL_CLOSED"
        return "ADMIT" if bool(vals_eq) else "SUPPRESS"

    raise ValueError(branch)


def classify_all(b: EvidenceBundle) -> Dict[str, str]:
    out = {}
    for br in ("BRANCH_A", "BRANCH_B", "BRANCH_C", "BRANCH_D", "BRANCH_E"):
        out[br] = classify_branch(b, br)
    return out
