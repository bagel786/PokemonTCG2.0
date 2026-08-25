#!/usr/bin/env python3
"""Build PEVL manuscript figures and LaTeX tables from validated summaries.

This script does not run experiments or analyses. Figures 4 and 5 and the
factorial table are conditional: absent, incomplete, suppressed, or internally
inconsistent summaries cannot create manuscript-ready outputs.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Patch


SCRIPT_PATH = Path(__file__).resolve()
SCRIPT_CONTAINER = SCRIPT_PATH.parents[1]
RELEASE_LAYOUT = (SCRIPT_CONTAINER / "data/processed").is_dir()
if RELEASE_LAYOUT:
    ROOT = SCRIPT_CONTAINER
    DEFAULT_SYNTHETIC = ROOT / "synthetic/results/pevl_results.json"
    DEFAULT_HISTORICAL = ROOT / "data/processed/ablation_summary.json"
    DEFAULT_PREFLIGHT = ROOT / "data/processed/pevl_trace_preflight_summary.json"
    DEFAULT_STRESS = ROOT / "data/processed/pevl_timed_search_stress_summary.json"
    DEFAULT_FACTORIAL = ROOT / "data/processed/pevl_factorial_summary.json"
    DEFAULT_COMBINED = ROOT / "data/processed/pevl_summary.json"
    DEFAULT_FIGURES = ROOT / "figures"
    DEFAULT_TABLES = ROOT / "generated/tables"
else:
    ROOT = SCRIPT_PATH.parents[2]
    DEFAULT_SYNTHETIC = ROOT / "paper/synthetic/results/pevl_results.json"
    DEFAULT_HISTORICAL = ROOT / "paper/data/ablation/summary.json"
    DEFAULT_PREFLIGHT = ROOT / "paper/data/pevl/trace_preflight_summary.json"
    DEFAULT_STRESS = ROOT / "paper/data/pevl/timed_search_stress_summary.json"
    DEFAULT_FACTORIAL = ROOT / "paper/data/pevl/factorial_summary.json"
    DEFAULT_COMBINED = ROOT / "paper/data/pevl/summary.json"
    DEFAULT_FIGURES = ROOT / "paper/figures"
    DEFAULT_TABLES = ROOT / "paper/tables"

FIGURE_STEMS = {
    "ladder": "fig_pevl_01_ladder",
    "synthetic": "fig_pevl_02_synthetic",
    "historical": "fig_pevl_03_historical_parity",
    "stress": "fig_pevl_04_stress",
    "factorial": "fig_pevl_05_factorial",
}
TABLE_NAMES = {
    "ladder": "pevl_ladder.tex",
    "retrospective": "pevl_retrospective_audit.tex",
    "prospective": "pevl_prospective_audit.tex",
    "factorial": "pevl_factorial.tex",
}

INK = "#1F2933"
MUTED = "#5F6B75"
GRID = "#D9E0E5"
BLUE = "#466F8A"
GREEN = "#4D7A68"
ORANGE = "#B57A35"
RED = "#9A4F4F"
PURPLE = "#6F638B"

LEVEL_DETAILS = {
    1: (
        "Artifact identity",
        "Evaluated bytes and configuration are identifiable",
        "Quarantine hash or configuration drift",
    ),
    2: (
        "Seed-namespace integrity",
        "Scheduled values and values passed at the engine boundary are distinct as planned",
        "Correct the namespace and rerun",
    ),
    3: (
        "Schedule parity",
        "The study attempted the declared matched schedule",
        "Reject incomplete or unequal pairs",
    ),
    4: (
        "Identical-arm record parity",
        "Compared fields repeat on tested A/A trajectories",
        "Suppress the affected paired contrast",
    ),
    5: (
        "Repeat and worker parity",
        "Within-arm traces repeat in tested execution contexts",
        "Freeze a validated context or model run variation",
    ),
    6: (
        "Stochastic-source audit",
        "Audit completeness and source disposition are recorded separately",
        "Control residual sources, bound claims, or redesign if the estimand changes",
    ),
    7: (
        "Cross-arm event alignment",
        "Shared logged events receive the same random quantities",
        "Do not use event-aligned or counterfactual wording",
    ),
    8: (
        "Statistical admission",
        "The prespecified rule admits only the supported claim class",
        "Admit, downgrade, or suppress the contrast",
    ),
}

EXPECTED_LEVEL_NAMES = {
    1: "artifact_identity",
    2: "seed_namespace_integrity",
    3: "schedule_parity",
    4: "identical_arm_record_parity",
    5: "repeat_and_worker_parity",
    6: "stochastic_source_audit",
    7: "cross_arm_event_alignment",
    8: "statistical_admission",
}
EXPECTED_SYNTHETIC_MODES = {
    "clean_deterministic",
    "stateful_draw_shift",
    "wall_clock_search",
    "process_global_state",
    "uint32_seed_conversion",
}
EXPECTED_FACTORIAL_CONTRASTS = {
    "primary_c4_minus_c1",
    "representation_main",
    "training_main",
    "interaction",
}
NONADMITTED_FACTORIAL_STATUSES = {
    "INCOMPLETE",
    "NOT_RUN",
    "SUPPRESSED_BY_PREFLIGHT",
    "SUPPRESSED_CONTROL_PARITY_FAILURE",
}
NONRENDERABLE_STRESS_STATUSES = {"INCOMPLETE", "NOT_RUN"}
PENDING_PREFLIGHT_STATUSES = {"INCOMPLETE", "NOT_RUN"}
EXPECTED_STRESS_STRATA = {
    "starmie/first",
    "starmie/second",
    "dipplin/first",
    "dipplin/second",
}
EXPECTED_PREFLIGHT_OPPONENTS = (
    {"Matched1", "Matched2", "Matched3", "Matched4", "Broader3"}
    if RELEASE_LAYOUT
    else {"b0", "d842", "master", "replay", "alakazam_no_search"}
)

OPPONENT_ORDER = (
    "B0",
    "d842_runtime",
    "master_v1",
    "replay_refresh",
    "starmie",
    "dipplin",
    "alakazam_no_search",
)
OPPONENT_LABELS = {
    "B0": "B0",
    "d842_runtime": "d842-runtime",
    "master_v1": "master-v1",
    "replay_refresh": "replay-refresh",
    "starmie": "Starmie",
    "dipplin": "Dipplin",
    "alakazam_no_search": "Alakazam (no search)",
}
MODE_LABELS = {
    "clean_deterministic": "Clean deterministic",
    "stateful_draw_shift": "Stateful draw shift",
    "wall_clock_search": "Wall-clock search",
    "process_global_state": "Process-global state",
    "uint32_seed_conversion": "uint32 conversion",
}
CONTRAST_LABELS = {
    "primary_c4_minus_c1": "Total intervention: C4 - C1",
    "representation_main": "Fixed-package representation contrast",
    "training_main": "Fixed-package training contrast",
    "interaction": "Fixed-package interaction contrast",
}


class ArtifactInputError(ValueError):
    """Raised when a machine-readable input cannot support an artifact."""


def reject_json_constant(value: str) -> None:
    raise ArtifactInputError(f"non-finite JSON constant prohibited: {value}")


def load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise ArtifactInputError(f"required {label} input is missing: {path}")
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=reject_json_constant,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactInputError(f"cannot read {label} input {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ArtifactInputError(f"{label} input must be a JSON object: {path}")
    return payload


def optional_json(path: Path, label: str) -> dict[str, Any] | None:
    if not path.exists() and not path.is_symlink():
        return None
    return load_json(path, label)


def require_analysis_header(
    payload: Mapping[str, Any], analysis_id: str
) -> None:
    if payload.get("schema_version") != 1:
        raise ArtifactInputError(
            f"{analysis_id} summary must use schema_version 1"
        )
    if payload.get("analysis_id") != analysis_id:
        raise ArtifactInputError(
            f"expected {analysis_id} summary, got "
            f"{payload.get('analysis_id')!r}"
        )


def ensure_regular_target(path: Path) -> None:
    """Reject special files and symlinks before overwriting outputs."""

    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise RuntimeError(
            f"refusing to overwrite non-regular generated target: {path}"
        )


def require_bool(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise ArtifactInputError(f"{label} must be boolean")
    return value


def require_int(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ArtifactInputError(f"{label} must be an integer >= {minimum}")
    return value


def require_probability(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ArtifactInputError(f"{label} must be numeric")
    result = float(value)
    if not 0.0 <= result <= 1.0:
        raise ArtifactInputError(f"{label} must be in [0, 1]")
    return result


def validate_interval(value: Any, label: str) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ArtifactInputError(f"{label} must be a two-value list")
    low = require_probability(value[0], f"{label}[0]")
    high = require_probability(value[1], f"{label}[1]")
    if low > high:
        raise ArtifactInputError(f"{label} is reversed")
    return low, high


def validate_effect_interval(value: Any, label: str) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ArtifactInputError(f"{label} must be a two-value list")
    if any(
        isinstance(item, bool) or not isinstance(item, (int, float))
        for item in value
    ):
        raise ArtifactInputError(f"{label} values must be numeric")
    low, high = (float(item) for item in value)
    if not all(math.isfinite(item) and -1.0 <= item <= 1.0 for item in (low, high)):
        raise ArtifactInputError(f"{label} values must be finite and in [-1, 1]")
    if low > high:
        raise ArtifactInputError(f"{label} is reversed")
    return low, high


def validate_synthetic(
    payload: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    levels = payload.get("levels")
    modes = payload.get("modes")
    if payload.get("framework") != "Paired Evaluation Validity Ladder":
        raise ArtifactInputError("synthetic framework name mismatch")
    if not isinstance(levels, list) or len(levels) != 8:
        raise ArtifactInputError("synthetic input must contain exactly eight levels")
    observed_levels = {
        row.get("level"): row.get("level_name")
        for row in levels
        if isinstance(row, dict)
    }
    if observed_levels != EXPECTED_LEVEL_NAMES:
        raise ArtifactInputError("synthetic level definitions do not match PEVL")
    if not isinstance(modes, list):
        raise ArtifactInputError("synthetic modes must be a list")
    by_mode: dict[str, dict[str, Any]] = {}
    for mode in modes:
        if not isinstance(mode, dict) or not isinstance(mode.get("mode"), str):
            raise ArtifactInputError(
                "every synthetic mode must be an identified object"
            )
        name = mode["mode"]
        if name in by_mode:
            raise ArtifactInputError(f"duplicate synthetic mode: {name}")
        audit = mode.get("audit")
        if (
            not isinstance(audit, list)
            or any(not isinstance(row, dict) for row in audit)
            or [row.get("level") for row in audit]
            != list(range(1, 9))
        ):
            raise ArtifactInputError(
                f"{name}: audit must contain ordered levels 1--8"
            )
        for row in audit:
            if (
                row["level"] < 8
                and row.get("status") not in {"pass", "fail", "blocked"}
            ):
                raise ArtifactInputError(
                    f"{name}: invalid evidence-gate status"
                )
            if (
                row["level"] == 8
                and row.get("status")
                not in {"admit", "downgrade", "suppress"}
            ):
                raise ArtifactInputError(f"{name}: invalid admission status")
        by_mode[name] = mode
    if set(by_mode) != EXPECTED_SYNTHETIC_MODES:
        raise ArtifactInputError(
            "synthetic mode set is incomplete or unexpected"
        )
    return by_mode


def validate_historical(payload: Mapping[str, Any]) -> dict[str, Any]:
    if (
        payload.get("status") != "INVALIDATED"
        or payload.get("schema_version") != 2
    ):
        raise ArtifactInputError(
            "historical audit must preserve invalidated schema-2 status"
        )
    audit = payload.get("control_parity_audit")
    if not isinstance(audit, dict):
        raise ArtifactInputError(
            "historical control_parity_audit is missing"
        )
    total = require_int(audit.get("pairs"), "historical pairs", minimum=1)
    outcome_total = require_int(
        audit.get("outcome_record_mismatch_units"),
        "historical outcome mismatches",
    )
    serialized_total = require_int(
        audit.get("serialized_record_mismatch_units"),
        "historical serialized mismatches",
    )
    if not 0 <= outcome_total <= serialized_total <= total:
        raise ArtifactInputError(
            "historical mismatch totals are inconsistent"
        )
    by_opponent = audit.get("by_opponent")
    if (
        not isinstance(by_opponent, dict)
        or set(by_opponent) != set(OPPONENT_ORDER)
    ):
        raise ArtifactInputError(
            "historical opponent audit set is incomplete"
        )
    pair_sum = outcome_sum = serialized_sum = 0
    for opponent in OPPONENT_ORDER:
        row = by_opponent[opponent]
        if not isinstance(row, dict):
            raise ArtifactInputError(
                f"historical {opponent} row must be an object"
            )
        pairs = require_int(
            row.get("pairs"), f"{opponent} pairs", minimum=1
        )
        outcome = require_int(
            row.get("any_outcome_record_mismatch_units"),
            f"{opponent} outcome mismatches",
        )
        serialized = require_int(
            row.get("any_serialized_record_mismatch_units"),
            f"{opponent} serialized mismatches",
        )
        if not 0 <= outcome <= serialized <= pairs:
            raise ArtifactInputError(
                f"{opponent} mismatch counts are inconsistent"
            )
        pair_sum += pairs
        outcome_sum += outcome
        serialized_sum += serialized
    if (pair_sum, outcome_sum, serialized_sum) != (
        total,
        outcome_total,
        serialized_total,
    ):
        raise ArtifactInputError(
            "historical opponent rows do not reproduce totals"
        )
    cause = payload.get("cause_audit")
    if (
        not isinstance(cause, dict)
        or not {"starmie", "dipplin"} <= set(cause)
    ):
        raise ArtifactInputError(
            "historical timed-search source audit is incomplete"
        )
    return audit


def validate_preflight(
    payload: Mapping[str, Any],
) -> dict[str, Any] | None:
    require_analysis_header(payload, "trace_preflight")
    status = payload.get("status")
    if status in PENDING_PREFLIGHT_STATUSES:
        if payload.get("admission_decision") != "suppress":
            raise ArtifactInputError(
                "pending trace preflight must suppress acquisition"
            )
        return None
    if status not in {"PASS", "FAIL"}:
        raise ArtifactInputError(
            f"unrecognized trace-preflight status: {status!r}"
        )
    expected_decision = (
        "admit_factorial_acquisition"
        if status == "PASS"
        else "suppress_factorial"
    )
    if payload.get("admission_decision") != expected_decision:
        raise ArtifactInputError(
            "trace-preflight status and admission decision conflict"
        )
    arms = require_int(
        payload.get("arms"), "preflight arms", minimum=1
    )
    opponents = require_int(
        payload.get("opponents"),
        "preflight opponents",
        minimum=1,
    )
    if arms != 4 or opponents != len(EXPECTED_PREFLIGHT_OPPONENTS):
        raise ArtifactInputError(
            "trace preflight must cover four arms and the five "
            "frozen opponents"
        )
    rows = payload.get("rows")
    if (
        not isinstance(rows, list)
        or len(rows) != arms * opponents
    ):
        raise ArtifactInputError(
            "trace-preflight row inventory is incomplete"
        )
    endpoint_fields = {
        "trace": "trace_mismatch_units",
        "outcome": "outcome_mismatch_units",
        "error": "error_mismatch_units",
        "decision": "decision_count_mismatch_units",
    }
    identities: set[tuple[str, str]] = set()
    unit_sum = execution_sum = mismatch_sum = 0
    endpoint_sums = {name: 0 for name in endpoint_fields}
    per_arm = {
        arm: {
            "units": 0,
            "executions": 0,
            "mismatches": 0,
            **{name: 0 for name in endpoint_fields},
        }
        for arm in ("C1", "C2", "C3", "C4")
    }
    for row in rows:
        if not isinstance(row, dict):
            raise ArtifactInputError(
                "trace-preflight rows must be objects"
            )
        arm = row.get("arm")
        opponent = row.get("opponent")
        if (
            arm not in {"C1", "C2", "C3", "C4"}
            or not isinstance(opponent, str)
        ):
            raise ArtifactInputError(
                "trace-preflight row has an invalid arm or opponent"
            )
        passed = require_bool(
            row.get("passed"),
            f"trace-preflight {arm}/{opponent} passed",
        )
        mismatches = require_int(
            row.get("mismatch_units"),
            f"trace-preflight {arm}/{opponent} mismatches",
        )
        endpoint_counts = {
            name: require_int(
                row.get(field),
                f"trace-preflight {arm}/{opponent} {field}",
            )
            for name, field in endpoint_fields.items()
        }
        if any(value > mismatches for value in endpoint_counts.values()):
            raise ArtifactInputError(
                f"trace-preflight {arm}/{opponent} endpoint mismatches "
                "exceed aggregate mismatches"
            )
        units = require_int(
            row.get("trajectory_units"),
            f"trace-preflight {arm}/{opponent} units",
            minimum=1,
        )
        executions = require_int(
            row.get("executions"),
            f"trace-preflight {arm}/{opponent} executions",
            minimum=1,
        )
        if units != 50 or executions != 150:
            raise ArtifactInputError(
                f"trace-preflight {arm}/{opponent} does not match "
                "the frozen 50-unit, 150-execution cell"
            )
        key = (arm, opponent)
        if key in identities:
            raise ArtifactInputError(
                f"duplicate trace-preflight row: {arm}/{opponent}"
            )
        identities.add(key)
        mismatch_sum += mismatches
        unit_sum += units
        execution_sum += executions
        per_arm[arm]["units"] += units
        per_arm[arm]["executions"] += executions
        per_arm[arm]["mismatches"] += mismatches
        for name, count in endpoint_counts.items():
            endpoint_sums[name] += count
            per_arm[arm][name] += count
        if status == "PASS" and (not passed or mismatches):
            raise ArtifactInputError(
                f"PASS trace preflight has a failed row: "
                f"{arm}/{opponent}"
            )
    expected_identities = {
        (arm, opponent)
        for arm in ("C1", "C2", "C3", "C4")
        for opponent in EXPECTED_PREFLIGHT_OPPONENTS
    }
    if identities != expected_identities:
        raise ArtifactInputError(
            "trace-preflight arm/opponent coverage is not the "
            "frozen four-by-five design"
        )
    total_units = require_int(
        payload.get("trajectory_units"),
        "preflight trajectory_units",
        minimum=1,
    )
    total_executions = require_int(
        payload.get("executions"),
        "preflight executions",
        minimum=1,
    )
    total_mismatches = require_int(
        payload.get("mismatch_units"),
        "preflight mismatch_units",
    )
    reported_endpoint_totals = {
        name: require_int(payload.get(field), f"preflight {field}")
        for name, field in endpoint_fields.items()
    }
    if (
        unit_sum,
        execution_sum,
        mismatch_sum,
    ) != (
        total_units,
        total_executions,
        total_mismatches,
    ):
        raise ArtifactInputError(
            "trace-preflight rows do not reproduce summary totals"
        )
    if reported_endpoint_totals != endpoint_sums:
        raise ArtifactInputError(
            "trace-preflight rows do not reproduce endpoint totals"
        )
    if status == "PASS" and total_mismatches != 0:
        raise ArtifactInputError(
            "PASS trace preflight contains mismatch units"
        )
    protocol_commit = payload.get("protocol_commit")
    claim_boundary = payload.get("claim_boundary")
    if not isinstance(protocol_commit, str) or not protocol_commit.strip():
        raise ArtifactInputError(
            "complete trace preflight lacks a protocol commit"
        )
    if not isinstance(claim_boundary, str) or not claim_boundary.strip():
        raise ArtifactInputError(
            "complete trace preflight lacks a claim boundary"
        )
    return {
        "status": status,
        "opponents": opponents,
        "per_arm": per_arm,
        "rows": rows,
        "totals": {
            "units": total_units,
            "executions": total_executions,
            "mismatches": total_mismatches,
            **endpoint_sums,
        },
    }


def validate_stress(
    payload: Mapping[str, Any],
) -> dict[str, Any] | None:
    require_analysis_header(payload, "timed_search_stress")
    status = payload.get("status")
    if status in NONRENDERABLE_STRESS_STATUSES:
        return None
    if status not in {"TRACE_DIVERGENCE", "TRACE_PARITY"}:
        raise ArtifactInputError(
            f"unrecognized stress status: {status!r}"
        )
    clusters = require_int(
        payload.get("clusters"), "stress clusters", minimum=1
    )
    if clusters != 200:
        raise ArtifactInputError(
            "stress summary does not match the frozen 200-cluster design"
        )
    executions = require_int(
        payload.get("executions"),
        "stress executions",
        minimum=clusters,
    )
    if executions != clusters * 4:
        raise ArtifactInputError(
            "stress summary must contain four executions per cluster"
        )
    disagreement_count = require_int(
        payload.get("trace_disagreement_clusters"),
        "stress trace disagreement clusters",
    )
    if disagreement_count > clusters:
        raise ArtifactInputError(
            "stress disagreement count exceeds clusters"
        )
    if (status == "TRACE_DIVERGENCE") != (disagreement_count > 0):
        raise ArtifactInputError(
            "stress status conflicts with trace-disagreement count"
        )
    secondary_fields = (
        "outcome_disagreement_clusters",
        "decision_count_disagreement_clusters",
        "error_disagreement_clusters",
        "policy_error_present_clusters",
    )
    secondary_totals = {
        field: require_int(
            payload.get(field), f"stress {field}"
        )
        for field in secondary_fields
    }
    if any(value > clusters for value in secondary_totals.values()):
        raise ArtifactInputError(
            "stress secondary disagreement count exceeds clusters"
        )
    overall = payload.get("trace_disagreement")
    if not isinstance(overall, dict):
        raise ArtifactInputError(
            "stress trace_disagreement summary is missing"
        )
    estimate = require_probability(
        overall.get("estimate"), "stress overall estimate"
    )
    if require_int(
        overall.get("clusters"), "stress overall bootstrap clusters"
    ) != clusters:
        raise ArtifactInputError(
            "stress bootstrap cluster count conflicts with summary"
        )
    interval = validate_interval(
        overall.get("bootstrap_95_ci"), "stress overall CI"
    )
    if not interval[0] <= estimate <= interval[1]:
        raise ArtifactInputError(
            "stress overall estimate falls outside its interval"
        )
    if abs(estimate * clusters - disagreement_count) > 1e-6:
        raise ArtifactInputError(
            "stress estimate does not reproduce disagreement count"
        )
    strata = payload.get("strata")
    if (
        not isinstance(strata, dict)
        or set(strata) != EXPECTED_STRESS_STRATA
    ):
        raise ArtifactInputError(
            "stress summary must contain the four frozen strata"
        )
    stratum_cluster_sum = 0
    stratum_disagreement_sum = 0
    stratum_secondary_sums = {
        field: 0 for field in secondary_fields
    }
    for name, row in strata.items():
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("trace_disagreement"), dict)
        ):
            raise ArtifactInputError(
                f"stress stratum {name} is malformed"
            )
        summary = row["trace_disagreement"]
        estimate = require_probability(
            summary.get("estimate"), f"stress {name} estimate"
        )
        low, high = validate_interval(
            summary.get("bootstrap_95_ci"),
            f"stress {name} CI",
        )
        clusters_in_stratum = require_int(
            summary.get("clusters"),
            f"stress {name} clusters",
            minimum=1,
        )
        if not low <= estimate <= high:
            raise ArtifactInputError(
                f"stress {name} estimate falls outside its CI"
            )
        if clusters_in_stratum > clusters:
            raise ArtifactInputError(
                f"stress {name} clusters exceed overall total"
            )
        if clusters_in_stratum != 50:
            raise ArtifactInputError(
                f"stress {name} does not contain 50 frozen clusters"
            )
        implied_disagreements = estimate * clusters_in_stratum
        rounded_disagreements = round(implied_disagreements)
        if abs(implied_disagreements - rounded_disagreements) > 1e-8:
            raise ArtifactInputError(
                f"stress {name} estimate does not imply an integer count"
            )
        stratum_cluster_sum += clusters_in_stratum
        stratum_disagreement_sum += rounded_disagreements
        stratum_field_map = {
            "outcome_disagreement_clusters": (
                "outcome_disagreement_count"
            ),
            "decision_count_disagreement_clusters": (
                "decision_count_disagreement_count"
            ),
            "error_disagreement_clusters": (
                "error_disagreement_count"
            ),
            "policy_error_present_clusters": (
                "policy_error_present_count"
            ),
        }
        for overall_field, stratum_field in stratum_field_map.items():
            value = require_int(
                row.get(stratum_field),
                f"stress {name} {stratum_field}",
            )
            if value > clusters_in_stratum:
                raise ArtifactInputError(
                    f"stress {name} {stratum_field} exceeds clusters"
                )
            stratum_secondary_sums[overall_field] += value
    if stratum_cluster_sum != clusters:
        raise ArtifactInputError(
            "stress strata do not reproduce the overall cluster count"
        )
    if stratum_disagreement_sum != disagreement_count:
        raise ArtifactInputError(
            "stress strata do not reproduce trace disagreements"
        )
    if stratum_secondary_sums != secondary_totals:
        raise ArtifactInputError(
            "stress strata do not reproduce secondary counts"
        )
    return dict(payload)


def validate_factorial(
    payload: Mapping[str, Any],
) -> dict[str, Any] | None:
    require_analysis_header(payload, "factorial")
    status = payload.get("status")
    decision = payload.get("admission_decision")
    if status in NONADMITTED_FACTORIAL_STATUSES:
        if isinstance(decision, str) and decision.startswith("admit"):
            raise ArtifactInputError(
                "suppressed factorial carries an admitted decision"
            )
        return None
    if (
        status != "ADMITTED_SEED_MATCHED"
        or decision != "admit_with_bounded_wording"
    ):
        raise ArtifactInputError(
            "factorial branch is unresolved: "
            f"status={status!r}, decision={decision!r}"
        )
    if (
        require_int(
            payload.get("control_mismatch_units"),
            "factorial control mismatches",
        )
        != 0
    ):
        raise ArtifactInputError(
            "admitted factorial contains control mismatches"
        )
    units = require_int(
        payload.get("units"), "factorial units", minimum=1
    )
    games = require_int(
        payload.get("games"), "factorial games", minimum=1
    )
    if units != 2_000 or games != 12_000 or games != units * 6:
        raise ArtifactInputError(
            "admitted factorial does not match the frozen "
            "2,000-unit, 12,000-game schedule"
        )
    cell_win_rates = payload.get("cell_win_rates")
    if (
        not isinstance(cell_win_rates, dict)
        or set(cell_win_rates) != {"C1", "C2", "C3", "C4"}
    ):
        raise ArtifactInputError(
            "admitted factorial cell win-rate set is incomplete"
        )
    rates = {
        cell: require_probability(rate, f"factorial {cell} win rate")
        for cell, rate in cell_win_rates.items()
    }
    expected_estimates = {
        "primary_c4_minus_c1": rates["C4"] - rates["C1"],
        "representation_main": 0.5
        * ((rates["C2"] - rates["C1"]) + (rates["C4"] - rates["C3"])),
        "training_main": 0.5
        * ((rates["C3"] - rates["C1"]) + (rates["C4"] - rates["C2"])),
        "interaction": rates["C4"] - rates["C3"] - rates["C2"] + rates["C1"],
    }
    contrasts = payload.get("contrasts")
    if (
        not isinstance(contrasts, dict)
        or set(contrasts) != EXPECTED_FACTORIAL_CONTRASTS
    ):
        raise ArtifactInputError(
            "admitted factorial contrast set is incomplete"
        )
    for name, row in contrasts.items():
        if not isinstance(row, dict):
            raise ArtifactInputError(
                f"factorial contrast {name} must be an object"
            )
        estimate = row.get("estimate")
        if isinstance(estimate, bool) or not isinstance(estimate, (int, float)):
            raise ArtifactInputError(
                f"factorial {name} estimate must be numeric"
            )
        estimate_value = float(estimate)
        if not math.isfinite(estimate_value) or not -1.0 <= estimate_value <= 1.0:
            raise ArtifactInputError(
                f"factorial {name} estimate must be finite and in [-1, 1]"
            )
        if not math.isclose(
            estimate_value,
            expected_estimates[name],
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ArtifactInputError(
                f"factorial {name} estimate does not reproduce the cell win rates"
            )
        low, high = validate_effect_interval(
            row.get("bootstrap_95_ci"),
            f"factorial {name} CI",
        )
        if not low <= estimate_value <= high:
            raise ArtifactInputError(
                f"factorial {name} estimate falls outside its CI"
            )
        if (
            require_int(
                row.get("bootstrap_draws"),
                f"factorial {name} bootstrap draws",
                minimum=1,
            )
            != 100_000
            or require_int(
                row.get("bootstrap_seed"),
                f"factorial {name} bootstrap seed",
            )
            != 2026083117
            or row.get("resampling")
            != "paired units within each of ten opponent-by-order strata"
        ):
            raise ArtifactInputError(
                f"factorial {name} bootstrap settings differ from the frozen design"
            )
    target = payload.get("target_population")
    if not isinstance(target, str) or not target.strip():
        raise ArtifactInputError(
            "admitted factorial target population is missing"
        )
    return dict(payload)


def validate_combined(
    payload: Mapping[str, Any],
    *,
    historical: Mapping[str, Any],
    preflight: Mapping[str, Any] | None,
    stress: Mapping[str, Any] | None,
    factorial: Mapping[str, Any] | None,
) -> None:
    """Require the analyzer's combined record to match split summaries."""

    if payload.get("schema_version") != 1:
        raise ArtifactInputError(
            "combined PEVL summary must use schema_version 1"
        )
    if payload.get("framework") != "Paired Evaluation Validity Ladder":
        raise ArtifactInputError("combined PEVL framework name mismatch")
    if payload.get("protocol") != (
        "paper/protocol/PEVL_PROSPECTIVE_PROTOCOL.md"
    ):
        raise ArtifactInputError("combined PEVL protocol path mismatch")
    components = {
        "prospective_trace_preflight": preflight,
        "timed_search_stress": stress,
        "gated_factorial": factorial,
    }
    for key, component in components.items():
        if component is None:
            raise ArtifactInputError(
                f"combined PEVL summary exists without split {key} input"
            )
        if payload.get(key) != component:
            raise ArtifactInputError(
                f"combined PEVL component does not match {key} input"
            )
    historical_record = payload.get("historical_control_parity")
    audit = historical.get("control_parity_audit")
    if not isinstance(historical_record, dict) or not isinstance(audit, dict):
        raise ArtifactInputError(
            "combined historical control-parity record is missing"
        )
    expected_historical_fields = {
        "status": historical.get("status"),
        "units": audit.get("pairs"),
        "outcome_record_mismatch_units": audit.get(
            "outcome_record_mismatch_units"
        ),
        "serialized_record_mismatch_units": audit.get(
            "serialized_record_mismatch_units"
        ),
        "by_opponent": audit.get("by_opponent"),
        "cause_audit": historical.get("cause_audit"),
    }
    for key, expected in expected_historical_fields.items():
        if historical_record.get(key) != expected:
            raise ArtifactInputError(
                "combined historical control-parity record conflicts "
                f"with source field {key}"
            )
    claim_boundary = payload.get("claim_boundary")
    if not isinstance(claim_boundary, str) or not claim_boundary.strip():
        raise ArtifactInputError(
            "combined PEVL claim boundary is missing"
        )


