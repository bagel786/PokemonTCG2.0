# Resource Envelopes Change the Realized Policies of Time-Limited Search Agents

## Protocol status

**DRAFT — NOT FROZEN — FINAL ACQUISITION FORBIDDEN**

This document belongs to branch `paper/resource-envelope-search-20260826`,
created from exact commit `af1504c149d462c152eec18472661a844b58988a`.
That commit is an implementation checkpoint, not a protocol freeze. Historical
V1/V2 code and results are exploratory only and are not resumed or validated by
this study.

The protocol becomes operative only when all `TO FREEZE` entries are resolved,
`FREEZE_MANIFEST.json` says `FROZEN`, a protocol-freeze commit is pushed, and the
human author explicitly approves that commit. A scientific-code defect after
freeze invalidates all affected results; repair requires a documented new
freeze and a complete rerun.

## Frozen scientific question and bounded claim

Question:

> When search agents receive the same wall-clock deadline, how much do
> controlled external CPU contention and process lifecycle change completed
> search work, selected actions, and relative performance—and are those effects
> reduced under matched fixed-work execution?

Permitted primary claim, if supported:

> On the tested platform, external resource envelopes can change the realized
> work, policy, and performance of time-limited search agents; matched
> fixed-work runs quantify how much of that sensitivity is consistent with
> variation in completed search work.

The study will not claim that time-versus-fixed-work comparison is new, that
fixed work is universally fairer or correct, hardware-independent
reproducibility, universal generalization, identified causal mediation, or a
rank reversal without simultaneous intervals supporting practically opposite
pairwise signs.

## Scope and contribution

The contribution under test is the combined, controlled measurement chain:

1. assigned same-core CPU contention and bounded process lifecycle;
2. a common work-boundary interface for deadline and exact-work stopping;
3. completed work and forward-model-call telemetry;
4. paired same-state semantic action divergence; and
5. paired game-score effects and stopping-mode attenuation.

The seven-paper audit in `NOVELTY_MATRIX.md` is not an exhaustive priority
search. The paper will use “we study” or “the tested combination,” never
“first,” unless a later exhaustive review justifies that wording.

## Tested game system

### Matchup and fixed anchor

All search configurations use the tracked Grimmsnarl deck and feature-v2 model
from `artifacts/grim_final_escape/candidate/` against one fixed, deterministic,
no-search neural anchor using the same deck/model. The exact deck, model,
engine-source, engine-binary, and adapter hashes will be frozen. The anchor is
not allowed to perform forward search and therefore cannot acquire a second,
uncontrolled time budget.

The evaluation-only engine is built from
`freshstart/engine/ptcgProgram/Export.cpp`. Its `BattleStartSeeded` entry point
controls gameplay RNG; `SearchSetSeed` clears the search arena and resets the
native search RNG before an independent root. This binary is for private
evaluation only, is not a production replacement, and will not be redistributed
or packaged with a submission.

### Three search configurations

The agents are intentionally algorithmically distinct and are not production
submissions:

| ID | Algorithm | Declared atomic work unit | Frozen pre-pilot bounds |
|---|---|---|---|
| `one_ply_value_v1` | Flat one-ply neural value search | One independently seeded determinization, fresh root, candidate transition, and leaf-value evaluation | eight root candidates |
| `flat_rollout_v1` | Flat policy rollout search | One independently seeded determinization, fresh root, candidate transition, and at most 16 deterministic-policy rollout steps | six root candidates; depth 16 |
| `puct_tree_v1` | Incremental adversarial PUCT | One tree simulation and backpropagation; the first unit also creates the seeded root | eight root candidates; depth 32; `c_puct=1.5` |

The 16-step rollout bound replaced a 96-step smoke configuration solely because
the latter's atomic-unit latency produced unacceptable deadline overshoot. No
game outcome or action effect was used for that change. Any further algorithm
change requires a new pilot bank.

Work units are agent-specific scientific quantities, not equal compute across
agents. Forward-model calls, created nodes, wall time, and process CPU time are
reported separately.

### Search-budget boundary

