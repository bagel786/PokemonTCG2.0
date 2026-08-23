#!/usr/bin/env python3
"""Generate all six manuscript figures from machine-readable results."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Polygon


SCRIPT_DIR = Path(__file__).resolve().parent
IS_RELEASE = (SCRIPT_DIR.parent / "data/processed").is_dir()
ROOT = SCRIPT_DIR.parent if IS_RELEASE else Path(__file__).resolve().parents[2]
DATA = ROOT / "data/processed" if IS_RELEASE else ROOT / "paper/data"
OUT = ROOT / "figures" if IS_RELEASE else ROOT / "paper/figures"
BLUE = "#0072B2"
ORANGE = "#E69F00"
PURPLE = "#6A3D9A"
GRAY = "#5C6770"
LIGHT = "#E8EEF2"


def load(path: str) -> dict:
    return json.loads((DATA / path).read_text(encoding="utf-8"))


def setup() -> None:
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.titlesize": 10,
        "axes.labelsize": 9,
        "legend.fontsize": 8,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "savefig.bbox": "tight",
    })


def save(fig: plt.Figure, stem: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{stem}.pdf", metadata={
        "Title": stem, "Creator": "paper/scripts/build_figures.py"
    })
    fig.savefig(OUT / f"{stem}.png", dpi=300, metadata={"Software": "Matplotlib"})
    plt.close(fig)


def box(ax, x: float, y: float, width: float, height: float, text: str,
        color: str = BLUE, hatch: str | None = None) -> None:
    patch = FancyBboxPatch(
        (x, y), width, height, boxstyle="round,pad=0.025,rounding_size=0.025",
        linewidth=1.4, edgecolor=color, facecolor="white", hatch=hatch,
    )
    ax.add_patch(patch)
    ax.text(x + width / 2, y + height / 2, text, ha="center", va="center", color="#17212B")


def arrow(ax, start: tuple[float, float], end: tuple[float, float], color: str = GRAY) -> None:
    ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=12,
                                 linewidth=1.2, color=color))


def figure_pipeline() -> None:
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    labels = [
        (0.03, "Partial\nobservation"),
        (0.21, "Variable legal\naction set"),
        (0.39, "Identity-aware\noption features"),
        (0.57, "Frozen trunk +\ntrained heads"),
        (0.75, "Runtime policy\n+ fixed shields"),
    ]
    for index, (x, label) in enumerate(labels):
        box(ax, x, 0.60, 0.14, 0.18, label, [GRAY, BLUE, ORANGE, PURPLE, BLUE][index],
            [None, "//", "..", "xx", "\\\\"][index])
        if index:
            arrow(ax, (x - 0.04, 0.69), (x, 0.69))
    box(ax, 0.20, 0.18, 0.18, 0.17, "C0 and candidate\nsame seed/order/seat", PURPLE, "//")
    box(ax, 0.47, 0.18, 0.18, 0.17, "Deterministic\nthird-party engine", GRAY, "..")
    box(ax, 0.74, 0.18, 0.18, 0.17, "Paired outcome\nand uncertainty", ORANGE, "xx")
    arrow(ax, (0.89, 0.60), (0.83, 0.35))
    arrow(ax, (0.38, 0.265), (0.47, 0.265))
    arrow(ax, (0.65, 0.265), (0.74, 0.265))
    ax.text(0.03, 0.93, "Policy and matched evaluation pipeline", fontsize=12, weight="bold")
    ax.text(0.03, 0.04, "Common random numbers define paired units; the engine and opponent population remain frozen.",
            color=GRAY)
    save(fig, "fig01_pipeline")


def figure_aliasing(representation: dict) -> None:
    corpus = representation["corpus"]
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.3), gridspec_kw={"wspace": 0.28})
    for ax in axes:
        ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    left, right = axes
    left.set_title("Before: distinct actions alias", loc="left", weight="bold")
    box(left, 0.03, 0.66, 0.29, 0.14, "PLAY item α", BLUE, "//")
    box(left, 0.03, 0.34, 0.29, 0.14, "PLAY item β", ORANGE, "..")
    box(left, 0.57, 0.49, 0.38, 0.17, "[PLAY, context,\nsource = 0]", GRAY, "xx")
    arrow(left, (0.32, 0.73), (0.57, 0.58)); arrow(left, (0.32, 0.41), (0.57, 0.57))
    left.text(0.03, 0.10, f"{corpus['baseline_unresolved_play_options']:,} / "
              f"{corpus['ordinary_play_options']:,} ordinary PLAY options unresolved", color=GRAY)
    right.set_title("After: source identity retained", loc="left", weight="bold")
    box(right, 0.03, 0.66, 0.29, 0.14, "PLAY item α", BLUE, "//")
    box(right, 0.03, 0.34, 0.29, 0.14, "PLAY item β", ORANGE, "..")
    box(right, 0.57, 0.66, 0.38, 0.14, "[PLAY, context, source α]", BLUE, "//")
    box(right, 0.57, 0.34, 0.38, 0.14, "[PLAY, context, source β]", ORANGE, "..")
    arrow(right, (0.32, 0.73), (0.57, 0.73)); arrow(right, (0.32, 0.41), (0.57, 0.41))
    right.text(0.03, 0.10, f"{corpus['states_with_two_or_more_play_identities']:,} states expose ≥2 PLAY identities",
               color=GRAY)
    fig.suptitle("Action-identity repair in the variable legal-action encoder", x=0.07,
                 ha="left", fontsize=12, weight="bold")
    save(fig, "fig02_action_aliasing")


def figure_provenance() -> None:
    counts = np.asarray([38_254, 3_361, 6_038])
    labels = ["Training", "Internal validation", "Team holdout"]
    colors = [BLUE, ORANGE, PURPLE]
    hatches = ["//", "..", "xx"]
    fig, axes = plt.subplots(2, 1, figsize=(7.2, 4.5), gridspec_kw={"height_ratios": [1, 1.45]})
    ax = axes[0]
    left = 0
    for value, label, color, hatch in zip(counts, labels, colors, hatches, strict=True):
        ax.barh([0], [value], left=left, color="white", edgecolor=color, hatch=hatch,
                linewidth=1.5, label=f"{label}: {value:,}")
        ax.text(left + value / 2, 0, f"{value:,}", ha="center", va="center", fontsize=8)
        left += value
    ax.set_xlim(0, counts.sum()); ax.set_yticks([]); ax.set_xlabel("Retained feature/action rows")
    ax.legend(ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.42), frameon=False)
    ax.set_title("Dataset split and experiment provenance", loc="left", weight="bold", fontsize=12)
    ax = axes[1]
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    stages = [
        (0.02, "A2 / C0\nfrozen baseline", GRAY, None),
        (0.22, "Retained expert\nfeature rows", BLUE, "//"),
        (0.42, "Encoder repair +\nheads-only training", ORANGE, ".."),
        (0.63, "Four-cell\nmatched ablation", PURPLE, "xx"),
        (0.82, "Fresh paired\nconfirmation", BLUE, "\\\\"),
    ]
    for index, (x, label, color, hatch) in enumerate(stages):
        box(ax, x, 0.40, 0.15, 0.24, label, color, hatch)
        if index:
            arrow(ax, (x - 0.05, 0.52), (x, 0.52))
    ax.text(0.02, 0.13, "Raw replay extraction cannot be rerun: original Aug. 14–15 observations are missing.",
            color=GRAY)
    save(fig, "fig03_dataset_provenance")


def figure_gameplay_forest(stats: dict) -> None:
    opponent = stats["fresh_confirmation"]["by_opponent"]
    rows = [(name, value) for name, value in opponent.items()]
    rows.append(("Equal-weight overall", stats["fresh_confirmation"]["primary"]))
    fig, ax = plt.subplots(figsize=(6.8, 4.2))
    y = np.arange(len(rows))[::-1]
    for index, ((label, result), ypos) in enumerate(zip(rows, y, strict=True)):
        low, high = result["paired_bootstrap_95_ci"]
        color = PURPLE if label == "Equal-weight overall" else BLUE
        marker = "D" if label == "Equal-weight overall" else ("s" if label in {"B0", "d842_runtime", "master_v1", "replay_refresh"} else "o")
        ax.errorbar(100 * result["effect"], ypos,
                    xerr=[[100 * (result["effect"] - low)], [100 * (high - result["effect"])]],
                    fmt=marker, color=color, markerfacecolor="white", markeredgewidth=1.5,
                    capsize=3, linewidth=1.3)
    ax.axvline(0, color=GRAY, linewidth=1, linestyle="--")
    ax.set_yticks(y, [label.replace("_", " ") for label, _ in rows])
    ax.set_xlabel("EXP23 − C0 win probability (percentage points)")
    ax.set_title("Fresh paired gameplay effects", loc="left", fontsize=12, weight="bold")
    ax.grid(axis="x", color=LIGHT, linewidth=0.8)
    ax.text(0.99, -0.16, "Squares: defined matched-policy family; circles: broader fixed policies; diamond: equal-weight primary",
            transform=ax.transAxes, ha="right", fontsize=7.5, color=GRAY)
    save(fig, "fig04_gameplay_forest")


def figure_gameplay_vs_expert(stats: dict, representation: dict, heldout: dict) -> None:
    primary = stats["fresh_confirmation"]["primary"]
    head = representation["team_holdout_expert_agreement"]["overall"]
    replay = heldout["overall"]
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.5), gridspec_kw={"wspace": 0.40})
    ax = axes[0]
    low, high = primary["paired_bootstrap_95_ci"]
    ax.errorbar(100 * primary["effect"], 0,
                xerr=[[100 * (primary["effect"] - low)], [100 * (high - primary["effect"])]],
                fmt="D", color=BLUE, markerfacecolor="white", markeredgewidth=1.5, capsize=4)
    ax.axvline(0, color=GRAY, linestyle="--", linewidth=1)
    ax.set_yticks([0], ["Fresh gameplay"]); ax.set_xlabel("Win difference (pp)")
    ax.set_title("A. Paired gameplay", loc="left", weight="bold")
    ax.grid(axis="x", color=LIGHT)
    ax = axes[1]
    for ypos, label, result, color, marker in [
        (1, "Feature-row holdout", head, ORANGE, "s"),
        (0, "Retained replay reanalysis", replay, PURPLE, "o"),
    ]:
        ci = result.get("episode_bootstrap_95_ci")
        approval = result["approval"]
        ax.errorbar(approval, ypos,
                    xerr=[[approval - ci[0]], [ci[1] - approval]], fmt=marker,
                    color=color, markerfacecolor="white", markeredgewidth=1.5, capsize=4)
    ax.axvline(0.5, color=GRAY, linestyle="--", linewidth=1)
    ax.set_yticks([1, 0], ["Feature-row holdout", "Retained replay\nreanalysis"])
    ax.set_xlabel("EXP23 approval among binary decisions")
    ax.set_title("B. Expert-action agreement", loc="left", weight="bold")
    ax.grid(axis="x", color=LIGHT)
    fig.suptitle("Gameplay and expert agreement are different estimands", x=0.08,
                 ha="left", fontsize=12, weight="bold")
    fig.text(0.5, -0.02,
             "Panels use distinct scales and denominators; their point estimates must not be subtracted or pooled.",
             ha="center", fontsize=8, color=GRAY)
    save(fig, "fig05_gameplay_vs_expert")


def figure_negative(negative: dict) -> None:
    rows = negative["results"]
    fig, ax = plt.subplots(figsize=(6.8, 3.2))
    y = np.arange(len(rows))[::-1]
    for ypos, result, color, marker in zip(y, rows, [PURPLE, ORANGE], ["s", "o"], strict=True):
        ax.errorbar(100 * result["effect"], ypos,
                    xerr=[[100 * (result["effect"] - result["ci_low"])],
                          [100 * (result["ci_high"] - result["effect"])]],
                    fmt=marker, color=color, markerfacecolor="white", markeredgewidth=1.5,
                    capsize=4, linewidth=1.4)
    ax.axvline(0, color=GRAY, linestyle="--", linewidth=1)
    ax.axvline(3, color=GRAY, linestyle=":", linewidth=1)
    ax.text(3, len(rows) - 0.55, "sequence-oracle gate", rotation=90, va="top", ha="right",
            fontsize=7, color=GRAY)
    ax.set_yticks(y, [result["label"] for result in rows])
    ax.set_xlabel("Candidate − baseline win probability (percentage points)")
    ax.set_title("Retained null results with raw evidence", loc="left", fontsize=12, weight="bold")
    ax.grid(axis="x", color=LIGHT)
    ax.text(0.99, -0.22, "Intervals: opponent-stratified paired bootstrap (temporal) and root-cluster bootstrap (oracle)",
            transform=ax.transAxes, ha="right", fontsize=7.5, color=GRAY)
    save(fig, "fig06_negative_forest")


def main() -> int:
    setup()
    stats = load("statistical_summary.json")
    representation = load("representation_audit.json")
    heldout = load("heldout_0813_summary.json")
    negative = load("negative_results.json")
    figure_pipeline()
    figure_aliasing(representation)
    figure_provenance()
    figure_gameplay_forest(stats)
    figure_gameplay_vs_expert(stats, representation, heldout)
    figure_negative(negative)
    print(json.dumps({"figures": 6, "formats": ["pdf", "png"], "output": str(OUT)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
