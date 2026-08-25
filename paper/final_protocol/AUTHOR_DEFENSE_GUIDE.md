# Author defense guide

Purpose: the corresponding author must be able to answer every question below
without overstating the evidence. Each plain-language answer is intentionally
short; each technical answer identifies the boundary a specialist may probe.
`human_verified` remains **PENDING** for every item until the human author signs
off. This guide is not a script for memorized claims and does not substitute
for reading the cited evidence.

## 1. What is a seed-matched comparison?

**Plain-language answer (2–4 sentences).** A seed-matched comparison schedules
two policies under the same recorded seed and the same other declared pairing
variables, such as opponent, order, seat, and configuration. It means the
experiment attempted a matched design and permits a descriptive within-row
contrast. Inferential pairing additionally requires a randomized assignment,
probability sample, or defended stochastic model that justifies the reference
distribution and exchangeability or independence. Neither statistical pairing
nor seed equality shows that a run repeats or that both policies received the
same value for each semantic event.

- **Manuscript section:** Definitions — Schedule matching
- **Evidence file:** `main.tex`; `tables/table_2_protocol_stages.tex`
- **Technical answer:** Schedule matching is row-level equality of
  frozen design fields, including the converted value passed at the observable
  engine boundary. It is Level 3 evidence in the admission map and is logically
  weaker than within-arm execution repeatability and cross-arm event alignment.
- **human_verified:** PENDING

## 2. Why is matching a seed not equivalent to repeating an execution?

**Plain-language answer (2–4 sentences).** A seed is one input, while an
execution can also depend on clocks, process state, concurrency, native state,
and how the engine consumes random draws. Even with the same seed, those other
sources can change actions or decision counts. Repetition therefore has to be
checked from the execution record, not inferred from the seed column.

- **Manuscript section:** Introduction; Definitions — Execution repeatability
- **Evidence file:** `source_data/processed_stress.json`;
  `../data/stochastic_source_audit.json`
- **Technical answer:** The timed-search diagnostic held the
  recorded schedule fixed but found 99 trace-projection disagreement clusters
  among 200 seed conditions. This rejects exact repeatability for at least one
  exercised condition but does not isolate a unique causal source.
- **human_verified:** PENDING

## 3. Why is outcome equality weaker than trace equality, and what is recorded?

**Plain-language answer (2–4 sentences).** In this paper, “complete” always
means complete within the declared recorded projection. That projection orders
the public-observation hash, acting side, and selected action for each decision,
then appends the terminal record; the analysis compares its SHA-256 digest and
byte count. It does not contain raw observations, hidden simulator state,
opaque search snapshots, or semantic random-event identifiers.

- **Manuscript section:** Definitions — Execution repeatability; Appendix —
  Trace record and study-specific fields
- **Evidence file:** `source_data/processed_preflight.json`;
  `../protocol/PEVL_PROSPECTIVE_PROTOCOL.md`
- **Technical answer:** Equation (1) compares the ordered
  `(digest, byte_count)` tuple, so either a digest difference or a byte-count-only
  difference marks the cluster. A missing required profile fails the gate rather
  than disappearing from the denominator. Tuple equality remains a claim about
  an observable projection, not an assertion that the entire black-box state
  was captured. The frozen stress endpoint was digest equality alone; byte count
  was added after acquisition as integrity hardening. Both the frozen digest
  endpoint and the later tuple identify 99/200 stress clusters because the 96
  byte-count disagreements are contained within the 99 digest disagreements.
- **human_verified:** PENDING

## 4. Why can two identical agents differ under timed search?

**Plain-language answer (2–4 sentences).** A timed-search policy may choose an
action based on how much work finishes before a deadline. Scheduling, queue
order, process state, and machine load can alter that work even when policy
bytes and the recorded seed match. In this case study those are plausible
mechanisms, not a proven unique cause of every divergence.

- **Manuscript section:** Prospective validation results — Timed-search stress
  test
- **Evidence file:** `source_data/processed_stress.json`;
  `../data/stochastic_source_audit.json`
- **Technical answer:** Each stress cluster contains serial-forward,
  serial-reverse, parallel-forward, and parallel-reverse profiles. Trace
  differences were more common than terminal-outcome differences, which is
  consistent with execution-path sensitivity but does not causally identify
  wall-clock timing.
