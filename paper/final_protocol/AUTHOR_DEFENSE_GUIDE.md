# Author defense guide (V2, closeout rewrite)

Purpose: after studying this guide, the human author should be able to answer
any reviewer question about the paper in their own words. Each question has a
SHORT ANSWER (plain language), TECHNICAL ANSWER (full detail), SOURCE
(file + section), and FAILURE MODE (what would make the answer wrong).
Sign-off is item 12 of `HUMAN_CLOSEOUT_FORM.md`.

## 1. What does “same seed” actually establish?

**Short answer:** It establishes that both arms were scheduled to receive the
same value at the engine boundary and that their rows agree on every declared
pairing field. That is a design property — a matched schedule — nothing more.

**Technical answer:** Stage 2 records the host-language seed and the exact
integer passed at the observable entry point, including any uint32 conversion,
and checks collisions. Stage 3 verifies row-level parity of opponent, order,
seat, environment, and decision limit. Neither says anything about what the
engine did internally with the value, whether execution repeated, or whether
the same semantic random events received the same quantities across arms.
Those are Stages 4–7, which must be evidenced separately.

**Source:** `main.tex` Definitions §Schedule matching; `METHOD_ASSUMPTION_AUDIT.md` M02–M03.

**Failure mode:** If the adapter converted or narrowed seeds inconsistently, or
a schedule field disagreed, the matched-schedule description itself would fail;
any paired wording would then be unsupported.

**Human comprehension checkbox:** [ ] I can deliver this answer in my own words, and I understand what would falsify it. Initials/Date: ______
## 2. Why can identical agents differ?

**Short answer:** Because the engine's behavior can depend on things the seed
does not pin down — wall-clock deadlines inside timed search, process-global
state, worker history, or enqueue order.

**Technical answer:** The stress test re-executed byte-identical artifacts on
fixed schedules across four profiles (serial forward/reverse, parallel
forward/reverse). 99 of 200 seed-condition clusters produced different recorded
trace projections, so at least one influence outside the seed differs between
executions. The static audit found candidate mechanisms (clock/deadline
patterns, module state), but attribution of any single divergence to one
mechanism is not claimed.

**Source:** `main.tex` Timed-search stress test; `METHOD_ASSUMPTION_AUDIT.md` M05–M06, M12.

**Failure mode:** If the trace projection were underspecified (omitting fields
that actually differ), disagreement could hide; conversely, if serialization
were non-canonical, false disagreements could appear. Canonicalization is an
assumption recorded in M04.

**Human comprehension checkbox:** [ ] I can deliver this answer in my own words, and I understand what would falsify it. Initials/Date: ______
## 3. What exactly is the recorded trace projection?

**Short answer:** A canonical digest over each decision's public-observation
hash, acting side, and chosen action, plus the terminal record — compared as a
SHA-256 digest and byte count. Raw observations are not stored.

**Technical answer:** The projection is declared (id/version/fields) in every
admission record. “Complete” always means complete within this declared
projection: opaque search snapshots and hidden simulator state are excluded by
design and by the engine's own trace contract. Byte-count equality was added
after acquisition as integrity hardening; the frozen endpoint was the digest,
and both give 99/200.

**Source:** `main.tex` Definitions §Execution repeatability + Appendix A; `release/pevl_bench/evidence.py`.

**Failure mode:** If two runs differed only in omitted state, digests would
agree while true trajectories differed — agreement is scoped, never proof about
omitted state.

**Human comprehension checkbox:** [ ] I can deliver this answer in my own words, and I understand what would falsify it. Initials/Date: ______
## 4. Why is outcome agreement weaker than trace agreement?

**Short answer:** Many different games end in the same winner. Identical
outcomes can hide completely different action sequences; identical traces
cannot.

**Technical answer:** In the stress battery, outcomes disagreed in 47 clusters
while traces disagreed in 99 — outcome checks alone would have missed 52
clusters whose executions diverged but terminal results coincided. Trace
agreement is therefore the stronger repeatability evidence; outcome agreement
is necessary but nowhere near sufficient for it.

**Source:** `main.tex` Definitions §Execution repeatability and stress section; macros \StressTraceMismatch vs \StressOutcomeMismatch.

**Failure mode:** The inference direction matters: trace disagreement implies
execution difference; trace agreement does not prove hidden-state equality.

