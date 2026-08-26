"""Inject checked results into the manuscript and render a review PDF."""

import html
import json
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (Image, PageBreak, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)


ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
AGG = ROOT / "results/final/aggregates"
FIG = ROOT / "results/final/figures"
TEMPLATE = HERE / "manuscript_template.md"
MARKDOWN = HERE / "manuscript.md"
PDF = HERE / "FINAL_MANUSCRIPT_FOR_REVIEW.pdf"


def values():
    macros = json.loads((AGG / "results_macros.json").read_text())
    success = json.loads((AGG / "success_criteria.json").read_text())
    cross = json.loads((AGG / "cross_system.json").read_text())
    variance = json.loads((AGG / "variance_ratios.json").read_text())
    costs = json.loads((AGG / "costs.json").read_text())
    overhead = json.loads((AGG / "overhead.json").read_text())["results"]
    decision = json.loads((AGG / "decision_metrics.json").read_text())
    def dec(method, branch, system="pooled"):
        return next(r for r in decision if r["method"] == method and r["branch"] == branch and r["system"] == system)
    def score(system, method="B7_csvf_full"):
        return next(r for r in cross["method_scores"] if r["system"] == system and r["method"] == method)
    def var(system, scenario):
        return next(r for r in variance if r["system"] == system and r["scenario"] == scenario)
    def cost(system):
        return next(r for r in costs if r["system"] == system and r["scenario"] == "ALL")
    def over(system):
        return next(r for r in overhead if r["system"] == system)
    result = dict(macros)
    result.update({
        "b7_overall_detection_pct": f"{100*success['overall_method_metrics']['B7_csvf_full']['detection']:.1f}",
        "b7_branch_c_detection_pct": f"{100*dec('B7_csvf_full','BRANCH_C')['detection_est']:.1f}",
        "b7_holdem_detection_pct": f"{100*score('holdem')['detection']:.1f}",
        "b7_holdem_fs_pct": f"{100*score('holdem')['false_suppression']:.1f}",
        "b7_ising_detection_pct": f"{100*score('ising')['detection']:.1f}",
        "b7_ising_fs_pct": f"{100*score('ising')['false_suppression']:.1f}",
        "holdem_s0_R": f"{var('holdem','S0')['var_ratio_R']:.3f}",
        "ising_s0_R": f"{var('ising','S0')['var_ratio_R']:.3f}",
        "holdem_runtime_s": f"{cost('holdem')['runtime_median_s']:.4f}",
        "ising_runtime_s": f"{cost('ising')['runtime_median_s']:.3f}",
        "holdem_storage_bytes": f"{cost('holdem')['storage_median_bytes']:,}",
        "ising_storage_bytes": f"{cost('ising')['storage_median_bytes']:,}",
        "holdem_overhead_pct": f"{over('holdem')['trace_overhead_percent']:.1f}",
        "ising_overhead_pct": f"{over('ising')['trace_overhead_percent']:.1f}",
        "cross_system_tau": f"{cross['kendall_tau_b_tradeoff']:.2f}",
    })
    return result


def inject(template, mapping):
    used = set()
    def repl(match):
        key = match.group(1); used.add(key)
        if key not in mapping:
            raise KeyError(f"unknown manuscript token {key}")
        return str(mapping[key])
    rendered = re.sub(r"\{\{([a-zA-Z0-9_]+)\}\}", repl, template)
    if re.search(r"\{\{.*?\}\}", rendered):
        raise ValueError("unresolved manuscript token")
    return rendered, sorted(used)


def inline(text):
    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    text = re.sub(r"`(.+?)`", r"<font name='Courier'>\1</font>", text)
    return text


def header_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5); canvas.setFillColor(colors.HexColor("#4A5568"))
    canvas.drawString(0.7*inch, 0.42*inch, "Internal review draft - NOT_READY_DO_NOT_SUBMIT")
    canvas.drawRightString(7.8*inch, 0.42*inch, f"Page {doc.page}")
    canvas.restoreState()


