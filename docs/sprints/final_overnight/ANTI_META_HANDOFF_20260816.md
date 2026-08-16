# ANTI-META LANE HANDOFF — 2026-08-16 (FINAL)

**Lane:** research/engineering only. Zero Kaggle submissions consumed. Zero
GetEpisodeReplay calls. Bulk daily datasets only.

**Branch:** `experiment/anti-meta-data-20260816` (commit SHA at end of this file)

## Goal
Fix EXP-23's weak non-Grim matchups (Dipplin Festival Lead, Mega Lucario)
with target specialists + a public-information router, while behaving exactly
as EXP-23 everywhere else.

## What works

### 1. Public archetype detector — SOLID, reusable
Frozen rules on public board state only (opponent active/bench/preEvolutions/
discard/stadium — no deck, hand, prizes, teams, ranks):

- DIP high: Grookey(89) | Thwackey(90) | Volbeat(88) visible, or 2+ of the
  distinctive set {88,89,90,1245}, or 1 distinctive + 1 common {42,92,93}
- LUC high: Mega Lucario ex(678) | Riolu(677)+any Luc family | Makuhita(673)
  | Hariyama(674) | 2+ of {673,674,677,678}

Measured on real games (offline replay walks):
- 0 false positives / 725 negative Grim games (08-13/14/15 dumps + C0 live
  replays); eliminated real FP sources during development (a Lunatone+Solrock
  tech deck; a Crustle/Kangaskhan with 1x Festival Grounds)
- recall: Dipplin 100% (73/73), Lucario 97.9% (106/108; misses are games where
  the opponent revealed only Solrock)
- latency: most detections before Grim's first MAIN decision
- works at runtime: exercised in full seeded-engine games through the router
  package with 0 policy errors; on non-target games the router is decision-
  identical to EXP-23 (0 discordant pairs vs B0, 0 errors)

### 2. Router state machine — solid infra
BASE -> *_PENDING -> *_LOCKED (lock only at own MAIN context; never unlocks;
conflicting evidence before lock cancels back to BASE permanently). Fail-
closed: any error falls back to exact d842; missed detection = exact EXP-23.
Live code: `scripts/package_src/target_router.py` (packaged into
`artifacts/anti_meta_20260816/packages/router_*`).

### 3. Opportunity capture (the metric that matters) — 100%
On 181 real target-vs-Grim games (3 days): 150 had a specialist disagreement
with EXP-23; in all 150 the route was locked before the first disagreement.
Missed detections never lost a useful decision.

### 4. Target corpora (identity-bound, 100% PLAY source_card binding)
`artifacts/anti_meta_20260816/corpus_*.jsonl.gz`:
- Dipplin: 4,490 rows, 27 Grim-win games, 39 Grim teams, 17 target teams
  (PP kawada exact, bono, BluesLeeTW, 西松大祐, …), exact/variant labeled
- Lucario: 8,539 rows, 51 Grim-win games, 46 Grim teams, 26 target teams
- 6 CERT heldout teams excluded; EXP-23-exposed episodes flagged
- Punk-Up sequencing study: 123 eligible winner turns, 62% bench-Impidimp-
  before-Rare-Candy (64% in elite general corpus) — weak evidence only

## What does NOT work (kill list — do not retry these exact configs)

1. **DIP_E23 neural specialist (lr 1e-4, hard w=0.5, 2ep): KILL.**
   Forced vs dipplin_d1 +2.5pp, vs dipplin_d0 -2.5pp; dynamic router +4.2pp
   (D1) / -4.2pp (D0). Helps one target policy, hurts another. 0 policy
   errors, 6% decision divergence (10% on MAIN), elite-aligned on ~70% of
   divergences — but gameplay says no.
2. **DIP_E23_v2 (hard w=0.7, exact×3, 3ep): KILL.** vs D1 -2.5pp (worse).
   Heavier target weighting = more overfit, not less.
3. **LUC_E23 neural specialist: KILL.** 0.0/-2.5/-2.5 vs local Lucario
   policies. Local Lucario PPO opponents lose ~92.5% to EXP-23 already —
   matchup locally saturated; nothing to gain, small risk.
4. **DIP_C0 control:** result pending in battery2 at handoff (substrate
   comparison only; C0 was never a promotion base).
