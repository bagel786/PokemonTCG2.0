# Equation Audit

Status: implementation fixtures pass; confirmatory M4-M6 equations not claimed.

## E1 - Detection and false suppression

- Equations: `p_det=x_det/n_inv`; `p_fs=(x_soft+x_hard)/n_valid`.
- Symbols/units: all x and n terms are counts of decision cells; p terms are
  dimensionless proportions.
- Sign/indexing: larger detection is desirable; smaller false suppression is
  desirable. NOT_APPLICABLE and DOWNGRADE labels are excluded from these two
  denominators.
- Toy example: 38 detections in 40 invalid cells gives 0.95.
- Implementation: `complete_analysis.summarize_decision_group`.
- Independent test: `independent_reaggregate.py` reproduces all Branch-B B5/B7
  numerators and denominators without production imports.
- Verdict: **PASS**.

## E2 - Wilson 95% score interval

- Equation: with `p=x/n`, `z=1.959964`, denominator `q=1+z^2/n`, center
  `(p+z^2/(2n))/q`, half-width
  `z*sqrt(p(1-p)/n+z^2/(4n^2))/q`.
- Symbols/units: x and n are counts; p, q, center, and half-width are
  dimensionless.
- Toy example: x=38, n=40 gives p=0.950 and interval [0.835, 0.986].
- Implementation: `analyze.py:wilson` and `complete_analysis.py:wilson`.
- Independent test: `interval_checks.py` implements the equation separately.
- Sign/indexing: invariant `0 <= x <= n`; D002 repaired the production
  denominator, D003 separated DOWNGRADE misses from hard-invalid misses, and
  D008 transparently corrected the remaining protocol-document transcription.
- Verdict: **PASS AFTER LOGGED REPAIR**.

## E3 - Two-proportion contrast

- Equation: `z=(p1-p2)/sqrt(ptilde(1-ptilde)(1/n1+1/n2))`, where
  `ptilde=(x1+x2)/(n1+n2)`; two-sided normal tail.
- Units: all terms dimensionless.
- Toy example: x1=30/40, x2=20/40 gives pooled p=0.625 and a positive z because
  method 1 has the larger rate.
- Implementation: `complete_analysis.two_prop_p`; Holm step-down is applied over
  the frozen primary family actually run.
- Independent check: counts and direction can be reconstructed from
  `method_contrasts.csv`; no separate p-value implementation was used.
- Assumption failure: methods classify identical cells, so proportion estimates
  are dependent. The frozen z test is retained as secondary and is not a primary
  evidentiary claim.
- Verdict: **FORMULA PASS; SAMPLING ASSUMPTION CAVEAT**.

## E4 - CRN variance ratio

- Equation: `d_i=A_i-B_i`; `d'_i=A_i-B_(i+1 mod n)`;
  `R=s2(d)/s2(d')`.
- Units: A/B/d retain chips or mean-absolute-magnetization units; variances use
  squared units; R is dimensionless.
- Toy example: A=(4,3,2), B=(1,1.5,1) gives d=(3,1.5,1) and
  d'=(2.5,2,1). This fixture explicitly checks B indexing and the A-B sign.
- Implementation: `complete_analysis.variance_outputs`.
- Independent test: `interval_checks.py` verifies paired and cyclic arrays.
- Interval: `log(R) +/- z*sqrt(4/(n-1))`, exponentiated. The independence
  assumption is approximate because paired and re-paired differences reuse one
  outcome bank; split-half sensitivity is emitted.
- Edge case: hold'em S3 has R=0 and no log interval. The plot labels exact zero
  rather than inventing a finite interval.
- Verdict: **PASS WITH DECLARED SHARED-BANK LIMITATION**.

## E5 - Monte Carlo standard error

- Equation: `MCSE=sqrt(phat*(1-phat)/B)`.
- Units: dimensionless rate over B resamples.
- Toy example: phat=0.05, B=2000 gives about 0.00487.
- Implementation: `complete_analysis.statistical_diagnostics`.
- Boundary: outputs are post-freeze centered/bootstrap diagnostics because the
  known-truth banks are missing. A correct MCSE does not upgrade the estimand.
- Verdict: **ARITHMETIC PASS; CONFIRMATORY INTERPRETATION FORBIDDEN**.

## E6 - Kendall tau-b

- Definition: concordant-minus-discordant pair ordering with tie correction.
- Units: dimensionless rank association in [-1,1].
- Unit/indexing: method is the paired item; hold'em and Ising provide the two
  score vectors in identical B0-B7 order.
- Implementation: SciPy `kendalltau(..., variant='b')`.
- Toy interpretation: identical order gives +1; reverse order gives -1.
- Boundary: n=8 methods and only two systems; M1-M2 is an ordering device, not a
  probability or commensurate utility.
- Verdict: **PASS WITH EXTERNAL-VALIDITY LIMIT**.

## Missing planned equations

Clopper-Pearson coverage intervals and cluster-bootstrap hierarchical intervals
were promised but are not used in confirmatory prose because their required
outcome banks were not retained. They are marked not estimable, not silently
replaced.