Observation conversion, legal-candidate enumeration, model loading, and
case-state reset occur before the measured search budget. The deadline begins
immediately before the first declared atomic unit. Native root construction is
inside a flat-search unit and inside the first PUCT unit. Action selection and
mandatory cleanup occur after the work loop and are separately observable.

This estimand is **incremental search-kernel work under a deadline**, not total
end-to-end agent response latency. The limitation will be explicit in the
manuscript.

## Stop-policy contract

`FixedWorkStop(N)` performs exactly `N` successfully completed units. It has no
clock dependency. An exception, partial unit, or inability to reach `N` makes
the case `fixed_work_invalid`; the partial policy is not treated as a valid
fixed-work outcome.

`WallClockStop(T)` reads a monotonic clock only at the same pre-unit boundary.
The currently running unit is allowed to finish. Overshoot is therefore bounded
empirically by atomic-unit latency, not asserted to be zero.

Both modes always attempt native cleanup. Every observed search decision and
every scheduled game receives exactly one terminal status. Agent-caused
fallbacks remain in intention-to-treat outcomes; infrastructure failure
invalidates the complete matched vector and may be replaced only by a frozen
reserve manifest.

## Resource-envelope intervention

### Platform

Heavy simulation is restricted to the authorized Azure `Standard_D8s_v6`
worker (8 vCPU, approximately 32 GiB). Exact CPU model, virtualization, kernel,
OS image, compiler, Python ABI, package hashes, frequency/temperature interfaces,
VM uptime, and engine hash are `TO FREEZE` from that worker.

Fresh process does not mean fresh VM. VM reboot state is held fixed and recorded;
the week-scale VM uptime observed during planning is not silently interpreted as
steady state.

### Load assignment

On Linux, the benchmark child and one independently spawned CPU co-runner are
pinned to the same frozen logical CPU. The co-runner executes an integer
recurrence without filesystem, network, BLAS, or engine access. `idle` means no
study co-runner; it does not mean zero operating-system activity.

A load batch is one independently launched loaded episode plus its paired idle
period. Idle-loaded order is deterministically randomized AB/BA per pair. The
worker seed, PIDs, affinity compliance, load average, available frequency and
temperature telemetry, start/end times, and exit codes are retained. A dead or
noncompliant co-runner invalidates the entire assigned matched load period.

Final acquisition requires at least 20 independent paired load batches. The
load manipulation must reduce wall-clock completed work by at least 20%, with a
stable pre-registered directional criterion in `PILOT_GATE.md`.

### Lifecycle assignment

Lifecycle means runtime warmth only:

- `fresh`: one OS-spawned Python process per game;
- `persistent`: one independently spawned process runs at most `K=8` cases.

Persistent sessions are nested within load batch, load condition, agent, and
budget mode. Between cases they reset gameplay, search arena, agent RNG,
determinization RNG, per-game counters, and case state. Imports, immutable model
weights, native card tables, allocator state, and ordinary runtime caches may
remain warm. Fresh rows receive the same pseudo-sequence slot as their matched
persistent rows. Sequence index is retained.

Fixed-work semantic state/seed/action hashes must agree across fresh/persistent
and idle/loaded cases. Any unexplained mismatch is a STOP condition. Final
lifecycle claims require at least 20 independently restarted relevant persistent
sessions and cluster-aware power; otherwise lifecycle is descriptive secondary
analysis.

## RNG separation

SHA-256 domain separation creates independent persisted streams for:

- environment/gameplay RNG;
- agent/determinization and native-search RNG;
- schedule/execution-order RNG; and
- load-condition/co-runner RNG.

No Python `hash()` value is persisted. Schedule shuffling uses a study-owned
SHA-256/rejection-sampled Fisher-Yates algorithm. RNG schedules are generated
outside timed paths. The V2 per-draw Philox constructor/dictionary ledger is not
used in a timed path.

## Design and assignment

The primary factorial is:

- agent: three levels;
- budget mode: wall-clock/fixed work;
- load: idle/loaded; and
- lifecycle: fresh/persistent.