- **human_verified:** PENDING

## 5. What does an A/A trace test establish?

**Plain-language answer (2–4 sentences).** It asks whether separately launched,
byte-identical arms produce the same declared execution record under the tested
seed conditions and contexts. A pass establishes exact repeatability for that
recorded projection and scope. A single required mismatch rejects exact parity
on the exercised schedule.

- **Manuscript section:** Pairing-assumption validation protocol — Stages 4–6
- **Evidence file:** `source_data/processed_preflight.json`;
  `tables/table_3_prospective_results.tex`
- **Technical answer:** The comparison proceeds from outcome and
  errors to decision count and then digest plus byte count of the canonical
  recorded trace. The prospective deterministic preflight passed on 1,000
  arm–seed-condition units and 3,000 executions with zero required mismatches.
- **human_verified:** PENDING

## 6. What does an A/A trace test fail to establish?

**Plain-language answer (2–4 sentences).** It cannot show that different
policies receive the same random quantity for the same semantic event after
their paths diverge. It also cannot validate fields the trace projection omits
or guarantee repeatability on untested machines, loads, or future runs. A/A is
within-arm evidence, not cross-arm counterfactual evidence.

- **Manuscript section:** Definitions — Execution repeatability and Semantic
  event alignment
- **Evidence file:** `source_data/figure_1_distinctions.json`;
  `source_data/processed_synthetic.json`
- **Technical answer:** Identical policies ordinarily consume the
  same stateful random sequence because they follow the same path. Different
  policies may branch and shift later draw assignments even when both arms are
  individually perfectly repeatable.
- **human_verified:** PENDING

## 7. What is semantic event alignment?

**Plain-language answer (2–4 sentences).** Semantic event alignment means that
the same modeled external event keeps a stable identity across arms and receives
the same random quantity, even after policy paths differ. It requires event
identifiers and values, event-specific streams, or a validated event-keyed
construction. Matching a stateful random-number sequence position is not enough
when one arm consumes an extra draw.

- **Manuscript section:** Definitions — Semantic event alignment
- **Evidence file:** `source_data/processed_synthetic.json`;
  `source_data/figure_3_synthetic_matrix.csv`
- **Technical answer:** In the synthetic draw-shift fixture,
  stateful draws aligned only one of five shared logged events after a path
  shift, whereas event-keyed derivation aligned all five. That is a fixture-
  scoped demonstration conditional on its ontology and distribution.
- **human_verified:** PENDING

## 8. Why can the real engine not establish event alignment?

**Plain-language answer (2–4 sentences).** The restricted engine does not expose
stable semantic event identifiers or event-keyed random streams. Its public
trace shows observations and actions, not which internal random event received
which value. The paper therefore stops at bounded seed-matched wording and does
not claim full CRN or counterfactual coupling.

- **Manuscript section:** Definitions — Semantic event alignment; Limitations
- **Evidence file:** `../protocol/PEVL_PROSPECTIVE_PROTOCOL.md`;
  `source_data/processed_factorial.json`
- **Technical answer:** A trace-digest pass can establish equality of
  the observable projection within one arm, but it cannot reconstruct hidden
  event assignments across different policy paths. Level 7 is explicitly
  marked not established for the restricted case study.
- **human_verified:** PENDING

## 9. Why are execution profiles within one seed cluster not independent?

**Plain-language answer (2–4 sentences).** The profiles reuse the same planned
seed condition, artifact, opponent, order, and other fixed inputs. They are
multiple diagnostic views of one condition, not fresh random draws from a
population. Treating them as independent would inflate the apparent amount of
information.

- **Manuscript section:** Pairing-assumption validation protocol — Stages 4–6
- **Evidence file:** `source_data/processed_stress.json`;
  `source_data/processed_preflight.json`
- **Technical answer:** The stress analysis reduces the four profile
  records to one disagreement indicator per seed condition and reweights the
  whole cluster. Worker and enqueue profiles are fixed execution contexts, not
  sampled hardware replicates.
- **human_verified:** PENDING

## 10. What do the empirical reweighting procedures reweight?

