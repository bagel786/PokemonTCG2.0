"""Generate Figures 1-8 and source CSVs from machine-readable inputs."""

import csv
import json
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch


ROOT = Path(__file__).resolve().parents[1]
AGG = ROOT / "results/final/aggregates"
OUT = ROOT / "results/final/figures"
SRC = ROOT / "results/final/figure_sources"
OUT.mkdir(parents=True, exist_ok=True)
SRC.mkdir(parents=True, exist_ok=True)

mpl.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9, "axes.titlesize": 11,
    "axes.labelsize": 9, "axes.spines.top": False, "axes.spines.right": False,
    "figure.facecolor": "white", "savefig.facecolor": "white",
})
COLORS = {"blue": "#2B6CB0", "orange": "#C05621", "green": "#2F855A",
          "purple": "#6B46C1", "gray": "#718096", "red": "#C53030",
          "ink": "#1A202C"}


def load_json(path):
    return json.loads(Path(path).read_text())


def read_csv(path):
    with Path(path).open() as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows):
    if not rows:
        return
    with Path(path).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


def save(fig, stem):
    fig.savefig(OUT / f"{stem}.pdf", bbox_inches="tight")
    fig.savefig(OUT / f"{stem}.png", dpi=240, bbox_inches="tight")
    plt.close(fig)


def figure1():
    rows = [
        {"branch": f"BRANCH_{b}", "name": name, "question": question}
        for b, name, question in [
            ("A", "Matched descriptive comparison", "Did recorded runs share the declared schedule?"),
            ("B", "Statistically paired inference", "Is the estimator's reference distribution justified?"),
            ("C", "Deterministic replay", "Does one artifact reproduce its declared projection?"),
            ("D", "CRN variance reduction", "Does a valid coupling reduce variance?"),
            ("E", "Event-aligned counterfactual / mechanism", "Did matched events receive equal random values?"),
        ]
    ]
    # Verify the branch identifiers against the canonical machine source.
    canonical = load_json(ROOT / "framework/claim_classes.json")
    canonical_text = json.dumps(canonical)
    assert all(row["branch"] in canonical_text for row in rows)
    write_csv(SRC / "figure1_claim_branches.csv", rows)
    fig, ax = plt.subplots(figsize=(8.5, 7.2)); ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    center = FancyBboxPatch((0.045, 0.88), 0.91, 0.08, boxstyle="round,pad=0.015",
                            fc=COLORS["ink"], ec="none")
    ax.add_patch(center)
    ax.text(0.5, 0.92, "What exact scientific claim does the evaluator want to make?",
            ha="center", va="center", color="white", weight="bold", fontsize=10)
    branch_colors = [COLORS["blue"], COLORS["green"], COLORS["orange"],
                     COLORS["purple"], COLORS["red"]]
    ys = np.linspace(0.72, 0.12, 5)
    for row, y, color in zip(rows, ys, branch_colors):
        ax.annotate("", xy=(0.5, y + 0.095), xytext=(0.5, 0.88),
                    arrowprops=dict(arrowstyle="-|>", color=COLORS["gray"], lw=1.1))
        ax.add_patch(FancyBboxPatch((0.14, y), 0.72, 0.105, boxstyle="round,pad=0.012",
                                    fc="white", ec=color, lw=1.8))
        ax.text(0.17, y + 0.07, f"{row['branch'].replace('_', ' ')}  {row['name']}",
                color=color, weight="bold", ha="left", va="center")
        ax.text(0.17, y + 0.035, row["question"], color=COLORS["ink"], ha="left", va="center")
    ax.text(0.5, 0.025, "Branches are alternatives by claim objective - not a cumulative ladder.",
            ha="center", color=COLORS["ink"], weight="bold")
    save(fig, "figure1_claim_specific_branching")


