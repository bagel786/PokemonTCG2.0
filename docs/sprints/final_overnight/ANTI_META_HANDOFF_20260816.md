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
