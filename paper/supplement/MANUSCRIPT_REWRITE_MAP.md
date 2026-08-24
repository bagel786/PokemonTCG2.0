# Manuscript rewrite map: methods-led APS Open Science Regular Article

## Locked editorial decisions

**Title:** *A Validity Ladder for Seed-Matched Evaluation of Game-Playing Agents*

**Article type:** APS Open Science Regular Article. The paper introduces and evaluates a method; it is not yet an established protocol supported across enough independent domains to be framed as a Protocol Article.

**Central contribution:**

> We propose an operational, fail-closed validity ladder for paired evaluation of black-box game-playing agents. The ladder separates artifact and schedule matching, within-arm execution reproducibility, and cross-arm event alignment; it prespecifies which paired claims are admitted or suppressed when each class of evidence passes or fails.

The representation-binding intervention is the treatment used in the restricted-engine case study. It is not the title-level contribution. The paper must not claim that it discovered that same-seed evaluation can fail, that seed pairing is generally invalid, or that identical-control parity proves event-level coupling. Classical CRN conditions, stream-based synchronization, recent paired-seed analysis, and recent event-keyed-randomness work already delimit those claims.

The narrative should follow one sequence:

1. Seed pairing can be useful, but a shared seed is only one piece of evidence.
2. PEVL separates eight increasingly demanding validation/admission levels.
3. A fully open synthetic testbed shows which levels detect five known modes.
4. A restricted game-agent pipeline supplies a real black-box case: an apparently favorable comparison coexisted with a failed repeated-control gate.
5. A prospectively frozen trace/stress protocol tests the revised workflow.
6. The factorial is reported only if all required gates pass; otherwise its suppression is itself the planned result.

Use `seed-matched` for the restricted-engine comparisons. Reserve `event-aligned`, `counterfactual`, and full-CRN wording for evidence satisfying Level 7. The restricted engine cannot expose the event identifiers or event-specific streams needed for Level 7, so no restricted-engine result may receive that interpretation.

Target 6,500--7,500 words in the abstract and main text combined, excluding references, acknowledgments, Data Availability, and appendices. Write for computational scientists outside game AI: define game-specific details only to the degree needed to understand the validity problem.

## New title and section structure

### Abstract (180--230 words; replace completely)

Use five moves, in this order:

1. **Problem:** paired seeds may increase precision, but schedule matching, repeatable execution, and event-aligned stochastic coupling are distinct.
2. **Method:** introduce the eight-level PEVL and its fail-closed claim-admission rule.
3. **Open validation:** state that five synthetic modes test clean execution, stateful draw shift, wall-clock search, process-global state, and 32-bit seed conversion; name the first catching level or level set for each.
4. **Restricted case:** report the historical repeated-control failure (210/2,800 outcome-record mismatches and 458/2,800 serialized-record mismatches, confined to two timed-search opponents) and then insert the prospective trace/stress result. Mention the historical `+2.786 pp` result only as an initially favorable, one-execution estimate whose mechanistic decomposition was suppressed.
5. **Admission outcome:** if the new factorial passes, report its prespecified primary `C4-C1` estimate and bounded five-opponent target population; if any gate fails, state that the factorial was suppressed. End with the black-box validation contribution, not agent strength.

Do not carry over the current abstract's detailed training, offline approval, opponent-family, temporal, or oracle results.

### I. Introduction: from matched seeds to valid comparisons (700--900 words)

Paragraph 1 should explain why paired stochastic evaluations are attractive. Cite classical CRN conditions and stream/substream synchronization after describing the intended efficiency gain: `glasserman1992crn,lecuyer2002streams`. Cite the current paired-seed preprint, explicitly as a preprint, after stating that favorable seed-level correlation can improve precision: `sharma2025pairedseeds`.

Paragraph 2 should define the gap. A matched schedule does not establish execution repeatability, and within-arm repeatability does not establish semantic event alignment after policies branch. Cite the stateful-PRNG/event-keyed preprint at the event-alignment sentence: `buffalo2026eventkeyed`.

