# What Does a Shared Seed Justify? A Prospective Fault-Injection Benchmark for Paired Stochastic Evaluations

Draft status: NOT READY — D-R2 evidence-contract defects discovered post-outcome; fail-closed per frozen protocol. Human repair-cycle authorization needed.

## Abstract

Practitioners justify comparisons of stochastic systems by sharing random
seeds, re-running "for replay," invoking event-keyed generators, or declaring
a hierarchical model — often as if these were interchangeable marks of a
trustworthy paired evaluation. They are not: they support different claims.
We formalize five claim classes that seed-matched evaluations routinely make —
matched description (A), statistically paired inference (B), scoped replay
(C), common-random-numbers coupling validity (D), and event-aligned coupling
(E) — and freeze an open, prospective fault-injection benchmark that plants
19 known-truth failures (plus clean controls) inside two open
systems: RLCard limit hold'em and a 2D Ising Metropolis simulator. Eight
validation strategies — from schedule checks through outcome A/A and
trace A/A diagnostics to a full claim-specific router (B7) — are compared on
planted-failure detection, false suppression of valid analyses, coverage
against abstention, and measured cost, using case-level paired inference with
seeds nested inside constructions. The protocol was frozen (commit `cfeef395ed708ef640ff8e7322b8f2e1ec7550cb`)
and pushed before any outcome existed; the historical V1 campaign that
motivated this repair reported the framework's own implementation bugs as its
headline numbers, which is exactly the failure mode prospective discipline is
meant to expose. Results on the repaired benchmark: B7 achieves strict
detection 0.861 (3720/4320) at pooled false suppression 0.124 (747/6000) on
covered cells; simple clustered analysis (B5) attains 1.000 (320/320) /
0.778 (560/720); method-level acquisition costs differ by
n/a× between cheapest and most expensive strategies; exploratory
common-random-number benefit intervals are reported without independence
assumptions. The benchmark-integrity gate FAILED; per protocol this renders the package NOT_READY_DO_NOT_SUBMIT regardless of recommendation outcomes. All data, code, freeze records, and deviation
logs ship for independent verification.

## 1. Scientific question

When two stochastic systems are evaluated under shared seeds, which evidence
is *necessary* for which claim? We ask empirically: how well do candidate
validation strategies detect planted invalid claims without suppressing valid
analyses or imposing excessive cost?

## 2. Five claim classes

- **A — matched description**: artifacts, declared schedules, conditions,
  row counts, denominators agree.
- **B — statistically paired inference**: the design defines valid paired
  units and a sound estimator/uncertainty procedure. Sharing a seed alone is
  NOT a justification; exact replay is NOT required either. Repeated
  measures, declared matched assignment, cluster-respecting units, defended
  joint models, or hierarchical analyses each suffice on their own terms.
- **C — scoped deterministic replay**: a declared projection repeats within
  the scope asserted (same artifact; across contexts/processes only if those
  contexts actually exist).
- **D — CRN coupling validity** vs **benefit**: construction soundness
  (marginals preserved, streams separated, no key collisions) is separate
  from whether coupling actually reduces variance.
- **E — event-aligned mechanistic coupling**: stable semantic events receive
  identical values under declared dependence assumptions, checked via
  ontology identity/version, key uniqueness, and matched/unmatched coverage —
  not merely nonempty overlap.

## 3. Related work