def setup_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 8,
            "axes.titlesize": 10,
            "axes.labelsize": 8,
            "axes.edgecolor": MUTED,
            "axes.linewidth": 0.7,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "legend.fontsize": 7,
            "xtick.labelsize": 7,
            "ytick.labelsize": 7,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "savefig.facecolor": "white",
        }
    )


def save_figure(
    fig: plt.Figure, output_dir: Path, stem: str
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    fixed_time = datetime(2026, 8, 24, tzinfo=timezone.utc)
    pdf = output_dir / f"{stem}.pdf"
    png = output_dir / f"{stem}.png"
    ensure_regular_target(pdf)
    ensure_regular_target(png)
    fig.savefig(
        pdf,
        bbox_inches="tight",
        pad_inches=0.06,
        metadata={
            "Title": stem,
            "Creator": "paper/scripts/build_pevl_artifacts.py",
            "CreationDate": fixed_time,
            "ModDate": fixed_time,
        },
    )
    fig.savefig(
        png,
        dpi=300,
        bbox_inches="tight",
        pad_inches=0.06,
        metadata={
            "Software": "paper/scripts/build_pevl_artifacts.py"
        },
    )
    plt.close(fig)
    if pdf.stat().st_size < 1_000 or png.stat().st_size < 1_000:
        raise RuntimeError(
            f"generated figure is unexpectedly small: {stem}"
        )
    return [pdf, png]


def figure_ladder(
    levels: Sequence[Mapping[str, Any]], output_dir: Path
) -> list[Path]:
    fig, ax = plt.subplots(figsize=(7.1, 4.8))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    fig.subplots_adjust(
        left=0.02, right=0.98, top=0.93, bottom=0.04
    )
    ax.text(
        0.01,
        0.98,
        "Paired Evaluation Validity Ladder",
        ha="left",
        va="top",
        fontsize=12,
        fontweight="bold",
        color=INK,
    )
    ax.text(
        0.99,
        0.98,
        "same schedule  !=  reproducible execution  "
        "!=  event-aligned coupling",
        ha="right",
        va="top",
        fontsize=7.3,
        color=MUTED,
    )
    colors = [
        BLUE,
        BLUE,
        BLUE,
        PURPLE,
        PURPLE,
        PURPLE,
        GREEN,
        ORANGE,
    ]
    for index, level_row in enumerate(levels):
        level = int(level_row["level"])
        title, admitted, _response = LEVEL_DETAILS[level]
        y = 0.83 - index * 0.103
        x = 0.04 + index * 0.018
        width = 0.66 - index * 0.018
        patch = FancyBboxPatch(
            (x, y),
            width,
            0.075,
            boxstyle=(
                "round,pad=0.008,rounding_size=0.008"
            ),
            facecolor="white",
            edgecolor=colors[index],
            linewidth=1.2,
        )
        ax.add_patch(patch)
        ax.text(
            x + 0.018,
            y + 0.038,
            f"L{level}",
            ha="left",
            va="center",
            color=colors[index],
            fontweight="bold",
        )
        ax.text(
            x + 0.075,
            y + 0.050,
            title,
            ha="left",
            va="center",
            color=INK,
            fontweight="bold",
            fontsize=7.6,
        )
        ax.text(
            x + 0.075,
            y + 0.024,
            admitted,
            ha="left",
            va="center",
            color=MUTED,
            fontsize=6.6,
        )
    claim_rows = [
        (
            0.695,
            0.742,
            "L1-L3",
            "Matched schedule\nattempt documented",
            BLUE,
        ),
        (
            0.725,
            0.432,
            "L1-L6",
            "Bounded seed-matched\nclaim may be eligible",
            PURPLE,
        ),
        (
            0.755,
            0.226,
            "L1-L7",
            "Event-aligned claim\nwithin logged boundary",
            GREEN,
        ),
        (
            0.785,
            0.080,
            "L8",
            "Admit / downgrade /\nsuppress",
            ORANGE,
        ),
    ]
    for x, y, prefix, text, color in claim_rows:
        ax.add_patch(
            FancyArrowPatch(
                (x - 0.03, y + 0.035),
                (x, y + 0.035),
                arrowstyle="-|>",
                mutation_scale=8,
                linewidth=0.9,
                color=color,
            )
        )
        ax.text(
            x + 0.012,
            y + 0.052,
            prefix,
            color=color,
            fontweight="bold",
            fontsize=7.2,
            va="center",
        )
        ax.text(
            x + 0.012,
            y + 0.020,
            text,
            color=INK,
            fontsize=6.8,
            va="center",
            linespacing=1.1,
        )
    ax.text(
        0.01,
        0.012,
        "Levels 1-7 are cumulative evidence gates. Level 8 is a "
        "prespecified claim-admission decision, not evidence that "
        "repairs a failed gate.",
        ha="left",
        va="bottom",
        fontsize=6.6,
        color=MUTED,
    )
    return save_figure(
        fig, output_dir, FIGURE_STEMS["ladder"]
    )


def figure_synthetic(
    by_mode: Mapping[str, Mapping[str, Any]],
    output_dir: Path,
) -> list[Path]:
    mode_order = [
        "clean_deterministic",
        "stateful_draw_shift",
        "wall_clock_search",
        "process_global_state",
        "uint32_seed_conversion",
    ]
    status_codes = {
        "fail": 0,
        "suppress": 0,
        "blocked": 1,
        "downgrade": 2,
        "pass": 3,
        "admit": 4,
    }
    status_labels = {
        "fail": "F",
        "suppress": "S",
        "blocked": "-",
        "downgrade": "D",
        "pass": "P",
        "admit": "A",
    }
    matrix = [
        [
            status_codes[row["status"]]
            for row in by_mode[mode]["audit"]
        ]
        for mode in mode_order
    ]
    fig, axes = plt.subplots(
        1,
        2,
        figsize=(7.1, 3.6),
        gridspec_kw={
            "width_ratios": [2.25, 0.8],
            "wspace": 0.36,
        },
    )
    fig.subplots_adjust(
        left=0.19, right=0.98, top=0.84, bottom=0.18
    )
    ax = axes[0]
    cmap = ListedColormap([RED, GRID, ORANGE, BLUE, GREEN])
    ax.imshow(
        matrix, cmap=cmap, vmin=-0.5, vmax=4.5, aspect="auto"
    )
    ax.set_xticks(
        range(8), [f"L{level}" for level in range(1, 9)]
    )
    ax.set_yticks(
        range(5), [MODE_LABELS[name] for name in mode_order]
    )
    ax.tick_params(length=0)
    for row_index, mode in enumerate(mode_order):
        for column_index, audit in enumerate(
            by_mode[mode]["audit"]
        ):
            status = audit["status"]
            color = (
                "white"
                if status not in {"blocked", "downgrade"}
                else INK
            )
            ax.text(
                column_index,
                row_index,
                status_labels[status],
                ha="center",
                va="center",
                color=color,
                fontweight="bold",
                fontsize=7,
            )
    ax.set_title(
        "A. Failure detection and admission",
        loc="left",
        fontweight="bold",
    )
    legend = [
        Patch(facecolor=BLUE, label="pass"),
        Patch(facecolor=RED, label="fail / suppress"),
        Patch(facecolor=GRID, label="blocked"),
        Patch(facecolor=ORANGE, label="downgrade"),
        Patch(facecolor=GREEN, label="admit"),
    ]
    ax.legend(
        handles=legend,
        ncol=3,
        frameon=False,
        loc="upper left",
        bbox_to_anchor=(-0.01, -0.20),
        handlelength=1.1,
        columnspacing=0.9,
    )

    draw = by_mode["stateful_draw_shift"]
    level_7 = draw["audit"][6]["evidence"]
    shared = require_int(
        level_7.get("shared_event_count"),
        "synthetic shared events",
        minimum=1,
    )
    raw_mismatches = require_int(
        level_7.get("mismatched_count"),
        "synthetic mismatches",
    )
    remediation = draw.get("evidence", {}).get(
        "event_keyed_remediation"
    )
    if not isinstance(remediation, dict):
        raise ArtifactInputError(
            "synthetic event-keyed remediation is missing"
        )
    remediated_mismatches = remediation.get(
        "mismatched_common_event_keys"
    )
    if not isinstance(remediated_mismatches, list):
        raise ArtifactInputError(
            "synthetic remediated mismatch list is missing"
        )
    aligned = [
        shared - raw_mismatches,
        shared - len(remediated_mismatches),
    ]
    if any(value < 0 or value > shared for value in aligned):
        raise ArtifactInputError(
            "synthetic event-alignment counts are inconsistent"
        )
    ax = axes[1]
    bars = ax.bar(
        [0, 1],
        aligned,
        width=0.62,
        color=[RED, GREEN],
        edgecolor="white",
    )
    ax.set_ylim(0, shared * 1.18)
    ax.set_xticks(
        [0, 1], ["Stateful\nstream", "Event-keyed\nremedy"]
    )
    ax.set_yticks(range(shared + 1))
    ax.set_ylabel("Shared events aligned")
    ax.set_title(
        "B. Draw-shift remedy",
        loc="left",
        fontweight="bold",
    )
    ax.grid(
        axis="y", color=GRID, linewidth=0.6, zorder=0
    )
    ax.set_axisbelow(True)
    for bar, value in zip(bars, aligned, strict=True):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + shared * 0.035,
            f"{value}/{shared}",
            ha="center",
            va="bottom",
            color=INK,
            fontweight="bold",
        )
    fig.suptitle(
        "Self-contained synthetic demonstration of selected PEVL failures",
        x=0.02,
        ha="left",
        fontsize=11,
        fontweight="bold",
        color=INK,
    )
    return save_figure(
        fig, output_dir, FIGURE_STEMS["synthetic"]
    )


