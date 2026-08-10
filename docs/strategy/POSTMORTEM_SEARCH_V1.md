# Forensic Search Postmortem — V1

**Deliverable:** §2.2 of the Opus 4.8 Plan. **Status:** DRAFT for user review. No repair of the
Director is proposed or permitted by this document.
**Authority:** all numbers reproduced from checked-in artifacts and source; file paths cited inline.

---

## 0. Bottom line

The Director's kill screen is reproduced exactly from the checked-in artifact
(`artifacts/turn_director/confirmation/kill_screen.json`): **control 54.35% vs treatment 52.95%**
over 2,000 games/arm, `passed: false`, **0 policy errors**. The decisive, non-obvious finding is in
the row-level data, not the headline:

> **When the Director actually intervened (1,240 games) it won 50.97%. When it abstained and returned
> the baseline (758 `incomplete_world_coverage` fallbacks) it won 56.18%.** The interventions were the
> part that lost — not the coverage gaps. The Director's own complete-turn decisions were *worse than
> the baseline they replaced.*

This reframes the failure: it is **not** a coverage bug to patch, nor a runtime bug (0 policy
errors). The evaluator/search picked worse lines when it fired, mostly on setup turns (interventions
concentrated on turns 1–3). Per the plan, **no attempt is made to repair the Director**; the matrix in
§4 routes each component to validate / reuse / retire.

---

## 1. Kill-screen reproduction (Director)

Source: `artifacts/turn_director/confirmation/kill_screen.json` (4,000 rows; candidate archive
sha256 `4b8438…12cb4`). Aggregated with a 20-line reader; every figure below is recomputed from the
rows, not copied from the summary block (they agree).

### Headline (matches the plan's "52.95% vs 54.35%")

| Arm | Games | Win rate | Uplift vs control | One-sided 95% lower |
|---|---|---|---|---|
| Control (baseline) | 2,000 | **54.35%** | — | — |
| Treatment (Director-routed) | 2,000 | **52.95%** | **−1.40 pts** | **−3.99 pts** |

`passed: false`, `policy_errors: 0`, `intention_to_treat: true`, engine randomness
`independent_unpaired`. Opponents split ~evenly across three lineages: `master_v1`, `replay_refresh`,
`v2_2` (~1,334 rows each).

### By actual play order

| Order | Control | Treatment | Uplift | Lower |
|---|---|---|---|---|
| Actual **first** | 57.30% (1021g) | 56.49% (979g) | −0.81 | −4.45 |
| Actual **second** | 51.28% (979g) | 49.56% (1021g) | −1.72 | −5.40 |

Negative on both orders; worse on the second (harder) seat.

### The row-level smoking gun (compliance-stratified)

