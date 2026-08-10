# Strategy Ontology & Interaction Model — V1

**Deliverable:** §2.1 of the Opus 4.8 Plan. **Status:** DRAFT for user review. Specification only —
no implementation.
**Grounding:** every entity maps to the engine's public observation (`cg.api`, strategy doc §2) and
carries (evidence source, uncertainty, counterfactual question, measurable outcome), per the plan.

---

## 0. Design commitments

1. **Interaction-first, not score-first.** The unit of analysis is the *interaction between two
   evolving game plans*, not a bag of independently-weighted predictions (the retired Director's
   failure, `POSTMORTEM_SEARCH_V1.md` §2). Damage/threat/prize/development are **evidence** consumed by
   the interaction, never standalone scalars to maximize.
2. **Public-information closure.** Every entity is a function of public observation + legal engine
   continuations + posterior beliefs over hidden information. Hidden truth enters *only* via
   posterior-sampled worlds; two positions with identical public evidence must yield identical
   planner inputs (strategy §8 hidden-information control).
3. **Falsifiable by construction.** Every concept has a *measurable outcome* against replays/engine so
   the benchmark (§2.4) can score it, and a *counterfactual question* so its causal role is testable
   by matched-world intervention rather than assumed.

---

## 1. Core entities

Each entity: **definition · public evidence · uncertainty · counterfactual question · measurable
outcome**. Names align with the plan's V1 contracts.

### 1.1 `PublicBeliefStateV1`
- **Def.** Public board/history + a posterior over legal deck-hypotheses for each player, with
  explicit unknown-deck mass and unseen-card distributions.
- **Evidence.** `Observation.current` (board, prizes, hand *counts*, discard, stadium),
  `Observation.logs` (revealed plays), deck-handshake nonexistent for opponent (hidden).
- **Uncertainty.** Categorical posterior over archetypes (strategy §4.0 as prior) + per-zone unseen
  card distributions; a reserved **unknown-plan / unknown-deck** probability mass that never collapses
  to zero.
- **Counterfactual.** "If the hidden truth were world *w′* with the same public evidence, do the
  planner inputs change?" (Must be: only via posterior sampling.)
- **Outcome.** Calibration of the deck-hypothesis posterior vs revealed decks in replays (Brier /
  log-loss); coverage of the true deck within top-k.

### 1.2 `StrategicGamePlanV1` (per player)
- **Def.** One player's win condition, current objective, milestones, resource prerequisites,
  attacker schedule, intended prize route, protected/expendable assets, counterplans, recovery
  branches, failure conditions, probability, evidence.
- **Evidence.** Archetype posterior (§1.1) → the profile in strategy §4/§5; board realization of
  milestones (bodies, energy, evolutions) from `current`.
- **Uncertainty.** Probability over *which* plan the player is on (top-2 recall is the benchmark gate);
  explicit unknown-plan mass.
- **Counterfactual.** "If prize count / readiness / engine availability changed, does the inferred
  plan change?" (strategy §8 — must move the *relevant* plan, not unrelated predictions).
- **Outcome.** Top-2 plan recall ≥85%, milestone/target accuracy ≥80%, calibration ≤0.10 (plan §5
  gate).

### 1.3 `ThreatVectorV1` (per Pokémon)
- **Def.** Contextual, multi-dimensional threat — **never** collapsed to one HP-like scalar (strategy
  §6.5). Dimensions: attack readiness / immediate pressure; prize leverage & liability; draw/search
  throughput; energy acceleration; disruption reach; mobility/heal/protect/recovery; scaling/closer;
  dependency centrality & replacement time; current interaction leverage (invested damage, target
  access).
- **Evidence.** Card metadata (`all_card_data`, `all_attack`), attached energy, damage-on, board role.
- **Uncertainty.** Per-dimension estimate with confidence; target-access probability is itself
  uncertain (gust availability).
- **Counterfactual.** "What is the effect of damaging / removing / trapping / **ignoring** this
  Pokémon under the current pair of plans?" — target priority *is* this counterfactual, not a fixed
  weight.
- **Outcome.** Per-dimension rank correlation ≥0.70 vs labels; acceptable target-priority ≥80%
  (plan §5).

