# Study Summary

## Scientific question

What evidence is required for each type of seed-matched claim, and what does a
full validation framework add over simpler strategies?

## Five independent claim branches

- A: recorded schedule matching.
- B: statistically justified paired inference.
- C: scoped deterministic replay.
- D: CRN coupling and variance reduction.
- E: semantic event-value alignment.

Branch B can be justified by design/model evidence without exact replay or event
alignment. The branches are not a ladder.

## Prospective design

The protocol was committed and pushed at `62ad878` before final outcomes. It
froze two open MIT-licensed systems, S0-S10, B0-B7, 40 final seeds, metrics, and
reporting gates. This was not a public registry submission.

## What ground truth means

Each scenario injects a known wrapper/design condition. A method is scored
against branch-specific construction labels. Detection asks how often hard-
invalid claims are rejected. False suppression asks how often valid claims are
unnecessarily downgraded or rejected.

## Main retained results

- Raw integrity: PASS; 35,014 rows, including 34,160 decisions and 854 pairs.
- Branch B: B7 and B5 each detected 160/160 hard-invalid cells.
- Branch B valid cells: B7 falsely suppressed 120/320 (37.5%); B5 0/320.
- B7 overall: 89.4% hard-invalid detection and 14.6% pooled false suppression.
- B7 Branch C: 156/320 detected (48.75%).
- Cross-system ordering tau-b: 0.81, but magnitudes differed sharply.
- Trace-logging overhead: about 33% hold'em and 92% Ising in a 50-run
  analysis-stage microbenchmark.

## Critical failures

- The runner did not retain A/A null banks, construction-fixed effects, or S8
  repeats promised for confirmatory coverage, Type-I error, and power.
- Ising S4/S8 do not inject the intended clock residual mechanics.
- Hold'em S3 ignores the policy distinction in event-keyed actions and collapses
  the arm contrast.
- Per-method runtime and full per-method storage were not retained.
- No independent human review or author-comprehension sign-off exists.

## Historical case

The restricted Pokémon engine provides motivation only: 99/200 timed-search
trace-projection disagreements and retrospective 210/2800 and 458/2800 record
disagreements. It is never pooled with the prospective data.
