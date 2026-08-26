# Statistical Design Details

Companion to ANALYSIS_PLAN.md and METRICS_PREDECLARED.md. Frozen 2026-08-26.

## 1. Proportion estimators and intervals

Detection/false-suppression/missed-failure quantities are binomial proportions over labeled cells.
- Point estimate: p̂ = x/n with x successes out of n cases (denominator always reported).
- Interval: Wilson score interval at 95%:

    center = (x + z²/2) / (n + z²),  half = z·sqrt(p̂(1−p̂)/n + z²/(4n²)) / (n + z²),  z = 1.959964.

- Clopper–Pearson used where a conservative guarantee is asserted (coverage claims).
- Toy example: x=38, n=40 → p̂=0.950, Wilson CI [0.840, 0.988]. Implemented in `analysis/interval_checks.py` against hand-computed fixtures (test_wilson_known_values).

## 2. Two-proportion contrasts (method vs framework)

z = (p̂₁ − p̂₂)/sqrt(p̃(1−p̃)(1/n₁+1/n₂)), pooled p̃=(x₁+x₂)/(n₁+n₂); two-sided; Holm step-down across the primary family {M1,M2} × method contrasts actually run. Effect sizes as risk differences with Newcombe hybrid-score intervals (no pooled-variance assumption for the difference CI).

## 3. Monte Carlo standard errors

For Type-I/power/coverage estimates from B resamples at true rate θ: MCSE = sqrt(θ̂(1−θ̂)/B). With B=2000 and θ≈0.05: MCSE ≈ 0.0049; θ≈0.95: same. Coverage tolerance band [0.90, 0.98] exceeds ±2·MCSE ≈ ±0.010 around nominal miscoverage 0.05 ⇒ band reflects both sampling and Monte Carlo error without further inflation.

## 4. Variance-ratio estimation (CRN)

Given paired outcomes (A_i, B_i), i=1..n:
- Paired differences d_i = A_i − B_i; s²_d with (n−1) df.
- Independent differences: seeded permutation π of seed indices forms d'_i = A_i − B_{π(i)} with π(i)≠i enforced (derangement via frozen deterministic cycle π(i)=i+1 mod n).
- R̂ = s²_d/s²_d'. CI on log R: log R̂ ± z·sqrt(2/(n₁−1)+2/(n₂−1)) (delta method on log of independent variance estimates, df-based constant replaced conservatively by z).
- Interpretation guard: R̂<1 does not imply validity; validity gates are structural (Branch D evidence), R̂ quantifies benefit only.

## 5. Hierarchical comparisons (S8/S9)

Naive paired t (unit=decision), Welch (unpaired), and random-intercept model y_ij = μ + u_i + ε_ij (seed clusters i) compared on the SAME stored outcomes; cluster-robust SEs via cluster bootstrap (resample seeds, B=2000). The framework's recommended analysis per scenario comes from its admitted branch, not post hoc preference.

## 6. Assumption register (per inferential procedure)

| Procedure | Key assumptions | What invalidates it |
|---|---|---|
| Wilson/Clopper intervals | cell independence | shared scenario mechanics across cells handled by reporting per-scenario alongside pooled |
| paired t | d_i i.i.d., finite variance | clustering across hands within a run → unit = seed-condition pair, not hand |
| Welch | independent arms, approximate normality of means | pairing present but ignored (efficiency loss, not bias) |
| cluster bootstrap | exchangeable seed clusters | order-dependent mechanics (S6) → excluded from bootstrap-validity scenarios |
| delta-method log R | s²_d, s²_d' independent | shared outcome bank breaks independence → derangement construction documented; sensitivity check with disjoint split-half banks |

## 7. Forbidden inference patterns (enforced in prose review)

- No "confidence interval" language for intervals whose sampling interpretation is unjustified under the design.
- No equivalence claims (no margins were prespecified).
- No "no effect" from nonsignificance.
- No cross-metric arithmetic (e.g., subtracting a false-suppression rate from a detection rate into a single "score" for headline use; Kendall τ ranking may use the predeclared M1−M2 tradeoff only where explicitly flagged as a composite ordering device, never as a probability).

## 8. Software verification

All interval/test implementations carry fixture tests with independently hand-computed values (EQUATION_AUDIT.md lists each with toy example, sign/indexing checks, and test file references).