Common-random-number theory [Glasserman & Yao 1992; Heidelberger 1993],
streamed RNGs [L'Ecuyer et al. 2002], event-keyed counter-based generation
[Buffalo et al. 2026], paired-seed statistical structure [Sharma 2026],
deterministic-replay infrastructure [Mudasiru 2026], rollout cards
[Masters et al. 2026], simulation V&V [Sargent 2013], metamorphic/statistical
oracle testing [Patrick et al.; Guderlei & Mayer], A/A practice [Kohavi
lineage]. Closest current threats are fault-injection scoreboards for agent
pipelines (Sabot), sabotaged research codebases (ASMR-Bench; MLE-Sabotage),
and ground-truth decoy banks for proteomics FDR ("entrapment"); each lacks
the combination studied here — claim-class branching for seed-matched
evaluations × planted truth × false-suppression accounting over validation
strategies × cross-domain open execution. Established ingredients are cited,
not claimed.

**Contributions.** (1) A frozen, open fault grammar with mechanically derived
truth labels spanning five claim classes and compound cases. (2) A repaired
empirical comparison of eight validation strategies including honest
abstention semantics. (3) Measured per-method costs under equal-work
accounting. (4) An audited negative-result lineage: our earlier campaign's
own classifier contradicted its framework and wrapped placeholder timings —
released here as development evidence demonstrating why result-excluded
audits matter.

## 4. Benchmark

Constructions G01–G19 derive every label from mechanism composition rules
(TRUTH_RULES); each system executes identical harness-level mechanics.
Development pilots (16 seeds) and dev regression bank (12 seeds) were run
pre-freeze solely for crash/schema/mechanism-presence gating; the confirmatory
bank uses 80 disjoint fresh seeds acquired in one pass AFTER a verified push
of commit `cfeef395ed708ef640ff8e7322b8f2e1ec7550cb` plus annotated tag. Repeated-measures cells retain
four paired repeats per arm; a dedicated cost bank (50 seeds × 3 randomized
orderings) measures marginal acquisition per strategy.

## 5. Validation strategies

B0 schedule-only; B1 outcome-A/A (consumes real retained repetitions);
B2 trace-A/A (scoped repeat); B3 within-seed replication; B4 honest unpaired;
B5 clustered/hierarchical; B6 event-keyed white-box; B7 claim-specific router
with predicate-level provenance. Unsupported branches return
ABSTAIN_NOT_EVALUATED; abstention never scores as detection or suppression.
Capability mutations verify each baseline degrades rather than admits when
its evidence is removed.

## 6. Protocol discipline

Freeze = timestamped commit pushed to a PRIVATE remote — not preregistration.
Three gates stay separated: benchmark integrity (must pass),
method recommendation (may honestly fail), human submission review (remains
pending by design).

## 7. Results

All numbers below are injected from machine-readable aggregates
(`results_macros.json`); the ledger maps each to raw-file hashes and scripts.

### 7.1 Detection / false suppression
| meth | br | sys | cov | det n | det | fs n | fs |
|---|---|---|---|---|---|---|---|
| B0 | A | holdem | 1.0 | 420/480 | 0.875 | 160/1040 | 0.154 |
| B0 | A | ising | 1.0 | 420/480 | 0.875 | 160/960 | 0.167 |
| B0 | B | holdem | 0.0 | - | - | - | - |
| B0 | B | ising | 0.0 | - | - | - | - |
| B0 | C | holdem | 0.0 | - | - | - | - |
| B0 | C | ising | 0.0 | - | - | - | - |
| B0 | D | holdem | 0.0 | - | - | - | - |
| B0 | D | ising | 0.0 | - | - | - | - |
| B0 | E | holdem | 0.8421 | - | - | - | - |
| B0 | E | ising | 0.8889 | - | - | - | - |
| B1 | A | holdem | 1.0 | 0/480 | 0.0 | 0/1040 | 0.0 |
| B1 | A | ising | 1.0 | 0/480 | 0.0 | 0/960 | 0.0 |
| B1 | B | holdem | 1.0 | 0/160 | 0.0 | 400/400 | 1.0 |
| B1 | B | ising | 1.0 | 0/160 | 0.0 | 320/320 | 1.0 |
| B1 | C | holdem | 1.0 | 0/480 | 0.0 | 0/1040 | 0.0 |
| B1 | C | ising | 1.0 | 0/480 | 0.0 | 0/960 | 0.0 |
| B1 | D | holdem | 0.0 | - | - | - | - |
| B1 | D | ising | 0.0 | - | - | - | - |
| B1 | E | holdem | 0.8421 | - | - | - | - |
| B1 | E | ising | 0.8889 | - | - | - | - |
| B2 | A | holdem | 0.0 | - | - | - | - |
| B2 | A | ising | 0.0 | - | - | - | - |
| B2 | B | holdem | 0.0 | - | - | - | - |
| B2 | B | ising | 0.0 | - | - | - | - |
| B2 | C | holdem | 1.0 | 480/480 | 1.0 | 0/1040 | 0.0 |
| B2 | C | ising | 1.0 | 480/480 | 1.0 | 0/960 | 0.0 |
| B2 | D | holdem | 0.0 | - | - | - | - |
| B2 | D | ising | 0.0 | - | - | - | - |
| B2 | E | holdem | 0.8421 | - | - | - | - |
| B2 | E | ising | 0.8889 | - | - | - | - |
| B3 | A | holdem | 0.0 | - | - | - | - |
| B3 | A | ising | 0.0 | - | - | - | - |
| B3 | B | holdem | 0.8421 | 0/160 | 0.0 | 240/240 | 1.0 |
| B3 | B | ising | 0.8333 | 0/160 | 0.0 | 160/160 | 1.0 |
| B3 | C | holdem | 0.1579 | 240/240 | 1.0 | - | - |
| B3 | C | ising | 0.1667 | 240/240 | 1.0 | - | - |
| B3 | D | holdem | 0.0 | - | - | - | - |
| B3 | D | ising | 0.0 | - | - | - | - |
| B3 | E | holdem | 0.8421 | - | - | - | - |
| B3 | E | ising | 0.8889 | - | - | - | - |
| B4 | A | holdem | 0.0 | - | - | - | - |
| B4 | A | ising | 0.0 | - | - | - | - |
| B4 | B | holdem | 1.0 | 160/160 | 1.0 | 400/400 | 1.0 |
| B4 | B | ising | 1.0 | 160/160 | 1.0 | 320/320 | 1.0 |
| B4 | C | holdem | 0.0 | - | - | - | - |
| B4 | C | ising | 0.0 | - | - | - | - |
| B4 | D | holdem | 0.0 | - | - | - | - |
| B4 | D | ising | 0.0 | - | - | - | - |
| B4 | E | holdem | 0.8421 | - | - | - | - |
| B4 | E | ising | 0.8889 | - | - | - | - |
| B5 | A | holdem | 0.0 | - | - | - | - |
| B5 | A | ising | 0.0 | - | - | - | - |
| B5 | B | holdem | 1.0 | 160/160 | 1.0 | 320/400 | 0.8 |
| B5 | B | ising | 1.0 | 160/160 | 1.0 | 240/320 | 0.75 |
| B5 | C | holdem | 0.0 | - | - | - | - |
| B5 | C | ising | 0.0 | - | - | - | - |
| B5 | D | holdem | 0.0 | - | - | - | - |
| B5 | D | ising | 0.0 | - | - | - | - |
| B5 | E | holdem | 0.8421 | - | - | - | - |
| B5 | E | ising | 0.8889 | - | - | - | - |
| B6 | A | holdem | 0.0 | - | - | - | - |
| B6 | A | ising | 0.0 | - | - | - | - |
| B6 | B | holdem | 0.1579 | - | - | 160/160 | 1.0 |
| B6 | B | ising | 0.1111 | - | - | 80/80 | 1.0 |
| B6 | C | holdem | 0.0 | - | - | - | - |
| B6 | C | ising | 0.0 | - | - | - | - |
| B6 | D | holdem | 0.1579 | 160/160 | 1.0 | 0/80 | 0.0 |
| B6 | D | ising | 0.1111 | 80/80 | 1.0 | 0/80 | 0.0 |
| B6 | E | holdem | 1.0 | 160/160 | 1.0 | 0/80 | 0.0 |
| B6 | E | ising | 1.0 | 80/80 | 1.0 | 0/80 | 0.0 |
| B7 | A | holdem | 1.0 | 420/480 | 0.875 | 80/1040 | 0.077 |
| B7 | A | ising | 1.0 | 420/480 | 0.875 | 80/960 | 0.083 |
| B7 | B | holdem | 1.0 | 160/160 | 1.0 | 0/400 | 0.0 |
| B7 | B | ising | 1.0 | 160/160 | 1.0 | 0/320 | 0.0 |
| B7 | C | holdem | 1.0 | 240/480 | 0.5 | 0/1040 | 0.0 |
| B7 | C | ising | 1.0 | 240/480 | 0.5 | 0/960 | 0.0 |
| B7 | D | holdem | 1.0 | 960/960 | 1.0 | 20/560 | 0.036 |
| B7 | D | ising | 1.0 | 880/880 | 1.0 | 454/560 | 0.811 |
| B7 | E | holdem | 1.0 | 160/160 | 1.0 | 80/80 | 1.0 |
| B7 | E | ising | 1.0 | 80/80 | 1.0 | 33/80 | 0.412 |

### 7.2 Case-level contrasts
| contrast | cases | risk diff | CI | p perm | p Holm |
|---|---|---|---|---|---|
| B0_schedule_only - B7 [d | 37 | -0.973 | [-1.189,-0.784] | 0.0001 | 0.0013 |
| B0_schedule_only - B7 [f | 37 | -0.144 | [-0.292,0.002] | 0.0793 | 0.4758 |
| B1_outcome_aa - B7 [dete | 37 | -1.257 | [-1.466,-1.034] | 0.0001 | 0.0013 |
| B1_outcome_aa - B7 [fs] | 37 | -0.009 | [-0.176,0.149] | 0.8873 | 1.0 |
| B2_trace_aa - B7 [detect | 37 | -0.932 | [-1.189,-0.676] | 0.0001 | 0.0013 |
| B2_trace_aa - B7 [fs] | 37 | -0.252 | [-0.389,-0.12] | 0.0018 | 0.0126 |
| B3_within_seed_reps - B7 | 37 | -1.095 | [-1.338,-0.858] | 0.0001 | 0.0013 |
| B3_within_seed_reps - B7 | 37 | -0.117 | [-0.277,0.036] | 0.1415 | 0.7074 |
| B4_unpaired_analysis - B | 37 | -1.149 | [-1.372,-0.912] | 0.0001 | 0.0013 |
| B4_unpaired_analysis - B | 37 | -0.009 | [-0.176,0.149] | 0.8873 | 1.0 |
| B5_cluster_hierarchical  | 37 | -1.149 | [-1.372,-0.912] | 0.0001 | 0.0013 |
| B5_cluster_hierarchical  | 37 | -0.063 | [-0.232,0.097] | 0.4327 | 1.0 |
| B6_event_keyed_whitebox  | 5 | 0.318 | [0.0,0.671] | 0.5 | 1.0 |

### 7.3 Costs
| meth | wall med s | wall p95 | cpu med | bytes med | max extra execs |
|---|---|---|---|---|---|

### 7.4 Exploratory CRN benefit
(no eligible benefit cells)

### 7.5 Conclusion changes (descriptive)
descriptive conclusion-change table shipped as `conclusion_changes_descriptive.csv` (case-level); treat as descriptive only.

### 7.6 Negative findings retained from the V1 campaign
The unrepaired campaign measured Branch-B false suppression of 37.5% for B7
(120/320) caused by a classifier bug downgrade path, zero-variance hold'em S3
"benefit" from policy-blind actions, runtime placeholders of 0.0 s in published
cost medians, and non-estimable M4–M6 aims whose proxies initially shipped
unlabeled. None may be read as evidence about the conceptual framework; all
are reproduced here as regression targets (G19 replants the policy-blind
fault as a labeled failure).

## 8. Limitations

Designed-failure prevalence is author-chosen and does not estimate natural
rates; two systems bound transferability; benchmark authorship overlaps
framework authorship (mitigated by mutation tests, holdout separation, and
independent reaggregation but not eliminated); construction was AI-assisted
under human direction (full log referenced below); wall-clock think budgets
make timing-sensitivity partially scheduler-dependent by design.

## 9. Data, code, AI use

Everything ships in the repository tree `prospective_repair/` (protocol,
grammar, wrappers, tests, raw rows, aggregates, figure sources, deviation
log, claim ledger, AI_USE_LOG.md). No journal submission, registry entry,
DOI minting, or archive upload occurred; public deposits require explicit
human authorization.

## References

1. Sharma, U. (2026). When Does Pairing Seeds Reduce Variance? arXiv:2512.24145v3.
2. Buffalo, V., Pearson, C. A. B., & Klein, D. (2026). Realizing Common Random Numbers: Event-Keyed Hashing for Causally Valid Stochastic Models. arXiv:2603.11084.
3. Glasserman, P., & Yao, D. (1992). Some Guidelines and Guarantees for Common Random Numbers. Management Science 38(6).
4. L'Ecuyer, P., Simard, R., Chen, E. J., & Kelton, W. D. (2002). An Object-Oriented Random-Number Package with Many Long Streams and Substreams. Operations Research 50(6).
5. Masters, C., Liu, Z., & Albrecht, S. V. (2026). Rollout Cards. arXiv:2605.12131.
6. Mudasiru, R. (2026). Deterministic Replay for AI Agent Systems. arXiv:2607.16200.
7. Girshovitz, I., Zeltzer, D., & Gilad-Bachrach, R. (2026). Automated Synthesis and Adversarial Validation of Executable Causal Research Pipelines. arXiv:2607.21173.
8. Gan, E., et al. (2026). ASMR-Bench: Auditing Sabotage in ML Research Codebases. arXiv:2604.16286.
9. Anthropic (2024). Sabotage Evaluations for Frontier Models. arXiv:2410.21514. And CTRL-ALT-DECEIT (2025), arXiv:2511.09904.
10. Wen, B., Käll, L., Noble, W. S., & Keich, U. (2025). Assessment of FDR control in tandem MS using entrapment. Nature Methods.
11. Patterson, A., Neumann, S., White, M., & White, A. (2024). Empirical Design in Reinforcement Learning. JMLR 25(318).
12. Agarwal, R., et al. (2021). Deep RL at the Edge of the Statistical Precipice. NeurIPS 34.
13. Field, C. A., & Welsh, A. H. (2007). Bootstrapping Clustered Data. JRSS-B 69(3).
14. Sargent, R. G. (2013). Verification and Validation of Simulation Models. Journal of Simulation 7(1).
15. Zha, D., et al. (2019). RLCard. arXiv:1910.04376.
16. Dehigaspetiyage Don, S. Y. (2026). ising-monte-carlo-toolkit v0.1.0.
17. Jott2121 (2026). Sabot: planted-fault scoreboard for agent stacks. GitHub.

*Reference-status flag:* items verified against primary metadata where marked
VERIFIED in REFERENCE_AUDIT.csv-equivalent ledger; remaining items require
human full-text confirmation before submission (tracked pending task).
