"""Build the human figure-review PDF from final figure PNGs."""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer


ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "results/final/figures"
OUT = ROOT / "HUMAN_PORTAL/FIGURE_REVIEW.pdf"

ITEMS = [
    ("figure1_claim_specific_branching.png", "Figure 1 - Claim branches", "Does this clearly show alternatives rather than a cumulative ladder?"),
    ("figure2_failure_claim_matrix.png", "Figure 2 - Failure/claim matrix", "Are VALID, DOWNGRADE, INVALID, and not-applicable states understandable without color?"),
    ("figure3_detection_false_suppression.png", "Figure 3 - Detection versus false suppression", "Is the B7 failure and cross-system magnitude difference clear?"),
    ("figure4_statistical_diagnostics_not_confirmatory.png", "Figure 4 - Statistical diagnostics", "Is the non-confirmatory status impossible to miss?"),
    ("figure5_variance_reduction.png", "Figure 5 - Variance ratios", "Is the exact-zero S3 point presented as a warning rather than a success?"),
    ("figure6_runtime_storage_cost.png", "Figure 6 - Cost", "Do you understand which costs are system-level rather than method-level?"),
    ("figure7_cross_system_summary.png", "Figure 7 - Cross-system ordering", "Is M1-M2 labeled as an ordering device, not a probability?"),
    ("figure8_historical_case.png", "Figure 8 - Historical motivation", "Is the restricted retrospective case visibly separate from prospective evidence?"),
]


def footer(canvas, doc):
    canvas.saveState(); canvas.setFont("Helvetica", 8); canvas.setFillColor(colors.HexColor("#4A5568"))
    canvas.drawString(0.7*inch, 0.4*inch, "Human figure review - NOT_READY_DO_NOT_SUBMIT")
    canvas.drawRightString(7.8*inch, 0.4*inch, f"Page {doc.page}"); canvas.restoreState()


def main():
    styles = getSampleStyleSheet()
    title = ParagraphStyle("ReviewTitle", parent=styles["Title"], fontSize=20, leading=24,
                           textColor=colors.HexColor("#1A202C"), spaceAfter=14)
    heading = ParagraphStyle("ReviewHeading", parent=styles["Heading2"], fontSize=14, leading=17,
                             textColor=colors.HexColor("#2B6CB0"), spaceAfter=8)
    body = ParagraphStyle("ReviewBody", parent=styles["BodyText"], fontSize=10, leading=14, spaceAfter=10)
    doc = SimpleDocTemplate(str(OUT), pagesize=letter, rightMargin=0.7*inch, leftMargin=0.7*inch,
                            topMargin=0.65*inch, bottomMargin=0.65*inch,
                            title="Figure Review", author="Human review required")
    story = [Paragraph("Figure Review Packet", title),
             Paragraph("Eight figures generated from machine-readable sources. Review labels, scope, and interpretation. This packet does not authorize submission.", body),
             Paragraph("Decision status: NOT_READY_DO_NOT_SUBMIT", heading),
             Paragraph("Initials after every page only if you can explain the review question in your own words.", body),
             PageBreak()]
    for idx, (filename, label, question) in enumerate(ITEMS):
        story.append(Paragraph(label, heading))
        img = Image(str(FIG / filename)); scale = min(6.8*inch/img.imageWidth, 5.9*inch/img.imageHeight)
        img.drawWidth *= scale; img.drawHeight *= scale; story.append(img); story.append(Spacer(1, 8))
        story.append(Paragraph(f"<b>Review question:</b> {question}", body))
        story.append(Paragraph("Reviewer initials: ____________________", body))
        if idx != len(ITEMS)-1: story.append(PageBreak())
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print(f"built {OUT}")


if __name__ == "__main__":
    main()
