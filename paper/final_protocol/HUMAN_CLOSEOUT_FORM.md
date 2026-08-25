# Human closeout form — APS Open Science Protocol Article

**Instruction to the human author:** this single document collects every
question that only a human can answer. Complete every section, initial each
line, and return the signed file. Machine tooling (including Codex) must not
fill in, infer, or guess any field. Until the applicable sections are complete,
the submission decision remains `NOT_READY_DO_NOT_SUBMIT`.

Article: *A Protocol for Validating Pairing Assumptions in Seed-Matched
Evaluations of Black-Box Game-Playing Agents* (APS Open Science Protocol
Article). Branch at issuance: `paper/apsos-submission-closeout-20260825`.

---

## 1. Authorship

| # | Question | Answer |
|---|----------|--------|
| 1.1 | Full legal/publication name for **every** author (exact spelling for the byline) | `[ANSWER]` |
| 1.2 | Preferred initials per author (for sign-off records) | `[ANSWER]` |
| 1.3 | Author order exactly as it should appear | `[ANSWER]` |
| 1.4 | Corresponding author (name) | `[ANSWER]` |
| 1.5 | Did any collaborator make a contribution qualifying them for coauthorship (per ICMJE/APS criteria)? List each person and their contribution basis. | `[ANSWER / NONE]` |
| 1.6 | Contribution basis for each listed author (one line per author) | `[ANSWER]` |

Initials/Date: ______

## 2. Affiliation

| # | Question | Answer |
|---|----------|--------|
| 2.1 | Institution name(s) exactly as they should appear | `[ANSWER]` |
| 2.2 | Department/lab, if any | `[ANSWER / NONE]` |
| 2.3 | City, state/province, country | `[ANSWER]` |
| 2.4 | Complete postal address as required by APS | `[ANSWER]` |
| 2.5 | Is “Independent Researcher” the correct affiliation label? If yes, confirm it is accurate and acceptable to you. | `[YES/NO + NOTES]` |

Initials/Date: ______

## 3. Contact

| # | Question | Answer |
|---|----------|--------|
| 3.1 | Corresponding-author email (will appear publicly) | `[ANSWER]` |
| 3.2 | Your ORCID iD (16 digits) | `[ANSWER / DECLINE]` |
| 3.3 | Do other authors have ORCID iDs to include? | `[LIST / N/A]` |

Initials/Date: ______

## 4. CRediT roles

For each author, mark all applicable roles:
Conceptualization · Methodology · Software · Validation · Formal analysis ·
Investigation · Data curation · Visualization · Writing—original draft ·
Writing—review & editing · Supervision · Project administration · Funding acquisition.

```
Author 1 ([NAME]):
  [ ] Conceptualization        [ ] Methodology          [ ] Software
  [ ] Validation               [ ] Formal analysis      [ ] Investigation
  [ ] Data curation            [ ] Visualization        [ ] Writing—original draft
  [ ] Writing—review & editing [ ] Supervision           [ ] Project administration
  [ ] Funding acquisition
Author 2 ([NAME], if any): (repeat grid)
```

Confirm: AI tools are not credited as authors or roles. Initials/Date: ______

## 5. Funding

| # | Question | Answer |
|---|----------|--------|
| 5.1 | Exact funding source(s), if any | `[ANSWER / NONE]` |
| 5.2 | Exact grant number(s) | `[ANSWER / N/A]` |
| 5.3 | If none: confirm this statement — “This research received no external funding.” | `[CONFIRM]` |
| 5.4 | Did any sponsor influence design, execution, or reporting? | `[NO / EXPLAIN]` |

Initials/Date: ______

## 6. Conflicts of interest

Check any that apply and explain; otherwise check “none.”

- [ ] Competition affiliation (which competition/operator, what role, dates): `[EXPLAIN]`
- [ ] Financial interests related to the evaluated system or its operator: `[EXPLAIN]`
- [ ] Employment by an affected platform/operator/rights holder: `[EXPLAIN]`
- [ ] Sponsorship of this work: `[EXPLAIN]`
- [ ] Personal relationships with rights holders or operators: `[EXPLAIN]`
- [ ] **NONE** — I confirm no financial or nonfinancial conflicts to disclose.

Initials/Date: ______

## 7. Acknowledgments

| # | Question | Answer |
|---|----------|--------|
| 7.1 | People/institutions to acknowledge | `[LIST / NONE]` |
| 7.2 | Have those people consented to being named? | `[YES/N/A + EVIDENCE]` |

Initials/Date: ______

## 8. Prior/overlapping disclosure

| # | Question | Answer |
|---|----------|--------|
| 8.1 | Was there a Kaggle report/public discussion/writeup? Give exact title, URL, dates, and what overlaps (text/data/results). | `[ANSWER / NONE]` |
| 8.2 | Any preprint posting of this work? | `[ANSWER / NONE]` |
| 8.3 | Any other manuscript or student-journal submission of overlapping material? Status? | `[ANSWER / NONE]` |
| 8.4 | Approve exact disclosure language to be used in the manuscript (write it here): | `[APPROVED TEXT]` |

Initials/Date: ______

## 9. AI use confirmation

The repository records substantive assistance by OpenAI Codex (GPT-5-family;
exact deployed snapshot not exposed) in `supplement/AI_USE_LOG.csv`, plus
drafting/verification uses disclosed in the manuscript.

