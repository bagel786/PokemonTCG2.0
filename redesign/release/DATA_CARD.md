# Data Card

## Dataset name

Claim-Specific Validation Framework prospective benchmark, 2026-08-26.

## Purpose

Evaluate eight validation strategies against eleven construction-labeled
seed-matching scenarios in one game and one scientific simulator.

## Composition

- Raw file: `data/raw/decisions_and_pairs.jsonl`
- Rows: 35,014 (34,160 decision; 854 outcome-pair)
- Systems: RLCard limit hold'em and 2D Ising Metropolis
- Scenarios: S0-S10
- Final seed bank: 40 seeds; S7 intentionally drops every third schedule row
- Decision unit: system x scenario x retained seed x method x claim branch
- Outcome unit: system x scenario x retained seed pair

## Provenance and chronology

Framework and protocol were committed and pushed at `62ad878` before final
outcome acquisition. The raw file hash is
`ead6dd392c61767c914f9bb1956b7a82213c5889f3e95faf15c4a3f3ec5d2540`.
The protocol is a public git freeze, not a public registry submission.

## Ground truth

Labels are construction facts declared in
`protocol/EXPECTED_DECISION_TABLE.json`. They do not estimate natural failure
prevalence. `VALID`, `DOWNGRADE`, `INVALID`, and `NOT_APPLICABLE` are scoped to a
claim branch.

## Sensitive information

No human subjects, personal data, private user data, or restricted legacy raw
assets are present.

## Quality and missingness

The raw-integrity audit passes. S7 missingness is deliberate and fully declared.
The schema omits the A/A null banks and repeated S8 outcomes promised for M4-M6,
and omits per-method time/bundle-byte fields for M9-M10. Those omissions are not
imputed.

## Known benchmark defects

- Ising S4/S8 do not implement the intended clock-residual mechanics even
  though the frozen label table marks replay invalid.
- Hold'em S3 uses the same event-keyed action rule in both arms and collapses the
  intended policy contrast, producing zero paired-difference variance.
- These are findings about benchmark implementation validity, not natural-system
  prevalence.

## Recommended use

Use for reproducibility auditing, method-development regression tests, and
planning a repaired prospectively frozen campaign. Do not use to claim that B7
is a validated universal framework or that M4-M6 are calibrated.
