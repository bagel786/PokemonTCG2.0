# Primary-source novelty audit

Audit date: 2026-08-24  
Decision: **PASS, narrowly, for the audited manuscript boundary**  
Submission effect: novelty is not the present fatal blocker; unresolved rights and public-release authorization are.

## Method and fail-closed rule

The search covered exact and fragment title queries, all four specified 2026 neighbors by title and identifier, forward/citing queries, and semantic searches across common random numbers (CRN), paired-seed evaluation, event-keyed and counter-based randomness, trace replay, A/A diagnostics, metamorphic testing, simulation verification and validation, empirical reinforcement-learning design, agent-evaluation stochasticity, and time/work budgeting. Only publisher, proceedings, arXiv, OpenReview, and official APS records were admitted. Search details and dated negative results are in `NOVELTY_SEARCH_LOG.json`; the source-by-source comparison is in `NOVELTY_MATRIX.csv`.

An unresolved work cannot support novelty, metadata, or manuscript wording. No unresolved record is retained in `references.bib` or `REFERENCE_AUDIT.csv`. A dated negative search is not evidence that no later or unindexed work exists.

The fatal test was whether one work, or a straightforward combination of two works, already supplies all of the following as an operational method:

1. observable boundary-seed and artifact identity;
2. complete declared-trace A/A or identical-arm repetition across execution contexts;
3. an explicit separation of within-arm repeatability from cross-arm semantic event alignment;
4. a result-independent statistical claim-admission rule;
5. automatic downgrade or suppression after a required pairing gate fails;
6. controlled synthetic coupling failure modes and repair;
7. an empirical black-box stochastic-agent case in which an attractive comparison is actually withheld when unsupported.

No single source passes that test. The strongest pair, Buffalo--Pearson--Klein plus Paduraru--Bouruc--Stefanescu, supplies a white-box event-keyed coupling model and a general trace-contract/fault-injection framework, but still does not supply boundary-seed auditing, identical-arm complete-projection checks across process/worker/enqueue contexts, a statistical admission map with automatic paired-claim suppression, or the empirical restricted-engine demonstration. The other five pairs among the four specified 2026 works omit at least those admission and coupling-validation elements. Combining Sharma's paired-seed analysis with any one trace paper still assumes or records the coupling rather than validating the entire fail-closed chain. **Fatal novelty test: PASS.**

## Closest three works

1. **Buffalo, Pearson, and Klein (2026), _Realizing Common Random Numbers: Event-Keyed Hashing for Causally Valid Stochastic Models_.** This is the closest source for the cross-arm problem and repair. It formalizes execution-invariance failure under stateful draws and proposes event-keyed counter-based randomness. The manuscript must not claim the draw-shift problem, stable event keys, or event-keyed repair as new. Its remaining difference is that it is a white-box construction requiring a declared event ontology; it does not provide the present black-box audit and statistical-admission workflow. Primary record: <https://arxiv.org/abs/2603.11084>.

2. **Sharma (2025, revised 2026), _When Does Pairing Seeds Reduce Variance? Evidence from a Multi-Agent Economic Simulation_.** This is the closest source for paired-seed statistical design. It analyzes conditional precision gains from paired seeds in a multi-agent simulation, taking the seed as the coupling unit. The manuscript must not present paired-seed analysis or the conditional covariance argument as new, and should not repeat the stronger assumption that the same seed automatically determines a matched stochastic realization in a black-box system. Primary record: <https://arxiv.org/abs/2512.24145>.

3. **Paduraru, Bouruc, and Stefanescu (2026), _A Trace-Based Assurance Framework for Agentic AI Orchestration: Contracts, Testing, and Governance_.** This is the closest trace-framework and title neighbor. It defines Message-Action Traces, contracts, replay, perturbation search, fault injection, and runtime governance. It does not validate CRN coupling or map pairing evidence to statistical claim classes, and its paper states that a full empirical study is future work. Publisher record: <https://doi.org/10.5220/0014840300004015>; author version: <https://arxiv.org/abs/2603.18096>.

## Exact remaining contribution boundary

The component ideas are prior art: conditional CRN theory; stream/substream organization; paired-seed variance analysis; event-keyed and counter-based random numbers; trace preservation and replay; trace contracts; A/A controls; metamorphic testing; simulation V&V; time/work budgeting; and artifact/reporting cards.

