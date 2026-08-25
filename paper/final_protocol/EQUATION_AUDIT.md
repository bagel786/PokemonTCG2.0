# Equation audit

Scope: all displayed mathematical definitions in `main.tex`. No equation is
included solely for presentation. Numerical examples are independently
recalculated by `scripts/recalculate_equation_examples.py`, whose current
output is `source_data/equation_examples.json` with status `PASS`. Directional
and algebraic identities are independently checked in
`tests/test_equations.py`.

## EQ01 — Trace-disagreement proportion (`eq:trace-disagreement`)

- **equation_id:** EQ01
- **symbols:** `N` = number of seed-condition clusters (count); `i` = cluster
  index; `r` = execution-profile index; `R` = frozen set of required profiles;
  `H_ir` = unitless SHA-256 trace-projection digest for cluster `i`, profile
  `r`; `I(·)` = unitless indicator; `q-hat` = unitless fraction of clusters
  with more than one observed digest.
- **plain_language_meaning:** Mark each seed condition as disagreeing if any
  required execution profile has a different recorded-trace digest, then divide
  the number marked by the total number of seed conditions.
- **analysis_unit:** One seed-condition cluster containing all prescribed
  execution profiles.
- **assumptions:** The profile set is complete and frozen; every digest uses the
  same canonical trace projection; missing profiles fail rather than vanish;
  clusters, not profile pairs, form the denominator.
- **toy_example:** Five clusters have digest rows `aaa`, `bbc`, `ddd`, `efe`,
  and `ggg`. Two rows contain more than one digest, so `q-hat = 2/5 = 0.40`.
- **test_file:** `tests/test_equations.py::test_trace_disagreement_toy_example`
  and `scripts/recalculate_equation_examples.py`.
- **test_result:** PASS — independent output records
  `trace_disagreement = 0.4`.
- **sign_and_index_check:** The indicator is nonnegative; the estimate must lie
  in `[0,1]`; profile labels do not affect the result; each cluster contributes
  at most one to the numerator.
- **human_verified:** PENDING — a human author must confirm the projection and
  cluster definition.

## EQ02 — Binary paired difference (`eq:paired-difference`)

- **equation_id:** EQ02
- **symbols:** `i` = matched-unit index; `Y_i^(I)` = intervention win indicator;
  `Y_i^(C)` = control win indicator; each `Y` is unitless and belongs to
  `{0,1}`; `d_i` = unitless intervention-minus-control difference in
  `{-1,0,1}`.
- **plain_language_meaning:** For the same scheduled unit, subtract the control
  win indicator from the intervention win indicator. Positive values favor the
  intervention direction fixed in the protocol.
- **analysis_unit:** One paired game unit within a frozen opponent-by-order
  stratum.
- **assumptions:** Arm labels and subtraction direction are fixed; win is coded
  1 and nonwin 0; the two outcomes belong to the same schedule unit.
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

## EQ03 — Stratified paired-unit bootstrap replicate (`eq:cluster-bootstrap`)

- **equation_id:** EQ03
- **symbols:** `K` = number of frozen strata (count); `k` = stratum index; `n_k`
  = paired-unit count in stratum `k`; `j` = draw index within stratum; `d_k,i` =
  unitless paired difference for unit `i` in stratum `k`; `I_bkj` = index drawn
  uniformly with replacement from `{1,…,n_k}` for bootstrap replicate `b`;
  `d-bar-star^(b)` = unitless equally weighted mean of within-stratum resampled
  paired differences.
- **plain_language_meaning:** Within each frozen stratum, resample whole paired
  unit identifiers, average their paired differences, and then average the
  stratum means equally. Never resample arms separately.
- **analysis_unit:** One paired unit identifier within a frozen stratum; the
  output is one bootstrap replicate of the fixed-schedule mean contrast.
- **assumptions:** The within-stratum empirical distributions are the resampling
  objects; unit identifiers retain all arm outcomes together; stratum weights,
  draw count, random seed, and percentile rule are frozen.
- **toy_example:** With one stratum, differences `[1,0,−1]`, and one-based sampled
  indices `[1,1,2]`, the replicate is `(1+1+0)/3 = 2/3`.
- **test_file:**
  `tests/test_equations.py::test_stratified_resampling_toy_example` and
  `scripts/recalculate_equation_examples.py`.
- **test_result:** PASS — independent output records
  `bootstrap_replicate = 0.6666666666666666`.
- **sign_and_index_check:** The test uses one-based manuscript indices but maps
  them explicitly to zero-based code indices; equal stratum weighting occurs
  outside the within-stratum sum.
- **human_verified:** PENDING — a human author must confirm that the fixed-
  schedule stability interpretation, rather than population coverage, is the
  intended one.

## EQ04 — Two-by-two factorial contrasts (`eq:factorial`)

- **equation_id:** EQ04
- **symbols:** `mu_00`, `mu_10`, `mu_01`, and `mu_11` = unitless win rates for
  C1 (neither flag), C2 (representation only), C3 (training only), and C4
  (both); first subscript = representation flag; second subscript = training
  flag; `T` = C4-minus-C1 total contrast; `R` = average representation contrast;
  `G` = average training contrast; `J` = difference-in-differences interaction.
- **plain_language_meaning:** `T` compares both interventions with neither; `R`
  averages the representation change at both training levels; `G` averages the
  training change at both representation levels; `J` measures departure from
  additivity on the win-rate-difference scale.
- **analysis_unit:** Cell win rates computed from the same 2,000 fixed-schedule
  units per cell, with paired resampling inside ten opponent-by-order strata.
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
  bootstrap replicates; `j` indexes within-stratum draws.
- `H` is used only for a trace digest, `Y` only for a binary outcome, `d` only
  for a paired outcome difference, and `mu` only for a cell win rate.
- All displayed estimands are unitless. Win-rate differences and bootstrap
  intervals are multiplied by 100 only for percentage-point presentation.
- The stress interval and factorial intervals use different resampling objects:
  whole four-profile seed-condition clusters for stress, and whole paired unit
  identifiers within ten strata for the factorial. The displayed EQ03 defines
  the latter.
- Semantic event alignment is stated as a verbal criterion because the stable-
  identifier/value equality adds no necessary mathematical content; no
  decorative equation was added.

## Audit disposition

**Machine checks: PASS. Human verification: PENDING.** The equation audit does
not clear the submission gate until a human author confirms each pending item
and the final reproduction report shows that the tests and independent example
recalculation passed against the submitted manuscript state.
