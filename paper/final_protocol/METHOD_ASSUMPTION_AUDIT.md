# Method and assumption audit

Audit scope: the methods described in `main.tex` for the Protocol Article
“A Protocol for Validating Pairing Assumptions in Seed-Matched Evaluations of
Black-Box Game-Playing Agents.” This is an explanation and scope audit, not an additional
analysis. The source-of-truth order is raw rows, frozen protocol, validated
analyzer output, executable code, hashes, generated macros, manuscript prose,
historical reports, and conversation summaries.

## M01 — Artifact identity

- **Problem solved:** Prevents results from being attributed to unspecified or
  drifting simulator, policy, opponent, evaluator, protocol, or configuration
  bytes.
- **Why needed here:** The restricted engine and several packages cannot be
  redistributed, so a verifier needs stable identifiers for the exact locally
  exercised artifacts.
- **Analysis unit:** One declared artifact or configuration object.
- **Assumptions:** SHA-256 is computed over the intended bytes with the declared
  file/tree algorithm; the inventory is complete; the identified bytes are the
  bytes actually executed.
- **Implementation:** Stage 1 computes and checks identities before admitting
  downstream evidence. The final artifact builder pins the protocol and result
  hashes.
- **Output:** An identity inventory and pass/fail decision.
- **Invalidating result:** A missing item, changed digest, ambiguous tree-hash
  rule, or evidence that different bytes executed.
- **Does not support:** A hash match does not establish behavioral validity,
  repeatability, event alignment, correctness, ownership, or redistribution
  permission.
- **human_verified:** PENDING — a human author must confirm that the inventory
  and hashing rule cover the exact bytes executed; this remains a submission
  blocker until signed.

## M02 — Boundary-seed and namespace verification

- **Problem solved:** Detects narrowing, reduction, collision, overlap, or other
  conversion between a scheduled seed and the integer passed at the observable
  engine boundary.
- **Why needed here:** Equality of host-language seed fields is uninformative if
  an adapter maps distinct scheduled values to the same boundary value.
- **Analysis unit:** One scheduled evaluation row, with schedule-level collision
  and overlap checks.
- **Assumptions:** The wrapper records the exact value passed at the accessible
  boundary; the conversion rule is applied to the complete planned schedule.
- **Implementation:** Stage 2 stores scheduled and boundary values, validates
  range and uniqueness, and checks unintended overlaps before acquisition.
- **Output:** A row-level conversion record, namespace audit, and pass/fail
  decision.
- **Invalidating result:** An unintended collision, out-of-range value, overlap
  forbidden by the protocol, missing scheduled row, or failure to observe the
  boundary value.
- **Does not support:** The recorded boundary value is not evidence of how the
  black-box engine internally consumes, splits, or ignores randomness.
- **human_verified:** PENDING — a human author must confirm the boundary is the
  last observable conversion point and the collision/overlap rules match the
  frozen schedule; this remains a submission blocker until signed.

## M03 — Row-level schedule parity

- **Problem solved:** Establishes that the two arms attempted the same declared
  evaluation conditions.
- **Why needed here:** A shared seed column cannot repair a difference in
  opponent, order, physical seat, environment, decision limit, or other fixed
  configuration.
- **Analysis unit:** One arm-paired schedule row.
- **Assumptions:** All variables required by the frozen protocol are recorded
  canonically and the expected cell inventory is complete.
- **Implementation:** Stage 3 compares all prespecified pairing fields and
  verifies the schedule fingerprint and expected rows.
- **Output:** A row-parity report and schedule fingerprint.
- **Invalidating result:** Any missing or duplicate cell, unequal required
  field, policy error, or silent row deletion.
- **Does not support:** Schedule parity establishes an attempted match, not
  repeatable execution or semantic alignment of random events.
- **human_verified:** PENDING — a human author must confirm the required pairing
  fields and complete row inventory; this remains a submission blocker until
  signed.

## M04 — Identical-arm recorded-trace test (A/A adaptation)

- **Problem solved:** Detects execution differences hidden by identical terminal
  outcomes.
- **Why needed here:** Two action paths may reach the same winner, so outcome
  equality alone is too coarse for a repeatability gate.
- **Analysis unit:** One artifact–seed-condition unit compared across separately
  launched, byte-identical arms.
- **Assumptions:** Serialization is canonical; the digest and byte-count
  comparison is correct; the declared projection contains every observable
  field required by the admitted claim; collision risk is negligible for the
  chosen digest.
