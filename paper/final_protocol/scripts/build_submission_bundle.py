#!/usr/bin/env python3
"""Assemble paper/final_protocol/submission_bundle_draft/ deterministically.

Initial-submission bundle for APS Open Science (PDF-only per current APS
guidance). Acceptance-stage source material is packaged separately and clearly
marked NOT REQUIRED FOR INITIAL SUBMISSION. No upload happens here.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import zipfile
from pathlib import Path

FINAL = Path(__file__).resolve().parents[1]
BUNDLE = FINAL / "submission_bundle_draft"
FIXED_ZIP_DATE = (2026, 8, 25, 0, 0, 0)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write(name: str, text: str) -> None:
    (BUNDLE / name).write_text(text.rstrip() + "\n", encoding="utf-8")


def main() -> int:
    BUNDLE.mkdir(exist_ok=True)
    for stale in BUNDLE.glob("*"):
        if stale.is_file():
            stale.unlink()
        else:
            shutil.rmtree(stale)

    # 1. manuscript.pdf
    shutil.copyfile(FINAL / "main.pdf", BUNDLE / "manuscript.pdf")

    # 2. acceptance-stage source zip + marker
    source_zip = BUNDLE / "manuscript_source_for_acceptance.zip"
    payload_files = ["main.tex", "mainNotes.bib", "references.bib", "results_macros.tex"]
    with zipfile.ZipFile(source_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        for rel in payload_files:
            path = FINAL / rel
            info = zipfile.ZipInfo(f"manuscript_source/{rel}", date_time=FIXED_ZIP_DATE)
            archive.writestr(info, path.read_bytes())
        for fig in sorted((FINAL / "figures").glob("*.pdf")):
            info = zipfile.ZipInfo(f"manuscript_source/figures/{fig.name}", date_time=FIXED_ZIP_DATE)
            archive.writestr(info, fig.read_bytes())
        for tab in sorted((FINAL / "tables").glob("*.tex")):
            info = zipfile.ZipInfo(f"manuscript_source/tables/{tab.name}", date_time=FIXED_ZIP_DATE)
            archive.writestr(info, tab.read_bytes())
        macros = FINAL / "results_macros.tex"
        info = zipfile.ZipInfo("manuscript_source/generated/results_macros.tex", date_time=FIXED_ZIP_DATE)
        archive.writestr(info, macros.read_bytes())
    write(
        "MANUSCRIPT_SOURCE_NOT_REQUIRED_FOR_INITIAL_SUBMISSION.txt",
        "manuscript_source_for_acceptance.zip contains REVTeX source, bibliography,\n"
        "generated tables/macros, and figures. Per current APS guidance, only the\n"
        "compiled PDF is required at initial submission; upload this zip at the\n"
        "acceptance stage when APS requests source files.\n",
    )

    # 3. cover letter
    letter = (FINAL / "cover_letter_final_draft.md").read_text()
    letter_txt = letter.replace("**", "").replace("`", "")
    letter_txt = re.sub(r"(?m)^#\s+", "", letter_txt)
    write("cover_letter.txt", letter_txt)

    # 4. submission metadata
    shutil.copyfile(FINAL / "SUBMISSION_METADATA_DRAFT.yaml", BUNDLE / "submission_metadata.yaml")

    tex = (FINAL / "main.tex").read_text(encoding="utf-8")
    abstract = tex.split("\\begin{abstract}")[1].split("\\end{abstract}")[0].strip()
    abstract = re.sub(r"\s+", " ", abstract)
    title = re.search(r"\\title\{([^{}]+)\}", tex).group(1)
    keywords = ("paired comparisons; common random numbers; seed-matched evaluation; "
                "reproducibility; agent evaluation; simulation validation")
    # expand result macros inside the abstract
    macros = dict(re.findall(r"\\newcommand\{\\([A-Za-z]+)\}\{([^{}]*)\}",
                             (FINAL / "results_macros.tex").read_text()))
    def expand(text: str) -> str:
        for name, value in sorted(macros.items(), key=lambda kv: -len(kv[0])):
            text = re.sub(rf"\\{name}(?:\{{\}})?", value, text)
        return text.replace("\\ ", " ")
    write("title_abstract.txt",
          f"Title: {title}\n\nAbstract: {expand(abstract)}\n\nKeywords: {keywords}")

    # 6. DAS (Version B content until apply script swaps Version A after authorization)
    das_versions = (FINAL / "data_availability_versions.md").read_text(encoding="utf-8")
    block_b = das_versions.split("## VERSION B — PUBLIC COMPANION NOT APPROVED")[1]
    block_b = block_b.split("### Selection rule")[0]
    write("data_availability_statement.txt",
          "Data Availability Statement (Version B — public companion not yet approved)\n"
          + block_b.strip())

    # 7-10. disclosure files from canonical sources
    shutil.copyfile(FINAL / "ai_disclosure.md", BUNDLE / "ai_disclosure.txt")
    shutil.copyfile(FINAL / "author_contributions.md", BUNDLE / "author_contributions.txt")
    conflicts_funding = (
        (FINAL / "conflict_of_interest.md").read_text(encoding="utf-8")
        + "\n\n---\n\n# Funding statement\n\n"
        "**Submission blocker: human confirmation required** via human_answers.yaml "
        "(funding.statement). Recommended default only if personally confirmed: "
        "\"This research received no external funding.\" Sponsor role: [human-confirmed or NONE].\n"
    )
    write("conflicts_and_funding.txt", conflicts_funding)
    write("overlap_disclosure.txt",
          "# Prior/overlapping disclosure (DRAFT - exact language transcribed by apply_human_answers.py)\n\n"
          "[Approved overlap disclosure sentence(s) - transcribed by apply script]\n\n"
          "Facts to disclose once confirmed: any Kaggle competition report or public\n"
          "write-up covering part of this work; any preprint posting; any prior\n"
          "student-journal submission and its status. Nothing here is asserted without\n"
          "the author's confirmation because the repository cannot establish it.\n")

    # 11-12. classification + reviewers
    shutil.copyfile(FINAL / "PHYSH_CANDIDATES.md", BUNDLE / "physh_candidates.md")
    shutil.copyfile(FINAL / "SUGGESTED_REVIEWERS_CANDIDATES.md", BUNDLE / "suggested_reviewers_candidates.md")

    # 13. archive/DOI status
    status = (FINAL / "release/RELEASE_STATUS.json").is_file()
    write("archive_and_doi_status.md",
          "# Archive and DOI status\n\n"
          "- Public-release candidate: built and manifest-verified at\n"
          "  `public_release_candidate/` (+ deterministic zip), status **CANDIDATE_NOT_AUTHORIZED**.\n"
          "- License: NO LICENSE GRANTED pending human confirmation (`LICENSE.*.proposed` placeholders).\n"
          "- DOI: none (blank until a deposit exists; validator blocks invented DOIs).\n"
          "- Recovered stress aggregates (actor counts, timings): included as processed data,\n"
          "  redistribution pending explicit approval; first-divergence positions never recorded.\n"
          "- The review package is not represented as publicly available anywhere in this bundle.\n"
          f"- RELEASE_STATUS.json present: {status}\n")

    # 14. initial-submission checklist
    write("APS_INITIAL_SUBMISSION_CHECKLIST.md",
          "# APS initial submission checklist\n\n"
          "- [x] Single self-contained PDF (text + figures): manuscript.pdf\n"
          "- [x] Cover letter (article type, problem, protocol, results, novelty boundary,\n"
          "      scope relevance, overlap-history pointer, availability, AI disclosure, reviewers)\n"
          "- [x] Author/affiliation/corresponding-author metadata prepared (placeholders until YAML)\n"
          "- [x] Corresponding-author ORCID flagged REQUIRED (APS rule)\n"
          "- [x] Title/abstract file (abstract within internal 175-210-word bound)\n"
          "- [x] Data Availability Statement (Version B; A auto-selected only when authorized)\n"
          "- [x] AI-use disclosure in Methods + Acknowledgment locations + cover-letter pointer\n"
          "- [x] PhySH candidates verified against official taxonomy (star one primary in widget)\n"
          "- [x] Editorial information: scope inquiry drafted (unsent); overlap disclosure file\n"
          "- [ ] Suggested/excluded reviewers (optional; human selects)\n"
          "- [ ] Funding/conflict entries completed in the submission form (human)\n\n"
          "Excluded from this bundle on purpose: rejection history, internal desk\n"
          "simulations, closeout forms, claim-ledger internals, full AI-use log (available\n"
          "on request), private repository, raw engine data, restricted traces, no-license\n"
          "review package, virtual environments, worker-agent reports.\n")

    # 15. acceptance-stage checklist
    write("APS_ACCEPTANCE_STAGE_SOURCE_CHECKLIST.md",
          "# Acceptance-stage source checklist (prepare now, submit only if accepted)\n\n"
          "- [ ] Upload manuscript_source_for_acceptance.zip (REVTeX main.tex, references.bib,\n"
          "      generated tables/macros, figure PDFs) identifying the main manuscript file.\n"
          "- [ ] Include any Supplemental Material source if ever created (none currently).\n"
          "- [ ] Confirm figures match published rendering (deterministic builder outputs).\n"
          "- [ ] Provide ORCID links for all authors via APS co-author email flow.\n"
          "- [ ] Complete license/formalities per APS (CC BY 4.0 publication applies).\n")

    write("APS_SUPPLEMENTAL_EVALUATION.md",
          "# Supplemental Material evaluation\n\n"
          "Decision: NO separate Supplemental Material PDF is used.\n\n"
          "Rationale: APS SM policy reserves supplements for nonessential-but-useful\n"
          "material; the manuscript must stand alone. All technical depth needed to\n"
          "verify claims is already in the appendices (trace record fields, factorial\n"
          "algebra, reweighting details, artifact/rights boundary), and the executable\n"
          "companion (future DOI archive) carries what must not live in a journal PDF\n"
          "(schemas, rules, tests). Using SM instead of the archive would also violate\n"
          "the APS note that SM files are not FAIR data-sharing substitutes.\n\n"
          "If the human later opts into an SM PDF, it needs: self-contained title/author\n"
          "block placeholder, README.TXT with Description field, citation line 'See\n"
          "Supplemental Material at [URL] for ...' in the main reference list, and all\n"
          "SM references mirrored in the main bibliography.\n")

    print(f"bundle assembled: {len(sorted(p.name for p in BUNDLE.iterdir()))} items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