def figure_historical(
    audit: Mapping[str, Any], output_dir: Path
) -> list[Path]:
    by_opponent = audit["by_opponent"]
    outcome_rates = [
        by_opponent[name]["any_outcome_record_mismatch_units"]
        / by_opponent[name]["pairs"]
        for name in OPPONENT_ORDER
    ]
    serialized_rates = [
        by_opponent[name]["any_serialized_record_mismatch_units"]
        / by_opponent[name]["pairs"]
        for name in OPPONENT_ORDER
    ]
    fig, ax = plt.subplots(figsize=(7.1, 3.7))
    fig.subplots_adjust(
        left=0.20, right=0.98, top=0.83, bottom=0.20
    )
    positions = list(range(len(OPPONENT_ORDER)))
    height = 0.34
    for name in ("starmie", "dipplin"):
        index = OPPONENT_ORDER.index(name)
        ax.axhspan(
            index - 0.48,
            index + 0.48,
            color="#FAF2E8",
            zorder=0,
        )
    outcome_bars = ax.barh(
        [value - height / 2 for value in positions],
        [100 * value for value in outcome_rates],
        height=height,
        color=BLUE,
        label="Outcome-record mismatch",
        zorder=2,
    )
    serialized_bars = ax.barh(
        [value + height / 2 for value in positions],
        [100 * value for value in serialized_rates],
        height=height,
        color=ORANGE,
        label="Serialized-record mismatch",
        zorder=2,
    )
    ax.set_yticks(
        positions,
        [OPPONENT_LABELS[name] for name in OPPONENT_ORDER],
    )
    ax.invert_yaxis()
    ax.set_xlabel(
        "Repeated-control units with any mismatch (%)"
    )
    ax.grid(
        axis="x", color=GRID, linewidth=0.6, zorder=0
    )
    ax.legend(
        frameon=False,
        ncol=2,
        loc="upper left",
        bbox_to_anchor=(0, -0.18),
    )
    for bars, field in (
        (outcome_bars, "any_outcome_record_mismatch_units"),
        (
            serialized_bars,
            "any_serialized_record_mismatch_units",
        ),
    ):
        for bar, name in zip(
            bars, OPPONENT_ORDER, strict=True
        ):
            count = by_opponent[name][field]
            if count:
                ax.text(
                    bar.get_width() + 0.8,
                    bar.get_y() + bar.get_height() / 2,
                    f"{count}",
                    va="center",
                    fontsize=6.8,
                    color=INK,
                )
    total = audit["pairs"]
    outcome_total = audit[
        "outcome_record_mismatch_units"
    ]
    serialized_total = audit[
        "serialized_record_mismatch_units"
    ]
    ax.set_title(
        "Historical repeated-control parity failure",
        loc="left",
        fontsize=11,
        fontweight="bold",
        color=INK,
    )
    ax.text(
        0.99,
        1.02,
        f"Overall: {outcome_total}/{total} outcome; "
        f"{serialized_total}/{total} serialized",
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        color=MUTED,
        fontsize=7,
    )
    ax.text(
        0.99,
        -0.20,
        "Shading marks the two packages with wall-clock-limited "
        "search identified by the source audit.",
        transform=ax.transAxes,
        ha="right",
        va="top",
        color=MUTED,
        fontsize=6.6,
    )
    return save_figure(
        fig, output_dir, FIGURE_STEMS["historical"]
    )