**Human comprehension checkbox:** [ ] I can deliver this answer in my own words, and I understand what would falsify it. Initials/Date: ______
## 5. What is one seed-condition cluster?

**Short answer:** One scheduled seed condition together with all of its
required execution profiles — here four profiles: serial forward/reverse and
parallel forward/reverse.

**Technical answer:** Clusters are the analysis unit for the stress endpoint:
the cluster disagrees if any required profile's (digest, byte-count) pair
differs. Profiles within a cluster share planned inputs, so they are not
independent observations; the denominator counts clusters, not profile pairs.
A missing profile invalidates the gate rather than shrinking the denominator
(fail closed).

**Source:** `main.tex` Eq. (1) discussion; `tests/test_equations.py::test_trace_disagreement_missing_profile_fails_closed`.

**Failure mode:** Treating profiles as independent replicates would inflate
the evidence; the equation deliberately prevents that.

**Human comprehension checkbox:** [ ] I can deliver this answer in my own words, and I understand what would falsify it. Initials/Date: ______
## 6. Why are execution profiles not independent?

**Short answer:** They are planned variations of the same seed condition under
the same artifacts — repeated measurements, not samples from a population.

**Technical answer:** Worker counts and enqueue orders test execution contexts
(deterministic contexts versus time-limited ones), not sampled hardware or
randomized assignments. That is why no population-level inference is drawn from
them and why the fixed-composition sensitivity keeps strata intact rather than
letting pooled resampling drift context composition.

**Source:** `main.tex` Stages 4–6 §Stage 5; appendix reweighting details.

**Failure mode:** Any claim like “X% of executions fail” would wrongly treat a
deterministic engineering battery as a probability sample.

**Human comprehension checkbox:** [ ] I can deliver this answer in my own words, and I understand what would falsify it. Initials/Date: ______
## 7. What did the historical audit show?

**Short answer:** Re-running three separately executed control arms over the
historical records showed 210/2,800 units disagreeing on win/draw and
458/2,800 when decision count was added — concentrated in the two timed-search
opponents — so the planned favorable paired comparison was suppressed.

**Technical answer:** The historical files lack full Stage-3 fields and trace
digests, so the strongest legitimate check is equality of an available-record
projection across control repetitions. The rule was frozen only for this
retrospective reanalysis, applied without dropping mismatches, and its result
was suppression of the historical comparison. Removing the failing opponents
would have changed the target population and was explicitly not used.

**Source:** `main.tex` Restricted game-agent case study; `METHOD_ASSUMPTION_AUDIT.md` M10.

**Failure mode:** Calling this prospective blinding, or treating the classifier
as outcome-blind (it consumes control-arm records; it is independent of
candidate-effect magnitude/direction/favorability only).

**Human comprehension checkbox:** [ ] I can deliver this answer in my own words, and I understand what would falsify it. Initials/Date: ______
## 8. Why was the historical gate retrospective?

**Short answer:** Because the historical outcomes already existed when the
gate and its suppression consequence were written down.

**Technical answer:** Git shows the historical data predates any current-protocol
audit commit. Freezing a rule after seeing outcomes cannot demonstrate
blinding; it demonstrates disciplined rule application. The manuscript states
this limitation directly rather than claiming preregistration.

**Source:** `CHRONOLOGY_AUDIT.json` CHRON-05; `supplement/PROTOCOL_DEVIATIONS.md` frozen-plan section.

**Failure mode:** If any document could show the rule predated acquisition, the
stronger claim might be defensible — no such document exists in the repository.

**Human comprehension checkbox:** [ ] I can deliver this answer in my own words, and I understand what would falsify it. Initials/Date: ______
## 9. What was prospectively frozen later?

**Short answer:** The retained experiment's protocol: acquisition conditions,
preflight requirements, binary suppression consequences, the paired-resampling
procedure, and secondary McNemar calculation — all committed before the
retained results.

**Technical answer:** Commit 803257f1 (2026-08-24 16:20) contains
PEVL_PROSPECTIVE_PROTOCOL.md; retained preflight/stress/factorial summaries
first appear in descendant commit 23b9106 (~95 minutes later). Binary actions:
one required preflight mismatch blocks factorial acquisition; invalidating
mismatches suppress all contrasts. Conditional on passes, the plan prescribed
100,000-resample 95% intervals and secondary exact two-sided McNemar.

