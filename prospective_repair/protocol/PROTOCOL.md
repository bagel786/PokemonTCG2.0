# PROSPECTIVE PROTOCOL (REPAIRED CAMPAIGN)

**Campaign:** claim-specific prospective repair
**Frozen (to be):** see FREEZE_RECORD — this file is version-controlled NOW but acquires binding status only at the verified freeze commit/tag.
**Status:** PRE-FREEZE DRAFT until tagged.

## 0. Registration-status discipline

This protocol, once committed and pushed, constitutes a **timestamped freeze on the private origin remote** (`github.com/bagel786/PokemonTCG2.0`, private). It is **NOT public preregistration**, confers no registration benefits, and must be described in exactly those terms. Public language ("public", "registered") may appear only after an authorized public deposit exists. Enforced by documentation scan tests.

## 1. Research questions

RQ1. Which evidence classes are necessary for specific claims made from seed-matched stochastic evaluations (branches A–E below)?
RQ2. How well do claim-specific validation strategies detect planted invalid claims **without suppressing valid analyses**, relative to competent simpler alternatives?
RQ3. What are the measured costs (extra system executions, wall/CPU time, storage) of each strategy?
RQ4. Do conclusions transfer qualitatively across an open game environment (RLCard limit hold'em) and an open Monte Carlo simulator (2D Ising)?

Explicitly REMOVED relative to the historical protocol (prospectively deleted BEFORE any outcome):
- Confirmatory uncertainty-coverage (old M4), confirmatory Type-I error (old M5), confirmatory power curves (old M6). Correct calibration needs dedicated independent known-truth banks; it is future work. No coverage/power/type-I result may be claimed anywhere in the repaired outputs; output schemas omit them entirely.

## 2. Claim classes (unchanged in meaning, repaired in operationalization)

- **A — matched description:** artifacts, declared schedules, conditions, rows, denominators consistently recorded.
- **B — statistically paired inference:** sampling/assignment/repeated-measures/joint-model design defines valid paired units + appropriate estimator & uncertainty. Does NOT require replay (C), coupling validity (D), or event alignment (E) unless the declared statistical model itself consumes that evidence. A shared seed alone does NOT justify B.
- **C — scoped deterministic replay:** a declared projection repeats in the contexts named by that replay claim (within-artifact, cross-context incl. genuinely cross-process when claimed).
- **D — CRN coupling:** D1 = coupling construction validity (marginal preservation, stream separation/collision, synchronization assumptions); D2 = measured covariance/variance benefit (may be NONE even when D1 valid).
- **E — event-aligned mechanistic coupling:** stable semantic events receive the declared corresponding random values under explicit dependence assumptions (ontology identity/version, matched+unmatched coverage, key uniqueness, value equality).

## 3. Design summary

- **Systems:** RLCard limit-holdem v1.2.0 (MIT) and ising-monte-carlo-toolkit v0.1.0 (MIT), pins in SYSTEM_MANIFEST.json. Identical mechanics layers implemented ONCE at the harness level and applied to both systems via adapter hooks.
- **Constructions:** fault-grammar instances G01–G16 (FAULT_GRAMMAR.json), each with machine-checkable ground truth derived mechanically by construction-composition rules; includes clean controls for every eligible branch, ≥1 genuinely new construction per branch vs the historical S0–S10 set, ≥2 compound-routing cases, multiple parameterizations within families (e.g., truncation bits ∈ {16,24}, burn draws ∈ {1,3}).
- **Methods:** eight validation strategies B0…B6 + B7 (full claim-specific framework). Competent-capability specifications frozen in BASELINE_SPECS.md BEFORE implementation; unsupported branches return `ABSTAIN_NOT_EVALUATED`; abstention scored separately from detection/false-suppression.
- **Banks (disjoint, zero overlap among themselves and with ALL V1/redesign seeds):**
  - pilot-mechanics: 16 seeds/system/construction — result-excluded (crash/schema/timing/mechanism-presence ONLY);
  - dev: 12 fresh seeds — regression validation of wrappers/classifier wiring; outcomes inspectable ONLY for crashes/legal values/schema/mechanism presence, permanently excluded;
  - final-holdout: 80 fresh seeds/system/construction — acquired exactly once AFTER verified freeze push; no interim aggregation;
  - repeats: residual-repeated-measures construction uses 4 paired repeats per arm (both arms);
  - cost-bank: 50 separate seeds × 3 randomized-order timing repetitions.
- **Primary metrics (frozen):** M1 invalid-detection; M2 false suppression (soft/hard); Mcov coverage/abstention; Mcost per-method measured cost. Definitions/gates in METRICS_AND_GATES.md.
- **Analysis units:** seed nested in system×construction case; case-level results primary; macro-averages over constructions and families; no pooled-seed-as-independent-failure-mode inference. Contrasts: case-level paired permutation + exact McNemar where cell-independence defensible. Details + equations: ANALYSIS_PLAN.md.
- **CRN benefit:** exploratory only, joint seed-cluster bootstrap; NO independence-based delta-method interval anywhere.
- **Budget:** ≤ 4 CPU-hours laptop-scale projected (~1–2 h expected); single-pass holdout; reruns only per frozen crash policy.

## 4. Execution order (binding)

1. Pilot (result-excluded) → fix crashes only.
2. Prefreeze test battery green → PREFREEZE_VALIDATION_REPORT.md.
3. Freeze commit + annotated tag pushed; remote SHA/tag-peel verification (freeze_guard refuses otherwise).
4. Final holdout executed ONCE; rows streamed to immutable location; hashed immediately post-run.
5. Frozen analysis; independent reaggregation; audits.
6. Manuscript + release + human portal. Recommendation-gate failure ≠ study unreadiness.

## 5. Deviations

Any post-freeze deviation: append to DEVIATIONS_LOG.md with timestamp/reason/scope BEFORE running affected analyses; fail closed on scientific deviations discovered after outcomes are visible.
