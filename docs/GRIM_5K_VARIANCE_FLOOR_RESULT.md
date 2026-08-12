STARTING SHA: f4451863ea61e007a184695b01f7b4224dff85a6
FROZEN MODEL SHA: D842F85ABFC44AF9F41979F91795E22C92C179B62E04D5A0A2F9C734E70AF1C3
FROZEN DECK SHA: 92B92BAC9F9163ECFF933B3DC39294D2CC154C8684F3C8497877661419EBC59D
FINAL EXPERIMENT SHA: e423b14

# Grim 5k Variance Floor

## Correctness Fixes

Confirmed and fixed the B3 direct-retreat state bug. A direct dead-support
RETREAT now arms a semantic promotion proposal, commits it only when the exact
RETREAT action is actually selected, then forces ready-Grim promotion on the
following `TO_ACTIVE`/`SWITCH` prompt. State stores no option index.

Added coverage for the complete direct and attach escape sequences, reordered
promotion options, retreat-used/productive/wrong-Active cases, missing or
non-ready Grim, invalid attachment source/target, insufficient retreat cost,
malformed state, target disappearance, turn/player changes, reset, and alternate
committed actions.

Focused correctness result: `53 passed, 1 skipped` across the new variance,
guardrail, runtime, tactical, builder, and evaluator diagnostics tests.

The separate legacy `GrimFloorController` command remains `11 passed, 2 failed`.
Both failures are the known old synthetic fixtures that omit `SelectType.MAIN`;
that controller is not used by this runtime and was not modified.

## Decision Disagreement

The real B0/B1/B2/B3 decision-audit pipeline is implemented in
`scripts/audit_grim_variance_floor_decisions.py`. It computes sanitized semantic
actions, disagreement by reason, own-turn ordinal, actual order, and public-only
escape traces.

It was run on local d842 replay shard `data/replays/55397271`, covering 5,401
hero decisions. The audit is replay-sequential and descriptive, not causal.

| Policy | Decisions | Changed vs B0 | Disagreement | <=3% gate | <=2% preferred |
|--------|-----------|---------------|--------------|-----------|----------------|
| B0 | 5,401 | 0 | 0.00% | PASS | PASS |
| B1 | 5,401 | 72 | 1.33% | PASS | PASS |
| B2 | 5,401 | 131 | 2.43% | PASS | FAIL |
| B3 | 5,401 | 140 | 2.59% | PASS | FAIL |

No candidate exceeded the 5% hard stop. B3 public-only traces recorded direct
retreat interventions, attach-to-escape starts, and complete-escape retreats;
no hidden hand/deck information was recorded.

Changed-reason counts for B3 were: setup 19, Shadow-over-Boss 10,
Shadow-over-retreat 12, tactical productive-attack/nullified-attack 31, Punk Up
count 38, Punk Up target 21, attach-to-escape 3, and direct retreat 6. Punk Up
activation was offered 70 times but did not change the selected semantic action.

## First / Second Split

The native mirror screen used forced actual order and balanced physical seats:
100 candidate-first and 100 candidate-second games per candidate.

The replay decision split was first 4,679 / second 660 decisions in this shard.
B1 changed 61 / 11, B2 changed 120 / 11, and B3 changed 129 / 11.

| Policy | Mirror WR | First | Second | Broad WR | Zero attack | Zero prize | Catastrophic floor |
|--------|-----------|-------|--------|----------|-------------|------------|--------------------|
| B0 exact d842 | incumbent control | control | control | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| B1 existing narrow guardrail | 48.0% [41.2, 54.9] | 52.0% | 44.0% | NOT RUN | 0.5% | 3.0% | 17.5% |
| B2 + Punk Up | 54.5% [47.6, 61.3] | 51.0% | 58.0% | NOT RUN | 1.0% | 3.5% | 10.5% |
| B3 + escape | 56.5% [49.6, 63.2] | 58.0% | 55.0% | NOT RUN | 0.5% | 3.5% | 13.5% |

These are unpaired native engine arms. They are a gross regression screen, not
proof of strength. B1/B2/B3 each had zero hero policy errors, zero opponent
policy errors, and zero illegal actions.

## Punk Up Mechanism

The distinct candidate trees are materialized by
`scripts/build_grim_variance_candidates.py`:

- B1: Punk Up off, escape off.
- B2: Punk Up on, escape off.
- B3: Punk Up on, escape on.