**Source:** `CHRONOLOGY_AUDIT.json` CHRON-01/02/04; frozen protocol file.

**Failure mode:** Git proves commit ordering, not when a human inspected
uncommitted files — the manuscript says exactly this.

**Human comprehension checkbox:** [ ] I can deliver this answer in my own words, and I understand what would falsify it. Initials/Date: ______
## 10. What was added post-acquisition?

**Short answer:** Three things only: the generic completed-case claim-class
taxonomy, the descriptive-only reinterpretation of the resampling quantiles as
empirical reweighting, and the byte-count integrity extension.

**Technical answer:** The frozen protocol already contained the eight-stage
ladder and binary gates. The generic executable admission map embeds
`created_after_acquisition=true` and pins itself to that status via a bundle
hash. None of these additions is credited to the frozen commit, and future
users must freeze them before collecting outcomes.

**Source:** `CHRONOLOGY_AUDIT.json` CHRON-06; `main.tex` Prospective validation results; `admission.py` formalization_provenance.

**Failure mode:** Describing the whole Level taxonomy (rather than these three
additions) as post-acquisition would overstate the departure — the earlier
manuscript draft did and was corrected.

**Human comprehension checkbox:** [ ] I can deliver this answer in my own words, and I understand what would falsify it. Initials/Date: ______
## 11. What does event alignment mean?

**Short answer:** After the two policies branch, every shared modeled exogenous
event keeps a stable identity and receives the same random quantity in both
arms.

**Technical answer:** It requires a declared event ontology, logged
event/value pairs (or event-keyed counter-based randomness), declared marginal
distributions and dependence structure. This is the property that makes
cross-arm differences interpretable as intervention effects rather than
re-randomized noise.

**Source:** `main.tex` Definitions §Semantic event alignment; M07.

**Failure mode:** Within-arm repetition cannot establish it: identical arms
follow the same path and consume the same stream positions trivially.

**Human comprehension checkbox:** [ ] I can deliver this answer in my own words, and I understand what would falsify it. Initials/Date: ______
## 12. Why can the real engine not establish it?

**Short answer:** Its interface exposes a seeded entry point but no stable
event identifiers or independent per-event streams, so there is nothing to
compare after paths diverge.

**Technical answer:** The engine is a restricted black box: internals are not
inspectable, and the trace projection intentionally excludes hidden state.
Stage 7 is therefore recorded as unavailable/not-applicable for the case, which
blocks event-aligned, counterfactual, and full-CRN wording but leaves lower-
stage evidence intact.

**Source:** `main.tex` Stages 7–8; Limitations.

**Failure mode:** Any wording implying equal random quantities for shared
events in the real case would contradict this recorded boundary.

**Human comprehension checkbox:** [ ] I can deliver this answer in my own words, and I understand what would falsify it. Initials/Date: ______
## 13. What does the synthetic event-keyed example prove?

**Short answer:** Inside a fully declared synthetic ontology, keying random
quantities to (seed, event identity) repairs draw-index misalignment: all five
logged shared events align after one arm consumes an extra draw.

**Technical answer:** The draw-shift fixture repeats exactly within each arm
but misaligns 4 of 5 shared events after the extra consumption; switching the
fixture's source to event-keyed hashing aligns 5 of 5. The suite also
demonstrates the failure modes (seed conversion, clock budget, process state)
that produce within-arm disagreement.

**Source:** `main.tex` Synthetic suite section; `pevl_bench/synthetic.py`.

**Failure mode:** The repair is proven only for the fixture's ontology and
distribution; porting it requires declaring an ontology and validating the
assignment — exactly what the real engine cannot currently support.

**Human comprehension checkbox:** [ ] I can deliver this answer in my own words, and I understand what would falsify it. Initials/Date: ______
## 14. What does it not prove?

**Short answer:** It does not prove that external simulators contain these
mechanisms, that the repair generalizes without a declared ontology, or that
the real engine's divergences have any particular cause.

**Technical answer:** Injected profiles make fixtures reproducible
demonstrations of logical possibility — a conformance oracle, not a prevalence
estimate. No empirical frequency claim is made anywhere.

**Source:** `main.tex` Synthetic suite §figure caption and limitations.