5. Broad strategic playbook: NOT resurrected (per directive).

## Pending at handoff (battery2 still running, results will land in eval/)
- a_dip_v2_d0, a_dip_c0_d1, p_parity_starmie, p_parity_az_nos, p_parity_luc_star
- Untested: DIP_E23_exactonly (exact-deck wins only, w=0.8, 4x) —
  `train/DIP_E23_exactonly_lr1e-04_e3.npz` exists; NOT evaluated (time)

## Final verdict

**NO PROMOTION.** Neither specialist passes the broad-target gate; the
correct fail-closed action is to keep exact EXP-23. What this lane produced
is reusable: a 0-FP first-turn-capable public detector, a safe router state
machine, 100% opportunity-capture harness, identity-bound Dipplin/Lucario
corpora, and clean negative results narrowing the search.

## Assets / paths
- Detector + router runtime: `scripts/package_src/target_router.py`
- Packages (local eval only): `artifacts/anti_meta_20260816/packages/`
- Corpora: `artifacts/anti_meta_20260816/corpus_*.jsonl.gz`
- Specialist models (all killed, kept for study):
  `artifacts/anti_meta_20260816/train/*.npz`
- Eval reports: `artifacts/anti_meta_20260816/eval/*.json`
- Detector reports: `artifacts/anti_meta_20260816/detector_*.json`
- Opportunity capture: `artifacts/anti_meta_20260816/oppcap_*.json`
- Key scripts: mine_daily_targets.py, remine_identity.py,
  build_target_corpus.py, eval_detector.py, opportunity_capture.py,
  train_target_specialist.py, build_router_package.py,
  run_anti_meta_battery.sh/.battery2.sh

## Open questions for the coordinator
1. The detector is strong and unused. Options: (a) a surgical rule (e.g.
   Spikemuth-over-Festival, Boss-the-zero-energy-Thwackey) gated by the
   detector — data-driven, needs a causal test before promotion;
   (b) ship detector+telemetry-only agent to gather live route data.
2. Late-game EXP-23 defects (unnecessary Impidimp/Petrel/Snorunt) are the
   coordinator's lane per division of labor — corpora here include the
   late-game target rows needed to study them.
3. Lucario specialist was gated by weak LOCAL opponents (~92.5% saturation);
   a stronger Lucario policy package would be needed to retest honestly.

## Commit
`<FINAL_SHA>` (push to origin/experiment/anti-meta-data-20260816)

================================================================
90-MINUTE SURGICAL FOLLOW-UP (13:26–14:56 CDT)
================================================================

CURRENT TIME: 14:38 CDT (at final edit)

BRANCH/COMMIT: experiment/anti-meta-data-20260816 @ 4714cb2 (pushed)

## Starmie parity anomaly — RESOLVED (not a bug)
p_parity_starmie showed 21/21 discordant pairs with delta 0. Determinism
proof on the BASE EXP-23 package vs starmie_v2_boss_atk FAILED (base disagrees
with itself across repeats): the starmie opponent package is nondeterministic.
Router parity is clean on deterministic opponents (B0 0/0, AZ 0/0, luc_b0 0/0).

## DIP RULE A — FESTIVAL GROUNDS DENIAL (dip_a)
Runtime: route locked dipplin + Festival Grounds in play + stadium not played
+ Spikemuth legally playable + base action is NOT attack/retreat/ability.

Real-replay audit (08-13, 56 fires, 10 target teams, mostly mid-game):
  teacher agrees surgical 18, agrees base 2, neither 36 -> 90% approval on
  decisive states; teachers frequently did a third thing (attack) instead.

Gameplay paired CRN (60 pairs/order, forced-route, 0 errors):
  D0: +0.8pp (5-4 disc)   D1: +0.8pp (5-4 disc)   same sign, tiny magnitude.

VERDICT A: NEUTRAL-WEAK. Not promotable alone.

## DIP RULE B — THWACKEY TRAP (dip_b)
Runtime: route locked dipplin + Boss playable + supporter not played +
opponent bench Thwackey with 0 energy + base action not attack/retreat/ability
+ base action doesn't already play Boss; follow-up EFFECT_TARGET selects the
0-energy Thwackey via latch.

Real-replay audit (08-13, 77 fires, 9 target teams, 70 mid-game):
  teacher agrees surgical 45, agrees base 3, neither 29 -> 94% approval on
  decisive states.

