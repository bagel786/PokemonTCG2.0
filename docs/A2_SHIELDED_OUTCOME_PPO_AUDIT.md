# A2 Shielded Terminal-Outcome PPO Audit

## Verdict

The four completed shielded shard 0/1 corpora and the corrected trainer are valid for bounded gameplay screening. The two trained order-specific policies are **not validated improvements over A2**. Both the full update and its 50% interpolation failed their aggregate A2 screen, and a fresh 2,000-pair actual-second confirmation reduced the remaining full-model signal to +0.15 percentage points with a 95% interval spanning -1.29 to +1.59 points.

The initial training attempt exposed one real implementation defect before any optimizer update: `load_rows` converted the token stream to a NumPy array, while `train_bc.collate` used scalar list truthiness. That run crashed during likelihood parity and emitted no model. `training/order_ppo.py` now keeps tokens as an ordinary list, with regression coverage in `tests/test_order_ppo.py`; the focused suite passes 7/7.

## Audited source data

Only these completed shielded files were accepted. Partial shard 2/3 files and all unshielded files were excluded.

| Actual order | Shard | Games | Decisions | Shield-excluded | SHA-256 |
|---|---:|---:|---:|---:|---|
| first | 0 | 1,000 | 93,603 | 291 | `EE59E61A8976783D0052CC690322BFBC2C3B9709F00DCA261F90DC7C6159E90E` |
| first | 1 | 1,000 | 93,613 | 389 | `DE5A836BCE55524BFE1FBD195ED2C193AED2E9A8CDE599F420DA6FC8AAEF3D68` |
| second | 0 | 1,000 | 93,038 | 373 | `9C7D75601CBF482B729E3C7A86454286DD7B810D722F1012B35C9A72753AD4D1` |
| second | 1 | 1,000 | 93,168 | 456 | `4AE2432F39CC1BA6DD3A322FAD7854C5428826AF05AC865BF0220593E675E4F9` |

Combined corpus facts:

- 4,000 unique episodes and 373,422 recorded decisions; 371,913 decisions are trainable.
- Exactly 1,509 decisions (0.404%) are excluded, all because the deployed tactical shield changed the sampled action. There are zero sanitizer-postprocessed decisions and no modified decision enters PPO.
- Both orders contain exactly 1,000 games from each physical seat. The six-opponent mixture is close to its requested weights; A2 accounts for 44.85% of first-order games and 45.40% of second-order games.
- First- and second-order episode IDs have zero overlap. Every opponent covers all five cross-fit folds; the smallest opponent/fold cell contains 22 games.
- Terminal rewards are constant within every episode and agree with the collection manifests: first-order has 878 wins, 1,117 losses, and 5 draws; second-order has 757 wins and 1,243 losses.
- Every behavior log probability is finite. An independent 8,192-row check spanning selected-action counts 0 through 5 produced mean importance ratio 1.000000 and maximum absolute log-probability disagreement `3.81e-6`.

The behavior model is authentic A2 schema 2, SHA-256 `B19871A9F1499C2460AE266E58194ACAB1D8C90B390FA5CF24ED94B9A2B6BDA8`. Collection sampled it at temperature 0.70 and executed the same tactical shield expected at deployment.

## Trainer audit

Training used one actor-only PPO epoch, terminal rewards only, clip ratio 0.10, learning rate `3e-5`, and a five-fold public-state baseline shrunk toward the opponent mean with strength 40. No critic, GAE, Q boost, or imitation target enters the objective.

The cross-fit excludes the complete held-out episode from its baseline statistics. The state baseline reduces row-level prediction MSE from 0.998 to 0.936 for first-order data and from 0.990 to 0.905 for second-order data. Turn balancing gives each `(episode, engine turn)` equal total weight, preventing long nested selection prompts from dominating; it covers 19,408 first-order and 18,871 second-order hero turns.

| Model | Trainable decisions | Parity max `|delta log p|` | Reported KL | Independent final KL | Raw greedy change rate | SHA-256 |
|---|---:|---:|---:|---:|---:|---|
| full first | 186,536 | `4.29e-6` | 0.000322 | 0.000301 | 0.586% | `9575B759CABF5FD3AB53C376539DC90270C73A00038E54183FD30DD1975A27F5` |
| full second | 185,377 | `4.77e-6` | 0.000316 | 0.000388 | 0.708% | `474B7D055BCD8BE8490392AEAC16489549D52A3CFD9AE1D36E3B6179C735ED6E` |
| half first | n/a | n/a | n/a | n/a | n/a | `95825736583E5F266C7BDB68C6F039C09E185F7142710E0EDF440D2E23CAEA46` |
| half second | n/a | n/a | n/a | n/a | n/a | `ECE524B33E592980A4B8B4C8DF07527FB72230682848D14E76840261FB0C1551` |

