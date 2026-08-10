# Live ladder comparison: d842 exact (55397271) vs A2 ordered (55399728)

Generated 2026-08-10 17:25 UTC from `data/replays/*/episodes_metadata.json`. Regenerate with:

```powershell
python scripts/fetch_submission_games.py --submission 55397271 55399728
python scripts/build_live_comparison_report.py 55397271 55399728 --out docs/LIVE_LADDER_D842_VS_A2.md
```

## Verdict

The **77.8-point public-score gap is not evidence of a strength difference.** Two shipments of the byte-identical d842 agent differ by at least that much **67% of the time** (15 shipments, sd 122.0). The live win-rate gap is not significant (permutation p = 0.26), and the two agents faced **1 shared opponent(s) out of 82** distinct opponents — effectively disjoint fields.

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
   823.4   826.9   839.3   853.8   866.5   906.3   969.7
```

- mean **774.2**, sd **122.0**, range 492.6–969.7 (spread 477.1)
- median absolute gap between two reships: **139.4**
- P(gap >= 77.8 | same agent) = **67%**

A2 ordered's 776.0 sits essentially on d842's own 15-ship mean of 774.2. The 853.8 run was a favourable draw, not a better agent.

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

