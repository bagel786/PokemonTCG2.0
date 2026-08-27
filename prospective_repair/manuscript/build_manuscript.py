"""Build FINAL_MANUSCRIPT_FOR_REVIEW from template + machine-readable macros.

Only {{TOKEN}} substitution happens here; no number is ever typed into prose.
Writes .md and, when pandoc exists, a PDF (paged); otherwise leaves the md
with explicit notice. Also emits FIGURE_REVIEW-style contact info.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MDIR = ROOT / "manuscript"


def load_macros() -> dict:
    mpath = ROOT / "results" / "final" / "aggregates" / "results_macros.json"
    if not mpath.exists():
        raise SystemExit("macros missing — run analyze first")
    macros = json.loads(mpath.read_text())
    # derived macros (computed here so they can never drift from aggregates)
    agg_p = ROOT / "results" / "final" / "aggregates" / \
        "results_aggregates.json"
    agg = json.loads(agg_p.read_text())

    def pooled(method):
        dn = dx = vn = fx = 0
        for d in agg["decision_metrics"]:
            if d["method"] != method:
                continue
            dn += d["invalid_covered"]; dx += d["det_strict_n"]
            vn += d["valid_covered"]; fx += d["fs_total"]
        return ((dx / dn if dn else None), (fx / vn if vn else None), dn, vn)

    for meth, dtag, ftag in (("B7_csvf_full", "B7_DET_POOLED",
                              "B7_FS_POOLED"),
                             ("B5_cluster_hierarchical", "B5_DET_POOLED",
                              "B5_FS_POOLED")):
        det, fs, dn, vn = pooled(meth)
        macros[dtag] = f"{det:.3f} ({int(round(det * dn))}/{dn})" \
            if det is not None else "n/a"
        macros[ftag] = f"{fs:.3f} ({int(round(fs * vn))}/{vn})" \
            if fs is not None else "n/a"
    walls = sorted(c["acq_wall_median_s"] for c in agg["cost_summary"])
    macros["COST_SPREAD"] = (
        f"{walls[-1]:.2f}s versus {walls[0]*1000:.1f} ms median"
        if walls else "n/a")
    return macros


def resolve(text: str, macros: dict) -> str:
    missing = set(re.findall(r"\{\{([A-Z0-9_]+)\}\}", text))
    unknown = [m for m in missing if m not in macros]
    if unknown:
        raise SystemExit(f"unresolved macro tokens: {sorted(unknown)[:10]}")
    for k, v in macros.items():
        text = text.replace("{{%s}}" % k, str(v))
    leftovers = re.findall(r"\{\{[A-Z0-9_]+\}\}", text)
    assert not leftovers, leftovers[:5]
    return text


def main():
    tpl = (MDIR / "manuscript_template.md").read_text()
    macros = load_macros()
    out = resolve(tpl, macros)
    final = MDIR / "FINAL_MANUSCRIPT_FOR_REVIEW.md"
    final.write_text(out)
    pdf = None
    if shutil.which("pandoc"):
        pdf = MDIR / "FINAL_MANUSCRIPT_FOR_REVIEW.pdf"
        subprocess.run(["pandoc", str(final), "-o", str(pdf),
                        "--pdf-engine=tectonic", "-V", "geometry:margin=1in",
                        "-V", "fontsize=11pt"], check=False)
    print({"md": str(final), "pdf": str(pdf) if pdf else None,
           "macro_keys": len(macros)})


if __name__ == "__main__":
    main()