Paragraph 3 should connect the problem to empirical machine-learning practice: deterministic reproduction of bytes or one result is not the same as reproducible findings, and comparison design must account for essential variation. Cite `bouthillier2019reproducible,patterson2024empirical`; use `agarwal2021statistical,pineau2021reproducibility` for uncertainty and transparent artifact reporting.

Paragraph 4 should identify the black-box setting: restricted simulator, third-party opponent packages, wall-clock search, process-local state, and no authority to replace the RNG implementation. State that a white-box remedy may be unavailable, so an operational admission system is needed.

Paragraph 5 should give four contributions:

1. the eight-level PEVL and its claim-admission vocabulary;
2. an open synthetic counterexample/remediation suite;
3. a real retrospective failure in which a seemingly matched game-agent design failed identical-control parity;
4. a prospectively frozen trace/stress evaluation and conditional factorial demonstration.

Do not lead with imperfect-information poker, imitation agreement, or the representation repair. DeepStack and Pluribus can appear once in the case-study background, not as the paper's motivating frame.

### II. Paired Evaluation Validity Ladder (900--1,100 words)

Open with the displayed distinction:

> same schedule ≠ reproducible executions ≠ event-aligned coupling.

Introduce Table I, a compressed version of `PEVL_FRAMEWORK.md` with four columns: level, required evidence, strongest admitted claim, and fail-closed action.

Define all eight levels in order:

1. artifact identity;
2. seed-namespace integrity;
3. schedule parity;
4. identical-arm record parity;
5. repeat and worker parity;
6. stochastic-source audit;
7. cross-arm event alignment;
8. statistical admission.

Make three qualifications explicit:

- a pass is scoped to the tested artifacts, seeds, fields, trajectories, and execution contexts;
- parity strength must be named (outcome, error, decision count, actions, public states, or full public-state/action digest);
- Level 8 applies the frozen claim rule to the evidence achieved and cannot repair a missing lower-level guarantee.

Cite `glasserman1992crn` after the CRN structural/timing boundary, `lecuyer2002streams` after the stream/substream remedy, and `buffalo2026eventkeyed` after the Level-7 event-keyed remedy. Cite `sharma2025pairedseeds` in the paragraph explaining that PEVL validates pairing rather than rejecting it.

End with the exact admission vocabulary used later:

- Levels 1--3: `schedule matched` only;
- Levels 1--6 plus a frozen Level-8 rule: bounded `seed-matched` comparison;
- Levels 1--7 plus Level 8: event-aligned CRN/counterfactual language for the validated event set;
- failed required parity: suppress the affected contrast or redesign prospectively.

### III. Methods (1,500--1,900 words)

#### A. Open synthetic validation suite

Describe the standard-library-only testbed and its deterministic fixtures. Use the checked-in `paper/synthetic/results/pevl_results.json` and `pevl_matrix.csv` as the evidence source.

The five modes are:

- clean deterministic: all eight levels pass;
- stateful draw shift: Levels 4--6 pass but Level 7 detects four misaligned shared events out of five; event-keyed SHA-256 randomness restores alignment for the shared event keys;
- wall-clock search: injected clock profiles produce Level-4--6 failures;
- process-global state: an injected reused-worker counter produces Level-4--6 failures;
- unsigned-32-bit seed conversion: Level 2 detects two requested seeds that narrow to one engine seed.

State that the clock and process state are injected so published output is byte-reproducible. The suite is a counterexample/test harness, not evidence that any external simulator contains those defects. Cite `buffalo2026eventkeyed` when explaining the draw-shift mechanism and white-box remediation.

#### B. Restricted-engine case study and treatment

Condense the current “Environment,” “Formal problem,” “Representation defect,” and training sections to the minimum needed to define C1--C4.

