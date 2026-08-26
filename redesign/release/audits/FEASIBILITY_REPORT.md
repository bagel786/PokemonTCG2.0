# Feasibility Report

**Date:** 2026-08-26
**Question:** Can a prospective empirical study add something beyond existing CRN theory, paired-seed statistics, replay infrastructure, metamorphic testing, A/A diagnostics, and V&V practice?

## Verdict: FEASIBLE — proceed toward protocol freeze

The feasibility audit examined (a) whether open systems with the required properties exist, (b) whether scenarios S0–S10 can be injected in a controlled labeled manner, (c) whether all 13 utility metrics are computable with known ground truth, (d) whether runtime is tractable, and (e) whether prior work leaves the evaluation question open (see `NOVELTY_AUDIT.md`).

## 1. Open systems exist (licenses verified 2026-08-26)

| Requirement | Game/agent system | Scientific system |
|---|---|---|
| Candidate | OpenSpiel (`google-deepmind/open_spiel`) | ising-monte-carlo-toolkit (`ddsyasas/ising-monte-carlo-toolkit`) |
| License | Apache-2.0 (verified via GitHub API license endpoint) | MIT (verified by decoding LICENSE blob) |
| Seeded interface | Yes; stochastic games incl. Pig, Can't Stop, Backgammon, Le Her | Yes (`--seed`); documented same-seed-same-results determinism |
| Source available | Yes | Yes |
| Raw trace access | Yes (Python API; wrapper emits per-step event logs) | Yes (wrapper emits per-sweep observables) |
| Semantic events definable | Yes (chance outcomes keyed by state/action/step) | Yes (spin proposals / cluster builds keyed by sweep/site) |
| Failure injectable | Yes (harness-level RNG interception) | Yes (same mechanism) |
| Many replications | Yes (episodes in milliseconds) | Yes (32x32 Metropolis runs in seconds) |
| Known limitations | Python API slower than C++; some games need builds | Young project (2026); Numba optional dependency |

Third system preferred but conditional on pilot budget: PettingZoo (Apache-2.0) or Mesa ABM (BSD-3). Selection rationale: OpenSpiel is the standard academic games/RL substrate; Ising MC is canonical statistical physics where CRN/pairing questions are native practice. Neither was chosen solely for convenience.

**Final selection note (pre-freeze):** the executable campaign subsequently used
RLCard limit hold'em 1.2.0 rather than the feasibility-stage OpenSpiel candidate,
as recorded in `protocol/SYSTEM_MANIFEST.json`. RLCard is MIT-licensed; its
initial Apache-2.0 label was corrected during the release rights audit (D007).

## 2. Failure scenarios injectable at harness level

All eleven scenarios S0–S10 are implementable as declared transformations of the **evaluation harness**, not of the underlying systems:
- S1/S2/S4/S5/S6 (namespace conversion, extra draws, clock-bounded computation, module state, worker queues): deterministic by construction inside the wrapper.
- S3: event-keyed repair via counter-based RNG keyed on declared event IDs.
- S7: schedule-row dropping.
- S8/S9/S10: analysis-side designs (benign residual randomness with valid repeated-measures inference; pseudoreplication; honest unpaired design).
Ground-truth labels for all six claim dimensions follow from construction rather than from observed outcomes.

## 3. Metrics computable

Each of the 13 metrics reduces to: a proportion with binomial uncertainty over labeled scenarios (detection, false-suppression, missed-failure), frequency calibration under simulated reference distributions (coverage/type-I/power/MCSE), an estimator-variance ratio against known truth (CRN variance reduction), cost measurement (runtime/storage/acquisition overhead), countable configuration decisions (human complexity), or cross-system rank agreement (consistency). Definitions are predeclared before outcome acquisition.

## 4. Runtime budget

Pilot estimates to be confirmed by the result-excluded smoke test: OpenSpiel Pig episodes ~1–10 ms → full grid (11 scenarios x 8 methods x seeds x repeats) well under one CPU-hour; Ising 32x32 x 2,000 sweeps ~1–3 s per run → grid under ~2 CPU-hours. Total campaign fits a laptop budget; no cluster dependency. Exact N fixed at sample-size planning (P8) using pilot timing only, never pilot outcomes.

## 5. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Ising toolkit too young/unstable | Pin commit; fallback to own minimal Metropolis/Wolff implementation under CC0 with identical interface (declared in protocol if invoked) |
| Wrapper RNG interception misses native C++ draws | Use Python-side chance-event interception points documented in SYSTEM_SELECTION_MATRIX; verify by S0 replay test before freeze |
| Baselines strawmanned | B0–B6 designed as best-effort honest alternatives; B5 hierarchical analysis implemented competently; study precommits to reporting any baseline win |
| Novelty erodes between now and submission | Re-run NOVELTY_AUDIT search pass at manuscript stage |
| Overclaiming from two systems | Claims scoped explicitly to "two open systems"; generalization discussed qualitatively only |

## 6. What would have made this infeasible

Recorded for honesty: no redistributable seeded game environment with trace access (false); no open stochastic scientific simulator (false); metrics requiring human adjudication of thousands of cases (not the case); prior work already performing strategy-vs-strategy evaluation with false-suppression accounting (checked — not found).
