# Grim Arm B — Final Rejection

Arm B is permanently rejected. Retain the qualified A2 + Damage V0 control and
do not reopen, retune, combine, rescreen, package, or upload B based on its
earlier positive 300-pair d842 screen.

## Final pre-registered confirmation

The final experiment used 1,200 actual-second deterministic CRN pairs: 400
pairs against each of exact d842, master_v1, and replay_refresh. The seed
blocks were fresh and mutually disjoint, physical seats alternated, and all
candidate, control, opponent, and available nested fallback/error counters
were zero.

| Opponent | B wins | Control wins | B-only / control-only | Paired delta | 95% CI |
|---|---:|---:|---:|---:|---:|
| exact d842 | 205 | 210 | 22 / 27 | -1.25 pp | [-4.68, +2.18] |
| master_v1 | 186 | 190 | 29 / 33 | -1.00 pp | [-4.86, +2.86] |
| replay_refresh | 206 | 196 | 30 / 20 | +2.50 pp | [-0.96, +5.96] |

The pre-registered primary estimand was the equal-weight mean of the three
opponent-specific paired deltas. It was **+0.083 pp**, with a two-sided 95% CI
of **[-1.989, +2.156] pp**. Assuming a 50/50 first/second-order mix, the implied
overall effect was approximately **+0.042 pp**.

## Gate decision

B failed both required strength gates:

- equal-weight actual-second delta was below +3.0 pp;
- the two-sided 95% CI did not exclude zero.

The remaining gates passed: no opponent cell was worse than -2.0 pp, and all
recorded error counters were zero. Passing safety gates does not override the
failed strength gates.

## Permanent disposition

The final balanced confirmation supersedes the earlier screening signal.
Arm B is archived as negative evidence and must not be reinterpreted as a
promising candidate because the earlier 300-pair d842 screen was positive.
Keep A2 + Damage V0 and stop Grim development.

Full result artifacts:

- `artifacts/grim_b_final_confirmation_vs_d842_second_400pairs.json`
- `artifacts/grim_b_final_confirmation_vs_master_v1_second_400pairs.json`
- `artifacts/grim_b_final_confirmation_vs_replay_refresh_second_400pairs.json`