- The simulator is a two-player, partially observable game with variable legal-action sets and restricted third-party components.
- C1 is blind encoder/original weights; C2 is identity encoder/original weights; C3 is blind encoder/trained output modules; C4 is identity encoder/trained output modules.
- The action repair binds an ordinary PLAY option's observed hand index to its source-card type/ID. It does not reveal hidden information or a unique physical-card serial.
- The retained corpus establishes 37,199/37,199 missing source coordinates and 9,776 multi-identity states, but zero exact within-state full-input collisions. This distinction must remain explicit.
- Training used one seed, winner/top-episode rows, a frozen trunk, four output-side modules, and a KL anchor; batch rounding produced zero rehearsal rows.

Cite `vinyals2015pointer,chandak2019actionrepresentations` after explaining explicit option-to-item identity. Cite `zaheer2017deepsets,huang2022invalidmasking` only for variable sets and legal-action masking, with a sentence saying those mechanisms do not establish this binding. Cite `moravcik2017deepstack,brown2019pluribus` in one broad game-AI context sentence. Move `ross2011dagger,laroche2019spibb` to the appendix training/offline-diagnostic discussion.

Do not describe C2 as a deployable policy; unchanged weights had not been trained to use the new coordinate. Do not describe C3/C4 differences as causal until the new factorial passes every gate.

#### C. Retrospective PEVL audit

Describe the historical evidence without presenting it as a prospective test of the new framework.

- Level 1: package and engine hashes were retained, with disclosed stale metadata conflicts.
- Level 2: all 2,800 recorded requested seeds were outside unsigned-32-bit range and changed at the engine boundary; retrospective conversion yielded 2,800 unique engine seeds with no collisions. Historical rows mislabeled the requested integer as `seed` and did not record the exact consumed value separately.
- Level 3: candidate/control schedules matched opponent, actual order, seat, and requested seed.
- Level 4: separately executed C1 controls disagreed on 210/2,800 outcome records and 458/2,800 fuller serialized records.
- Level 6: source inspection found monotonic-clock search deadlines in Starmie and Dipplin, separate process-pool tasks, and process-local native state. Cite `baier2016timemanagement` only to establish that time management is algorithmically meaningful in MCTS, not to prove it was the sole cause.
- Level 7: unavailable because the restricted engine exposes no semantic random-event identifiers.
- Level 8: the planned seven-opponent factorial was suppressed.

The earlier C4--C1 estimate (`+2.786 pp`, conditional interval `[+0.679,+4.929]`) is retained as a historical one-execution observation that motivates fail-closed admission. It must not be called the paper's primary result, a repeatable effect, or a representation/training decomposition.

#### D. Prospective validation and conditional factorial

Follow `PEVL_PROSPECTIVE_PROTOCOL.md` exactly and state that it was frozen before result access.

1. **Trace preflight:** five determinism-eligible opponents, C1--C4, two orders, 25 seeds/order, and three execution profiles (two fresh serial executions and one eight-worker execution): 1,000 arm/seed-condition trajectories and 3,000 games. Every within-arm public-state/action digest, terminal record, error count, and decision count must match. Any mismatch suppresses the factorial before acquisition.
2. **Timed-search stress test:** C1 against Starmie and Dipplin, two orders, 50 seeds/order, and four execution profiles (one/four workers crossed with forward/reverse enqueue): 200 seed-condition clusters and 800 games. Primary endpoint is complete trace-digest agreement; secondary endpoints are first divergence, actor, decision count, outcome, errors, and timing.
3. **Five-opponent factorial:** only after a full preflight pass. For each of C2, C3, and C4, run a separately executed C1 comparison over five opponents, two orders, and 200 pairs/stratum: 2,000 common units per cell and 12,000 games total. Repeated C1 outcome/draw/error/decision records must match across all three files. One mismatch suppresses all contrasts.

Report exact scheduled and unsigned-32-bit engine seeds, schedule and run fingerprints, hashes, environment, decision cap, process start method, worker count, enqueue position, run UUID, trace digest, outcome, errors, decisions, and elapsed wall time as specified by the protocol.

#### E. Estimands and statistical admission