The defensible contribution is their **operational integration into a fail-closed black-box statistical-admission protocol**. In particular, the package binds artifacts and observable boundary seeds, verifies full schedules, checks the complete declared trace projection under identical-arm repetition and multiple execution contexts, distinguishes within-arm repeatability from cross-arm semantic alignment, audits bounded stochastic sources, freezes evidence-to-claim rules before outcomes, automatically downgrades or suppresses unsupported paired wording, exercises controlled coupling failures and an event-keyed repair in a synthetic suite, and applies the rule to a restricted simulator.

Two sentences suitable for the contribution boundary are:

> Prior work separately establishes conditional CRN theory, streams and substreams, paired-seed precision analysis, event-keyed white-box repair, trace-contract assurance, and preserved rollout records. This protocol's remaining contribution is an executable black-box admission workflow that combines observable boundary-seed identity, complete declared-trace A/A across execution contexts, an explicit within-arm/cross-arm distinction, a prospectively frozen claim map with automatic suppression, controlled coupling failures, and a restricted-engine case study.

Do not use “first,” “novel event-keyed,” “proves pairing,” “guarantees valid CRN,” or a claim that an A/A pass establishes cross-arm alignment. The restricted engine cannot establish semantic event alignment because it exposes neither stable semantic event identifiers nor event-keyed streams.

## Four specified 2026 close-work audits

### 1. Rollout Cards: A Reproducibility Standard for Agent Research

Primary record: <https://arxiv.org/abs/2605.12131> (arXiv:2605.12131 v1; arXiv-issued DOI 10.48550/arXiv.2605.12131).

1. **Problem:** Agent papers report scores while omitting inspectable rollout evidence and the views, reporting rules, failures, skips, and drops that produced the scores.
2. **Unit of evidence:** A preserved rollout record bundled with declared views, reporting rules, and a drops manifest; the audit also examines repositories and fixed-evidence regrading.
3. **Traces, pairing, or both:** It preserves rollout evidence, including trace-bearing exports in some settings. It does not validate a same-seed stochastic pairing.
4. **Within-arm versus cross-arm:** No. It does not separate identical-arm execution repeatability from cross-arm semantic event alignment.
5. **Statistical claim admission:** No. Declared reporting rules improve score provenance, but there is no pairing-evidence-to-estimand/claim-class admission map.
6. **Automatic suppression after a failed gate:** No. Regrading changes reported scores and can invert rankings, but it is not an automatic paired-inference gate.
7. **Black-box stochastic simulators:** It covers agent benchmarks and preserved outputs, not a black-box simulator coupling audit.
8. **Controlled synthetic failure modes:** No coupling conformance suite. Fixed records are regraded under alternative reporting rules, which tests a different failure class.
9. **A real attractive result suppressed:** No in the required sense. It demonstrates score changes and ranking inversions, but does not withhold a favorable paired claim after failed pairing validation.
10. **Remaining contribution here:** Boundary-seed identity, complete declared-trace A/A across execution contexts, semantic event-alignment evidence, a frozen statistical admission map, automatic suppression, controlled pairing failures, and the restricted-engine application.

Fatal test: **not fatal alone or paired with any one other specified close work**; it supplies excellent evidence preservation and reporting provenance, not coupling validity or inferential admission.

### 2. A Trace-Based Assurance Framework for Agentic AI Orchestration: Contracts, Testing, and Governance

Primary records: <https://doi.org/10.5220/0014840300004015> (ENASE 2026, pp. 420--427) and <https://arxiv.org/abs/2603.18096> (author version).