**Failure mode:** Reading detection rates in the suite as failure rates in the
wild.

**Human comprehension checkbox:** [ ] I can deliver this answer in my own words, and I understand what would falsify it. Initials/Date: ______
## 15. Why is the factorial descriptive?

**Short answer:** Opponents, orders, seeds, and profiles are fixed engineering
choices, not random samples; candidate rows carry no trace digests; and event
alignment is unavailable — so no reference distribution exists for population
statements.

**Technical answer:** The admitted output is a fixed-battery descriptive
contrast (+0.55 pp total C4−C1) plus stratified empirical-reweighting
quantiles spanning zero. The frozen plan had labeled these intervals and added
McNemar; the post-acquisition conservative reading declines inferential labels
because randomized assignment, probability sampling, and a defended joint model
are all absent.

**Source:** `main.tex` Claim-admission consequence + Appendix B; EQUATION_AUDIT EQ04.

**Failure mode:** Calling it causal, counterfactual, equivalence, superiority,
or full-CRN — all forbidden wording in the claim classes.

**Human comprehension checkbox:** [ ] I can deliver this answer in my own words, and I understand what would falsify it. Initials/Date: ______
## 16. What do the empirical reweighting quantiles mean?

**Short answer:** How much the fixed-battery contrast moves when schedule-
indexed units (or whole clusters) are resampled within the realized battery.
They summarize sensitivity to reweighting — nothing about new opponents,
seeds, or training runs.

**Technical answer:** Stress: pooled whole-cluster resampling gives [42.5%,
56.5%]; a post-acquisition fixed-composition sensitivity preserving all four
stratum sizes gives [46.0%, 53.0%]. Factorial: ten-stratum paired-unit
resampling, equally weighted stratum means, 100,000 draws, frozen seed
2026083117/18.

**Source:** `main.tex` reweighting subsection + appendix; `independent_statistics_audit.py` recomputation.

**Failure mode:** Reading them as confidence intervals or tests — the manuscript
labels them descriptive everywhere.

**Human comprehension checkbox:** [ ] I can deliver this answer in my own words, and I understand what would falsify it. Initials/Date: ______
## 17. Why does crossing zero not mean equivalence?

**Short answer:** Quantiles spanning zero mean the data cannot distinguish the
contrast from zero at battery scope — absence of evidence, not evidence of
absence.

**Technical answer:** No equivalence margin was specified anywhere; an
equivalence claim would require a pre-specified margin and a procedure designed
to accept it. The claim-class definitions forbid equality/equivalence/superiority
wording regardless of interval location.

**Source:** Appendix reweighting details (“quantiles spanning zero cannot
support equivalence”); claim_classes.json forbidden_wording.

**Failure mode:** Any “the policies are identical up to noise” statement.

**Human comprehension checkbox:** [ ] I can deliver this answer in my own words, and I understand what would falsify it. Initials/Date: ______
## 18. What prior work already existed?

**Short answer:** CRN theory, streams/substreams, counter-based parallel RNGs,
event-keyed randomness, paired-seed statistics, rollout preservation, trace
assurance, deterministic workflow contracts, metamorphic testing, simulation
V&V, and A/A diagnostics.

**Technical answer:** Full mapping with per-work differences is Table I and
NOVELTY_MATRIX.csv (23 verified references, including the two close KDD-2026
workshop papers added during closeout).

**Source:** `main.tex` Related work; `NOVELTY_MATRIX.csv`; `NOVELTY_AUDIT_V2.md`.

**Failure mode:** Overlooking a close work — the fatal novelty test is
re-run at closeout precisely to catch that.

**Human comprehension checkbox:** [ ] I can deliver this answer in my own words, and I understand what would falsify it. Initials/Date: ______
## 19. What exactly is the contribution?

**Short answer:** An executable, fail-closed workflow that decides which
paired statistical claim, if any, the observable evidence supports — validated
synthetically and demonstrated on a real restricted engine where it both
suppressed an unsupported comparison and admitted a qualified one.

**Technical answer:** Eight evidence stages mapped to six claim classes with
seven machine-checked safety properties; a synthetic conformance suite; a
frozen prospective demonstration (preflight pass; stress failure; gated
factorial reported descriptively); and explicit chronology discipline.

**Source:** Abstract; Introduction contribution paragraph.

