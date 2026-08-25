# Admission decision table

Generated from `protocol/admission_rules.json` and `protocol/claim_classes.json`; do not edit this table independently.

Formalization status: `post_acquisition_executable_formalization`. This executable map was created after acquisition. The frozen experiment-specific protocol—including its finite-population paired-bootstrap intervals and secondary exact McNemar inference—remains authoritative. The current Level-6 descriptive-only restriction is a later conservative reporting rule, not frozen provenance or evidence of prospective validation; future adopters must freeze it before acquisition.

## Interfaces and trust boundary

`AdmissionProtocol.evaluate_trusted_states` is a pure classifier for explicitly trusted, prevalidated gate states. It does not inspect or authenticate scientific records and its decision reports `caller_asserted_prevalidated_states`. The public `admit` command accepts the separate closed file-bound record schema, checks its hash and declared support bytes, derives every gate state that the included records can establish, and reports file-verification certificates. Roles, profile provenance, and trace semantics remain caller assertions. The included bundle deliberately marks the source audit unavailable and event alignment not applicable; it cannot manufacture stronger evidence.

## Ordered evidence gates

| Level | Gate | Question | Evidence required when blocked |
|---:|---|---|---|
| 1 | `artifact_identity` | Are every compared artifact and execution configuration unambiguously identified? | Verified immutable identities for both agent artifacts, engine, configuration, runner, and protocol source. |
| 2 | `seed_namespace_integrity` | Are requested and engine-boundary seeds recorded and collision-free under the declared conversion? | Recorded requested seeds, conversion rule, exact values passed at the engine boundary, and a collision check. |
| 3 | `schedule_parity` | Do all declared schedule fields match row by row across arms? | Row-level equality of declared seed, condition, order, seat, initial-state controls, and other frozen schedule fields across arms. |
| 4 | `identical_arm_record_parity` | Do required identical-arm control records agree on every prespecified field? | Complete identical-arm record comparisons for all required controls and fields under the frozen acquisition rule. |
| 5 | `repeat_and_worker_parity` | Is each arm repeatable across every prespecified execution profile for the declared trace projection? | Within-arm equality across every required fresh-process, repeat, worker-count, and enqueue-order profile for the declared trace projection. |
| 6 | `stochastic_source_audit` | Has the prespecified stochastic-source audit been completed without an unresolved invalidator? | A bounded audit of random streams, clocks, process state, concurrency, external services, and other prespecified stochastic or execution-dependent sources. |
| 7 | `cross_arm_event_alignment` | Are shared exogenous events aligned across arms within a declared event ontology? | Cross-arm alignment of shared exogenous events under a declared semantic event ontology and alignment procedure. |

## Complete rule partition

A pass prefix is the number of consecutive `pass` states from Level 1. After the first non-pass state, any later `pass` is contradictory and suppresses the claim.

| Pass prefix | Permitted class | Decision | Required wording | Estimand | Analysis unit | Uncertainty | Failure action |
|---:|---|---|---|---|---|---|---|
| 0 | `suppress` | suppress | No comparative or repeatability claim is admitted from this evidence record. | None admitted from this evidence record. | None admitted. | None; do not compute or report a comparative inferential procedure as admitted. | Stop comparative interpretation, preserve the invalid record, repair the evidence chain, and rerun admission without inspecting result favorability. |
| 1--2 | `descriptive_unmatched` | downgrade | The arms may be described separately; this evidence does not admit a schedule-matched or paired comparison. | Arm-specific empirical summaries with no seed-matched or paired interpretation. | Separate arm-specific observation; no cross-arm pair is asserted. | Arm-wise uncertainty that preserves the acquisition structure; no paired procedure. | Report arms separately or redesign the seed boundary and schedule; suppress every paired contrast. |
| 3--4 | `schedule_matched` | downgrade | The declared schedule fields matched across arms; schedule matching alone does not establish repeatable execution, paired randomness, or event alignment. | A descriptive contrast indexed by common recorded schedule fields, without execution-pair interpretation. | Recorded schedule row within each arm; no execution-level pair is asserted. | Use an unpaired or purely descriptive procedure justified independently of shared execution; do not use a paired procedure. | Suppress planned paired contrasts; repair the first blocked parity or repeatability gate and reacquire if required by the frozen protocol. |
| 5 | `execution_repeatable` | downgrade | Execution was repeatable across the declared within-arm profiles only for recorded trace projection {projection_id}@{projection_version} with fields [{projection_fields}]; this does not establish cross-arm event alignment or admit a paired outcome contrast. | Exact-repeatability diagnostics for the declared recorded trace projection on the exercised schedule. | Seed-condition cluster containing all prespecified within-arm execution profiles. | Report exact mismatch indicators or cluster-level disagreement summaries for the exercised schedule; no paired outcome procedure. | Do not use paired outcome inference; complete and pass the stochastic-source audit before seeking bounded seed-matched admission. |
| 6 | `seed_matched_bounded` | admit | Within the frozen schedule and validated execution contexts, a fixed-battery descriptive seed-indexed contrast is admitted with empirical reweighting sensitivity only; inferential pairing, confidence intervals, hypothesis tests, population effects, and semantic event alignment are not established. Repeatability is asserted only for recorded trace projection {projection_id}@{projection_version} with fields [{projection_fields}]. | A fixed-battery descriptive seed-indexed contrast under the current post-acquisition conservative reporting restriction; this taxonomy is not the frozen analysis plan. | Seed-indexed unit within each fixed schedule stratum, with repeated profiles retained as one cluster where applicable. | Empirical whole-unit reweighting of the declared fixed battery as descriptive sensitivity only; not a confidence interval, hypothesis test, or population uncertainty statement. | Use only fixed-battery descriptive wording and empirical reweighting sensitivity; suppress the contrast if any experiment-specific invalidator or required gate fails. |
| 7 | `event_aligned` | admit | Within the declared event ontology, shared exogenous events were aligned and a fixed-battery descriptive contrast is admitted; this does not by itself establish inferential pairing, a confidence interval, a hypothesis test, or a population effect. Repeatability is asserted only for recorded trace projection {projection_id}@{projection_version} with fields [{projection_fields}]. | A fixed-battery descriptive event-aligned contrast within the declared schedule and semantic event ontology. | Event-aligned trajectory pair within the declared semantic ontology and schedule stratum. | Empirical reweighting of the declared fixed battery may be reported as descriptive sensitivity; it is not a confidence interval, hypothesis test, or population uncertainty statement. | Preserve the ontology, event keys, projection, and declared analysis unit; any drift requires a new admission decision, and inferential pairing requires a separate justified design. |

