# When Does a Shared Seed Justify a Paired Claim?

## A prospective benchmark across an open card game and Ising Monte Carlo

**Draft status:** Internal methods manuscript for human review. Not submission-ready. The protocol was frozen in public git history before final outcome acquisition, but it was not registered in a public registry.

### Abstract

Shared seeds are routinely used to compare stochastic systems, yet the evidentiary meaning of a shared seed depends on the claim. We replace a cumulative validation ladder with five independent branches: matched description, statistically paired inference, deterministic replay, common-random-number (CRN) variance reduction, and event-aligned mechanistic comparison. Before final outcomes, we froze eleven construction-labeled scenarios, eight validation strategies, 40 final seeds, and thirteen metrics, then ran the benchmark in RLCard limit hold'em and a two-dimensional Ising Metropolis simulator.

The retained corpus contains 34160 labeled decision cells and 854 outcome pairs. For statistically paired claims, both the full framework (B7) and the clustered/hierarchical baseline (B5) detected 100.0% of hard-invalid cells (n=160), but B7 suppressed or downgraded 37.5% of valid cells while B5 suppressed 0.0%. Across all branches, B7 detected 89.4% of hard-invalid cells and falsely suppressed 14.6% of valid cells, failing both its Branch-C detection requirement and the prespecified 10% pooled false-suppression limit. Results also differed by system: B7 detection was 99.1% in hold'em and 79.7% in Ising.

The campaign cannot support its planned confirmatory calibration, Type-I-error, or power claims because the runner did not retain the frozen A/A null banks, fixed-effect constructions, or repeated S8 outcomes. Centered bootstrap results are reported only as post-freeze diagnostics. The data therefore reject B7 as a universal recommendation and show that claim-specific reasoning is necessary but not sufficient: the classifier, benchmark wrapper, and retained schema must themselves be validated. The correct status is **NOT_READY_DO_NOT_SUBMIT**.

### 1. Introduction

A seed is an input value, not a scientific guarantee. Two executions can record the same seed while using different effective namespaces, consuming draws in different semantic contexts, inheriting mutable worker state, or applying an analysis whose reference distribution is unrelated to execution replay. Conversely, a statistically sound repeated-measures or randomized design can justify paired inference even when exact trace replay is impossible. Treating all these questions as one cumulative ladder both admits unsupported claims and suppresses valid ones.

This paper asks: **What evidence is needed for each kind of paired claim, and how much does each validation strategy improve reliability relative to simpler alternatives?** Its intended contribution is evaluation science rather than a new random-number technique. The study prospectively compares validation strategies under known construction labels, measures both detection and false suppression, and exercises the same failure taxonomy in an open game and an open scientific simulator.

The results are deliberately unfavorable to the full framework. The prospectively frozen success gate is not met, and important confirmatory outcome banks are absent. We report those failures because a validation framework that hides its own false suppressions or silently substitutes outcomes would contradict its purpose.

[[FIGURE:figure1_claim_specific_branching.png|Figure 1. The five claim branches are alternatives by inferential objective, not rungs on a universal ladder.]]

### 2. Claim-specific problem formulation

Branch A concerns only whether recorded runs shared declared schedule fields and a complete denominator. It does not imply replay, coupling, or statistical validity. Branch B concerns the justification for a paired estimator and uncertainty procedure. Randomized assignment, probability sampling, repeated measures, a hierarchical model, or a defended joint stochastic model may justify it; exact replay and event alignment are not universal prerequisites.

Branch C is scoped deterministic replay: repeated execution of one artifact must reproduce a declared trace projection across the tested contexts. Branch D concerns CRN coupling: the construction must preserve marginals, induce measurable covariance, and improve or at least quantify precision relative to independent pairing. Branch E is stronger and mechanistic: corresponding semantic events must have stable identifiers and receive recorded random quantities under declared dependence assumptions.

The decision rule is fail-closed only within a selected branch. Missing Branch-C evidence cannot downgrade a supported Branch-B claim. This independence is central because the benchmark later shows that a software classifier can violate the conceptual rule even when its documentation states it correctly.