**Plain-language answer (2–4 sentences).** For the timed-search diagnostic, the
frozen pooled procedure reweights whole seed-condition clusters, keeping all
four execution profiles together, but can change context composition. The
factorial procedure reweights whole schedule-indexed unit identifiers within
each of ten opponent-by-order strata and keeps all arm outcomes together.
Neither procedure reweights arms or profiles separately.

- **Manuscript section:** Pairing-assumption validation protocol — Seed-indexed
  descriptive contrast and reweighting; Appendix — Empirical reweighting details
- **Evidence file:** `source_data/processed_stress.json`;
  `source_data/processed_factorial.json`; `EQUATION_AUDIT.md`
- **Technical answer:** Both frozen procedures use 100,000 draws and frozen
  analysis seeds, but their empirical reweighting objects differ. Stress counts
  are strongly heterogeneous across the four strata: 44/50, 48/50, 4/50, and
  3/50. The frozen pooled quantiles are 42.5%–56.5%; an explicitly
  post-acquisition, source-driven fixed-composition sensitivity gives 46%–53%.
  Neither range is a confidence interval or coverage statement in the final
  article. The case-study protocol originally called the finite-population
  resampling outputs bootstrap intervals; `empirical reweighting quantiles` is a
  later conservative descriptive label.
- **human_verified:** PENDING

## 11. Why was the historical factorial suppressed?

**Plain-language answer (2–4 sentences).** Its repeated controls did not agree
on the strongest projection available in the historical rows. There were 210
of 2,800 available-outcome (win/draw) mismatches and 458 of 2,800 mismatches
after decision count was added. The frozen rule therefore suppressed the
planned historical contrasts instead of selecting only the agreeing contexts
after inspection. The gate and suppression consequence were frozen
retrospectively after these historical outcomes already existed; this is an
auditable safeguard, not evidence of prospective blinding.

- **Manuscript section:** Restricted game-agent case study
- **Evidence file:** `../data/ablation/canonical_ablation.csv`;
  `source_data/statistics_verification.json`;
  `source_data/independent_statistics_verification.json`
- **Technical answer:** The historical data lack the later trace
  projection and current Stage-3 field set, so the audit is explicitly an
  available-record projection. The mismatches were confined to two timed-search
  context packages, but removing them post hoc would change the frozen target
  and is not a valid rescue analysis. Retrospective freezing does not convert
  the historical audit into prospective validation.
- **human_verified:** PENDING

## 12. Why is the gated factorial reported only as a descriptive summary?

**Plain-language answer (2–4 sentences).** Git orders the binary deterministic
qualification protocol before the retained preflight and factorial artifacts,
and the factorial’s frozen repeated-control available-record gate had zero
mismatches. The frozen plan then called for finite-population paired bootstrap
intervals and secondary exact McNemar inference, but the article later adopted
a conservative descriptive-only taxonomy. It therefore reports a fixed-battery
contrast and empirical reweighting sensitivity: the preflight and factorial
used different seed ranges, factorial candidate rows have no trace digests, and
the engine cannot establish semantic event alignment. The five deterministic
contexts were a newly frozen, audit-informed target, not a rescue subset of the
historical target.

- **Manuscript section:** Prospective validation results — Deterministic
  preflight; Claim-admission consequence
- **Evidence file:** `source_data/processed_preflight.json`;
  `source_data/processed_factorial.json`;
  `../protocol/PEVL_PROSPECTIVE_PROTOCOL.md`
- **Technical answer:** The preflight comprised 1,000 arm–seed-
  condition units and 3,000 trajectories across four arms and five deterministic
  contexts. The factorial used 2,000 common units per cell and 12,000 engine
  games. Transferring qualification across those different seed batteries is a
  bounded assumption about the same identified artifacts and contexts, not
  observed candidate-arm trace repeatability on factorial rows. The admitted
  label is descriptive seed matching, not inferential pairing or event
  alignment. The later taxonomy cannot evidence its own prospective validation;
  future studies must freeze it and its reporting consequences before
  acquisition.
- **human_verified:** PENDING

## 13. What do the factorial reweighting quantiles mean?

**Plain-language answer (2–4 sentences).** They show how a prespecified
fixed-battery contrast varies when the realized schedule-indexed units are
empirically reweighted within the ten frozen strata under the fixed algorithm.
For the total C4-minus-C1 contrast, the descriptive value is +0.55 percentage
points and the 2.5th and 97.5th reweighting percentiles are −2.05 and +3.15
percentage points. These are sensitivity quantiles for this battery, not a
confidence interval or a claim about new seeds, opponents, or training runs.
The frozen plan used the term finite-population paired bootstrap interval; the
descriptive quantile label was adopted conservatively after acquisition.

