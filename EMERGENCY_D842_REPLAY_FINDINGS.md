# Emergency d842 replay findings and submission record

## Outcome

Kaggle submission **55399728** was uploaded at 2026-08-10 07:09 UTC and is `COMPLETE`.  The active pair is the new A2 ordered candidate plus exact-d842 submission 55397271.  Kaggle completed full-game validation episode 91574390, then the candidate won its first public ladder game (episode 91574491) and moved from 600.0 to 713.45.  The uploaded archive is `artifacts/emergency_d842/grim_a2_ordered.tar.gz`.

Recommendation: **likely stronger than d842**.  The strongest evidence is the independent 30,000-game comparison (53.657% A2 versus 49.777% structural d842, +3.88 points) and the new forced-order screen (54.6% actually first, 52.6% actually second).  The remaining concern is the strong master-v1 matchup, especially when actually second.

## Full replay corpus

The refreshed corpus contains 1,045 complete rated games across the four policy lineages used here.  The two live d842 controls were refreshed immediately before analysis (47/47 files, 16 newly downloaded).

| Lineage | Games | WR | First WR | Second WR | Exact mirrors | 850+ WR | Relative +75 WR |
|---|---:|---:|---:|---:|---:|---:|---:|
| Exact d842 | 821 | 57.73% | 62.75% | 50.15% | 158 (50.63%) | 43.85% | 57.69% |
| PPO 5k | 116 | 61.21% | 70.15% | 48.98% | 23 (65.22%) | 39.53% | 28.57% |
| Modified PLAY | 57 | 57.89% | 65.00% | 41.18% | 17 (29.41%) | 45.00% | 100.00% (2 games) |
| Search-disabled | 51 | 52.94% | 58.97% | 33.33% | 7 (0%) | 0% (4 games) | 25.00% |

The dominant d842 weaknesses are clear: an actual-second gap of 12.60 points and only 43.85% against opponents initially rated 850+.  The alternate lineages do not supply a generally superior actual-second teacher; all three are worse than exact d842 in that stratum.

In the 78 exact-mirror losses, frozen d842 semantically reproduced the winning opponent's recorded actions at every comparable post-setup observation.  No repeated first meaningful divergence survived semantic comparison.  That is evidence that this mirror subset is mostly same-policy variance, not evidence for inventing counterfactual opponent behavior.

## Largest recurring d842-to-A2 differences

The existing sterile disagreement bank covers 12,070 d842 decisions from 131 episodes.  A2 differs semantically on 848 decisions (7.03%); on the new 41,837-decision actual-second corpus its model top choice differs on 2,750 decisions (6.57%).  Ratings were unavailable in the older disagreement bank, so rating fields are not fabricated.

| d842 choice → A2 choice | Decisions | Episodes | First/second | Interpretation |
|---|---:|---:|---:|---|
| empty → Munkidori | 43 | 43 | 24/19 | More setup width; likely causal early development |
| Impidimp → Grimmsnarl ex | 32 | 23 | 21/11 | Faster conversion to the main attacker |
| Morgrem → Grimmsnarl ex | 23 | 18 | 14/9 | Earlier attacker completion |
| attack 937 → retreat | 22 | 13 | 18/4 | Avoids a low-value attack or preserves continuity; contextual |
| Spikemuth ability → attack 937 | 20 | 18 | 13/7 | Converts development into immediate tempo |
| empty → Impidimp | 16 | 16 | 8/8 | Adds another viable evolution target |
| Grimmsnarl ex → Munkidori | 14 | 11 | 9/5 | Diversifies support instead of overcommitting attackers |
| five Darkness Energy → two | 12 | 12 | 8/4 | Different Punk Up distribution/count; ambiguous without continuation |
| Munkidori → Froslass | 12 | 12 | 5/7 | Changes support engine and damage route |
| Impidimp → Munkidori | 11 | 10 | 3/8 | Going-second-skewed support choice |

These are first-order recorded-state disagreements only.  Later-state causal claims were deliberately avoided.

## Iterations

| Candidate | Change rate | Games | Overall / first / second | Mirror | Important result and next action |
|---|---:|---:|---|---|---|
| Replay residual 1e-5 | 2.03% | 500 | 50.2% second | 50.2% vs d842 | Neutral; retained for comparison, then replaced |
| Replay residual 3e-5 | 2.99% | 500 | 47.2% second | 47.2% vs d842 | Larger update hurt; reduce/update direction |
| Replay residual 1e-4 | 4.07% | 500 | 45.8% second | 45.8% vs d842 | Clearly too aggressive; discarded |
| Master-v1 | not measured here | 1,000 | 49.7% / 53.2% / 46.2% | direct d842 | Strong first, weak second; discarded |
| A2 shield | 6.6–7.0% | 1,000 new + 30,000 prior | 53.6% / 54.6% / 52.6% new; 53.657% prior | direct d842 | Strongest consistent candidate; selected |
| A2 + replay second | 2.03% from d842 second plus shield | 500 | 46.2% second | direct d842 | Interaction was harmful; discarded immediately |

Final-population checks for the selected archive: 64.0% actually first and 58.0% actually second versus v2.2 (500 games total); 48.4% first and 43.6% second versus master-v1 (500 total).  All runs had zero policy errors.  Prior authentic checks showed A2 improving over d842 by 0.85 points versus Alakazam 2.4a and 2.85 points versus Alakazam 2.7.

## Final candidate

The candidate is the schema-2 A2 option policy plus three deterministic tactical interventions: ensure a legal Basic during optional setup, reject nullified attacks when an alternative exists, and attack instead of ending a turn when a productive attack is legal.  An actual-order router latches `current.firstPlayer`; both order arms use the selected A2 model, with exact d842 as a fail-closed fallback.

Reproduction commands:

```powershell
python -m training.train_v2_model
python scripts/build_recovery_probes.py
python scripts/package_order_ppo_candidate.py --base artifacts/recovery_probes/a2_v2_shield.tar.gz --policy-first artifacts/recovery_probes/extracted/a2/policy_weights.npz --policy-second artifacts/recovery_probes/extracted/a2/policy_weights.npz --output artifacts/emergency_d842/grim_a2_ordered.tar.gz --manifest artifacts/emergency_d842/package_a2_ordered.json
```

Hashes:

- Archive: `F294AA1183C132BEED5BEAF542BD8A05BE5729AA11C9D114C9EEFF78B730847E`
- Both policy arms: `B19871A9F1499C2460AE266E58194ACAB1D8C90B390FA5CF24ED94B9A2B6BDA8`
- `main.py`: `61643FBEEB3E83578E992FB137EA110C3D9A30709C525FC3E8591EDC6D4BFFDF`
- order router: `E62B8F9C0555BD4CBD2BE1D7950A42FC21375FA424508FB0B838320BF65D2B83`

Final sterile validation: 50 complete games, 9,880 decisions, zero policy errors, deterministic replay, 1.81 ms p99 and 18.31 ms maximum latency.
