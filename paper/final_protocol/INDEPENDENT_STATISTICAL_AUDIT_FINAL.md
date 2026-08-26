# Independent statistical audit — FINAL (machine-finalization refresh)

Date: 2026-08-25. Verdict: **PASS** — rerun today via
`python paper/final_protocol/scripts/independent_statistics_audit.py --check`
(status PASS, conflicts: 0) against the unchanged raw acquisition trees.
Machine-readable record: `source_data/independent_statistics_verification.json`.
Executable: `scripts/independent_statistics_audit.py`; tests:
`tests/test_independent_statistics.py`. Full method detail remains in
`INDEPENDENT_STATISTICAL_AUDIT.md` (authoritative); nothing here weakens it.

## What was independently recalculated (from 58 hash-verified raw files)

| Quantity | Independent value | Displayed | Match |
|---|---|---|---|
| Deterministic preflight mismatches / units / executions | 0 / 1,000 / 3,000 | same | YES |
| Timed-search trace-digest disagreement clusters | 99/200 | same | YES |
| Byte-count-only disagreement clusters | 96 (subset of digest disagreements; combined rule also 99/200) | same | YES |
| Stress outcome / decision-count / error disagreements | 47 / 93 / 0 | same | YES |
| Historical outcome-record disagreements | 210/2,800 | same | YES |
| Historical decision-count disagreements | 457/2,800 | consistent | YES |
| Historical full available-record disagreements | 458/2,800 | same | YES |
| Factorial primary contrast | +0.55 pp | \PrimaryEstimatePP | YES |
| Primary reweighting quantiles | [−2.05, +3.15] pp | [\PrimaryLowPP,\PrimaryHighPP] | YES |
| Representation / training / interaction contrasts | +0.95 / −0.40 / +1.30 pp | macros | YES |
| Factorial control-gate mismatches | 0 | \FactorialControlMismatch | YES |
| Reweighting draws / frozen analysis seed | 100,000 / recorded seed | \ReweightingDraws | YES |

## Interpretation boundaries (unchanged and re-checked)

- All quantiles are **empirical reweighting quantiles of the realized fixed
  batteries** — descriptive sensitivity ranges only. They are not confidence
  intervals, hypothesis tests, or population intervals anywhere in the
  manuscript.
- The McNemar value is retained solely as a numerical audit artifact; it is not
  admitted inference under the post-acquisition reporting restriction.
- No equality, equivalence, superiority, or null-result inference is drawn from
  any interval spanning zero.
- The historical audit's retrospective status (outcomes predate rule freezing;
  not prospective blinding) is preserved; suppression is a rule application,
  not a blinded finding.

## Independence boundary

No production analyzer, processed unit CSV, or processed summary supplies a
numerator, denominator, outcome, mismatch flag, or reweighting input to this
audit; processed display artifacts are read only after raw-row calculation.
All 58 raw-file hashes match the frozen audit manifest; 32,600 execution-row
schemas validated exactly; 422,475 numeric JSON values inspected with zero
nonfinite values.

## Human signoff

Equation comprehension (§12.1), method assumptions (§12.2), and central-number
verification (§12.4) remain **PENDING human signoff**. Machine PASS never
substitutes for author understanding.