All candidate trees verified the frozen model and raw-deck hashes. B2's mirror
screen recorded 405 activation, 223 count, and 1,069 target interventions
across the two hundred games. B3 recorded 402 activation, 215 count, and 1,035
target interventions. These counts are descriptive and include no hidden data.

## Dead Active Escape Mechanism

B3 recorded 29 direct-retreat interventions, 24 attach-to-escape starts, and 24
completed escape-retreat transitions in the 200-game mirror screen. The replay
audit recorded 16 direct-retreat, 8 attach-to-escape, and 2 complete-retreat
interventions, with 6, 3, and 0 semantic action changes respectively. No B3
escape-promotion intervention was observed in the aggregate telemetry, so
promotion completion and subsequent attack conversion are not claimed as
established gameplay effects.

The local direct fixture and replay traces both cover the intended public
semantic sequence.

## Development Population

The exact d842 mirror is the completed 200-game development screen. B1/B2/B3
were each evaluated against exact frozen B0 with 100 games in each actual order.

An authentic Alakazam 2.4a pilot ran locally for B3: 5 games, 2 wins, 40.0%
with Wilson interval [11.8%, 76.9%], 66.7% actual-first and 0.0% actual-second,
zero policy errors, and zero illegal actions. This is far too small for a
promotion claim. The requested 50-game Alakazam batch exceeded the local
10-minute job limit before producing result files.

## Final Holdout

Not run. Alakazam 2.7 and a non-Grim/non-Alakazam holdout were not promoted to
final confirmation because the broad development screen was not available.

An Azure fallback was attempted only after the local authentic runner proved too
slow. The private repository could not be cloned from the VM, and the bounded
in-place transfer attempt produced no result artifacts. The VM was deallocated
afterward. No Kaggle API, upload, or submission archive was used.

## 5-Game Burn-In Proxy

Using the 200 local mirror games per candidate, 20,000 resampled mixed-order
sequences produced:

| Policy | P(wins <=1) | P(wins <=2) | P(at least one zero attack) | P(at least one catastrophic floor) |
|--------|-------------|-------------|------------------------------|-------------------------------------|
| B1 | 21.6% | 53.8% | 2.5% | 61.9% |
| B2 | 13.6% | 41.4% | 5.0% | 42.5% |
| B3 | 11.5% | 38.3% | 2.7% | 51.9% |

This is labeled `LOCAL BURN-IN RISK PROXY - NOT A KAGGLE SCORE FORECAST`.
The sample is only the direct mirror screen and is not a live rating model.

## 10-Game Burn-In Proxy

Mixed-order results:

| Policy | P(wins <=3) | P(wins <=4) | P(at least one zero attack) | P(at least one catastrophic floor) |
|--------|-------------|-------------|------------------------------|-------------------------------------|
| B1 | 20.9% | 42.6% | 4.8% | 85.8% |
| B2 | 10.9% | 26.9% | 9.6% | 66.5% |
| B3 | 8.7% | 23.3% | 5.3% | 76.8% |

The same local-proxy warning applies. These bootstrap values are descriptive,
not evidence of expected Kaggle rating movement.

## Statistical Limitations

- Native game arms are unpaired because the engine uses independent randomness.
- The 200-game mirror screen is a kill screen, not a statistically conclusive strength comparison.
- The decision audit covers one 5,401-decision d842 shard, not the full replay corpus.
- Broad authentic evaluation was blocked by local Alakazam runtime and unavailable reliable Azure transfer.
- The 5-game authentic pilot is not a promotion sample.
- Intervention-state outcomes are not causal because difficult states trigger interventions.
- B4 Poffin remains disabled because the required 10-independent-catastrophic-game evidence gate was not met or auditable.

## Recommendation

`INCONCLUSIVE_DO_NOT_PACKAGE`

B2 and B3 survived the gross direct-mirror kill threshold and had zero runtime
errors. B2 had the lowest measured catastrophic-floor rate in this screen;
B3 had the highest mirror point estimate. Neither has the required replay
disagreement audit or broad holdout evidence, so neither is justified for a
live Kaggle submission.

SHOULD I SPEND A LIVE KAGGLE SUBMISSION ON THIS?

NO. The measured mirror screen is encouraging but incomplete: the <=3%
decision-disagreement gate and broad general-strength/holdout gates were not
established.
