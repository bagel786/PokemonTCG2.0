# Method and Assumption Audit

Status: complete machine audit; human scientific approval pending.

## B0 - Schedule matching only

1. **Problem:** detects declared row/seed/context mismatches.
2. **Why appropriate:** sufficient for Branch-A descriptive schedule wording.
3. **Assumptions:** recorded fields are authentic; artifact IDs are meaningful.
4. **Unit:** one retained schedule row.
5. **Implementation:** `benchmark.baselines.b0_schedule_matching_only`.
6. **Output:** ADMIT/SUPPRESS for A and a simple paired decision for B.
7. **Invalidated by:** effective-seed conversion, silent missing rows, wrong grouping.
8. **Does not establish:** replay, CRN synchronization, event alignment, or a
   statistical reference distribution.

## B1 - Outcome-only A/A

1. **Problem:** detects visible terminal-outcome instability under repetition.
2. **Why appropriate:** low-cost noise-floor diagnostic when terminal outcome is
   the declared projection.
3. **Assumptions:** A/A repetitions are actually retained and comparable.
4. **Unit:** repeated terminal outcome within a schedule row.
5. **Implementation:** `b1_outcome_only_aa`; the current runner passes no
   empirical A/A variance, so the baseline defaults to stability.
6. **Output:** paired/replay admission or downgrade.
7. **Invalidated by:** missing A/A bank or a richer claim than terminal outcome.
8. **Does not establish:** trace equality or coupling. The runner's missing bank
   makes B1 weaker than its label suggests.

## B2 - Trace-level A/A

1. **Problem:** tests a declared within-artifact trace projection.
2. **Why appropriate:** directly targets Branch C when projection/context scope
   is honored.
3. **Assumptions:** repeated runs and projection rule are prospectively declared.
4. **Unit:** artifact-seed-context repetition.
5. **Implementation:** `b2_trace_level_aa` reads `within_replay_ok` in one
   evidence bundle.
6. **Output:** scoped replay admission/suppression.
7. **Invalidated by:** insufficient context coverage or post-hoc projection.
8. **Does not establish:** cross-arm event alignment or paired statistical
   validity.

## B3 - Extra within-seed replication

1. **Problem:** exposes residual execution variability.
2. **Why appropriate:** empirical repeated execution is relevant to replay and
   hierarchical residual-noise planning.
3. **Assumptions:** repeats are stored and the analysis uses the seed cluster.
4. **Unit:** seed-condition cluster, not individual decision/event.
5. **Implementation:** `b3_within_seed_replication`, minimum two repeats.
6. **Output:** replay admission, suppression, or fail-closed.
7. **Invalidated by:** discarded repeat outcomes or decision-level counting.
8. **Does not establish:** that all paired inference requires exact replay.

## B4 - Honest unpaired analysis

1. **Problem:** provides valid wording when pairing evidence is absent.
2. **Why appropriate:** S10 uses independent arm seeds by construction.
3. **Assumptions:** arms are independent at the declared analysis unit.
4. **Unit:** independent arm observation/seed-condition.
5. **Implementation:** `b4_unpaired_analysis` downgrades paired wording.
6. **Output:** unpaired-only statistical recommendation.
7. **Invalidated by:** hidden pairing or dependent arms not modeled.
8. **Does not establish:** equivalence, replay, CRN, or event alignment. Its high
   framework-scoring false suppression reflects branch wording, not invalid
   unpaired science.

## B5 - Clustered/hierarchical analysis

1. **Problem:** respects residual seed/repeated-measure dependence.
2. **Why appropriate:** directly targets Branch B's analysis-unit justification.
3. **Assumptions:** cluster IDs and design justification are correct; clusters
   are exchangeable for bootstrap/model interpretation.
4. **Unit:** seed-condition cluster.
5. **Implementation:** `b5_clustered_hierarchical`; the decision layer checks
   the unit/design, while the promised outcome-level hierarchical comparison is
   not estimable because S8 repeats were not retained.
