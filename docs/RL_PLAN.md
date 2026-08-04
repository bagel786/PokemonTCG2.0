# Dual-policy RL plan

> **Sequencing update, 2026-07-30:** dual-policy infrastructure is retained, but
> it is not the immediate competition path. First ship the legal Garchomp BC and
> Grimmsnarl heuristic baselines, collect real ladder evidence, and select one
> primary learner. Resume dual training only if ladder results justify it.

## What learns

Garchomp and Grimmsnarl are separate live policies. In each round, both collect
games against the same generation of opponents, then both receive PPO updates.
Neither live opponent is frozen. Historical checkpoints form a bounded minority
of the league so that a new policy must retain answers to older strategies.

The opponent distribution contains:

- the other live learner, with extra sampling weight;
- the learner's current mirror policy;
- all ten archetypes from `freshstart/META.md`, oversampling rare counters;
- elite behavior-cloned policies where replay coverage is adequate; and
- at most eight historical Garchomp/Grimmsnarl checkpoints.

## Reward and update

The environment reward is intentionally sparse and aligned with the competition:
`1` for winning and `0` for losing. The value head estimates win probability and
acts as the policy-gradient baseline. We do not award arbitrary points for taking
prizes, attaching energy, or surviving longer because such shaping can be gamed.

Terminal outcome remains the objective, but terminal-only Monte Carlo credit is
not assumed to be the final estimator. Before scaled training, compare it against
GAE/value-difference advantages on the same rollouts. This gives intermediate
decisions credit when they improve predicted win probability without redefining
the game objective. Direct prize rewards are excluded: prize taking is only one
of three win conditions and a locally favorable prize can still lose the prize
trade, expose a multi-prize attacker, or miss a board/deck-out win.

PPO uses the exact temperature-scaled behavior distribution stored during
collection, clipped importance ratios, gradient clipping, a target-KL stop,
entropy regularization, and an elite behavior-cloning anchor. PPO reconstructs
the ordered without-replacement likelihood for every selected action and the
selection-count likelihood when the legal count is variable, so both single- and
multi-selection decisions receive policy updates.

## Scale and gates

Use short rounds rather than one giant rollout. After ladder evidence selects one
primary archetype, begin with 5,000-20,000 focused games per iteration. A cumulative
100,000-300,000 games is a conditional ceiling, not the default commitment. One to
two million games is not planned.

The measured 1,000-game-per-learner collection produced about 196,600 decisions
in roughly 11 minutes on the 8-vCPU worker. At that rate 100,000 games is about
9-12 hours including update overhead and 300,000 is about 27-36 hours. This fits
daily candidate/evaluation cycles instead of consuming most of the remaining
competition window.

Azure competition infrastructure has an operational ceiling of $150 against the
user's $200 credit balance. The current regular Linux D8s v6 retail compute rate
is $0.484/hour; daily auto-shutdown remains enabled, no second paid worker is
allowed by default, and at least $50 remains reserved for storage, billing lag,
and safety.

Training checkpoints are not automatically deployed. A routine reversible ladder
challenger needs only:

1. zero policy errors in a short official-engine smoke;
2. no catastrophic regression in a 200-500-game incumbent screen; and
3. a packaged Linux/amd64 legality and timeout smoke.

Full elite-agreement, archetype, 2,000-game, and authentic-opponent gates are
reserved for close or final candidates. The ladder supplies the high-validity
signal for normal iteration.

Two thousand games is an experiment screen, not the training budget. Near a 50%
win rate its 95% sampling margin is roughly 2.2 percentage points; 10,000 games is
roughly 1 point, and 50,000 games roughly 0.44 points.

## Example

```bash
python training/run_league.py \
  --bc-shard data/processed/elite-2026-07-28-500.jsonl.gz \
  --iterations 1 \
  --games-per-learner 100 \
  --workers 8 \
  --output-dir artifacts/league_smoke
```

Preserve one live ladder anchor and use the other slot for the challenger. Add
sharded rollout checkpoints and resume manifests before any multi-hour collection
so Azure auto-shutdown cannot invalidate a whole round.
