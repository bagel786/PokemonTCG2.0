# Rolling Multi-Day Elite Distillation

## Summary

Build a seven-day, recency-weighted elite dataset and use counterfactual search to retain only demonstrably better decisions. Target a Kaggle rating above 1000. This is feasible and differs from Candidate B by filtering labels for causal advantage rather than merely adding winner-only demonstrations.

## Implementation Changes

- Stream the newest seven complete Kaggle episode days, deleting raw files after inspection. Weight dates with `2^(-age_days/3)`, normalize each episode-seat’s total contribution, deduplicate by episode/seat/step, and report opponent archetype, team, seat, outcome, Lucario, and Iono coverage.
- During calibration, train on the older six days and reserve the newest day as a temporal holdout. After hyperparameters are frozen, refresh the rolling window and refit using all seven days while retaining stable whole-team holdouts.
- For winning exact-Grim seats where d842 disagrees with the elite action, preserve a compact search record containing the public observation, both actions, both decklists, features, date, team, matchup, seat, and outcome.
- Search-filter only reliable matchups:
  - Grim mirror using d842 continuations on both sides.
  - Exact known Alakazam variants using their authentic fast policies.
  - Evaluate elite and d842 actions on the same eight determinizations. Retain a label only when mean paired advantage is at least `+0.5`, at least four worlds are informative, and no search/policy error occurs.
  - Require at least 10,000 retained decisions with both seats represented; do not weaken the margin if this minimum is missed.
- Do not search-label Lucario, Iono, or Raging Bolt. Mix authenticated Lucario/Iono winning demonstrations as outcome-weighted defense data. Exclude Raging Bolt from training until a qualified continuation pilot exists.
- Train three d842 refresh candidates with fixed source weights: 55% filtered labels, 20% recency-weighted broad elite wins, 15% exact-d842 ladder rehearsal, and 10% authenticated Lucario/Iono wins. Use the existing `0.5` distillation anchor:
  - Heads only at learning rate `3e-5`.
  - Heads only at `1e-4`.
  - Representation at `1e-5` plus heads at `1e-4`.
  - Run up to three epochs with temporal-loss early stopping and frozen-module verification.
- Keep the existing 1.45-million-parameter architecture unchanged. Record train/validation curves by date, seat, and matchup to distinguish capacity limits from label or distribution problems.

## Interfaces and Artifacts

- Extend the daily miner with rolling-window, recency-weight, exact-deck, coverage-report, and compact-disagreement-output options.
- Add a resumable counterfactual scorer that accepts disagreement JSONL, registered continuation policies, determinization count, and advantage threshold; output model-ready filtered JSONL plus an audit manifest.
- Manifests must record dataset hashes, date weights, exclusions, split membership, deck hashes, search telemetry, coverage counts, and zero-leakage checks.

## Test and Promotion Plan

- Test replay alignment, cross-day deduplication, exponential weights, episode-normalized weighting, stable team/date splits, archetype detection, and resumable streaming.
- Test paired common-random-number search, forced inclusion of both compared actions, deterministic scoring, threshold behavior, and safe exclusion of determinization failures.
- Run an end-to-end bounded daily smoke before the seven-day acquisition and verify identical manifests/checkpoints on resume.
- Shortlist using held-out filtered-label loss and action agreement, then run 500- and 2,000-game mirror screens.
- Finalists receive a 50,000-game seat-balanced mirror gate against d842. Both seat lifts must be non-negative versus the matched structural control, aggregate mirror strength must improve, and policy/engine errors must remain zero.
- Run authenticated Alakazam, Lucario, Bellibolt, and available meta regression gates. Promote only if field-frequency-weighted expected strength improves; allow small easy-matchup regressions but no regression larger than three percentage points.
- If no candidate passes, ship nothing. If candidates pass, package and validate the best two trained models, then request approval before replacing either live Kaggle slot.

## Assumptions

- “100+” means a rating above 1000.
- The rolling window is the newest seven complete days available when acquisition begins, initially July 28–August 3.
- Available Azure credits remain capped at the documented `$167`; acquisition and search stop safely before that cap.
- Plain multi-day BC is not repeated as a separate candidate because Candidate B already showed improved imitation without gameplay improvement.
- No architecture expansion, inference-time search, automatic Kaggle upload, or unqualified Raging Bolt search is included.
