#!/usr/bin/env python3
"""Validate terminal evidence and build final Protocol Article artifacts.

This program is deliberately fail closed.  It accepts only the prospectively
frozen protocol commit and the exact analyzed inputs audited for this article.
It never runs the restricted game engine or rewrites acquisition rows.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Patch


SCRIPT = Path(__file__).resolve()
FINAL = SCRIPT.parents[1]
ROOT = SCRIPT.parents[3]
PAPER = ROOT / "paper"
PROTOCOL_COMMIT = "803257f102232763fc88d28c14b668f9b62eb277"

INPUTS = {
    "synthetic": (
        PAPER / "synthetic/results/pevl_results.json",
        "d34a2ea1546a0a88e90a5ca58b49f1085edfcaf753f70ed49e0f04202e9ba6f9",
    ),
    "combined": (
        PAPER / "data/pevl/summary.json",
        "d8e74d83a7c6bd3ad4690d91321ae4508f7b6f10a76cb6b4efaeab0e2b4014cd",
    ),
    "preflight": (
        PAPER / "data/pevl/trace_preflight_summary.json",
        "c6295f9f3981d346d0cbcb38327e575b560aaf0950bd52f52594cfb8f9cc56b3",
    ),
    "stress": (
        PAPER / "data/pevl/timed_search_stress_summary.json",
        "40b9f5e17a424742ad8a05739646fe56843b8f3a432b124bfc33f9aed1ab5a4b",
    ),
    "factorial": (
        PAPER / "data/pevl/factorial_summary.json",
        "c7df75c7ae0f76a007d866947ad5262242d86c0c90cb0c8631d201dedd023e59",
    ),
    "historical": (
        PAPER / "data/ablation/summary.json",
        "fadc6111654423dab62486e27d05636439b0647192fabe3786a69cd60a49e239",
    ),
    "protocol": (
        PAPER / "protocol/PEVL_PROSPECTIVE_PROTOCOL.md",
        "8b9329b948a054fc7252b9c2662490890e0a8439ad852393c6e25f537c8b887e",
    ),
    "seed_audit": (
        PAPER / "data/seed_namespace_audit.json",
        "50344ba5a8b3ab21d037c0d37115562ea0c2c1da8fabdfe0b717d292a52f7a5e",
    ),
    "stochastic_audit": (
        PAPER / "data/stochastic_source_audit.json",
        "995ab30d0f2166963b5bc7dd73d2784ed95cde2f93315e1e06bece935a875c60",
    ),
}

INK = "#1F2933"
MUTED = "#5F6B75"
GRID = "#D9E0E5"
BLUE = "#466F8A"
PURPLE = "#6F638B"
GREEN = "#4D7A68"
ORANGE = "#B57A35"
RED = "#9A4F4F"
FIXED_DATE = datetime(2026, 8, 24, tzinfo=timezone.utc)


class EvidenceError(ValueError):
    """Raised when an input cannot support a manuscript artifact."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def reject_constant(value: str) -> None:
    raise EvidenceError(f"non-finite JSON constant is prohibited: {value}")


def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicates,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"top-level JSON value must be an object: {path}")
    return value


def finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvidenceError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise EvidenceError(f"{label} must be finite")
    return result


