# FINAL SURGICAL PORTFOLIO PACKET — 2026-08-16

**V1 = EXP23 + DIP_B + ENDGAME_LETHAL** (Crustle/Lucario/Dragapult: no V1 components — see sections 6-8.)

## 1. Time, branch, commit

- Packet written: 15:05 CDT (2026-08-16)
- Branch: `final/surgical-portfolio-20260816` (worktree `pokemonTCG2.0-sprint`)
- Frozen bases (untouched):
  - `final/overnight-20260816` @ `de532fa` (EXP23 live-loss analysis)
  - `experiment/anti-meta-data-20260816` @ `84f4cfe` (DIP_B certified promotion)
- Sprint commits: `e355a4f` (solver + wiring + miner) + packaging commit (TBD)

## 2. Base identity verification

- Base agent: EXP-23, model CEFE6118..., tree `/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/final_sprint/exp23_identity_trained`
- Deck: 60 cards, Grimmsnarl/Marnie Darkness engine (sha TBD in final package manifest)
- Verified by `scripts/package_final_candidate.py` (policy npz sha == EXP23_SHA, deck 60, no specialist npz, PLAY identity on)

## 3. ENDGAME_LETHAL (PROMOTE — main new component)

- **Predicate:** our remaining prizes <= 2 AND a select prompt exists inside our own turn (any context).
- **Mechanism:** DFS over the remainder of the CURRENT turn with native search engine
  (`search_begin/search_step`), depth <= 6, node cap 400, hard time budget 150ms.
  Override base action ONLY if a continuation provably reaches `result == ourIndex`
  before the opponent acts. Otherwise exact EXP23 behavior. Receding horizon: rerun
  at every prompt; no cross-prompt option-index storage.
- **Provability:** deck-order-dependent plays are excluded from searched lines
  (Pokégear 3.0, Poké Pad, Buddy-Buddy Poffin, Lillie's Determination, Unfair Stamp,
  Team Rocket's Petrel, Dawn). Every remaining Grim action touches only public zones
  (hand/board/discard), so terminal wins are hidden-info-invariant. Opponent deck is
  determinized only for the engine's count validation; no searched line makes the
  opponent draw.
- **Fires / latency (screen telemetry, 120 mirror games):** 445 fires; ctx MAIN 167,
  Night-Stretcher pick 84, Shadow Bullet target 39, Munkidori counter contexts ~94,
  others; prizes=1 in 406/445. p50 5ms, p95 92ms (pre-ordering build); after
  ATTACK-first ordering: p50 3ms, p95 19ms.
- **Offline mining (EXP23 vs B0, seeded):** 33 missed lethals / 40 games (post-fix).
  Dominant family: EXP23 plays a supporter/item (Lillie, Petrel, PokePad, Night
  Stretcher) or evolves while a direct **Shadow Bullet (attack 937) wins on the spot**
  at prizes=1. Secondary families: energy ATTACH -> attack, ABILITY -> attack, Boss ->
  attack, Rare Candy/evolve -> attack.
- **CRN paired (candidate router_endgame = EXP23+DIP_B+ENDGAME vs control = exact EXP23):**
  - vs B0 (Grim mirror), 60 pairs/order: overall +0.83pp (54.2% vs 53.3%), discordants
    1 candidate / 0 control, 119 concordant, **0 policy errors both arms**.
  - vs Alakazam 2.4a, 60 pairs/order: **exact parity, 0 discordants, 0 errors**.
  - vs B0 expanded 100 pairs/order: TBD (running at write time).
  - vs Dipplin D1 (forced route, dip_b + endgame), 40 pairs/order: TBD (running).
- **Risk notes:** single-determinization search; lines that trigger opponent coin-flip
  abilities mid-turn are not filtered (rare, no coin effects in Grim deck's own
  actions); terminal wins are prize-based so opponent draws cannot invalidate them.

## 4. DIP_B (PROMOTE — previously certified, re-verified in V1)

- Archive `artifacts/anti_meta_20260816/exp23_dip_surgical.tar.gz`
  sha256 `977f9e6e23c1898c4726fb630560a45e1218848a51e2b0de822cd7e0526048ce`
- Mechanism: public-state Dipplin route -> Boss's Orders strands a ZERO-ENERGY THWACKEY
  Active. No neural specialist. Fails closed to exact EXP23 outside the route.
- Prior evidence: D0 +6.7pp, D1 +3.3pp, 18/6 favorable discordants, 0 errors, exact
  parity vs B0 + Alakazam.
- V1 D1 screen (with ENDGAME_LETHAL layered): TBD (running).

## 5. Portfolio composition (V1)

- `exp23_portfolio_v1` = exact EXP23 base
  + ENDGAME_LETHAL (flag `PTCG_ENDGAME_LETHAL`, default on)
  + DIP_B (flag `PTCG_SURGICAL=dip_b`, baked default)
  + NOTHING ELSE (dip_a off, luc_veto off, no specialist npz)
- Runtime priority: 1) proven terminal lethal, 2) surgical route (dipplin only), 3) EXP23 base.

## 6. Crustle findings — INCOMPLETE (no V1 component)

- No evaluable Crustle opponent package exists in any worktree/artifacts
  (`build_recovery_opponents.py` requires archives that are not present).
- `scripts/crustle_behavior.py` + decklists exist; behavior mining not re-run this
  sprint (time).
- The generic ENDGAME_LETHAL subsumes Crustle endgame escapes (Boss->Shadow Bullet)
  wherever prizes <= 2. Mid-game Crustle/Munkidori breakpoints remain unexplored.
- **KILL for V1 (not from evidence, from no-evaluator).** V2 lane if time remains.

## 7. Lucario complete-turn findings — NOT RUN THIS SPRINT

- LUC_VETO remains KILLED (43-44% teacher approval; single-action imitation is the
  wrong metric). Complete-turn counterfactual scan did not run before the V1 cutoff.
- No Lucario rule in V1.

## 8. Dragapult — NOT TOUCHED

- Prior broad surgery killed; no DIP_B-like mechanism identified; 15-minute scan not
  run (V1 deadline priority). No Dragapult rule in V1.

## 9. Packaging

- Tree: `artifacts/anti_meta_20260816/packages/router_endgame` (built by
  `scripts/build_router_package.py` from EXP-23 identity tree + router/surgical/endgame modules)
- Sterile archive + sha256 + manifest: TBD (built with `scripts/package_final_candidate.py`)
- Smoke: TBD

## 10. Recommended Kaggle action

- **SUBMIT exp23_portfolio_v1 NOW** (once screens confirm no regression + smoke passes):
  DIP_B alone was already recommended; ENDGAME_LETHAL adds a provable-win layer with
  1/0 favorable discordants and exact Alakazam parity.
- Do NOT submit if: B0-big or D1 screens show a meaningful negative discordant count
  or any policy error.

## 11. Remaining known risks

- ENDGAME search lines that pass through opponent-triggered coin flips (unfiltered).
- Runtime: search memory usage per prompt (search_end/release pattern matches
  existing OnePlySearchPolicy usage).
- Live endgame states may include mechanics absent from local deterministic engine
  tests; override is terminal-proof from the engine's public computation.

## 12. Incomplete experiments (NOT promoted)

- Crustle CRN screen (no opponent package) — section 6.
- Lucario complete-turn causal scan — section 7.
- Dragapult scan — section 8.
- B0-big and D1 screens were still running at packet draft time.
