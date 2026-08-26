| scenario | name | construction | paired_gt | replay_gt | crn_gt |
| --- | --- | --- | --- | --- | --- |
| S0 | clean control | no injection; substream-separated stateful RNG both arms | VALID | VALID | VALID |
| S1 | seed namespace conversion (16-bit truncation) | arm B effective seed = declared & 0xFFFF (16-bit truncation); seeds drawn from [2^20,2^40) so truncation always bites; arm B only | DOWNGRADE | VALID | INVALID |
| S2 | stateful draw shift (one extra burn draw in arm B) | arm B consumes one extra dealer-stream draw before EVERY hand (recurring shift; robust to RandomState refill realignment) | DOWNGRADE | VALID | INVALID |
| S3 | event-keyed repair | both arms use SHA-256 counter-based event-keyed draws keyed by (stream, event_id); deck order and actions are pure functions of keys | VALID | VALID | VALID |
| S4 | clock-bounded computation (wall-clock think budget) | random-policy agent spends a wall-clock think budget per step; budget scales with process rank (0.30ms * (1 + 0.75*(rank%3))) so trajectories vary across execution contexts; think draws on isolated agent stream | VALID | INVALID | VALID |
| S5 | process-global mutable state (worker reuse) | module-level cache contamination: reused-worker context burns one dealer draw before hand 0 AND forces first action of hand 0 to last legal id | DOWNGRADE | INVALID | INVALID |
| S6 | queue/enqueue order dependence | queue-order skew: deterministic per-arm draw tax every hand (arm A: rank%3; arm B: (7*rank+1)%3), emulating enqueue-order-dependent worker behavior | DOWNGRADE | INVALID | INVALID |
| S7 | missing/dropped schedule rows before analysis | harness drops every 3rd schedule row after acquisition, before analysis (row index % 3 == 2) | DOWNGRADE | VALID | VALID |
| S8 | benign residual randomness, valid repeated-measures design | S4-style clock jitter PLUS repeats_per_seed=3 AND repeated-measures/hierarchical analysis declaration | VALID | INVALID | VALID |
| S9 | pseudoreplication (decisions treated as independent replicates) | analysis declares decision-level unit (pseudoreplication) instead of seed-condition cluster | INVALID | VALID | VALID |
| S10 | valid unpaired design (independent seeds, declared) | arms use independent seeds (B = A + 1,000,003), independence declared in schedule | INVALID | VALID | INVALID |