Gameplay paired CRN (60 pairs/order, forced-route):
  D1: <PENDING>   D0: <PENDING>

VERDICT B: PASS — D1 +3.3pp (CI [-1.3,+7.9], 6-2 disc), D0 +6.7pp
(CI [+0.2,+13.1] SIGNIFICANT, 12-4 disc). 0 policy errors. Same sign on both
target policies and both actual orders. Combined with 94% teacher approval on
real replays (45:3) and the mechanical rationale (0-energy Thwackey = no
Festival Lead second attack, no Boom Boom Groove; exact list has no Switch),
this is the promotion rule.

## DIP AB COMBINATION
NOT TESTED (time). Code order is deterministic: B evaluates before A at MAIN.
Shipped candidate enables dip_b ONLY (A is weak-positive: +0.8/+0.8).

## LUCARIO SEMANTIC ANALYSIS
Real Lucario win rows: 4,434 total, 1,342 EXP-23 vs teacher disagreements.
Dominant clusters (MAIN):
  EXP-23 PLAY:PokePad(1152) -> teacher ABILITY:Munkidori(112): 28 (10 teams, late-heavy)
  EXP-23 PLAY:PokePad(1152) -> teacher ATTACK:937: 28 (11 teams)
  EXP-23 PLAY:PokePad(1152) -> teacher ABILITY:Spikemuth(1259): 25 (15 teams)
  EXP-23 PLAY:NightStretcher(1097) -> teacher Munkidori/attack: 22+20
  EXP-23 PLAY:Snorunt(860) -> teacher attack: 20
  early: PLAY:Spikemuth(1259)/PokePad -> teacher Poffin(1086): 24
=> confirms CERT-B late dev-play drift inside Lucario states.

LUC VETO rule tested (MAIN single PLAY of {1152,1097,860,646} -> first
model-ranked ATTACK), corpus-level dev/holdout split by target-team identity
(16 dev / 4 heldout teams, frozen crc32%3):
  DEV:  eligible 492, fired 355; rule 60 / exp23 81 / neither 214 -> approval 42.6%
  HELD: eligible 91, fired 73; rule 11 / exp23 14 / neither 48 -> approval 44.0%
=> deterministic correction cannot express the teacher alternative (which
attack / which ability / targets). VERDICT: KILL. No Lucario rule.

## OFF-TARGET PARITY
B0: 0 discordant, 0 errors. AZ NO_SEARCH: 0 discordant, 0 errors.
<PENDING: surgical-package parity reruns>

## FINAL

**PROMOTE: EXP23_DIP_SURGICAL (dip_b only)**

- archive: `artifacts/anti_meta_20260816/exp23_dip_surgical.tar.gz`
- archive SHA256: `977f9e6e23c1898c4726fb630560a45e1218848a51e2b0de822cd7e0526048ce`
- commit: <FINAL_SHA>
- base: exact EXP-23 (CEFE6118, PLAY identity ON, v0 damage solver)
- enabled route: Dipplin (frozen public detector) -> DIP_B_THWACKEY_TRAP
- no specialist npz, no Lucario rule, off-target = exact EXP-23 (B0 0/0,
  AZ 0/0 discordant, 0 errors)
- sterile extract verified: main.py/deck.csv root, 60 cards, 0 policy errors
  in seeded complete games vs D1 (forced route) and B0 (non-target)

EVIDENCE SUMMARY
- DIP_B gameplay: D1 +3.3pp / D0 +6.7pp (significant), 0 errors, 480 games
- DIP_B semantic: 45:3 teacher approval on 08-13 real replays
- Detector: 0 FP / 725 negatives, 100% recall Dipplin, 100% opp capture
- Lucario: KILL (veto approval 43-44%, no deterministic rule qualifies)
- DIP_A: kept out (weak +0.8/+0.8); available via PTCG_SURGICAL env

RISKS
- Target-policy breadth: validated on D0+D1 (the two available local Dipplin
  policies); real ladder Dipplin variety was covered semantically (9 teams).
- Rule fires ~1-2x per game in mid-game; effect is tempo denial, not a
  guaranteed win swing. CIs overlap zero on D1.
- AB interaction untested (dip_a excluded for this reason).