- **Implementation:** Stage 4 compares, in increasing strength, terminal outcome,
  errors, decision count, and the SHA-256 digest plus byte count of the ordered
  public-observation-hash, acting-side, selected-action, and terminal stream.
- **Output:** Field-level parity, trace-projection parity, and profile-specific
  mismatch diagnostics supported by the retained evidence.
- **Invalidating result:** One required mismatch on the exercised schedule, a
  noncanonical serializer, or an omitted field that is material to the claim.
- **Does not support:** A pass does not establish equality of raw observations,
  hidden state, opaque search state, semantic random events, or cross-arm
  counterfactual coupling. “Complete” means complete only within the declared
  recorded projection.
- **human_verified:** PENDING — a human author must be able to name every
  included and excluded projection field and defend the serializer; this
  remains a submission blocker until signed.

## M05 — Repeat, worker, and enqueue-context testing

- **Problem solved:** Tests whether the same artifact and seed condition repeats
  under prespecified serial, worker-count, enqueue-order, and pool-lifecycle
  contexts.
- **Why needed here:** Process-local state, queue history, concurrency, and
  clock-bounded computation can change execution despite an unchanged schedule.
- **Analysis unit:** One seed-condition cluster containing all required execution
  profiles.
- **Assumptions:** Profiles are launched as declared; all profiles in the cluster
  share the intended scheduled inputs; comparisons retain the cluster intact.
- **Implementation:** Stage 5 runs fresh serial repeats and fixed worker/enqueue
  profiles, then compares the declared trace projection within each cluster.
- **Output:** Cluster-level parity indicators and profile-specific diagnostics.
- **Invalidating result:** Any required profile mismatch, missing profile, or
  evidence that a nominally fresh process or pool was reused contrary to the
  protocol.
- **Does not support:** Profiles are fixed execution contexts, not random samples
  of machines or loads. Repeats inside one seed cluster are dependent diagnostic
  measurements, not independent observations.
- **human_verified:** PENDING — a human author must confirm profile launch
  semantics, cluster membership, and the dependence interpretation; this
  remains a submission blocker until signed.

## M06 — Stochastic-source audit

- **Problem solved:** Inventories bounded, statically visible Python patterns
  that may warrant dynamic repeat/worker testing: explicit randomness,
  clocks/deadlines, process or thread concurrency APIs, module/global state, and
  native pointer or handle patterns.
- **Why needed here:** A trace mismatch establishes non-repeatability for its
  recorded projection but does not reveal which accessible source patterns may
  merit follow-up. The scan supplies a reproducible candidate-pattern inventory
  without treating those patterns as causes.
- **Analysis unit:** One `.py` or `.pyi` source file inside each of 11 frozen
  package trees, aggregated by package tree and one of five declared pattern
  categories. Two engine binaries are separate identity units only.
- **Assumptions:** The 11 tree digests identify the intended package bytes; the
  decoded Python source set is complete within the declared extensions; AST and
  bounded qualified-name/identifier patterns are applied as implemented; scan
  scope and parse outcomes are reported.
- **Implementation:** Stage 6 applies a Python AST plus bounded pattern scan to
  the 11 package trees for explicit RNG interfaces, clock/deadline interfaces,
  concurrency APIs, module/global state, and native pointer/handle patterns.
  The two engine binaries are SHA-256 checked, but their source internals are
  unavailable and explicitly recorded as `not_assessed`.
- **Output:** Per-tree and aggregate hit counts, generalized pattern counts,
  source-set and canonical-location fingerprints, parse counts, artifact
  digests, and explicit not-assessed records for both engine binaries.
- **Invalidating result:** A tree or binary hash mismatch, missing inventory
  item, unreported parse failure, changed category/pattern implementation, or a
  scope statement inconsistent with the scanned Python files.
- **Does not support:** The scan does not execute code, inspect engine-binary
  internals, observe runtime scheduling, prove that a pattern executed or caused
  a mismatch, or prove determinism from an empty category. It does not cover
  hardware-sensitive numerics or external state.
- **human_verified:** PENDING — a human author must confirm the scanned source
  scope and explain why hits are candidates rather than causes; this remains a
  submission blocker until signed.

## M07 — Semantic event-alignment check

- **Problem solved:** Determines whether shared modeled exogenous events receive
  the same random quantity after different policies take different paths.