For the stress test, the reused seed-condition containing four executions is the resampling cluster; use the frozen 100,000-draw cluster bootstrap and seed `2026083118`. Cite `field2007clustered` for general cluster-resampling context, while defining the study-specific cluster directly.

For an admitted factorial, average the ten opponent-by-order strata equally. The primary contrast is `C4-C1`. Secondary contrasts are the representation main effect, training main effect, and interaction exactly as defined in the frozen protocol. Use 100,000 paired within-stratum resamples with seed `2026083117`; retain exact McNemar inference as secondary for the primary binary contrast. Cite `patterson2024empirical,agarwal2021statistical` after the paragraph on estimands, variation, and estimation-first reporting.

State before results that statistical significance cannot repair a failed PEVL gate and no opponent, row, or seed may be removed after result inspection.

### IV. Results (1,500--1,900 words)

#### A. Synthetic failure-mode detection

Report the generated matrix exactly:

- clean mode: no failure, event-aligned pairing admitted;
- seed collision: first caught at Level 2;
- wall-clock and process-state modes: caught at Levels 4--6, affected paired contrast suppressed;
- draw shift: within-arm repeats pass Levels 4--6, Level 7 catches four of five shifted shared events, and the event-keyed remedy restores all shared-event values.

The central result is that no single lower-level check detects every mode. In particular, identical-arm trace parity cannot detect cross-arm draw shifts, and exact identical-arm repetition cannot detect seed-namespace collisions by itself.

#### B. Retrospective restricted-engine audit

Report the historical audit in PEVL order rather than project chronology.

The required main values are:

- historical seed conversion: 2,800/2,800 requested seeds changed under unsigned-32-bit narrowing; 2,800 unique consumed values; zero collision groups;
- all opponents: 210/2,800 outcome-record mismatch units (7.5%) and 458/2,800 serialized-record mismatch units (16.36%);
- Starmie: 191/400 outcome mismatches (47.75%) and 377/400 serialized mismatches (94.25%);
- Dipplin: 19/400 outcome mismatches (4.75%) and 81/400 serialized mismatches (20.25%);
- each of the other five packages: zero available outcome/serialized mismatches;
- historical trace capture: absent, so trace parity is not retroactively claimed.

Present the attractive historical C4--C1 estimate before the invalidation only to demonstrate why a fail-closed rule matters. Then state that the 210-unit repeated-control failure suppresses all historical cross-cell mechanistic contrasts. The post hoc five-opponent effects remain appendix-only and receive no interval or test.

#### C. Prospective trace and timed-search results

Populate this subsection only from frozen outputs. Report:

- pass/fail counts for every C1--C4 arm and five-opponent preflight stratum;
- mismatch rate and clustered interval for each timed-search opponent/order;
- trace disagreement as primary, even when terminal outcomes agree;
- first-divergence position and actor distributions;
- serial-repeat, worker-count, and enqueue-order diagnostics without interpreting them as randomized hardware effects;
- the highest PEVL level reached and exact Level-8 admission decision.

Use bounded causal wording. A divergence concentrated under worker contention and an implementation with monotonic deadlines is “consistent with” or “associated with” timing sensitivity unless a controlled intervention isolates the clock as the unique cause.

#### D. Gated factorial result

This subsection has three mutually exclusive publication branches:

1. **Preflight failure:** state that the factorial was not acquired and why. Do not show an empty effect table.
2. **Acquisition/repeated-C1 failure:** report the invalidating record and suppress every factorial effect. Effects may not appear even descriptively in the main text.
3. **Full pass:** report `C4-C1` first with its stratified interval, then the representation and training main effects and interaction with intervals. Limit inference to the five frozen determinism-eligible opponents and exact execution configuration. State that Level 7 remains unavailable even after a complete pass.

No manuscript build may silently substitute zeros or “TBD” for pending prospective outputs. The results generator should fail until one of these branches is explicitly selected by the machine-readable admission file.

### V. Discussion: what the ladder changes (800--1,000 words)

Organize the discussion around implications, not the development story.

