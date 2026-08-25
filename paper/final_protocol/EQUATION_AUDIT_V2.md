# Equation audit V2 — closeout refresh (2026-08-25)

Status: **machine checks PASS; human verification PENDING** (see
`HUMAN_CLOSEOUT_FORM.md` Section 12). This document records the closeout
re-verification of every displayed equation in `main.tex` and the reviewer-
required Eq. 3 clarification. Full per-equation detail remains authoritative in
`EQUATION_AUDIT.md`; nothing in V2 weakens it.

## EQ01 — Trace-disagreement proportion (`eq:trace-disagreement`)

- Re-verified against `tests/test_equations.py` and
  `scripts/recalculate_equation_examples.py`: toy example 0.40, byte-count-only
  detection, missing-profile fail-closed behavior all PASS.
- Case-study provenance unchanged: digest endpoint 99/200; digest-or-byte also
  99/200; byte-count disagreements are a subset of digest disagreements.
- Symbols, units, analysis unit (seed-condition cluster), and indicator
  semantics unchanged from V1.

## EQ02 — Binary paired difference (`eq:paired-difference`)

- Direction test PASS (intervention minus control; C4−C1 positive when C4 wins).
- Units and sign convention unchanged.

## EQ03 — Stratified paired-unit empirical reweighting (`eq:paired-reweighting`)

- **Closeout change (reviewer-required):** the manuscript now states explicitly
  that because strata may contain unequal unit counts, the outer factor $1/K$
  makes each replicate an **equally weighted mean of stratum means**, not an
  unqualified battery mean over all units; with equal $n_k$ the two coincide.
- Toy example re-verified: one stratum, differences $[1,0,-1]$, indices
  $[1,1,2]$ → replicate $2/3$.
- Interpretation guard retained: the 2.5th/97.5th percentiles are labeled
  **empirical reweighting quantiles** of the realized battery everywhere they
  appear (main text, Table III context, Fig. 4/5 captions, appendix). No
  manuscript text presents them as confidence intervals, hypothesis tests, or
  population-effect statements. The frozen plan's original "95% interval"
  language is preserved only as disclosed protocol history, never as the
  current reporting label.

## EQ04 — Two-by-two factorial contrasts (`eq:factorial`)

- Signs and toy values re-verified: $(T,R,G,J)=(0.04,0.025,0.015,0.01)$ for
  rates $(0.50,0.52,0.51,0.54)$.
- Remains in the Appendix; main text retains only the admitted descriptive
  consequence (fixed-battery contrast + unresolved status).

## Symbol/unit audit

Unchanged from V1: `i` schedule/paired unit; `k` strata; `r` execution profiles;
`b` replicates; `j` within-stratum draws; `H` ordered digest–byte record;
`Y` binary outcome; `d` paired difference; `mu` cell win rate. All displayed
contrasts unitless before percentage-point presentation. The admission-safety
proposition remains prose-stated with machine-checked property tests; no
decorative equations were added during closeout.

## Verification chain

| Check | Result |
|---|---|
| `tests/test_equations.py` (release + final_protocol) | PASS |
| `scripts/recalculate_equation_examples.py` → `source_data/equation_examples.json` | PASS |
| Independent statistics audit (`test_independent_statistics.py`) | PASS |
| Contradiction audit textual-number checks | run in final pipeline |

Human signoff of EQ01–EQ04 comprehension is item 12.1 of
`HUMAN_CLOSEOUT_FORM.md`.
