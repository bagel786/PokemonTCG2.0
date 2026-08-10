# Strategic Benchmark Specification — V1

**Deliverable:** §2.4 of the Opus 4.8 Plan. **Status:** DRAFT for user review. Specification only.
**Freeze rule:** position IDs, rubric, splits, metrics, exclusions, and confidence methods are frozen
**before any training**; sealed answer keys live **outside** the implementation agent's context (held
by the user, the strategic adjudicator).

---

## 0. Purpose & separation of concerns

The benchmark gates the **product** (the reasoner), distinct from the competency exam that gates the
**designer** (`STRATEGY_RESEARCH_V1.md` §10). They share machinery (position representation, rubric,
scoring) — so the exam is built as a **subset split** of this benchmark (§1), which is why the user may
fold the exam into the development split rather than run it separately.

---

## 1. Position inventory (700, frozen)

| Split | N | Role | Key custody |
|---|---|---|---|
| Curriculum (worked) | 50 | fully-worked strategy examples (`STRATEGY_RESEARCH_V1` §9 seed + expansion) | open |
| **Blind competency exam** | 50 | designer gate; unseen during research | **user-held, sealed** |
| Development | 100 | visible; candidate-width & pivotal-gate tuning | open |
| Threshold / calibration | 100 | override-controller & posterior calibration | open |
| **Sealed evaluation** | **400** | product gate; permanently sealed | **user-held, sealed** |

**Sealed 400 structure:** 50 cells × 8 positions =
`5 matchup groups × 5 strategic-interaction families × 2 actual play orders`.