### 3. Prior work and exact contribution

CRN theory, streams/substreams, paired-seed inference, event-keyed hashing, deterministic replay, metamorphic testing, rollout cards, A/A diagnostics, and simulation verification and validation are established. Sharma analyzes when paired seeds reduce variance in a multi-agent economic simulator. Buffalo, Pearson, and Klein explain why stateful draw indices may not represent stable causal events and propose event-keyed counter-based randomness. Rollout cards preserve records and drop manifests. Replay systems test reproducible execution. None of those components is claimed as new here.

The closest conceptual predecessor is Girshovitz, Zeltzer, and Gilad-Bachrach's ARA pipeline, which evaluates a validity-first causal-research assistant under controlled assumption violations and reports surfaced concerns and downgraded interpretations. The narrower proposed contribution here is a benchmark object specific to seed-matched stochastic comparisons: five claim classes, eleven planted scenarios, eight strategies, explicit false-suppression measurement, and a game-plus-physics execution. The manuscript-stage novelty recheck found no source supplying all of those elements, but novelty feasibility does not cure the empirical incompleteness reported below.

### 4. Systems and prospective protocol

The game system is RLCard 1.2.0 limit hold'em under MIT. Arm A is a random policy and arm B a conservative policy, evaluated over ten hands per run. Dealer and agent substreams derive from NumPy SeedSequence children. The scientific system is ising-monte-carlo-toolkit v0.1.0 under MIT, configured as an L=20 two-dimensional Ising Metropolis simulation with 20 equilibration and 90 measurement sweeps. Arm temperatures are 2.269 and 2.9, and the outcome is mean absolute magnetization over the retained measurement trajectory.

Commit `62ad878` froze the framework, systems, scenarios, methods, final seeds, exclusions, statistical procedures, stopping rule, and figure/table plan before acquisition. Pilot and final seeds were disjoint. The final grid used 40 seeds per system-scenario except S7, where the construction intentionally removed every third row and retained 27/40 per system. No data-driven exclusions or interim looks were permitted.

The protocol is a public git-history freeze, not a public registry submission. No OSF registration was created.

### 5. Known-ground-truth failure benchmark

Scenarios S0-S10 cover a clean control; seed-namespace truncation; stateful draw shift; event-keyed repair; clock-bounded computation; process-global state; queue ordering; silently dropped rows; benign residual randomness with a valid repeated-measures design; pseudoreplication; and a valid unpaired design. Ground-truth labels were fixed by construction for each claim branch before outcomes.

The unit for decision metrics is one system-scenario-seed-method-branch cell. This does not estimate failure prevalence in natural systems. It estimates behavior on the designed scenario bank. S7 is supposed to have missing schedule rows; the raw-integrity check therefore expects 27 retained pairs and 1,080 decision cells per system in S7, rather than treating the planned injection as accidental missingness.

[[FIGURE:figure2_failure_claim_matrix.png|Figure 2. Construction-known claim labels for scenarios S0-S10. Letters and symbols duplicate the color encoding.]]

### 6. Baseline methods

B0 checks only recorded schedule fields. B1 adds an outcome-only A/A control. B2 compares a declared trace projection in A/A repetitions. B3 adds within-seed repetitions. B4 uses honest unpaired wording and analysis. B5 models the declared seed-condition cluster or repeated-measure structure. B6 uses white-box event-keyed coupling. B7 applies the complete claim-specific evidence bundle.

These are not ordered by assumed quality. B4 can be the correct strategy for S10, and B5 can be the strongest simple strategy for Branch B. Configuration complexity ranges from 3 declared fields for B0 to 16 for B7. White-box RNG access and an event ontology are required only for B6 and the relevant B7 branches.

### 7. Statistical evaluation

For a method and branch, hard-invalid detection is

`p_det = x_det / n_inv`,

where `x_det` is the number of hard-invalid cells receiving SUPPRESS or FAIL_CLOSED and `n_inv` is the number of construction-labeled INVALID cells. Both are counts of cells and `p_det` is dimensionless. False suppression is

