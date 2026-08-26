# APS Open Science — current official requirements refresh

Date checked: 2026-08-25. Method: official APS pages (live where reachable;
otherwise dated Wayback Machine captures of the official pages, snapshot date
recorded per item). Live `journals.aps.org` and `www.aps.org` returned HTTP 403
to this environment on 2026-08-25; items verified only through archived
captures are labeled with the capture date. Items that could not be verified
from any official page are explicitly marked **UNVERIFIED**.

## 1. Journal identity and APC waiver

- Requirement: APS Open Science (APSO, ISSN 3070-2240) is an open-access APS journal publishing "high-quality, useful research" across physics and adjacent fields.
- Official source: https://journals.aps.org/apsos/ (Wayback capture 2026-07-14).
- Stage: pre-submission.
- Current project status: article type declared as APS Open Science Protocol Article.
- Action needed: none for machine pass; human author should re-check the live page before submission.
- **Current waiver deadline: "APC waived for all submissions and transfers received before 01 Sept 2026."** Submissions on/after 2026-09-01 may incur an article publication charge. The planned submission window must respect this deadline or budget an APC.
- License: articles publish under CC BY 4.0 with Crossref DOIs (launch press release, Wayback capture 2025-12-03).

## 2. Scope and acceptance criteria

- Requirement: scope spans "the full breadth of physics and adjacent fields," including methodological and technical developments, replication/reproducibility studies, and negative/null results (official APS press releases, archived 2025-12-03 and 2026-05-21).
- Official source: https://www.aps.org/about/news/2025/12/open-science-expand-global-participation (archived); https://www.aps.org/about/news/2026/04/open-science-publishes-first-papers (archived). The journal-specific `/apsos/about` page could not be fetched live (403) and has no archive capture — **journal-page wording UNVERIFIED**; repository guidance already cites it, so treat exact journal-scope sentences as unconfirmed until the live page is accessible.
- Stage: initial.
- Project status: manuscript foregrounds experimental design/methodology over the game case; a scope inquiry is prepared but unsent (`APS_SCOPE_INQUIRY_READY.txt`).
- Action needed: optional human decision to send the scope inquiry.

## 3. Article types and Protocol Article definition

- Requirement: APSO accepts multiple article types including methods papers. The specific **Protocol Article definition could not be verified from any retrievable official page**: `/apsos/authors` was 403 live and its only archive capture (2025-12-20) returned 404 — **UNVERIFIED**.
- Repository guidance (APS_DESK_FIT.md, prior audits) describes a Protocol Article as a step-by-step description of an effective experimental/computational procedure enabling reproducibility and adoption. This remains the operating definition but is flagged unverified against current official text.
- Stage: initial.
- Project status: manuscript is organized as a stepwise protocol with evidence ladder, claim map, conformance suite, and case study.
- Action needed: human author must confirm the Protocol Article definition and any length/format specifics from the live authors page at submission time.

## 4. Initial-submission file requirements

- Requirement: PDF-only at initial submission; "all textual material and figures should be in a single file"; supplemental material (if any) as a separate PDF. Full source files (REVTeX preferred) are required only at acceptance.
- Official source: https://journals.aps.org/authors/web-submission-guidelines-physical-review and https://journals.aps.org/authors/editorial-policies-submissions (Wayback captures 2025-05-28); Submission FAQ (capture 2025-12-05).
- Stage: initial (PDF) / acceptance (source).
- Project status: single self-contained `manuscript.pdf` prepared in the submission bundle; REVTeX source zip prepared separately and marked NOT REQUIRED FOR INITIAL SUBMISSION.
- Action needed: none beyond final PDF inspection.

## 5. Cover letter

- Requirement: cover letter accompanies every submission; used to indicate suitability and (optionally) suggested referees; also the place to flag joint submissions and CJK author names. Disclosure of AI use to editors is expected in the cover letter under the AI policy.
- Official sources: same web-submission guidelines + FAQ captures; AI policy predecessor page (below).
- Stage: initial.
- Project status: `cover_letter_final_draft.md/.txt` (~400–550 words) includes article type, novelty boundary, history of overlapping public report, data/software status, AI-disclosure pointer, and reviewer-suggestion offer.
- Action needed: human review/signoff of the letter before upload.

## 6. Author, affiliation, corresponding author, ORCID

- Requirements: email address and affiliation for **every** author (affiliation tracked at institution/corporation level, not department); exactly one designated corresponding author who certifies the submission; corresponding author **must** provide an ORCID iD; all authors are encouraged to link ORCIDs (co-authors receive email links post-submission).
- Official sources: web-submission guidelines + FAQ captures (dates above).
- Stage: account creation + initial.
- Project status: all author fields remain placeholders pending the single human-answer YAML; no metadata inferred from Git or elsewhere.
- Action needed: human completes `human_answers.template.yaml`.