**Failure mode:** Sliding into component-priority claims (CRN, replay, etc.)
that belong to prior work.

**Human comprehension checkbox:** [ ] I can deliver this answer in my own words, and I understand what would falsify it. Initials/Date: ______
## 20. How does this differ from Rollout Cards?

**Short answer:** Rollout Cards preserve and disclose rollout evidence and
reporting rules; they do not verify that same-seed executions repeat or gate
statistical wording on that verification.

**Technical answer:** Cards are publication bundles (views/rules/drops
manifests). This protocol adds artifact/seed/schedule verification, fresh-
process and cross-context repetition testing, stochastic-source auditing, and
an automatic admission decision with suppression consequences.

**Source:** Related-work section; NOVELTY_MATRIX row masters2026rolloutcards.

**Failure mode:** Equating preservation with validation.

**Human comprehension checkbox:** [ ] I can deliver this answer in my own words, and I understand what would falsify it. Initials/Date: ______
## 21. How does this differ from Trace Assurance?

**Short answer:** Message–Action Trace contracts verify implementation
conformance and enable replay/governance; they do not decide when a same-seed
comparison may be called statistically paired.

**Technical answer:** The assurance framework targets contracts, fault
injection, localization; this protocol's unit is the statistical claim, with
fail-closed downgrade/suppression semantics derived from pairing evidence.

**Source:** Related work; NOVELTY_MATRIX row paduraru2026traceassurance.

**Failure mode:** Conflating trace fidelity with coupling validity.

**Human comprehension checkbox:** [ ] I can deliver this answer in my own words, and I understand what would falsify it. Initials/Date: ______
## 22. How does this differ from AEVAL?

**Short answer:** AEVAL makes agent-workflow changes deterministically testable
via evaluation contracts; it does not address cross-arm seed coupling or
automatic suppression of paired claims.

**Technical answer:** AEVAL preserves first-attempt evidence and turns changes
into contract tests; this protocol validates the pairing assumptions behind
comparative statistics and maps evidence to permitted wording mechanically.

**Source:** Related work; NOVELTY_MATRIX row anand2026aeval.

**Failure mode:** Presenting contract testing as coupling validation.

**Human comprehension checkbox:** [ ] I can deliver this answer in my own words, and I understand what would falsify it. Initials/Date: ______
## 23. What is Stage 6?

**Short answer:** A bounded static audit of package sources for stochastic
influences — clocks/deadlines, explicit randomness, module-global state,
native handles, concurrency — resolved through five named outcomes.

**Technical answer:** Outcomes: CONTROLLED (found and bounded with recorded
evidence), RESIDUAL (possible, not shown estimand-changing → downgrade),
ESTIMAND_CHANGING (directly alters the needed execution relation → suppress
mechanistic paired claims), UNAVAILABLE (black-box boundary), UNRESOLVED (hit
without sufficient evidence; no automatic pass). The mapping ships as
machine-readable rules generating `docs/STAGE6_DECISION_RULES.md`, with tests
covering all seven rules including the clean-scan-is-not-proof rule.

**Source:** `main.tex` Stages 4–6 §Stage 6; `stage6_source_audit_rules.json`;
`docs/STAGE6_DECISION_RULES.md`.

**Failure mode:** Treating a hit as cause, or a clean scan as determinism.

**Human comprehension checkbox:** [ ] I can deliver this answer in my own words, and I understand what would falsify it. Initials/Date: ______
## 24. Why does a static hit not prove cause?

**Short answer:** Code containing a clock pattern may never execute that branch
during compared runs; presence of a mechanism is not exercise of the mechanism.

**Technical answer:** Stage 6 requires dynamic disposition evidence (executes?
changes the execution relation? bounded?) before upgrading beyond RESIDUAL.
The real-case audit found hits but the engine binaries were hash-checked only,
so the stage stays honest about its uninspected boundary (2 binaries unassessed).

**Source:** Stage 6 rules 3–6; case-study section.

**Failure mode:** Asserting “timing caused divergence X” from scan output.

**Human comprehension checkbox:** [ ] I can deliver this answer in my own words, and I understand what would falsify it. Initials/Date: ______
## 25. Why does a clean scan not prove determinism?

**Short answer:** The scanner covers declared Python trees only — not binaries,
hardware, or external state; absence of detected patterns is not absence of
influence.