One matched block contains all 24 cells. It fixes environment seed, physical
seat, and actual first/second play order across conditions. Physical seat and
play order form four balanced strata. Condition execution order is randomized
within each load period without outcomes. Common seeds cease to imply common
trajectories after policies diverge; matching remains an assignment device, not
a claim of identical stochastic events.

The independent unit for game inference is the complete seed/seat/play-order
block, not a row, action, decision, or repeat. Load batch and persistent session
are higher assignment clusters. More within-cluster rows cannot replace missing
clusters.

## Outcome-blind deadline and work calibration

The calibration bank is disjoint from the gate pilot and final bank. Candidate
deadlines are `TO FREEZE` before acquisition (provisional set: 10, 25, 50, and
100 ms). The selector receives only agent/config ID, requested deadline,
completed units, forward-model calls, setup/search latency, process CPU time,
overshoot, binding indicator, and terminal validity. It rejects action, value,
score, win, regret, rank, and trajectory fields.

The deterministic selection rule will choose the smallest candidate satisfying
all frozen latency/work requirements, including nonzero useful work for all
agents, overshoot limits, and projected runtime with analysis reserve. If none
qualifies, the pilot stops and the atomic unit must be redesigned before a new
bank.

After the deadline hash is frozen, an independent idle/fresh wall-clock bank
sets one integer `N_a` per agent to the median completed units. All eligible
attempts, including zero/partial deadline attempts, enter the median. For even
sample sizes, take the arithmetic mean of the two middle counts and round
half-up. The same `N_a` is then used across load and lifecycle levels. These are
agent-specific typical idle/fresh deadline budgets, not universal fairness.

## Frozen-state repeatability panel

Approximately 100 public decision states will be sampled from approximately 100
independent source games, at most one state per source game. Pilot and final
state IDs are disjoint. Each state/agent/envelope combination receives ten
repeated executions across independently restarted resource sessions.

The engine's `search_begin_input` is an opaque, raw-memory-derived serialization
and is not a portable semantic fingerprint. Exactly one captured opaque string
is therefore frozen per panel state and reused without decoding, normalization,
masking, or recapture. The canonical capture artifact stores the original ASCII
bytes, their byte count and SHA-256, the public semantic hash, an embedded state
artifact hash, and the complete-file SHA-256. Every scientific load requires the
expected complete-file digest and rejects noncanonical JSON bytes.

Two distinct checks must not be conflated. Independent clean-process recapture
is judged on exact public semantic state/history plus fixed-work outputs; opaque
byte identity is neither expected nor used to replace the frozen artifact. The
binding replay gate instead loads the **same frozen artifact** in two clean
processes. For all three agents and five frozen agent seeds at fixed `N=8`, state
hash, semantic action hash, completed work, terminal status, and cleanup status
must match. Any mismatch, any changed opaque byte/hash/count, or any artifact
hash mismatch is `STOP`: the panel is dropped and the study cannot make a
same-state action-divergence claim. The pre-freeze Linux finding and source audit
are recorded in `OPAQUE_SERIALIZATION_AUDIT.md`.

Actions are hashed by selected option semantics, not only option index.
Persistent states appear at a frozen sequence slot after a frozen history
prefix. Within-envelope disagreement and loaded-minus-idle excess divergence are
both reported at the state-cluster level. Repeats and repeat pairs are not
independent.

## Estimands

Game score is `1` for win, `0.5` for draw, and `0` for loss. For agent `a`,
lifecycle `c`, and the frozen block population:

1. wall-clock load effect on work (ratio of means, never pooled across agents):
   `R_work[a,c] = E(W_loaded,T) / E(W_idle,T) - 1`, where `W` is the
   per-game mean completed work per eligible search decision. A valid game
   with zero eligible search decisions has `W=0`; it remains in its matched
   block. The zero-decision game rate and a descriptive sensitivity excluding
   a complete load pair when either game has zero eligible decisions are both
   reported, but the sensitivity never replaces the primary estimand;