1. **Problem:** Long-horizon LLM orchestration fails through nontermination, role drift, unsupported claims, untrusted context, side effects, and service/retrieval/memory faults that final-output tests miss.
2. **Unit of evidence:** A Message-Action Trace with step/trace contracts, contract verdicts, first-violation localization, perturbation schedules, and governance actions.
3. **Traces, pairing, or both:** It instruments and replays traces and compares stochastic seeds/configurations. It does not establish a CRN pairing or semantic random-event alignment.
4. **Within-arm versus cross-arm:** No explicit distinction corresponding to repeatability versus paired stochastic alignment.
5. **Statistical claim admission:** No. Contract pass/fail and allow/rewrite/block are runtime assurance/governance decisions, not admission of statistical estimands or paired wording.
6. **Automatic suppression after a failed gate:** No paired-inference suppression mechanism.
7. **Black-box stochastic simulators:** It treats stochastic agentic orchestration and external services, but not validation of same-seed coupling in a restricted simulator.
8. **Controlled synthetic failure modes:** Partly. It defines bounded perturbation search and structured fault injection at service, retrieval, and memory boundaries; it does not supply a synthetic coupling conformance suite with draw shifts and event-keyed repair.
9. **A real attractive result suppressed:** No. The framework is methodological, and its conclusion leaves a full empirical study to future work.
10. **Remaining contribution here:** An implemented and empirically exercised black-box pairing audit, including boundary identities, identical-arm full-projection checks across contexts, the within/cross distinction, frozen claim admission, automatic suppression, and controlled coupling-specific failures.

Fatal test: **not fatal**. Even combined with Buffalo's event-keyed construction it omits the end-to-end black-box admission and empirical suppression package.

### 3. AEVAL: From Anecdotal to Deterministic Testing for Agentic Skill Workflows

Primary record: <https://arxiv.org/abs/2607.16345> (arXiv:2607.16345 v2; accepted at the ICML 2026 Workshop on Statistical Frameworks for Uncertainty in Agentic Systems, as reported on the primary record).

1. **Problem:** Skill changes are evaluated by anecdotal demonstrations, allowing silent regressions and self-correction bias.
2. **Unit of evidence:** A skill change triggers an evaluation-contract test case whose executor emits per-run artifacts, transcripts, assertions, and a CI-routable quality signal; the grader scores the first attempt separately.
3. **Traces, pairing, or both:** It preserves execution transcripts/artifacts. It does not validate matched stochastic seeds or cross-arm coupling.
4. **Within-arm versus cross-arm:** No same-seed repeatability/event-alignment distinction.
5. **Statistical claim admission:** No. It generates deterministic CI pass/fail evidence, not a rule admitting an estimand or paired statistical claim.
6. **Automatic suppression after a failed gate:** Adjacent but not equivalent. CI can fail a skill change and first-attempt grading prevents a patched run from receiving a spurious pass, but no failed pairing gate suppresses paired inference.
7. **Black-box stochastic simulators:** No; it targets agentic skill workflows across SDKs, not semantic coupling in a black-box stochastic simulator.
8. **Controlled synthetic failure modes:** It includes deliberately degraded skills and execution/connectivity failures, but not controlled seed conversion, stateful draw-shift, timing/process-state, event-key, and manifest-tamper modes.
9. **A real attractive result suppressed:** Adjacent yes: spurious 100% pass signals become auditable first-attempt failures. No for the mandated test: it does not suppress an attractive scientific paired comparison because coupling evidence failed.
10. **Remaining contribution here:** Pairing-specific black-box evidence, the within/cross distinction, result-independent statistical admission, automatic paired-claim suppression, coupling conformance tests, and the restricted-engine application.

Fatal test: **not fatal**. It is strong prior art for deterministic evidence-grounded testing and fail-closed CI, so the manuscript must limit novelty to the pairing/statistical-admission integration.

### 4. Realizing Common Random Numbers: Event-Keyed Hashing for Causally Valid Stochastic Models

Primary record: <https://arxiv.org/abs/2603.11084> (arXiv:2603.11084 v1; arXiv-issued DOI 10.48550/arXiv.2603.11084).

1. **Problem:** Stateful, draw-indexed pseudorandom streams silently break CRN when interventions alter execution order, so equal seeds no longer identify the same modeled exogenous events.
2. **Unit of evidence:** A modeled stochastic event/exogenous variable with a stable event key and a deterministic counter-based value assignment.
3. **Traces, pairing, or both:** It directly defines a causally valid pairing construction. Trace preservation is not its evidence unit.
4. **Within-arm versus cross-arm:** It explicitly addresses cross-scenario event alignment/execution invariance, but does not stage it against a separate identical-arm complete-trace repeatability gate.
5. **Statistical claim admission:** No evidence-to-estimand/wording admission map.
6. **Automatic suppression after a failed gate:** No automatic suppression of paired inference.
7. **Black-box stochastic simulators:** No. The repair requires white-box control of the event ontology, keys, distributions, and dependence structure.
8. **Controlled synthetic failure modes:** Partly. Its toy infection example demonstrates a stateful draw-shift and event-keyed repair; it is not the present multi-mode executable conformance and tamper suite.
9. **A real attractive result suppressed:** No empirical favorable comparison is withheld by an admission rule.
10. **Remaining contribution here:** A fail-closed black-box audit for systems that cannot install or inspect the ideal event-keyed repair, plus boundary identity, context-stressed identical-arm evidence, explicit claim admission/suppression, a broader coupling failure suite, and an empirical restricted-engine case.

