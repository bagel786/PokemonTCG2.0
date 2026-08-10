# Live ladder comparison: d842 exact (55397271) vs A2 ordered (55399728)

Generated 2026-08-10 17:46 UTC from `data/replays/*/episodes_metadata.json`. Regenerate with:

```powershell
python scripts/fetch_submission_games.py --submission 55397271 55399728
python scripts/build_live_comparison_report.py 55397271 55399728 --out docs/LIVE_LADDER_D842_VS_A2.md
```

## Verdict

The **77.8-point public-score gap is not evidence of a strength difference.** Two shipments of the byte-identical d842 agent differ by at least that much **67% of the time** (15 shipments, sd 122.3). The live win-rate gap is not significant (permutation p = 0.26), and the two agents faced **1 shared opponent(s) out of 82** distinct opponents — effectively disjoint fields.

Offline evidence, which has ~350x the sample size, favours A2 by roughly +25 Elo. Gate on that, not on public score.

## Live rated public games

| | d842 exact (55397271) | A2 ordered (55399728) |
|---|---|---|
| Rated public games | 43 | 40 |
| Window (UTC) | 2026-08-10 05:12 → 2026-08-10 15:18 | 2026-08-10 07:12 → 2026-08-10 16:47 |
| **Win rate** | **69.8%** [54.9, 81.4] | **57.5%** [42.2, 71.5] |
| Actually first | 68.8% (n=16) | 65.0% (n=20) |
| Actually second | 70.4% (n=27) | 50.0% (n=20) |
| Mean opponent rating | 733.7 | 742.5 |
| Median opponent rating | 764.6 | 759.8 |
| Final public score | 853.8 | 776.0 |
| Performance rating (opponent-adjusted) | 889.7 | 800.8 |
| Distinct opponents | 43 | 40 |

Win rates are Wilson 95% CIs. Performance rating is the Elo at which observed score equals expectation against the actual opponents faced; unlike public score it does not reward an easy draw.

## Significance

| Test | Result |
|---|---|
| Overall win-rate gap | +12.3 pts, permutation p = **0.26** |
| Opponent-adjusted gap | permutation p = **0.30** |
| First-seat gap | +3.8 pts, p = 1.00 |
| Second-seat gap | +20.4 pts, p = 0.23 |
| Games/arm to resolve a 12.3-pt gap at 80% power | **480** |

Nothing here is significant. Both arms are roughly an order of magnitude too small.

## The empirical null: reships of the identical agent

`grimmsnarl_5k_reference` is the same d842 bytes shipped 15 times:

```
   492.6   660.1   664.6   665.3   700.8   714.4   810.0   818.7
   823.4   826.9   839.3   860.7   866.5   906.3   969.7
```

- mean **774.6**, sd **122.3**, range 492.6–969.7 (spread 477.1)
- median absolute gap between two reships: **142.8**
- P(gap >= 77.8 | same agent) = **67%**

A2 ordered's 776.0 sits essentially on d842's own 15-ship mean of 774.6. The 853.8 run was a favourable draw, not a better agent.

## Win rate by opponent rating band

**d842 exact (55397271)**

| Opponent band | Overall | First | Second |
|---|---|---|---|
| 0–700 | 78.6% (n=14) | 100.0% (n=6) | 62.5% (n=8) |
| 700–800 | 76.5% (n=17) | 40.0% (n=5) | 91.7% (n=12) |
| 800–900 | 50.0% (n=12) | 60.0% (n=5) | 42.9% (n=7) |

**A2 ordered (55399728)**

| Opponent band | Overall | First | Second |
|---|---|---|---|
| 0–700 | 44.4% (n=9) | 100.0% (n=2) | 28.6% (n=7) |
| 700–800 | 68.4% (n=19) | 70.0% (n=10) | 66.7% (n=9) |
| 800–900 | 50.0% (n=10) | 42.9% (n=7) | 66.7% (n=3) |
| 900–3000 | 50.0% (n=2) | 100.0% (n=1) | 0.0% (n=1) |

Both profiles are **non-monotone** in opponent strength — win rate does not fall as opponents get stronger. That is the signature of small-sample noise, not a strength profile, and it is the main reason these live splits should not drive a ship decision.

## Why the live comparison cannot settle it

1. **Disjoint fields.** 1 shared opponent(s) out of 82. The two agents were scored against different populations.
2. **Different pacing.** d842 exact played 43 games in 2026-08-10 05:12→2026-08-10 15:18; A2 ordered played 40 in 2026-08-10 07:12→2026-08-10 16:47. Games are front-loaded during the high-sigma burn-in, so equal game counts are not equal information.
3. **Sample size.** ~480 games per arm are needed; there are 43 and 40.

## Offline evidence (for contrast)

| Source | Games | A2 win rate vs d842 |
|---|---:|---|
| Mirror gate (`docs/grim_recovery_analysis.md`) | 30,000 | 53.657%, Wilson LB 53.09% (+3.50 seat 0, +4.26 seat 1) |
| `eval_a2_first_vs_d842_500.json` | 500 | 54.6% [50.2, 58.9] |
| `eval_a2ordered_second_vs_d842_500.json` | 500 | 52.6% [48.2, 56.9] |
| Pooled direct head-to-head | 1,000 | 53.60% [50.50, 56.67], binomial p = 0.025 |

Two independent designs over ~31,000 games both land on ~53.6%, i.e. **≈ +25 Elo** for A2. Real, but small — and A2 remains weak second vs master-v1 (43.6%).