1. **Pairing is conditional, not rejected.** Pairing can improve precision when correlation is favorable (`sharma2025pairedseeds`), but its implementation assumptions require evidence.
2. **Black-box validation complements white-box remedies.** Event-keyed or event-specific randomness is stronger when the simulator is modifiable (`buffalo2026eventkeyed,lecuyer2002streams`); PEVL controls what may be claimed when it is not.
3. **Control parity is one rung.** Passing identical-arm tests scopes reproducibility on tested trajectories; it does not prove cross-arm semantic alignment.
4. **Fail-closed reporting has scientific value.** The historical gate rejected an attractive decomposition instead of selecting agreeing rows or a favorable post hoc population.
5. **Case-study interpretation.** The option--item repair is factually grounded and behaviorally consequential at the model-output level, but its gameplay effect can be decomposed only if the prospective factorial passes.
6. **Open-science use.** The synthetic suite, processed audit rows, protocols, hashes, and analysis code allow independent inspection even though restricted engine materials cannot be redistributed. Cite `pineau2021reproducibility,gebru2021datasheets` here or in Data Availability.

### VI. Limitations (450--650 words)

Retain and reorganize these limitations:

- PEVL is evaluated in one open synthetic suite and one restricted game domain; it is not yet a universal standard.
- Synthetic clocks and process state are injected deterministic fixtures, not measurements of live operating-system behavior.
- The restricted engine cannot satisfy Level 7, so even passing game results remain seed-matched and implementation-conditional.
- Opponents are fixed engineering populations, not probability samples; the five factorial opponents were prospectively redefined after the historical audit and do not represent the full competition field.
- The historical trace was not captured, and clock timing is source-supported rather than proven to be the sole divergence cause.
- The treatment used one training seed and outcome-selected data; C2 is an untrained-feature probe.
- Engine, opponents, decks, card data, full traces, and possibly policy weights have rights/privacy restrictions.
- Author metadata, release rights/license, and archival DOI remain human-controlled submission blockers.

Move detailed corpus-loss, stale-manifest, historical-aggregate, and unavailable-wave limitations to appendices or the provenance supplement.

### VII. Conclusion (120--180 words)

Conclude with the distinction among schedule matching, reproducible execution, and event alignment. State that PEVL makes paired evaluation fail closed by connecting evidence to allowed claims. Mention the real parity failure and the open synthetic testbed. End with a bounded recommendation: record exact consumed seeds, test identical arms and execution contexts at trace level, audit stochastic sources, and suppress any contrast whose required gate fails.

Do not conclude with agent strength, offline agreement, or the representation repair alone.

## Current-to-new manuscript crosswalk

| Current `main.tex` component | New location and treatment |
|---|---|
| Title and abstract | Replace completely with the framework title and five-move abstract above. |
| Introduction | Reuse only the bounded action-interface and reproducibility ideas. Replace the opening poker/game frame with the paired-evaluation problem. Move poker citations to the case-study subsection. |
| Formal problem setting | Move the policy-scoring equation and variable-action definition to Methods III.B. Replace the current gameplay/replay estimands with the PEVL distinction in Section II; place replay estimands in Appendix C. |
| Environment and frozen baseline | Condense to Methods III.B. Move full hashes, stale-manifest conflicts, and evidence hierarchy to Appendix B/provenance supplement. |
| Representation defect and identity-aware intervention | Condense to Methods III.B. Preserve the missing relational binding versus zero exact-collision distinction. Reuse the schematic as a case-study panel. |
| Replay data and restricted training | Move nearly all material to Appendix B. Main text keeps only four-cell definitions, one-seed/output-module scope, outcome selection, and zero rehearsal. |
| Evaluation protocol and statistical analysis | Split into Methods III.C--E. Historical protocol becomes retrospective audit; new prospective protocol becomes the controlling method. Remove “primary” terminology from the old seven-opponent execution. |
| Primary gameplay results | Rename and demote to Results IV.B as a historical one-execution observation. Detailed opponent/order cells and forest plot move to Appendix C. |
| Invalidated four-cell analysis | Promote the parity evidence—not the post hoc effects—to Results IV.B. Replace the current effect-heavy table with a level-by-level retrospective audit and opponent mismatch table. |
| Refresh-held-out diagnostics | Move to Appendix C under “Offline diagnostics with different estimands.” Retain the state-distribution explanation, but do not use it in the abstract or contribution list. |
| Negative and null experiments | Move to Appendix D or supplement. They demonstrate evidence discipline but are not PEVL validation experiments. |
| Discussion | Rewrite around pairing conditions, black-box versus white-box validation, control-parity scope, fail-closed admission, and open science. |
| Limitations | Retain the relevant engine/opponent/reproducibility/rights paragraphs, reorganized as Section VI. Move historical missing-artifact detail to appendices. |
| Conclusion | Replace with PEVL-level conclusions and bounded recommendations. |
| Existing appendices | Reorganize into Appendix A (formal/statistical details), B (case-study artifacts, representation, corpus, training), C (historical gameplay/offline diagnostics), and D (negative results, exclusions, provenance conflicts). |

