#!/usr/bin/env python3
"""Rebuild the five review figures and four compact tables from released data."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


SCRIPT = Path(__file__).resolve()
RELEASE = SCRIPT.parents[1]
SOURCE = RELEASE / "source_data"
FIGURES = RELEASE / "figures"
TABLES = RELEASE / "tables"
FIXED_DATE = datetime(2026, 8, 24, tzinfo=timezone.utc)
INK = "#1f2933"
MUTED = "#5f6b75"
BLUE = "#466f8a"
GREEN = "#4d7a68"
ORANGE = "#b57a35"
RED = "#9a4f4f"
PURPLE = "#6f638b"


def load_json(name: str) -> Any:
    return json.loads((SOURCE / name).read_text(encoding="utf-8"))


def load_csv(name: str) -> list[dict[str, str]]:
    with (SOURCE / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def save_figure(figure: plt.Figure, stem: str) -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    figure.savefig(
        FIGURES / f"{stem}.pdf",
        bbox_inches="tight",
        metadata={"Creator": "build_figures_tables.py", "CreationDate": FIXED_DATE, "ModDate": FIXED_DATE},
    )
    figure.savefig(
        FIGURES / f"{stem}.png",
        dpi=180,
        bbox_inches="tight",
        metadata={"Software": "build_figures_tables.py"},
    )
    plt.close(figure)


def figure_1() -> None:
    rows = load_json("figure_1_distinctions.json")
    figure, axis = plt.subplots(figsize=(10.2, 3.6))
    axis.set_xlim(0, 3)
    axis.set_ylim(0, 1)
    axis.axis("off")
    colors = (BLUE, PURPLE, GREEN)
    for index, (row, color) in enumerate(zip(rows, colors, strict=True)):
        x = index + 0.08
        box = FancyBboxPatch((x, 0.15), 0.84, 0.7, boxstyle="round,pad=0.025", facecolor="white", edgecolor=color, linewidth=2)
        axis.add_patch(box)
        axis.text(x + 0.42, 0.73, row["stage"], ha="center", va="center", fontsize=12, fontweight="bold", color=color)
        axis.text(x + 0.42, 0.55, row["question"], ha="center", va="center", fontsize=10, color=INK, wrap=True)
        axis.text(x + 0.42, 0.36, row["evidence"], ha="center", va="center", fontsize=8.3, color=MUTED, wrap=True)
        axis.text(x + 0.42, 0.20, "permits: " + row["permits"], ha="center", va="center", fontsize=8.3, color=INK, wrap=True)
        if index < 2:
            axis.add_patch(FancyArrowPatch((x + 0.87, 0.5), (x + 1.05, 0.5), arrowstyle="-|>", mutation_scale=15, linewidth=1.5, color=MUTED))
    axis.set_title("Matched schedule, repeatability, and event alignment are distinct", fontsize=14, color=INK, pad=10)
    save_figure(figure, "figure_1_distinctions")


def figure_2() -> None:
    payload = load_json("figure_2_admission_flow.json")
    levels = payload["levels"]
    figure, axis = plt.subplots(figsize=(11.4, 4.0))
    axis.set_xlim(0, 8)
    axis.set_ylim(0, 2.2)
    axis.axis("off")
    for index, row in enumerate(levels):
        x = index + 0.18
        box = FancyBboxPatch((x, 1.15), 0.78, 0.62, boxstyle="round,pad=0.02", facecolor="#f7f9fa", edgecolor=BLUE, linewidth=1.5)
        axis.add_patch(box)
        axis.text(x + 0.39, 1.61, row["level"], ha="center", va="center", fontsize=10, fontweight="bold", color=BLUE)
        axis.text(x + 0.39, 1.36, row["label"], ha="center", va="center", fontsize=8, color=INK, wrap=True)
        if index < len(levels) - 1:
            axis.add_patch(FancyArrowPatch((x + 0.8, 1.46), (x + 1.0, 1.46), arrowstyle="-|>", mutation_scale=12, color=MUTED))
    axis.text(3.65, 0.75, payload["success_action"], ha="center", fontsize=10, color=GREEN, fontweight="bold")
    axis.text(3.65, 0.35, payload["failure_action"], ha="center", fontsize=10, color=RED, fontweight="bold")
    axis.text(6.55, 0.75, payload["restricted_engine_boundary"], ha="center", fontsize=9, color=ORANGE)
    axis.set_title("Prospectively frozen claim-admission flow", fontsize=14, color=INK)
    save_figure(figure, "figure_2_admission_flow")


def figure_3() -> None:
    rows = load_csv("figure_3_synthetic_matrix.csv")
    modes = list(dict.fromkeys(row["mode"] for row in rows))
    levels = sorted({int(row["level"]) for row in rows})
    codes = {"pass": 0, "admit": 0, "fail": 1, "downgrade": 1, "blocked": 2, "suppress": 2}
    matrix = np.asarray([[codes[next(row["status"] for row in rows if row["mode"] == mode and int(row["level"]) == level)] for level in levels] for mode in modes])
    from matplotlib.colors import ListedColormap
    figure, axis = plt.subplots(figsize=(10.0, 4.8))
    axis.imshow(matrix, aspect="auto", cmap=ListedColormap([GREEN, ORANGE, RED]), vmin=0, vmax=2)
    axis.set_xticks(range(len(levels)), [f"L{level}" for level in levels])
    axis.set_yticks(range(len(modes)), modes)
    axis.set_xlabel("Protocol level")
    axis.set_title("Synthetic conformance modes trigger the intended gates", fontsize=14, color=INK)
    for y, mode in enumerate(modes):
        for x, level in enumerate(levels):
            status = next(row["status"] for row in rows if row["mode"] == mode and int(row["level"]) == level)
            axis.text(x, y, status, ha="center", va="center", fontsize=7.3, color="white", fontweight="bold")
    save_figure(figure, "figure_3_synthetic_matrix")


def figure_4() -> None:
    rows = load_csv("figure_4_timed_search.csv")
    labels = [row["stratum"] for row in rows]
    estimates = np.asarray([float(row["estimate"]) for row in rows])
    low = np.asarray([float(row["ci_low"]) for row in rows])
    high = np.asarray([float(row["ci_high"]) for row in rows])
    y = np.arange(len(rows))[::-1]
    figure, axis = plt.subplots(figsize=(9.2, 4.3))
    axis.errorbar(estimates, y, xerr=np.vstack([estimates - low, high - estimates]), fmt="o", color=PURPLE, ecolor=PURPLE, capsize=4)
    axis.set_yticks(y, labels)
    axis.set_xlim(0, 1.02)
    axis.set_xlabel("Trace-digest disagreement proportion")
    axis.grid(axis="x", alpha=0.25)
    axis.set_title("Timed-search repeated executions disagree within seed clusters", fontsize=14, color=INK)
    save_figure(figure, "figure_4_timed_search")


def figure_5() -> None:
    rows = load_csv("figure_5_factorial.csv")
    labels = [row["contrast"] for row in rows]
    estimates = np.asarray([float(row["estimate_pp"]) for row in rows])
    low = np.asarray([float(row["ci_low_pp"]) for row in rows])
    high = np.asarray([float(row["ci_high_pp"]) for row in rows])
    y = np.arange(len(rows))[::-1]
    figure, axis = plt.subplots(figsize=(9.2, 4.0))
    axis.axvline(0, color=MUTED, linewidth=1)
    axis.errorbar(estimates, y, xerr=np.vstack([estimates - low, high - estimates]), fmt="o", color=BLUE, ecolor=BLUE, capsize=4)
    axis.set_yticks(y, labels)
    axis.set_xlabel("Paired win-rate contrast (percentage points)")
    axis.grid(axis="x", alpha=0.25)
    axis.set_title("Admitted factorial contrasts are compatible with small effects in either direction", fontsize=13, color=INK)
    save_figure(figure, "figure_5_factorial")


def write_tables() -> None:
    TABLES.mkdir(parents=True, exist_ok=True)
    (TABLES / "table_1_prior_work.tex").write_text(
        "\\begin{tabular}{p{0.27\\linewidth}p{0.31\\linewidth}p{0.34\\linewidth}}\n"
        "\\toprule\nArea & Established contribution & Role here \\\\\n+\\midrule\n"
        "Common random numbers & Conditions and stream management & Operational evidence gates \\\\\n+"
        "Paired-seed evaluation & Shared schedules and uncertainty & Trace-based admission checks \\\\\n+"
        "Metamorphic and A/A testing & Invariance-based software checks & Repeat and worker profiles \\\\\n+"
        "Simulation verification & Credibility and validation practice & Fail-closed artifact workflow \\\\\n+"
        "\\bottomrule\n\\end{tabular}\n",
        encoding="utf-8",
    )
    (TABLES / "table_2_protocol_stages.tex").write_text(
        "\\begin{tabular}{llll}\n\\toprule\nStage & Evidence & Permitted statement & Failure action \\\\\n+\\midrule\n"
        "Schedule & Seeds, order, seat & Matched schedule & Correct or suppress \\\\\n+"
        "Repeatability & Digest and byte count & Bounded execution parity & Downgrade or suppress \\\\\n+"
        "Event alignment & Event/value pairs & Ontology-bounded coupling & Seed-matched wording only \\\\\n+"
        "Admission & Frozen map & Scoped statistical claim & Suppress disallowed claim \\\\\n+"
        "\\bottomrule\n\\end{tabular}\n",
        encoding="utf-8",
    )
    historical = json.loads((RELEASE / "data/processed/historical_summary.json").read_text(encoding="utf-8"))
    preflight = json.loads((RELEASE / "data/processed/preflight_summary.json").read_text(encoding="utf-8"))
    stress = json.loads((RELEASE / "data/processed/timed_search_stress.json").read_text(encoding="utf-8"))
    (TABLES / "table_3_prospective_results.tex").write_text(
        "\\begin{tabular}{lrrl}\n\\toprule\nAudit & Units & Mismatches & Decision \\\\\n+\\midrule\n"
        f"Historical outcome record & {historical['units']} & {historical['outcome_record_mismatches']} & historical contrasts suppressed \\\\\n+"
        f"Deterministic preflight & {preflight['trajectory_units']} & {preflight['trace_mismatch_units']} & passed \\\\\n+"
        f"Timed-search trace digest & {stress['clusters']} & {stress['trace_disagreement_clusters']} & exact repeatability rejected \\\\\n+"
        "\\bottomrule\n\\end{tabular}\n",
        encoding="utf-8",
    )
    factorial = json.loads((RELEASE / "data/processed/factorial_summary.json").read_text(encoding="utf-8"))
    labels = {
        "primary_c4_minus_c1": "Total intervention",
        "representation_main": "Representation",
        "training_main": "Training",
        "interaction": "Interaction",
    }
    lines = ["\\begin{tabular}{lrr}", "\\toprule", "Contrast & Estimate (pp) & 95\\% interval (pp) \\\\", "\\midrule"]
    for key in labels:
        row = factorial["contrasts"][key]
        low, high = row["bootstrap_95_ci"]
        lines.append(f"{labels[key]} & {100 * row['estimate']:.2f} & [{100 * low:.2f}, {100 * high:.2f}] \\\\")
    lines.extend(["\\bottomrule", "\\end{tabular}", ""])
    (TABLES / "table_4_factorial.tex").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    for function in (figure_1, figure_2, figure_3, figure_4, figure_5):
        function()
    write_tables()
    outputs = sorted(path.relative_to(RELEASE).as_posix() for root in (FIGURES, TABLES) for path in root.iterdir() if path.is_file())
    print(json.dumps({"status": "PASS", "outputs": outputs}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