- **Manuscript section:** Claim-admission consequence; Appendix — Secondary
  factorial details
- **Evidence file:** `source_data/processed_factorial.json`;
  `tables/table_4_factorial.tex`
- **Technical answer:** Whole schedule-indexed paired identifiers are reweighted within
  five-context-by-two-order strata, all four cell rates and contrasts are
  recomputed, and percentile endpoints are taken from 100,000 draws. Equal
  stratum weighting and the frozen seed are part of the descriptive procedure;
  no inferential sampling or assignment mechanism is asserted.
  The frozen plan also specified secondary exact two-sided McNemar inference for
  C4 versus C1. Its value is retained only in the numerical audit and is not
  admitted as inference under the later descriptive-only taxonomy.
- **human_verified:** PENDING

## 14. Why do sign-spanning reweighting quantiles not prove equality?

**Plain-language answer (2–4 sentences).** Quantiles spanning both signs show
that empirical reweightings of this fixed battery produce contrasts in both
directions. They do not test whether a population difference is zero.
Equivalence would require a justified margin and an inferential design directed
at that claim; neither was supplied here.

- **Manuscript section:** Claim-admission consequence; Appendix — Empirical
  reweighting details
- **Evidence file:** `source_data/processed_factorial.json`; `EQUATION_AUDIT.md`
- **Technical answer:** All four empirical reweighting ranges span zero.
  “Null-compatible” is permissible only as shorthand for that descriptive
  sensitivity behavior, not as a hypothesis-test conclusion or unresolved
  population effect. No manuscript p-value or hypothesis test is admitted.
- **human_verified:** PENDING

## 15. Why does agent competitive quality not determine the reproducibility result?

**Plain-language answer (2–4 sentences).** Reproducibility asks whether a fixed
artifact and declared execution condition yield the same recorded behavior, not
whether the artifact is competitively strong. A weak agent can repeat exactly,
and a strong agent can vary under timed search. This paper makes no leaderboard,
state-of-the-art, or policy-quality claim.

- **Manuscript section:** Introduction; Restricted game-agent case study
- **Evidence file:** `main.tex`; `claim_ledger.csv` once generated
- **Technical answer:** Artifact quality and trace repeatability are
  orthogonal properties. The factorial demonstration is included to show the
  admission consequence, while detailed game strategy and competitive history
  remain outside the paper’s estimand.
- **human_verified:** PENDING

## 16. What prior work already existed?

**Plain-language answer (2–4 sentences).** Common random numbers, conditions for
their variance reduction, streams and substreams, paired-seed evaluation,
event-keyed randomness, A/A and metamorphic testing, simulation verification,
empirical RL reproducibility, and time-versus-work budgets all predate this
article. The paper does not claim to have discovered that same seeds can fail,
that synchronization matters, or that identical-arm and fixed-work checks are
new. It cites each component at the scope its primary source supports.

- **Manuscript section:** Related work and contribution boundary
- **Evidence file:** `REFERENCE_AUDIT.csv`; `references.bib`;
  `tables/table_1_prior_work.tex`
- **Technical answer:** The literature audit verifies bibliographic
  fields and sentence support from primary publisher, proceedings, arXiv, or
  OpenReview records. The unverified “Silent Unpairing” item is not cited or used
  as evidence because no authoritative public record was found.
- **human_verified:** PENDING

## 17. What exactly does this paper add?

**Plain-language answer (2–4 sentences).** It integrates existing components
into one executable black-box protocol that separates schedule matching,
within-arm repeatability, cross-arm event alignment, and claim admission. It
implements a complete declared trace projection, a fail-closed map that admits,
downgrades, or suppresses claims, a self-contained conformance suite, and a
frozen experiment-specific qualification in a restricted-engine demonstration.
The contribution is operational integration and evidence-to-wording discipline,
not ownership of the component ideas or a population effect estimate.

- **Manuscript section:** Introduction; Related work and contribution boundary;
  Pairing-assumption validation protocol