2. wall-clock load effect on score:
   `Delta_T[a,c] = E(S_loaded,T - S_idle,T)`;
3. fixed-work load effect on score:
   `Delta_F[a,c] = E(S_loaded,F - S_idle,F)`;
4. stopping-mode attenuation contrast:
   `Gamma[a,c] = Delta_T[a,c] - Delta_F[a,c]`; and
5. same-state loaded-minus-idle excess semantic action-divergence probability.

The confirmatory family is exactly these five equal-agent-weighted endpoints
for each of `fresh` and `persistent`, for ten endpoints total. Agent-specific
work units are never pooled: each agent's loaded/idle ratio of block-equal
per-game means is calculated first, and the three dimensionless ratios are
then averaged with equal weight. The other endpoints likewise average the
three agent-specific estimates with equal weight.
Agent-specific load effects are simultaneous secondary estimates. Lifecycle
contrasts, sequence trends, rank correlation, high-work-reference regret, and
pairwise rank contrasts are secondary unless cluster-aware pilot power promotes
a specific contrast before freeze.

No ratio such as `1 - Delta_F/Delta_T` is interpreted as a mediated fraction.
Attenuation is described as associational evidence consistent with completed
work differences.

## Sample size and power

The final block count is `TO FREEZE` from a simulation of the exact
batch-to-common-session-bundle-to-block scheduler using pilot-estimated joint
endpoint distributions, batch/session cluster variance, batch/session/block
attrition, runtime plus analysis reserve, and the frozen ten-endpoint
multiplicity correction. Every retained confirmatory endpoint must have at
least 80% simulated power at its frozen smallest effect of interest; the score
SESOI is 10 percentage points. A simple unclustered paired
binary approximation can already require about 385 pairs when discordance is
0.5; therefore 200–300 blocks will not be used merely because they were an
initial target. Equivalence at true zero requires its own 80% operating
characteristic. If feasible runtime cannot support the required independent
blocks, the confirmatory family is prospectively narrowed or the result is an
inconclusive pilot. The current score-only power artifact explicitly sets
`freeze_authorized=false` and `NARROW_OR_EXTEND`; it cannot authorize the
ten-endpoint family even if its score endpoint alone exceeds 80%. Retaining all
ten requires pilot-frozen joint distributions and per-endpoint/minimum power;
otherwise the family must be narrowed prospectively before protocol freeze.

## Analysis

Primary estimates are complete matched-block contrasts. The resampling hierarchy
follows assignment: paired load batch, nested persistent session where relevant,
then complete matched block vectors. Cells/rows are never independently
bootstrapped. With approximately 20 top-level pairs, a restricted randomization
or wild-cluster sensitivity analysis is required.

The ten confirmatory endpoints use Bonferroni familywise 95% coverage: every
member interval has 99.5% coverage. The eight main-game endpoints are
recomputed together on each common paired-load-batch, nested-session-bundle,
complete-block resample, including the nonlinear agent-specific work ratios.
The two action-divergence endpoints resample independently sourced frozen states
only, never repeats or repeat pairs. This Bonferroni construction is used
because game blocks and frozen states are different inference-unit populations
and cannot share one defensible max-T resample. Common-resample max-T intervals
may be used for coherent secondary families drawn from one population. A null
supports invariance only when the entire simultaneous interval lies within a
frozen outcome-specific equivalence margin. Otherwise it is inconclusive.

A supporting score model may use a clearly identified linear mixed model for
`0/.5/1` score, or a binomial/logistic model only if draws are handled by a
frozen rule. It includes `agent * budget_mode * load`,
`agent * budget_mode * lifecycle`, four-level seat/order stratum, and sequence
slot, with random effects matching actual nesting. Work counts are modeled
separately. Singular-fit and convergence handling are frozen before outcomes.

A rank reversal requires pairwise intervals from the same joint simultaneous
artifact to lie wholly beyond the frozen ±5-percentage-point tie margin with
opposite signs in the two envelopes. Marginal intervals from separate analyses
cannot establish reversal. Kendall correlation with three agents is descriptive.