- **Matchup groups** (refreshed to the 2026-08-08 meta, `STRATEGY_RESEARCH_V1` §4.0):
  (1) Grimmsnarl mirror, (2) Grimmsnarl vs Alakazam, (3) Grimmsnarl vs Mega Lopunny, (4) Grimmsnarl vs
  the over-performing tail (Dragapult / Mega Lucario / Dipplin), (5) Grimmsnarl vs field/other. *(The
  plan's Mewtwo-heavy cells are dropped — Mewtwo fell to <1%; see §4.0.)*
- **Interaction families** (plan §5): setup→attacker conversion; tempo & prize-route trades; threat/
  engine-denial/targeting; damage-investment/pressure/forced-response; recovery/comeback/passing/
  non-greedy.
- **Both play orders** per cell (first / second) — the kill screen showed order-dependent effects
  (`POSTMORTEM` §1).

Positions are drawn from the mined corpus (`docs/strategy/annotation_corpus.jsonl`, 120 anchored
turns, 65 episodes) plus the 2026-08-08 top-rated export for non-mirror matchups and family-3 coverage
(the noted gap in the current corpus). **Low-confidence exclusions are replaced so the sealed set
stays exactly 400.**

### 1.1 Freezing & sealing mechanism
- Each position = a public-information observation digest (`public_state_hash`, `director.py`) + engine
  snapshot ref. IDs frozen in a manifest with sha256; manifest committed, **answer keys withheld**.
- The implementation agent receives *positions only*; the user holds the labels and runs scoring.
  Sealed labels never enter any prompt/context of the implementation agent (prevents leakage/overfit).

---

## 2. Label schema (per position)

Every label carries (plan §5): both game plans; milestones; prerequisites; acceptable complete-turn
**policy families** (equivalence set, not a single line); counterplans; decomposed threats
(`ThreatVectorV1`); probabilistic damage (`DamageForecastV1`); abstract prize routes
(`PrizeRouteDistributionV1`); causal reasoning; confidence; catastrophic alternatives (lines that must
never be chosen). Schema mirrors `STRATEGY_RESEARCH_V1` §9 + the ontology entities.

---

## 3. Component gates (sealed requirements — plan §5)

| Capability | Sealed requirement |
|---|---|
| Game-plan inference | top-2 plan recall ≥85%, milestone/target ≥80%, calibration ≤0.10 |
| Strategic interaction | plan-comparison ≥85%; counterfactual consistency ≥95% |
| Threat decomposition | per-dim rank corr ≥0.70; target priority ≥80%; no stratum <70% |
| Prize-route tail | top-2 route recall ≥85%; ≥15% Brier-skill lift vs frequency; timing MAE ≤1 turn |
| Damage distribution | ≥15% CRPS improvement; 80% intervals cover 75–85%; conditional MAE ≤20 HP (≤30 matchup ceiling) |
| Candidate generation | acceptable-line recall ≥95% overall, ≥90% per stratum at frozen width |
| Explanation | 100% trace-supported; ≥80% expert-recognizable causal |
| Overrides | point acceptance ≥90%; Wilson lower ≥80%; zero catastrophes; mean regret ≤2 pts; positive tactical-swing lower bound |

**Global blockers (any → fail):** an illegal line, a private-information assumption, a prize-count
error, or a catastrophic strategic misunderstanding on *any* position.

---

## 4. Ablations (each head must earn its place — plan §5)

Ablate independently: opponent-plan reasoning, prize-tail projection, threat decomposition,
interaction propagation. Each must show a **positive confidence-bounded improvement in its intended
strata**; otherwise **remove or redesign** it rather than keep a decorative prediction head (the
Director's failure was exactly a set of heads that didn't improve decisions — `POSTMORTEM` §2).

---

## 5. Metrics & confidence methods (frozen)

- **Distributional:** CRPS / log score (damage), Brier (KO, route), calibration error (ECE) with
  reliability diagrams.
- **Acceptability / recall:** proportion with Wilson score intervals; **Wilson lower bound** is the
  gate, not the point estimate.
- **Ranking:** Spearman rank correlation (threat dimensions).
- **Counterfactual consistency:** matched-world intervention agreement rate.
- **Regret:** mean win-probability regret vs the acceptable-line set.
- **Stratified reporting:** every metric reported per matchup × family cell; **no cell below its floor**
  (≥70% per stratum where specified).

---

## 6. Data controls (plan §5)

- Keep the **164 hash-proven d842 episodes** separate from the **567-game same-deck family** (the
  corpus is deck-selected, not model-proven — `GRIM_5K_LOSS_ANALYSIS.md` §7).
- Preserve the existing **33-episode untouched holdout**.
- Require ≥**400 replay-backed exact-lineage episodes**, incl. **150 actual-second** games, before any
  runtime promotion.
- **Split by whole episode, opponent team, and time** (no leakage across splits).
- Exact opponent lists may create offline truth but **never** enter live-faithful inputs (ontology §0.2,
  Director defect 8).
- Treat board width / Marnie-body counts / energy / readiness as **interaction evidence, not causal
  rules** (`STRATEGY_RESEARCH_V1` §6, §8).
- **Engine-certify** the episode `91427733` attach→retreat line before using B2b as a correction
  target — *retreat-legality core done* (`CERTIFICATION_91427733_B2b.md`); complete the promote→attack
  tail in the runtime-proof harness first.

---

## 7. Promotion gates (gameplay — plan §6, summarized; upload is separately user-authorized)

| Stage | Games/arm | Pass condition |
|---|---|---|
| Kill screen | 2,000 | reject on any policy error, actual-second point ≤ baseline, or runtime breach |
| Qualification | 10,000 | positive actual-second lower CB; overall noninferior within 1 pt |
| Sealed final | 20,000 | actual-second uplift ≥2 pts, one-sided 95% lower >0; overall lower ≥ −0.5 pt; critical-matchup lower ≥ −3 pt |

Two-sample intervals for full games (engine entropy independent); paired common-world analysis only
for state counterfactuals. **No upload without separate explicit user authorization.**

---

## 8. Required scenario coverage (must appear in the sealed set — plan §6)

Mega Lucario damage-investment vs irrelevant-Solrock KO (`STRATEGY_RESEARCH_V1` §6.6/A3); Grim mirror
Munkidori/Froslass interaction; Alakazam immediate-prize vs engine-disruption; development
width-without-fuel & excess-bodies-as-liability (§6.1); trapped-Active engine proof (91427733 T9);
walls (productive-attack-over-END vs nullified attacks, §3.2); non-greedy pass/retreat/develop/heal/
Boss-without-immediate-KO; counterfactual sensitivity (changing prizes/readiness/engine/heal/invested
damage moves the *relevant* plan only); hidden-information invariance (identical public evidence →
identical planner inputs); ordered selections, random contingencies, semantic re-resolution, equal
coverage, worker termination, memory cleanup, legal fallback — all must pass with zero errors.

---

## 9. Build order (before training)

1. Freeze this spec + the split manifest (IDs, sha256). **(user seals the 50 exam + 400 eval labels)**
2. Complete the corpus to 700: enrich family-3 & non-mirror matchups from the top-rated export;
   replace low-confidence positions to hold 400 sealed.
3. Fill labels (both plans, routes, threats, damage, causal) — open splits by me, sealed splits by the
   user.
4. Only then: candidate-width sweep (dev split) → posterior/override calibration (calibration split) →
   sealed evaluation. **No implementation before user approval of all four §2 documents + competency.**