- **Evidence file:** `source_data/processed_synthetic.json`;
  `tables/table_2_protocol_stages.tex`;
  `../protocol/PEVL_PROSPECTIVE_PROTOCOL.md`
- **Technical answer:** Each stage produces a falsifiable artifact and a
  reporting consequence. The case-study protocol prospectively froze binary
  acquisition/suppression consequences for the new acquisitions, while its
  historical gate was frozen retrospectively and the multi-level generic map
  was formalized after acquisition. The later map consistently describes the
  suppressed historical analysis and fixed-battery factorial summary, but that
  consistency is not evidence that the taxonomy was prospectively validated.
- **human_verified:** PENDING

## 18. Which files let another researcher verify each result?

**Plain-language answer (2–4 sentences).** `source_data/processed_synthetic.json`
supports the five fixture results; `processed_preflight.json` and
`processed_stress.json` support the prospective diagnostics; and
`processed_factorial.json` plus processed paired rows support the factorial.
`statistics_verification.json` records fixed-battery descriptive reweighting
quantiles and isolates the separately requested inferential arithmetic under an
explicitly nonadmitted numerical-audit block. `independent_statistics_verification.json`,
`results_macros.tex`, figure source-data files, tests, protocols, and the release
manifest connect those inputs to the paper.
Restricted trajectories cannot be replayed without separately authorized
engine and package access.

- **Manuscript section:** Data Availability Statement; Appendix — Artifact and
  rights boundary
- **Evidence file:** `source_data/`; `scripts/`; `tests/`; `release/`
- **Technical answer:** The one-command workflow must verify source
  hashes and schemas, rebuild statistics, macros, tables, and figures, run the
  contradiction audit and tests, compile the PDF, and write a reproduction
  report. The release is computationally self-contained for synthetic and
  processed analyses only after its final manifest passes. It omits the frozen
  protocol's promised first-divergence position, acting-side/actor localization,
  and timing summaries for the stress diagnostic, and it includes no raw trace
  lines from which first divergence can be independently reconstructed. This is
  an unresolved reporting/access protocol deviation; it does not change the
  frozen primary digest count of 99/200, but human confirmation and an amendment
  decision remain PENDING.
- **human_verified:** PENDING

## 19. Which materials are restricted and why?

**Plain-language answer (2–4 sentences).** The tournament engine and source,
engine binaries, third-party opponent packages, game assets and metadata,
private replay observations, policy packages, and raw restricted traces are not
redistributed. Organizer terms, third-party rights, privacy constraints, and
unresolved release authority prevent the repository from granting access.
They are not described as available on request because no legal and practical
controlled-access mechanism has been established.

- **Manuscript section:** Limitations; Data Availability Statement; Appendix —
  Artifact and rights boundary
- **Evidence file:** `data_availability.md`;
  `supplement/RIGHTS_AND_ACCESS_AUDIT.md`; `release/MANIFEST.sha256`
- **Technical answer:** The computational package retains approved digests,
  neutral labels, processed diagnostics, and sufficient processed rows for
  reaggregation. Those materials do not replace end-to-end replay and do not
  confer rights in excluded third-party content.
- **human_verified:** PENDING

## 20. How was AI used and checked?

**Plain-language answer (2–4 sentences).** OpenAI Codex, using a GPT-5-family
model whose exact deployed snapshot was not exposed, assisted with scientific
reasoning, literature synthesis, code and debugging, frozen-workflow
orchestration, statistical analysis, deterministic visualization, drafting,
release assembly, and adversarial review. Human instructions defined the
scientific question, frozen constraints, and claim authority. Accepted outputs
were checked against hashes, schemas, rows, tests, primary sources, compilation,
and rendered output as appropriate; no AI system is an author.

- **Manuscript section:** Pairing-assumption validation protocol — AI-assisted
  research methods; Artificial-intelligence assistance
- **Evidence file:** `supplement/AI_USE_LOG.csv`; `ai_disclosure.md`;
  `source_data/build_report.json`; `REFERENCE_AUDIT.csv`
- **Technical answer:** AI suggestions are not themselves evidence.
  Any incomplete activity history, unexposed model identifier, unverified claim,
  or unresolved confidentiality, terms, privacy, and intellectual-property issue
  must remain disclosed as a blocker rather than be inferred away.