## Evidence and visual-asset disposition

### Reusable evidence

| Evidence artifact | Main-text use |
|---|---|
| `paper/supplement/PEVL_FRAMEWORK.md` | Source of exact level definitions and claim vocabulary; compress into Section II and Table I. |
| `paper/protocol/PEVL_PROSPECTIVE_PROTOCOL.md` | Controlling source for all prospective methods, stopping rules, estimands, and reporting branches. |
| `paper/synthetic/results/pevl_results.json` and `pevl_matrix.csv` | Primary evidence for open synthetic results and detection matrix. |
| `paper/data/seed_namespace_audit.json` | Historical Level-2 result and prospective no-collision verification. |
| `paper/data/ablation/summary.json` | Historical Level-4 mismatch counts, by-opponent localization, source audit, and fail-closed decision. |
| `paper/data/statistical_summary.json` | Historical one-execution C4--C1 estimate, conditional interval, and exact scope. |
| `paper/data/representation_audit.json` | Case-study treatment evidence; missing binding, multi-identity prevalence, zero exact within-state collisions, and model-output sensitivity. |
| `paper/claim_ledger.csv` and `PROVENANCE_AUDIT.md` | Claim gating, hash conflicts, unavailable artifacts, and appendix provenance. |

### Existing figures

| Current figure | Disposition |
|---|---|
| `fig01_pipeline` | Retire from the main text. It is policy-centric and visually terminates in “paired outcome and uncertainty,” whereas the new paper must interpose validation/admission gates. It may be retained only in the case-study appendix. |
| `fig02_action_aliasing` | Reuse as the case-study treatment panel, with caption changed to “missing option--item binding” and an explicit zero-collision caveat. Prefer combining it with the historical opponent-parity bars as a two-panel case-study figure. |
| `fig03_dataset_provenance` | Move to Appendix B. It is important provenance but not a main framework result. |
| `fig04_gameplay_forest` | Move to Appendix C and label “historical one-execution schedule-matched effects.” It cannot be the headline efficacy figure. |
| `fig05_gameplay_vs_expert` | Move to Appendix C or supplement. It supports estimand separation but is secondary to PEVL. |
| `fig06_negative_forest` | Move to Appendix D or supplement. |

### Existing tables

| Current table | Disposition |
|---|---|
| `representation.tex` | Appendix B; optionally cite its two most important values in Methods III.B. |
| `ablation.tex` | Appendix C only. Its post hoc effect rows must not appear in the main paper. Replace it in the main text with a parity/audit table. |
| `primary.tex` / `results.tex` | Appendix C as historical one-execution cells. Remove “primary” from caption and labels. |
| `heldout.tex` | Appendix C. |
| `negative.tex` | Appendix D. |

## Required new outputs

The rewrite is not complete until the following generated outputs exist and trace to machine-readable inputs.

### Main figures

