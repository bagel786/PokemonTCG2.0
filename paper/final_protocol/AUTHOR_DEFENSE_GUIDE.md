# Author defense guide

Purpose: the corresponding author must be able to answer every question below
without overstating the evidence. Each plain-language answer is intentionally
short; the technical note identifies the boundary a specialist may probe.
`human_verified` remains **PENDING** for every item until the human author signs
off. This guide is not a script for memorized claims and does not substitute
for reading the cited evidence.

## 1. What is a seed-matched comparison?

**Plain-language answer (2–4 sentences).** A seed-matched comparison schedules
two policies under the same recorded seed and the same other declared pairing
variables, such as opponent, order, seat, and configuration. It means the
experiment attempted a matched design. It does not yet show that either run
repeats or that both policies received the same random value for each semantic
event.

- **Manuscript section:** Definitions — Schedule matching
- **Evidence file:** `main.tex`; `tables/table_2_protocol_stages.tex`
- **Deeper technical explanation:** Schedule matching is row-level equality of
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
- **Deeper technical explanation:** The timed-search diagnostic held the
  recorded schedule fixed but found 99 trace-projection disagreement clusters
  among 200 seed conditions. This rejects exact repeatability for at least one
  exercised condition but does not isolate a unique causal source.
- **human_verified:** PENDING

## 3. What does a complete trace contain?

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
- **Deeper technical explanation:** Digest equality is stronger than outcome
  equality because it commits to the full recorded sequence, while the byte
  count guards against some serialization mistakes. It remains a claim about
  an observable projection, not an assertion that the entire black-box state
  was captured.
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
- **Deeper technical explanation:** Each stress cluster contains serial-forward,
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

- **Manuscript section:** Trace-based validation protocol — Stages 4–6
- **Evidence file:** `source_data/processed_preflight.json`;
  `tables/table_3_prospective_results.tex`
- **Deeper technical explanation:** The comparison proceeds from outcome and
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
- **Deeper technical explanation:** Identical policies ordinarily consume the
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
- **Deeper technical explanation:** In the synthetic draw-shift fixture,
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
- **Deeper technical explanation:** A trace-digest pass can establish equality of
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

- **Manuscript section:** Trace-based validation protocol — Stages 4–6
- **Evidence file:** `source_data/processed_stress.json`;
  `source_data/processed_preflight.json`
- **Deeper technical explanation:** The stress analysis reduces the four profile
  records to one disagreement indicator per seed condition and resamples the
  whole cluster. Worker and enqueue profiles are fixed execution contexts, not
  sampled hardware replicates.
- **human_verified:** PENDING

## 10. What does the cluster bootstrap resample?

**Plain-language answer (2–4 sentences).** For the timed-search diagnostic, it
resamples whole seed-condition clusters, keeping all four execution profiles
together. For the factorial, the paired-unit bootstrap resamples whole common
unit identifiers within each of ten opponent-by-order strata and keeps all arm
outcomes together. Neither procedure resamples arms or profiles separately.

- **Manuscript section:** Trace-based validation protocol — Paired estimand and
  resampling; Appendix — Resampling and multiplicity details
- **Evidence file:** `source_data/processed_stress.json`;
  `source_data/processed_factorial.json`; `EQUATION_AUDIT.md`
- **Deeper technical explanation:** Both procedures use 100,000 draws and frozen
  analysis seeds, but their resampling objects differ. Their percentile
  intervals describe stability over the realized fixed battery, not coverage
  for new opponents, hardware, or training runs.
- **human_verified:** PENDING

## 11. Why was the historical factorial suppressed?

**Plain-language answer (2–4 sentences).** Its repeated controls did not agree
on the strongest projection available in the historical rows. There were 210
of 2,800 available-outcome (win/draw) mismatches and 458 of 2,800 mismatches
after decision count was added. The frozen rule therefore suppressed the
planned historical contrasts instead of selecting only the agreeing contexts
after inspection.

- **Manuscript section:** Restricted game-agent case study
- **Evidence file:** `../data/ablation/canonical_ablation.csv`;
  `source_data/statistics_verification.json`
- **Deeper technical explanation:** The historical data lack the later trace
  projection and current Stage-3 field set, so the audit is explicitly an
  available-record projection. The mismatches were confined to two timed-search
  context packages, but removing them post hoc would change the frozen target
  and is not a valid rescue analysis.
- **human_verified:** PENDING

## 12. Why was the prospective factorial admitted?

**Plain-language answer (2–4 sentences).** The prospectively frozen deterministic
preflight passed before factorial acquisition, and the factorial’s
prespecified repeated-control available-record gate had zero mismatches. The
fixed schedule, artifact identities, seed boundary, strata, sample sizes, and
failure actions were checked. Admission is bounded because the factorial rows
did not record trace digests and the engine cannot establish semantic event
alignment.

- **Manuscript section:** Prospective validation results — Deterministic
  preflight; Gated factorial demonstration
- **Evidence file:** `source_data/processed_preflight.json`;
  `source_data/processed_factorial.json`;
  `../protocol/PEVL_PROSPECTIVE_PROTOCOL.md`