- **Why needed here:** Within-arm repetition can pass while stateful draw
  consumption shifts cross-arm random-event assignments.
- **Analysis unit:** One shared semantic event identifier within a declared event
  ontology, compared across arms.
- **Assumptions:** Event identifiers are stable across policy paths; the ontology
  covers the events relevant to the claim; marginal distributions and intended
  dependence are preserved; logged values correspond to those events.
- **Implementation:** Stage 7 compares event identifiers and values, or uses
  validated event-specific streams/event-keyed randomness. The synthetic suite
  supplies such an oracle for five logged shared events.
- **Output:** Covered event classes, aligned/misaligned event counts, and a scoped
  alignment decision.
- **Invalidating result:** A shared event receives unequal values, identifiers
  are path dependent, a relevant class is absent, or the keying construction
  changes the intended distribution.
- **Does not support:** The restricted engine exposes neither semantic event
  identifiers nor event-keyed streams, so it cannot establish this level. A
  synthetic pass is confined to the fixture’s ontology and distribution.
- **human_verified:** PENDING — a human author must confirm the ontology and
  dependence assumptions for any event-alignment claim and acknowledge that the
  restricted case does not pass this method; this remains a submission blocker
  until signed.

## M08 — Frozen claim map and executable admission formalization

- **Problem solved:** Prevents favorable outcomes from being used to waive
  missing validation evidence.
- **Why needed here:** Without a frozen consequence, a failed trace gate could be
  followed by selective exclusions or stronger post hoc wording.
- **Analysis unit:** One proposed statistical claim and the complete set of gates
  required for its prespecified estimand.
- **Assumptions:** The experiment-specific map, protocol identifier, sample
  sizes, required strata, descriptive contrast, and failure actions are recorded
  in a Git commit that precedes the retained result artifacts. Git history does
  not prove when a human inspected uncommitted files. The generic JSON rule
  bundle is a post-acquisition executable formalization and must remain
  subordinate to those frozen rules. Its evidence-bound `admit` path derives
  gate states from validated evidence; a separate explicitly trusted-state
  classifier accepts caller-supplied states for formal conformance checks. Rule
  evaluation may receive only gate states and the declared trace projection,
  never outcomes, estimates, reweighting quantiles, p-values, or result
  favorability.
- **Implementation:** Stage 8 admits bounded wording, downgrades interpretation,
  or suppresses the comparison; schema, commit, sample-size, stratum, and
  nonfinite-value checks fail closed. The executable property suite replaces all
  result values, weakens each prerequisite, inserts favorable results after
  failures, removes projection scope, repeats identical evaluations, supplies
  unknown/malformed/contradictory states, exhaustively enumerates all six states
  across seven gates, and rejects rule/schema/class tampering.
- **Output:** A deterministic admission status, ordered permitted claim class,
  permitted and forbidden wording, contrast, analysis unit, descriptive
  reweighting rule,
  first blocking gate, and repair action. The substantive ordering is no
  stronger than `schedule_matched < execution_repeatable < event_aligned`;
  weaker descriptive and suppression classes sit below that sequence.
- **Invalidating result:** Protocol drift, an unsatisfied required gate, an
  outcome-dependent change, a missing stratum, property-test or tamper-test
  failure, or any executable decision inconsistent with the frozen rule.
- **Does not support:** Admission is not proof that assumptions are universally
  true or that future executions will pass. It cannot turn a schedule-matched
  estimate into inferential pairing, a population effect, or a fully
  event-aligned counterfactual effect. The later executable bundle is not
  evidence that its generic taxonomy was prospectively frozen.
- **human_verified:** PENDING — a human author must confirm the prospective
  experiment-specific authority, post-acquisition formalization provenance,
  result-independent input projection, and all seven claimed safety properties;
  this remains a submission blocker until signed.

## M09 — Trace-disagreement proportion

- **Problem solved:** Summarizes how many exercised seed-condition clusters show
  any trace-projection disagreement across their required profiles.
- **Why needed here:** Counting profile pairs would treat dependent comparisons
  inside a seed condition as separate observations and obscure the fail-on-any-
  mismatch rule.
- **Analysis unit:** One seed-condition cluster containing all prescribed
  profiles.
- **Assumptions:** Cluster membership and profile set are frozen; equality is
  computed on the same canonical `(digest, byte_count)` projection record;
  missing profiles fail rather than disappear.