def figure_stress(
    stress: Mapping[str, Any], output_dir: Path
) -> list[Path]:
    rows: list[tuple[str, Mapping[str, Any]]] = [
        ("Overall", stress["trace_disagreement"])
    ]
    for key in sorted(stress["strata"]):
        opponent, order = key.split("/", 1)
        rows.append(
            (
                f"{opponent.title()} / {order}",
                stress["strata"][key]["trace_disagreement"],
            )
        )
    fig, ax = plt.subplots(figsize=(6.3, 3.5))
    fig.subplots_adjust(
        left=0.22, right=0.96, top=0.82, bottom=0.20
    )
    y = list(reversed(range(len(rows))))
    for index, (
        (_label, summary),
        ypos,
    ) in enumerate(zip(rows, y, strict=True)):
        estimate = float(summary["estimate"])
        low, high = summary["bootstrap_95_ci"]
        color = PURPLE if index == 0 else BLUE
        marker = "D" if index == 0 else "o"
        ax.errorbar(
            100 * estimate,
            ypos,
            xerr=[
                [100 * (estimate - low)],
                [100 * (high - estimate)],
            ],
            fmt=marker,
            color=color,
            markerfacecolor="white",
            markeredgewidth=1.2,
            capsize=3,
            linewidth=1.1,
        )
    ax.set_yticks(y, [label for label, _summary in rows])
    ax.set_xlabel(
        "Seed-condition clusters with trace disagreement (%)"
    )
    ax.set_xlim(left=0)
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.set_title(
        "Prospective timed-search repeat/worker stress test",
        loc="left",
        fontsize=11,
        fontweight="bold",
    )
    ax.text(
        0.99,
        -0.20,
        f"{stress['trace_disagreement_clusters']}/"
        f"{stress['clusters']} trace-disagreement clusters; "
        f"{stress['outcome_disagreement_clusters']} outcome, "
        f"{stress['decision_count_disagreement_clusters']} "
        "decision-count, "
        f"{stress['error_disagreement_clusters']} error "
        "disagreements.",
        transform=ax.transAxes,
        ha="right",
        va="top",
        color=MUTED,
        fontsize=6.6,
    )
    return save_figure(
        fig, output_dir, FIGURE_STEMS["stress"]
    )


