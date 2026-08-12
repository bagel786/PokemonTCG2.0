STARTING SHA: f4451863ea61e007a184695b01f7b4224dff85a6
FROZEN MODEL SHA: D842F85ABFC44AF9F41979F91795E22C92C179B62E04D5A0A2F9C734E70AF1C3
FROZEN DECK SHA: 92B92BAC9F9163ECFF933B3DC39294D2CC154C8684F3C8497877661419EBC59D
FINAL EXPERIMENT SHA: 6fd0d9e

# Grim 5k Variance Floor

This is a code-and-mechanics result, not a gameplay promotion result. The
required local replay and evaluation artifacts were not present in this
checkout, so no game-level win-rate claim is made.

| Policy | Mirror WR | First | Second | Broad WR | Zero attack | Zero prize | Catastrophic floor |
|--------|-----------|-------|--------|----------|-------------|------------|--------------------|
| B0 exact d842 | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| B1 existing narrow guardrail | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| B2 + Punk Up | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| B3 + escape | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| B4 + early Poffin | NOT ATTEMPTED | NOT ATTEMPTED | NOT ATTEMPTED | NOT ATTEMPTED | NOT ATTEMPTED | NOT ATTEMPTED | NOT ATTEMPTED |

## Intervention Rates

Not measured. `scripts/evaluate_grim_variance_floor.py` was run against the
specified local history path and found zero replay rows. The machine-readable
placeholder is `artifacts/grim_variance_floor/intervention_audit.json`.

## First/Second Mechanism Differences

Not measured because the local development replay bank is absent. The evaluator
retains actual order and physical seat fields and will split them when replay
rows are supplied.

## Punk Up Results

Implemented behind `GrimVarianceConfig.punk_up_floor`.

- Exact useful caps: Impidimp 1, Morgrem 2, Grimmsnarl ex 2.
- Activation requires a legal YES, positive useful capacity, and deck cards remaining.
- Count is capped by legal bounds, useful capacity, and 5.
- Number-valued count options are resolved semantically by `option.number`.
- Targets prefer active Grimmsnarl, benched Grimmsnarl, Morgrem, then zero-energy Impidimp.
- Excess Energy is not forced above attack-readiness capacity.

Focused fixtures cover all cap values, zero-cap fallthrough, count semantics,
target ordering, and ordinary-prompt fallthrough.

## Dead Active Escape Results

Implemented behind `GrimVarianceConfig.dead_active_escape`.

- Only Munkidori, Snorunt, and the exact deck's Froslass variants qualify.
- Direct RETREAT requires a ready benched Marnie's Grimmsnarl ex.
- Attach-to-escape requires a legal Darkness attachment that proves retreat.
- The only persistent sequence is semantic attach -> retreat -> ready-Grim promotion.
- State stores turn, player, Active serial, and stage only; no option index persists.
- Missing prerequisites, reordered options, malformed prompts, turn changes, resets,
  and alternate committed actions clear the sequence.

## Optional Poffin Decision

`B4` was skipped. The required threshold audit cannot be performed without the
local development corpus, and the guard explicitly says not to try Poffin
without the measured losing-game precondition.

## Local 5-Game Burn-In Proxy

Not run. The evaluator labels this output `LOCAL BURN-IN RISK PROXY - NOT A
KAGGLE SCORE FORECAST`; no rating or TrueSkill estimate is produced.

## Local 10-Game Burn-In Proxy

Not run for the same reason. See `artifacts/grim_variance_floor/burnin_proxy.json`.

## Diversity / Holdout

Not run. No local recovery opponent artifact set was available. No new opponent
was built and no network or Kaggle API was used.

## Known Statistical Limitations

- There are zero local replay rows for this checkout, so mechanism and gameplay estimates are unavailable.
- No causal claim can be made from the existing historical correlations alone.
- Ordinary native game arms must be treated as unpaired unless the runner proves common randomness.
- The legacy floor-controller test suite retains two fixture failures caused by missing `SelectType.MAIN`; this experiment does not use that controller.
- The full repository suite also has unrelated missing ignored artifacts and one pre-existing schema-padding precision failure.

## Recommendation

`INCONCLUSIVE_DO_NOT_PACKAGE`

The B3 implementation passes its focused mechanics/runtime tests and preserves
the frozen model, deck, temperature 0, search-disabled proof, tactical shield,
sanitizer, and existing narrow guardrail. It must not be packaged or evaluated
as a gameplay finalist until the missing local replay/evaluation artifacts are
restored and B1/B2/B3 intervention and gameplay gates are completed.