def figure2():
    expected = load_json(ROOT / "protocol/EXPECTED_DECISION_TABLE.json")["scenarios"]
    dims = ["descriptive", "paired_inference", "replay", "crn", "event_alignment"]
    labels = ["A Descriptive", "B Paired", "C Replay", "D CRN", "E Event"]
    code = {"VALID": 2, "DOWNGRADE": 1, "INVALID": 0, "NOT_APPLICABLE": -1}
    rows, matrix = [], []
    for sid in [f"S{i}" for i in range(11)]:
        values = []
        for dim, label in zip(dims, labels):
            state = expected[sid]["gt"][dim]
            rows.append({"scenario": sid, "scenario_name": expected[sid]["name"],
                         "claim": label, "ground_truth": state})
            values.append(code[state])
        matrix.append(values)
    write_csv(SRC / "figure2_failure_claim_matrix.csv", rows)
    cmap = mpl.colors.ListedColormap(["#E2E8F0", "#FED7D7", "#FEEBC8", "#C6F6D5"])
    norm = mpl.colors.BoundaryNorm([-1.5, -0.5, 0.5, 1.5, 2.5], cmap.N)
    fig, ax = plt.subplots(figsize=(8.5, 6.4)); ax.imshow(matrix, cmap=cmap, norm=norm, aspect="auto")
    ax.set_xticks(range(5), labels, rotation=20, ha="right")
    sids = [f"S{i}" for i in range(11)]
    ax.set_yticks(range(11), [f"{sid}  {expected[sid]['name']}" for sid in sids])
    symbols = {"VALID": "V", "DOWNGRADE": "D", "INVALID": "X", "NOT_APPLICABLE": "-"}
    for i, sid in enumerate(sids):
        for j, dim in enumerate(dims):
            ax.text(j, i, symbols[expected[sid]["gt"][dim]], ha="center", va="center", weight="bold")
    ax.set_title("Construction-known ground truth by failure scenario and claim type")
    legend = [Line2D([0], [0], marker="s", ls="", color=color, label=label,
                     markeredgecolor="none", markersize=9)
              for color, label in [("#C6F6D5", "V valid"), ("#FEEBC8", "D downgrade"),
                                   ("#FED7D7", "X invalid"), ("#E2E8F0", "- not applicable")]]
    ax.legend(handles=legend, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=4, frameon=False)
    save(fig, "figure2_failure_claim_matrix")


def figure3():
    rows = load_json(AGG / "cross_system.json")["method_scores"]
    write_csv(SRC / "figure3_detection_false_suppression.csv", rows)
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 4.4), sharex=True, sharey=True)
    offsets = [(5, 5), (5, -11), (5, 5), (5, -11), (5, 5), (5, 5), (5, -11), (-55, 5)]
    for ax, system in zip(axes, ("holdem", "ising")):
        selected = [r for r in rows if r["system"] == system]
        for i, row in enumerate(selected):
            marker = "D" if row["method"] == "B7_csvf_full" else "o"
            color = COLORS["red"] if row["method"] == "B7_csvf_full" else COLORS["blue"]
            ax.scatter(row["false_suppression"], row["detection"], s=55, marker=marker,
                       color=color, edgecolor="white", linewidth=0.6, zorder=3)
            ax.annotate(row["method"].split("_")[0],
                        (row["false_suppression"], row["detection"]),
                        xytext=offsets[i], textcoords="offset points", fontsize=8)
        ax.axvline(0.10, color=COLORS["gray"], ls="--", lw=1)
        ax.axhline(0.95, color=COLORS["gray"], ls=":", lw=1)
        ax.set_title("RLCard hold'em" if system == "holdem" else "Ising Monte Carlo")
        ax.set_xlabel("False-suppression rate"); ax.grid(alpha=0.18)
    axes[0].set_ylabel("Hard-invalid detection rate"); axes[0].set_xlim(-0.03, 0.72); axes[0].set_ylim(-0.03, 1.06)
    fig.suptitle("Reliability tradeoff across all claim branches", weight="bold")
    fig.text(0.5, -0.02, "Lines mark the predeclared 10% false-suppression and 95% detection criteria; rates pool designed cells.", ha="center", fontsize=8)
    fig.tight_layout(); save(fig, "figure3_detection_false_suppression")