`p_fs = (x_soft + x_hard) / n_valid`,

where the numerator counts DOWNGRADE and SUPPRESS decisions on valid cells. For example, 3 suppressions among 40 valid cells gives 0.075. Wilson 95% intervals accompany proportions; denominators are always reported.

CRN performance uses

`R = Var(A_i - B_i) / Var(A_i - B_(i+1))`,

where `i` indexes seed-condition pairs and the denominator uses the frozen cyclic derangement. Outcomes retain their native units (chips or mean absolute magnetization), variance uses squared outcome units, and R is dimensionless. In the toy fixture A=(4,3,2) and B=(1,1.5,1), paired differences are (3,1.5,1) while deranged differences are (2.5,2,1). R below one indicates measured precision benefit, not coupling validity.

The planned M4-M6 procedures required known-zero A/A banks and stored repeated outcomes. Those rows do not exist. We do not reinterpret centered empirical resampling as confirmatory calibration. The post-freeze diagnostic uses B=2,000 bootstrap replicates and is visually segregated from confirmatory results.

### 8. Detection and false-suppression results

The raw-integrity audit passed for 35014 total rows (SHA-256 `ead6dd392c61767c914f9bb1956b7a82213c5889f3e95faf15c4a3f3ec5d2540`). An independently written script reproduced all Branch-B headline counts without importing the production analyzer.

For Branch B, B7 and B5 each detected 100.0% of 160 hard-invalid cells. Their valid-case behavior differed: B7 produced 37.5% false suppression among 320 valid cells, whereas B5 produced 0.0%. The result does not establish equivalence; it shows observed strategy behavior on the frozen bank.

Across branches, B7 hard-invalid detection was 89.4%, but Branch-C detection was only 48.8%, below the predeclared 95% criterion. Pooled false suppression was 14.6%, above the 10% limit. In particular, the implementation downgraded valid Branch-B cases when synchronization evidence was absent even though the conceptual framework allows design-based paired inference without replay or event alignment. This is a reference-implementation failure, not evidence against design-based pairing.

[[FIGURE:figure3_detection_false_suppression.png|Figure 3. Detection and false-suppression tradeoffs by system, pooling the designed claim cells.]]

### 9. Calibration, coverage, power, and variance results

Confirmatory coverage, Type-I error, and power are **not estimable as frozen**. The runner omitted hold'em same-policy mirror pairs, Ising equal-temperature pairs, construction-fixed effects, and the repeated S8 outcomes required by the analysis plan. N=80 subsampling without replacement is also impossible from a retained bank of 40. Acquiring replacements after inspecting decision outcomes would create a new campaign and is not done here.

The centered bootstrap diagnostic is retained only to expose what the code computed and to support future test design. It is not evidence that the frozen uncertainty procedures are calibrated.

[[FIGURE:figure4_statistical_diagnostics_not_confirmatory.png|Figure 4. Centered empirical bootstrap diagnostics. These panels are explicitly non-confirmatory because the promised known-truth banks were absent.]]

Variance-ratio results were heterogeneous. In S0, R was 1.153 for hold'em and 0.858 for Ising; both uncertainty intervals included one. Six of eight point estimates across S0, S3, S4, and S8 were below one, but no nondegenerate interval excluded one. Hold'em S3 had exactly zero paired-difference variance because the event-keyed adapter used the same keyed action rule in both arms, eliminating the intended policy contrast. That degenerate result is a benchmark implementation warning, not compelling CRN evidence.

[[FIGURE:figure5_variance_reduction.png|Figure 5. Paired-to-cross-seed variance ratios. Marginals are preserved by re-pairing the same outcome bank.]]

### 10. Runtime and storage tradeoffs

Median stored pair runtime was 0.0064 seconds for hold'em and 1.164 seconds for Ising. Median stored bytes per pair were 1,694 and 29,009, respectively. An analysis-stage 50-run microbenchmark estimated draw-logging overhead of 32.9% in hold'em and 92.2% in Ising.

