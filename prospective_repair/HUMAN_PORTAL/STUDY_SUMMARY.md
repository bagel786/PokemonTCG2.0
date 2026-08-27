# STUDY SUMMARY (for the human author)

**Object.** An open, prospective fault-injection benchmark asking which
evidence is necessary for which claim made from seed-matched stochastic
evaluations — detection of planted invalid claims, false suppression of valid
analyses, abstention coverage, and measured cost across eight validation
strategies on two open systems.

**Repair lineage.** The prior `redesign/` campaign is preserved byte-for-byte
as development evidence; its NOT_READY verdict stands and its known defects
(baseline default-ADMIT policy, Branch-B downgrade contradiction, hold'em
policy collapse, missing Ising mechanics, placeholder runtimes, M4–M6
non-estimability) are each mapped to repairs in
`REVIEWER_TO_REPAIR_TRACEABILITY.csv` and regression-tested here.

**Confirmatory design (frozen at `cfeef39` + tag).**
- Fault grammar G01–G19: clean controls per branch, ≥1 genuinely new failure
  class per branch vs V1 (duplicated row ids; cross-process scope violation;
  keyed stream collision; ontology drift support; replanted historical
  policy-blind bug as G19), compound constructions, multiple parameterizations.
- Banks: pilot 16 / dev 12 / **final 80 seeds/system/construction** /
  repeats 4×paired-arm for residual-RM cells / cost 50×3 randomized orderings;
  pairwise disjoint and disjoint from every V1 seed (asserted in code).
- Truth labels derive mechanically from mechanism composition rules;
  implementation must match labels or the scenario is deleted before freeze —
  never relabeled.

**Frozen statistics.** Unit = seed nested in system×construction case; primary
summaries are macros over constructions; method contrasts use case-level
sign-flip permutation with Holm; exact McNemar secondary only; ordinary
two-proportion z-tests are schema-forbidden. CRN variance benefit is
exploratory under a joint seed-cluster bootstrap (no independence delta
method). M4–M6 removed prospectively; no coverage/Type-I/power claims exist
anywhere in outputs (schema-enforced).

**Three gates.** (1) Benchmark integrity — mechanics match labels, freeze
preceded outcomes and was verified remotely, provenance per decision row,
timings real, independent reaggregation agrees exactly. (2) Method
recommendation — M1 ≥ 0.95 ∧ pooled M2 ≤ 0.10 for B7 ∧ not Pareto-dominated;
failure = publishable negative result about B7, NOT unreadiness of the study.
(3) Human submission review — entirely yours.

**Status at assembly:** acquisition single-pass complete → frozen analysis +
independent reaggregation executed → machine gate outcomes recorded in
FINAL_GO_NO_GO.md. All numbers you will quote live in
`analysis/results_macros.json` + `claim_ledger.csv`.
