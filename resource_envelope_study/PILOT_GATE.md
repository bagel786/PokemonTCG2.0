# Pilot gate

## Current decision

**PENDING — no Azure pilot has been run.**

The 24-case macOS run in `runs/smoke_local/` is an implementation smoke only.
It had 24/24 terminal games, 1,793/1,793 `ok` search decisions, zero cleanup
failures, and exact fixed work, but it had one matched block, no Linux affinity,
and no inferential value. It cannot satisfy any scientific gate.

APS scope is **NO-GO (provisional)** until every Ising Day-1 gate below passes.
This is not a final venue decision.

## Binding classification rule

After the disjoint Azure pilot, classify the study once as `GO`, `NARROW`, or
`STOP`. Do not change thresholds after final outcomes.

| Check | GO | NARROW | STOP |
|---|---|---|---|
| Load manipulation | ≥20% relative wall-work reduction; same direction in ≥16/20 paired batches and ≥2/3 agents | 10–20% or only one responsive agent | <10%, unstable sign, or noncompliant load |
| Fixed-work correctness | Exact `N`, no clock branch, all designated semantic hashes identical | not available | Any mismatch or partial result |
| Action response | ≥10 pp loaded-idle excess divergence for ≥2 agents | 5–10 pp or one agent | <5 pp for all agents |
| Illegal/crash | zero | not available | any unresolved event |
| Deadline fallback | ≤0.5% of eligible decisions | 0.5–1% | >1% |
| Instrumentation | paired 90% equivalence interval for throughput ratio within [0.95, 1.05], fixed-work action hash exact | [0.90, 1.10] only after reducing instrumentation before a new bank | outside [0.90, 1.10] |
| Overshoot | p99 ≤10% of deadline and maximum ≤25% | reduce atomic-unit granularity before a new bank | remains above bounds |
| Matchup | each retained agent score in [0.20, 0.80] | replace/exclude one agent before freeze | fewer than three valid agents |
| Clusters | ≥20 paired load batches and ≥20 relevant persistent sessions | narrow factors/claims before freeze | inflate rows while below cluster minimum |
| Power | ≥80% at 10 pp under exact clustered scheduler and multiplicity | narrow confirmatory family and recompute | proceed underpowered |
| Runtime | 1.5× pilot p95 projection finishes with ≥24 h analysis reserve | prospectively reduce scope | no analysis reserve |
| Agent distinctness | three distinguishable latency/work and quality curves | replace one agent before new bank | effectively identical included agents |
| Accounting | every scheduled case and observed decision has one terminal status; totals reconcile | not available | any unexplained duplicate/missing/mismatch |

`NARROW` is prospective: generate a new disjoint manifest and document the
reduced claim before freeze. It is not permission to select favorable agents or
outcomes from the same bank.

## Ising Day-1 gate

APS remains `NO-GO` unless all pass:

- exact fixed-sweep count and no clock-dependent fixed-sweep branch;
- deterministic clean-process replay;
- `m ∈ [-1,1]` and energy/spin `∈ [-2,2]`;
- tiny-lattice exact-enumeration agreement;
- long-run/reference agreement at `T=1.5`, `T_c`, and `T=3.5`;
- split `R-hat ≤ 1.01` for frozen observables;
- frozen ESS and MCSE thresholds met by independent chains;
- ≥20% loaded reduction in completed deadline sweeps; and
- instrumentation throughput effect ≤5%.

Failure is reported; no physics narrative will be fabricated.

## Pre-pilot issues already resolved

- Alakazam `SIMULATION_CAP` was rejected as fixed work because nested clocks
  remain active.
- Historical MCTS root coverage was not reused because it can exceed configured
  simulations.
- V2 S4 was rejected because it is deterministic truncation, not wall-clock
  resource assignment.
- The V2 per-draw Philox/dictionary ledger is absent from the timed path.
- A native transient-card reconciliation defect found by full-game smoke was
  fixed before pilot; the failed smoke is not evidence.
- Flat-rollout depth was reduced from 96 to 16 using only atomic-unit latency
  and overshoot, before pilot outcomes were inspected.

## To fill from the authorized Azure pilot

- exact pilot manifest/hash and protocol implementation commit;
- engine build/source/compiler hashes;
- load compliance and manipulation estimates;
- deadline-selection whitelist and hash;
- calibrated `N_a` values and rounding audit;
- same-state replay/repeatability result;
- instrumentation equivalence interval;
- overshoot distribution;
- fallback/error/accounting rates;
- matchup/cost-quality screens;
- cluster-aware power and runtime projection; and
- final `GO`, `NARROW`, or `STOP` decision with reasons.
