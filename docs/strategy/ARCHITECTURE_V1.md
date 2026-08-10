# Strategic-Interaction Architecture Specification — V1

**Deliverable:** §2.3 of the Opus 4.8 Plan. **Status:** DRAFT for user review. Specification only —
**no implementation is authorized by this document** (plan gate: code begins only after competency +
all four docs are approved).
**Depends on:** `ONTOLOGY_INTERACTION_V1.md` (entities), `POSTMORTEM_SEARCH_V1.md` (what to reuse/
retire), `STRATEGY_RESEARCH_V1.md` (strategy grounding).

---

## 0. Invariants (non-negotiable, from the postmortem)

1. **The frozen d842-plus-rails policy is always the decision-maker by default.** The reasoner may
   only *override* it, and only on calibrated proof of positive interaction value. Every failure path
   returns the exact baseline action. (Reuses `runtime_proof_director.py` / `proof_search.py`
   fail-closed discipline — `POSTMORTEM` §3.2–3.3.)
2. **Interventions must be net-positive, not merely present.** The kill-screen lesson: the Director's
   *interventions* lost (51.0% vs 54.35%) while its abstentions were fine (`POSTMORTEM` §1). The
   override controller (§6) is the gate that enforces this.
3. **Public-information closure & no index caching.** Opponent deck is never known; hidden truth
   enters only via posterior worlds; semantic actions are re-resolved against the live observation
   every call (fixes Director defects 8, 10).
4. **Score only completed-turn or terminal boundaries.** No partial-turn leaves (fixes defect 2).
5. **Search runs in a killable worker with hard time bounds.** No 300-s one-shot (fixes defect 10).

---

## 1. Component map & data flow

```
 agent(obs_dict)
   │
   ├─ 1. Sanitize + baseline action  ──────────────►  a_base  (frozen d842 + rails; ALWAYS computed first)
   │
   ├─ 2. Pivotal-state gate ──────────────────────►  if not pivotal → return a_base
   │
   ├─ 3. PublicBeliefStateV1  (posterior over decks/plans)          [ontology §1.1]
   │
   ├─ 4. Candidate generation  (semantic complete-turn policies,    [§4]
   │        always incl. a_base's exact policy)
   │
   ├─ 5. WORKER (killable): belief-state beam/expectimax             [§5]
   │        for each candidate:
   │          infer both plans → apply via engine → interaction graph
   │          → opponent counterplan → hero→opp→hero search
   │          → prize-tail projection → PlanInteractionV1 vs baseline
   │
   ├─ 6. Calibrated override controller  ─────────►  select a_cand or ABSTAIN  [§6]
   │
   ├─ 7. DecisionTraceV1  (sole explanation source)                 [ontology §1.8]
   │
   └─ return  a_cand  if override fires and re-resolves legal, else a_base
```

**Information boundaries (hard walls):**
- Steps 1–2 use only the live observation.
- Step 3 may read logs/board/discard (public) and the archetype prior; **never** the opponent's hand
  or deck.
- Step 5 (worker) receives posterior-sampled worlds only; the *same* hidden worlds and random-event
  schedules are used for sibling roots (paired evaluation of candidates), but full-game promotion
  statistics use independent unpaired games (plan §6.4).
- Steps 6–7 read only the worker's `PlanInteractionV1` outputs; the override never re-derives from
  hidden state.

---

## 2. Contracts (typed, versioned)

All defined in `ONTOLOGY_INTERACTION_V1.md` §1. Versioned `…V1`; new fields append-only (the engine
appends enum members mid-competition — never switch exhaustively without a default, per ENGINE.md).

`PublicBeliefStateV1 · StrategicGamePlanV1 · ThreatVectorV1 · DamageForecastV1 ·
PrizeRouteDistributionV1 · PlanInteractionV1 · CompleteTurnPolicyV1 · SearchDecisionV1 ·
DecisionTraceV1`.

Auxiliary models (allowed by the plan; d842 stays frozen) produce the *evidence* heads
(`StrategicGamePlanV1`, `ThreatVectorV1`, `DamageForecastV1`, `PrizeRouteDistributionV1`). They are
**inputs** to the interaction, never independent additive scores (ontology §0.1; the Director's fatal
pattern).

---

## 3. Pivotal-state gate (step 2)

Search only at **calibrated pivotal main-phase states** (plan §4 runtime). A state is pivotal iff:
- it is a `SelectContext.MAIN` decision, **and**
- the baseline policy's action is *contestable* — the calibrated candidate-better probability upper
  bound exceeds the override floor for at least one generated candidate.

Non-pivotal states return `a_base` with zero worker cost. The gate is calibrated on
development/calibration data (§2.4 splits), not hand-set. Budget: ≤6 planning attempts per game.

---

## 4. Candidate generation (step 4)

Candidates are **semantic equivalence classes of contingent complete-turn policies** (ontology §1.7),
always including the exact d842-plus-rails policy.

- **Empirical width per decision family.** Measure candidate recall + runtime at widths
  `{4,8,12,16,24,32}` for development / targeting-damage / switching / recovery / sequencing
  positions. Freeze the smallest width that: includes an expert-acceptable line on ≥95% of
  development/calibration positions; no stratum <90%; <1 pt gain from the next width; fits its runtime
  share (plan §4). If none qualifies → improve generation, don't widen indefinitely.
- **Runtime enumeration** in batches of 4. Early-stop only when: calibrated remaining-candidate
  probability <5%, required plan families are represented, and no unseen candidate's UCB can satisfy
  the override controller. Reaching the cap without those → **abstain** (return baseline).

---

## 5. Explicit search (step 5, in the worker)

