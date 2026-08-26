# Claim-Specific Validation Framework (CSVF) v1.0.0-prospective

**Frozen:** 2026-08-26
**Central question:** *What exact scientific claim does the evaluator want to make?*

> **Core principle.** Evidence requirements attach to the inferential objective of the claim, not to a universal cumulative ladder. A researcher may legitimately satisfy Branch B without satisfying Branches C or E whenever the statistical design alone supports the paired inference.

> **Superseded anti-pattern.** The superseded cumulative 'validity ladder' treated deterministic replay and event alignment as prerequisites for every paired claim. This over-requires evidence and suppresses valid analyses.

---

## The five branches

### BRANCH_A — Matched Descriptive Comparison

- **Question:** Do these recorded runs share the declared schedule?
- **Example claim:** “These recorded runs shared declared schedule fields.”
- **Description:** A descriptive claim that two or more recorded runs used the same declared schedule (seed value, context/opponent, row identity). No statistical or causal inference is made; no replay is implied.
- **Required evidence:**
  - `artifact_identity` — Each recorded run carries a verifiable artifact identifier (code version, model/binary hash, configuration hash).
  - `schedule_identity` — Declared schedule fields (seed, opponent/context condition, row identifiers) match across compared runs.
  - `complete_rows` — All scheduled rows are present in the analysis denominator; missing rows are detected, not silently dropped.
  - `correct_grouping` — Runs are grouped into analysis units by the declared grouping key (e.g., seed-condition cluster).
- **Explicitly NOT required:** exact_replay_of_execution; identical_trace_projection; event_alignment
- **Permitted wording:**
  - “the runs shared the declared seed value and schedule fields”
  - “runs were matched on recorded schedule fields”
  - “the schedule was complete for {n}/{n} scheduled rows”
- **Forbidden wording:**
  - ✗ “the runs are replicates of one another”
  - ✗ “the executions were identical”
  - ✗ “paired estimates are valid because seeds match”

### BRANCH_B — Statistically Paired Inference

- **Question:** Does the paired estimator's reference distribution have a justified basis?
- **Example claim:** “The paired estimator and uncertainty procedure have a justified reference distribution.”
- **Description:** A claim that a paired difference estimator and its uncertainty have a valid statistical justification via randomized assignment, probability sampling, repeated-measures design, hierarchical modeling, or a defended joint stochastic model.
- **Required evidence:**
  - at least one of: `[randomized_assignment`, `probability_sampling`, `repeated_measures_design`, `hierarchical_model`, `defended_joint_stochastic_model]`
  - `correct_grouping` — Runs are grouped into analysis units by the declared grouping key (e.g., seed-condition cluster).
  - `complete_rows` — All scheduled rows are present in the analysis denominator; missing rows are detected, not silently dropped.
- **Explicitly NOT required:** exact_replay_of_execution; event_alignment
- **Permitted wording:**
  - “under the randomized/repeated-measures design, the paired difference estimator has a justified reference distribution”
  - “pairing is justified by the declared assignment mechanism”
  - “uncertainty was obtained by the prespecified procedure under assumption X”
- **Forbidden wording:**
  - ✗ “seeds were shared, therefore pairing is exact”
  - ✗ “paired inference requires no assumptions because seeds match”
  - ✗ “the interval is an exact confidence interval (without justified sampling interpretation)”

### BRANCH_C — Deterministic Replay

- **Question:** Does repeating the same artifact reproduce the declared trace projection?
- **Example claim:** “Repeating the same artifact under declared conditions reproduces the declared trace projection exactly.”
- **Description:** A claim about execution repeatability of one artifact: repeated executions under declared conditions produce byte-identical declared trace projections across processes, workers, and contexts.
- **Required evidence:**
  - `within_artifact_repeated_executions` — The same artifact was executed multiple times under declared identical conditions.
  - `declared_trace_projection` — A declared, finite projection of the execution trace (fields, ordering, comparison rule) is specified before comparison.
  - `context_testing` — Execution was repeated across process instances, worker reuse states, and execution contexts to expose nondeterminism.
  - `exact_repeatability_criteria` — An exact equality criterion on the declared trace projection is declared before testing.
- **Explicitly NOT required:** event_alignment; cross_arm_coupling
- **Permitted wording:**
  - “K/K repeated executions reproduced the declared projection of the trace exactly”
  - “execution is repeatable under the declared conditions and projection scope”
  - “no mismatch was found in the declared projection across tested contexts”
- **Forbidden wording:**
  - ✗ “the system is deterministic (unscoped)”
  - ✗ “replay holds, therefore cross-arm comparisons are aligned”
  - ✗ “any trace field matches (beyond the declared projection)”

### BRANCH_D — Common-Random-Number Variance Reduction

- **Question:** Does shared randomness create a valid coupling that improves comparison precision?
- **Example claim:** “Shared randomness creates a valid coupling that improves comparison precision.”
- **Description:** A claim that a CRN-style coupling between two configurations preserves marginals, induces measurable positive covariance, and reduces variance of the paired difference relative to independent sampling on the same replication budget.
- **Required evidence:**
  - `specified_coupling_construction` — The common-random-number coupling construction is fully specified (which streams, substreams, draws are shared).
  - `preserved_marginals` — The coupling preserves each arm's marginal distributions (verified empirically or argued structurally).
  - `measured_covariance` — Cross-arm covariance induced by the coupling is estimated from replicated pairs.
  - `measured_variance_reduction` — Variance of the paired difference is compared against independent-sampling variance on the same budget.
  - `synchronization_assumptions` — Assumptions about stream synchronization across arms are declared (and tested where possible).