**Technical answer:** Rule `clean_scan_no_proof` deliberately returns RESIDUAL,
never CONTROLLED: control requires a found-and-bounded mechanism. Deterministic
behavior is only ever established behaviorally, by Stages 4–5 repetition.

**Source:** stage6_source_audit_rules.json rule 7 note; main text sentence
“a zero-hit scan does not prove determinism”.

**Failure mode:** Upgrading to CONTROLLED on a zero-hit inventory.

**Human comprehension checkbox:** [ ] I can deliver this answer in my own words, and I understand what would falsify it. Initials/Date: ______
## 26. What can another researcher reproduce?

**Short answer:** Everything engine-free: regenerate and verify the synthetic
suite, run the admission CLI on the worked example, print decision tables,
reaggregate all processed diagnostics, rerun every equation/statistics test,
and rebuild figures/tables/PDF via the one-command reproduction.

**Technical answer:** The release manifest binds the exact tree; the final
report records commands, hashes, and the clean-environment record
(CLEAN_ENV_REPRODUCTION.json). Restricted trajectories cannot be replayed —
stated, not promised.

**Source:** release README; REPRODUCTION_REPORT_V2.json; CLEAN_ENV_REPRODUCTION.json.

**Failure mode:** Promising end-to-end gameplay replication that rights
boundaries forbid.

**Human comprehension checkbox:** [ ] I can deliver this answer in my own words, and I understand what would falsify it. Initials/Date: ______
## 27. What remains restricted?

**Short answer:** The engine and binaries, third-party opponent packages, game
assets/metadata, private replay observations, policy packages, raw restricted
traces, and credentials — none redistributed, none offered on request because
no lawful access mechanism exists.

**Technical answer:** Only approved digests and bounded processed summaries
represent them. The DAS states this explicitly and flags the reasonable-request
gap as an editorial-risk item rather than promising access.

**Source:** Data Availability Statement; RIGHTS_AND_ACCESS_AUDIT.md;
RELEASE_OWNERSHIP_MATRIX.csv.

**Failure mode:** Any wording implying availability beyond the review package.

**Human comprehension checkbox:** [ ] I can deliver this answer in my own words, and I understand what would falsify it. Initials/Date: ______
## 28. How was AI used?

**Short answer:** OpenAI Codex (GPT-5-family; exact snapshot not exposed)
provided substantive research assistance under human direction — protocol
reasoning, code, statistics, visualization, auditing, drafting — with every
output accepted only after human verification against primary sources and
tests. No AI system is an author.

**Technical answer:** Uses are logged in supplement/AI_USE_LOG.csv; research
uses are disclosed in Methods, other assistance in Acknowledgments, per APS
policy. Completeness and tool-terms compliance require human confirmation
(closeout form Section 9).

**Source:** AI-assisted research methods section; ai_disclosure.md.

**Failure mode:** Discovering substantive unrecorded AI use would invalidate
the disclosure and require correction before submission.

**Human comprehension checkbox:** [ ] I can deliver this answer in my own words, and I understand what would falsify it. Initials/Date: ______
## 29. What would make the paper scientifically invalid?

**Short answer:** Any of: a fabricated or miscounted central number; a
prospective-validation claim for the post-acquisition taxonomy; an event-
aligned or causal claim for the restricted engine; presenting retrospective
suppression as blinding; or unresolved fabrication-level problems in the human
metadata that undermine trust in provenance.

**Technical answer:** The load-bearing numbers are independently recomputed
(0/3,000 preflight; 99/200 stress with 47/93/0 secondary; 210 & 458 of 2,800
historical; factorial contrasts/quantiles). Chronology is Git-auditable
(CHRONOLOGY_AUDIT.json). Every claim class carries forbidden wording enforced
by tests. If any of those bindings broke — or the human signoffs revealed
misunderstanding — the corresponding conclusions would need withdrawal or
correction.

**Source:** CONTRADICTION_AUDIT checks; claim_ledger.csv; HUMAN_CLOSEOUT_FORM.md.

**Failure mode:** This guide itself becoming stale relative to the manuscript;
the pipeline re-verifies textual-number consistency on every run.

**Human comprehension checkbox:** [ ] I can deliver this answer in my own words, and I understand what would falsify it. Initials/Date: ______
