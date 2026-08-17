# Post-Deadline Rating Projection (2026-08-17)

Where the two final arena submissions end up over the remaining ~2 weeks,
given today's live game data.

## Current state

| Sub | Record | Rating | Last 20 | Last 10 |
|---|---|---|---|---|
| 55565462 `exp23_dip_surgical` (dip_b) | 27W-23L (54.0%) | 782.0 | 9W-11L (45%) | 4W-6L (40%) |
| 55565454 `exp23_dip_drag_end_evolve_veto_blaze` (veto) | 25W-23L (52.1%) | 745.9 | 9W-11L (45%) | 4W-6L (40%) |

## Why we are where we are

1. **The veto is irrelevant.** It fired 0 times in 47 live games (only 2
   Dragapult matchups, 1W-1L). Offline replay of both packaged modules against
   every live game shows zero decision divergences. The 44-point gap between
   the two subs is one early high-sigma upset: a -126.5 loss vs a 496-rated
   opponent at 05:54 on 08-17, plus a luckier placement block for dip_b
   (+228 vs +199 over the first 10 games).
2. **Recent losses are blowouts, not coin flips.** 5 of 11 dip_b losses in the
   last 20 ended at 0-1 prizes; only 1 loss was close (4+ prizes). Typical
   loss: opponent takes 4-5 prizes by turn 9-13.
3. **Losses cluster by matchup, not rating.** Last 20: Grimmsnarl mirror
   0W-4L, Lucario 0W-2L, Dudunsparce 0W-2L, while Alakazam is 5W-1L.
   Opponent rating in losses (792 avg) is barely higher than in wins (760).
4. **Going second is the biggest leak.** dip_b last 20: 62% going first
   (8W-5L) vs 14% going second (1W-6L). The second-player losses span all
   matchups (2 mirror, 2 Lucario, 1 Alakazam, 1 Dudunsparce) - it is a
   general second-player problem, not a mirror-specific one.

## Projection model

- Empirical drift at 45% form: -1.25 pts/game (net -24.9 over the last 20).
- Pace: ~96 games/day once the arena ramps (observed ~5.4/hr across the
  daytime window) -> roughly 1350 games over the remaining 14 days.
- TrueSkill stakes decay as rating falls, so the rating converges to the
  equilibrium where we go ~50% against the pool we are matched into.
- Monte Carlo with win probability anchored to p(790) = 45% and an
  equilibrium band of 720-745, stakes +6.9/-7.9 (empirical last-20):

| Sub | Median | P25-P75 | P10-P90 | P(>=860) |
|---|---|---|---|---|
| dip_b | **~700** | 670-730 | 640-760 | ~0% |
| veto | **~665** | 635-695 | 620-720 | ~0% |

## Prediction

- **dip_b: ~700** (range 670-730), converging down from 782.
- **veto: ~665** (range 635-695), converging down from 746.
- 860 is out of reach at current form; it would require a sustained >=54%
  win rate, and the recent 20-game sample says 45%.

Caveats: seat split is a coin flip (going second has been brutal - some
mean-reversion there could add ~30-50 points), the meta mix can shift, and
the equilibrium band is inferred from a 20-game window.
