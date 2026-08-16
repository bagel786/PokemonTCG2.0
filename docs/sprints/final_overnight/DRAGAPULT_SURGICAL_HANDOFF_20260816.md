# DRAGAPULT SURGICAL HANDOFF — 2026-08-16

**CURRENT TIME:** ~13:50 CDT
**BRANCH:** `experiment/dragapult-surgical-20260816` (isolated worktree `PokemonTCG2.0-drag-surgical`)
**BASE:** `bd35101` (final/overnight-20260816)
**COMMIT:** see below (pushed with evidence)
**PARALLEL-AGENT ISOLATION:** the anti-meta Dipplin/Lucario/router agent works in
`PokemonTCG2.0-anti-meta` @ `6247885` on `experiment/anti-meta-data-20260816`. Not touched.
**NO KAGGLE SUBMISSIONS MADE.** Fleet untouched (EXP23 + C0).

---

## BASELINE

| Source | n | WR |
|---|---|---|
| Elite exact-Grim vs Dragapult (0815 dump) | 175 | **40.0%** (70W-105L) |
| … vs HIGH-ranked Dragapult (top-50) | 8 | 25.0% |
| … vs MEDIUM (rank 51-147) | 15 | 33.3% |
| … vs UNRANKED opponents | 152 | 41.4% |
| EXP23 live (today) | 4 | 25.0% (1W-3L) |
| C0 live bank (same day) | 2 | 100% (n=2, meaningless) |

Strength gradient is real: weaker Dragapult opponents are the beatable ones; EXP23's
live 1-3 includes 2 games vs the same ranked Dragapult/Dusknoir team.

## LIVE LOSS CLASSIFICATION

| Ep | Result | First Grim | Classification |
|---|---|---|---|
| 93671387 | L (adj.) | t6 | **UNKNOWN/STRUCTURAL**: 4-1 prize lead at truncation, adjudicated loss; evolve available t5 taken t6 (minor tempo) |
| 93673237 | L | t5 | **STRUCTURAL**: opponent double Dragapult ex by t7 + 3-prize burst; we took 4; Boss ×2 sat unused late |
| 93685951 | L | t11 | **ATTACKER-EXHAUSTION + LATE-CLUTTER (partially avoidable)**: 3×Munkidori bench by t8 while Marnie line lagged; at t14-15 full rebuild kit in hand (Grim×2, Candy, Morgrem, Impidimp, Poffin×2) unused; ended with Munkidori active, 0 Grim left |
| 93679642 | W | t7 | fast win, opponent never stabilized |

Note: in ep93685951 the early hand was Grim-heavy with NO Impidimp/Morgrem/candy —
the Munk spam was largely forced by draws (structural), not pure policy choice.

## ELITE FINDINGS (175 games, board-state mining)

- **Tempo is king:** first Grim t3 → 83% (10/12); t4-7 → 38-51%; t8+ → collapse; never → 0/12.
- **Powered Munkidori (t6-8):** 0 powered → 22.8% (79); 1 → 48.6% (70); 2 → 77.3% (22).
  Confounded by position (powered Munks = spare energy = winning board), but direction is
  consistent with the Munkidori-conversion hypothesis.
- **Replacement line:** at first Grim KO, 0 Marnie pieces in play → 0/12 wins; 1 → 22.7%; 2 → 25.0%.
- **Froslass:** entered BEFORE first Grim → 29.4% (n=17); AFTER → 43.6% (n=39); none → 41.4% (n=116).
  Early Froslass slightly negative (likely forced-draw confound).
- **Punk-bench-first (Impidimp played on first-Grim turn):** 39.4% (n=104) vs 49.2% (n=59)
  for evolve-without-extra-bench. **No support for a blanket bench-first rule** (Saf's
  hypothesis not confirmed in this population; effect likely situational on energy deficit).
- **Mid-game bench width:** elite WINS average min-bench(t3-8)=3.0 vs 2.3 in losses.
  NO support for a generic narrow-bench rule.

## INTERVENTIONS TESTED (replay audit, EXP23 + C0 + elite on all 175 games)

Window: decisions with Dragapult ex PUBLICLY online, turn ≥ 6 → n = 8,943.

| Rule | Fires | Evidence | Verdict |
|---|---|---|---|
| **A** replacement-line (play Marnie piece instead of support basic when no Marnie line in play) | 6 | EXP23 already does this | **DEAD — nothing to fix** |
| **B** Munk-power (attach D to unpowered bench Munkidori) | 0 | EXP23 never has this attach opportunity in replay | **DEAD — nothing to fix** |
| **C** late-support freeze (EXP23 plays Snorunt/Froslass/Munkidori late vs online Dragapult) | EXP23 374 (4.18%) vs C0 218 (2.44%) vs elite 230 (2.57%) | EXP23 has a real ~1.7pp support-play excess vs both C0 and elite | **REAL but small** |

**Delta audit** (193 decisions where EXP23 plays support, C0 does NOT):
- elite exact-matches C0's action: **48.2%**; elite plays support: 25.4%
- **W/L split (decisive):** in WINNING games elite agree with C0's exact action only
  **38.8%** (31/80) and play support themselves 30.0% (24/80); in LOSING games agreement
  is 54.9% (62/113). The C0-fallback alignment lives mostly in already-lost positions —
  it is not a winning-behavior magnet where it matters.
- fires skew to losing games (80W/113L) — much is desperation-state behavior

Interpretation: a C0-fallback rule would improve elite-action alignment on ~1.1
decisions/game (+23pp on those decisions) but with **no causal win-rate evidence**,
its strongest alignment is in LOSING games (54.9% vs 38.8% in wins), and 25-30% of
the time elite themselves play support there. This does NOT clear the promotion bar
("clear improvement toward winning elite behavior").

## CAUSAL TESTING

Not feasible in the remaining budget (requires hidden-state determinization machinery;
>=45 min). Declared NOT attempted rather than done badly.

## FINAL CANDIDATE

**NONE.** No EXP23_DRAG_SURGICAL package was built. Rationale:
1. The matchup ceiling is deck-level (40% elite, 25% vs top Dragapult).
2. The only real EXP23-specific divergence (late support excess) is ~1.7pp of late
   drag-online decisions, elite-alignment gain is modest (48% vs 25%), and it
   concentrates in losing games.
3. Rules A/B (attacker continuity, Munk power) — the strongest board-level signals —
   have ZERO actionable fires in EXP23's replay behavior; EXP23 is already fine there.
4. Any surgical build still carries packaging/parity/submission risk against a hard
   3:45 freeze; coordinator controls submissions and the parallel router owns
   dynamic-archetype routing.

If the coordinator later wants the ONE surviving rule, it is:
`if dragapult_ex_publicly_online(obs) and turn >= 6 and chosen_action_plays_support_basic(obs, action):
    substitute C0-policy action (PLAY_IDENTITY_ENABLED=False for that call)`
— with the caveat that C0's action is elite-exact only 48% of the time there.

## FINAL VERDICT

**NO DRAG CANDIDATE.** "No safe improvement found" — honest result. Analysis preserved
for the 4:43 review and for potential folding into the parallel anti-meta router.

## EVIDENCE FILES (committed)

- `scripts/overnight_20260816/{stratify_drag_baseline,mine_elite_patterns,classify_live_drag_losses,narrate_drag_games,audit_drag_rules,delta_audit,elite_support_rate}.py`
- `artifacts/drag_surgical/{elite_dragapult_0815.json, elite_patterns.json, rule_audit.json}`
- 175 elite episodes cached locally at `artifacts/drag_surgical/elite_episodes/` (954MB, NOT committed)