def figure4():
    rows = read_csv(AGG / "statistical_diagnostics.csv")
    selected = [r for r in rows if r["n"] == "40" and r["scenario"] in {"S0", "S3"}
                and r["metric"] in {"typeI", "null_coverage"}]
    write_csv(SRC / "figure4_statistical_diagnostics.csv", selected)
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 4.3))
    for ax, metric, target in zip(axes, ("typeI", "null_coverage"), (0.05, 0.95)):
        subset = [r for r in selected if r["metric"] == metric]
        labels = [f"{r['system']} {r['scenario']}\n{r['procedure']}" for r in subset]
        values = [float(r["estimate"]) for r in subset]
        colors = [COLORS["blue"] if r["procedure"] == "paired_t" else COLORS["orange"] for r in subset]
        ax.bar(range(len(values)), values, color=colors, edgecolor="white"); ax.axhline(target, color=COLORS["ink"], ls="--", lw=1)
        ax.set_xticks(range(len(labels)), labels, rotation=35, ha="right", fontsize=7)
        ax.set_ylabel("Estimated rate"); ax.set_title("Centered-null rejection" if metric == "typeI" else "Centered-null interval inclusion")
        ax.grid(axis="y", alpha=0.18)
    fig.suptitle("Post-freeze resampling diagnostics - not confirmatory M4/M5", weight="bold", color=COLORS["red"])
    fig.text(0.5, -0.04, "Promised A/A mirror and equal-temperature banks were not retained; bars use centered empirical proxies (B=2,000).", ha="center", fontsize=8)
    fig.tight_layout(); save(fig, "figure4_statistical_diagnostics_not_confirmatory")


def figure5():
    rows = read_csv(AGG / "variance_ratios.csv"); write_csv(SRC / "figure5_variance_ratios.csv", rows)
    labels = [f"{r['system']} {r['scenario']}" for r in rows]; y = np.arange(len(rows))[::-1]
    fig, ax = plt.subplots(figsize=(8.4, 5.2))
    for yy, row in zip(y, rows):
        value = float(row["var_ratio_R"]); color = COLORS["blue"] if row["system"] == "holdem" else COLORS["orange"]
        if value == 0:
            ax.scatter(0.08, yy, marker="<", color=color, s=55, zorder=3); ax.text(0.095, yy, "exact 0", va="center", fontsize=7)
        else:
            low, high = float(row["ratio_ci_lo"]), float(row["ratio_ci_hi"])
            ax.errorbar(value, yy, xerr=[[value-low], [high-value]], fmt="o", color=color, capsize=3, lw=1.2)
    ax.axvline(1, color=COLORS["ink"], ls="--", lw=1); ax.set_xscale("log"); ax.set_xlim(0.07, 3.2)
    ax.set_yticks(y, labels); ax.set_xlabel("R = Var(paired difference) / Var(cross-seed difference)")
    ax.set_title("Measured common-random-number variance ratios"); ax.grid(axis="x", alpha=0.18, which="both")
    ax.text(0.075, -0.9, "helps", color=COLORS["green"], fontsize=8); ax.text(2.2, -0.9, "hurts", color=COLORS["red"], fontsize=8)
    save(fig, "figure5_variance_reduction")


def figure6():
    all_rows = [r for r in read_csv(AGG / "costs.csv") if r["scenario"] == "ALL"]
    overhead = load_json(AGG / "overhead.json")["results"]
    source = []
    for row in all_rows:
        match = next(x for x in overhead if x["system"] == row["system"])
        source.append({"system": row["system"], "runtime_median_s": row["runtime_median_s"],
                       "storage_median_bytes": row["storage_median_bytes"],
                       "trace_overhead_percent": match["trace_overhead_percent"]})
    write_csv(SRC / "figure6_runtime_storage_cost.csv", source)
    fig, axes = plt.subplots(1, 3, figsize=(9.2, 3.9)); systems = [r["system"] for r in source]; colors = [COLORS["blue"], COLORS["orange"]]
    panels = [("runtime_median_s", "Median pair runtime (s)", True),
              ("storage_median_bytes", "Median stored bytes / pair", True),
              ("trace_overhead_percent", "Trace overhead (%)", False)]
    for ax, (key, title, log) in zip(axes, panels):
        values = [float(r[key]) for r in source]; ax.bar(systems, values, color=colors, edgecolor="white")
        if log: ax.set_yscale("log")
        ax.set_title(title); ax.grid(axis="y", alpha=0.18)
        for i, value in enumerate(values): ax.text(i, value * (1.12 if log else 1.02), f"{value:.2g}", ha="center", fontsize=8)
    fig.suptitle("Observed acquisition cost and analysis-stage logging overhead", weight="bold"); fig.tight_layout()
    save(fig, "figure6_runtime_storage_cost")