def render(md):
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="TitleCustom", parent=styles["Title"], fontName="Helvetica-Bold",
                              fontSize=22, leading=25, textColor=colors.HexColor("#1A202C"), spaceAfter=12))
    styles.add(ParagraphStyle(name="Subtitle", parent=styles["Heading2"], fontSize=13, leading=16,
                              alignment=TA_CENTER, textColor=colors.HexColor("#2B6CB0"), spaceAfter=16))
    styles.add(ParagraphStyle(name="H3Custom", parent=styles["Heading2"], fontSize=13, leading=16,
                              textColor=colors.HexColor("#1A202C"), spaceBefore=12, spaceAfter=7))
    styles.add(ParagraphStyle(name="BodyCustom", parent=styles["BodyText"], fontSize=9.1, leading=12.2,
                              alignment=TA_LEFT, spaceAfter=7))
    styles.add(ParagraphStyle(name="Caption", parent=styles["BodyText"], fontSize=7.8, leading=10,
                              textColor=colors.HexColor("#4A5568"), spaceAfter=10))
    styles.add(ParagraphStyle(name="Reference", parent=styles["BodyText"], fontSize=7.6, leading=9.2,
                              alignment=TA_LEFT, spaceAfter=3))
    doc = SimpleDocTemplate(str(PDF), pagesize=letter, rightMargin=0.72*inch, leftMargin=0.72*inch,
                            topMargin=0.62*inch, bottomMargin=0.62*inch,
                            title="When Does a Shared Seed Justify a Paired Claim?",
                            author="Author(s) pending human confirmation")
    story = []
    chunks = re.split(r"\n\s*\n", md.strip())
    first_h1 = True
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        if chunk.startswith("[[FIGURE:"):
            match = re.match(r"\[\[FIGURE:([^|]+)\|(.+)\]\]", chunk, re.S)
            path = FIG / match.group(1); caption = match.group(2)
            img = Image(str(path)); max_w, max_h = 6.8*inch, 5.8*inch
            scale = min(max_w/img.imageWidth, max_h/img.imageHeight)
            img.drawWidth *= scale; img.drawHeight *= scale
            story.extend([Spacer(1, 5), img, Paragraph(inline(caption), styles["Caption"])])
        elif chunk.startswith("# "):
            if not first_h1: story.append(PageBreak())
            story.append(Paragraph(inline(chunk[2:]), styles["TitleCustom"])); first_h1 = False
        elif chunk.startswith("## "):
            story.append(Paragraph(inline(chunk[3:]), styles["Subtitle"]))
        elif chunk.startswith("### "):
            story.append(Paragraph(inline(chunk[4:]), styles["H3Custom"]))
        elif re.match(r"^\d+\.\s", chunk):
            story.append(Paragraph(inline(" ".join(chunk.splitlines())), styles["Reference"]))
        elif chunk.startswith("`") and chunk.endswith("`"):
            story.append(Table([[Paragraph(inline(chunk), styles["BodyCustom"])]], colWidths=[6.7*inch],
                               style=TableStyle([("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#EDF2F7")),
                                                 ("BOX",(0,0),(-1,-1),0.5,colors.HexColor("#CBD5E0")),
                                                 ("LEFTPADDING",(0,0),(-1,-1),8), ("RIGHTPADDING",(0,0),(-1,-1),8)])))
            story.append(Spacer(1, 5))
        else:
            story.append(Paragraph(inline(" ".join(chunk.splitlines())), styles["BodyCustom"]))
    doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)


def main():
    mapping = values()
    rendered, used = inject(TEMPLATE.read_text(), mapping)
    MARKDOWN.write_text(rendered)
    provenance = {key: {"value": mapping[key], "source": "generated aggregate read by build_manuscript.py"}
                  for key in used}
    (HERE / "manuscript_numbers.json").write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    render(rendered)
    print(f"rendered {PDF}")


if __name__ == "__main__":
    main()