- **human_verified:** PENDING

## 21. Why do source-pattern hits not prove what caused a trace disagreement?

**Plain-language answer (2–4 sentences).** A static scan can show that source
code contains a clock, random interface, concurrency call, global state, or a
native handle. It cannot show that the matching branch ran, influenced the
record, or uniquely caused a disagreement. Hits nominate mechanisms for
controlled follow-up; zero hits do not prove determinism.

- **Manuscript section:** Pairing-assumption validation protocol — Stages 4–6:
  trace repetition and source audit
- **Evidence file:** `../data/stochastic_source_audit.json`;
  `METHOD_ASSUMPTION_AUDIT.md`
- **Technical answer:** The bounded scanner applies declared AST and qualified-
  name/identifier patterns only to the frozen Python source set. It does not
  execute code, inspect the two binary engines, observe runtime scheduling, or
  cover hardware-sensitive numerics and external state, so causal attribution
  would require a separate intervention or runtime trace.
- **human_verified:** PENDING

## 22. How is admission result independent, and what safety properties are tested?

**Plain-language answer (2–4 sentences).** The evidence-bound admission path
derives gate states from validated evidence, while a separate classifier accepts
explicit states only as trusted inputs for formal checks. Rule evaluation does
not see who won, a contrast, reweighting quantiles, a p-value, or result
favorability. Failing or removing evidence cannot strengthen wording, and
unknown, malformed, or contradictory evidence suppresses rather than admits.

- **Manuscript section:** Pairing-assumption validation protocol — Executable
  admission map and formal properties
- **Evidence file:** `release_templates/pevl_bench/admission.py`;
  `release_templates/protocol/admission_rules.json`;
  `release_templates/tests/test_release.py`
- **Technical answer:** Result independence means that replacing the outcome
  payload leaves admission unchanged. The seven named properties are **result
  independence**, **prerequisite monotonicity**, **failure dominance**,
  **projection scoping**, **stateless determinism**, **unknown-state
  fail-closedness**, and **strict claim ordering**. Stateless determinism means
  that separate evaluations of unchanged inputs, with no retained evaluator
  state, return the same answer; this is a repeat-run property, not a
  state-mutating operation. For
  example, if Levels 1–4 pass and the repeat/worker gate fails,
  carried contrasts of +20 and −20 percentage points receive the same
  schedule-matched downgrade, and deleting artifact evidence can only weaken
  it. The tests replace result payloads, weaken prerequisites, insert extreme favorable
  payloads after failures, remove projection fields, repeat evaluations,
  exercise malformed and tampered documents, and enumerate all six declared
  states across all seven gates. The generic bundle is explicitly a
  post-acquisition formalization; prospectively frozen experiment-specific
  rules remain authoritative. The tests cannot establish that the taxonomy was
  prospectively validated for already completed acquisitions.
- **human_verified:** PENDING

## 23. Why do the later sign-spanning descriptive quantiles not weaken the protocol result?

**Plain-language answer (2–4 sentences).** Gate evidence, rather than result
favorability, determines what wording the rule permits. The frozen historical
retrospective rule suppressed an apparently favorable comparison after a
required gate failed; the post-acquisition taxonomy reports the later case only
as a fixed-battery descriptive contrast and reweighting sensitivity after its
binary qualification gates passed. Sign-spanning
quantiles describe that sensitivity and are neither a failed protocol test nor
a population null result.

- **Manuscript section:** Claim-admission consequence; Interpretation and
  permitted claims
- **Evidence file:** `source_data/processed_factorial.json`;
  `source_data/statistics_verification.json`;
  `release/tests/test_admission_hardening.py`;
  `../protocol/PEVL_PROSPECTIVE_PROTOCOL.md`
- **Technical answer:** Git orders the experiment-specific rule commit before
  the retained result artifacts; it does not establish when a human viewed
  uncommitted files, and the historical gate was frozen only after historical
  outcomes existed. Functional tests show that replacing outcome payloads while
  holding evidence fixed leaves admission unchanged. Direction, reweighting
  quantiles, p-values, and favorability are excluded from the decision
  projection. “Null-compatible” can describe only the sign-spanning empirical
  reweighting distribution, not a test, population effect, event alignment,
  equivalence, or policy superiority.
- **human_verified:** PENDING