The raw schema did not retain per-method timers or complete per-method evidence-bundle sizes. Consequently, M9 is not estimable by method and M10 is limited to system artifact bytes. These omissions prevent the planned joint dominance comparison on detection, false suppression, and runtime.

[[FIGURE:figure6_runtime_storage_cost.png|Figure 6. Observed acquisition time, stored bytes, and trace-logging microbenchmark overhead.]]

### 11. Cross-system results

The predeclared M1-M2 ordering score had Kendall tau-b 0.81 across the two systems. This score is an ordering device, not a probability or utility. The apparent agreement masks an important magnitude difference: B7 detected 99.1% of hard-invalid cells with 0.0% false suppression in hold'em, versus 79.7% detection and 29.1% false suppression in Ising.

Inspection of the executable wrapper explains part of that difference. The Ising path does not implement the intended S4/S8 clock-bounded residual randomness; it reuses clean mechanics while the frozen ground-truth table labels replay invalid. The observed Branch-C misses therefore audit the benchmark wrapper as much as the framework. Cross-domain exercise succeeded in revealing a portability failure, but it does not establish general cross-domain effectiveness.

[[FIGURE:figure7_cross_system_summary.png|Figure 7. Cross-system method ordering. Lines reveal both rank agreement and magnitude differences.]]

### 12. Restricted historical case

The earlier Pokémon engine study remains a motivating historical example, not primary cross-domain evidence. A fixed timed-search battery found 99/200 seed-condition clusters disagreeing on a declared trace projection. A retrospective repeated-control audit found 210/2,800 outcome-record disagreements and 458/2,800 available-record disagreements and suppressed that historical comparison.

Restricted assets cannot be redistributed; semantic event identifiers and factorial candidate traces were unavailable; the taxonomy was developed after acquisition; and historical suppression was retrospective. These results are never pooled with the prospective open-system benchmark and do not validate the full framework.

[[FIGURE:figure8_historical_case.png|Figure 8. Historical disagreement rates shown only as motivating evidence. Different denominators and projections prohibit pooling.]]

### 13. Discussion

The central conceptual correction survives: exact replay is not a universal prerequisite for paired inference. B5's Branch-B performance demonstrates the practical value of modeling the analysis unit and design without imposing event alignment. At the same time, the full implementation shows how a framework can contradict its own conceptual branch independence by importing coupling evidence into a design-based decision.

Three lessons follow. First, validation must be claim-specific. Second, the validator is itself an empirical object requiring planted-fault tests, false-suppression accounting, and cross-system exercise. Third, prospective freezing is useful because it makes an unfavorable result difficult to rationalize away. The freeze did not make the study correct; it made the incompleteness visible.

The appropriate next study is a new, independently frozen campaign. It should repair the Ising S4/S8 mechanics, retain every promised A/A and repeated-measure row, pretest the analysis output contract, time each method, and separate conceptual framework evaluation from reference-implementation evaluation.

### 14. Limitations

The benchmark covers two systems and eleven designed scenarios, not the prevalence of failures in deployed systems. One scientific wrapper failed to instantiate two intended mechanics. The event-keyed hold'em adapter collapsed policy divergence in S3. M4-M6, method-level M9, and full M10 are missing as frozen. The two-proportion contrasts treat matched cells as independent even though the frozen plan specified that test; those p-values are secondary and must be interpreted cautiously. The cyclic variance comparison reuses the same marginal bank, so the delta-method independence assumption is approximate; a split-half sensitivity is supplied.

The novelty audit relies on current public metadata and may change. License verification supports redistribution of the study-authored wrappers, not blanket relicensing of dependencies. The historical case is restricted and retrospective. No independent human scientific review, author comprehension sign-off, or public registration exists at this handoff.

### 15. Conclusion

A shared seed supports only the claim whose assumptions and evidence are actually established. The five-branch formulation is clearer than a cumulative ladder, and the prospective benchmark exposes meaningful differences among simple strategies. Yet the full reference framework failed its own detection and false-suppression gate, and the retained schema cannot support the planned confirmatory statistical validation. The empirical conclusion is therefore narrow: claim-specific validation remains feasible and potentially useful, but this implementation and campaign are not ready to support a full empirical methods paper.