1. **Figure 1: PEVL ladder and claim classes.** Eight levels grouped visually into provenance/schedule (1--3), reproducibility/source audit (4--6), event alignment (7), and admission (8). Show the strongest allowed wording at each stopping point.
2. **Figure 2: Synthetic detection matrix and draw-shift remedy.** Heat map of five modes by eight levels, plus a small stateful-versus-event-keyed event alignment panel. Generate from `pevl_matrix.csv` and `pevl_results.json`.
3. **Figure 3: Restricted case study.** Panel A reuses the option--item binding schematic; Panel B plots historical outcome- and serialized-record mismatch rates for all seven opponents. The caption must say traces were not captured historically.
4. **Figure 4: Prospective repeat/worker stress test.** Plot complete trace-disagreement rates with seed-cluster intervals by opponent/order, annotated with first-divergence actor/position summaries. Generate only from frozen prospective results.
5. **Figure 5: Conditional factorial forest.** Create only after full admission. Plot total intervention, representation main effect, training main effect, and interaction with intervals. If suppressed, omit this figure and report the gate failure instead.

### Main tables

1. **Table I: compressed PEVL.** Eight rows: required evidence, strongest admitted claim, fail response.
2. **Table II: retrospective audit.** PEVL level, observed evidence, status, and consequence; include the seven-opponent mismatch breakout without post hoc effects.
3. **Table III: prospective preflight/stress results.** Execution profiles, seed-condition clusters, trace mismatches, outcome mismatches, and admission decision.
4. **Table IV: factorial estimates, conditional.** Primary and secondary contrasts only after full pass; otherwise no effect table.

### Machine-readable and generated manuscript inputs

- `paper/data/pevl/retrospective_audit.json` and `.csv`, deterministically derived from the seed audit, ablation summary, and historical statistical summary;
- `paper/data/pevl/trace_preflight_summary.json` and `.csv`;
- `paper/data/pevl/timed_search_stress_summary.json` and `.csv`;
- `paper/data/pevl/factorial_summary.json` and `.csv`, created only if acquisition occurs and carrying an explicit admitted/suppressed status;
- `paper/data/pevl/claim_admission.json`, the single machine-readable switch selecting the publication branch and highest achieved level;
- `paper/pevl_macros.tex`, containing only verified values and failing generation when the admission branch is unresolved;
- generated LaTeX for the new main tables and PDF/PNG pairs for every new figure;
- new claim-ledger families for PEVL definitions, synthetic modes, historical seed/parity audit, trace preflight, timed stress test, and conditional factorial contrasts.

## Exact citation placement map

| Citation key | Exact manuscript placement and purpose |
|---|---|
| `glasserman1992crn` | Introduction paragraph 1 after classical CRN benefit/conditions; Section II after explaining that structural and event-timing assumptions bound CRN guarantees. |
| `lecuyer2002streams` | Introduction paragraph 1 after stream/substream synchronization; Section II Level 7 as one white-box strategy, without claiming it guarantees semantic alignment automatically. |
| `sharma2025pairedseeds` | Introduction paragraph 1 and Discussion point 1; label as a current arXiv preprint and use only for the possible precision benefit under favorable seed-level correlation. |
| `buffalo2026eventkeyed` | Introduction paragraph 2, Section II Level 7, and synthetic draw-shift Methods; label as an arXiv preprint and use for the stateful draw-shift/event-keyed remedy distinction. |
| `bouthillier2019reproducible` | Introduction paragraph 3 for methods/results/inferential reproducibility and essential sources of variation. |
| `patterson2024empirical` | Introduction paragraph 3 and Methods III.E for empirical RL design, variation, comparison assumptions, and experimenter bias. |
| `agarwal2021statistical` | Introduction paragraph 3 or Methods III.E for uncertainty and aggregate reporting; do not imply it prescribes PEVL or the exact bootstrap. |
| `pineau2021reproducibility` | Introduction paragraph 3 and Discussion/open-science paragraph for transparent code/artifact reporting. |
| `baier2016timemanagement` | Methods III.C Level-6 source audit after describing wall-clock-limited MCTS; it establishes the relevance of time management, not the unique cause of the observed mismatch. |
| `vinyals2015pointer` | Methods III.B after the sentence that explicit pointers bind a choice to an input element. |
| `chandak2019actionrepresentations` | Methods III.B after the sentence on structured representations for large finite action sets. |
| `zaheer2017deepsets` | Methods III.B for variable-size set representation context, immediately followed by the limitation that pooled identity tokens do not establish option--item binding. |
| `huang2022invalidmasking` | Methods III.B after distinguishing legality masking from semantic action features. |
| `moravcik2017deepstack,brown2019pluribus` | One Methods III.B background sentence situating imperfect-information game agents; not in the opening motivation and not as empirical comparators. |
| `ross2011dagger` | Appendix C offline-diagnostic discussion for learner-induced state-distribution shift; state that this study does not implement DAgger. |
| `laroche2019spibb` | Appendix B training discussion for baseline-anchored motivation; state that no SPIBB or safe-improvement guarantee applies. |
| `field2007clustered` | Methods III.E and Appendix A for seed-condition, episode, or root-cluster resampling context; the manuscript must still define its own clusters. |
| `gebru2021datasheets` | Discussion/open-science paragraph or Data Availability for dataset documentation context. |

