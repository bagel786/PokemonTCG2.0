# BASELINE SPECIFICATIONS (frozen before implementation)

Decision vocabulary: ADMIT | DOWNGRADE | SUPPRESS | FAIL_CLOSED | ABSTAIN_NOT_EVALUATED.
Rule 1: a method that does not evaluate a branch returns ABSTAIN_NOT_EVALUATED — never ADMIT.
Rule 2: each method receives ONLY its typed evidence view (enforced by constructor signature); possessing more evidence is impossible by construction.
Rule 3: abstention is reported as coverage, never counted as detection or false suppression, unless an explicit frozen scoring rule says otherwise (none does).
Rule 4: unknown/missing required evidence inside a claimed branch ⇒ FAIL_CLOSED (fail closed), not admit.

| method | capability branches | consumes (typed view) | decision rules |
|---|---|---|---|
| B0_schedule_only | A only | {declared/effective schedules, row completeness/id-uniqueness} | A: ADMIT iff fields match ∧ effective==declared ∧ rows complete ∧ ids unique; else SUPPRESS. All else ABSTAIN |
| B1_outcome_aa | A,B(no-pair-wording),C(no) | {schedule fields, retained A/A outcome repetitions bank (same config, ≥2 reps)} | A: as B0 fields-rule. B: if A/A dispersion within frozen noise band → downgraded wording “stable terminal outcome only” (DOWNGRADE = paired claim must be weakened), full paired ADMIT forbidden because outcome-only cannot establish pairing validity; if no bank → FAIL_CLOSED on its A/C checks; never asserts D/E (ABSTAIN). Detection surface: flags visible outcome instability as replay-scope warning only |
| B2_trace_aa | C(within-artifact), weak B | {one declared trace projection + one scoped within-proc repeat} | C: ADMIT iff projections equal AND scope asserted is within_artifact only; cross-context/process claims outside view ⇒ FAIL_CLOSED. B: unpaired-vs-paired wording = DOWNGRADE always (cannot certify pairing). Others ABSTAIN |
| B3_within_seed_reps | C(weak),B(residual diagnostics) | {≥min_repeats within-seed re-executions incl. outcomes? NO — outcomes excluded from decisions; counts+digests+dispersion signs only} | C: ADMIT iff enough repeats ∧ digest-stable; FAIL_CLOSED if fewer than min_repeats. B: pairing admitted ONLY IF residual-dispersion protocol explicitly designed (design view says repeats planned & clustered unit); else DOWNGRADE. Others ABSTAIN |
| B4_unpaired_analysis | B(unpaired wording),A-fields | {arm-independence declarations, arm outcome availability counts} | If arms declared independent ∧ design says independent_arms → recommend unpaired inference: B=SUPPRESS paired wording while noting valid unpaired analysis exists (encoded SUPPRESS with reason code UNPAIRED_ONLY). If independence undeclared → FAIL_CLOSED (cannot choose). A-fields check as B0. C/D/E ABSTAIN. No dead paths |
| B5_cluster_hierarchical | B(clustered/hierarchical/RM) | {unit declaration, repeat-cluster keys/usability, hierarchical-model declaration, within-cluster variation indicator, design justification refs} | B: ADMIT iff unit cluster-respecting ∧ clusters usable ∧ (hierarchical OR repeated-measures justification present) ∧ nonzero within-cluster variation where residual randomness claimed; SUPPRESS if pseudoreplicated unit; DOWNGRADE if clusters usable but no model justification; FAIL_CLOSED if cluster keys unusable. Never needs/uses replay or coupling views. Others ABSTAIN |
| B6_event_keyed_whitebox | E,D1(partial) | {event logs both arms, ontology id/version, key-uniqueness map, matched/unmatched coverage, marginals summary, collision counts} | E: ADMIT iff ontology match ∧ uniqueness ∧ coverage threshold ∧ all compared values equal; FAIL_CLOSED if ontology/version missing; SUPPRESS otherwise. D1: ADMIT only when marginals preserved ∧ zero collisions; else SUPPRESS (no covariance/benefit measurement — reports BENEFIT_UNKNOWN). B: ABSTAIN unless event-keyed construction ALSO declares matched_paired_units intact — then defers to pairing basis WITHOUT measuring it ⇒ always DOWNGRADE wording, honest limitation |
| B7_csvf_full | A,B,C,D1,D2,E (router) | {full bundle via router; branch-local predicates; no cross-branch leakage} | Branch-specific gates exactly as framework/classifier.py implements (repaired semantics); outputs ADMIT/DOWNGRADE/SUPPRESS/FAIL_CLOSED per branch plus predicate-level provenance |

Anti-gaming notes:
- An always-abstain method scores Mcov=0 → cannot appear optimal; detection-conditional-on-coverage reported alongside absolute detection.
- Capability matrix above is normative; mutation tests remove each input from every method's view and assert the expected degradation (never silent admission).
- No baseline may inspect final outcome VALUES for decisions (counts/dispersion indicators allowed where specified).
- Names intentionally continue B0–B7 for comparability of *roles* only; old empirical columns are void.