## 24. How does this method differ from Rollout Cards?

**Plain-language answer (2–4 sentences).** Rollout Cards preserve the records,
views, reporting rules, failures, skips, and drops behind agent-evaluation
scores. That is valuable evidence and reporting provenance, but it does not
test whether two same-seed executions are coupled or decide whether failed
pairing evidence suppresses a paired statistical claim. This paper adds that
pairing-specific validation and admission workflow.

- **Manuscript section:** Related work and contribution boundary
- **Evidence file:** `NOVELTY_AUDIT.md`; `NOVELTY_MATRIX.csv`;
  `REFERENCE_AUDIT.csv`
- **Technical answer:** The unit in Rollout Cards is a preserved rollout plus
  declared views, scoring/reporting rules, and a drops manifest. The present
  protocol instead binds observable boundary seeds and schedules, tests a
  declared A/A projection across execution profiles, separates within-arm
  repeatability from cross-arm semantic alignment, and maps the resulting
  evidence to estimands and permitted wording. It does not claim rollout
  preservation or reporting provenance as new.
- **human_verified:** PENDING

## 25. How does this method differ from trace-assurance frameworks?

**Plain-language answer (2–4 sentences).** Trace-assurance frameworks use
contracts, replay, perturbations, and governance actions to find and control
failures in agentic orchestration. They do not ask whether a shared seed creates
a legitimate stochastic pair or map a failed pairing gate to suppression of a
paired estimate. This paper narrows the trace idea to that statistical-admission
problem.

- **Manuscript section:** Related work and contribution boundary
- **Evidence file:** `NOVELTY_AUDIT.md`; `NOVELTY_MATRIX.csv`;
  `REFERENCE_AUDIT.csv`
- **Technical answer:** Paduraru, Bouruc, and Stefanescu use Message-Action
  Traces, step and trace contracts, first-violation localization, structured
  fault injection, and allow/rewrite/block governance. Their framework does not
  supply boundary-seed collision auditing, the identical-arm versus cross-arm
  semantic-alignment distinction, a statistical evidence-to-claim map, or the
  present empirical suppression case. This paper does not claim trace
  contracts, replay, perturbation search, or runtime governance as new.
- **human_verified:** PENDING

## 26. How does this method differ from AEVAL?

**Plain-language answer (2–4 sentences).** AEVAL turns agent-skill changes into
deterministic evaluation-contract tests with inspectable first-attempt
artifacts and CI-friendly pass/fail signals. It addresses anecdotal evaluation
and self-correction bias, not same-seed stochastic coupling. This protocol uses
related fail-closed discipline for deciding whether paired statistical wording
is supported.

- **Manuscript section:** Related work and contribution boundary
- **Evidence file:** `NOVELTY_AUDIT.md`; `NOVELTY_MATRIX.csv`;
  `REFERENCE_AUDIT.csv`
- **Technical answer:** AEVAL's unit is an evaluation-contract test case and its
  executor artifacts, transcripts, assertions, and first-attempt quality signal.
  It does not verify observable boundary-seed identity, distinguish within-arm
  trace repeatability from cross-arm event alignment, or admit an estimand and
  uncertainty procedure after pairing gates. This paper does not claim
  deterministic workflow testing, CI gating, or first-attempt evidence as new.
- **human_verified:** PENDING

## 27. How does this method differ from event-keyed randomness?

**Plain-language answer (2–4 sentences).** Event-keyed randomness is a
white-box repair: a stable identifier assigns the same random quantity to the
same modeled event across diverging executions. This protocol tests what can be
claimed when a black-box system may not expose or permit that repair. It uses an
event-keyed fixture to demonstrate the distinction but does not claim the
construction as new.

- **Manuscript section:** Definitions — Semantic event alignment; Related work
  and contribution boundary
- **Evidence file:** `source_data/processed_synthetic.json`;
  `NOVELTY_AUDIT.md`; `REFERENCE_AUDIT.csv`
- **Technical answer:** Buffalo, Pearson, and Klein define a counter-based value
  assignment keyed by a declared semantic event ontology, addressing the
  execution-invariance failure of draw-indexed streams. Applying it requires
  control of event identities, marginals, and intended dependence. The present
  restricted engine exposes none of those; its contribution is a black-box
  evidence ladder and fail-closed admission decision, not an alternative random
  number generator.