def figure_factorial(
    factorial: Mapping[str, Any], output_dir: Path
) -> list[Path]:
    order = [
        "primary_c4_minus_c1",
        "representation_main",
        "training_main",
        "interaction",
    ]
    fig, ax = plt.subplots(figsize=(6.2, 3.4))
    fig.subplots_adjust(
        left=0.31, right=0.97, top=0.82, bottom=0.22
    )
    y = list(reversed(range(len(order))))
    for index, (name, ypos) in enumerate(
        zip(order, y, strict=True)
    ):
        result = factorial["contrasts"][name]
        estimate = float(result["estimate"])
        low, high = result["bootstrap_95_ci"]
        color = PURPLE if index == 0 else BLUE
        marker = "D" if index == 0 else "o"
        ax.errorbar(
            100 * estimate,
            ypos,
            xerr=[
                [100 * (estimate - low)],
                [100 * (high - estimate)],
            ],
            fmt=marker,
            color=color,
            markerfacecolor="white",
            markeredgewidth=1.3,
            capsize=3,
            linewidth=1.2,
        )
    ax.axvline(
        0, color=MUTED, linestyle="--", linewidth=0.8
    )
    ax.set_yticks(
        y, [CONTRAST_LABELS[name] for name in order]
    )
    ax.set_xlabel("Win-rate contrast (percentage points)")
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.set_title(
        "Admitted five-opponent fixed-schedule factorial",
        loc="left",
        fontsize=11,
        fontweight="bold",
    )
    ax.text(
        0.99,
        -0.22,
        f"{factorial['units']:,} seed-condition units; "
        "empirical intervals describe the frozen schedule only "
        "and does not establish Level 7.",
        transform=ax.transAxes,
        ha="right",
        va="top",
        color=MUTED,
        fontsize=6.6,
    )
    return save_figure(
        fig, output_dir, FIGURE_STEMS["factorial"]
    )