def exact_int(value: Any, expected: int, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value != expected:
        raise EvidenceError(f"{label}: expected {expected}, found {value!r}")


def exact(value: Any, expected: Any, label: str) -> None:
    if value != expected:
        raise EvidenceError(f"{label}: expected {expected!r}, found {value!r}")


def stress_fixed_composition_reweighting(stress: dict[str, Any]) -> dict[str, Any]:
    """Reweight whole stress clusters while preserving the four fixed strata."""
    expected_strata = {
        "starmie/first", "starmie/second", "dipplin/first", "dipplin/second"
    }
    vectors: dict[str, list[int]] = {}
    rows = stress.get("cluster_rows")
    if not isinstance(rows, list):
        raise EvidenceError("stress cluster rows are missing")
    for row in rows:
        if not isinstance(row, dict):
            raise EvidenceError("stress cluster row is malformed")
        key = f"{row.get('opponent')}/{row.get('actual_order')}"
        value = row.get("trace_disagreement")
        if value not in {0, 1, False, True}:
            raise EvidenceError(f"stress trace flag is not binary: {key}")
        vectors.setdefault(key, []).append(int(value))
    if set(vectors) != expected_strata or any(len(values) != 50 for values in vectors.values()):
        raise EvidenceError("stress fixed-composition strata drift")

    draws = 100_000
    seed = 2026083118
    rng = np.random.default_rng(seed)
    estimates = np.zeros(draws, dtype=np.float64)
    counts: dict[str, int] = {}
    for key in sorted(vectors):
        vector = np.asarray(vectors[key], dtype=np.float64)
        counts[key] = int(vector.sum())
        indices = rng.integers(0, len(vector), size=(draws, len(vector)))
        estimates += vector[indices].mean(axis=1) / len(vectors)
    low, high = np.quantile(estimates, [0.025, 0.975]).tolist()
    point = float(np.mean([np.mean(values) for values in vectors.values()]))
    if not math.isclose(point, 0.495, rel_tol=0.0, abs_tol=1e-15):
        raise EvidenceError("stress fixed-composition point estimate drift")
    if not np.allclose([low, high], [0.46, 0.53], rtol=0.0, atol=1e-15):
        raise EvidenceError("stress fixed-composition reweighting quantiles drift")
    exact(counts, {
        "dipplin/first": 4,
        "dipplin/second": 3,
        "starmie/first": 44,
        "starmie/second": 48,
    }, "stress fixed-composition counts")
    return {
        "estimate": point,
        "quantiles_2_5_97_5": [low, high],
        "draws": draws,
        "seed": seed,
        "stratum_weighting": "equal with fixed 50-cluster composition",
        "reweighting_unit": "whole seed-condition cluster retaining all four profiles",
        "role": "post-acquisition fixed-composition sensitivity to the frozen pooled reweighting",
        "stratum_disagreement_counts": counts,
    }


def validate_inputs() -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {}
    for label, (path, expected_hash) in INPUTS.items():
        if not path.is_file() or path.is_symlink():
            raise EvidenceError(f"required regular input is missing: {path}")
        observed = sha256(path)
        if observed != expected_hash:
            raise EvidenceError(
                f"{label} source hash changed: expected {expected_hash}, found {observed}"
            )
        if path.suffix == ".json":
            payloads[label] = load_json(path)

    combined = payloads["combined"]
    preflight = payloads["preflight"]
    stress = payloads["stress"]
    factorial = payloads["factorial"]
    historical = payloads["historical"]
    synthetic = payloads["synthetic"]
    seed_audit = payloads["seed_audit"]
    stochastic_audit = payloads["stochastic_audit"]

    exact(combined.get("schema_version"), 1, "combined schema")
    exact(combined.get("framework"), "Paired Evaluation Validity Ladder", "framework")
    exact(combined.get("protocol"), "paper/protocol/PEVL_PROSPECTIVE_PROTOCOL.md", "protocol path")
    for label, payload, analysis_id in (
        ("preflight", preflight, "trace_preflight"),
        ("stress", stress, "timed_search_stress"),
        ("factorial", factorial, "factorial"),
    ):
        exact(payload.get("schema_version"), 1, f"{label} schema")
        exact(payload.get("analysis_id"), analysis_id, f"{label} analysis id")
        exact(payload.get("protocol_commit"), PROTOCOL_COMMIT, f"{label} protocol commit")

    if combined.get("prospective_trace_preflight") != preflight:
        raise EvidenceError("combined/preflight content conflict")
    if combined.get("timed_search_stress") != stress:
        raise EvidenceError("combined/stress content conflict")
    if combined.get("gated_factorial") != factorial:
        raise EvidenceError("combined/factorial content conflict")

    exact(seed_audit.get("conversion_rule"), "scheduled_seed & 0xffffffff", "seed conversion rule")
    exact(seed_audit.get("prospective_passed"), True, "seed audit status")
    exact(seed_audit.get("historical_prospective_engine_seed_overlap"), [], "seed namespace overlap")
    exact(seed_audit.get("provenance", {}).get("git_commit"), PROTOCOL_COMMIT, "seed audit protocol commit")
    exact_int(seed_audit.get("historical_fresh_confirmation", {}).get("scheduled_count"), 2800, "historical boundary-seed count")
    exact_int(seed_audit.get("prospective_all", {}).get("scheduled_count"), 2450, "prospective boundary-seed count")

    exact(stochastic_audit.get("schema_version"), "pevl-stochastic-source-audit-v1", "stochastic audit schema")
    exact(stochastic_audit.get("provenance", {}).get("git_commit"), PROTOCOL_COMMIT, "stochastic audit protocol commit")
    exact_int(len(stochastic_audit.get("inventory", [])), 13, "stochastic audit artifact count")
    exact(stochastic_audit.get("level_results", {}).get("level_1_artifact_identity", {}).get("status"), "pass", "stochastic audit artifact status")
    exact(stochastic_audit.get("level_results", {}).get("level_6_stochastic_source_audit", {}).get("status"), "bounded_audit_recorded", "stochastic audit source status")
    if any(item.get("hash_match") is not True for item in stochastic_audit["inventory"]):
        raise EvidenceError("stochastic audit contains a drifting artifact")

    exact(preflight.get("status"), "PASS", "preflight status")
    exact(preflight.get("admission_decision"), "admit_factorial_acquisition", "preflight admission")
    for key, expected_value in {
        "arms": 4,
        "opponents": 5,
        "trajectory_units": 1000,
        "executions": 3000,
        "mismatch_units": 0,
        "trace_mismatch_units": 0,
        "outcome_mismatch_units": 0,
        "error_mismatch_units": 0,
        "decision_count_mismatch_units": 0,
    }.items():
        exact_int(preflight.get(key), expected_value, f"preflight {key}")
    rows = preflight.get("rows")
    if not isinstance(rows, list) or len(rows) != 20:
        raise EvidenceError("preflight must contain the frozen 20 arm/opponent rows")
    identities: set[tuple[str, str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise EvidenceError("preflight row must be an object")
        arm, opponent = row.get("arm"), row.get("opponent")
        if arm not in {"C1", "C2", "C3", "C4"} or not isinstance(opponent, str):
            raise EvidenceError("preflight arm/opponent identity drift")
        identities.add((arm, opponent))
        exact_int(row.get("trajectory_units"), 50, "preflight row units")
        exact_int(row.get("executions"), 150, "preflight row executions")
        exact_int(row.get("mismatch_units"), 0, "preflight row mismatches")
        exact(row.get("passed"), True, "preflight row pass")
    if len(identities) != 20 or len({item[1] for item in identities}) != 5:
        raise EvidenceError("preflight row coverage drift")

    exact(stress.get("status"), "TRACE_DIVERGENCE", "stress status")
    for key, expected_value in {
        "clusters": 200,
        "executions": 800,
        "trace_disagreement_clusters": 99,
        "outcome_disagreement_clusters": 47,
        "decision_count_disagreement_clusters": 93,
        "error_disagreement_clusters": 0,
        "policy_error_present_clusters": 0,
    }.items():
        exact_int(stress.get(key), expected_value, f"stress {key}")
    trace = stress.get("trace_disagreement")
    if not isinstance(trace, dict):
        raise EvidenceError("stress trace-disagreement summary is missing")
    exact(finite_number(trace.get("estimate"), "stress estimate"), 0.495, "stress estimate")
    exact(trace.get("bootstrap_95_ci"), [0.425, 0.565], "stress pooled reweighting quantiles")
    exact_int(trace.get("bootstrap_draws"), 100000, "stress reweighting draws")
    strata = stress.get("strata")
    if not isinstance(strata, dict) or set(strata) != {
        "starmie/first", "starmie/second", "dipplin/first", "dipplin/second"
    }:
        raise EvidenceError("stress strata drift")
    for name, row in strata.items():
        if not isinstance(row, dict) or not isinstance(row.get("trace_disagreement"), dict):
            raise EvidenceError(f"stress stratum is malformed: {name}")
        exact_int(row["trace_disagreement"].get("clusters"), 50, f"{name} clusters")
        exact_int(row["trace_disagreement"].get("bootstrap_draws"), 100000, f"{name} draws")
    stress_fixed_composition_reweighting(stress)

    exact(factorial.get("status"), "ADMITTED_SEED_MATCHED", "factorial status")
    exact(factorial.get("admission_decision"), "admit_with_bounded_wording", "factorial admission")
    exact_int(factorial.get("units"), 2000, "factorial units")
    exact_int(factorial.get("games"), 12000, "factorial games")
    exact_int(factorial.get("control_mismatch_units"), 0, "factorial control mismatches")
    contrasts = factorial.get("contrasts")
    expected_contrasts = {
        "primary_c4_minus_c1": (0.0055, [-0.02049999999999999, 0.03149999999999999]),
        "representation_main": (0.0095, [-0.01075000000000002, 0.02999999999999998]),
        "training_main": (-0.004, [-0.02025000000000001, 0.012499999999999994]),
        "interaction": (0.013, [-0.018500000000000027, 0.044499999999999984]),
    }
    if not isinstance(contrasts, dict) or set(contrasts) != set(expected_contrasts):
        raise EvidenceError("factorial contrast inventory drift")
    for name, (estimate, interval) in expected_contrasts.items():
        row = contrasts[name]
        exact(finite_number(row.get("estimate"), f"{name} estimate"), estimate, f"{name} estimate")
        exact(row.get("bootstrap_95_ci"), interval, f"{name} reweighting quantiles")
        exact_int(row.get("bootstrap_draws"), 100000, f"{name} reweighting draws")
        if "ten opponent-by-order strata" not in str(row.get("resampling")):
            raise EvidenceError(f"{name} analysis unit drift")

    historical_record = combined.get("historical_control_parity")
    if not isinstance(historical_record, dict):
        raise EvidenceError("historical control-parity record is missing")
    exact(historical_record.get("status"), "INVALIDATED", "historical status")
    exact_int(historical_record.get("units"), 2800, "historical units")
    exact_int(historical_record.get("outcome_record_mismatch_units"), 210, "historical outcome mismatches")
    exact_int(historical_record.get("serialized_record_mismatch_units"), 458, "historical serialized mismatches")
    exact(historical_record.get("source_sha256"), INPUTS["historical"][1], "historical source hash")
    exact(historical.get("status"), "INVALIDATED", "historical analyzer status")

    exact(synthetic.get("schema_version"), "1.1.0", "synthetic schema")
    modes = synthetic.get("modes")
    if not isinstance(modes, list) or {
        row.get("mode") for row in modes if isinstance(row, dict)
    } != {
        "clean_deterministic",
        "stateful_draw_shift",
        "wall_clock_search",
        "process_global_state",
        "uint32_seed_conversion",
    }:
        raise EvidenceError("synthetic mode inventory drift")
    levels = synthetic.get("levels")
    if not isinstance(levels, list) or len(levels) != 8:
        raise EvidenceError("synthetic level inventory drift")

    return payloads


def tex_number(value: float, *, signed: bool = False, digits: int = 2) -> str:
    result = f"{value:.{digits}f}"
    if signed and value > 0:
        result = "+" + result
    return result


def write_macros(payloads: dict[str, dict[str, Any]]) -> Path:
    combined = payloads["combined"]
    preflight = payloads["preflight"]
    stress = payloads["stress"]
    factorial = payloads["factorial"]
    historical = combined["historical_control_parity"]
    primary = factorial["contrasts"]["primary_c4_minus_c1"]
    representation = factorial["contrasts"]["representation_main"]
    training = factorial["contrasts"]["training_main"]
    interaction = factorial["contrasts"]["interaction"]
    trace = stress["trace_disagreement"]
    stress_fixed = stress_fixed_composition_reweighting(stress)
    stress_counts = stress_fixed["stratum_disagreement_counts"]
    stochastic_audit = payloads["stochastic_audit"]
    source_assessed = stochastic_audit["level_results"]["level_6_stochastic_source_audit"]["verified_package_tree_count"]
    binary_unassessed = sum(
        item["source_audit"]["status"] == "not_assessed"
        for item in stochastic_audit["inventory"]
    )

    def pp(row: dict[str, Any]) -> tuple[str, str, str]:
        estimate = tex_number(100 * float(row["estimate"]), signed=True)
        low, high = row["bootstrap_95_ci"]
        return estimate, tex_number(100 * low, signed=True), tex_number(100 * high, signed=True)

    p_est, p_low, p_high = pp(primary)
    r_est, r_low, r_high = pp(representation)
    t_est, t_low, t_high = pp(training)
    i_est, i_low, i_high = pp(interaction)
    content = f"""% Generated by scripts/build_final_artifacts.py; do not edit.
% protocol_commit={PROTOCOL_COMMIT}
% combined_sha256={INPUTS['combined'][1]}
% preflight_sha256={INPUTS['preflight'][1]}
% stress_sha256={INPUTS['stress'][1]}
% factorial_sha256={INPUTS['factorial'][1]}
\\newcommand{{\\ProtocolCommitShort}}{{803257f1}}
\\newcommand{{\\SyntheticModes}}{{5}}
\\newcommand{{\\SyntheticSharedEvents}}{{5}}
\\newcommand{{\\SyntheticMisalignedEvents}}{{4}}
\\newcommand{{\\HistoricalUnits}}{{{historical['units']:,}}}
\\newcommand{{\\HistoricalOutcomeMismatch}}{{{historical['outcome_record_mismatch_units']}}}
\\newcommand{{\\HistoricalAvailableRecordMismatch}}{{{historical['serialized_record_mismatch_units']}}}
\\newcommand{{\\PreflightJobs}}{{{len(preflight['rows'])}}}
\\newcommand{{\\PreflightUnits}}{{{preflight['trajectory_units']:,}}}
\\newcommand{{\\PreflightExecutions}}{{{preflight['executions']:,}}}
\\newcommand{{\\PreflightMismatches}}{{{preflight['mismatch_units']}}}
\\newcommand{{\\StressClusters}}{{{stress['clusters']}}}
\\newcommand{{\\StressExecutions}}{{{stress['executions']}}}
\\newcommand{{\\StressTraceMismatch}}{{{stress['trace_disagreement_clusters']}}}
\\newcommand{{\\StressTracePct}}{{{100 * trace['estimate']:.1f}}}
\\newcommand{{\\StressTraceLowPct}}{{{100 * trace['bootstrap_95_ci'][0]:.1f}}}
\\newcommand{{\\StressTraceHighPct}}{{{100 * trace['bootstrap_95_ci'][1]:.1f}}}
\\newcommand{{\\StressFixedCompositionLowPct}}{{{100 * stress_fixed['quantiles_2_5_97_5'][0]:.1f}}}
\\newcommand{{\\StressFixedCompositionHighPct}}{{{100 * stress_fixed['quantiles_2_5_97_5'][1]:.1f}}}
\\newcommand{{\\StressStratumClusters}}{{50}}
\\newcommand{{\\StressAFirstMismatch}}{{{stress_counts['starmie/first']}}}
\\newcommand{{\\StressASecondMismatch}}{{{stress_counts['starmie/second']}}}
\\newcommand{{\\StressBFirstMismatch}}{{{stress_counts['dipplin/first']}}}
\\newcommand{{\\StressBSecondMismatch}}{{{stress_counts['dipplin/second']}}}
\\newcommand{{\\StressOutcomeMismatch}}{{{stress['outcome_disagreement_clusters']}}}
\\newcommand{{\\StressDecisionMismatch}}{{{stress['decision_count_disagreement_clusters']}}}
\\newcommand{{\\StressErrorMismatch}}{{{stress['error_disagreement_clusters']}}}
\\newcommand{{\\ReweightingDraws}}{{100,000}}
\\newcommand{{\\FactorialUnits}}{{{factorial['units']:,}}}
\\newcommand{{\\FactorialGames}}{{{factorial['games']:,}}}
\\newcommand{{\\FactorialControlMismatch}}{{{factorial['control_mismatch_units']}}}
\\newcommand{{\\SourceAssessedPackageTrees}}{{{source_assessed}}}
\\newcommand{{\\SourceUnassessedBinaries}}{{{binary_unassessed}}}
\\newcommand{{\\PrimaryEstimatePP}}{{{p_est}}}
\\newcommand{{\\PrimaryLowPP}}{{{p_low}}}
\\newcommand{{\\PrimaryHighPP}}{{{p_high}}}
\\newcommand{{\\RepresentationEstimatePP}}{{{r_est}}}
\\newcommand{{\\RepresentationLowPP}}{{{r_low}}}
\\newcommand{{\\RepresentationHighPP}}{{{r_high}}}
\\newcommand{{\\TrainingEstimatePP}}{{{t_est}}}
\\newcommand{{\\TrainingLowPP}}{{{t_low}}}
\\newcommand{{\\TrainingHighPP}}{{{t_high}}}
\\newcommand{{\\InteractionEstimatePP}}{{{i_est}}}
\\newcommand{{\\InteractionLowPP}}{{{i_low}}}
\\newcommand{{\\InteractionHighPP}}{{{i_high}}}
"""
    output = FINAL / "results_macros.tex"
    output.write_text(content, encoding="utf-8")
    return output


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def save_figure(fig: plt.Figure, stem: str) -> list[Path]:
    outputs: list[Path] = []
    metadata = {
        "Creator": "paper/final_protocol/scripts/build_final_artifacts.py",
        "Producer": "Matplotlib",
        "CreationDate": FIXED_DATE,
        "ModDate": FIXED_DATE,
        "Title": stem,
    }
    pdf = FINAL / "figures" / f"{stem}.pdf"
    png = FINAL / "figures" / f"{stem}.png"
    fig.savefig(pdf, bbox_inches="tight", metadata=metadata)
    fig.savefig(
        png,
        bbox_inches="tight",
        dpi=180,
        metadata={"Software": "build_final_artifacts.py", "Creation Time": "2026-08-24T00:00:00Z"},
    )
    plt.close(fig)
    outputs.extend([pdf, png])
    return outputs


def figure_distinctions() -> list[Path]:
    rows = [
        {
            "stage": "Schedule matching",
            "question": "Were declared\nrows matched?",
            "evidence": "Boundary seed, context,\norder, seat, and limits",
            "permits": "Matched-schedule\nattempt",
        },
        {
            "stage": "Execution repeatability",
            "question": "Does each arm\nrepeat?",
            "evidence": "A/A trace-projection digest\nand byte count across profiles",
            "permits": "Bounded within-arm\nrepeatability",
        },
        {
            "stage": "Semantic event alignment",
            "question": "Did shared events receive\nequal random values?",
            "evidence": "Stable event IDs plus\nlogged event/value pairs",
            "permits": "Event-aligned coupling\nwithin the ontology",
        },
    ]
    write_json(FINAL / "source_data/figure_1_distinctions.json", rows)
    fig, ax = plt.subplots(figsize=(12, 4.8))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 4.6)
    ax.axis("off")
    colors = [BLUE, PURPLE, GREEN]
    for index, (row, color) in enumerate(zip(rows, colors, strict=True)):
        x = 0.25 + index * 4.0
        box = FancyBboxPatch(
            (x, 0.75), 3.25, 3.15,
            boxstyle="round,pad=0.06,rounding_size=0.08",
            linewidth=2.0, edgecolor=color, facecolor="white",
        )
        ax.add_patch(box)
        ax.text(x + 0.18, 3.58, row["stage"], fontsize=11.2, fontweight="bold", color=INK, va="top")
        ax.text(x + 0.18, 3.04, row["question"], fontsize=10.8, color=INK, va="top", linespacing=1.25)
        ax.text(x + 0.18, 2.27, "Evidence", fontsize=9.8, fontweight="bold", color=color, va="top")
        ax.text(x + 0.18, 1.98, row["evidence"], fontsize=9.2, color=MUTED, va="top", linespacing=1.25)
        ax.text(x + 0.18, 1.40, "Permits", fontsize=9.8, fontweight="bold", color=color, va="top")
        ax.text(x + 0.18, 1.11, row["permits"], fontsize=9.2, color=MUTED, va="top", linespacing=1.25)
        if index < 2:
            arrow_x = x + 3.31
            ax.add_patch(FancyArrowPatch((arrow_x, 2.35), (arrow_x + 0.58, 2.35), arrowstyle="-|>", mutation_scale=14, color=RED, linewidth=1.8))
            ax.text(arrow_x + 0.29, 2.72, "does not\nimply", ha="center", va="center", color=RED, fontsize=7.7, fontweight="bold")
    ax.text(0.25, 4.35, "Three distinct validation questions", fontsize=22, fontweight="bold", color=INK)
    ax.text(0.25, 0.28, "Evidence accumulates left to right; later claims require additional observations rather than stronger wording.", fontsize=10.5, color=MUTED)
    return save_figure(fig, "figure_1_distinctions")


def figure_admission_flow() -> list[Path]:
    levels = [
        ("L1", "Artifact\nidentity"),
        ("L2", "Seed\nnamespace"),
        ("L3", "Schedule\nparity"),
        ("L4", "A/A trace-\nprojection parity"),
        ("L5", "Repeat/worker\nparity"),
        ("L6", "Source\naudit"),
        ("L7", "Event\nalignment"),
    ]
    source = {
        "levels": [{"level": level, "label": label.replace("\n", " ")} for level, label in levels],
        "failure_action": "suppress or downgrade the affected claim",
        "success_action": "apply the frozen admission map",
        "restricted_engine_boundary": "Level 7 unavailable",
        "level_6_boundary": "fixed-battery descriptive contrast and empirical reweighting only",
    }
    write_json(FINAL / "source_data/figure_2_admission_flow.json", source)
    fig, ax = plt.subplots(figsize=(12, 5.4))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 6)
    ax.axis("off")
    ax.text(0.3, 5.65, "Pairing-assumption protocol and claim admission", fontsize=22, fontweight="bold", color=INK)
    for index, (level, label) in enumerate(levels):
        x = 0.35 + index * 1.55
        color = BLUE if index < 3 else PURPLE if index < 6 else GREEN
        box = FancyBboxPatch((x, 3.45), 1.25, 1.35, boxstyle="round,pad=0.04", facecolor="white", edgecolor=color, linewidth=2)
        ax.add_patch(box)
        ax.text(x + 0.625, 4.53, level, ha="center", va="center", color=color, fontweight="bold", fontsize=12)
        ax.text(x + 0.625, 3.93, label, ha="center", va="center", color=INK, fontsize=8.8)
        if index < len(levels) - 1:
            ax.add_patch(FancyArrowPatch((x + 1.26, 4.12), (x + 1.50, 4.12), arrowstyle="-|>", mutation_scale=11, color=MUTED))
        if index < 6:
            ax.add_patch(FancyArrowPatch((x + 0.625, 3.42), (x + 0.625, 2.65), arrowstyle="-|>", mutation_scale=10, color=RED, linewidth=1.2))
    fail_box = FancyBboxPatch((1.65, 1.35), 6.5, 1.15, boxstyle="round,pad=0.06", facecolor="#FBF1F1", edgecolor=RED, linewidth=2)
    ax.add_patch(fail_box)
    ax.text(4.9, 2.10, "Any required failure", ha="center", va="center", color=RED, fontweight="bold", fontsize=12)
    ax.text(4.9, 1.67, "Suppress or downgrade the affected claim;\nlater statistics cannot repair the gate.", ha="center", va="center", color=INK, fontsize=9.7, linespacing=1.25)
    admit_box = FancyBboxPatch((8.55, 1.35), 3.0, 1.15, boxstyle="round,pad=0.06", facecolor="#EFF7F3", edgecolor=GREEN, linewidth=2)
    ax.add_patch(admit_box)
    ax.text(10.05, 2.10, "L8: claim map", ha="center", va="center", color=GREEN, fontweight="bold", fontsize=11.5)
    ax.text(10.05, 1.68, "admit / downgrade / suppress", ha="center", va="center", color=INK, fontsize=10.2)
    ax.add_patch(FancyArrowPatch((10.275, 3.43), (10.05, 2.52), arrowstyle="-|>", mutation_scale=12, color=GREEN, linewidth=2))
    ax.add_patch(FancyArrowPatch((9.78, 3.46), (8.08, 2.48), arrowstyle="-|>", mutation_scale=10, color=RED, linewidth=1.2))
    ax.text(10.25, 5.22, "Restricted engine:\nL7 unavailable", color=ORANGE, fontweight="bold", fontsize=9.8, ha="center", va="top", linespacing=1.15)
    ax.text(0.35, 0.55, "Passes are scoped to tested artifacts and contexts; inferential pairing needs a separate sampling or randomization basis.", fontsize=10.5, color=MUTED)
    return save_figure(fig, "figure_2_admission_flow")


def figure_synthetic(payload: dict[str, Any]) -> list[Path]:
    modes = [
        ("clean_deterministic", "Clean deterministic"),
        ("stateful_draw_shift", "Stateful draw shift"),
        ("wall_clock_search", "Injected clock budget"),
        ("process_global_state", "Injected process state"),
        ("uint32_seed_conversion", "Seed conversion"),
    ]
    rows: list[dict[str, Any]] = []
    status_map = {"pass": 0, "blocked": 1, "fail": 2, "admit": 3, "downgrade": 4, "suppress": 2}
    matrix: list[list[int]] = []
    mode_by_id = {
        str(row["mode"]): row
        for row in payload["modes"]
        if isinstance(row, dict) and isinstance(row.get("mode"), str)
    }
    for mode_id, label in modes:
        mode = mode_by_id[mode_id]
        audits = mode.get("audit") or mode.get("levels")
        if not isinstance(audits, list) or len(audits) != 8:
            raise EvidenceError(f"synthetic audit inventory malformed: {mode_id}")
        values: list[int] = []
        for item in audits:
            level = int(item["level"])
            status = str(item["status"])
            if status not in status_map:
                raise EvidenceError(f"unknown synthetic status {status}")
            values.append(status_map[status])
            rows.append({"mode": label, "level": level, "status": status})
        matrix.append(values)
    write_csv(FINAL / "source_data/figure_3_synthetic_matrix.csv", ["mode", "level", "status"], rows)
    from matplotlib.colors import ListedColormap
    fig, ax = plt.subplots(figsize=(10.8, 5.0))
    cmap = ListedColormap([BLUE, "#D5DDE3", RED, GREEN, ORANGE])
    ax.imshow(matrix, aspect="auto", cmap=cmap, vmin=-0.5, vmax=4.5)
    ax.set_xticks(range(8), [f"L{i}" for i in range(1, 9)])
    ax.set_yticks(range(len(modes)), [label for _, label in modes])
    ax.set_title("Synthetic conformance suite: detected failure and admission", loc="left", fontsize=18, fontweight="bold", color=INK, pad=16)
    symbols = {0: "P", 1: "-", 2: "F", 3: "A", 4: "D"}
    for y, row in enumerate(matrix):
        for x, value in enumerate(row):
            ax.text(x, y, symbols[value], ha="center", va="center", fontweight="bold", color="white" if value != 1 else INK, fontsize=11)
    for spine in ax.spines.values():
        spine.set_visible(False)
    legend = [
        Patch(color=BLUE, label="pass"), Patch(color="#D5DDE3", label="blocked"),
        Patch(color=RED, label="fail / suppress"), Patch(color=GREEN, label="admit"),
        Patch(color=ORANGE, label="downgrade"),
    ]
    ax.legend(handles=legend, ncol=5, frameon=False, bbox_to_anchor=(0, -0.15), loc="upper left")
    ax.text(0, -0.30, "The event-keyed repair aligns 5/5 shared events; the stateful stream aligns 1/5.", transform=ax.transAxes, color=MUTED, fontsize=10.5)
    fig.subplots_adjust(bottom=0.26)
    return save_figure(fig, "figure_3_synthetic_matrix")


def figure_stress(stress: dict[str, Any]) -> list[Path]:
    aliases = {
        "starmie/first": "Timed-search A / order 1",
        "starmie/second": "Timed-search A / order 2",
        "dipplin/first": "Timed-search B / order 1",
        "dipplin/second": "Timed-search B / order 2",
    }
    order = ["overall", "starmie/first", "starmie/second", "dipplin/first", "dipplin/second"]
    rows: list[dict[str, Any]] = []
    overall = stress["trace_disagreement"]
    rows.append({"stratum": "Overall", "clusters": 200, "estimate": overall["estimate"], "quantile_2_5": overall["bootstrap_95_ci"][0], "quantile_97_5": overall["bootstrap_95_ci"][1]})
    for name in order[1:]:
        summary = stress["strata"][name]["trace_disagreement"]
        rows.append({"stratum": aliases[name], "clusters": summary["clusters"], "estimate": summary["estimate"], "quantile_2_5": summary["bootstrap_95_ci"][0], "quantile_97_5": summary["bootstrap_95_ci"][1]})
    write_csv(FINAL / "source_data/figure_4_timed_search.csv", ["stratum", "clusters", "estimate", "quantile_2_5", "quantile_97_5"], rows)
    fig, ax = plt.subplots(figsize=(10.2, 5.4))
    y = list(range(len(rows)))[::-1]
    for index, (position, row) in enumerate(zip(y, rows, strict=True)):
        color = PURPLE if index == 0 else BLUE
        ax.errorbar(100 * row["estimate"], position, xerr=[[100 * (row["estimate"] - row["quantile_2_5"])], [100 * (row["quantile_97_5"] - row["estimate"])]], fmt="D" if index == 0 else "o", mfc="white", mec=color, mew=2, ms=9, ecolor=color, capsize=5, lw=2)
    ax.set_yticks(y, [row["stratum"] for row in rows])
    ax.set_xlim(0, 104)
    ax.set_xlabel("Seed-condition clusters with trace-projection disagreement (%)", fontsize=11.5)
    ax.set_title("Timed-search repeat/worker stress test", loc="left", fontsize=19, fontweight="bold", color=INK, pad=14)
    ax.grid(axis="x", color=GRID, linewidth=1)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    ax.text(0, -0.22, "Bars show frozen pooled or stratum-specific empirical reweighting quantiles; all four profiles stay together.", transform=ax.transAxes, color=MUTED, fontsize=10.2)
    return save_figure(fig, "figure_4_timed_search")


def figure_factorial(factorial: dict[str, Any]) -> list[Path]:
    labels = {
        "primary_c4_minus_c1": "Total intervention",
        "representation_main": "Representation contrast",
        "training_main": "Training contrast",
        "interaction": "Interaction",
    }
    order = ["primary_c4_minus_c1", "representation_main", "training_main", "interaction"]
    rows = []
    for name in order:
        item = factorial["contrasts"][name]
        rows.append({"contrast": labels[name], "estimate_pp": 100 * item["estimate"], "quantile_2_5_pp": 100 * item["bootstrap_95_ci"][0], "quantile_97_5_pp": 100 * item["bootstrap_95_ci"][1], "units": factorial["units"], "reweighting_draws": item["bootstrap_draws"]})
    write_csv(FINAL / "source_data/figure_5_factorial.csv", ["contrast", "estimate_pp", "quantile_2_5_pp", "quantile_97_5_pp", "units", "reweighting_draws"], rows)
    fig, ax = plt.subplots(figsize=(10.4, 5.2))
    y = list(range(len(rows)))[::-1]
    for index, (position, row) in enumerate(zip(y, rows, strict=True)):
        color = PURPLE if index == 0 else BLUE
        ax.errorbar(row["estimate_pp"], position, xerr=[[row["estimate_pp"] - row["quantile_2_5_pp"]], [row["quantile_97_5_pp"] - row["estimate_pp"]]], fmt="D" if index == 0 else "o", mfc="white", mec=color, mew=2, ms=9, ecolor=color, capsize=5, lw=2)
    ax.axvline(0, color=MUTED, linestyle="--", linewidth=1.5)
    ax.set_yticks(y, [row["contrast"] for row in rows])
    ax.set_xlabel("Win-rate contrast (percentage points)", fontsize=11.5)
    ax.set_title("Admitted fixed-battery factorial description", loc="left", fontsize=19, fontweight="bold", color=INK, pad=14)
    ax.grid(axis="x", color=GRID, linewidth=1)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    ax.text(0, -0.22, "2,000 seed-condition units; bars are stratified paired-unit reweighting quantiles, not confidence intervals.", transform=ax.transAxes, color=MUTED, fontsize=10.2)
    return save_figure(fig, "figure_5_factorial")


def write_tables(payloads: dict[str, dict[str, Any]]) -> list[Path]:
    stress = payloads["stress"]
    factorial = payloads["factorial"]
    tables: dict[str, str] = {
        "table_1_prior_work.tex": r"""\begin{table*}[t]
\caption{Relationship to prior methods. The present contribution is their operational integration for black-box agent evaluation, not priority over the component ideas.}
\label{tab:prior-work}
\footnotesize
\begin{tabularx}{\linewidth}{>{\raggedright\arraybackslash}p{0.18\linewidth}>{\raggedright\arraybackslash}p{0.28\linewidth}>{\raggedright\arraybackslash}X}
\toprule
Prior area & Established contribution & Role here \\
\midrule
Common random numbers & Conditions for covariance and variance reduction; synchronization depends on model structure and event timing \cite{glasserman1992crn} & Motivates separating a matched integer from an evidenced coupling. \\
Streams and substreams & Organized independent replications and synchronized streams \cite{lecuyer2002streams} & White-box design option; stream labels alone do not prove semantic assignment. \\
Paired-seed evaluation & Precision can improve when seed-level outcomes are favorably correlated \cite{sharma2025pairedseeds} & Supports pairing when its implemented relationship is validated. \\
Event-keyed and counter-based randomness & Stable event keys prevent draw shifts within a declared event ontology; counter-based generators provide random access \cite{buffalo2026eventkeyed,salmon2011parallel} & Implemented only in the synthetic repair; unavailable inside the restricted engine. \\
Agent evidence records and deterministic workflow tests & Rollout records preserve views, reporting rules, and drops; evaluation contracts turn workflow changes into auditable tests \cite{masters2026rolloutcards,anand2026aeval} & Complementary evidence preservation and testing; neither validates paired stochastic coupling or admits a statistical claim class. \\
Trace-contract assurance & Message--Action Traces support contracts, replay, perturbation, localization, and governance \cite{paduraru2026traceassurance} & Closest trace framework; it does not distinguish identical-arm repeatability from cross-arm event alignment or suppress paired inference. \\
Reproducibility and RL evaluation & Variation, units, estimation, and transparent reporting are essential \cite{bouthillier2019reproducible,patterson2024empirical,agarwal2021statistical,pineau2021reproducibility} & Supplies the broader empirical-design boundary. \\
Software and simulation testing & A/A, metamorphic relations, and verification/validation test implementations and models \cite{kohavi2010aa,lin2020exploratorymt,raunak2021metamorphic,sargent2013verification} & Informs trace invariants and fail-closed conformance checks. \\
Work versus time budgets & Search time allocation is established prior art \cite{baier2016timemanagement} & Justifies auditing clock-bounded search without claiming its invention. \\
\bottomrule
\end{tabularx}
\end{table*}
""",
        "table_2_protocol_stages.tex": r"""\begin{table*}[t]
\caption{Protocol stages, required evidence, strongest permitted statement, and failure action. Every pass is local to the tested artifacts, schedule, trace schema, and execution contexts.}
\label{tab:protocol}
\footnotesize
\begin{tabularx}{\linewidth}{>{\raggedright\arraybackslash}p{0.16\linewidth}>{\raggedright\arraybackslash}p{0.25\linewidth}>{\raggedright\arraybackslash}p{0.25\linewidth}>{\raggedright\arraybackslash}X}
\toprule
Stage & Evidence & Permitted statement & Failure action \\
\midrule
1 Artifact identity & Hashes for engine, policies, opponents, protocol, code, and configuration & The evaluated bytes are identified. & Quarantine missing or drifting artifacts. \\
2 Seed namespace & Scheduled seed, exact boundary value, conversion rule, and collision audit & The claimed boundary seed was supplied and units remain distinct. & Correct the adapter or schedule and rerun. \\
3 Schedule parity & Row equality for opponent, order, seat, seed, environment, and limits & A complete matched schedule was attempted. & Reject unequal or incomplete pairs. \\
4 Identical-arm parity & Separate A/A executions compared through the digest and byte count of the recorded trace projection & The compared fields repeat on exercised A/A trajectories. & Suppress the affected paired comparison. \\
5 Repeat/worker parity & Fresh repeats, worker counts, enqueue orders, and process lifecycles & Within-arm traces repeat in tested contexts. & Freeze a passing context or model run variation. \\
6 Source audit & Bounded Python source-pattern scan; binary internals remain unassessed & Candidate mechanisms and the uninspected boundary are recorded. & Control, dynamically test, or narrow the estimand and wording. \\
7 Event alignment & Stable event identifiers and equal values for shared exogenous events & Event-aligned coupling for the logged ontology. & Retain at most bounded descriptive seed-indexed wording. \\
8 Statistical admission & Frozen map from gates to estimand, unit, descriptive summary or justified uncertainty procedure, target, and wording & Level 6 permits a fixed-battery descriptive schedule-indexed contrast and empirical reweighting only; inferential pairing requires an additional sampling or randomization basis. & Admit, downgrade, or suppress automatically. \\
\bottomrule
\end{tabularx}
\end{table*}
""",
        "table_3_prospective_results.tex": f"""\\begin{{table*}}[t]
\\caption{{Prospective validation results. Trace-projection digest and byte-count fields were captured for preflight and stress executions but not for factorial outcome rows.}}
\\label{{tab:prospective-results}}
\\footnotesize
\\begin{{tabularx}}{{\\linewidth}}{{>{{\\raggedright\\arraybackslash}}p{{0.18\\linewidth}}>{{\\centering\\arraybackslash}}p{{0.10\\linewidth}}>{{\\centering\\arraybackslash}}p{{0.09\\linewidth}}>{{\\centering\\arraybackslash}}p{{0.15\\linewidth}}>{{\\centering\\arraybackslash}}p{{0.12\\linewidth}}>{{\\raggedright\\arraybackslash}}X}}
\\toprule
Stage & Units/clusters & Executions & Trace-record disagreement & Outcome disagreement & Admission \\\\
\\midrule
Deterministic preflight & {payloads['preflight']['trajectory_units']:,} & {payloads['preflight']['executions']:,} & 0 & 0 & Qualify acquisition for the newly frozen five-context scope; later-seed transfer remains an assumption. \\\\
Timed-search stress & {stress['clusters']} & {stress['executions']} & {stress['trace_disagreement_clusters']} & {stress['outcome_disagreement_clusters']} & Reject exact repeatability for at least one exercised seed condition. \\\\
Factorial repeated control & {factorial['units']:,} per cell & {factorial['games']:,} games & --- & {factorial['control_mismatch_units']} & Admit a fixed-battery descriptive schedule-indexed contrast plus reweighting sensitivity; no inferential or Level-7 claim. \\\\
\\bottomrule
\\end{{tabularx}}
\\end{{table*}}
""",
        "table_4_factorial.tex": r"""\begin{table}[t]
\caption{Admitted fixed-battery factorial contrasts. Values are percentage-point win-rate differences with the 2.5th and 97.5th percentiles of the frozen stratified paired-unit reweighting distribution; these are not confidence intervals.}
\label{tab:factorial}
\small
\begin{tabularx}{\columnwidth}{>{\raggedright\arraybackslash}Xrrr}
\toprule
Contrast & Estimate & 2.5th & 97.5th \\
\midrule
Total intervention & \PrimaryEstimatePP & \PrimaryLowPP & \PrimaryHighPP \\
Representation & \RepresentationEstimatePP & \RepresentationLowPP & \RepresentationHighPP \\
Training & \TrainingEstimatePP & \TrainingLowPP & \TrainingHighPP \\
Interaction & \InteractionEstimatePP & \InteractionLowPP & \InteractionHighPP \\
\bottomrule
\end{tabularx}
\end{table}
""",
    }
    outputs: list[Path] = []
    for name, content in tables.items():
        path = FINAL / "tables" / name
        path.write_text(content, encoding="utf-8")
        outputs.append(path)
    return outputs


def write_cover_letter(payloads: dict[str, dict[str, Any]]) -> Path:
    """Generate central cover-letter counts from the validated evidence objects."""
    preflight = payloads["preflight"]
    stress = payloads["stress"]
    factorial = payloads["factorial"]
    content = f"""# Draft cover letter — do not submit

**Blocked pending the human actions in `HUMAN_ACTIONS.md`, especially release
ownership, redistribution authority, licensing, author approval, and archive
metadata.**

Dear Editors,

We seek consideration of “A Protocol for Validating Pairing Assumptions in
Seed-Matched Evaluations of Black-Box Game-Playing Agents” as an **APS Open
Science Protocol Article**.

Recording the same seed in two agent evaluations establishes a matched
schedule; it does not establish repeatable execution or semantic alignment of
random events after the agents' paths diverge. The article presents an
executable, fail-closed protocol that verifies artifacts and boundary seeds,
checks schedule parity, compares an identical-arm trace projection across
execution contexts, audits bounded stochastic sources, and maps gate evidence
to the statistical claim that may be admitted, downgraded, or suppressed.

The technical contribution is the operational integration of established
common-random-number theory, structured random streams, trace preservation,
deterministic testing, and event-keyed randomness into a black-box pairing
validation workflow. A self-contained conformance suite exercises clean,
draw-shift, clock-budget, process-state, and seed-conversion modes, rejects
schema or manifest tampering, and supplies a machine-readable admission map
with exhaustive tests for result independence, prerequisite monotonicity,
failure dominance, projection scoping, determinism, unknown-state
fail-closedness, and claim-class ordering. This generic executable taxonomy is a
post-acquisition formalization; the prospectively frozen experiment-specific
rules remain authoritative for the completed case study.

The case study found zero required mismatches across
{preflight['executions']:,} deterministic executions, while
{stress['trace_disagreement_clusters']} of {stress['clusters']} fixed
timed-search seed-condition clusters disagreed on the complete recorded trace
projection, with pronounced context heterogeneity.
The frozen rule suppressed an apparently favorable historical comparison after
its repeated-control gate failed. For a later {factorial['units']:,}-unit-per-cell
comparison, Git history places the rule and acquisition-gate commit before the
retained result artifacts; changing the outcome payload while holding gate
evidence fixed leaves admission unchanged. Its five deterministic contexts were
a newly frozen, audit-informed target. The qualification preflight used a
different seed range, and candidate factorial rows contain no trace digests.
The admitted output is therefore a fixed-battery descriptive contrast with
empirical reweighting sensitivity, not a confidence interval, p-value, or
population-effect claim.

This contribution is narrower than Rollout Cards, trace-assurance frameworks,
AEVAL, and event-keyed randomness individually: those works provide evidence
records, trace contracts, deterministic workflow tests, or white-box stochastic
repair, whereas this article connects within-arm repeatability and cross-arm
alignment evidence to automatic admission or suppression of paired statistical
wording in a restricted black-box setting.

The engine-independent computational package contains the synthetic implementation,
machine-readable admission rules, worked example, tests, processed diagnostics,
analysis code, protocols, source data for generated figures, and integrity
manifests. It excludes the tournament engine and source, engine binaries,
third-party opponent packages, game assets and metadata, policy packages and
weights, private replay observations, and raw restricted traces.
Ownership, redistribution authority, an approved license, archival release,
and DOI are not established; the package therefore must not be described or
distributed as public software.

OpenAI Codex, using a GPT-5-family model whose exact deployed snapshot was not
exposed, assisted under human direction with literature synthesis, protocol
reasoning, code and test generation, statistical checking, figure generation,
drafting, and adversarial review. The manuscript and machine-readable log state
the verification boundary; no AI system is an author, and no generative-image
system was used.

Sincerely,

**[Corresponding-author metadata requires human completion; see
`HUMAN_ACTIONS.md`.]**
"""
    output = FINAL / "cover_letter.md"
    output.write_text(content, encoding="utf-8")
    return output


def copy_source_summaries(payloads: dict[str, dict[str, Any]]) -> list[Path]:
    outputs: list[Path] = []
    for stale_name in (
        "validated_synthetic.json", "validated_combined.json",
        "validated_preflight.json", "validated_stress.json",
        "validated_factorial.json",
    ):
        stale = FINAL / "source_data" / stale_name
        if stale.exists() and not stale.is_symlink():
            stale.unlink()

    synthetic_path = FINAL / "source_data/processed_synthetic.json"
    write_json(synthetic_path, payloads["synthetic"])
    outputs.append(synthetic_path)

    preflight = payloads["preflight"]
    preflight_contexts = {
        name: f"deterministic-{index}"
        for index, name in enumerate(
            sorted({str(row["opponent"]) for row in preflight["rows"]}), start=1
        )
    }
    processed_preflight = {
        key: preflight[key]
        for key in (
            "schema_version", "analysis_id", "status", "protocol_commit",
            "admission_decision", "arms", "opponents", "trajectory_units",
            "executions", "mismatch_units", "trace_mismatch_units",
            "outcome_mismatch_units", "error_mismatch_units",
            "decision_count_mismatch_units", "claim_boundary",
        )
    }
    processed_preflight["rows"] = [
        {
            "arm": row["arm"],
            "context": preflight_contexts[str(row["opponent"])],
            "trajectory_units": row["trajectory_units"],
            "executions": row["executions"],
            "mismatch_units": row["mismatch_units"],
            "trace_mismatch_units": row["trace_mismatch_units"],
            "outcome_mismatch_units": row["outcome_mismatch_units"],
            "error_mismatch_units": row["error_mismatch_units"],
            "decision_count_mismatch_units": row["decision_count_mismatch_units"],
            "passed": row["passed"],
            "source_sha256": row["source_sha256"],
        }
        for row in preflight["rows"]
    ]
    preflight_path = FINAL / "source_data/processed_preflight.json"
    write_json(preflight_path, processed_preflight)
    outputs.append(preflight_path)

    stress = payloads["stress"]
    stress_names = sorted(
        {str(row["opponent"]) for row in stress["cluster_rows"]},
        key=lambda name: -sum(
            int(row["trace_disagreement"])
            for row in stress["cluster_rows"]
            if row["opponent"] == name
        ),
    )
    stress_contexts = {
        name: f"timed-search-{chr(65 + index)}"
        for index, name in enumerate(stress_names)
    }
    processed_stress = {
        key: stress[key]
        for key in (
            "schema_version", "analysis_id", "status", "protocol_commit",
            "clusters", "executions", "trace_disagreement_clusters",
            "outcome_disagreement_clusters",
            "decision_count_disagreement_clusters", "error_disagreement_clusters",
            "policy_error_present_clusters",
        )
    }
    processed_stress["pevl_level_6_boundary"] = (
        "recorded trace mismatches and bounded source inspection identify "
        "plausible mechanisms in the exercised executions; no retained evidence "
        "supports an earliest-divergence localization or a unique causal source"
    )
    def reweighting_view(summary: dict[str, Any], role: str) -> dict[str, Any]:
        view = {
            "estimate": summary["estimate"],
            "quantiles_2_5_97_5": summary["bootstrap_95_ci"],
            "reweighting_draws": summary["bootstrap_draws"],
            "reweighting_seed": summary["bootstrap_seed"],
            "role": role,
            "inferential_status": (
                "descriptive empirical reweighting of a fixed battery; "
                "not a confidence interval or population inference"
            ),
        }
        if "clusters" in summary:
            view["clusters"] = summary["clusters"]
        return view

    processed_stress["fixed_battery_scope"] = (
        "four fixed timed-search opponent-by-order strata; 50 clusters per stratum"
    )
    processed_stress["trace_disagreement"] = reweighting_view(
        stress["trace_disagreement"],
        "prespecified pooled whole-cluster reweighting; context composition may vary",
    )
    processed_stress["cluster_rows"] = [
        {
            "context": stress_contexts[str(row["opponent"])],
            "actual_order": row["actual_order"],
            "trace_disagreement": row["trace_disagreement"],
            "outcome_disagreement": row["outcome_disagreement"],
            "decision_count_disagreement": row["decision_count_disagreement"],
            "error_disagreement": row["error_disagreement"],
            "policy_error_present": row["policy_error_present"],
        }
        for row in stress["cluster_rows"]
    ]
    processed_stress["strata"] = {
        f"{stress_contexts[name]}/{order}": {
            **{
                field: field_value
                for field, field_value in value.items()
                if field != "trace_disagreement"
            },
            "trace_disagreement": reweighting_view(
                value["trace_disagreement"],
                "stratum-specific whole-cluster empirical reweighting",
            ),
        }
        for key, value in stress["strata"].items()
        for name, order in [key.split("/", 1)]
    }
    fixed_composition = stress_fixed_composition_reweighting(stress)
    processed_stress["fixed_composition_reweighting_sensitivity"] = {
        "estimate": fixed_composition["estimate"],
        "quantiles_2_5_97_5": fixed_composition["quantiles_2_5_97_5"],
        "reweighting_draws": fixed_composition["draws"],
        "reweighting_seed": fixed_composition["seed"],
        "stratum_weighting": fixed_composition["stratum_weighting"],
        "reweighting_unit": fixed_composition["reweighting_unit"],
        "role": fixed_composition["role"],
        "inferential_status": (
            "post-acquisition descriptive sensitivity; not a confidence "
            "interval or population inference"
        ),
        "stratum_disagreement_counts": {
            f"{stress_contexts[name]}/{order}": count
            for key, count in fixed_composition[
                "stratum_disagreement_counts"
            ].items()
            for name, order in [key.split("/", 1)]
        },
    }
    stress_path = FINAL / "source_data/processed_stress.json"
    write_json(stress_path, processed_stress)
    outputs.append(stress_path)

    factorial = payloads["factorial"]
    processed_factorial = {
        key: factorial[key]
        for key in (
            "schema_version", "analysis_id", "status", "protocol_commit",
            "admission_decision", "units", "games",
            "control_mismatch_units", "cell_win_rates",
            "simple_effects_descriptive",
        )
    }
    processed_factorial["fixed_battery_target"] = factorial["target_population"]
    processed_factorial["contrasts"] = {
        name: {
            "estimate": value["estimate"],
            "quantiles_2_5_97_5": value["bootstrap_95_ci"],
            "reweighting_draws": value["bootstrap_draws"],
            "reweighting_seed": value["bootstrap_seed"],
            "reweighting": (
                "stratified paired-unit empirical reweighting within each of "
                "ten fixed opponent-by-order strata"
            ),
            "inferential_status": (
                "fixed-battery descriptive sensitivity; not a confidence "
                "interval, hypothesis test, or population effect"
            ),
        }
        for name, value in factorial["contrasts"].items()
    }
    processed_factorial["qualification_transfer"] = (
        "preflight and factorial used different seed ranges; candidate factorial "
        "rows contain no trace digests, so transfer is a bounded assumption"
    )
    processed_factorial["pevl_levels"] = {
        "levels_1_to_5": (
            "qualification supported only for frozen artifacts, schedules, "
            "trace projection, and exercised preflight contexts"
        ),
        "level_6": (
            "admits only a fixed-battery descriptive seed-indexed contrast and "
            "empirical reweighting sensitivity"
        ),
        "level_7": (
            "not established because the restricted engine exposes no semantic "
            "event identifiers or event-keyed streams"
        ),
        "level_8": (
            "no confidence interval, hypothesis test, population effect, "
            "counterfactual, or full-CRN wording admitted"
        ),
    }
    factorial_path = FINAL / "source_data/processed_factorial.json"
    write_json(factorial_path, processed_factorial)
    outputs.append(factorial_path)

    seed_audit = payloads["seed_audit"]
    processed_seed_audit = {
        "conversion_rule": seed_audit["conversion_rule"],
        "uint32_max": seed_audit["uint32_max"],
        "historical_fresh_confirmation": seed_audit["historical_fresh_confirmation"],
        "historical_prospective_engine_seed_overlap": seed_audit["historical_prospective_engine_seed_overlap"],
        "prospective_all": seed_audit["prospective_all"],
        "prospective_study_summary": {
            study: {
                "contexts": len(contexts),
                "scheduled_count": sum(int(row["scheduled_count"]) for row in contexts.values()),
                "all_collision_free": all(bool(row["passed_no_collision"]) for row in contexts.values()),
            }
            for study, contexts in seed_audit["prospective_by_schedule"].items()
        },
        "prospective_passed": seed_audit["prospective_passed"],
        "protocol_commit": seed_audit["provenance"]["git_commit"],
    }
    seed_path = FINAL / "source_data/processed_seed_namespace_audit.json"
    write_json(seed_path, processed_seed_audit)
    outputs.append(seed_path)

    stochastic_audit = payloads["stochastic_audit"]
    processed_stochastic_audit = {
        "schema_version": stochastic_audit["schema_version"],
        "audit_claim": stochastic_audit["audit_claim"],
        "audit_levels": stochastic_audit["audit_levels"],
        "category_definitions": stochastic_audit["category_definitions"],
        "level_results": stochastic_audit["level_results"],
        "scope_limits": stochastic_audit["scope_limits"],
        "protocol_commit": stochastic_audit["provenance"]["git_commit"],
        "inventory_summary": {
            "artifacts": len(stochastic_audit["inventory"]),
            "source_assessed_package_trees": sum(
                item["source_audit"]["status"] == "completed_static_python_ast_scan"
                for item in stochastic_audit["inventory"]
            ),
            "binary_source_assessments": sum(
                item["artifact_kind"] == "file" and item["source_audit"]["status"] != "not_assessed"
                for item in stochastic_audit["inventory"]
            ),
            "all_frozen_hashes_match": all(item["hash_match"] for item in stochastic_audit["inventory"]),
        },
    }
    stochastic_path = FINAL / "source_data/processed_stochastic_source_audit.json"
    write_json(stochastic_path, processed_stochastic_audit)
    outputs.append(stochastic_path)

    identity = {
        "protocol_commit": PROTOCOL_COMMIT,
        "inputs": {
            label: {"role": label, "sha256": expected_hash}
            for label, (path, expected_hash) in INPUTS.items()
        },
        "generator": {
            "path": str(SCRIPT.relative_to(ROOT)),
            "sha256": sha256(SCRIPT),
        },
    }
    path = FINAL / "source_data/artifact_identity.json"
    write_json(path, identity)
    outputs.append(path)
    return outputs


def main() -> int:
    payloads = validate_inputs()
    generated: list[Path] = []
    generated.extend(copy_source_summaries(payloads))
    generated.append(write_macros(payloads))
    generated.extend(write_tables(payloads))
    generated.append(write_cover_letter(payloads))
    generated.extend(figure_distinctions())
    generated.extend(figure_admission_flow())
    generated.extend(figure_synthetic(payloads["synthetic"]))
    generated.extend(figure_stress(payloads["stress"]))
    generated.extend(figure_factorial(payloads["factorial"]))
    report = {
        "status": "PASS",
        "protocol_commit": PROTOCOL_COMMIT,
        "generated": [str(path.relative_to(FINAL)) for path in generated],
        "generated_sha256": {
            str(path.relative_to(FINAL)): sha256(path) for path in generated
        },
    }
    write_json(FINAL / "source_data/build_report.json", report)
    print(json.dumps({"status": "PASS", "files": len(generated)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