## Loss buckets and the shape of each run

Regenerate the full per-game tables with `python scripts/loss_buckets_live.py <submission>`.

### Streak structure

| | d842 exact | A2 ordered |
|---|---|---|
| Longest loss streak | 3 | 6 |
| Longest win streak | 8 | 5 |
| Runs vs expected | 19 vs 19.1 | 14 vs 20.6 |
| Wald-Wolfowitz p | **0.959** | **0.032** |

A2 ordered's results are **clustered beyond chance** (p = 0.032); d842 exact's are not (p = 0.959). The streaks you can see in the A2 run are real, not pattern-matching on noise.

### Phase breakdown

**d842 exact**

| Games | W-L | WR | Mean opp | Rating end | Net | Mean rating move |
|---|---|---|---|---|---|---|
| 1-7 bad start | 3-4 | 42.9% | 616 | 568.2 | -31.8 | 72.0 |
| 8-15 eight-win run | 8-0 | 100.0% | 690 | 793.4 | +225.1 | 28.1 |
| 16-32 churn | 10-7 | 58.8% | 779 | 806.4 | -3.5 | 11.4 |
| 33-43 climb to peak | 9-2 | 81.8% | 771 | 853.8 | +46.2 | 6.8 |

**A2 ordered**

| Games | W-L | WR | Mean opp | Rating end | Net | Mean rating move |
|---|---|---|---|---|---|---|
| 1-8 climb to 953 | 7-1 | 87.5% | 748 | 953.0 | +353.0 | 60.5 |
| 9-14 the crash | 0-6 | 0.0% | 788 | 747.6 | -205.4 | 34.2 |
| 15-32 churn | 10-8 | 55.6% | 722 | 748.4 | +0.8 | 14.4 |
| 33-40 tail | 6-2 | 75.0% | 749 | 776.0 | +27.6 | 8.6 |

**The mean-rating-move column is the whole story.** TrueSkill sigma collapses as games accumulate, so early games are worth several times more than late ones. A2 ordered peaked at 953.0 after 8 games, then lost 6 straight while moves were still worth ~34 points each (-205.4). It then went 16-10 (61.5%) over the remaining 26 games and earned only +28.5 for it — at the late rate (~9 points) it would need ~16 consecutive wins to return to its peak. d842 exact had the mirror-image luck: it opened **3-4**, worse than A2, but its recovery — an 8-0 run — landed while moves were still worth ~28 points each, banking +225.1. Both agents were volatile. Only one was volatile at the right time, and that is the entire 78-point gap.

### Loss quality

| | d842 exact | A2 ordered |
|---|---|---|
| Losses | 13 | 17 |
| Mean loss margin (prizes) | +1.62 | **+1.24** |
| Mean win margin (prizes) | +1.77 | **+2.17** |
| Margin quality (win − loss) | +0.15 | **+0.94** |
| Blowout losses (>=4 prizes) | 3/13 | **0/17** |
| Shutout losses (0 prizes taken) | 2 | **0** |
| Close losses (<=1 prize) | 8/13 | 10/17 |

A2 ordered **wins more decisively and loses more narrowly** than d842 exact on every margin measure, with zero blowouts and zero shutouts against 3 and 2 for d842 exact. Neither margin gap is significant on its own (permutation p = 0.46 and 0.56), but the direction is independent of the offline evals and agrees with them.

Prize margins are read from the last recorded position, which lags the finish: the engine never emits a terminal state (`result` stays -1 and prizes never reach 0). Treat them as accurate to about one prize, and as a comparison between agents rather than an absolute.

### Matchups

| Opponent deck | d842 exact | A2 ordered |
|---|---|---|
| Alakazam | 6/9 (67%) | 6/12 (50%) |
| Grimmsnarl ex (mirror) | 8/12 (67%) | 2/4 (50%) |
| Mega Lucario ex | 2/5 (40%) | 4/6 (67%) |
| Archaludon ex | 5/5 (100%) | 1/3 (33%) |
| Mega Kangaskhan ex | 1/3 (33%) | 2/3 (67%) |
| Cynthia's Garchomp ex | — | 2/3 (67%) |
| Crustle | — | 1/3 (33%) |

**Alakazam is the single largest slice of the field** — 21% of d842 exact's games and 30% of A2 ordered's, consistent with the 2026-08-08 census that flagged it as a priority matchup. It is also the biggest single bucket of A2 losses (6 of 17). A2 is 6/12 there against d842's 6/9. Pooled across both agents the matchup is 12/21, so treat the per-agent split as suggestive only — but Alakazam is where the offline work should point.

### Free wins

- A2 ordered game 7 (episode 91580056): 3 turns, statuses `DONE,DONE` — opponent failed rather than A2 outplaying it.
- A2 ordered game 17 (episode 91588467): 15 turns, statuses `ERROR,DONE` — opponent failed rather than A2 outplaying it.

Both landed inside the opening high-sigma window, so they inflated the 953 peak that the subsequent 'crash' partly just gave back.

d842 exact had 0 non-clean termination(s).

## What to act on

1. **Do not read the score gap as a strength difference.** It is inside the same-agent reship null.
2. **Do not read A2's crash as a policy defect.** Zero blowouts, zero shutouts, 4 of the 6 crash losses decided by a single prize.
3. **Ladder placement is dominated by when volatility lands, not by strength.** Both agents swung; d842's swing landed favourably and A2's did not.
4. **Alakazam is the real target.** Largest share of the field and the largest bucket of A2's losses.