| # | Question | Answer |
|---|----------|--------|
| 9.1 | Confirm Codex use record is complete; list any unrecorded substantive uses with approximate dates/tasks | `[CONFIRMED / ADDITIONS]` |
| 9.2 | Any other AI tools used substantively (ChatGPT, Copilot, etc.)? Dates, tasks, versions | `[LIST / NONE]` |
| 9.3 | Were exact model snapshots exposed to you at any time? | `[YES—DETAIL / NO]` |
| 9.4 | Were confidential/restricted data ever submitted to an AI tool? | `[NO / EXPLAIN FULLY]` |
| 9.5 | Confirm compliance with applicable tool terms, privacy/confidentiality, IP, and usage-limit obligations | `[CONFIRM]` |

Initials/Date: ______

## 10. Release rights and license

Answer per component: synthetic conformance suite; admission engine
(`pevl_bench`); analysis scripts; processed neutralized summaries; figures and
source data; schemas/manifests; protocols/docs.

| # | Question | Answer |
|---|----------|--------|
| 10.1 | Who wrote and who owns the synthetic suite code? | `[ANSWER]` |
| 10.2 | Who wrote and who owns the admission code? | `[ANSWER]` |
| 10.3 | Who owns the analysis scripts? | `[ANSWER]` |
| 10.4 | Do coauthors share copyright in any component? | `[YES—WHICH / NO]` |
| 10.5 | Do any processed data contain third-party restricted information? | `[NO / EXPLAIN]` |
| 10.6 | May the code be redistributed publicly? | `[YES/NO/PENDING—REASON]` |
| 10.7 | May processed diagnostics be redistributed publicly? | `[YES/NO/PENDING—REASON]` |
| 10.8 | Approved license choice (e.g., MIT for code, CC BY 4.0 for docs/data — state exactly one per asset class) | `[ANSWER]` |
| 10.9 | Archive approval: authorize deposit (e.g., Zenodo) that mints a DOI? | `[AUTHORIZED / NOT AUTHORIZED]` |
| 10.10 | Maintainer contact for the archived package | `[ANSWER]` |
| 10.11 | DOI/archive creator names (exactly as they should appear) | `[ANSWER]` |

Initials/Date: ______

Restricted/excluded items (engine, binaries, opponent packages, game assets,
private replay observations, policy weights, raw restricted traces,
credentials) remain excluded unless you explicitly assert personal legal
authority to release each one:
- [ ] Confirmed exclusion of all restricted items above.

## 11. Protocol deviation D03 (missing stress localization/actor/timing outputs)

The frozen protocol promised public-package outputs: first-divergence positions,
acting-side/actor localization, and timing summaries for the timed-search stress
test. They are absent from the release.

| # | Question | Answer |
|---|----------|--------|
| 11.1 | Were first-divergence positions actually collected at acquisition time? | `[YES/NO/UNSURE—INVESTIGATED]` |
| 11.2 | Were acting-side/actor outputs collected? | `[YES/NO/UNSURE—INVESTIGATED]` |
| 11.3 | Were timing summaries collected? | `[YES/NO/UNSURE—INVESTIGATED]` |
| 11.4 | If yes to any: where do those files exist now (paths/media)? | `[PATHS]` |
| 11.5 | If unavailable: why — lost, never retained, or legally restricted? | `[EXPLANATION]` |
| 11.6 | If recoverable and lawful: approve generating sanitized processed outputs and adding them to the release? | `[APPROVE / DENY]` |
| 11.7 | If not recoverable/lawful: approve the signed deviation/amendment text prepared in `supplement/PROTOCOL_DEVIATIONS.md` (D03)? | `[APPROVE / REQUEST CHANGES]` |
| 11.8 | Exact date of your disposition | `[YYYY-MM-DD]` |

Signature: ____________________ Initials/Date: ______

## 12. Scientific comprehension signoff

By initialing each line, I affirm personal understanding (not delegation):

- [ ] 12.1 I understand every displayed equation, its symbols, units, and estimator meaning (`EQUATION_AUDIT.md` EQ01–EQ04).
- [ ] 12.2 I confirm the method assumptions recorded in `METHOD_ASSUMPTION_AUDIT.md` (M01–M17).
- [ ] 12.3 I can state the novelty boundary against Rollout Cards, trace-assurance frameworks, AEVAL, event-keyed CRN, paired-seed analysis, CRN theory, streams/substreams, metamorphic testing, and A/A diagnostics.
- [ ] 12.4 I have verified every central number (0 mismatches / 3,000 executions; 99/200 clusters; 47 outcome; 93 decision-count; 0 error; historical 26/200 and 34/200 available-record counts; factorial contrasts and quantiles).
- [ ] 12.5 I confirm the empirical-vs-post-acquisition chronology: frozen eight-stage protocol → prospective retained acquisitions under frozen binary rules → post-acquisition generic claim-class taxonomy and descriptive-only Level-6 mapping (a conservative formalization/template, not prospectively validated).
- [ ] 12.6 I confirm the historical gate was frozen retrospectively after outcomes existed and is not evidence of blinding.
- [ ] 12.7 I understand the D03 omission and my disposition in Section 11.
- [ ] 12.8 I approve the final manuscript and authorize (or decline) APS submission.

Signature: ____________________ Date: `[YYYY-MM-DD]`

---

**Return path:** commit the completed form (or hand it back for transcription)
and re-run the final reproduction pipeline. Every machine gate will re-execute;
human answers will then be transcribed into the title block, declarations,
license, citation metadata, and deviation register before any submission step.
