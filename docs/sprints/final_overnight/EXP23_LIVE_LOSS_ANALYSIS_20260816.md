# EXP23 LIVE LOSS ANALYSIS — 55556726 (2026-08-16, ~14:00 CDT)

**Record:** 27 rated games vs real opponents, **17W-10L (63%)**, plus 1 self-probe (net 0).
Zero policy errors, live self-parity maintained (byte-identical to local package).

## W/L by archetype

| Archetype | Record | Note |
|---|---|---|
| Alakazam | 6W-0L | local proxy (az24, -1.6pp) UNDER-predicted; live Alakazam teams are very beatable |
| Grim mirror | 5W-1L (83%) | matches field battery (+4.5pp) |
| Dragapult | 1W-4L (20%) | known weak spot, now n=5 |
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

## Patterns

1. **Tempo:** losses with first Grim ≥ t8: 3 (plus one more at t5-6 that lost close races).
   Wins with first Grim t3: 5/6. The deck's Grim tempo remains the dominant lever.
2. **Munk clutter correlates with losses:** 6 of 10 losses had ≥2 Munks on board at t8,
   vs 4 of 17 wins. Consistent with CERT-B late-divergence + the Dragapult audit
   (clutter = spread fodder / lost bench development), but confounded by forced draws.
3. **Dragapult = 4 losses, 2 with severe tempo failure (t11, t14), 2 close races.**
   Deck-level 40% matchup (elite baseline) — live 20% at n=5 is below but overlapping.
4. **Alakazam 6-0 and mirror 83%** are the carry cells — exactly where the field
   battery predicted gains.
5. **No mechanism failures:** no errors, no fallbacks, parity clean.

## Bottom line

EXP23 live ≈ 63% winrate with the expected strengths (mirror, Alakazam) and the
expected weakness (Dragapult). Loss causes are dominated by tempo/draw structure
and close prize races, not by identifiable policy blunders. No action warranted
beyond continued monitoring; the drag-surgical audit concluded no safe policy fix
exists (see DRAGAPULT_SURGICAL_HANDOFF).
