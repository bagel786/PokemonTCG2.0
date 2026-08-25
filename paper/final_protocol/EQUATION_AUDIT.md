# Equation audit

Scope: all displayed mathematical definitions in `main.tex`. No equation is
included solely for presentation. Numerical examples are independently
recalculated by `scripts/recalculate_equation_examples.py`, whose current
output is `source_data/equation_examples.json` with status `PASS`. Directional
and algebraic identities are independently checked in
`tests/test_equations.py`.

## EQ01 — Trace-disagreement proportion (`eq:trace-disagreement`)

- **equation_id:** EQ01
- **manuscript_location:** Main text, Definitions — Execution repeatability,
  displayed equation labeled `eq:trace-disagreement`.
- **symbols:** `N` = number of seed-condition clusters (count); `i` = cluster
  index; `r` = execution-profile index; `R` = frozen set of required profiles;
  `H_ir = (D_ir,B_ir)` = ordered pair of SHA-256 trace-projection digest
  `D_ir` and byte count `B_ir` for cluster `i`, profile `r`; `I(·)` = unitless
  indicator; `q-hat` = unitless fraction of clusters with more than one
  observed digest--byte-count pair.
- **dimension_or_unit:** `N`, `i`, and the cardinality inside the indicator are
  counts; `D_ir` is a categorical SHA-256 digest and `B_ir` is a byte count;
  `H_ir` is their ordered record; the
  indicator and `q-hat` are unitless, with `q-hat` reported as a proportion or
  after multiplication by 100 as a percentage.
- **plain_language_meaning:** Mark each complete seed condition as disagreeing
  if any required execution profile has a different recorded-trace digest or
  byte count, then divide the number marked by the total number of complete
  seed conditions. A missing required profile invalidates the gate rather than
  silently changing that denominator.
- **analysis_unit:** One seed-condition cluster containing all prescribed
  execution profiles, each carrying the complete `(digest, byte_count)` record.
- **assumptions:** The profile set is complete and frozen; every digest uses the
  same canonical trace projection; missing profiles fail rather than vanish;
  clusters, not profile pairs, form the denominator.
- **toy_example:** Five complete clusters contain three profile records each.
  One cluster differs by digest and one differs only by byte count; the other
  three have identical tuples, so `q-hat = 2/5 = 0.40`.
- **test_file:** `tests/test_equations.py::test_trace_disagreement_toy_example`,
  `tests/test_equations.py::test_trace_disagreement_detects_byte_count_only_change`,
  `tests/test_equations.py::test_trace_disagreement_missing_profile_fails_closed`,
  and `scripts/recalculate_equation_examples.py`.
- **test_result:** PASS — independent output records
  `trace_disagreement = 0.4`, `byte_count_only_disagreement = true`, and
  `missing_profile_fail_closed = true`.
- **sign_and_index_check:** The indicator is nonnegative; the estimate must lie
  in `[0,1]`; profile labels do not affect the result; each cluster contributes
  at most one to the numerator.
- **human_verified:** PENDING — a human author must confirm the projection and
  cluster definition.

## EQ02 — Binary paired difference (`eq:paired-difference`)

- **equation_id:** EQ02
- **manuscript_location:** Main text, Pairing-assumption validation protocol —
  Seed-indexed descriptive contrast and reweighting, displayed equation labeled
  `eq:paired-difference`.
- **symbols:** `i` = matched-unit index; `Y_i^(I)` = intervention win indicator;
  `Y_i^(C)` = control win indicator; each `Y` is unitless and belongs to
  `{0,1}`; `d_i` = unitless intervention-minus-control difference in
  `{-1,0,1}`.
- **dimension_or_unit:** `i` is an index; both `Y` indicators and `d_i` are
  unitless. Means of `d_i` are unitless win-rate differences and are multiplied
  by 100 only when displayed in percentage points.
