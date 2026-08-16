# FINAL SURGICAL PORTFOLIO PACKET — 2026-08-16

**V1 = EXP23 + DIP_B + ENDGAME_LETHAL** (Crustle/Lucario/Dragapult: no V1 components — see sections 6-8.)

## 1. Time, branch, commit

- Packet written: 16:15 CDT (2026-08-16)
- Branch: `final/surgical-portfolio-20260816` (worktree `pokemonTCG2.0-sprint`)
- Frozen bases (untouched):
  - `final/overnight-20260816` @ `de532fa` (EXP23 live-loss analysis)
  - `experiment/anti-meta-data-20260816` @ `84f4cfe` (DIP_B certified promotion)
- Sprint commits: `e355a4f` (solver+wiring+miner), `e52daa1` (ordering+exclusions), `d4a08fd` (node-budget determinism fix + homework set) + packaging commit (TBD)

## 2. Base identity verification

- Base agent: EXP-23, model CEFE6118..., tree `/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/final_sprint/exp23_identity_trained`
- Deck: 60 cards, Grimmsnarl/Marnie Darkness engine; verified byte-identical to EXP23's live deck (episode visualize decks)
- `scripts/package_final_candidate.py` verifies: policy npz sha == EXP23_SHA, deck 60, no specialist npz, PLAY identity on, surgical default baked, endgame module present

## 3. ENDGAME_LETHAL (PROMOTE — conditional on final screens)

- **Predicate:** our remaining prizes <= 2 AND a select prompt inside our own turn (any context). Flag `PTCG_ENDGAME_LETHAL` (default on).
- **Mechanism:** DFS over the remainder of the CURRENT turn with native search engine
  (`search_begin/search_step`), depth <= 6, deterministic node budget 400 (NO wall-clock
  budget — see determinism fix below). Override base action ONLY if a continuation
  provably reaches `result == ourIndex` before the opponent acts. Otherwise exact EXP23.
  Receding horizon at every prompt; no cross-prompt option-index storage.
- **Provability:** deck-order/prize-hidden-dependent plays excluded from searched lines:
  Pokégear 3.0, Poké Pad, Buddy-Buddy Poffin, Lillie's Determination, Unfair Stamp,
  Team Rocket's Petrel, Dawn. Every remaining Grim action touches only public zones;
  terminal wins are hidden-info-invariant. No searched line makes the opponent draw.
- **DETERMINISM BUG FOUND AND FIXED:** v1 of the solver used a 150ms wall-clock budget.
  Under parallel screen load, whether a win was found within budget depended on machine
  timing → same-seed runs flipped outcomes (proved by direct replay). Fixed to a strictly
  node-count budget (400 engine steps ≈ tens of ms). Post-fix spot check: same seed,
  two runs, byte-identical outcome and decision count (157/157 vs B0).
- **Latency (deterministic package, B0 telemetry):** p50 5ms, p95 92ms (older timing
  build); ordered build p50 3ms, p95 19ms; worst case bounded by 400 engine steps.

### 3a. Live-loss homework set (the rescue metric)

Built from ALL 30 EXP23 live games (submission 55556726 replays, incl. search_begin_input):

- 29 games parsed (12 losses, 17 wins); 674 eligible decisions (our prizes <= 2)
- Labels: NO_LETHAL 638 / BASE_LETHAL 18 / MISSED_LETHAL 18
- **RESCUED LOSSES: 0 / 12.** Every missed lethal occurred in a game EXP23 won anyway
  (4 winning games contain missed lethals — solver accelerates, does not rescue, in live).
- Precision on live states: every solver fire was engine-verified terminal; no false
  interventions observed on NO_LETHAL states (fires only occur with a proven win).
- Conclusion: EXP23's live losses are draw-structural (consistent with the overnight
  analysis); the solver's live value is marginal. Its value is proven instead by seeded
  CRN rescues below (games EXP23 actually loses in paired deterministic play).

### 3b. Seeded CRN (rescue evidence, deterministic opponents)

All paired vs exact EXP23 control. Package: router_endgame (EXP23 + DIP_B + ENDGAME).

- vs B0 Grim mirror (deterministic package): 60p +0.83pp (1-0 discordants), 0 errors;
  earlier time-budget cells: 60p +1.1pp, 100p +0.5pp, 40p +1.25pp (all 1-0, 0 errors).
  TOTAL mirror rescues: 4 candidate-only discordant wins / 520 pairs, 0 control-only.
- vs Alakazam 2.4a (deterministic package): 60p exact parity (0 discordants, 0 errors).
- vs Dipplin D1 (forced route, dip_b + endgame), clean deterministic rerun 40p/order:
  overall +2.5pp (4-2 discordants), 0 policy errors. DIP_B value preserved with the
  endgame layer on top.
