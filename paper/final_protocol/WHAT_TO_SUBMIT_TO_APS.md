# What goes where: APS submission versus public archive

## INITIAL APS SUBMISSION (upload by human only)

| Item | File / source | Status |
|---|---|---|
| Manuscript PDF (single file, text+figures) | `submission_bundle_draft/manuscript.pdf` | ready |
| Supplemental Material PDF | none (appendices keep paper self-contained) | evaluated, not used |
| Cover letter | `submission_bundle_draft/cover_letter.txt` | ready pending human signoff |
| Author/affiliation metadata | entered in APS form from `human_answers.yaml` via apply script | placeholders until YAML |
| Corresponding-author designation | one author, flagged in YAML | human choice |
| ORCID iD | corresponding author REQUIRED by APS; coauthors encouraged | human supplies |
| Title & abstract | `submission_bundle_draft/title_abstract.txt` | ready |
| Data Availability Statement | questionnaire answers → `data_availability_statement.txt` (Version B now; A only when archive+DOI live) | ready |
| PhySH terms (star ≥1 primary) | `submission_bundle_draft/physh_candidates.md` | candidates verified |
| Editorial information | scope inquiry (unsent, optional), overlap-disclosure file | ready |
| Suggested/excluded reviewers | `suggested_reviewers_candidates.md` (+ your exclusions) | optional, human selects |
| Funding/conflict information | APS form entries from YAML | placeholders until YAML |

## ACCEPTANCE STAGE ONLY (not for initial upload)

- `manuscript_source_for_acceptance.zip` — REVTeX source, bibliography,
  generated tables/macros, figure PDFs. Marked NOT REQUIRED FOR INITIAL
  SUBMISSION inside the bundle.

## PUBLIC ARCHIVE (Zenodo or equivalent — separate from APS, after authorization)

Sanitized code and processed-data package (`public_release_candidate/`, zip +
`MANIFEST.sha256`); approved LICENSE files replacing `.proposed` placeholders;
`CITATION.cff`; minted DOI; archive metadata (`ARCHIVE_METADATA_TEMPLATE.json`
/ `ZENODO_METADATA_TEMPLATE.json`); reproduction documentation
(`CLEAN_ENV_REPRODUCTION.json`, release README commands).

## NOT INITIALLY REQUIRED BY APS

LaTeX source and figure sources at initial submission — prepared anyway in the
bundle's acceptance zip so no rework is needed later.

## NEVER SUBMIT OR PUBLISH

Restricted tournament engine or binaries · third-party opponent packages ·
game assets/metadata · raw restricted traces · private replay observations ·
policy weights without clean provenance · credentials · internal QA dossiers
(desk simulations, closeout forms, claim-ledger internals, worker-agent
reports, rejection correspondence) · any component without confirmed rights ·
the review package while it carries no-license placeholders.
