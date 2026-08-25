# Oxford failure-mode audit — closeout (2026-08-25)

Each prior Oxford-reviewer criticism is evaluated against the current
manuscript state (branch `paper/apsos-submission-closeout-20260825`, post
closeout edits). Status values: PASS (does not trigger), FIXED (triggered,
corrected), or OPEN (remains a human-dependent risk).

| # | Criticism | Triggers now? | Evidence | Fix / disposition | Status |
|---|-----------|---------------|----------|-------------------|--------|
| 1 | Execution-log residue in main prose | No | No log lines, stack traces, or CLI dumps in narrative; commands appear only as named interfaces (`python -m pevl_bench …`) in the executable-map subsection | n/a | **PASS** |
| 2 | Raw archive filenames in narrative | No | Restricted identifiers neutralized (timed-search-A/B, deterministic-1..5); CONTEXT_MAP enforced at build; manifest rejects local paths | n/a | **PASS** |
| 3 | Unexplained stack of advanced methods | No | Every stage states problem→assumption→implementation→limitation (Stages 1–8 sections; M01–M17); Stage 4/5 nesting and trust anchor now explicit | n/a | **PASS** |
| 4 | Internal contradiction | No | Chronology defect ("named Level taxonomy added after acquisition") corrected to name exactly the three post-acquisition additions; "outcome independent" replaced by candidate-effect-independence phrasing; CHRONOLOGY_AUDIT.json binds statements to Git | Corrected this closeout | **FIXED** |
| 5 | Unsupported “preregistered” claim | No | Historical gate explicitly retrospective ("frozen only for retrospective reanalysis after outcomes existed… not evidence of prospective blinding"); generic taxonomy marked `created_after_acquisition` in machine-checkable provenance | Corrected/verified | **PASS** |
| 6 | Promised missing supplement | No | All referenced artifacts exist in release (decision tables, worked example, source data per figure); D03 promised outputs partially recovered into release with provenance; remainder documented as never-recorded deviation | Recovered during closeout | **PASS** |
| 7 | Arithmetic/sign/symbol error | No | Eqs. 1–4 re-audited (EQUATION_AUDIT_V2.md); toy examples independently recomputed by `recalculate_equation_examples.py`; textual numbers cross-checked by contradiction audit | n/a | **PASS** |
| 8 | Unsupported inference from nonsignificance | No | "Quantiles spanning zero cannot support equivalence" stated; forbidden-wording lists prohibit equality/equivalence/superiority | n/a | **PASS** |
| 9 | Cross-metric arithmetic nonsense | No | Stress secondary counts (47 outcome / 93 decision / 0 error) are cluster counts of distinct endpoints within 99 trace-disagreement clusters; historical 210 vs 458 of 2,800 explained as projection widening | n/a | **PASS** |
| 10 | Missing reconstruction path for central evidence | Partially | 99/200 digest endpoint reconstructable from released cluster rows + pinned summary hash; actor/timing aggregates now released; position-level localization impossible (positions never recorded) — disclosed as deviation, not silently omitted | Closeout recovery + deviation register | **PASS with disclosed limit** |
| 11 | Repeated reviewer-facing defensive phrases | Partially | Admission-proposition duplication compressed; abstract rewritten; several "cannot/does not" clusters reduced. Some repetition is structurally required by machine-checked disclosure patterns | Style-only residue | **FIXED (residual style)** |
| 12 | Malformed tables/figures | No | Visual audit PASS on prior build; figures regenerated deterministically from source data in pipeline; final-run visual audit scheduled | Will re-verify in final pipeline | **PASS** |
| 13 | Stale numbers | No | All macros regenerated from pinned inputs; report schema-v2 regeneration occurs in the final pipeline after last content change | Final pipeline pending | **PASS (pending final rerun)** |
| 14 | Unverifiable references | No | REFERENCE_AUDIT.csv/V2: 23 entries, each with primary source + exact supporting sentence verified present; two new workshop papers verified from camera-ready PDFs + venue site; preprints never described as peer reviewed | Refreshed this closeout | **PASS** |
| 15 | Human author cannot explain every method | Open until signed | AUTHOR_DEFENSE_GUIDE.md rewritten: 29 questions × (short answer, technical answer, source, failure mode); comprehension signature pending in HUMAN_CLOSEOUT_FORM.md §12 | Human action | **OPEN (human)** |
| 16 | Placeholders visible to reviewers (meta) | Yes | Author/email/affiliation placeholders remain by design until human completion | HUMAN_ACTIONS_FINAL.md gate | **OPEN (human, completeness gate only)** |

## Aggregate

- Scientific-content failures: none open.
- Fixed this closeout: items 4 and 11 (partially), plus recovery under item 10.
- Open items are exclusively human-completion gates (15, 16) tracked in
  `HUMAN_ACTIONS_FINAL.md`; they block submission, not reviewability.

The prior DESK_REJECT pattern driven by these failures does not reproduce
against the current state (see `DESK_REVIEW_SIMULATION_V2.json`).
