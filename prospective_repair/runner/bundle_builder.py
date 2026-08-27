"""Evidence-bundle builder: artifacts + construction mechanisms -> bundle.

Single producer of EvidenceBundle; enforces canonical enums (T22), the
identity model (T23), and honesty flags (matched_conditions_intact,
denominator_corrupt) derived from MECHANISMS, not outcomes.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from framework.evidence import ArmIdentity, EvidenceBundle  # noqa: E402
from systems.mechanics import ExecutionSpec  # noqa: E402


def build_bundle(system: str, spec: ExecutionSpec, art_a: Dict, art_b: Dict,
                 repeat_arts_a: List[Dict], repeat_arts_b: List[Dict],
                 context_records: List[Dict], row_plan: Dict,
                 grammar_construction: Dict,
                 aa_bank_reps: int = 0,
                 aa_dispersion_indicator: Optional[int] = None,
                 ontology_version_a: str = "v1",
                 ontology_version_b: str = "v1") -> EvidenceBundle:
    b = EvidenceBundle()
    b.row_id = f"{system}-{spec.construction}-{spec.declared_seed}"
    b.declared_seed = int(art_a["declared_seed"])
    b.declared_seed_b = int(art_b["declared_seed"])
    b.effective_seed_a = int(art_a["effective_seed"])
    b.effective_seed_b = int(art_b["effective_seed"])
    b.schedule_fields_match = True  # both arms carry identical declared fields by harness
    b.rows_scheduled = row_plan.get("rows_scheduled", 1)
    b.rows_present = row_plan.get("rows_present_recorded", 1)
    b.row_ids_unique = bool(row_plan.get("ids_unique", True))

    for art, tgt in ((art_a, "a"), (art_b, "b")):
        ident = ArmIdentity(
            system=art["system"], system_version=art["system_version"],
            adapter_version=art["adapter_version"],
            adapter_hash=art["adapter_hash"], agent_id=art["agent_id"],
            agent_config_hash=art["agent_config_hash"])
        if tgt == "a":
            b.identity_arm_a = ident
        else:
            b.identity_arm_b = ident
    b.allowed_differences_declared = True  # grammar constructions differ ONLY by declared policy/temperature

    b.design_justifications = list(spec.design_justifications)
    b.analysis_unit = "decision" if spec.analysis_unit == "decision" else \
        ("hand_cluster" if spec.analysis_unit == "hand" else "seed_condition")
    b.model_family = "hierarchical" if any(
        x in spec.design_justifications for x in ("hierarchical_model",)) else "none"
    # Truncation/burn/cache/queue/dup/persist/collision destroy matched
    # realization wording (statistical comparison remains possible => DOWNGRADE):
    corrupting = bool(spec.truncate_bits_b or spec.burn_draws_b or
                      spec.module_cache_contam_b or spec.queue_tax_a or
                      spec.queue_tax_b or spec.persistent_state_cross_proc or
                      spec.stream_collision_b or
                      (row_plan.get("duplicated") is True))
    b.matched_conditions_intact = not corrupting
    denom_bad = bool(spec.drop_rows_mod) or row_plan.get("duplicated") is True \
        or not b.row_ids_unique
    b.denominator_corrupt = denom_bad
    usable_pairs = min(len(repeat_arts_a), len(repeat_arts_b))
    colliding = spec.repeat_ids_collide
    b.repeat_ids_unique_within_units = not colliding
    b.repeats_per_unit_pairs = 0 if colliding else usable_pairs
    var_flags = []
    for ra, rb in zip(repeat_arts_a[:usable_pairs], repeat_arts_b[:usable_pairs]):
        var_flags.append(
            ra["projection_digest"] != art_a["projection_digest"] or
            rb["projection_digest"] != art_b["projection_digest"])
    b.within_cluster_variation_present = None if usable_pairs == 0 else any(var_flags)
    b.model_consumes_sync = False  # no repaired analysis consumes sync; explicit field per spec
    b.independent_arms_declared = "independent_arms" in spec.design_justifications

    # ---- replay evidence -------------------------------------------------
    b.replay_scope_claimed = spec.replay_scope_claimed
    # Within-artifact repetition evidence folds in same-process executions of
    # arm A (context replicas ARE re-executions); process-separated replicas
    # are compared only for the scopes that claim them.
    inproc_ctx_digests = [c["digest"] for c in (context_records or [])
                          if not c.get("process_separated")]
    dgs = [art_a["projection_digest"]] + inproc_ctx_digests + \
        [r["projection_digest"] for r in repeat_arts_a]
    b.repeats_digests_equal_primary = len(set(dgs)) == 1 and len(dgs) >= 2
    b.contexts = context_records
    fps = {c.get("dealer_fp") for c in context_records
           if c.get("dealer_fp") is not None}
    primary_fp = art_a.get("dealer_first_fp")
    coupled_desync = primary_fp is not None and any(f != primary_fp
                                                    for f in fps)
    b.context_instability_coupled_stream = (None if primary_fp is None
                                            else coupled_desync)
    b.context_desync_of_coupled_stream = b.context_instability_coupled_stream
    b.has_process_separated_replica = any(c.get("process_separated")
                                          for c in context_records)

    # ---- coupling evidence -----------------------------------------------
    keyed_on = spec.event_keyed or spec.policy_blind
    if keyed_on:
        b.coupling_type = ("event_keyed_policy_blind" if spec.policy_blind
                           else "event_keyed_policy_preserving")
        ka, kb = set(art_a.get("event_keys") or []), set(
            art_b.get("event_keys") or [])
        common = ka & kb
        b.key_collision_count = int(art_a.get("event_duplicates", 0) +
                                    art_b.get("event_duplicates", 0))
        b.key_uniqueness_ok = b.key_collision_count == 0
        b.ontology_match = (ontology_version_a == ontology_version_b and
                            spec.ontology_drift_b is False)
        values_ok = None
        if art_a.get("marginals_ok") is not None:
            values_ok = (bool(art_a["marginals_ok"]) and
                         bool(art_b["marginals_ok"]))
        b.events_values_equal_matched = values_ok
        b.matched_event_count = len(common)
        b.unmatched_event_count = len(ka ^ kb)
        b.partial_ontology_declared = False
        b.marginals_preserved = values_ok
        b.stream_separation_ok = spec.stream_collision_b is False
    elif spec.independent_seeds_b_delta:
        b.coupling_type = "independent_seeds"
    elif not corrupting or _sync_intact(spec, art_a, art_b):
        b.coupling_type = "stateful_sync"
        fa = [e for e in (art_a.get("draw_log_tail") or [])
              if e.get("stream") in ("model", "dealer")][:8]
        fb = [e for e in (art_b.get("draw_log_tail") or [])
              if e.get("stream") in ("model", "dealer")][:8]
        equal = len(fa) == len(fb) and all(
            x.get("value") == y.get("value") and x.get("kind") == y.get("kind")
            for x, y in zip(fa, fb))
        b.sync_verified_stateful = bool(equal) if (fa and fb) else None
        b.context_desync_of_coupled_stream = (
            True if spec.persistent_state_cross_proc else
            (b.context_instability_coupled_stream if
             b.context_instability_coupled_stream is not None else
             bool(spec.module_cache_contam_b)))
    else:
        b.coupling_type = "stateful_sync"
        b.sync_verified_stateful = False

    b.notes.append(f"construction={spec.construction}")
    b.aa_extras = {"aa_bank_reps_available": aa_bank_reps,
                   "aa_outcome_dispersion_indicator": aa_dispersion_indicator}
    return b


def _sync_intact(spec: ExecutionSpec, art_a: Dict, art_b: Dict) -> bool:
    # think-budget jitter lives on ISOLATED stream => coupled stream intact.
    return spec.think_budget_scale > 0 and not (
        spec.truncate_bits_b or spec.burn_draws_b or spec.queue_tax_a or
        spec.queue_tax_b)


def build_bundle_with_crossproc(bundle: EvidenceBundle,
                                xproc_records: List[Dict],
                                primary_digest_a: str) -> EvidenceBundle:
    ctxs = list(bundle.contexts or []) + [
        {"context_label": r.get("context_label", f"xproc-{r['pid']}"),
         "pid": r["pid"], "digest": r["digest"],
         "primary_digest": primary_digest_a,
         "process_separated": True} for r in xproc_records]
    bundle.contexts = ctxs
    bundle.has_process_separated_replica = True
    bundle.repeats_digests_equal_primary = bundle.repeats_digests_equal_primary
    return bundle