### 1.4 `DamageForecastV1`
- **Def.** Conditional + belief-marginalized distributions for next-turn direct / bench / passive /
  moved damage, with attacker & target identity distributions and KO probability.
- **Evidence.** Attacker card attacks/costs, attached energy, opponent plan posterior, immunity table
  (strategy §3.2 — **checked first**; effect/counter damage is zero through walls).
- **Uncertainty.** Full distribution (10/50/90 percentiles), conditional per opponent-plan hypothesis;
  source attribution.
- **Counterfactual.** "If the opponent is on plan *p* vs *p′*, how does the incoming-damage
  distribution shift?"
- **Outcome.** CRPS / log score, KO Brier (primary gates); ≥15% CRPS improvement, 80% intervals cover
  75–85%, conditional median abs err ≤20 HP (plan §5). Point error is interpretability only.

### 1.5 `PrizeRouteDistributionV1`
- **Def.** Distribution over terminal prize routes (signatures like `2→2→2`, `1×6`, `3→3`), timing,
  resource requirements, fragility, race-win probability — the real scoreboard (strategy §3.1, §6.4).
- **Evidence.** Remaining prizes, each Pokémon's prize class (1/2/3), invested damage, attacker
  readiness/replacement clocks, gust/target-access, engine/accel dependencies, recovery/heal/
  disruption availability, deck-out risk.
- **Uncertainty.** Distribution over routes + route-switch probability; robustness vs opponent
  counterplans.
- **Counterfactual.** "Does taking this KO now change the *route* or just the count?" (a 3-for-1 trade
  loses the race while 'ahead on KOs').
- **Outcome.** Top-2 route recall ≥85%, ≥15% Brier-skill lift over a frequency baseline, prize-event
  timing MAE ≤1 hero turn (plan §5).

### 1.6 `PlanInteractionV1`
- **Def.** How a candidate complete-turn policy changes **both** players' plans, threats, tempo,
  resources, damage schedule, and prize routes — the central object.
- **Evidence.** Engine transition of the candidate (exact board/resource delta) + re-estimated
  opponent counterplan + projected leaf through the prize tail.
