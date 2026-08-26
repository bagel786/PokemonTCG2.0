"""Evidence bundle construction and the CSVF classifier (fail-closed).

The classifier consumes ONLY structural evidence (artifact identity, declared
vs effective schedules, draw-log synchronization, replay digests, design
declarations, analysis-unit declarations). Final outcome values are excluded
from classifier inputs (result-exclusion invariant).
"""

from .rng_manager import event_alignment_violations


def build_bundle(row_plan, arm_a, arm_b, repeats_a=None, contexts=None,
                 rows_present=None, rows_scheduled=None, analysis_meta=None):
    """Assemble an EvidenceBundle for one schedule row.

    row_plan: declared schedule fields (seed, condition labels, coupling type,
              design declarations)
    arm_a/arm_b: RunArtifact for the primary pair
    repeats_a: list of RunArtifact re-executions of arm A (within-artifact)
    contexts: list of dicts {context_label, digest} from other processes/workers
    rows_present/rows_scheduled: completeness accounting
    analysis_meta: declared analysis properties (unit, model family)
    """
    repeats_a = repeats_a or []
    contexts = contexts or []
    rows_present = rows_present if rows_present is not None else 1
    rows_scheduled = rows_scheduled if rows_scheduled is not None else 1
    analysis_meta = analysis_meta or {}

    declared = int(row_plan["seed"])
    eff_a = int(arm_a.effective_seed)
    eff_b = int(arm_b.effective_seed)

    schedule_fields_match = (
        arm_a.declared_seed == arm_b.declared_seed == declared
        and row_plan.get("condition_a") is not None
        and row_plan.get("condition_b") is not None
    )
    effective_matches_declared = (eff_a == declared) and (eff_b == declared)

    # Replay evidence -------------------------------------------------------
    primary_digest = arm_a.projection_digest()
    replay_digests = [primary_digest] + [r.projection_digest() for r in repeats_a]
    within_replay_ok = len(set(replay_digests)) == 1 and len(repeats_a) >= 1
    ctx_labels = {c["context_label"] for c in contexts}
    context_testing_done = len(ctx_labels) >= 2
    cross_context_ok = all(c["digest"] == primary_digest for c in contexts)

    def _first_dealer_fp(art):
        return next((e.get("value") for e in art.draw_log
                     if e.get("source") == "dealer"), None)

    primary_dealer_fp = _first_dealer_fp(arm_a)
    # Instability counts ONLY when the coupled (dealer/model) stream itself
    # differs in another execution context; pure agent-side jitter does not.
    context_instability = any(
        c.get("dealer_fp") is not None and c.get("dealer_fp") != primary_dealer_fp
        for c in contexts)

    # Coupling / synchronization evidence ------------------------------------
    coupling_type = row_plan.get("coupling_type")  # 'stateful_sync'|'event_keyed'|None
    sync_verified = False
    events_aligned = None
    if coupling_type == "stateful_sync":
        fa = [e for e in arm_a.draw_log
              if e.get("source") in ("dealer", "model")][:24]
        fb = [e for e in arm_b.draw_log
              if e.get("source") in ("dealer", "model")][:24]
        if fa and fb and len(fa) == len(fb):
            sync_verified = all(
                x.get("value") == y.get("value")
                for x, y in zip(fa, fb))
        else:
            sync_verified = False
    elif coupling_type == "event_keyed":
        keys_a = {e["event_id"]: e["values"] for e in arm_a.draw_log}
        keys_b = {e["event_id"]: e["values"] for e in arm_b.draw_log}
        common = set(keys_a) & set(keys_b)
        events_aligned = {
            "compared": len(common),
            "mismatched": sum(1 for k in common if keys_a[k] != keys_b[k]),
        }
        sync_verified = len(common) > 0 and events_aligned["mismatched"] == 0

    design = set(row_plan.get("design_justifications", []))
    unit = analysis_meta.get("analysis_unit", "seed_condition")
    model_family = analysis_meta.get("model_family", "none")

    return {
        "row_id": row_plan["row_id"],
        "declared_seed": declared,
        "artifact_identity_ok": (
            arm_a.system == arm_b.system
            and arm_a.adapter_version == arm_b.adapter_version
            and arm_a.adapter_hash == arm_b.adapter_hash
        ),
        "schedule_fields_match": schedule_fields_match,
        "effective_matches_declared": effective_matches_declared,
        "rows_complete": rows_present == rows_scheduled,
        "rows_missing": max(0, rows_scheduled - rows_present),
        "unit_is_cluster": unit in ("seed_condition", "hand_cluster"),
        "unit_declared": unit,
        "model_family": model_family,
        "design_justifications": sorted(design),
        "has_randomized_assignment": "randomized_assignment" in design,
        "has_repeated_measures": "repeated_measures" in design
        and analysis_meta.get("repeats_per_unit", 1) > 1,
        "has_hierarchical_model": "hierarchical_model" in model_family,
        "has_defended_joint_model": "defended_joint_stochastic_model" in design,
        "repeats_available": len(repeats_a),
        "context_testing_done": context_testing_done,
        "within_replay_ok": within_replay_ok,
        "cross_context_ok": cross_context_ok,
        "context_instability": context_instability,
        "coupling_type": coupling_type,
        "coupling_specified": coupling_type in ("stateful_sync", "event_keyed"),
        "sync_verified": bool(sync_verified),
        "events_aligned": events_aligned,
        "independent_seeds_declared": bool(row_plan.get("independent_seeds")),
    }


