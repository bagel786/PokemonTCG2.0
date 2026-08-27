# METRICS, GATES, AND READINESS (frozen at freeze)

## Metrics (all WITH exact denominators; Wilson 95% intervals for proportions)

- **M1 invalid-detection rate** — P(decision ∈ {SUPPRESS, FAIL_CLOSED} | GT=INVALID), denominator = covered invalid cells for that method×branch. Strict detection only; DOWNGRADE on INVALID reported separately as caveat-only.
- **M2 false-suppression rate** — P(decision ∈ {DOWNGRADE→soft, SUPPRESS/FAIL_CLOSED→hard} | GT=VALID); components reported; headline uses soft+hard combined. DOWNGRADE on GT=DOWNGRADE constructions is CORRECT by definition.
- **Mcov capability coverage** — fraction of applicable decision cells NOT abstained, per method×branch; abstention otherwise unscored.
- **Mdet|cov** — detection conditional on coverage (companion to M1; guards abstain-to-win).
- **Mcost per-method cost** — extra system executions required (count/type), evidence-acquisition wall+CPU time, classifier time, raw artifact + bundle bytes; median/p95/run-to-run spread from the dedicated cost bank; equal-work interpretation: base pair identical across methods; costs are the marginal acquisition each method additionally performs.
- **Secondary/descriptive:** per-case seed-correct fractions; macro-averages over constructions/families/systems; conclusion-flip table (paired-vs-unpaired estimator sign/significance agreement on holdout outcomes) with case-level unit; CRN benefit R with joint seed-cluster bootstrap interval (EXPLORATORY ONLY; degenerate zero-variance flagged DEGENERATE_NOT_BENEFIT).

## Removed prospectively (before outcomes; forbidden in all outputs)

Old M4 (coverage/calibration), M5 (Type-I error), M6 (power curves), N∈{10,20,40,80} subsampling grids, known-truth bank resampling proxies. Output schemas contain no such aggregates; doc-scan tests reject any coverage/power/type-I RESULT claims. Correct calibration requires dedicated independent banks: FUTURE WORK.

## Unit & aggregation discipline

- L1 cell = (system × construction × seed × method × branch).
- Case = (system × construction): report fraction of seeds correct/detected/false-suppressed.
- Primary summaries: macro over constructions within fault family × system; family macros; NO inference treating seeds as independent failure modes; pooled rates descriptive-only.

## Method contrasts

- PRIMARY: for each simple method vs B7 and predeclared key pairs (B5 vs B7 included), case-level paired difference on strict-detection and false-suppression indicators → two-sided sign-flip permutation test over cases (exact where ≤ 2^C feasible else 10,000 random flips, seeded 20260827) + cluster(seed)-bootstrap CI on the paired risk difference.
- SECONDARY where 1:1 matched cells exist and clustering is negligible at cell level: exact McNemar on discordant cells, reported as secondary only.
- FORBIDDEN everywhere: ordinary independent two-proportion z-tests on method columns (schema validator rejects such outputs). Multiplicity: Holm within the primary family {detection contrasts ∪ fs contrasts}; effect sizes and denominators primary, p-values secondary.

## Gates (three, separated)

1. **Benchmark-integrity gate** (must pass for ANY submission-ready status): mechanics match labels (independent audits), freeze pushed before outcomes and verified remotely, raw schema complete incl. provenance payloads + nonzero real timings, statistics use frozen units/procedures, no unresolved defect changes a truth label or headline result, independent reaggregation agrees exactly.
   FAIL ⇒ overall `NOT_READY_DO_NOT_SUBMIT` regardless of anything else.
2. **Method-recommendation gate** (may pass or fail; failure can be a publishable negative result): B7 achieves M1 ≥ 0.95 AND pooled M2 ≤ 0.10 on covered cells AND is not Pareto-dominated by any simpler method jointly on (M1, M2, Mcov, Mcost) with dominance defined as ≥ on all four and > on at least one. Recommendation wording follows whichever method wins; if B5 or another baseline dominates B7, the paper reports exactly that.
3. **Submission gate (human)**: comprehension questionnaire, citation full-text verification, authorship/CRediT, AI-use approval, license/rights, PDF review, venue choice. Machines leave ALL items pending; no fabricated human sign-off.

Machine final statuses possible: `SUBMISSION_CANDIDATE_PENDING_HUMAN_REVIEW` (gate1 PASS; gates 2 either way documented) or `NOT_READY_DO_NOT_SUBMIT` (gate1 FAIL). Never conflated again.