**Go/no-go: NOT_READY_DO_NOT_SUBMIT.**

### 16. Data and software availability

The local release package contains the open-system wrappers, failure injectors, raw prospective JSONL, aggregates, analysis scripts, protocols, manifests, tests, figure/table sources, environment specification, notices, system cards, data card, reproducibility guide, and SHA-256 manifest. Restricted legacy assets are excluded. No archive or DOI has been uploaded; deposit requires human approval.

### 17. AI disclosure

ChatGPT/Codex assisted with experiment engineering, analysis repair, diagnostic code, figures, manuscript drafting, release assembly, and hostile audit. Exact deployed model snapshots were not exposed. AI output was treated as untrusted work product: raw rows, code-derived aggregates, independent reaggregation, equation fixtures, render checks, and human-review gates remain the evidentiary controls. AI is not an author, and AI output is not evidence. The detailed task/file/verification record appears in `AI_USE_LOG.csv`.

### 18. Author contributions

Human author(s), pending confirmation: conceptual direction, domain accountability, approval of scientific claims, restricted-material governance, authorship, and final submission decision. AI-assisted engineering: code scaffolding, deterministic aggregation, draft prose, formatting, and audit prompts under human direction. Final CRediT roles must be assigned and approved by the human author before any submission.

### 19. References

1. Sharma, U. (2025). *When Does Pairing Seeds Reduce Variance? Evidence from a Multi-Agent Economic Simulation*. arXiv:2512.24145v3. https://arxiv.org/abs/2512.24145

2. Buffalo, V., Pearson, C. A. B., & Klein, D. (2026). *Realizing Common Random Numbers: Event-Keyed Hashing for Causally Valid Stochastic Models*. arXiv:2603.11084. https://arxiv.org/abs/2603.11084

3. Masters, C., Liu, Z., & Albrecht, S. V. (2026). *Rollout Cards: A Reproducibility Standard for Agent Research*. arXiv:2605.12131. https://arxiv.org/abs/2605.12131

4. Girshovitz, I., Zeltzer, D., & Gilad-Bachrach, R. (2026). *Automated Synthesis and Adversarial Validation of Executable Causal Research Pipelines*. arXiv:2607.21173. https://arxiv.org/abs/2607.21173

5. Mudasiru, R. (2026). *Deterministic Replay for AI Agent Systems*. arXiv:2607.16200. https://arxiv.org/abs/2607.16200

6. Glasserman, P., & Yao, D. D. (1992). Some Guidelines and Guarantees for Common Random Numbers. *Management Science, 38*(6), 884-908. https://doi.org/10.1287/mnsc.38.6.884

7. L'Ecuyer, P., Simard, R., Chen, E. J., & Kelton, W. D. (2002). An Object-Oriented Random-Number Package with Many Long Streams and Substreams. *Operations Research, 50*(6), 1073-1075. https://doi.org/10.1287/opre.50.6.1073.358

8. Patterson, A., Neumann, S., White, M., & White, A. (2024). Empirical Design in Reinforcement Learning. *Journal of Machine Learning Research, 25*(318), 1-63.

9. Agarwal, R., Schwarzer, M., Castro, P. S., Courville, A., & Bellemare, M. G. (2021). Deep Reinforcement Learning at the Edge of the Statistical Precipice. *NeurIPS 34*, 29304-29320.

10. Field, C. A., & Welsh, A. H. (2007). Bootstrapping Clustered Data. *JRSS B, 69*(3), 369-390. https://doi.org/10.1111/j.1467-9868.2007.00593.x

11. Sargent, R. G. (2013). Verification and Validation of Simulation Models. *Journal of Simulation, 7*(1), 12-24. https://doi.org/10.1057/jos.2012.20

12. Zha, D. et al. (2019). RLCard: A Toolkit for Reinforcement Learning in Card Games. arXiv:1910.04376. https://arxiv.org/abs/1910.04376
