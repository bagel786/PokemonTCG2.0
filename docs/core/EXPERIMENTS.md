# Experiment ledger

Results in this file are local engine measurements, not Kaggle leaderboard claims. Games are
seat-balanced. A neural checkpoint is promoted only when its head-to-head evidence improves on
the matching incumbent and it passes archive validation on Linux/amd64.

## Data snapshot

- Source: public competition replays dated 2026-07-28.
- Downloaded: 513 replay JSON files (about 2.3 GB raw).
- Filter: games involving the published top-100 team list.
- Processed: 69,638 legal decisions from 486 episodes.
- Grimmsnarl subset (`card 648`): 48,048 decisions.
- Garchomp subset (`card 381`): 1,231 decisions.
- Replay alignment: observation at step `t`, submitted action at step `t+1`.
- Features exclude opponent hand, opponent deck order, visualization state, and other private
  fields that are unavailable to a live agent.

## Baseline floor

| Agent | Opponent | Games | Wins | Win rate | Status |
|---|---:|---:|---:|---:|---|
| Grimmsnarl heuristic | random legal | 100 | 84 | 84.0% | ready |
| Garchomp heuristic | random legal | 100 | 91 | 91.0% | ready |
| Garchomp heuristic | Grimmsnarl heuristic | 1,000 | 554 | 55.4% | matchup baseline |

The random-policy matches are legality and gross-regression checks, not estimates of competitive
strength.

## Behavior cloning

| Challenger | Held-out action top-1 | Matchup | Games | Wins | Win rate | Wilson 95% | Decision |
|---|---:|---|---:|---:|---:|---:|---|
| Grimmsnarl BC (500-file shard) | 63.28% | Grim heuristic | 1,000 | 483 | 48.3% | 45.2–51.4% | reject |
| Garchomp BC (500-file shard) | 48.3% | Garchomp heuristic | 1,000 | 556 | 55.6% | 52.5–58.7% | candidate |
| Garchomp BC (500-file shard) | 48.3% | Grim heuristic | 1,000 | 583 | 58.3% | 55.2–61.3% | candidate |

The Garchomp validation split contains only 169 held-out decisions. Its local matchup result is
encouraging, including a 2.9 percentage-point gain over the heuristic's Grimmsnarl matchup, but
the replay sample is too small to call it a final policy.

## Self-play RL smoke test

- Seed: Grimmsnarl behavior-cloning checkpoint.
- Collection: 40 games / 3,579 decisions, sampled at temperature 0.65 against the heuristic.
- Update: one PPO-style epoch with a behavior-cloning anchor.
- Evaluation: 52 wins in 100 games against the Grimmsnarl heuristic.
- Decision: not promoted; the experiment proves the RL path runs end-to-end but does not provide
enough evidence of an improvement.

## RL correctness audit and synchronized dual league (2026-07-29)

The initial smoke path was not ready for scaled training: collection sampled a
temperature-scaled policy while PPO recomputed unscaled action probabilities,
which invalidated its importance ratio. The update now stores and reuses the
exact behavior temperature, reports approximate KL and clip fraction, stops at a
target KL, clips gradients, and retains the elite behavior-cloning anchor.

`training/run_league.py` collects generation-N games for every live learner
declared in `training/learners.json` before updating any of them. All policies
advance only after every rollout set exists. A bounded pool of at most eight historical checkpoints
is mixed with the live cross-play opponent and all ten meta archetypes; historical
models do not replace either live learner.

End-to-end dual smoke: 20 games per learner. Garchomp collected 1,704 decisions
and Grimmsnarl 2,429. Both produced loadable challengers over two PPO epochs;
approximate KL remained below 0.004 and clip fraction below 0.043. These samples
validate the pipeline only and are not promotion evidence.

The ten-archetype legality smoke completed 100 games / 11,063 decisions with zero
hero or opponent policy errors after fixing attached-card feature handling. Its
matchup win rates are not strength estimates because most opponent archetypes
still use generic heuristics pending more elite replay coverage.

## Historical Alakazam opponents