| Treatment subset | Games | Win rate |
|---|---|---|
| **Complied** (Director's line was played) | **1,240** | **50.97%** |
| Fell back: `incomplete_world_coverage` | **758** | **56.18%** |
| (other non-complied) | 2 | — |

Intervention win rate (51.0%) sits **below** control (54.35%); abstention win rate (56.2%) sits
**above** it. The 758 coverage fallbacks are exactly the plan's "758/2,000 incomplete-coverage
treatment games" — but they were the *healthy* part of the arm. The intention-to-treat average
(52.95%) is dragged down by the 1,240 games the Director actually steered.

**Where it intervened:** `selected_turn` among complied games concentrates on turns **1–3**
(472 + 529 + 168 = 1,169 of 1,240). The Director fired mostly on setup/early turns — the same phase
§5.3 of the strategy doc identifies as decisive — and made them *worse*, consistent with a board
evaluator that misprices early development.

---

## 2. Director defect audit (mechanism, confirmed from source)

Each defect the plan enumerates, confirmed against `ptcg_ai/director.py` (and `DirectorConfig`,
lines 149–182). These are **causes of the §1 result**, not a repair list.

| # | Defect (plan) | Confirmed in source | Consequence |
|---|---|---|---|
| 1 | **One-reply horizon** | `DirectorConfig.horizon = "turn_reply"` — hero turn → one opponent reply | Cannot see the *next* hero turn; the plan's mandated horizon is hero→opp→hero. Blind to two-turn prize routes. |
| 2 | **Incomplete-turn leaves** | leaves scored when node allowance exhausts (`max_nodes_per_world=300`), not only at completed turns | Compares partial turns; violates "score only completed-turn/terminal boundaries." |
| 3 | **Unordered selection enumeration** | `enumerate_complete_actions` builds action sets without canonical ordering of simultaneous selections | Same semantic turn enumerated inconsistently across siblings → unfair candidate comparison. |
| 4 | **Grim-specific evaluator** | `_board_vector` / `ko_pressure` / `prize_value` are Marnie-Grim tuned (`MARNIE_LINE_IDS`) | Not deck-general; can't transfer to the reasoner's target of a deck-general architecture. |
| 5 | **Immediate-prize priority** | lexicographic `_board_vector` leads with prize/KO pressure | Greedy on immediate prizes — the §6.3/§6.4 counterexample failure (bench-snipe anti-pattern, prize-value blindness). |
| 6 | **Circular pruning** | frontier sorted by `_board_vector` then pruned by the same vector | Prunes toward what the evaluator already prefers → confirmation, misses non-greedy lines. |
| 7 | **Heuristic / worst-case opponent** | `_adversarial_reply_vector` (worst-case reply), `GrimmsnarlHeuristic` rollout | Unconditional minimax reply, not a plan-posterior-weighted opponent → over-pessimistic, mis-ranks. |
| 8 | **Exact-list assumption** | `determinize_state(obs, hero_deck, opponent_deck, rng)` uses the **exact** opponent deck | Offline-only truth leaking into evaluation; not live-faithful (opponent deck is hidden at runtime). |
| 9 | **Absent override calibration** | fixed trigger/threshold (`trigger`, no calibrated margin) | The plan's removed "+3%" style rule; no calibrated value-margin/uncertainty gating → fires when it shouldn't (see §1: interventions lose). |
| 10 | **300-s one-shot runtime** | `hard_timeout_seconds=300.0`, `cleanup_seconds=295.0`, single planning attempt | Whole-budget one-shot, not the plan's bounded 13.5/15 s attempts, ≤6/game, killable worker. |

The §1 compliance data is the empirical signature of defects **5–9 acting together**: a greedy,
Grim-tuned, worst-case-opponent, one-reply evaluator that fired without calibration and picked worse
early-turn lines.

---

## 3. Legacy search audit (each component separately)

Audited from source docstrings/headers and config. None is proposed for repair; each gets a verdict
in §4.

### 3.1 Selective 1-ply forward search — `ptcg_ai/search.py`
*"Selective 1-Ply Forward Search Policy for Live Competition Agent."* Scores each legal option one
step ahead against a heuristic. **Assessment:** genuinely finds the **B1** bucket (attack offered but
turn ended — 1-ply, clean, 1.9× loss skew per strategy §5.3) but is structurally blind to **B2b**
(n-ply: attach→retreat→attack looks bad at 1-ply). Cheap and safe. The `determinize_state`/
`search_begin` harness it shares with the Director is **reusable** (it is what certified B2b —
`CERTIFICATION_91427733_B2b.md`).

### 3.2 One-prompt selective proof search — `ptcg_ai/proof_search.py`
*"Fail-closed selective proof search around an externally supplied policy action … a one-prompt
diagnostic. All root candidates are stepped as siblings from one native search root, so they share
one [world]."* Never calls the d842 model; the baseline action is the fallback on every failure.
**Assessment:** the **information boundary and fail-closed discipline are exactly right** and match
the plan's contracts (frozen policy decides; search only overrides on proof; baseline fallback). Its
horizon (one prompt, siblings from one root) is too shallow to plan a turn, but the *pattern* is a
keeper.

### 3.3 Runtime terminal proof — `ptcg_ai/runtime_proof_director.py`
*"Fail-closed runtime proof for immediate, deterministic game wins … only replaces [the action] when
a bounded native sibling comparison proves one semantic alternative wins at this prompt in every
public-information determinization. It … does not score nonterminal positions, continue through later
prompts, inspect an opponent deck, or retain option indices."* **Assessment:** **the model citizen.**
It respects every information boundary the Director violates (no opponent deck, no index caching,
public-information determinizations only, terminal-only). Narrow (immediate wins only) but correct.
The plan's runtime should keep this as the innermost lethal-check layer.

### 3.4 MCTS teacher — `training/mcts_teacher.py`
*"Generic information-set PUCT teacher for training-only opponents … contains no deck/card tactics …
samples hidden worlds … covers every bounded legal root action … adversarial PUCT over the engine
forward model. Neural checkpoints are priors/value/rollout, never the final policy."* **Assessment:**
**training-only, and correctly scoped as such.** It is not a runtime component and the plan does not
put MCTS at runtime (it mandates belief-state beam/expectimax). Value as a **data/opponent generator**
and as a source of value targets; explicitly *not* a runtime policy. Evaluated by
`training/evaluate_search_teacher.py` (seat-balanced qualification).

### 3.5 Authentic Alakazam search / league — `training/candidate_b_gates.py`, `external_alakazam_benchmark.json`
An **authentic external opponent** (Alakazam) used as an evaluation league
(`--authentic-league`, `--authentic-games 200`). **Assessment:** not a search *policy* at all — it is
an **evaluation opponent**. Reusable and valuable: the plan's benchmark needs authentic
(non-self-play) opponents to avoid over-fitting to the mirror. Keep as an eval fixture.

---

## 4. Validate / Reuse / Retire matrix

| Component | Source | Verdict | Rationale / disposition |
|---|---|---|---|
| **Turn Director** | `ptcg_ai/director.py` | **RETIRE** | Kill screen `passed:false`; interventions 51.0% < baseline 54.35% (§1). Defects 1–10 are structural, not bugs. No repair per plan. |
| Director's `determinize_state` + `search_begin` fork harness | `ptcg_ai/search.py` helpers | **REUSE** | Correct, deck-agnostic engine-fork plumbing; already certified B2b. Foundation for the new belief-state search. |
| Lexicographic board evaluator (`_board_vector`) | `director.py` | **RETIRE** | Grim-specific, immediate-prize-greedy (defects 4–6); the counterexample failures of strategy §6. Replace with the interaction-first value of the new architecture. |
| Selective 1-ply search | `ptcg_ai/search.py` | **VALIDATE** | Keep for the **B1** rule only (clean, cheap); measure lift on B1 regression set. Not a turn planner. |
| One-prompt proof search | `ptcg_ai/proof_search.py` | **REUSE (pattern)** | Adopt its fail-closed / frozen-policy / baseline-fallback discipline as the override *contract*; extend horizon. |
| Runtime terminal proof | `ptcg_ai/runtime_proof_director.py` | **REUSE** | Keep as-is as the innermost lethal-check; it already honors every information boundary. |
| MCTS teacher | `training/mcts_teacher.py` | **REUSE (training-only)** | Data/opponent/value-target generator. Never a runtime policy. |
| Search-teacher eval | `training/evaluate_search_teacher.py` | **REUSE** | Seat-balanced qualification harness for teachers. |
| Authentic Alakazam league | `training/candidate_b_gates.py` + json | **REUSE** | Authentic external opponent fixture for the benchmark. |

---

## 5. What the postmortem tells the architecture

1. **Abstention was fine; intervention was the problem.** The new reasoner must clear a *higher* bar
   than "beat the coverage gaps" — its interventions must be net-positive, which the plan enforces via
   the calibrated override controller (defect 9) and matched-world evaluation.
2. **Setup turns are where it fired and failed.** Early-development valuation (strategy §5.3) is the
   evaluator's hardest and highest-leverage job; the retired lexicographic evaluator got it wrong.
3. **Every information boundary the Director crossed (exact opponent deck, one-reply worst-case,
   index caching) is already respected by `runtime_proof_director.py`** — the correct patterns exist
   in-repo and are reused, not reinvented.
4. **No component is both a runtime policy and correct except the terminal proof.** The new
   belief-state beam/expectimax search is genuinely new work; the reused parts are plumbing (fork
   harness), discipline (fail-closed contract), and fixtures (teachers, authentic league).