DECISIONS = ("ADMIT", "DOWNGRADE", "SUPPRESS", "FAIL_CLOSED")


def _downgrade_if(ok, downgrade_ok=False):
    if ok:
        return "ADMIT"
    return "DOWNGRADE" if downgrade_ok else "SUPPRESS"


def classify_branch(bundle, branch):
    """Return decision string for one branch from one bundle."""

    def gate(cond, dgrade=False):
        return _downgrade_if(cond, dgrade)

    if branch == "BRANCH_A":
        if not bundle["artifact_identity_ok"]:
            return "SUPPRESS"
        if bundle["independent_seeds_declared"]:
            return gate(bundle["rows_complete"], dgrade=True)
        if not bundle["schedule_fields_match"]:
            return "SUPPRESS"
        if not bundle["effective_matches_declared"]:
            return "SUPPRESS"  # declared seed was not the effective seed
        if not bundle["rows_complete"]:
            return "SUPPRESS"  # missing rows invalidate the denominator
        return "ADMIT"

    if branch == "BRANCH_B":
        justified = any([
            bundle["has_randomized_assignment"],
            bundle["has_repeated_measures"],
            bundle["has_hierarchical_model"],
            bundle["has_defended_joint_model"],
        ])
        if bundle["independent_seeds_declared"]:
            return "SUPPRESS"  # paired wording unsupported in unpaired design
        if not bundle["rows_complete"]:
            return "DOWNGRADE"
        if not bundle["unit_is_cluster"]:
            return "SUPPRESS"  # pseudoreplication guard
        if bundle["coupling_specified"] and bundle["sync_verified"]:
            # Demonstrated execution-state instability undermines trust that
            # recorded runs came from the synchronized context at all.
            if bundle["coupling_type"] == "stateful_sync" and bundle[
                    "context_instability"]:
                return "DOWNGRADE"
            return "ADMIT"  # synchronized pairing: strongest basis
        # Weaker basis (randomization/repeated-measures/joint model) supports
        # only downgraded statistical wording, never full matched claims.
        return "DOWNGRADE" if justified else "SUPPRESS"

    if branch == "BRANCH_C":
        if not bundle["repeats_available"] or not bundle["context_testing_done"]:
            return "FAIL_CLOSED"
        return gate(bundle["within_replay_ok"] and bundle["cross_context_ok"])

    if branch == "BRANCH_D":
        if not bundle["coupling_specified"]:
            return "SUPPRESS"
        if not bundle["sync_verified"]:
            return "SUPPRESS"
        if bundle["coupling_type"] == "stateful_sync" and bundle[
                "context_instability"]:
            return "SUPPRESS"  # sync cannot be trusted across contexts
        return "ADMIT"

    if branch == "BRANCH_E":
        if bundle["coupling_type"] != "event_keyed":
            return "SUPPRESS"
        ea = bundle["events_aligned"]
        if ea is None:
            return "FAIL_CLOSED"
        if ea["compared"] == 0:
            return "FAIL_CLOSED"
        return gate(ea["mismatched"] == 0)

    raise ValueError(branch)


def classify_all(bundle):
    return {b: classify_branch(bundle, b) for b in
            ["BRANCH_A", "BRANCH_B", "BRANCH_C", "BRANCH_D", "BRANCH_E"]}