- **Explicitly NOT required:** within_artifact_exact_replay; semantic_event_equality
- **Permitted wording:**
  - “the declared coupling reduced variance of the paired difference by factor r versus independent sampling”
  - “marginal distributions were preserved under the coupling (verified by test T)”
  - “cross-arm covariance was positive and synchronized as assumed”
- **Forbidden wording:**
  - ✗ “CRN applies because seeds match (without marginal preservation and variance evidence)”
  - ✗ “variance reduction generalizes beyond the measured scenario”
  - ✗ “repeatability alone demonstrates coupling validity”

### BRANCH_E — Event-Aligned Counterfactual or Mechanistic Claim

- **Question:** Did corresponding semantic events receive the same random quantities across divergent arms?
- **Example claim:** “Corresponding exogenous events received the same random quantities across divergent policies or algorithms.”
- **Description:** A mechanistic/counterfactual claim at event granularity: semantic events identified by a stable ontology received identical random quantities across arms whose behavior diverged, enabling event-level attribution.
- **Required evidence:**
  - `stable_event_identifiers` — Semantic events carry identifiers that are stable across policies/algorithms (declared event ontology).
  - `event_value_records` — Random quantities delivered at each semantic event are recorded with their event keys.
  - `event_keyed_streams_or_validated_equivalent` — Event-keyed random streams exist, or an equivalent validated construction is documented.
  - `declared_event_ontology` — The event ontology (what counts as an event, its granularity) is declared before acquisition.
  - `dependence_assumptions` — Assumptions under which event-level equality implies distribution-level coupling validity are stated.
- **Explicitly NOT required:** within_artifact_exact_replay; trace_projection_equality_everywhere
- **Permitted wording:**
  - “for e/e matched event keys, recorded random quantities were identical across arms”
  - “event-level equality held under the declared ontology and keying construction”
  - “counterfactual attribution is supported at event granularity under the declared dependence assumptions”
- **Forbidden wording:**
  - ✗ “events were aligned because schedules matched”
  - ✗ “event alignment holds without a declared ontology”
  - ✗ “post-hoc event matching justifies counterfactual claims”

## Independence of branches

| Satisfied | Imposes requirement on other branches? |
|---|---|
| B (statistical pairing) | None from C or E; design features justify the reference distribution |
| C (replay) | None; replay says nothing about cross-arm coupling |
| D (CRN) | None from C; marginal preservation + covariance evidence suffices |
| E (event alignment) | None from C; scoped to declared ontology |
| A (descriptive) | None; never upgrades to statistical language |

## Decision flow (summary)

- **Route.** Classify the evaluator's intended claim by inferential objective into exactly one branch A-E. If classification fails or is ambiguous after documented adjudication -> D_FAIL_CLOSED.
- **N_A** (`BRANCH_A`): check `artifact_identity`, `schedule_identity`, `complete_rows`, `correct_grouping`; pass → D_ADMIT_DESCRIPTIVE; fail → D_SUPPRESS_OR_DOWNGRADE
- **N_B** (`BRANCH_B`): check `B_design_justification`, `correct_grouping`, `complete_rows`; pass → D_ADMIT_STATISTICAL; fail → D_SUPPRESS_OR_DOWNGRADE
- **N_C** (`BRANCH_C`): check `within_artifact_repeated_executions`, `declared_trace_projection`, `context_testing`, `exact_repeatability_criteria`; pass → D_ADMIT_REPLAY; fail → D_SUPPRESS_OR_DOWNGRADE
- **N_D** (`BRANCH_D`): check `specified_coupling_construction`, `preserved_marginals`, `measured_covariance`, `measured_variance_reduction`, `synchronization_assumptions`; pass → D_ADMIT_CRN; fail → D_SUPPRESS_OR_DOWNGRADE
- **N_E** (`BRANCH_E`): check `stable_event_identifiers`, `event_value_records`, `event_keyed_streams_or_validated_equivalent`, `declared_event_ontology`, `dependence_assumptions`; pass → D_ADMIT_EVENT; fail → D_SUPPRESS_OR_DOWNGRADE
- **D_ADMIT_DESCRIPTIVE** → ADMIT_AS_DESCRIPTIVE
- **D_ADMIT_STATISTICAL** → ADMIT_AS_STATISTICAL_PAIRED
- **D_ADMIT_REPLAY** → ADMIT_AS_REPLAY_SCOPED
- **D_ADMIT_CRN** → ADMIT_AS_CRN_EVIDENCED
- **D_ADMIT_EVENT** → ADMIT_AS_EVENT_ALIGNED
- **D_SUPPRESS_OR_DOWNGRADE** → SUPPRESS_CLAIM_OR_DOWNGRADE_TO_SUPPORTED_BRANCH
- **D_FAIL_CLOSED** → FAIL_CLOSED_UNCLASSIFIABLE

## Implementation invariants (tested, not theorized)

- result exclusion: classifier inputs exclude final outcome values of the study being validated
- monotonicity: removing any required evidence can never upgrade an admission decision
- fail closed: unknown or ambiguous state yields FAIL_CLOSED_UNCLASSIFIABLE, never admission
- projection scoping: replay admission is scoped to the declared trace projection only
- deterministic classifier: identical evidence inputs yield identical decisions
- branch independence: satisfaction of any branch imposes no requirement from another branch

---

*This document and the four JSON files (`claim_classes.json`, `evidence_requirements.json`, `permitted_wording.json`, `decision_graph.json`) are generated from the single canonical source `canonical_framework.py`. Regenerate with `python3 canonical_framework.py`.*
