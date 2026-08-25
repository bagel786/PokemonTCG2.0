> **Review-package transcription.** Restricted labels and local paths are neutralized. The statistical plan and identifiers are preserved, but these bytes are not the frozen source artifact. The original finite-population paired-bootstrap interval and secondary exact-McNemar language remains visible below and records the frozen case-study plan. The current Level-6 fixed-battery descriptive-only restriction is a later, post-acquisition conservative reporting rule: it is not frozen provenance and is not evidence that the claim taxonomy was prospectively validated. Future adopters must freeze that taxonomy and its uncertainty rules before acquisition. Statements about noninspection are protocol conditions; Git proves commit ordering, not when a human inspected uncommitted files. Historical statements below about package contents are not current availability claims: the package actually distributed is defined by the release manifest, README, processed metadata, and PROTOCOL_DEVIATIONS.md, which omit unverifiable first-divergence positions, actors, and timing summaries.

# Frozen prospective protocol: Paired Evaluation Validity Ladder

Status: frozen before any PEVL trace-preflight, timed-search stress-test, or
five-opponent factorial result is generated or inspected.  The Git commit that
first contains this protocol is the protocol commit.  Subsequent amendments
must be appended here with a timestamp, reason, and a statement of which results
were available; the original text must not be replaced.

## Scientific question and admissible novelty

This study evaluates a fail-closed validity ladder for seed-matched comparisons
of black-box game-playing agents.  It does not claim to discover that common
random numbers can fail, and it does not treat identical-control parity as proof
of cross-arm event-level coupling.  The contribution is an operational workflow
that records artifacts and the exact engine seed, validates schedules, tests
identical-arm and repeat/worker trace reproducibility, audits stochastic sources,
and suppresses paired contrasts when their prespecified admission gates fail.

The framework distinguishes:

1. artifact identity;
2. seed-namespace integrity;
3. schedule parity;
4. identical-arm record parity;
5. repeat and worker parity;
6. stochastic-source audit;
7. cross-arm event alignment; and
8. statistical admission.

The restricted engine exposes a seeded entry point but not event identifiers or
independent event-keyed streams.  Therefore no game-engine experiment in this
protocol can pass Level 7.  A passing factorial is reported as a finite-population,
seed-matched paired comparison, not as a fully coupled counterfactual or a
general common-random-number guarantee.

## Frozen artifacts

All tree digests use the evaluator's canonical SHA-256 tree algorithm, excluding
`__pycache__` and `.pyc` files.  A byte mismatch invalidates the affected run.

| Role | Label | SHA-256 |
|---|---|---|
| seeded engine | engine | `867e3f9bb87e0b48889a44b5d4b04f5d2d434b2a0788d1b2bcfe0caebcb5ab78` |
| production sentinel | production engine | `7a157f045d333f99d1996d49c12bdbdd148072a619af246385c7295518776e30` |
| blind encoder, original weights | C1 | `13426288358d597ead809e45c364c7f7b9274a6eebf55ddd942142e3326535c3` |
| identity encoder, original weights | C2 | `36e804ae6c593db57b595bfca9fd48592da10957f0e5f840a7e390edbeb39b63` |
| blind encoder, trained weights | C3 | `236afa20b4ced63169736fea616849fa564281c05e9435e4dd77ecfb4ae5fd54` |
| identity encoder, trained weights | C4 | `83489e0c80c631763c65375d2a7a34d28d6aa9fbb1d11e89d130c83b1e27f1c0` |

The five determinism-eligible opponent packages are a newly defined target
population selected before this protocol from the prior repeated-control audit.
They are not a probability sample of the competition field.

| Index | Opponent label | SHA-256 | Environment |
|---:|---|---|---|
| 0 | deterministic-1 | `0c15b56adf3b09c654505a152309fdc9f8401579a495da714347d98ae735003c` | `{}` |
| 1 | deterministic-2 | `7db753d6610930d8bd9694b4b9bece5ac48733b825422a3e399c18077b55e64e` | `{}` |
| 2 | deterministic-3 | `8a06ebab47cc60ed981dfada85972eb8a62e732e349f01c2a3085262079f06e8` | `{}` |
| 3 | deterministic-4 | `30e45955b67893514c8ee077cac15d46fc207efe781cbce1b94242defda4cbdc` | `{}` |
| 4 | deterministic-5 | `5d44338891094988ca15f0c26d5187316549facd64a7bfbac04aa0048424e8c7` | `{"NO_SEARCH":"1"}` |

The timed-search diagnostic population contains timed-search-A
(`1b73779da7dcc93c8f121090bb0f1ae2d9b10b798ca4c70447b0ce1d6d01c0db`)
and timed-search-B
(`076ae8de12d2d6c4a170b47b2d2f9cf538c1d318a05bb2e81f13da9be2cd2026`).
They are analyzed separately and are never added to the factorial population.

## Seed namespaces and schedule construction

Each result must record the scheduled Python integer, the conversion rule
`scheduled_seed & 0xffffffff`, and the exact unsigned 32-bit seed passed to the
engine.  Every scheduled seed below is already in `[0, 2^32-1]`; conversion must
therefore leave it unchanged.  The evaluator must fail before execution if any
converted seed collides within an acquisition schedule.

Actual order `first` uses `base_seed + i`; actual order `second` uses
`base_seed + 1_000_000 + i`.  Physical seat is `i mod 2` and is identical for
all arms sharing a seed-condition unit.

### Four-arm trace preflight

The preflight uses `i=0,...,24` for each order.  Base seeds are:

| Opponent | Base seed |
|---|---:|
| deterministic-1 | 2026072700 |
| deterministic-2 | 2026073700 |
| deterministic-3 | 2026074700 |
| deterministic-4 | 2026075700 |
| deterministic-5 | 2026078700 |

