# Candidate B report — 2026-08-04

## Verdict

**Failed the ship gate. Nothing was packaged or submitted.**

Winner-only elite behavioral cloning produced small, real offline imitation
gains, but those gains did not translate into a Grimmsnarl mirror improvement.
The selected finalist scored 49.83% over 10,000 games against the original d842
5k checkpoint and failed the structural/seat-split superiority gate.

## Data

- August 3 dataset: all 4,720 exposed JSON episodes streamed; zero failures and
  zero raw episodes retained.
- Exact 60-card Grim units: 3,002 total, including 1,388 winners and 470 winning
  mirrors.
- Retained fresh winning decisions: 143,384.
- Leakage-safe fresh splits: 111,932 train, 12,216 internal validation, 19,236
  whole-team holdout.
- Latest pure-5k holdout (`55222011`): 6,344 decisions from 66 games, excluded
  wholesale from training.
- Historical exact-signature rehearsal: 454,053 decisions.
- Own exact-d842 ladder rehearsal: 35,017 decisions from 373 games.

Training source weights were 55% fresh elite wins, 30% historical exact-Grim
rehearsal, and 15% exact-d842 ladder rehearsal. Loss outcomes were not used as
negative action labels.

## Candidates

All candidates started from SHA256
`d842f85abfc44af9f41979f91795e22c92c179b62e04d5a0a2f9c734e70af1c3`.

| Candidate | Unseen-team exact delta | d842 holdout exact drift | 500-game mirror |
|---|---:|---:|---:|
| heads, lr 3e-5 | +0.20 pp | -2.33 pp | 49.8% |
| heads, lr 1e-4 | +0.56 pp | -2.99 pp | 52.0% |
| representation + heads | +0.51 pp | -3.14 pp | 51.4% |

The generic elite temporal gate was not applicable to the d842 self-labeled
holdout: d842 necessarily matches its own recorded actions 100%. The corrected
Candidate B audit treated that set as bounded drift (4% aggregate/seat, 5% in
large contexts, 0.5% count) while retaining strict unseen-elite non-regression.
No weights were retrained after this correction.

## Simulator gates

- 2,000-game semifinals:
  - heads lr 1e-4: 51.6% overall, 49.1% going second.
  - representation + heads: 51.35% overall, 49.7% going second.
- 10,000-game finalist mirror: **49.83% overall** (95% Wilson
  48.85–50.81%), 52.6% going first, 47.06% going second.
- Versus the independent 10,000-game d842 structural control, observed seat
  lifts were +1.34 pp going first and +0.40 pp going second, but neither met
  the confidence/non-inferiority requirements; overall superiority also failed.
- Lucario non-regression: 90.5% candidate vs 90.0% d842 — passed.
- Bellibolt non-regression: 94.1% candidate vs 93.7% d842 — passed.
- Authentic Alakazam was stopped after the structural failure because it could
  no longer change the ship verdict and was unusually slow locally.
- Zero policy/engine errors in completed gates.

## Interpretation and next lever

Winner-only BC does not identify which actions caused a win; it improved
agreement with elite play without improving game outcomes. More days of the
same broad BC, heavier weights on ladder games, or another self-play PPO pass
are therefore low-value repetitions of signals now shown to be insufficient.

The next credible experiment is **targeted counterfactual distillation**:

1. Select mirror/going-second states where d842 disagrees with fresh elite play.
2. Use engine search/rollouts to score the legal alternatives at those states.
3. Train only on choices with demonstrated positive counterfactual advantage,
   retaining d842 rehearsal and KL protection.
4. Reuse the same 10,000-game structural and matchup gates.

A secondary option is conservative offline RL using both winning and losing
exact-Grim episode-seats to learn a critic, followed by advantage-weighted
regression. That requires another streaming pass because only winning decisions
were retained in this experiment.

## Artifacts

- Data/split manifest: `artifacts/candidate_b_20260804/refresh_data/split_manifest.json`
- Candidate reports: `artifacts/candidate_b_20260804/candidates/*/candidate.json`
- Final gate report: `artifacts/candidate_b_20260804/gates/final_report.json`