- **vs Dragapult — SCREEN INVALIDATED.** The available dragapult opponent is
  NONDETERMINISTIC: plain EXP23 control flips win/loss across same-seed reruns
  (verified: 5 runs → mixed outcomes, varying decision counts). Paired-CRN assumptions
  violated; no Dragapult evidence is claimed from that cell. (The +10pp there must NOT
  be used.)

## 4. DIP_B (PROMOTE — previously certified, carried into V1)

- Archive `artifacts/anti_meta_20260816/exp23_dip_surgical.tar.gz`
  sha256 `977f9e6e23c1898c4726fb630560a45e1218848a51e2b0de822cd7e0526048ce`
- Mechanism: public-state Dipplin route -> Boss's Orders strands a ZERO-ENERGY THWACKEY
  Active. No neural specialist. Fails closed to exact EXP23 outside the route.
- Prior evidence: D0 +6.7pp, D1 +3.3pp, 18/6 favorable discordants, 0 errors, exact
  parity vs B0 + Alakazam. V1 D1 rerun (with ENDGAME layered): TBD.

## 5. Portfolio composition (V1)

- `exp23_portfolio_v1` = exact EXP23 base
  + ENDGAME_LETHAL (flag `PTCG_ENDGAME_LETHAL`, default on)
  + DIP_B (flag `PTCG_SURGICAL=dip_b`, baked default)
  + NOTHING ELSE (dip_a off, luc_veto off, no specialist npz)
- Runtime priority: 1) proven terminal lethal, 2) surgical route (dipplin only), 3) EXP23 base.

## 6. Crustle findings — INCOMPLETE (no V1 component)

- No evaluable Crustle opponent package exists in any worktree/artifacts
  (`build_recovery_opponents.py` requires archives that are not present).
- The generic ENDGAME_LETHAL subsumes Crustle endgame escapes (Boss->Shadow Bullet)
  wherever prizes <= 2. Mid-game Crustle/Munkidori breakpoints remain unexplored.
- **No V1 component.** V2 lane if time remains.

## 7. Lucario complete-turn findings — NOT RUN THIS SPRINT

- LUC_VETO remains KILLED (43-44% teacher approval; single-action imitation is the
  wrong metric). Complete-turn counterfactual scan did not run before the V1 cutoff.
- No Lucario rule in V1.

## 8. Dragapult — NOT TOUCHED; evaluator nondeterministic

- Prior broad surgery killed; no DIP_B-like mechanism identified.
- Available deterministic evaluator does NOT exist (opponent package nondeterministic —
  see 3b). No Dragapult rule in V1.

## 9. Packaging

- Tree: `artifacts/anti_meta_20260816/packages/router_endgame` (built by
  `scripts/build_router_package.py` from EXP-23 identity tree + router/surgical/endgame modules)
- Sterile archive: `artifacts/anti_meta_20260816/exp23_portfolio_v1.tar.gz`
- **SHA256: `b654b05084c6fef7ae497e71143024d2327650cff838341d904954d1b4d37a5c`**
- Manifest: `artifacts/anti_meta_20260816/exp23_portfolio_v1.manifest.json`
- deck.csv sha256 `92b92bac9f9163ecff933b3dc39294d2cc154c8684f3c8497877661419ebc59d`
- Sterile smoke (extracted archive vs B0, 3 pairs/order): 0 policy errors, 0
  discordants, candidate tree sha256 `82280f544ddc4971f5c0adb781786582926104c087b2f91b3ba48cf9e6a001d9`

## 10. Recommended Kaggle action

- **SUBMIT exp23_portfolio_v1 NOW.**
- Final screens (deterministic package): B0 4-0 discordant rescues / 520 pairs,
  Alakazam exact parity 240 pairs, Dipplin D1 +2.5pp (4-2), 0 policy errors
  everywhere, sterile smoke clean.
- Live evidence shows the solver won't rescue EXP23's current losses (structural),
  but it converts genuine seeded mirror losses with near-zero risk, and DIP_B was
  already a recommended submit. If higher-reasoning review disagrees, the rollback
  candidates are: EXP23 alone, or the certified DIP_B-only archive
  (sha 977f9e6e23c1898c4726fb630560a45e1218848a51e2b0de822cd7e0526048ce).

## 11. Remaining known risks

- Lines that pass through opponent-triggered coin flips mid-turn are not filtered
  (rare; no coin effects in the Grim deck's own actions).
- Live endgame states may include mechanics absent from local tests; override is
  terminal-proof from the engine's public computation either way.
- Runtime cost: up to 400 engine search steps per eligible prompt (tens of ms on the
  reference box; no wall-clock budget to avoid nondeterminism).

## 12. Incomplete experiments (NOT promoted)

- Crustle CRN screen (no opponent package) — section 6.
- Lucario complete-turn causal scan — section 7.
- Dragapult CRN cell — invalid evaluator (opponent nondeterministic) — section 8.