- **Deeper technical explanation:** The preflight comprised 1,000 arm–seed-
  condition units and 3,000 trajectories across four arms and five deterministic
  contexts. The factorial used 2,000 common units per cell and 12,000 engine
  games; its admission status is `ADMITTED_SEED_MATCHED`, not event aligned.
- **human_verified:** PENDING

## 13. What does the factorial interval mean?

**Plain-language answer (2–4 sentences).** It shows how the prespecified
contrast varies when the realized paired units are resampled within the ten
frozen strata under the fixed algorithm. For the total C4-minus-C1 contrast,
the estimate is +0.55 percentage points with an empirical 95% interval from
−2.05 to +3.15 percentage points. The interval is an algorithmic stability
summary for this battery, not a claim about new opponents or training runs.

- **Manuscript section:** Gated factorial demonstration
- **Evidence file:** `source_data/processed_factorial.json`;
  `tables/table_4_factorial.tex`
- **Deeper technical explanation:** Whole paired identifiers are resampled within
  five-context-by-two-order strata, all four cell rates and contrasts are
  recomputed, and percentile endpoints are taken from 100,000 draws. Equal
  stratum weighting and the frozen seed are part of the estimand implementation.
- **human_verified:** PENDING

## 14. Why does an interval including zero not prove equality?

**Plain-language answer (2–4 sentences).** An interval spanning zero says the
realized data and procedure are compatible with effects in either direction.
It does not show that the true difference is exactly zero. Equivalence would
require a justified margin and a test designed to show that the effect lies
inside that margin; none was prespecified here.

- **Manuscript section:** Gated factorial demonstration; Appendix — Resampling
  and multiplicity details
- **Evidence file:** `source_data/processed_factorial.json`; `EQUATION_AUDIT.md`
- **Deeper technical explanation:** All four factorial intervals cross zero, so
  the correct phrase is “null-compatible” or “compatible with effects in either
  direction.” The secondary McNemar `p=0.706483` also cannot establish equality
  and cannot override admission.
- **human_verified:** PENDING

## 15. Why does agent competitive quality not determine the reproducibility result?

**Plain-language answer (2–4 sentences).** Reproducibility asks whether a fixed
artifact and declared execution condition yield the same recorded behavior, not
whether the artifact is competitively strong. A weak agent can repeat exactly,
and a strong agent can vary under timed search. This paper makes no leaderboard,
state-of-the-art, or policy-quality claim.

- **Manuscript section:** Introduction; Restricted game-agent case study
- **Evidence file:** `main.tex`; `claim_ledger.csv` once generated
- **Deeper technical explanation:** Artifact quality and trace repeatability are
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
- **Deeper technical explanation:** The literature audit verifies bibliographic
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
prospectively validated restricted-engine demonstration. The contribution is
operational integration and evidence-to-wording discipline, not ownership of
the component ideas.

- **Manuscript section:** Introduction; Related work and contribution boundary;
  Trace-based validation protocol
- **Evidence file:** `source_data/processed_synthetic.json`;
  `tables/table_2_protocol_stages.tex`;
  `../protocol/PEVL_PROSPECTIVE_PROTOCOL.md`
- **Deeper technical explanation:** Each stage produces a falsifiable artifact
  and a predetermined reporting consequence. The same map explains both the
  suppressed historical analysis and the bounded prospective factorial, which
  is the practical integration being demonstrated.
- **human_verified:** PENDING

## 18. Which files let another researcher verify each result?

**Plain-language answer (2–4 sentences).** `source_data/processed_synthetic.json`
supports the five fixture results; `processed_preflight.json` and
`processed_stress.json` support the prospective diagnostics; and
`processed_factorial.json` plus processed paired rows support the factorial.
`statistics_verification.json`, `results_macros.tex`, figure source-data files,
tests, protocols, and the release manifest connect those inputs to the paper.
Restricted trajectories cannot be replayed without separately authorized
engine and package access.

- **Manuscript section:** Data Availability Statement; Appendix — Artifact and
  rights boundary
- **Evidence file:** `source_data/`; `scripts/`; `tests/`; `release/`
- **Deeper technical explanation:** The one-command workflow must verify source
  hashes and schemas, rebuild statistics, macros, tables, and figures, run the
  contradiction audit and tests, compile the PDF, and write a reproduction
  report. The release is computationally self-contained for synthetic and
  processed analyses only after its final manifest passes.
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
- **Deeper technical explanation:** The review package retains approved digests,
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

- **Manuscript section:** Trace-based validation protocol — AI-assisted research
  methods; Artificial-intelligence assistance
- **Evidence file:** `supplement/AI_USE_LOG.csv`; `ai_disclosure.md`;
  `source_data/statistics_verification.json`; `REFERENCE_AUDIT.csv`
- **Deeper technical explanation:** AI suggestions are not themselves evidence.
  Any incomplete activity history, unexposed model identifier, unverified claim,
  or unresolved confidentiality, terms, privacy, and intellectual-property issue
  must remain disclosed as a blocker rather than be inferred away.
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

Until every row is confirmed, the package cannot receive a ready-to-submit
decision.