- **plain_language_meaning:** For the same scheduled unit, subtract the control
  win indicator from the intervention win indicator. Positive values favor the
  intervention direction fixed in the protocol.
- **analysis_unit:** One schedule-indexed game unit within a frozen
  opponent-by-order stratum.
- **assumptions:** Arm labels and subtraction direction are fixed; win is coded
  1 and nonwin 0; the two outcomes belong to the same schedule unit. This is a
  descriptive algebraic pairing and supplies neither inferential
  exchangeability nor semantic event alignment.
- **toy_example:** If intervention wins and control does not, `d_i = 1 − 0 = 1`.
  Reversing the outcomes gives `−1`; equal outcomes give `0`.
- **test_file:** `tests/test_equations.py::test_paired_difference_directions`
  and `scripts/recalculate_equation_examples.py`.
- **test_result:** PASS — all four binary pairs have the expected sign, and the
  independent output records `paired_difference = 1` for the stated example.
- **sign_and_index_check:** The manuscript consistently uses intervention minus
  control; C4 minus C1 is therefore positive when C4 wins alone.
- **human_verified:** PENDING — a human author must confirm the arm labels and
  estimand direction.

## EQ03 — Stratified paired-unit empirical reweighting replicate (`eq:paired-reweighting`)

- **equation_id:** EQ03
- **manuscript_location:** Main text, Pairing-assumption validation protocol —
  Seed-indexed descriptive contrast and reweighting, displayed equation labeled
  `eq:paired-reweighting`. This equation defines factorial paired-unit
  empirical reweighting; it does not define the pooled whole-cluster stress
  reweighting.
- **symbols:** `K` = number of frozen strata (count); `k` = stratum index; `n_k`
  = paired-unit count in stratum `k`; `j` = draw index within stratum; `d_k,i` =
  unitless paired difference for unit `i` in stratum `k`; `I_bkj` = index drawn
  uniformly with replacement from `{1,…,n_k}` for empirical reweighting
  replicate `b`; `d-bar-star^(b)` = unitless equally weighted mean of
  within-stratum reweighted paired differences.
- **dimension_or_unit:** `K`, `n_k`, and all indices are counts or index labels;
  `d_k,i` and `d-bar-star^(b)` are unitless win-rate differences. Replicates and
  percentile endpoints are multiplied by 100 only for percentage-point
  presentation.
- **plain_language_meaning:** Within each frozen stratum, reweight whole
  schedule-indexed paired-unit identifiers by sampling their indices with
  replacement, average their differences, and then average the stratum means
  equally. Never reweight arms separately.
- **analysis_unit:** One paired unit identifier within a frozen stratum; the
  output is one empirical reweighting replicate of the fixed-battery mean
  contrast.
- **assumptions:** The within-stratum empirical distributions are the only
  reweighting objects; unit identifiers retain all arm outcomes together;
  stratum weights, draw count, random seed, and percentile rule are frozen.
  No probability sample, randomized assignment, or defended population model
  is supplied, so the quantiles are not confidence limits.
- **toy_example:** With one stratum, differences `[1,0,−1]`, and one-based sampled
  indices `[1,1,2]`, the replicate is `(1+1+0)/3 = 2/3`.
- **test_file:**
  `tests/test_equations.py::test_stratified_paired_unit_reweighting_toy_example` and
  `scripts/recalculate_equation_examples.py`.
- **test_result:** PASS — independent output records
  `reweighting_replicate = 0.6666666666666666`.
- **sign_and_index_check:** The test uses one-based manuscript indices but maps
  them explicitly to zero-based code indices; equal stratum weighting occurs
  outside the within-stratum sum.
- **human_verified:** PENDING — a human author must confirm that the fixed-
  schedule stability interpretation, rather than population coverage, is the
  intended one.

## EQ04 — Two-by-two factorial contrasts (`eq:factorial`)

