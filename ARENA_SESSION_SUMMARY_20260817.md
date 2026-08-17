# Arena Session Summary (2026-08-17)

Full analysis session on the post-deadline ladder games for the two final
submissions of `pokemon-tcg-ai-battle`:
- `55565462` — exp23_dip_surgical (dip_b)
- `55565454` — exp23_dip_drag_end_evolve_veto_blaze (veto)

## 1. Baseline question: odds of 794 -> 860

- Pulled all live episodes via `EpisodeService/ListEpisodes` (agent rewards +
  score deltas; no replay downloads needed).
- Early records: dip_b 26W-21L (55.3%), veto 25W-21L (54.3%).
- At those rates and +/-5 stakes, reaching 860 was ~62-82%; breakeven win rate
  54.4% (50% odds), 56.8% (90% odds).
- Stakes are not fixed +/-5: early games swing +/-20-25, recent games settle
  at ~+6.9/-7.9.

## 2. Why veto was ~50 points behind dip_b

- Replayed all 47-51 live games offline through both packaged modules
  (`scripts/veto_vs_dipb_live.py`).
- The veto **fired 0 times in 47 games** — the ladder only matched it vs
  Dragapult twice (1W-1L), and in neither game did the END->EVOLVE conditions
  line up.
- Zero decision divergences between the two modules across every live game;
  both reproduce the live action streams (standard 1-step replay offset).
  The two submissions are behaviorally identical in practice.
- The 44-point gap is early-phase rating variance: one -126.5 upset loss vs a
  496-rated opponent at 05:54 on 08-17, plus a luckier placement block for
  dip_b (+228 vs +199 over the first 10 games).

## 3. Loss quality (not coin flips)

dip_b last 20 (9W-11L):
- 5 losses at 0-1 prizes (blowouts), 5 at 2-3 prizes, only 1 close (5-4).
- Typical loss: opponent takes 4-5 prizes by turn 9-13.
- Losses cluster by matchup, not rating (opp avg 792 in losses vs 760 in wins):
  - Grimmsnarl mirror 0W-4L
  - Lucario 0W-2L
  - Dudunsparce 0W-2L
  - Crustle 0W-1L (vs a 616)
  - Alakazam 5W-1L (still farming)

## 4. First vs second player

- dip_b overall: 64% first (18W-10L) vs 38% second (8W-13L).
- dip_b last 20: 62% first vs **14% second (1W-6L)**.
- The 6 second-player losses: 2 mirror, 2 Lucario, 1 Alakazam, 1 Dudunsparce —
  a general second-player problem, not mirror-specific.
- Going second vs opp <800: 38%; vs <750: 62% — the handicap only shows
  against opponents close to our rating.
- Seat split is fair: 54 first / 45 second across 99 games.
- `SelectContext.IS_FIRST`: our agent answered YES 42/42 when asked and went
  first every time. Opponents were asked 57 times: YES 45, NO 12 (12 games
  where they declined and handed us first). We have no control over the 45.

## 5. Rating band performance (combined 99 games, 52W-47L = 52.5%)

| Opponent band | Record | Win rate |
|---|---|---|
| < 600 | 5W-1L | 83% |
| 600-700 | 10W-3L | 77% |
| 700-750 | 12W-9L | 57% |
| 750-800 | 13W-14L | 48% |
| 800-850 | 9W-11L | 45% |
| 850+ | 1W-9L | 10% |

- 850+ losses split evenly by seat (3 first / 3 second) — genuine skill gap at
  the top, not seat luck. The lone 850+ "win" was a 0-0 game vs an 1108-rated
  opponent (likely opponent error).
- Monotonic curve -> 50% crossover ~= 770 = equilibrium rating.

## 6. Projection model

- Mean-reverting rating model: p(win) = 0.5 - (rating - equilibrium)/700,
  stakes +/-7.2, rating-matched opponents.
- 48/day x 14 days = 672 games; 96/day = 1344 games.
- Last-20 45% form implied equilibrium ~735; seat-adjusted 51% implied ~800;
  combined-bucket curve says ~770.

## 7. Final predictions

| Sub | Start | Median final | IQR | P(final >= 845) | P(touch 845+) |
|---|---|---|---|---|---|
| dip_b | 782.9 | ~768 | 740-797 | 1.3% | 63% (48/d) / 85% (96/d) |
| veto | 739.2 | ~768 | 739-797 | 1.4% | 61% (48/d) / 85% (96/d) |

- 860: effectively out of the question — needs sustained >=54% win rate;
  measured form is 45% (last 20) / 51% (seat-adjusted) / 52.5% (combined).
- Bronze (845+, ~rank 690): final ~1-4%, but transient touch 60-85%.
- Bronze cutoff is a moving target (still inflating), and medals use final
  rating, not peak.

## 8. Latest games

- dip_b: 782.9 (28W-24L, 53.8%), last 6 = 2W-4L.
- veto: 739.2 (26W-25L, 51.0%), last 6 = 1W-5L.
- Newest dip_b loss (ep 93963269): Grimmsnarl mirror, going second, 3-5
  prizes in 12 turns — opponent's Grimmsnarl ex online T7, ours T8; the
  standard one-turn-late second-player snowball.
- Arena now occasionally matches much lower-rated opponents (258-437) at
  tiny stakes (+/-0.3-0.9), pool thinning or new weak submissions entering.

## Artifacts

- `scripts/veto_vs_dipb_live.py` — offline replay diff of both packaged
  modules against every live game.
- `data/replays/<sub_id>/episodes_metadata.json` — live episode records
  (rewards + score deltas) for both submissions.
- `POST_DEADLINE_RATING_PROJECTION.md` — earlier projection writeup.