The half models are exact 50/50 parameter interpolations between A2 and the corresponding full PPO model.

Remaining limitations do not invalidate the experiment, but they constrain interpretation:

- Terminal-only credit has high variance and assigns the same outcome across many correlated decisions.
- The objective improves a temperature-0.70 stochastic policy; it need not improve the deterministic argmax used in competition. The observed greedy change rate is under 0.71% per reached decision.
- Shield-modified decisions are omitted, so the learned actors are only meaningful behind the identical tactical shield.
- Engine randomness during collection was not explicitly seeded. Corpus win rates are therefore training diagnostics, not reproducible benchmark estimates.
- Shard 0 and shard 1 reused the actor RNG seed, and the state baseline does not condition explicitly on physical seat. These increase variance but do not introduce outcome or test leakage.
- Training manifests omit batch size and rollout hashes, a provenance gap; the source hashes above should be carried into any downstream record.

## Gameplay screens

Both candidates were tested against A2 with deterministic common-random-number pairing, 100 pairs per actual order (400 engine games per candidate), base seed `202608139001`, and zero candidate, control, or opponent policy errors. The deterministic gameplay engine SHA-256 was `11662D6D96FEBB8ACA8F500BDFDE520AE0F1686AB3959EEF90AA16C958E68188`; the production engine was preserved.

| Candidate | First order | Second order | Overall | Paired 95% CI | Decision |
|---|---:|---:|---:|---:|---|
| full PPO | -5 wins / 100 (-5.0 pp) | +3 wins / 100 (+3.0 pp) | -2 wins / 200 (-1.0 pp) | [-5.61, +3.61] pp | Failed aggregate; inconclusive |
| half interpolation | -2 wins / 100 (-2.0 pp) | +1 win / 100 (+1.0 pp) | -1 win / 200 (-0.5 pp) | [-3.45, +2.45] pp | Failed aggregate; inconclusive |

Full package provenance:

- Archive SHA-256: `38D0CAC006C16ED7DA08853FAB8C0CC42BA4B8176B13F3C2049B6769BFD5AE74`
- Extracted tree SHA-256: `FF37A2DCE23C72488B5ED23AC4078F4714091A2DA6B79590B833A5F21756DECB`

Half package provenance:

- Archive SHA-256: `21F2779AF6835D17DF4A381F258275A23C1D6C1CBC008D7F83425BE2E40EE97F`
- Extracted tree SHA-256: `6B013C7D2A77654E288AE8CC79F1B336D7BF41E87357ACCCA3AFA01B510EE654`

The paired screen did not support either full or half PPO as stronger than A2. Because the initial split direction was consistently negative first-order and positive second-order, two routers were packaged to preserve byte-exact A2 when moving first and use the learned model only when moving second. On a fresh 200-pair-per-order schedule, the half router was exactly tied overall (205 wins each); the full router was +1.0 point overall (209 versus 205), driven by +2.0 points moving second. Both had intervals spanning zero and zero policy errors.

The full router then received a selection-independent, actual-second-only confirmation of 2,000 pairs (4,000 engine games), base seed `202608150701`:

| Candidate | Candidate wins | A2 wins | Paired delta | Paired 95% CI | Errors | Decision |
|---|---:|---:|---:|---:|---:|---|
| A2-first / full-PPO-second | 997/2,000 | 994/2,000 | +0.15 pp | [-1.294, +1.594] pp | 0 | Reject; no meaningful replicated lift |

The decisive result contains 110 candidate-only wins and 107 control-only wins; 1,783 pairs were concordant. The production DLL was hash-identical before and after evaluation. Result SHA-256: `364F4A10E39E668DC18161EA35EBC04E6FECCCFE66821602104A3905C7CA850D`. The tested router archive is retained only as a failed experiment:

- Archive: `artifacts/elite_policy_candidates/a2_outcome_second_full/package/a2_outcome_second_full.tar.gz`
- Archive SHA-256: `B15B3E1F2C8903CCA2E71095BE931301C603065B69CE199C001A3179E4388BB6`
- Extracted tree SHA-256: `BEB1B2F57FA667379308F756C9C60084D589E3BBDDEC0A0CAD01CF0D24DD823B`

## Bounded recipes if outcome PPO is revisited

- Conservative: state baseline, shrinkage 40, batch size 1,024, learning rate `3e-5`, clip 0.10, target KL 0.001, hard KL 0.003, one epoch.
- Aggressive: state baseline, shrinkage 10, batch size 1,024, learning rate `6e-5`, clip 0.10, target KL 0.0015, hard KL 0.003, one epoch. Require an independent final-policy KL below 0.003 before gameplay.

Do not train the aggressive recipe merely to create a larger change. The fresh order-isolation test did not replicate a meaningful second-order lift, so this terminal-outcome PPO path is closed rather than expanded. Its central limitation is credit assignment, not update magnitude.
