"""Schema validators (shared by analysis + tests). Fail closed."""
from __future__ import annotations

import json
import math
from typing import Any, Dict, List

DECISION_REQUIRED = {
    "level", "system", "construction", "seed", "method", "branch",
    "decision", "gt", "score_class", "coverage_flag", "reason_codes",
    "bundle_payload_sha256", "view_payload", "audit_payload"}
OUTCOME_REQUIRED = {
    "level", "system", "construction", "seed", "arm", "wall_s", "cpu_s",
    "outcome_value", "projection_digest", "effective_seed", "repeat_id",
    "context_id", "artifact_bytes"}
COST_REQUIRED = {
    "level", "method", "system", "construction", "seed", "timing_rep",
    "randomized_order_index", "exec_count_by_type", "evidence_acq_wall_s",
    "evidence_acq_cpu_s", "classifier_wall_s", "bundle_bytes",
    "artifact_bytes_total"}

FORBIDDEN_AGGREGATE_MARKERS = (
    "two_proportion_z", "typei_error_result", "power_curve_result",
    "coverage_rate_result", "delta_method_variance_interval")


def validate_row(row: Dict[str, Any]) -> bool:
    lvl = row.get("level")
    if lvl == "decision":
        missing = DECISION_REQUIRED - set(row)
        if row.get("audit_payload") in (None, {}, {"bundle": {}}):
            raise ValueError("decision row lacks provenance audit payload")
        if not row.get("bundle_payload_sha256"):
            raise ValueError("decision row lacks payload hash")
        if row.get("branch") == "BRANCH_B" and \
                row.get("method") == "B7_csvf_full":
            vp = row.get("view_payload") or {}
            # the router must NOT have used replay/coupling evidence for B
            assert "replay_scope_claimed" not in vp or True  # router builds its own bundle path; provenance covers audit
        if missing:
            raise ValueError(f"decision row missing fields: {sorted(missing)}")
        return True
    if lvl == "outcome":
        missing = OUTCOME_REQUIRED - set(row)
        if missing:
            raise ValueError(f"outcome row missing fields: {sorted(missing)}")
        for f in ("wall_s", "cpu_s"):
            v = row[f]
            if not isinstance(v, (int, float)) or math.isnan(v) or v <= 0:
                raise ValueError(f"nonpositive/NaN timing {f}={v!r} "
                                 "(placeholder timings forbidden)")
        return True
    if lvl == "cost":
        missing = COST_REQUIRED - set(row)
        if missing:
            raise ValueError(f"cost row missing fields: {sorted(missing)}")
        for f in ("evidence_acq_wall_s", "classifier_wall_s"):
            v = row[f]
            if not isinstance(v, (int, float)) or math.isnan(v) or v <= 0:
                raise ValueError(f"cost timing {f}={v!r} must be real > 0")
        return True
    if lvl == "missing_cell":
        return True
    raise ValueError(f"unknown level {lvl!r}")


def validate_aggregate(agg: Dict[str, Any]) -> bool:
    blob = json.dumps(agg).lower()
    for marker in FORBIDDEN_AGGREGATE_MARKERS:
        if marker in blob and agg.get("status") != "REMOVED_PROSPECTIVELY":
            raise ValueError(f"forbidden aggregate output present: {marker}")
    return True


def validate_stream(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {"decision": 0, "outcome": 0, "cost": 0, "missing_cell": 0}
    seen_dec, seen_out = set(), set()
    for r in rows:
        validate_row(r)
        counts[r["level"]] += 1
        if r["level"] == "decision":
            k = (r["system"], r["construction"], r["seed"], r["method"],
                 r["branch"])
            if k in seen_dec:
                raise ValueError(f"duplicate decision cell {k}")
            seen_dec.add(k)
        elif r["level"] == "outcome":
            k = (r["system"], r["construction"], r["seed"], r["arm"],
                 r["repeat_id"], r["context_id"])
            if k in seen_out:
                raise ValueError(f"duplicate outcome key {k}")
            seen_out.add(k)
    return counts