Fatal test: **not fatal**, though it removes any novelty claim for the stateful-draw diagnosis or event-keyed repair.

## Additional semantic and foundational neighbors

- Bjarnason, Silva, and Monperrus, _On Randomness in Agentic Evals_ (<https://arxiv.org/abs/2602.07150>), shows large run-to-run and trajectory variability across 60,000 agent trajectories and recommends repeated runs. It motivates repeatability auditing but does not establish paired coupling.
- Mustahsan et al., _Stochasticity in Agentic Evaluations: Quantifying Inconsistency with Intraclass Correlation_ (<https://arxiv.org/abs/2512.06710>), uses repeated-trial ICC to measure within-query inconsistency. Reliability measurement is not semantic event alignment or claim admission.
- Glasserman and Yao (<https://pubsonline.informs.org/doi/10.1287/mnsc.38.6.884>) and L'Ecuyer et al. (<https://pubsonline.informs.org/doi/10.1287/opre.50.6.1073.358>) establish conditional CRN reasoning and stream/substream organization.
- Salmon et al., _Parallel Random Numbers: As Easy as 1, 2, 3_ (<https://doi.org/10.1145/2063384.2063405>), is foundational counter-based-generator prior art. The manuscript must not imply that counter-based random access is new.
- Bouthillier et al. (<https://proceedings.mlr.press/v97/bouthillier19a.html>), Patterson et al. (<https://jmlr.org/papers/v25/23-0183.html>), Agarwal et al. (<https://proceedings.neurips.cc/paper/2021/hash/f514cec81cb148559cf475e7426eed5e-Abstract.html>), and Pineau et al. (<https://jmlr.org/papers/v22/20-303.html>) establish empirical-design, uncertainty, artifact, and reproducibility context.
- Sargent (<https://doi.org/10.1057/jos.2012.20>), Lin et al. (<https://doi.org/10.1109/MCSE.2018.2880577>), and Raunak and Olsen (<https://doi.org/10.1109/MET52542.2021.00015>) establish simulation V&V and metamorphic-testing context.
- Kohavi and Longbotham's official SIGKDD article (<https://www.kdd.org/exploration_files/v12-02-8-UR-Kohavi.pdf>) establishes A/A diagnostics; Baier and Winands (<https://doi.org/10.1109/TCIAIG.2015.2443123>) establish MCTS time/work budgeting as an algorithmic concern.

## Manuscript checks and remaining condition

1. **PASS:** The current manuscript cites and contrasts all four specified 2026 close works: Rollout Cards, Trace Assurance, AEVAL, and Event-Keyed CRN.
2. **PASS:** The introduction states a distinct two-sentence integration boundary without a priority claim.
3. **PASS:** Sharma is qualified: the source uses the seed as the pairing unit, while this protocol tests what a restricted implementation must show before inheriting that assumption.
4. **PASS:** The manuscript assigns the stateful draw-shift diagnosis and event-keyed white-box repair to Buffalo, Pearson, and Klein.
5. **PASS:** The manuscript cites current agent-stochasticity neighbors and says run-to-run variation is not an unoccupied topic.
6. **PASS:** The real case study's semantic-alignment claim remains explicitly unsupported; within-arm evidence is not promoted to cross-arm alignment.
7. **CONDITIONAL:** Automatic suppression and the claim map must remain executable and prospective in the rebuilt review package. If they become narrative, outcome-contingent, or absent from the independently runnable artifact, the remaining novelty boundary materially weakens.

Current novelty score: **4/5**. This is a novelty finding, not submission clearance; rights and final artifact verification remain separate hard gates.
