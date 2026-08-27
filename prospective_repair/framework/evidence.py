"""Evidence schema with separation of concerns + typed per-method views.

Repairs: D-R2 (branch independence), D-R3 (artifact identity), D-R13 (provenance),
randomized_assignment semantics (never implied by seeded draws alone).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from .constants import (UNIT_SEED_CONDITION, MF_HIERARCHICAL, DESIGN_JUSTIFICATIONS)


@dataclass
class ArmIdentity:
    """Per-arm identity: agent/policy/config distinguishable; system layer shared."""
    system: str = ""
    system_version: str = ""
    adapter_version: str = ""
    adapter_hash: str = ""
    agent_id: str = ""            # 'random_policy' | 'conservative_policy' | temperature arm id
    agent_config_hash: str = ""   # hash of policy/temperature/config payload

    def compatible_system_layer(self, other: "ArmIdentity") -> bool:
        return (self.system == other.system
                and self.system_version == other.system_version
                and self.adapter_version == other.adapter_version
                and self.adapter_hash == other.adapter_hash)

    def as_dict(self) -> Dict[str, str]:
        return asdict(self)


@dataclass
class EvidenceBundle:
    """Every field the repaired framework may consult.

    Groups:
      identity / schedule  -> Branch A
      design / unit        -> Branch B   (independent of C/D/E evidence)
      replay               -> Branch C
      coupling             -> Branch D/E (required by B only if model_consumes_sync)
      provenance           -> audit trail
    Outcome VALUES are never present anywhere in this object.
    """
    row_id: str = ""

    # --- Branch A ---
    declared_seed: Optional[int] = None          # arm A declaration
    declared_seed_b: Optional[int] = None        # arm B declaration (may differ
                                                 # when independence declared)
    effective_seed_a: Optional[int] = None
    effective_seed_b: Optional[int] = None
    schedule_fields_match: bool = False
    rows_scheduled: int = 1
    rows_present: int = 1
    row_ids_unique: bool = True
    identity_arm_a: ArmIdentity = field(default_factory=ArmIdentity)
    identity_arm_b: ArmIdentity = field(default_factory=ArmIdentity)
    allowed_differences_declared: bool = False   # e.g. "arms differ only in policy"

    # --- Branch B ---
    design_justifications: List[str] = field(default_factory=list)
    analysis_unit: str = UNIT_SEED_CONDITION
    model_family: str = "none"
    repeat_ids_unique_within_units: bool = True
    repeats_per_unit_pairs: int = 0          # usable paired repeats BOTH arms, ≥0
    within_cluster_variation_present: Optional[bool] = None  # None => unknown
    model_consumes_sync: bool = False        # statistical model itself needs coupling sync
    independent_arms_declared: bool = False
    matched_conditions_intact: bool = True   # truncate/burn/cache/queue/dup/persist corrupt this
    denominator_corrupt: bool = False        # dropped rows or duplicated ids
    paired_realization_complete: bool = True # aliases matched_conditions_intact & !denominator_corrupt

    # --- Branch C ---
    replay_scope_claimed: str = "within_artifact"  # within_artifact|cross_context_inproc|cross_process
    repeats_digests_equal_primary: Optional[bool] = None     # None => unknown/no repeats
    contexts: List[Dict[str, Any]] = field(default_factory=list)
    context_instability_coupled_stream: Optional[bool] = None
    has_process_separated_replica: bool = False

    # --- Branch D ---
    coupling_type: str = "none"
    sync_verified_stateful: Optional[bool] = None
    marginals_preserved: Optional[bool] = None       # keyed paths
    key_uniqueness_ok: Optional[bool] = None
    key_collision_count: int = 0
    stream_separation_ok: Optional[bool] = None
    ontology_match: Optional[bool] = None            # D shares ontology requirement w/ E
    events_values_equal_matched: Optional[bool] = None
    matched_event_count: int = 0
    unmatched_event_count: int = 0                   # keys present in one arm only
    partial_ontology_declared: bool = False
    context_desync_of_coupled_stream: Optional[bool] = None

    # --- provenance ---
    predicate_trace: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    def effective_matches_declared(self) -> bool:
        # per-arm declarations: independent-seed constructions declare distinct
        # B seeds and are judged against THAT declaration.
        ok_a = self.effective_seed_a == self.declared_seed
        declared_b = (self.declared_seed_b
                      if self.declared_seed_b is not None
                      else self.declared_seed)
        ok_b = self.effective_seed_b == declared_b
        return ok_a and ok_b

    def artifact_identity_ok(self) -> bool:
        ok = self.identity_arm_a.compatible_system_layer(self.identity_arm_b)
        if not self.allowed_differences_declared:
            # Without an allowed-differences declaration we additionally require that
            # arms are genuinely distinct at agent level (nothing to compare otherwise).
            ok = ok and self.identity_arm_a.agent_config_hash != ""
            ok = ok and self.identity_arm_b.agent_config_hash != ""
        return ok

    @property
    def pairing_bases(self) -> Dict[str, bool]:
        d = set(self.design_justifications)
        return {
            "matched_assignment": ("randomized_matched_assignment" in d or
                                   "matched_paired_units" in d),
            "repeated_measures": "repeated_measures" in d,
            "hierarchical_model": self.model_family == MF_HIERARCHICAL,
            "defended_joint_model": "defended_joint_stochastic_model" in d,
        }

    def bundle_sha256(self) -> str:
        blob = json.dumps(asdict(self), sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()

    def to_audit_payload(self) -> Dict[str, Any]:
        return {
            "bundle": asdict(self),
            "identity_arm_a": self.identity_arm_a.as_dict(),
            "identity_arm_b": self.identity_arm_b.as_dict(),
            "bundle_sha256": self.bundle_sha256(),
        }


# ---------------------------------------------------------------------------
# Typed capability views (baselines cannot see outside their view by construction)
# ---------------------------------------------------------------------------

VIEW_FIELDS = {
    "B0_schedule_only": ["declared_seed", "effective_seed_a", "effective_seed_b",
                         "schedule_fields_match", "rows_scheduled", "rows_present",
                         "row_ids_unique"],
    "B1_outcome_aa": ["schedule_fields_match", "aa_outcome_dispersion_indicator",
                      "aa_bank_reps_available"],
    "B2_trace_aa": ["replay_scope_claimed", "repeats_digests_equal_primary",
                    "schedule_fields_match"],
    "B3_within_seed_reps": ["repeats_digests_equal_primary",
                            "repeat_ids_unique_within_units", "design_justifications",
                            "analysis_unit", "within_cluster_variation_present"],
    "B4_unpaired_analysis": ["independent_arms_declared", "schedule_fields_match",
                             "denominator_corrupt"],
    "B5_cluster_hierarchical": ["analysis_unit", "model_family",
                                "repeat_ids_unique_within_units",
                                "repeats_per_unit_pairs",
                                "within_cluster_variation_present",
                                "pairing_bases" ],
    "B6_event_keyed_whitebox": ["coupling_type", "ontology_match", "key_uniqueness_ok",
                                "key_collision_count", "marginals_preserved",
                                "stream_separation_ok", "events_values_equal_matched",
                                "matched_event_count", "unmatched_event_count",
                                "partial_ontology_declared", "pairing_bases"],
}


class MethodView:
    """Read-only, capability-filtered projection of an EvidenceBundle."""

    __slots__ = ("_data", "_name")

    def __init__(self, name: str, bundle: "EvidenceBundle",
                 extras: Optional[Dict[str, Any]] = None):
        fields = [f for f in VIEW_FIELDS[name] if f not in
                  ("aa_outcome_dispersion_indicator", "aa_bank_reps_available")]
        out: Dict[str, Any] = {}
        for f in fields:
            if f == "pairing_bases":
                out[f] = dict(bundle.pairing_bases)
            else:
                out[f] = getattr(bundle, f)
        if extras:
            out.update(extras)
        object.__setattr__(self, "_data", out)
        object.__setattr__(self, "_name", name)

    @property
    def view_name(self) -> str:
        return self._name

    def __getattr__(self, item):  # only view fields reachable
        try:
            data = object.__getattribute__(self, "_data")
        except AttributeError:
            raise AttributeError(item)
        if item in data:
            return data[item]
        raise AttributeError(
            f"{object.__getattribute__(self, '_name')} view has no '{item}' "
            "(capability-filtered)")

    def as_dict(self) -> Dict[str, Any]:
        return dict(object.__getattribute__(self, "_data"))
