# Dragapult Emergency BC — Stage 0 Feasibility Report

Crawl timestamp: 2026-08-14 14:10 UTC (leaderboard snapshot: 6,815 teams).
Branch: `dragapult-emergency-bc`.

## Summary

**VERDICT: Stage 0 kill gate PASSED decisively.**

The current leaderboard Dragapult surge is real and its pilots are highly
crawlable. Five current elite teams pilot the *identical* modern
Dragapult ex / Munkidori decklist (`bbe68b1e00e51226`, matching our
`freshstart/decklists/dragapult_ex.txt` exactly), with 561 public completed
episodes exposing **62,669 usable hero decisions** in the last ~48 hours.

## Teacher roster (as of crawl)

| Team | Rank | Submission | Score | Episodes | Decisions | Win% | Deck |
|---|---|---|---|---|---|---|---|
| flg | 1 | 55456110 | 1254.5 | 99 | 10,756 | 73% | exact |
| flg | 1 | 55456208 | 1165.6 | 120 | 13,447 | 72% | exact |
| Kh0a | 17 | 55504533 | 1139.4 | 50 | 5,918 | 77% | exact |
| Kh0a | 17 | 55504550 | 1117.3 | 47 | 5,585 | 81% | exact |
| 213tubo | 14 | 55502744 | 1135.7 | 53 | 6,309 | — | exact |
| Raihan Ramadistra | 13 | 55494171 | 1151.7 | 66 | 7,852 | — | exact |
| Raihan Ramadistra | 13 | 55474573 | 889.3 | 71 | 8,304 | — | exact |
| atsushi11o7 | 81 | 55492763 | 1014.7 | 59 | 5,862 | — | exact |

All teachers: zero parse errors, zero duplicate episodes, single deck hash.
flg's IS_FIRST behavior: always "first" (287/287) — matches the runtime hardcode.

Additional Dragapult-adjacent teams (BigBugg #41, saeNeko #72, Boseiju #79,
aaa #73, RtoABC #68, MTamago #35, 宝糕手 #39, KawattaTaido #60) expose another
~1,000 episodes; crawl in progress, mixed decklists (Dudunsparce/Dusknoir
variants) to be hash-filtered at extraction.

## Opponent diversity (flg)

Dragapult mirror ~56%, Grimmsnarl ~9%, Alakazam ~8%, Dudunsparce ~6%,
Crustle ~5%, Lucario ~5%, Ogerpon ~6%, others. flg's win rate vs Grimmsnarl
opponents: **19/21 (90%)** — the matchup itself is fine for the teachers.

## Initial BC learning curve (validation = newest 33 flg episodes, held out)

| Corpus | Episodes | Top-1 | Top-3 |
|---|---|---|---|
| flg-a only | 84 | 52.0% | 81.5% |
| flg 25% | 46 | ~50% | ~82% |
| flg 50% | 93 | 55.9% | 85.1% |
| flg 100% | 186 | 59.6% | 86.9% |
| all 8 submissions | 477 | **65.3%** | **90.7%** |
| all 8 (semantic-loss) | 477 | 66.0% | 91.1% |

Agreement is improving monotonically with data — teacher behavior is
learnable. Per-context: main-phase play choices (ctx 0) are the hardest
bucket (~44-56% top-1) and dominate the error mass. Count-head accuracy on
variable-count prompts: 95.3%.

## Early gameplay probes (unpaired, non-deterministic engine)

| Candidate | vs Dipplin S1 | vs A2+Damage V0 |
|---|---|---|
| bc_flg_full (59.6%) | 50/100 (50%) | 6/100 (6%) |
| bc_combined (65.3%) | — | 23/150 (15.3%) |
| bc_combined_sem (66.0%) | — | 24/150 (16.0%) |

Operational errors: zero everywhere. The clone is competitive against mature
Dipplin S1 but catastrophically weak against the Grimmsnarl A2+Damage V0 —
a bucket the teachers win 90% of. This is the primary open problem, not a
Stage-0 data problem.

## Next steps (sprint)

1. Longer training, Grimmsnarl-row upweighting, order-specific variants.
2. Crawl the additional ~1,000 episodes and retrain.
3. Population screen; promote only if the A2+Damage bucket recovers.