## 7. Data Availability Statement (DAS)

- Requirements: every published article carries a DAS generated from submission-questionnaire answers; publicly shared artifacts must be cited in the reference list and named in the DAS; embargoes allowed for privacy/trade-secret reasons; if data cannot be public, authors must agree to private sharing on reasonable request; SM files must not be used as a substitute for FAIR data sharing.
- Official source: https://journals.aps.org/authors/data-availability-statements (Wayback capture 2026-04-04). The April-2026 text names Physical Review journals without explicitly naming APSO — extension to APSO **UNVERIFIED**; assume it applies and verify at submission.
- Stage: initial questionnaire → proofing → publication.
- Project status: two candidate DAS versions prepared (public companion approved vs not approved); restricted materials are honestly bounded with no false "available on request" promise for third-party-restricted items; editorial-risk item flagged instead.
- Action needed: YAML selection between Version A/B (A only when ownership+license+archive+DOI are authorized).

## 8. AI-use disclosure policy

- Requirement: APS released an **updated AI policy for APS journals on 17 June 2026** (announcement linked from APSO home). The updated page (https://journals.aps.org/authors/appropriate-use-ai-tools) could not be fetched (403, no archive) — **current wording UNVERIFIED**. The verified predecessor policy (https://journals.aps.org/authors/ai-based-writing-tools, capture 2025-11-11) required: no AI authorship; disclosure of writing-tool use to editors in the cover letter; substantive research uses described reproducibly in Methods (tool name, version, manufacturer); generative-AI images prohibited.
- Operating assumption (fail-safe superset): disclose research-conduct AI use in Methods, drafting/editing/packaging assistance in Acknowledgments, mention in cover letter, keep a machine-readable activity log, and state human direction/verification. This satisfies both the predecessor and any stricter successor policy.
- Stage: initial + publication.
- Project status: two-location disclosure present in the manuscript; completeness gated on human YAML confirmation of all historical ChatGPT/Codex/other uses.
- Action needed: human confirms AI-use completeness in YAML; re-check live policy page before submission.

## 9. Supplemental Material

- Requirements: SM = useful-but-nonessential material; never a substitute for the main result or a length-limit dodge; separate files, not copyedited, must be publication-ready; README.TXT with prominent Description field mandatory; cited in main-text reference list as "[20] See Supplemental Material at [URL] for [description]"; all SM references must also appear in the main bibliography.
- Official sources: https://journals.aps.org/authors/supplemental-material-instructions (capture 2025-08-22); editorial-policies page (capture 2025-05-28).
- Stage: initial (optional) → publication.
- Project status: evaluated; decision recorded in the bundle — technical detail stays in appendices; no separate SM PDF is required because appendices + the DOI-bound computational companion carry everything nonessential. If the human later opts for SM, the bundle checklist lists the required README/citation steps.
- Action needed: none unless human overrides.

## 10. PhySH classification

- Requirement: PhySH terms are mandatory during submission (minimum one concept; 3–8 typical; star exactly one primary; primary usually from Research Areas facet).
- Official sources: https://physh.aps.org (fetched live 2026-08-25); https://journals.aps.org/authors/physh (capture 2024-08-24); term list verified at https://physh.org/concepts/... (live 2026-08-25).
- Stage: initial (mandatory step).
- Project status: candidates prepared in `PHYSH_CANDIDATES.md` (primary: Machine learning; secondaries: Reinforcement learning, Artificial intelligence, Monte Carlo methods, Statistical methods [facet to re-confirm in widget]).
- Action needed: human selects/stars terms in the submission widget.

## 11. Submission metadata

- Requirements: title, abstract, authors/affiliations/emails, corresponding author, ORCID, PhySH classification, DAS questionnaire, funding/conflict info as requested, suggested/excluded reviewers optional.
- Title/abstract word limits for APSO specifically: **UNVERIFIED** (length guide predates APSO and contains no APSO row). The abstract is held to 175–210 words as an internal conservative bound.
- Stage: initial.
- Project status: `SUBMISSION_METADATA_DRAFT.yaml` prepared with placeholders; nothing inferred.
- Action needed: human fills via YAML application script.

## Differences from repository guidance found during refresh

1. Waiver deadline (2026-09-01) was not previously recorded anywhere in the repository — added here; submission timing now carries an explicit deadline note.
2. The June 2026 APS AI-policy update was not reflected in older repository notes; the disclosure strategy above is built to satisfy the stricter superset, and the live policy must be re-checked by the human.
3. No conflicts found with current file requirements (PDF-only initial submission), cover-letter expectations, DAS rules, or PhySH process; repository guidance remains consistent with official sources.