def tex_escape(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(
        replacements.get(char, char) for char in value
    )


def write_tex(path: Path, lines: Sequence[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    ensure_regular_target(path)
    path.write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return path


def table_ladder(output_dir: Path) -> Path:
    lines = [
        (
            "% Auto-generated by "
            "paper/scripts/build_pevl_artifacts.py; do not edit."
        ),
        r"\begin{table*}",
        (
            r"\caption{Compressed Paired Evaluation Validity Ladder. "
            r"Levels 1--7 are cumulative evidence gates; Level 8 is "
            r"the prespecified decision that admits, downgrades, or "
            r"suppresses a claim.}"
        ),
        r"\label{tab:pevl-ladder}",
        r"\begin{ruledtabular}",
        r"\begin{tabular}{clp{6.0cm}p{5.0cm}}",
        (
            r"Level & Gate or decision & Evidence admitted & "
            r"Fail-closed response \\"
        ),
        r"\hline",
    ]
    for level in range(1, 9):
        title, admitted, response = LEVEL_DETAILS[level]
        lines.append(
            f"{level} & {tex_escape(title)} & "
            f"{tex_escape(admitted)} & "
            f"{tex_escape(response)} \\\\"
        )
    lines.extend(
        [
            r"\end{tabular}",
            r"\end{ruledtabular}",
            r"\end{table*}",
        ]
    )
    return write_tex(
        output_dir / TABLE_NAMES["ladder"], lines
    )


def table_retrospective(
    audit: Mapping[str, Any], output_dir: Path
) -> Path:
    lines = [
        (
            "% Auto-generated by "
            "paper/scripts/build_pevl_artifacts.py; do not edit."
        ),
        r"\begin{table*}",
        (
            r"\caption{Retrospective repeated-control audit. "
            r"Outcome-record parity compares terminal outcome and "
            r"error fields; serialized-record parity additionally "
            r"includes decision counts. The prespecified "
            r"seven-opponent factorial was invalidated.}"
        ),
        r"\label{tab:pevl-retrospective}",
        r"\begin{ruledtabular}",
        r"\begin{tabular}{lrrrl}",
        (
            r"Opponent package & Units & Outcome mismatch & "
            r"Serialized mismatch & Audit note \\"
        ),
        r"\hline",
    ]
    for opponent in OPPONENT_ORDER:
        row = audit["by_opponent"][opponent]
        pairs = row["pairs"]
        outcome = row[
            "any_outcome_record_mismatch_units"
        ]
        serialized = row[
            "any_serialized_record_mismatch_units"
        ]
        note = (
            "wall-clock search"
            if opponent in {"starmie", "dipplin"}
            else "no mismatch observed"
        )
        lines.append(
            f"{tex_escape(OPPONENT_LABELS[opponent])} & "
            f"{pairs:,} & {outcome:,} "
            f"({100 * outcome / pairs:.1f}\\%) & "
            f"{serialized:,} "
            f"({100 * serialized / pairs:.1f}\\%) & "
            f"{tex_escape(note)} \\\\"
        )
    pairs = audit["pairs"]
    outcome = audit["outcome_record_mismatch_units"]
    serialized = audit[
        "serialized_record_mismatch_units"
    ]
    lines.extend(
        [
            r"\hline",
            (
                f"Overall & {pairs:,} & {outcome:,} "
                f"({100 * outcome / pairs:.1f}\\%) & "
                f"{serialized:,} "
                f"({100 * serialized / pairs:.1f}\\%) & "
                r"planned contrasts suppressed \\"
            ),
            r"\end{tabular}",
            r"\end{ruledtabular}",
            r"\end{table*}",
        ]
    )
    return write_tex(
        output_dir / TABLE_NAMES["retrospective"], lines
    )


def table_prospective(
    preflight: Mapping[str, Any],
    preflight_details: Mapping[str, Any],
    stress: Mapping[str, Any] | None,
    output_dir: Path,
) -> Path:
    preflight_admission = (
        "factorial acquisition admitted"
        if preflight_details["status"] == "PASS"
        else "factorial acquisition suppressed"
    )
    lines = [
        (
            "% Auto-generated by "
            "paper/scripts/build_pevl_artifacts.py; do not edit."
        ),
        r"\begin{table*}",
        (
            r"\caption{Prospective PEVL execution audit. The trace "
            r"preflight covers all four arms and the frozen "
            r"determinism-eligible opponents. A stress row appears "
            r"only after a complete processed summary exists.}"
        ),
        r"\label{tab:pevl-prospective}",
        r"\begin{ruledtabular}",
        r"\begin{tabular}{llrrrl}",
        (
            r"Stage & Population & Units & Executions & "
            r"Trace mismatches & Admission \\"
        ),
        r"\hline",
        (
            "Four-arm trace preflight & "
            f"4 arms $\\times$ "
            f"{preflight_details['opponents']} opponents & "
            f"{preflight['trajectory_units']:,} & "
            f"{preflight['executions']:,} & "
            f"{preflight['mismatch_units']:,} units & "
            f"{preflight_admission} \\\\"
        ),
    ]
    if stress is not None:
        status_text = (
            "exact trace reproducibility rejected"
            if stress["status"] == "TRACE_DIVERGENCE"
            else "trace parity on exercised schedule"
        )
        lines.append(
            f"Timed-search stress & 2 opponents "
            f"$\\times$ 2 orders & "
            f"{stress['clusters']:,} & "
            f"{stress['executions']:,} & "
            f"{stress['trace_disagreement_clusters']:,} "
            "clusters & "
            f"{tex_escape(status_text)} \\\\"
        )
    lines.extend(
        [
            r"\end{tabular}",
            r"\end{ruledtabular}",
            r"\end{table*}",
        ]
    )
    return write_tex(
        output_dir / TABLE_NAMES["prospective"], lines
    )


def table_factorial(
    factorial: Mapping[str, Any], output_dir: Path
) -> Path:
    order = [
        "primary_c4_minus_c1",
        "representation_main",
        "training_main",
        "interaction",
    ]
    lines = [
        (
            "% Auto-generated by "
            "paper/scripts/build_pevl_artifacts.py; do not edit."
        ),
        r"\begin{table*}",
        (
            r"\caption{Conditionally admitted five-opponent "
            r"seed-matched factorial. Effects and paired-bootstrap "
            r"intervals are percentage-point differences in win "
            r"probability. Level 7 event alignment is not "
            r"established.}"
        ),
        r"\label{tab:pevl-factorial}",
        r"\begin{ruledtabular}",
        r"\begin{tabular}{lrrl}",
        r"Contrast & Estimate (pp) & 95\% CI (pp) & Role \\",
        r"\hline",
    ]
    for index, name in enumerate(order):
        result = factorial["contrasts"][name]
        low, high = result["bootstrap_95_ci"]
        role = (
            "primary"
            if index == 0
            else "secondary, estimation-focused"
        )
        lines.append(
            f"{tex_escape(CONTRAST_LABELS[name])} & "
            f"{100 * result['estimate']:+.2f} & "
            f"[{100 * low:+.2f}, {100 * high:+.2f}] & "
            f"{role} \\\\"
        )
    lines.extend(
        [
            r"\end{tabular}",
            r"\end{ruledtabular}",
            r"\end{table*}",
        ]
    )
    return write_tex(
        output_dir / TABLE_NAMES["factorial"], lines
    )


def remove_conditional_outputs(
    key: str,
    figures_dir: Path,
    tables_dir: Path,
) -> list[Path]:
    targets = [
        figures_dir / f"{FIGURE_STEMS[key]}.pdf",
        figures_dir / f"{FIGURE_STEMS[key]}.png",
    ]
    if key == "factorial":
        targets.append(
            tables_dir / TABLE_NAMES["factorial"]
        )
    removed: list[Path] = []
    for path in targets:
        if path.is_symlink() or path.exists():
            if path.is_symlink() or not path.is_file():
                raise RuntimeError(
                    "refusing to remove non-regular generated "
                    f"target: {path}"
                )
            path.unlink()
            removed.append(path)
    return removed


def remove_prospective_table(
    tables_dir: Path,
) -> list[Path]:
    path = tables_dir / TABLE_NAMES["prospective"]
    if not path.is_symlink() and not path.exists():
        return []
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(
            "refusing to remove non-regular generated "
            f"target: {path}"
        )
    path.unlink()
    return [path]


def build_artifacts(
    *,
    synthetic_path: Path = DEFAULT_SYNTHETIC,
    historical_path: Path = DEFAULT_HISTORICAL,
    preflight_path: Path = DEFAULT_PREFLIGHT,
    stress_path: Path = DEFAULT_STRESS,
    factorial_path: Path = DEFAULT_FACTORIAL,
    combined_path: Path = DEFAULT_COMBINED,
    figures_dir: Path = DEFAULT_FIGURES,
    tables_dir: Path = DEFAULT_TABLES,
) -> dict[str, Any]:
    setup_style()
    synthetic = load_json(
        synthetic_path, "synthetic PEVL"
    )
    historical = load_json(
        historical_path, "historical parity"
    )
    by_mode = validate_synthetic(synthetic)
    audit = validate_historical(historical)

    preflight_payload = optional_json(
        preflight_path, "trace-preflight summary"
    )
    preflight_details = (
        None
        if preflight_payload is None
        else validate_preflight(preflight_payload)
    )
    stress_payload = optional_json(
        stress_path, "stress summary"
    )
    stress = (
        None
        if stress_payload is None
        else validate_stress(stress_payload)
    )
    factorial_payload = optional_json(
        factorial_path, "factorial summary"
    )
    factorial = (
        None
        if factorial_payload is None
        else validate_factorial(factorial_payload)
    )
    combined_payload = optional_json(
        combined_path, "combined PEVL summary"
    )
    component_payloads = (
        preflight_payload,
        stress_payload,
        factorial_payload,
    )
    if any(payload is not None for payload in component_payloads):
        if combined_payload is None:
            raise ArtifactInputError(
                "processed PEVL component exists without "
                f"combined summary: {combined_path}"
            )
    if combined_payload is not None:
        validate_combined(
            combined_payload,
            historical=historical,
            preflight=preflight_payload,
            stress=stress_payload,
            factorial=factorial_payload,
        )

    if factorial is not None:
        if (
            preflight_payload is None
            or preflight_details is None
            or preflight_details["status"] != "PASS"
        ):
            raise ArtifactInputError(
                "admitted factorial lacks a complete PASS preflight"
            )
        if (
            factorial.get("protocol_commit")
            != preflight_payload.get("protocol_commit")
        ):
            raise ArtifactInputError(
                "factorial and preflight protocol commits differ"
            )
    if stress is not None and preflight_payload is not None:
        preflight_commit = preflight_payload.get("protocol_commit")
        if (
            isinstance(preflight_commit, str)
            and stress.get("protocol_commit") != preflight_commit
        ):
            raise ArtifactInputError(
                "stress and preflight protocol commits differ"
            )
    if (
        preflight_details is not None
        and preflight_details["status"] == "PASS"
        and factorial_payload is not None
        and factorial_payload.get("status")
        == "SUPPRESSED_BY_PREFLIGHT"
    ):
        raise ArtifactInputError(
            "factorial suppression conflicts with PASS preflight"
        )

    generated: list[Path] = []
    removed: list[Path] = []
    skipped: dict[str, str] = {}
    generated.extend(
        figure_ladder(synthetic["levels"], figures_dir)
    )
    generated.extend(
        figure_synthetic(by_mode, figures_dir)
    )
    generated.extend(
        figure_historical(audit, figures_dir)
    )
    generated.append(table_ladder(tables_dir))
    generated.append(
        table_retrospective(audit, tables_dir)
    )

    if stress is None:
        removed.extend(
            remove_conditional_outputs(
                "stress", figures_dir, tables_dir
            )
        )
        skipped["stress"] = (
            "summary missing"
            if stress_payload is None
            else "status "
            f"{stress_payload.get('status')} is not renderable"
        )
    else:
        generated.extend(
            figure_stress(stress, figures_dir)
        )

    if preflight_details is None:
        removed.extend(remove_prospective_table(tables_dir))
        skipped["preflight"] = (
            "summary missing"
            if preflight_payload is None
            else "status "
            f"{preflight_payload.get('status')} is not renderable"
        )
    else:
        if preflight_payload is None:
            raise AssertionError(
                "validated preflight lost its source payload"
            )
        generated.append(
            table_prospective(
                preflight_payload,
                preflight_details,
                stress,
                tables_dir,
            )
        )

    if factorial is None:
        removed.extend(
            remove_conditional_outputs(
                "factorial", figures_dir, tables_dir
            )
        )
        skipped["factorial"] = (
            "summary missing"
            if factorial_payload is None
            else "status "
            f"{factorial_payload.get('status')} is not admitted"
        )
    else:
        generated.extend(
            figure_factorial(factorial, figures_dir)
        )
        generated.append(
            table_factorial(factorial, tables_dir)
        )

    return {
        "generated": [str(path) for path in generated],
        "removed_stale": [str(path) for path in removed],
        "skipped": skipped,
    }


def parse_args(
    argv: Sequence[str] | None = None,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--synthetic",
        type=Path,
        default=DEFAULT_SYNTHETIC,
    )
    parser.add_argument(
        "--historical",
        type=Path,
        default=DEFAULT_HISTORICAL,
    )
    parser.add_argument(
        "--preflight",
        type=Path,
        default=DEFAULT_PREFLIGHT,
    )
    parser.add_argument(
        "--stress", type=Path, default=DEFAULT_STRESS
    )
    parser.add_argument(
        "--factorial",
        type=Path,
        default=DEFAULT_FACTORIAL,
    )
    parser.add_argument(
        "--combined",
        type=Path,
        default=DEFAULT_COMBINED,
    )
    parser.add_argument(
        "--figures-dir",
        type=Path,
        default=DEFAULT_FIGURES,
    )
    parser.add_argument(
        "--tables-dir",
        type=Path,
        default=DEFAULT_TABLES,
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    result = build_artifacts(
        synthetic_path=args.synthetic,
        historical_path=args.historical,
        preflight_path=args.preflight,
        stress_path=args.stress,
        factorial_path=args.factorial,
        combined_path=args.combined,
        figures_dir=args.figures_dir,
        tables_dir=args.tables_dir,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
