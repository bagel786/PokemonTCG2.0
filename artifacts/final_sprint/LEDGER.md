# FINAL SPRINT LEDGER — Aug 15 (submission day)

Frozen champion C0 = exact A2+Damage V0 (archive A44B676F…, tree 13426288…, model B19871A9…, deck 92B92BAC…). Verified on disk.

## Trace mining (236 live games, 4 subs)
- Mirror 84 games: first 18/42 (42.9%), second 22/42 (52.4%). Anomaly confirmed.
- Mirror-first = race to first Grimmsnarl ex (W first_grim 2.71 vs L 3.0; opp first_grim W 3.67 vs L 3.42). Mostly draw-driven; T2 candy misses with pieces in hand: 3W/4L (symmetric).
- Snorunt setup-active: 6/24 mirror-first losses (only 2 with a choice available).
- T1 Gym search fetched Impidimp with 647/648 available in 4/42 mirror-first losses (9 games, 5 had no Impidimp on board = correct fetch).
- Alakazam losses (20): attacker exhaustion after first Grim KO (no second attacker ready, no energy stock).

## Experiments (all paired CRN vs exact C0, zero policy errors)
- EXP-16 gym search tier: -3.0pp; T1-gated: **-3.33pp [CI -5.4,-1.2] SIGNIFICANT → KILL**
- EXP-18 candy-T2 push: -0.8pp → KILL
- EXP-17 setup-active tier: +1.0pp first cell; fresh B0 -0.4, m1 -0.1 → KILL
- punk_target fresh: B0 -1.3pp / m1 -0.4pp (1000p each) → KILL (sprint-870 positives were seed noise)
- EXP-1 full punk fresh: +0.5pp (first +2.8, second -1.8)
- **EXP-20 = full punk, FIRST arm only** (second arm byte-identical):
    first-seat cells: B0 fresh +2.75 (disc 50/39), B0 +1.83, B0b +2.83, m1 0.00, m1b +1.25, rr +0.33, rrb +2.75, a2ctl -1.25
    **Alakazam 2.4a SEARCH-ON first order: +3.0pp (100 pairs, disc 10/7, 0 errors; C0 baseline 75.0%)**
    second-order control: exactly 0 discordant.
    → pooled first-seat ~+1.5pp across 9 cells. PASSED gates as narrow/large-bucket/zero-regression candidate.
- Live audit tool built (scripts/audit_live_rails.py) - fixed cross-game latch artifact by replaying handshake per game.

## SUBMISSION
- **55532521** "punk-first-rail-20260815" = exp20_punk_first_only.tar.gz (sha 6D26061ED9F33B0ED0966BFDA542F6DCACB27EE887C61668FFE4267D52ACFF59)
  - submitted 2026-08-15 17:05 UTC (12:05 CDT)
  - mechanism: order-conditional full Punk Up rail (activate/count/target tier) on the actual-first arm only; actual-second arm = exact C0.
  - active pair: 55513649 (C0, 798.2) + 55532521 (challenger).
- 4 submissions remain.

## Open
- EXP-21 (punk-first + playid-second, independent mechanisms per arm): built, screens pending.
- Monitor 55532521: validation + first 5-10 games trajectory.

## EXP-20 post-submission regressions (all first-order, zero errors)
- Starmie v2: +5.0pp (200 pairs, ns, disc 38/28)
- Dipplin D1: +7.0pp (100 pairs, CI [+1.25,+12.75] SIGNIFICANT, disc 8/1)
- EXP-21 (punk-first + playid-second) vs C0 B0: -0.25pp (first -0.5, second 0.0 w/ 82-82 disc) -> playid-second = noise on fresh seeds. KILL. Only punk-first remains.
- Submission 55532521 live: 4 rated games 2W-2L (W vs 460, L vs 722, W vs 591, L vs 740; score 615.6). Expected-rating ordering, no mechanism failure.

## Afternoon updates
- EXP-20 vs C0 B0 first-order BIG (1000 fresh pairs): -0.2pp (disc 112/114). B0 pooled first-seat remains +1.17pp over 5 cells.
- EXP-22 (punk count+target, NO activate, first-only): +2.0pp fresh B0 (600p, disc 75/63); head-to-head vs EXP-20 +1.0pp (400p, ns). Kept as reserve; not replacing 55532521 (diff not decisive, would cost live trajectory).
- 55532521 live @12:30 CT: 7 rated, 4W-3L, score 679.1; wins vs <700, losses vs 641-740 (expected ordering, no mechanism failure).

## a2ctl gate
- EXP-20 vs A2-ordered first-order fresh (400p): -0.25pp (ns, disc 45/46). No regression vs prior live agent.
- 55532521 live @12:50 CT: 9 rated, 5W-4L, score 660.3. Perfect rating-ordering (wins <700, losses 641-740). Matches C0 live behavior.

## EXP-23 IDENTITY-FIXED RETRAIN — THE BREAKTHROUGH
Mechanism: v2 encoder defect fixed (PLAY options were identity-blind: source_card=0 for 100% of 110,966 training rows). Retrained heads from A2 on 47,653 fresh elite Grim decisions (Aug 14-15 top-episode dumps, mined WITH identity bound), lr 1e-4, 3 epochs, KL anchor 0.5, seed 20260816. Model sha CEFE61189BC6F4E3.

Gates vs exact C0 (paired CRN, zero errors, all cells):
  B0 800p: +3.38pp (ns) | B0 fresh 1200p: +4.17pp SIG [+0.7,+7.6] | m1 800p: +6.38pp SIG [+2.1,+10.6] | rr 800p: +6.25pp SIG [+1.9,+10.6] | az24 NO_SEARCH 400p: -0.75pp ns | az24 SEARCH-ON 100p: -2.0pp ns | starmie 400p: +2.0pp ns | dipplin 200p: +0.5pp ns
  6 positive / 2 neutral / 0 negative cells. Grim-family pooled ~+5pp. First candidate ever with 3 significant cells.

Package: exp23_identity_trained.tar.gz sha 0734B60C089EEA9C2E40550B8E9C6DC3983957210794BA245C4C00BD9D4E7096
Sterile smoke: PASS (60-card deck, identity flag ON, model CEFE6118...).
NOT YET SUBMITTED - awaiting user go-ahead (autonomy expired 7pm CT).
