# EXP23 LIVE LOSS ANALYSIS — 55556726 (2026-08-16, ~14:30 CDT)

**Record:** 28 rated games vs real opponents, **17W-11L (61%)**, plus 1 self-probe (net 0).
Zero policy errors, live self-parity maintained (byte-identical to local package).

## W/L by archetype

| Archetype | Record | Note |
|---|---|---|
| Alakazam | 6W-0L | local proxy (az24, -1.6pp) UNDER-predicted; live Alakazam teams are very beatable |
| Grim mirror | 5W-2L (71%) | matches field battery (+4.5pp); both losses = forced-bad opener or close race |
| Dragapult | 1W-4L (20%) | known weak spot, n=5 |
| Dipplin | 0W-1L | n=1 |
| other | 5W-4L | mixed |

## Loss classification (10 losses)

| Ep | Opponent | Archetype | Cause |
|---|---|---|---|
| 93668609 | パチリス | Dipplin/Rillaboom | PRIZE RACE LOST + 4 Munks on board t8 |
| 93670440 | Xiaolei Lian | other | TEMPO (first Grim t9) + race lost + 3 Munks t8 |
| 93671387 | tellurium_rrr | Dragapult | close race; adjudicated at truncation with 4-1 prize lead |
| 93673237 | Shelgon | Dragapult | close race vs double-Dragapult burst |
| 93674154 | Yuta Goda | other | prize race lost |
| 93677628 | Koba Empire | other | close race (2-1) |
| 93680533 | ペンギン | Grim mirror | prize race lost (first Grim t5, normal tempo) |
| 93685951 | tellurium_rrr | Dragapult | TEMPO (first Grim t11) + close race + 3 Munks t8 |
| 93693193 | Pathetic384 | other | prize race lost + 2 Munks t8 |
| 93699067 | titako0000 | Dragapult | TEMPO (first Grim t14) + close race + 2 Munks t8 |
| 93715535 | Ash Kecap | Grim mirror | prize race collapse (6-1); FORCED Munkidori-only setup hand (verified: single SETUP_ACTIVE option), no policy choice |

## Patterns

1. **Tempo:** losses with first Grim ≥ t8: 3 (plus forced-bad openers). Wins with first Grim
   t3: 5/6. The deck's Grim tempo remains the dominant lever — draw-driven, not policy.
2. **Munk clutter correlates with losses:** 7 of 11 losses had ≥2 Munks on board at t8,
   vs 4 of 18 wins. Consistent with CERT-B late-divergence, but largely forced by draws.
3. **Dragapult = 4 losses** (2 tempo collapse, 2 close races) — deck-level matchup.
4. **Alakazam 6-0 and mirror 71%** are the carry cells — field battery confirmed.
5. **No mechanism failures:** no errors, no fallbacks, parity clean.

## Cheap-fix candidates evaluated (audit results)

1. **Munk-ability priority** ("when EXP23 plays a support basic and an ability is
   available, use the ability instead"): fires only 41× in 28 live games (30 in WINS);
   C0 takes the ability in just 34.1% of those spots and plays support itself 31.7%.
   Alignment too weak + fires skew to winning games → **REJECTED** (touching wins is unsafe).
2. **Late-support freeze vs online Dragapult** (drag-surgical lane): EXP23 4.18% vs
   C0 2.44% vs elite 2.57%, but C0-fallback action is elite-exact only 38.8% in winning
   games → **REJECTED** (details: DRAGAPULT_SURGICAL_HANDOFF).
3. **Tempo/opener fixes**: first-Grim delays and forced-Munk openers are draw/opener
   luck, not policy choices. Nothing to fix without changing the deck list (out of scope).
4. **Boss under-use**: observed (Boss ×2 unused in one loss) but no systematic
   EXP23-vs-C0 divergence established; contextual, not cheaply fixable.

## Bottom line

All 11 losses decompose into draw structure (forced openers, slow Grim line), close
prize races, and the known deck-level Dragapult weakness. The two plausible policy
patches both fail the alignment bar. **No cheap safe improvement exists — EXP23 should
run untouched; further gains would require new training, not today.**
