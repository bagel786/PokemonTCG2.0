# Overnight Grimmsnarl recovery report — 2026-07-30

## Decision

**Recommendation: submit the PPO candidate.** It passed every overnight gate and
is package-ready, but it was not uploaded. The BC candidate is preserved as the
rollback artifact.

## Data

- July 27 v2 shard: 619,853 total decisions, including 420,458 Grimmsnarl
  decisions from 4,224 usable episodes.
- July 28 v1-compatible shard: 69,638 total decisions, including 48,048
  Grimmsnarl decisions from 486 episodes.
- Grimmsnarl training total: 468,506 decisions.
- July 27 outcomes: 336,680 winner-side decisions and 283,173 loser-side
  decisions.
- The July 27 raw-file manifest covered 4,430 files and 21,471,371,045 bytes.
  Raw files were removed only after the v2 gzip and manifest passed validation.
- July 29 and July 28 refresh/download attempts remained blocked by Kaggle HTTP
  429. That failure was bounded and did not block existing-data training.

## Heuristic recovery

The original fixed heuristic matched elite selections 50.15% overall, 40.15% on
main-turn decisions, 20.09% on setup-bench choices, and 16.86% on damage-counter
placement. The hierarchical elite-prior fallback reached 60.93% exact agreement
on 39,380 held-out decisions. It is used only after a neural exception; the
competition policy no longer drops to a heuristic based on an uncalibrated
confidence threshold.

## Feature schema v2

Schema v2 adds context-card, effect-card, looking-zone, and deck-search tokens;
sum/square-root state aggregation that preserves multiplicity; and fixed
per-Pokémon summaries for both active positions and benches. Model archives carry
`model_schema_version`, replay rows carry `feature_version`, and v1 archives remain
loadable.

Real data exposed an eleven-card selection, so the v2 count head supports legal
counts from 0 through 60. This replaced an invalid 0-through-9 head that produced
a non-finite loss. A regression test now covers the eleven-card backward pass.

## Behavior cloning

| Model | Held-out records | Exact selection | Single top-1 | Single top-3 | Count accuracy |
|---|---:|---:|---:|---:|---:|
| v1 full-data control | 43,533 | 71.32% | 72.16% | 93.53% | 98.39% |
| v2 seed 0 | 43,533 | 71.78% | 72.69% | 93.83% | 98.33% |
| v2 seed 1 | 43,533 | 72.12% | 73.06% | 93.94% | 98.33% |
| v2 combined fine-tune | 43,533 | **72.38%** | **73.29%** | **94.05%** | **98.38%** |

The selected BC archive is `grim_bc_best.npz`, with SHA-256
`45c8fa94ee835de74935b321e8535bc2bf9256173c69d6b8fe66c5479abee138`.
The v1 control beat the original heuristic 973–27 over 1,000 seat-balanced
official-engine games with zero policy errors.

## RL correctness

- Stochastic count choice and ordered sampling without replacement are supported.
- Each decision records exact behavior log probability, chosen order, model hash,
  schema version, decision index, and trajectory ID.
- Terminal-outcome GAE uses gamma 1.0 and lambda 0.95. Win/loss remains the only
  objective; no prize, damage, attachment, or survival reward was added.
- PPO replays the count and ordered-selection likelihood, applies a 0.50 BC
  anchor, stops at target KL 0.01, and rolls an epoch back at hard KL 0.02.
- Sixteen automated tests pass.
- A 20-game final-model mixed-league smoke produced 1,793 policy decisions and
  zero opponent-policy exceptions.
- A full-model PPO replay smoke reported approximate KL 0.00056 and clip fraction
  0.0262.

## Packaging

The preserved BC package `grimmsnarl-bc-v2-overnight.tar.gz` is 4,689,234 bytes
with SHA-256
`ebba509ccf674c8357a2de18a838c9aac973ec5badbad3aa2f2f1dddded0a306`.
It passed 20 Linux official-engine games covering 3,909 decisions with zero policy
errors, p99 decision latency 0.76 ms, and maximum observed latency 30.16 ms.

## PPO generation and promotion

The resumable generation completed ten atomic 500-game shards:

- 5,000 games and 458,571 decisions;
- 425,357 trainable decisions;
- 3,106 wins for the exploratory hero (62.12% collection telemetry, not a
  promotion score);
- exact target opponent proportions within sampling variation, including 2,559
  current mirrors, 981 previous Grimmsnarl snapshots, 731 Alakazam 2.7 games,
  244 Alakazam 2.4a games, and 485 other meta games; and
- zero opponent exceptions, invalid log probabilities, ordered-action
  mismatches, or decision-index errors.

PPO completed two epochs without a rollback. Approximate KL was 0.00134 then
0.00166; clip fraction was 0.0638 then 0.0738. Both are well below the target KL
0.01 and hard rollback threshold 0.02.

| Promotion gate | BC | PPO | Result |
|---|---:|---:|---|
| Direct head-to-head, 1,000 games | 47.5% | **52.5%** | pass |
| Elite exact selection, 43,533 records | 72.38% | **72.49%** | pass; +0.11 pp |
| Authentic Alakazam 2.7, 100 games each | 65.0% | **74.0%** | pass; +9.0 pp |
| Crustle screen, 200 games each | 96.5% | 96.5% | pass |
| Mewtwo screen, 200 games each | 100.0% | 99.5% | pass; -0.5 pp |

All 1,200 direct/screen games reported zero hero and opponent policy errors. The
first Alakazam screen exposed a retained-module lifecycle leak in the historical
submission adapter; that incomplete diagnostic was discarded, the leak was
fixed and regression-tested, and a fresh paired 100-game screen produced the
numbers above.

The selected model `grim_selected.npz` has SHA-256
`d842f85abfc44af9f41979f91795e22c92c179b62e04d5a0a2f9c734e70af1c3`.
The final package `grimmsnarl-ppo-5k-overnight.tar.gz` is 4,689,385 bytes with
SHA-256 `3a588e913a7419baf6660130611583f65807a930cde139e9fcfcf0ec7a837489`.
It passed 20 Linux games and 3,911 decisions with zero policy errors, p99 latency
0.78 ms, and maximum observed latency 29.28 ms.

## Azure operations

Auto-shutdown was extended to 15:00 UTC. At final packaging, VM uptime was 9.75
hours; at $0.484/hour the conservative full-boot compute estimate was $4.72.
This is far below both the $150 operational ceiling and the user's $200 credit
balance. All 149.8 MB of overnight artifacts plus both BC and PPO packages were
synchronized locally and verified by SHA-256 before explicit VM deallocation.

No Kaggle submission is performed by this workflow.