- **Implementation:** Equation (1) assigns an indicator of one when more than one
  required profile `(digest, byte_count)` tuple occurs in a cluster and averages
  over complete clusters. A byte-count-only difference is a disagreement.
- **Output:** A unitless disagreement proportion plus exact counts.
- **Invalidating result:** A changed denominator, omitted profile, digest or byte
  count from a different schema, or a cluster split into pseudo-independent
  pairwise rows.
- **Does not support:** The proportion is not prevalence in a population of
  agents, hardware, or workloads and does not identify the cause of disagreement.
- **human_verified:** PENDING — a human author must confirm the cluster
  denominator and complete profile set; this remains a submission blocker until
  signed.

## M10 — Historical available-record repeated-control audit

- **Problem solved:** Tests the strongest repeatability projection supported by
  historical rows that lack the current trace schema.
- **Why needed here:** Retrospective data cannot honestly be relabeled as having
  passed a trace gate it never recorded.
- **Analysis unit:** One historical opponent–order–seed condition compared across
  three separately executed control arms; 2,800 units total.
- **Assumptions:** Surviving rows are complete for the declared historical
  projection; the three control columns refer to the same schedule unit; equality
  is recomputed without dropping mismatches.
- **Implementation:** The audit compares the three repeated-control win/draw
  records, then extends that available projection with decision count.
- **Output:** 210 of 2,800 available-outcome (win/draw) mismatches and 458 of
  2,800 available-record mismatches after decision count is added, with the
  planned historical factorial suppressed.
- **Invalidating result:** Schedule or row-identity failure, inconsistent
  recomputation, missing comparison columns, or a claim that the historical
  projection is a complete trace.
- **Does not support:** The audit does not isolate wall-clock timing as the unique
  cause, and a post hoc subset of agreeing contexts does not rescue the frozen
  historical estimand.
- **human_verified:** PENDING — a human author must confirm the available-record
  projection, all retained historical units, and the suppression consequence;
  this remains a submission blocker until signed.

## M11 — Prospective deterministic trace preflight

- **Problem solved:** Tests whether fixed artifacts repeat on the complete
  declared trace projection across the serial and worker contexts required
  before factorial acquisition.
- **Why needed here:** Historical available-record failures made a prospective,
  trace-bearing gate necessary before collecting the bounded demonstration.
- **Analysis unit:** One arm–seed-condition unit containing three execution
  trajectories.
- **Assumptions:** Four arms, five newly frozen audit-informed deterministic
  contexts, both actual orders, 25 seeds per order, two fresh serial profiles,
  and one eight-worker profile are complete and correctly labeled. The five
  contexts are a new protocol target, not a rescue subset of the historical
  seven-opponent target.
- **Implementation:** The analyzer compares digest and byte count of the public-
  observation-hash/action/terminal projection, outcome, errors, and decision
  count across 1,000 units and 3,000 executions.
- **Output:** Zero mismatches and qualification of factorial acquisition for the
  exact preflight scope.
- **Invalidating result:** One mismatch, missing job/profile, artifact or protocol
  drift, or an altered schedule.
- **Does not support:** The preflight and factorial use different frozen seed
  ranges, and candidate factorial rows contain no trace digests. Applying the
  qualification result to those later rows is a bounded transfer assumption
  about the same identified artifacts and contexts, not direct factorial-row
  trace evidence. The pass also does not generalize to untested hardware, loads,
  timed-search contexts, hidden state, or cross-arm semantic event alignment.
- **human_verified:** PENDING — a human author must confirm the frozen preflight
  inventory and bounded meaning of zero mismatches; this remains a submission
  blocker until signed.

## M12 — Timed-search stress test and whole-cluster empirical reweighting

- **Problem solved:** Exercises fixed timed-search contexts under serial/parallel
  and forward/reverse enqueue profiles and describes realized trace-disagreement
  sensitivity under empirical reweighting.
- **Why needed here:** Timed-search contexts were retained as diagnostics instead
  of being silently removed after historical mismatches.
- **Analysis unit:** One opponent–order–seed-condition cluster containing four
  execution profiles; 200 clusters and 800 executions total.
- **Assumptions:** Each cluster contains all four profiles; the 200 realized
  clusters are a fixed engineering battery; profiles are never reweighted
  independently. The frozen pooled procedure treats all 200 clusters as one
  empirical distribution and can vary the context composition. The
  fixed-composition calculation is an explicitly post-acquisition,
  source-driven sensitivity that reweights within each of four fixed strata.