def figure7():
    cross = load_json(AGG / "cross_system.json"); rows = cross["method_scores"]
    write_csv(SRC / "figure7_cross_system_summary.csv", rows)
    lookup = {(r["system"], r["method"]): r for r in rows}; methods = [f"B{i}" for i in range(8)]; y = np.arange(8)[::-1]
    fig, ax = plt.subplots(figsize=(8.3, 5.0))
    for yy, method in zip(y, methods):
        full = next(r["method"] for r in rows if r["method"].startswith(method + "_"))
        h, s = lookup[("holdem", full)]["tradeoff"], lookup[("ising", full)]["tradeoff"]
        ax.plot([h, s], [yy, yy], color=COLORS["gray"], lw=1.4)
        ax.scatter(h, yy, color=COLORS["blue"], marker="o", s=45, zorder=3); ax.scatter(s, yy, color=COLORS["orange"], marker="s", s=42, zorder=3)
    ax.axvline(0, color=COLORS["ink"], lw=1); ax.set_yticks(y, methods)
    ax.set_xlabel("Predeclared ordering score M1 - M2 (not a probability)")
    ax.set_title(f"Cross-system method ordering (Kendall tau-b = {cross['kendall_tau_b_tradeoff']:.2f})"); ax.grid(axis="x", alpha=0.18)
    ax.legend(handles=[Line2D([0], [0], marker="o", color="none", markerfacecolor=COLORS["blue"], label="hold'em"),
                       Line2D([0], [0], marker="s", color="none", markerfacecolor=COLORS["orange"], label="Ising")], frameon=False, loc="lower right")
    save(fig, "figure7_cross_system_summary")


def figure8():
    rows = [
        {"case": "Timed-search trace projection", "mismatches": 99, "denominator": 200, "scope": "restricted fixed battery"},
        {"case": "Historical outcome record", "mismatches": 210, "denominator": 2800, "scope": "retrospective audit"},
        {"case": "Historical available record", "mismatches": 458, "denominator": 2800, "scope": "retrospective audit"},
    ]
    for row in rows: row["percent"] = 100 * row["mismatches"] / row["denominator"]
    write_csv(SRC / "figure8_historical_case.csv", rows)
    fig, ax = plt.subplots(figsize=(8.2, 4.4)); y = np.arange(3)[::-1]; vals = [r["percent"] for r in rows]
    ax.barh(y, vals, color=[COLORS["purple"], COLORS["gray"], COLORS["gray"]], edgecolor="white")
    ax.set_yticks(y, [r["case"] for r in rows]); ax.set_xlabel("Disagreement proportion (%)")
    ax.set_title("Restricted historical case - motivating evidence only")
    for yy, value, row in zip(y, vals, rows): ax.text(value + 0.8, yy, f"{row['mismatches']}/{row['denominator']} ({value:.1f}%)", va="center")
    ax.set_xlim(0, 58); ax.grid(axis="x", alpha=0.18)
    fig.text(0.5, -0.02, "Not pooled with the prospective benchmark; restricted materials and retrospective rules limit interpretation.", ha="center", fontsize=8)
    fig.tight_layout(); save(fig, "figure8_historical_case")


def main():
    figure1(); figure2(); figure3(); figure4(); figure5(); figure6(); figure7(); figure8()
    print(f"generated {len(list(OUT.glob('*.pdf')))} PDFs and {len(list(OUT.glob('*.png')))} PNGs")


if __name__ == "__main__":
    main()