`analysis.py` is the sole final raw-to-summary driver. It accepts canonical
JSON/JSONL only, requires caller-supplied file SHA-256 values, recomputes every
per-record artifact hash, reconciles every result and episode to a
scientifically complete atomic commit, binds both raw journals through outcome
hash manifests, and checks the exact final schedule and repeatability inventory
before reading outcomes. It derives intervals from its own content-hashed
bootstrap evidence; arbitrary caller-supplied intervals cannot be wrapped as a
frozen publication summary.

`reaggregate.py` may use only released raw data and the schedule; it must not
import the production analysis module. It independently recomputes all ten
headline point estimates, the zero-decision convention and sensitivity, and
every reported block/batch/case/state/source/repeat inventory count. Every
manuscript headline point and count must reproduce from that program.

## Missingness, exclusions, and terminal accounting

No completed-case deletion is allowed.

- agent timeout, search error, illegal action, and fallback remain assigned-arm
  intention-to-treat events;
- fixed work not reaching exactly `N_a` is protocol invalidity;
- infrastructure or load noncompliance invalidates the complete matched vector;
- replacement uses only a pre-frozen reserve manifest and retains the failed
  artifact; and
- unreplaced confirmatory cells require worst-case bounds or `DO_NOT_SUBMIT`.

Every scheduled case must have one and only one game terminal status. Every
observed search call must have one and only one decision status. Per-game work,
simulations, nodes, sweeps, forward calls, and decision hashes must reconcile
exactly with per-decision records.

## Pilot gates

The binding table is in `PILOT_GATE.md`. Gates cover manipulation strength,
fixed-work correctness, action response, illegal/crash/fallback rate,
instrumentation equivalence, overshoot, matchup floor/ceiling, cluster count,
power, runtime reserve, agent cost/quality distinctness, and exact terminal
accounting. Gates are not retuned after final outcomes.

## Open Ising companion and APS scope

APS scope is provisionally `NO-GO` until the separate Day-1 gate passes. The
companion is a 2D ferromagnetic square Ising model with periodic boundaries,
`J/k_B=1`, random-scan single-spin Metropolis updates, and one sweep equal to
`L^2` attempted flips. Temperatures are frozen below, at, and above
`T_c = 2/log(1+sqrt(2))` (provisional `1.5`, `T_c`, `3.5`) and analyzed
separately. Burn-in is outside the measurement budget. Chains are independent.
Magnetization per spin is in `[-1,1]`; energy per spin is in `[-2,2]`.

The arm must pass exact tiny-lattice enumeration, clean-process deterministic
replay, normalized bounds, long-run/reference agreement, split `R-hat <= 1.01`,
frozen ESS/MCSE thresholds, at least 20% loaded work reduction, and at most 5%
instrumentation effect. Fixed time checks only at sweep boundaries; fixed sweeps
are exact. Failure leaves APS scope `NO-GO` and cannot rescue weak Pokémon
results.

## Reproducibility and disclosure

Before freeze the repository will contain disjoint calibration, gate-pilot,
repeatability, final, and reserve manifests; versioned schemas; environment and
engine build locks; raw/hash inventories; analysis; independent reaggregation;
plot code; and expected artifact inventory. Final figures accept only the
canonical frozen analysis summary plus its hash-bound plot-source inventory;
raw, unfrozen, or schema-drifted inputs are refused. SVGs and their manifest are
generated deterministically and every input/output file hash is recorded.

Generative AI is a tool, not an author. `AI_USE_DISCLOSURE.md` records the model
identifier if exposed by the product, tasks assisted, human direction, and the
verification applied to every substantive output. The human author must approve
the question, protocol, interpretation, manuscript, and submission.

## Venue decision rule

- APSOS only if the open physical-simulation arm and scope gate pass.
- TMLR only if the final contribution is substantively about learning-agent
  evaluation.
- SMPT if simulation experimental design is central.
- Otherwise `EXTEND_STUDY` or `DO_NOT_SUBMIT`.

No journal submission, Kaggle upload, preprint, or final acquisition is
authorized by this draft.