- **Implementation:** The diagnostic records cluster indicators and uses 100,000
  whole-cluster reweighting draws under the frozen pooled analysis seed. The
  fixed-composition sensitivity preserves 50 clusters per stratum, reweights
  within stratum, and averages the four stratum means equally.
- **Output:** 99/200 trace-projection disagreement clusters (49.5%); frozen
  pooled 2.5th and 97.5th reweighting percentiles 42.5%–56.5%; exact stratum
  counts 44/50 and 48/50 for Timed-search A/orders 1 and 2 and 4/50 and 3/50
  for Timed-search B/orders 1 and 2; post-acquisition fixed-composition
  sensitivity percentiles 46%–53%; 47 outcome disagreements, 93 decision-count
  disagreements, and zero error-record disagreements.
- **Invalidating result:** Missing profile rows, changed clustering or frozen
  reweighting seed, noncanonical traces, or treating profiles within a cluster
  as independent.
- **Does not support:** Neither percentile range is a population confidence
  interval. The context-heterogeneous association does not prove wall-clock
  timing, process state, or any other mechanism uniquely caused every
  difference.
- **human_verified:** PENDING — a human author must confirm the frozen pooled
  procedure, the post-acquisition label on the fixed-composition sensitivity,
  the fixed-battery interpretation, and noncausal wording; this remains a
  submission blocker until signed.

## M13 — Binary schedule-indexed descriptive difference

- **Problem solved:** Gives a directionally explicit descriptive unit-level
  contrast between intervention and control outcomes.
- **Why needed here:** The factorial uses the same frozen schedule unit across
  four cells; arm-level means alone would discard the paired row identity.
- **Analysis unit:** One schedule-indexed unit within an opponent-by-order
  stratum.
- **Assumptions:** Binary win is coded 1 and nonwin 0; intervention minus control
  is the frozen direction; both outcomes belong to the same unit.
- **Implementation:** Equation (2) computes `intervention − control`, yielding
  −1, 0, or 1.
- **Output:** A unitless paired difference whose mean is reported in percentage
  points.
- **Invalidating result:** Reversed arm labels, unmatched rows, inconsistent
  outcome coding, or missing outcomes.
- **Does not support:** A paired difference does not itself establish
  inferential exchangeability or independence, a sampling distribution,
  repeatability, semantic event alignment, a causal mechanism, or external
  generalizability.
- **human_verified:** PENDING — a human author must confirm the arm labels,
  matched-unit identity, and intervention-minus-control direction; this remains
  a submission blocker until signed.

## M14 — Stratified paired-unit empirical reweighting

- **Problem solved:** Describes sensitivity of fixed-battery factorial contrasts
  to reweighting schedule-indexed paired units while retaining four-cell outcomes
  and equal weighting of the ten frozen opponent-by-order strata.
- **Why needed here:** Reweighting arms separately would break row identity, and pooling
  without the frozen stratum rule would change the estimand.
- **Analysis unit:** One paired unit identifier within one of ten fixed strata.
- **Assumptions:** The realized within-stratum empirical distributions are the
  only reweighting objects; all cells for an identifier remain together; 100,000
  draws, the analysis seed, and percentile rule are frozen. No probability
  sample, randomized assignment, or defended stochastic population model
  supplies an inferential reference distribution.
- **Implementation:** Equation (3) samples whole unit identifiers with
  replacement within each stratum, computes each stratum mean, weights the ten
  strata equally, and recomputes contrasts.
- **Output:** The 2.5th and 97.5th percentiles of empirical reweighting
  distributions in unitless scale, displayed in percentage points.
- **Invalidating result:** Separate arm reweighting, cross-stratum movement,
  changed draw count/seed, missing cells, or a different weighting rule.
- **Does not support:** These quantiles are not confidence intervals or
  hypothesis tests, do not cover a superpopulation of new seeds, opponents,
  hardware, training runs, or execution contexts, and are not equivalence
  tests.
- **human_verified:** PENDING — a human author must confirm the reweighting unit,
  equal stratum weights, and fixed-battery interpretation; this remains a
  submission blocker until signed.

## M15 — Fixed-battery two-by-two factorial contrasts

- **Problem solved:** Separates the frozen four-cell comparison into descriptive
  total, average representation, average training, and interaction contrasts.
- **Why needed here:** Four independently named cell rates do not encode the
  intended intervention directions or interaction algebra.