6. **Output:** paired admission/downgrade/suppression.
7. **Invalidated by:** pseudoreplication, order-dependent nonexchangeability, or
   a model that does not match the hierarchy.
8. **Does not establish:** replay or event alignment. It detected all hard-invalid
   Branch-B cells with no valid-cell suppression in this bank; no equivalence or
   universal superiority is inferred.

## B6 - Event-keyed white-box coupling

1. **Problem:** prevents stateful draw-index shifts from reassigning randomness
   across semantic events.
2. **Why appropriate:** directly targets Branch E and can support D when
   marginals/covariance are also measured.
3. **Assumptions:** stable event ontology, collision-resistant keying, recorded
   values, and defended dependence structure.
4. **Unit:** declared semantic event within a seed-condition pair.
5. **Implementation:** SHA-256-derived `EventKeyedRNG` and logged event IDs.
6. **Output:** event/coupling admission or downgrade.
7. **Invalidated by:** unstable or arm-specific keys, policy collapse, key
   collisions, or missing marginal checks.
8. **Does not establish:** statistical pairing for every claim. Hold'em S3 also
   ignores the policy distinction, so its exact-zero variance is degenerate.

## B7 - Full claim-specific framework

1. **Problem:** route a stated claim to an independent evidence gate.
2. **Why appropriate:** different scientific claims require different evidence.
3. **Assumptions:** branch classification and each evidence predicate implement
   the canonical framework without cross-branch leakage.
4. **Unit:** one method-branch decision cell; inferential units remain branch
   specific.
5. **Implementation:** `classifier.classify_branch` over evidence bundles.
6. **Output:** ADMIT/DOWNGRADE/SUPPRESS/FAIL_CLOSED.
7. **Invalidated by:** classifier-framework contradiction, wrong construction
   labels, or incomplete evidence acquisition.
8. **Does not establish:** theory, universal optimality, or submission readiness.
   In this campaign, B7 fails the predeclared Branch-C detection and pooled
   false-suppression criteria.

## Statistical procedures

| Procedure | Problem solved | Unit | Assumptions | Output | What invalidates/does not establish |
|---|---|---|---|---|---|
| Wilson score interval | binomial uncertainty for M1-M3 | labeled cell | independent/exchangeable cell interpretation | 95% interval | shared mechanics make pooled prevalence interpretation inappropriate |
| Two-proportion z test + Holm | frozen B0-B6 vs B7 contrasts | pooled cells | independent proportions | adjusted p-values | methods score identical cells, so dependence violates the simple test; secondary only |
| Paired t | mean paired difference | seed pair | iid finite-variance differences | mean/test/interval | cannot be confirmatory Type-I/coverage without retained known-truth banks |
| Welch | independent-arm mean difference | arm observation | independent arms; approximate mean normality | mean/test/interval | ignores real pairing and cannot repair hidden dependence |
| Cluster bootstrap | repeated-measure uncertainty | seed cluster | exchangeable clusters | bootstrap interval | S8 repeat outcomes absent; frozen confirmatory comparison not executed |
| Variance ratio | paired vs cyclic cross-seed precision | seed pair | comparable marginals; approximate variance independence | R and log-scale interval | R<1 does not prove coupling validity; shared bank weakens delta-method independence |
| Kendall tau-b | cross-system rank association | eight methods | two system score vectors | tau-b | two systems cannot establish general consistency; M1-M2 is not a utility |
| Logging microbenchmark | trace acquisition cost | timed run | comparable bare/instrumented paths | median relative overhead | not per-method runtime and not universal hardware performance |

## Audit verdict

The method descriptions now state purpose, assumptions, unit, implementation,
output, invalidators, and boundaries. B1, B5 outcome-level validation, M4-M6,
M9, and M10 remain incomplete by retained-schema construction. This is a
reported failure, not a prose-only caveat.