- **Algorithm:** belief-state **beam / expectimax**, not MCTS (MCTS is training-only — `POSTMORTEM`
  §3.4). Reuses the `determinize_state` + `search_begin(manual_coin=True)` fork harness (`POSTMORTEM`
  §4, already certified in `CERTIFICATION_91427733_B2b.md`).
- **Horizon:** completed current hero turn → completed opponent turn → completed next hero turn (fixes
  Director's one-reply horizon, defect 1).
- **Opponent model:** continuations weighted by the **plan posterior** with **calibrated downside
  constraints** (CVaR-style), *not* greedy/unconditional minimax (fixes defect 7). Maintains explicit
  unknown-plan mass.
- **Determinism control:** identical hidden worlds and random-event schedules for sibling roots
  (paired). `manual_coin=True` for evaluation, sampled schedules across worlds for marginalization.
- **Leaf scoring:** only terminal or completed-turn boundaries; each leaf projected through the
  **prize-tail model** (§5.1).
- **Abort → baseline:** unequal coverage across siblings, incomplete turns, nondeterminism, cleanup
  failure, or budget exhaustion returns `a_base` (the coverage fallback that was *healthy* in the kill
  screen — `POSTMORTEM` §1).

### 5.1 Prize-tail model (beyond the search horizon)
At each search leaf, run a stochastic **strategic-event** model (plan §3): state = remaining prizes,
per-Pokémon prize liability, invested damage, attacks-to-KO, attacker readiness/replacement clocks,
gust/target-access probability, engine/accel dependencies, retreat/heal/recovery/disruption/protection
availability, board-extinction & deck-out risk. Transitions are *strategic events* (attacker takes
prizes; engine removal delays readiness; damaged liability retreats; recovery restores an attacker;
forced one-prizer switches route), not card-by-card actions. Terminate at terminal / 12 combined prize
events / explicit unresolved-tail. Returns route signature, timing distribution, race-win probability,
route-switch probability, robustness vs counterplans (→ `PrizeRouteDistributionV1`).

---

## 6. Calibrated override controller (step 6)

Removes the fixed "+3%" rule (Director defect 9). Calibrated on development/calibration data + ≥2,000
engine-certified candidate pairs (plan §4):

1. Calibrate strategic-value and candidate-better probabilities via nested held-out folds.
2. Sweep thresholds on value margin, uncertainty, downside, belief-entropy, ensemble-agreement.
3. **Reject** any threshold set with a catastrophic override, non-positive lower CI on tactical swing,
   expert-acceptability Wilson lower bound <80%, or mean regret >2 win-probability points.
4. Select the survivor with highest override coverage; ties → lower regret, then latency.
5. Freeze before sealed evaluation.

"No threshold qualifies" is a **valid** result → runtime stays baseline-only. No per-matchup
thresholds unless that stratum has ≥200 calibration examples; unsupported strata abstain.

---

## 7. Runtime, isolation, fallback (steps 5–7 operational)

- **Time:** 13.5 / 15 s soft/hard per attempt; 81 / 90 s cumulative per game; ≤6 attempts/game.
  (Well inside the engine's 600 s budget; leaves margin for the frozen baseline's own cost.)
- **Isolation:** native search in a **killable worker process**; parent always holds `a_base` and a
  deadline. Worker death / timeout → baseline.
- **Re-resolution:** semantic actions re-resolved against the current observation every call; **never**
  cache raw indices (a stale digest / invalid action / hidden-info violation → disable search for that
  game, return baseline).
- **Parity:** ship the Kaggle-provided `cg/`; diff before every submission (ENGINE.md parity note).

---

## 8. Explanations (step 7)

`DecisionTraceV1` is the **sole** source of rendered explanations (plan §5 explanation gate: 100%
trace-supported, ≥80% expert-recognizable). An explanation is a causal chain of §3 interaction
relations, each edge backed by an engine transition or matched-world intervention, e.g.:

`damage Mega Lucario (engine: 180 to 340HP) → forces heal/retreat (opponent only-legal survival) →
delays Mega Brave clock by 1 (tempo) → improves our 2→2→2 race-win prob (+Δ from prize tail)`.

No claim may appear in an explanation that is not an edge in the candidate's interaction graph.

---

## 9. What is new vs reused (from the postmortem matrix)

| Layer | Disposition |
|---|---|
| Frozen d842 + rails baseline | **frozen** (unchanged decision-maker) |
| Engine-fork harness (`determinize_state`/`search_begin`) | **reuse** |
| Terminal lethal proof (`runtime_proof_director.py`) | **reuse** as innermost check |
| Fail-closed override contract (`proof_search.py` pattern) | **reuse pattern**, extend horizon |
| 1-ply B1 rule (`search.py`) | **validate & keep** narrowly |
| Belief-state beam/expectimax + interaction graph + prize tail | **NEW** (this spec) |
| Evidence heads (plan/threat/damage/route models) | **NEW** aux models (d842 frozen) |
| Calibrated override controller | **NEW** (replaces fixed threshold) |
| Lexicographic Grim board evaluator | **retired** (do not port) |
| MCTS teacher, authentic Alakazam league | **reuse training/eval only** |

---

## 10. Failure-mode table (every path returns a legal action)

| Condition | Action |
|---|---|
| Non-pivotal state | `a_base` |
| No qualifying candidate width | improve generation offline; runtime abstains → `a_base` |
| Incomplete/unequal coverage, nondeterminism, cleanup fail | `a_base` |
| Worker timeout / death | `a_base`, disable search for the game |
| Stale digest / invalid action / hidden-info violation | `a_base`, disable search for the game |
| Override controller: no threshold qualifies | baseline-only runtime |
| Budget (attempts/time) exhausted | `a_base` |
| Any exception anywhere | sanitized `a_base` (never let an illegal answer escape — COMPETITION.md) |