Two user-provided Kaggle archives, recalled around the low 800s and 870, passed
archive path/static-source audits. Both use the same Alakazam 60-card multiset but
materially different decision systems. Version 2.7 uses a learned direct policy;
2.4a uses expensive determinized rollout search. Their exact historical rating
mapping is unknown and may be stale.

Both authentic agents completed a four-game seat-balanced integration smoke with
zero policy errors and defeated the Garchomp BC incumbent in all four games. The
sample is too small for a win-rate claim, but it establishes a useful hard
Alakazam regression suite. Scaled training uses both learned priors with
verified-lethal search disabled and combined league weight capped at eight;
authentic search remains an evaluation gate for both artifacts.

## Azure two-day challenger (2026-07-30)

The first Jul 27 fetch used one Kaggle request per episode and was throttled after 43 of 4,430
files. Those 43 episodes contributed 6,137 decisions overall, but did not enlarge the held-out
Garchomp set (169 decisions). The resulting eight-epoch Garchomp checkpoint produced:

| Matchup | Games | Wins | Win rate | Wilson 95% |
|---|---:|---:|---:|---:|
| New BC vs Garchomp heuristic | 2,000 | 1,070 | 53.5% | 51.31–55.68% |
| New BC vs Grimmsnarl heuristic | 2,000 | 1,197 | 59.85% | 57.68–61.98% |
| New BC vs prior Garchomp BC | 2,000 | 964 | 48.2% | 46.02–50.39% |

Decision: reject the new checkpoint and retain `garchomp_bc_500.npz` as the incumbent. The
downloader now uses Kaggle's single bulk archive for full-day requests with exponential backoff;
a full Jul 27 retry is queued before the next retraining cycle.

## Submission artifacts

### Freshstart ladder anchors

| Submission ID | Agent | Artifact | Role |
|---:|---|---|---|
| `55099955` | Garchomp BC | `garchomp-bc500-candidate-v2.tar.gz` | ladder baseline |
| `55099961` | Grimmsnarl heuristic | `grimmsnarl-heuristic-v1.tar.gz` | ladder baseline |

Both were uploaded manually on 2026-07-30. Kaggle API status checks were still
rate-limited with HTTP 429 immediately after upload.

| Archive | SHA-256 | Engine | Status |
|---|---|---|---|
| `grimmsnarl-heuristic-v0.tar.gz` | `e3d01f49ddac2ffbc1024343a35eda8130a047c8ec9839e995e30e70577133a5` | current official | submission-ready floor |
| `garchomp-heuristic-v0.tar.gz` | `0fbc9a2d9aa010b2079872fb5a7796543870c37eec12ebfa39e26ba83bbac902` | current official | submission-ready floor |
| `garchomp-bc500-candidate.tar.gz` | `b7e8d521a4a15686c398b9f60c17b6b9e8f93316f581c168c8a6c94b12a84c02` | current official | neural candidate |
| `garchomp-bc500-candidate-v2.tar.gz` | `1951cde27d93c13e7c0090d3962ca186a7a7ecbe9c9cc7e38e1f48923fbec693` | current official | current neural candidate; Linux/amd64 validated |

Official Linux engine SHA-256 used by all three archives:
`d16244a3157fc55c3314f08dcc7c5179168697d78c105b95c7debd556b764bb7`.

The two artifacts containing `sample-not-promoted` or the standalone sample PPO checkpoint are
diagnostic outputs and must not be submitted. Every Kaggle upload remains manual because it
evicts the older of the two live agents.

## Next promotion experiment

1. Pull additional days of top-player replays, prioritizing Garchomp episodes until the held-out
   set contains at least several thousand decisions.
2. Retrain multiple seeds and compare them against both the Garchomp incumbent and the dominant
   Grimmsnarl matchup over at least 2,000 seat-balanced games each.
3. Start PPO from the strongest stable BC seed; retain the BC loss as an anchor and vary
   opponent mixtures rather than training only against one heuristic.
4. Promote only a policy whose lower confidence bound and cross-matchup results beat the current
   incumbent, then package and validate it on Linux/amd64.
