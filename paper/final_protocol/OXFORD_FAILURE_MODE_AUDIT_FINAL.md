# Oxford-style failure-mode audit — FINAL

Date: 2026-08-25. Method: hostile re-audit derived from the prior rejection,
run against the current manuscript, cover letter, bundle, and release. Each
failure mode below is marked machine PASS/FAIL; human-signoff items are listed
separately and never counted as passing by assertion.

| # | Failure mode | Check performed | Verdict |
|---|---|---|---|
| 1 | Execution-log residue in narrative | pdftotext scan for traceback/.log/stdout/stderr: 0 hits | PASS (machine) |
| 2 | Raw archive/private names in narrative | prohibited-label grep (starmie/dipplin/alakazam et al.) over main.tex + cover letter + release tree: 0 hits; contradiction audit enforces continuously | PASS (machine) |
| 3 | Unexplained method stack | Every stage 1–8 states what it checks, its output, and its failure consequence; assumptions recorded in METHOD_ASSUMPTION_AUDIT M01–M17 | PASS (machine) |
| 4 | Procedure contradiction | CONTRADICTION_AUDIT regenerated each run: factual + machine-verification contradictions must be 0 | PASS (machine, rerun pending in final reproduction) |
| 5 | Unsupported preregistration language | Prohibited-phrase mutation tests (test_protocol_reporting_provenance) enforce frozen-vs-post-acquisition boundary; Git-ordering-only wording retained | PASS (machine) |
| 6 | Promised missing supplement | SM evaluation: no SM promised or used; appendices self-contained (APS_SUPPLEMENTAL_EVALUATION.md) | PASS (machine) |
| 7 | Arithmetic/sign/index error | tests/test_equations.py + recalculate_equation_examples.py + independent raw-row recomputation all PASS today | PASS (machine) |
| 8 | Inference from nonsignificance | Quantiles spanning zero explicitly support no null/equivalence/superiority conclusion anywhere | PASS (machine) |
| 9 | Cross-metric comparison | No comparison of e.g. trace-mismatch % against outcome-mismatch % as if commensurable; strata reported separately with composition caveat | PASS (machine) |
| 10 | Unreconstructable central number | All headline numbers recomputed independently from 58 hash-verified raw files (0 conflicts today) | PASS (machine) |
| 11 | Formulaic reviewer-facing prose | Cover letter rewritten (~503 words): no internal file names, hashes, McNemar, or rebuttal posture; ≤1 factorial sentence | PASS (machine) |
| 12 | Stale figure/table | build_report accounts for every main figure/table; source data regenerated deterministically; visual audit re-bound to current PDF (14 pages) | PASS (machine) |
| 13 | Unverifiable reference | 23/23 bibliography entries verified to primary sources on 2026-08-25 (REFERENCE_AUDIT_FINAL.csv) | PASS (machine) |
| 14 | Claimed human understanding without signoff | All comprehension/signoff gates remain explicitly PENDING (closeout form §12, claim ledger worksheet, defense-guide checkboxes, YAML booleans); nothing pre-signed | PASS (machine, fail-closed) |

## Human signoff pending (not a pass)

Author comprehension of equations/methods/central numbers · final manuscript
approval · AI-use completeness · D03 disposition · rights/license/archive
authorization · reviewer selection · submission authorization.

## Residual risks honestly recorded

- Scope risk: game-engine case with argued (not demonstrated) adjacent-field
  adoption; unsent scope inquiry is the mitigation path.
- The five-pass desk simulation remains an AI-labeled simulation, never a
  substitute for APS editorial judgment.