## Fail-closed cases

Missing gates, extra gates, unknown states, malformed projections, and unknown schema or protocol identifiers produce `suppress`. Explicit `malformed` or `contradictory` states also produce `suppress`. `fail`, `unavailable`, and `not_applicable` never count as a passed prerequisite.

The rule matcher receives only gate states and the declared trace projection. Result data—including effect estimates, p-values, interval direction, and favorability—are outside the rule projection.

## Verified classifier properties

The implementation test is named `stateless repeat-run determinism`; the seven-property count uses the concise label stateless determinism.

The bundled tests count exactly seven named properties:

1. `result independence`
2. `prerequisite monotonicity`
3. `failure dominance`
4. `projection scoping`
5. `stateless determinism`
6. `unknown-state fail-closedness`
7. `strict claim ordering`

## Mapping assumptions

- The frozen case-study protocols prespecified finite-population paired percentile bootstrap intervals and secondary exact two-sided McNemar inference; that original plan remains visible in the protocol transcriptions.
- The current Level-6 fixed-battery descriptive-only restriction is a later post-acquisition conservative reporting restriction, not frozen provenance and not evidence that this taxonomy was prospectively validated.
- Future adopters must freeze the claim taxonomy, gate-to-claim mapping, estimands, and uncertainty rules before data acquisition.
- The seven evidence gates preserve Levels 1 through 7 of the frozen ladder; Level 8 is represented by the decision returned by this engine, which under the current restriction admits only fixed-battery descriptive wording absent a separate inferential design.
- The named intermediate claim classes are a post-acquisition taxonomy. They do not retroactively replace the frozen experiment-specific binary suppression rules.
- A claim is limited by the longest contiguous prefix of passed gates. A later pass cannot repair an earlier fail, unavailable, or not-applicable prerequisite.
- Level 5 is the minimum evidence for execution-repeatability wording because the frozen protocol separates identical-arm record parity at Level 4 from repeat-and-worker parity at Level 5.
- Level 6 permits only a fixed-battery descriptive seed-indexed contrast and empirical reweighting sensitivity. It does not establish inferential pairing, a confidence interval, a hypothesis test, a population effect, Level 7 semantic event alignment, a fully coupled counterfactual, or a general common-random-number guarantee.
- Level 7 establishes scoped semantic event alignment but does not by itself create a sampling or randomization basis for inferential pairing; absent a separately justified design its contrast remains fixed-battery descriptive.
- Any frozen experiment-specific invalidator must be encoded as a failed or contradictory prerequisite and continues to suppress the planned paired contrast even if this generic map permits a weaker descriptive statement.
- Not-applicable is never treated as pass; ambiguity about whether a prerequisite applies therefore cannot strengthen a claim.
- The pure classifier accepts only explicitly trusted, prevalidated gate states. The public admit command separately verifies declared bundle-relative files and derives states from standardized records; roles, profile provenance, and trace semantics remain caller assertions, and neither interface reads result_data.