- **human_verified:** PENDING

## 28. What does the worked admission example establish?

**Plain-language answer (2–4 sentences).** The engine-independent example shows
how a researcher can package evidence, request a decision, identify the first
blocking gate, and obtain bounded wording and a repair action. Its first four
gates pass, but a fresh-profile trace changes at the repeat/worker gate, so the
tool permits only `schedule_matched` wording and recommends reacquisition. The
apparently favorable result carried in the file cannot override that decision.

- **Manuscript section:** Pairing-assumption validation protocol — Executable
  admission map and formal properties
- **Evidence file:** `release_templates/examples/example_evidence.json`;
  `release_templates/docs/WORKED_ADMISSION_EXAMPLE.md`;
  `release_templates/tests/test_release.py`
- **Technical answer:** `python -m pevl_bench admit` evaluates the strict JSON
  envelope; `explain` returns the permitted class, forbidden wording, first
  blocking gate, and repair evidence. The example tests interface and decision
  semantics without the restricted engine. It does not validate the real case,
  make the generic map prospective for completed acquisitions, or supersede a
  study-specific frozen suppression rule.
- **human_verified:** PENDING

## 29. What must another researcher do to adopt the protocol?

**Plain-language answer (2–4 sentences).** For a new study, the researcher must
prospectively declare artifacts, seed conversion, schedule fields, trace
projection, execution profiles, event ontology if available, analysis unit,
descriptive reweighting rule and any separate inferential sampling or assignment
basis, and the evidence-to-claim failure actions. They then collect
every required profile, run the gates, retain failures, and use the admitted
wording rather than choosing a favorable subset. They must also document rights
and release only materials they are authorized to distribute.

- **Manuscript section:** Pairing-assumption validation protocol; Data
  Availability Statement
- **Evidence file:** `release_templates/docs/ADMISSION_DECISION_TABLE.md`;
  `release_templates/docs/WORKED_ADMISSION_EXAMPLE.md`;
  `release_templates/protocol/admission_schema.json`; `data_availability.md`
- **Technical answer:** For a new prospective study, the adopter freezes the
  experiment-specific rule and identifiers, validates boundary conversion and
  row completeness, launches A/A repeats across declared process/worker/enqueue
  contexts, runs the bounded source audit, tests event alignment when observable,
  and invokes admission on a schema-valid evidence record. Any missing,
  malformed, contradictory, or unrecognized prerequisite fails closed. The
  adopter must freeze and validate the generic taxonomy against the
  study-specific rule before acquisition;
  the supplied post-acquisition formalization cannot retroactively authorize a
  completed comparison.
- **human_verified:** PENDING

## Required author sign-off

The author must initial each item only after answering it without this guide,
locating the named evidence, and explaining its limitation. A blanket signature
is insufficient.

| Question | Author initials | Date | Comprehension confirmed | Notes |
|---:|---|---|---|---|
| 1 |  |  | NO |  |
| 2 |  |  | NO |  |
| 3 |  |  | NO |  |
| 4 |  |  | NO |  |
| 5 |  |  | NO |  |
| 6 |  |  | NO |  |
| 7 |  |  | NO |  |
| 8 |  |  | NO |  |
| 9 |  |  | NO |  |
| 10 |  |  | NO |  |
| 11 |  |  | NO |  |
| 12 |  |  | NO |  |
| 13 |  |  | NO |  |
| 14 |  |  | NO |  |
| 15 |  |  | NO |  |
| 16 |  |  | NO |  |
| 17 |  |  | NO |  |
| 18 |  |  | NO |  |
| 19 |  |  | NO |  |
| 20 |  |  | NO |  |
| 21 |  |  | NO |  |
| 22 |  |  | NO |  |
| 23 |  |  | NO |  |
| 24 |  |  | NO |  |
| 25 |  |  | NO |  |
| 26 |  |  | NO |  |
| 27 |  |  | NO |  |
| 28 |  |  | NO |  |
| 29 |  |  | NO |  |

Until every row is confirmed, the package cannot receive a ready-to-submit
decision. The unsigned `supplement/PROTOCOL_DEVIATIONS.md` record also requires
human confirmation and an explicit amendment decision; this guide records
neither one.
