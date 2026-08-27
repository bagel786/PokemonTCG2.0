"""Generate figures + machine-readable sources from aggregates only.

Every figure writes its source CSV beside the PDF/PNG. No hand-entered
empirical numbers anywhere.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
METHODS = ["B0_schedule_only", "B1_outcome_aa", "B2_trace_aa",
           "B3_within_seed_reps", "B4_unpaired_analysis",
           "B5_cluster_hierarchical", "B6_event_keyed_whitebox",
           "B7_csvf_full"]
SHORT = {m: m.split("_")[0] for m in METHODS}


def _wcsv(path: Path, rows, fields):
    path.parent.mkdir(exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def fig_detection_fs(agg: dict, outdir: Path):
    per = defaultdict(lambda: [0.0, 0.0, 0])
    for d in agg["decision_metrics"]:
        if d["coverage"] <= 0 or d["invalid_covered"] == 0 and \
                d["valid_covered"] == 0:
            continue
        k = (d["system"], d["method"])
        if d["invalid_covered"]:
            per[k][0] += d["det_strict_n"] / d["invalid_covered"]
            per[k][2] += 0.5
        if d["valid_covered"]:
            per[k][1] += d["fs_total"] / d["valid_covered"]
            per[k][2] += 0.5
    pts = [{"system": s, "method": m,
            "mean_det_rate": round(v[0], 4), "mean_fs_rate": round(v[1], 4)}
           for (s, m), v in sorted(per.items()) if v[2] > 0]
    _wcsv(outdir.parent / "figure_sources" /
          "figure3_detection_fs.csv", pts,
          ["system", "method", "mean_det_rate", "mean_fs_rate"])
    fig, axes = plt.subplots(1, 2, figsize=(9, 4), sharey=True)
    for ax, sname in zip(axes, ("holdem", "ising")):
        sp = [p for p in pts if p["system"] == sname]
        ax.scatter([p["mean_det_rate"] for p in sp],
                   [p["mean_fs_rate"] for p in sp], s=26)
        for p in sp:
            ax.annotate(SHORT[p["method"]],
                        (p["mean_det_rate"], p["mean_fs_rate"]),
                        fontsize=7, xytext=(3, 2), textcoords="offset points")
        ax.set_xlim(-0.03, 1.05)
        ax.set_ylim(-0.02, 0.6)
        ax.set_xlabel("strict detection rate (branch mean)")
        ax.set_title(sname)
        ax.grid(alpha=0.25)
    axes[0].set_ylabel("false-suppression rate")
    fig.suptitle("Detection vs false suppression by method "
                 "(covered cells only)")
    fig.tight_layout()
    for ext in ("pdf", "png"):
        fig.savefig(outdir / f"figure3_detection_fs.{ext}")
    plt.close(fig)


def fig_costs(agg: dict, outdir: Path):
    cs = sorted(agg["cost_summary"],
                key=lambda r: METHODS.index(r["method"]))
    fields = ["method", "n", "acq_wall_median_s", "acq_wall_p95_s",
              "cpu_median_s", "classifier_median_s", "bundle_bytes_median",
              "extra_execs_max"]
    _wcsv(outdir.parent / "figure_sources" / "figure5_costs.csv",
          cs, fields)
    fig, ax = plt.subplots(figsize=(8, 3.6))
    names = [SHORT[r["method"]] for r in cs]
    med = [max(r["acq_wall_median_s"], 1e-6) for r in cs]
    p95 = [max(r["acq_wall_p95_s"], 1e-6) for r in cs]
    ax.bar(names, med, color="#4878CF", label="median acquisition wall s")
    ax.errorbar(names, med,
                yerr=[[m - min(m, l) for m, l in zip(med, med)],
                      [h - m for h, m in zip(p95, med)]],
                fmt="none", ecolor="gray", capsize=3, label="p95")
    ax.set_yscale("log")
    ax.set_ylabel("seconds (log scale)")
    ax.set_title("Per-method evidence-acquisition cost (dedicated cost bank)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    for ext in ("pdf", "png"):
        fig.savefig(outdir / f"figure5_costs.{ext}")
    plt.close(fig)


def table_grammar(outdir: Path):
    grammar = json.loads((ROOT / "protocol" /
                          "FAULT_GRAMMAR.json").read_text())
    dims = ["descriptive", "paired_inference", "replay", "crn",
            "event_alignment"]
    rows = []
    for c in grammar["constructions"]:
        for sname in (["holdem", "ising"] if
                      "both" in c.get("systems", ["both"])
                      else c.get("systems", [])):
            row = {"construction": c["id"], "system": sname}
            row.update({d: c["gt"].get(d, "NOT_APPLICABLE") for d in dims})
            rows.append(row)
    _wcsv(outdir.parent / "table_sources" / "table2_grammar_truth.csv",
          rows, ["construction", "system"] + dims)


def main(bank_dir: Path):
    agg = json.loads((bank_dir / "aggregates" /
                      "results_aggregates.json").read_text())
    outdir = bank_dir / "figures"
    outdir.mkdir(exist_ok=True)
    fig_detection_fs(agg, outdir)
    fig_costs(agg, outdir)
    table_grammar(outdir)
    print("figures+tables written under", outdir)


if __name__ == "__main__":
    import sys
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        ROOT / "results" / "final"
    main(target)