- **Uncertainty.** Over opponent responses (plan-posterior-weighted, with calibrated downside — *not*
  greedy minimax, the Director's defect 7).
- **Counterfactual.** The whole entity **is** a counterfactual: candidate vs baseline as complete
  causal plan changes, on identical hidden worlds + random schedules (matched-world).
- **Outcome.** Expert-acceptable plan comparison ≥85%; controlled counterfactual consistency ≥95%
  (plan §5).

### 1.7 `CompleteTurnPolicyV1`
- **Def.** An engine-validated *contingent* policy keyed by public-state digest, ending only at a
  completed turn or terminal state (the unit of planning — strategy §3.6).
- **Evidence.** Legal engine continuations from the root observation; canonical ordering of
  simultaneous selections (fixes Director defect 3).
- **Uncertainty.** Contingency over random events (coin flips, reveals) inside the turn.
- **Counterfactual.** "Does this policy remain legal & complete under re-resolution against the live
  observation?" (never cache raw indices — Director defect 10 / runtime rule).
- **Outcome.** 100% legal, 100% turn-complete or terminal at every scored leaf; zero policy errors.

### 1.8 `SearchDecisionV1` / `DecisionTraceV1`
- **Def.** The selected action or **abstention**, with calibrated evidence, coverage, uncertainty; the
  trace is the **sole** source of rendered explanations.
- **Evidence.** The interaction comparison (§1.6) + override controller verdict.
- **Uncertainty.** Calibrated candidate-better probability + downside bound.
- **Counterfactual.** "Would removing any single evidence head change the decision?" (ablation hook).
- **Outcome.** 100% trace-supported claims; ≥80% expert-recognizable causal explanations; override
  point-acceptance ≥90%, zero catastrophes (plan §5).

---

## 2. Supporting concept definitions

Mapped to the plan's ontology vocabulary; each is a projection of the entities above.

| Concept | Definition | Public evidence | Measurable outcome |
|---|---|---|---|
| **Win condition** | the terminal state a plan drives toward (take 6 prizes via route R / deck-out / bench-out) | archetype posterior + board | plan-inference recall |
| **Milestone** | a checkpoint prerequisite to the win condition (e.g. "3 Marnie's bodies + fuel by T4", strategy §5.3) | board realization | milestone accuracy ≥80% |
| **Tempo clock** | turns-until-attacker-online / turns-until-next-KO; every-turn vs every-other-turn schedules (strategy §4.5/§4.6) | attacker readiness, cooldown attacks | timing MAE ≤1 turn |
| **Resource** | energy in play, hand size, bench width, engine throughput, stadium slot | `current` counts | early order-robust correlation (strategy §8) |
| **Role** | attacker / engine / wall / pivot / disruptor / recovery (e.g. Munkidori & Froslass = bench engine, strategy §5.2) | card abilities + board position | role-conditioned target priority |
| **Threat** | contextual danger of a Pokémon → `ThreatVectorV1` | §1.3 | per-dim rank corr ≥0.70 |
| **Counterplan** | the opponent's disruption intent (gust / energy-deny / hand-attack / immunity / stadium-deny / weakness, strategy §7) | logs, board | opponent-plan recall |
| **Prize route** | `PrizeRouteDistributionV1` | §1.5 | route recall ≥85% |
| **Recovery path** | how a stalled plan comes back (attach→retreat→promote; recur attacker; heal via Munkidori) | legal continuations | B2b-class regression pass |
| **Failure condition** | the state that ends a plan (dead Active no attacker; weakness one-shot; effect-immune target; deck-out) | board + immunity table | failure-detection precision |

---

## 3. Interaction relations

Candidate policies update a **strategic interaction graph** using these typed relations (plan §3).
Each edge must be supported by an **engine transition** or a **matched-world intervention** — never an
asserted heuristic (the discipline the Director lacked).

| Relation | Meaning | Engine-observable support |
|---|---|---|
| `enables` | makes a later milestone reachable | resource/board delta unlocking a legal future action |
| `accelerates` | advances a tempo clock | attacker online ≥1 turn sooner |
| `protects` | reduces loss probability of an asset | removes a KO/gust/deny line for the opponent |
| `denies` | removes an opponent resource/throughput | energy/stadium/engine piece removed |
| `forces` | compels an opponent action | only-legal or dominated opponent response |
| `exposes` | increases an asset's loss probability | opponent gains a KO/prize line |
| `recovers` | restores a stalled plan | dead→active attacker, heal, retreat-unlock |
| `converts-to-prizes` | realizes route progress | KO taken / lethal set up on the prize tail |

**Reasoning sequence per candidate** (plan §3, restated as the ontology's evaluation loop):
infer both plans (§1.2) → apply candidate through engine, record exact deltas (§1.7) → update the
interaction graph (§3 relations) → re-estimate opponent counterplan (§1.6) → search
hero→opp→hero (§2.3 architecture) → project the leaf through the prize tail (§1.5) → compare candidate
vs baseline as complete causal plan changes (§1.6).

---

## 4. Anti-patterns this ontology forbids (traceable to the postmortem)

| Forbidden | Why | Enforced by |
|---|---|---|
| A single scalar board value | Director defect 4–6; strategy §6 counterexamples | `ThreatVectorV1` is a vector; value is an interaction, not a number |
| Immediate-prize / most-damage greed | strategy §6.3 (B4 anti-corr), §6.4 (prize value) | `PrizeRouteDistributionV1` scores *routes*, not counts |
| Worst-case unconditional opponent | Director defect 7 | plan-posterior-weighted responses + calibrated downside |
| Exact opponent deck at runtime | Director defect 8; strategy §8 | `PublicBeliefStateV1` posterior only; hidden truth via sampling |
| Cached raw option indices | Director defect 10 | `CompleteTurnPolicyV1` re-resolves semantically each call |
| Explanations not backed by a trace | plan §5 explanation gate | `DecisionTraceV1` is the sole explanation source |

---

## 5. Open questions for the architecture (§2.3) and benchmark (§2.4)

- The exact **posterior representation** for deck/plan hypotheses (parametric vs particle) — deferred
  to §2.3, gated by the calibration outcome in §1.1/§1.2.
- The **prize-tail model** granularity (strategic-event transitions, strategy §5.4) — deferred to §2.3.
- Which entities get **ablation heads** in the benchmark (opponent-plan, prize-tail, threat
  decomposition, interaction propagation each must show confidence-bounded lift or be removed — plan
  §5) — specified in §2.4.