- **equation_id:** EQ04
- **manuscript_location:** Appendix, Secondary factorial details, displayed
  equation labeled `eq:factorial`. The equation and detailed factorial results
  are not in the main protocol narrative.
- **symbols:** `mu_00`, `mu_10`, `mu_01`, and `mu_11` = unitless win rates for
  C1 (neither flag), C2 (representation only), C3 (training only), and C4
  (both); first subscript = representation flag; second subscript = training
  flag; `T` = C4-minus-C1 total contrast; `R` = average representation contrast;
  `G` = average training contrast; `J` = difference-in-differences interaction.
- **dimension_or_unit:** Every `mu` and each contrast is a unitless proportion;
  reported contrast values are multiplied by 100 and expressed in percentage
  points. Subscripts and cell labels are indices, not quantities.
- **plain_language_meaning:** `T` compares both interventions with neither; `R`
  averages the representation change at both training levels; `G` averages the
  training change at both representation levels; `J` measures departure from
  additivity on the win-rate-difference scale.
- **analysis_unit:** One common fixed-schedule unit carrying all four cell
  outcomes within one of ten opponent-by-order strata; cell win rates aggregate
  2,000 such units per cell, and reweighting retains each unit's four outcomes.
- **assumptions:** Cell-to-subscript mapping and signs are correct; all four cell
  outcomes are present for every unit; the frozen repeated-control gate is
  satisfied; absent factorial trace digests are not treated as observed zeros.
- **toy_example:** For rates `(0.50,0.52,0.51,0.54)`, `(T,R,G,J)` equals
  `(0.04,0.025,0.015,0.01)` before multiplication by 100.
- **test_file:** `tests/test_equations.py::test_factorial_signs_and_directions`
  and `scripts/recalculate_equation_examples.py`.
- **test_result:** PASS — independent output records total
  `0.040000000000000036`, representation `0.025000000000000022`, training
  `0.015000000000000013`, and interaction `0.010000000000000009`; floating-
  point tails are representational only.
- **sign_and_index_check:** Direct substitutions verify C4−C1 for `T`,
  representation changes `C2−C1` and `C4−C3`, training changes `C3−C1` and
  `C4−C2`, and interaction `C4−C2−C3+C1`.
- **human_verified:** PENDING — a human author must confirm the substantive cell
  labels and that no equivalence claim is intended.

## Symbol reuse and unit audit

- `i` consistently indexes a paired or clustered schedule unit within the local
  equation; `k` indexes strata; `r` indexes execution profiles; `b` indexes
  empirical reweighting replicates; `j` indexes within-stratum draws.
- `H` is used only for the ordered `(digest, byte_count)` trace record, `Y` only for a binary outcome, `d` only
  for a paired outcome difference, and `mu` only for a cell win rate.
- All displayed contrasts are unitless. Win-rate differences and empirical
  reweighting quantiles are multiplied by 100 only for percentage-point
  presentation.
- The stress and factorial procedures use different empirical reweighting
  objects: whole four-profile seed-condition clusters for stress, and whole
  schedule-indexed paired-unit identifiers within ten strata for the
  factorial. The displayed EQ03 defines the latter. Neither distribution is
  presented as population inference.
- The admission-safety proposition is deliberately stated in prose rather than
  as a decorative equation. Its result independence, prerequisite monotonicity,
  failure dominance, projection scoping, determinism/idempotence, unknown-state
  fail-closedness, and claim-class ordering are independently executable
  properties in `release_templates/tests/test_release.py`, including exhaustive
  enumeration of the declared gate-state space.
- Semantic event alignment is stated as a verbal criterion because the stable-
  identifier/value equality adds no necessary mathematical content; no
  decorative equation was added.

## Audit disposition

**Machine checks: PASS. Human verification: PENDING.** The equation audit does
not clear the submission gate until a human author confirms each pending item
and the final reproduction report shows that the tests and independent example
recalculation passed against the submitted manuscript state.
