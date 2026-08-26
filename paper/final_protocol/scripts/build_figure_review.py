#!/usr/bin/env python3
"""Build HUMAN_PORTAL/FIGURE_REVIEW.pdf: one figure per page at comfortable
size with figure number, final caption, and the one thing to check visually.
Deterministic (fixed PDF metadata)."""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from pathlib import Path

FINAL = Path(__file__).resolve().parents[1]
OUT = FINAL / "HUMAN_PORTAL/FIGURE_REVIEW.pdf"

ENTRIES = [
    {
        "stem": "figure_1_distinctions",
        "number": "Figure 1",
        "caption": ("Schedule matching, within-arm execution repeatability, and cross-arm "
                    "semantic event alignment answer different questions and require different "
                    "evidence. Each claim is limited to the declared schedule, trace projection, "
                    "execution contexts, and event ontology."),
        "check": "Check that no text touches or overlaps the boxes and arrows, and that the three panels read left to right.",
    },
    {
        "stem": "figure_2_admission_flow",
        "number": "Figure 2",
        "caption": ("Validation and admission flow. Levels 1-7 accumulate scoped evidence. A frozen "
                    "required failure retains its suppression action; Level 8 cannot repair it. The "
                    "claim classes are a later conservative reporting taxonomy for this completed "
                    "case. Level 6 does not itself supply a sampling basis for inferential pairing."),
        "check": "Check that every label fits inside its box, the orange note points cleanly at L7, and the two outcome arrows do not cross anything.",
    },
    {
        "stem": "figure_3_synthetic_matrix",
        "number": "Figure 3",
        "caption": ("Synthetic failure-detection and admission matrix. P pass, F fail, A admit, "
                    "D downgrade, dash = blocked gate. The suite demonstrates known logical "
                    "relations; it does not estimate failure prevalence in external systems."),
        "check": "Check that the letters are readable in every cell and the legend does not overlap the note below it.",
    },
    {
        "stem": "figure_4_timed_search",
        "number": "Figure 4",
        "caption": ("Fixed-battery trace-projection disagreement in the timed-search stress test. "
                    "Dots show cluster-level disagreement; bars are descriptive empirical "
                    "reweighting quantiles, not confidence intervals. Neutral labels replace "
                    "package names."),
        "check": "Check that the percentage labels do not collide with the markers and that the note at the bottom is fully visible.",
    },
    {
        "stem": "figure_5_factorial",
        "number": "Figure 5",
        "caption": ("Fixed-battery factorial contrasts with empirical reweighting quantiles for "
                    "2,000 schedule-indexed units per cell. Bars are descriptive sensitivities, "
                    "not confidence intervals or tests."),
        "check": "Check that all four contrast labels and value annotations are readable and that nothing overlaps the dashed zero line.",
    },
]

import textwrap

from datetime import datetime
FIXED_META = {"CreationDate": datetime(2026, 8, 26),
              "ModDate": datetime(2026, 8, 26),
              "Author": "build_figure_review.py", "Title": "Figure review packet"}


def main() -> int:
    OUT.parent.mkdir(exist_ok=True)
    with PdfPages(OUT, metadata=FIXED_META) as pdf:
        for entry in ENTRIES:
            image_path = FINAL / "figures" / f"{entry['stem']}.png"
            image = mpimg.imread(image_path)
            fig = plt.figure(figsize=(11, 8.5))
            fig.text(0.06, 0.965, f"{entry['number']}", fontsize=20, fontweight="bold",
                     color="#1F2937", va="top")
            caption = "\n".join(textwrap.wrap(entry["caption"], width=105))
            fig.text(0.06, 0.915, caption, fontsize=11.5, color="#1F2937", va="top",
                     linespacing=1.35)
            check = "\n".join(textwrap.wrap("WHAT TO CHECK: " + entry["check"], width=100))
            fig.text(0.06, 0.055, check, fontsize=11, color="#7A1F1F", va="bottom",
                     fontweight="bold", linespacing=1.35)
            axes = fig.add_axes([0.06, 0.15, 0.88, 0.68])
            axes.imshow(image)
            axes.axis("off")
            pdf.savefig(fig)
            plt.close(fig)
    print(f"figure review written: {OUT} ({len(ENTRIES)} pages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