## Claims to demote, retain, or forbid

### Retain in the main paper

- the PEVL definitions and exact claim-admission rules;
- the five synthetic modes, detection levels, and event-keyed remediation;
- historical seed narrowing, repeated-control mismatch counts, opponent localization, source audit, and factorial suppression;
- the representation defect only as the treatment definition, including zero exact within-state collisions;
- prospective trace/stress results;
- factorial estimates only after full gate passage;
- restricted rights and Level-7 boundary.

### Demote to appendices

- detailed model hashes and stale package metadata;
- corpus split, missing raw replay observations, full training hyperparameters, and zero-rehearsal provenance;
- all historical opponent/order gameplay cells, family summaries, utility sensitivity, and the old forest plot;
- feature-row and retained-replay action agreement;
- temporal takeover and sequence-oracle null experiments;
- post hoc five-opponent historical effects;
- unsupported PPO, expected-Q, Turn Director, historical meta-weighted, and missing-wave claims as provenance exclusions only.

### Forbid

- “we discovered that seeds are insufficient”;
- “control parity proves coupling”;
- “deterministic opponent” without naming the tested execution scope;
- causal attribution of historical `+2.786 pp` to representation, training, or interaction;
- use of the post hoc agreeing-opponent subset as confirmation;
- universal gameplay improvement, superhuman play, competition rank/rating, or population-wide opponent claims;
- inference that zero exact within-state vector collisions means the representation was relationally sufficient;
- inference that source inspection proves wall-clock timing was the sole divergence mechanism;
- event-aligned, counterfactual, or full-CRN wording for the restricted-engine experiments.

## Rewrite acceptance checklist

- The title, first abstract sentence, and contribution paragraph are PEVL-led rather than representation-led.
- Every main Results subsection answers a prespecified PEVL question.
- The old seven-opponent gameplay result is labeled retrospective and one-execution conditional everywhere.
- The manuscript reports the historical requested-versus-consumed seed distinction and does not call the 12-digit stored value the exact engine seed.
- Trace disagreement is primary in the stress test even when terminal outcomes agree.
- The factorial section follows exactly one machine-selected admission branch and contains no pending placeholders.
- All prospective statistics, macros, tables, and figures regenerate from frozen raw outputs.
- Every displayed number has a claim-ledger entry and source hash; no summary prose becomes evidence.
- All new bibliography keys resolve and the current Sharma v3 title is used.
- Data Availability distinguishes the open synthetic suite and processed audit package from restricted engine/opponent/card assets.
- The release verifier, red-team audit, LaTeX compilation, reference resolution, full-page PDF rendering, and visual review all pass after the rewrite.
- Human authors complete authorship, affiliation, ORCID, CRediT, funding, conflict, acknowledgment, AI-use, rights/license, repository, and DOI metadata before submission.