- **Analysis unit:** One common fixed-schedule unit per cell, stratified by five
  deterministic contexts and two actual orders; 2,000 units per cell.
- **Assumptions:** Cell mapping `(00,10,01,11)` is correct; signs were frozen;
  schedules and outcomes are complete; the repeated-control available-record
  gate is satisfied; the preflight used a different seed range; candidate
  factorial rows have no trace digests; the preflight-to-factorial transfer is
  a bounded qualification assumption rather than trace evidence on these rows.
- **Implementation:** Equation (4) computes four prespecified linear contrasts
  on the fixed battery. The stratified paired-unit procedure supplies only an
  empirical reweighting sensitivity; no manuscript hypothesis test is admitted.
- **Output:** Descriptive total +0.55 percentage points with reweighting
  percentiles [−2.05,+3.15], representation +0.95 [−1.08,+3.00], training
  −0.40 [−2.03,+1.25], and interaction +1.30 [−1.85,+4.45].
- **Invalidating result:** Wrong cell mapping/sign, missing unit, failed
  repeated-control gate, schedule drift, or treating absent factorial trace
  digests as zero mismatches.
- **Does not support:** Reweighting quantiles spanning zero do not constitute a
  null-hypothesis result and do not prove equality or equivalence. The fixed
  battery does not support population inference, policy superiority, a
  mechanism, inferential pairing, or full CRN coupling.
- **human_verified:** PENDING — a human author must confirm cell labels, signs,
  fixed-battery interpretation, bounded transfer assumption, and descriptive
  rather than inferential wording; this remains a submission blocker until
  signed.

## M16 — Synthetic conformance suite

- **Problem solved:** Supplies an executable oracle for logical failure modes
  without requiring the restricted engine.
- **Why needed here:** External readers cannot replay restricted trajectories,
  and several non-implications are easiest to verify in controlled fixtures.
- **Analysis unit:** One fixed synthetic mode evaluated through the eight-stage
  evidence/admission map.
- **Assumptions:** Injected modes implement their declared mechanisms; expected
  outputs, schema, and manifest are unchanged; event-alignment claims stay within
  the logged ontology.
- **Implementation:** Five modes cover clean deterministic behavior, stateful draw
  shift, injected clock budget, injected process state, and seed conversion; an
  event-keyed construction is checked against five logged shared events.
- **Output:** Per-level JSON/CSV evidence, schema validation, manifest checks, and
  admission decisions.
- **Invalidating result:** Fixture/schema drift, verification or mutation-test
  failure, an unexpected admission result, or a changed manifest.
- **Does not support:** Designed fixtures do not estimate failure prevalence in
  real systems and do not establish the completeness of an external engine’s
  event ontology.
- **human_verified:** PENDING — a human author must confirm the fixture oracle,
  expected failure direction, ontology scope, and tamper checks; this remains a
  submission blocker until signed.

## M17 — AI-assisted research workflow

- **Problem solved:** Makes substantive machine assistance and its verification
  auditable rather than treating it as invisible authorship.
- **Why needed here:** AI assistance included reasoning, literature synthesis,
  code, debugging, orchestration, statistics, deterministic visualization,
  drafting, release assembly, and adversarial review.
- **Analysis unit:** One recorded AI-assisted task or output in
  `supplement/AI_USE_LOG.csv`.
- **Assumptions:** The activity log is complete; exact tool/model information is
  reported only when exposed; a human checks every accepted scientific output.
- **Implementation:** Tasks, human instructions, outputs, verification, and
  acceptance status are logged; hashes, schemas, reaggregation, tests, primary
  sources, compilation, and rendered pages are used as appropriate.
- **Output:** A machine-readable activity record and manuscript disclosure.
- **Invalidating result:** Missing substantive use, invented model/version detail,
  unverified accepted output, confidentiality/rights breach, or listing an AI
  system as an author.
- **Does not support:** AI assistance transfers no authorship, ownership,
  submission authority, or responsibility away from the human authors.
- **human_verified:** PENDING — a human author must confirm the activity log is
  complete, every accepted scientific output was independently checked, and no
  unexposed model metadata was inferred; this remains a submission blocker until
  signed.

## Audit disposition

The methods are explainable within their bounded purposes, but human
verification remains required. In particular, the corresponding author must
confirm the completeness of the AI-use history, understand every assumption,
and approve the distinction between a complete **recorded projection** and an
unobservable complete engine trace. Rights, license, DOI, and human metadata
are outside these method checks and remain submission blockers.