Each C1--C4 arm is executed once serially, again in a fresh serial pool, and
once with eight workers.  The process start method is `spawn`.  For each
arm/opponent/order/seed condition, the public-observation/action trace digest,
terminal result, error counts, and decision count must agree across all three
executions.  The preflight contains 1,000 seed-condition trajectories and 3,000
games.  Any mismatch invalidates the entire five-opponent factorial before its
large schedule begins.  Mismatches remain reportable PEVL evidence.

### Timed-search repeat/worker stress test

The stress test uses C1 only and `i=0,...,49` for both orders.  timed-search-A has base
seed `2026092700`; timed-search-B has base seed `2026093700`.  Each opponent/order/seed
condition is executed four times: a fresh one-worker pool in forward enqueue
order, a fresh one-worker pool in reverse enqueue order, a fresh four-worker
pool in forward enqueue order, and a fresh four-worker pool in reverse enqueue
order.  Full restricted traces are retained locally for divergence
localization; the review package contains digests, first-divergence positions
and actors, decision counts, terminal outcomes, errors, and timing summaries.

The primary endpoint is whether all four complete public-state/action trace
digests agree.  Secondary endpoints are first divergence position and acting
side, decision-count disagreement, terminal-outcome disagreement, and error
disagreement.  The seed-condition, containing all four executions, is the
statistical and resampling cluster.  Repeated executions are not independent
observations.  Results are stratified by opponent and actual order; worker-count
and enqueue-order comparisons are diagnostics rather than randomized hardware
effects.

### Five-opponent four-cell factorial

The factorial is admitted only after the four-arm trace preflight passes in
full.  C2, C3, and C4 are each evaluated against a separately executed C1
control using the tested paired runner.  Each of the five opponents has 200
pairs per actual order, for 400 paired units and 800 games per candidate-control
file.  The complete design contains 15 files, 2,000 common seed-condition units
per cell, and 12,000 games.

Base seeds are:

| Opponent | Base seed |
|---|---:|
| deterministic-1 | 2026082700 |
| deterministic-2 | 2026083700 |
| deterministic-3 | 2026084700 |
| deterministic-4 | 2026085700 |
| deterministic-5 | 2026086700 |

The fixed settings are both actual orders, eight workers, `spawn`, and a 2,000
decision cap.  No unit is excluded after execution.  A policy error, opponent
error, decision-cap exception, incomplete schedule, engine or package hash
drift, production-sentinel mutation, converted-seed collision, or schedule
mismatch invalidates the factorial.  In addition, the C1 outcome, draw, errors,
and decision count must agree across the C2, C3, and C4 files on all 2,000 common
units.  One mismatch suppresses every planned factorial contrast.

## Estimands and uncertainty

Losses and draws are zero in the win indicator.  Each estimate is the equally
weighted mean of the ten opponent-by-actual-order stratum means.  The primary
factorial contrast is the fixed-package total intervention `C4-C1`.  Secondary
factorial estimands are:

* representation main effect: `0.5 * ((C2-C1) + (C4-C3))`;
* training main effect: `0.5 * ((C3-C1) + (C4-C2))`;
* representation-by-training interaction: `C4-C3-C2+C1`.

Simple effects are reported descriptively to interpret an interaction.  The
95% intervals use 100,000 paired resamples within each of the ten strata with
seed `2026083117`.  Exact two-sided McNemar inference for the primary binary
contrast is secondary.  Secondary factorial intervals are estimation-focused;
they do not receive binary success labels.  No equivalence claim is made when
an interval includes zero.

The timed-search disagreement proportions use 100,000 cluster bootstrap draws
over seed-condition units with seed `2026083118`.  A single trace mismatch is
enough to falsify exact reproducibility for the exercised schedule, but rates
and intervals quantify how often the diagnostic occurred in this finite test.

## Synthetic validation and representation case study

A fully open synthetic simulator is analyzed before the restricted-engine case.
It contains clean deterministic, stateful draw-shift, wall-clock search,
process-global-state, and 32-bit seed-conversion modes.  It also implements an
event-keyed counter-based remedy for draw-shift.  Its role is to show which PEVL
levels detect each known failure and to make the framework independently
executable; it is not used to tune the game-engine gates.

The action-representation case remains a treatment example.  The manuscript
must distinguish a missing option--item relational binding from literal
within-state action-vector collision, of which the retained corpus contains
zero.  Offline recorded-action agreement and earlier temporal/oracle results
are appendix diagnostics and never substitutes for gameplay or validity gates.

## Stopping, reporting, and claim admission

Runs stop only after every scheduled task completes or an invalidating execution
error occurs.  There is no effect-based optional stopping, seed replacement,
opponent deletion, or rerun chosen after inspecting an estimate.  Operational
retries caused by an interrupted machine must retain the incomplete artifact and
use a new run UUID; they do not silently overwrite it.

Reporting is fail closed:

* trace-preflight failure: suppress the factorial and report the failure;
* factorial acquisition or repeated-C1 failure: suppress every factorial
  contrast and report the invalidating record;
* stress-test trace parity: report the exercised schedule as repeatable without
  claiming Level 7 event alignment;
* stress-test trace divergence: reject exact reproducibility for that
  opponent/condition and retain all outcomes, including equal terminal results;
* any passing game experiment: use `seed-matched` and finite-population wording;
* no game experiment: use `causally coupled`, `counterfactual`, or full-CRN
  wording unless event-level alignment is independently established.

The restricted engine, opponent code, deck/card material, and full traces are
not redistributed.  Processed row-level outcomes, safe trace diagnostics,
protocols, analysis code, and the open synthetic simulator are included subject
to the corresponding author's rights and license approval.
