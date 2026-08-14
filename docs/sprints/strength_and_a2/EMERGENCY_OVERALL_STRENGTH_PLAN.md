# Emergency overall-strength result

## Decision

The strongest established policy remains **A2**. No hybrid produced a repeatable lift over A2. The best broad hybrid, `grimmsnarl_emergency_phase_router`, is packaged and valid, but is classified **neutral overall / likely slightly weaker than A2 in the authentic Grim+Alakazam slice**. It should **not replace the active A2 slot on current evidence**. It is suitable for inspection as a different A2-derived hedge.

No Kaggle upload or active-slot eviction was performed, per the task's hard constraint.

## Live refresh and population weights

The refresh found 44 rated d842 games and 40 rated A2 games. Their public-score gap remains non-significant and consistent with the empirical same-agent reship variance; offline A2 evidence remains the better policy signal.

Across the 84 unique rated games, the observed field was:

| Archetype | Overall | <700 (n=23) | 700-850 (n=53) | 850+ (n=8) |
|---|---:|---:|---:|---:|
| Alakazam | 25.0% | 13.0% | 26.4% | 50.0% |
| Grimmsnarl mirror | 20.2% | 8.7% | 22.6% | 37.5% |
| Mega Lucario | 13.1% | 17.4% | 13.2% | 0% |
| Archaludon | 9.5% | — | 13.2% | 0% |
| Mega Kangaskhan | 7.1% | — | — | 12.5% |
| Garchomp | 3.6% | — | — | 0% |
| Crustle | 3.6% | — | — | 0% |
| Long tail | 17.9% | mixed | mixed | 0% |

Only 3/84 games had an opponent at least 75 rating points above the submission, so no reliable relative-strength bucket can be estimated from the live sample.

The authoritative runnable slice used absolute live weights of 25.0% Alakazam and 20.2% Grim. Within Grim, the 20.2% was split across d842/A2/master-v1/v2.2/replay-refresh as 5.05/5.05/4.04/3.03/3.03 points. Alakazam 2.4a and 2.7 received 12.5 points each. Scores over this slice renormalize its 45.2% total weight. Alakazam was run in direct-policy mode (`NO_SEARCH=1`) for throughput; it is a usable policy opponent, not a claim about full-search counterfactuals.

Low-confidence diagnostics used Lucario 13.1%, Crustle 3.6%, and Bellibolt/Ogerpon/Starmie-Froslass at 2.0% each. These local implementations cover another 22.7% of the observed field only as stress tests. Archaludon, Kangaskhan, Garchomp, and the remaining long tail were not fabricated from weak agents.

## Live loss buckets

| Submission | Losses by largest buckets | First/second losses | Close | Blowout | Interpretation |
|---|---|---:|---:|---:|---|
| d842 | mirror 4, Lucario 3, Alakazam 3, Kangaskhan 2 | 5 / 8 | 8/13 | 3/13 | Broader structural holes; two shutouts |
| A2 | Alakazam 6, mirror 2, Lucario 2, Archaludon 2, Crustle 2 | 7 / 10 | 10/17 | 0/17 | Losses cluster, but are materially less one-sided |

A2's largest actionable bucket is Alakazam, followed by second-order continuity across several archetypes. The sample does not support treating the current d842 public score as superior strength.

## Runtime and candidates

The isolated runtime evaluates d842 and A2 logits from one encoded observation, blends option and count logits, then applies the tactical shield exactly once. It supports global alpha, actual-order alpha, phase routing, and an optional small master-v1 component. Actual order is read from `current.firstPlayer`.

All 35,656 evaluation games completed with **zero hero policy errors**. Screen results below are independent-engine-RNG estimates, so differences of a few points at 504 games are ranking signals, not proof.

| Screen | Candidate | Games | Weighted | First | Second | Grim | Alakazam | Change vs A2 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| alpha | d842 exact | 504 | 67.97% | 54.37% | 60.32% | 45.56% | 86.81% | — |
| alpha | d842 + shield | 504 | 69.30% | 68.25% | 52.78% | 50.83% | 84.72% | 6.40% |
| alpha | A2 25% | 504 | 70.77% | 61.11% | 63.89% | 53.33% | 85.42% | 5.07% |
| alpha | A2 50% | 504 | 72.57% | 63.10% | 60.71% | 50.28% | 90.97% | 3.23% |
| alpha | A2 75% | 504 | 74.37% | 65.87% | 63.49% | 54.17% | 90.97% | 1.33% |
| alpha | A2 100% | 504 | 73.97% | 69.84% | 60.71% | 55.56% | 89.58% | 0% |
| order | first 1.0 / second .50 | 504 | 66.15% | 59.13% | 55.16% | 47.22% | 81.94% | 1.20% |
| order | first 1.0 / second .75 | 504 | 73.82% | 61.90% | 65.08% | 52.22% | 91.67% | 0.50% |
| order | first .75 / second .50 | 504 | 72.93% | 65.87% | 61.51% | 53.06% | 90.28% | 2.03% |
| order | first .75 / second .75 | 504 | 72.18% | 65.08% | 61.90% | 53.61% | 88.19% | 1.33% |
| order | first .50 / second .50 | 504 | 76.22% | 72.62% | 60.71% | 56.39% | 92.36% | 3.23% |
| phase | A2 turns 1-3, then .75 | 504 | 72.91% | 66.67% | 58.33% | 51.11% | 90.97% | 0.97% |
| phase | A2 development / .75 combat | 504 | 70.87% | 61.51% | 64.29% | 54.44% | 84.03% | 0.27% |
| phase | A2 development / d842 combat | 504 | 74.11% | 63.49% | 65.48% | 54.17% | 90.28% | 0.80% |
| phase | A2 unstable / .75 stable | 504 | 71.54% | 64.29% | 61.90% | 53.61% | 86.81% | 0.80% |
| soup | .60 A2/.30 d842/.10 master | 504 | 74.12% | 66.67% | 63.49% | 55.56% | 88.89% | 1.90% |
| soup | .50 A2/.30 d842/.20 master | 504 | 72.63% | 62.70% | 57.54% | 46.39% | 94.44% | 2.07% |
| near-A2 | A2 85% | 1,008 | 73.72% | 67.06% | 63.29% | 55.97% | 88.19% | 0.73% |
| near-A2 | A2 90% | 1,008 | 70.74% | 66.07% | 58.13% | 52.78% | 85.42% | 0.53% |
| near-A2 | first 1.0 / second .85 | 1,008 | 71.30% | 63.69% | 59.13% | 50.56% | 88.54% | 0.27% |
| near-A2 | first 1.0 / second .90 | 1,008 | 70.89% | 67.86% | 59.72% | 55.83% | 83.68% | 0.20% |

Decision-change rates use 3,000 live replay decisions per screen candidate. Full A2 parity was separately verified over 5,000 decisions: alpha 1.0 differed on 0 and produced no illegal actions or errors.

## Larger payoff results

The 3,010-game-per-candidate main round:

| Candidate | Weighted | First | Second | Grim | Alakazam | Errors |
|---|---:|---:|---:|---:|---:|---:|
| A2 75% | **72.72%** | **67.11%** | 60.27% | 53.77% | 88.49% | 0 |
| A2 development / d842 combat | 72.68% | 65.71% | **61.13%** | 53.21% | **88.95%** | 0 |
| .60 A2/.30 d842/.10 master | 72.39% | 66.05% | 61.06% | **53.86%** | 87.79% | 0 |
| full A2 | 71.83% | 66.31% | 58.94% | 52.88% | 86.98% | 0 |

The independent 3,000-game-per-arm final round reversed the small-screen ordering:

| Candidate | Weighted | First | Second | Grim | Alakazam | Errors |
|---|---:|---:|---:|---:|---:|---:|
| full A2 | **74.16%** | **68.53%** | **62.80%** | **54.40%** | **88.20%** | 0 |
| A2 development / d842 combat | 72.13% | 65.80% | 60.73% | 51.40% | 87.00% | 0 |

Pooling the common six authentic opponents from the main and final rounds gives 5,580 games per arm: A2 73.86% weighted versus phase-router 73.02%. The 1,000-game focused A2 mirror was A2 51.2%, A2-85% 47.6%, and A2-75% 46.9%. This is the clearest reason not to claim a hybrid win.

The low-confidence common-archetype diagnostic was phase-router 80.19%, A2 79.25%, and A2-75% 76.04% over 1,000 games each. Combining all locally modeled weights (67.9% of the observed field) makes A2 and the phase router effectively tied: 74.534% versus 74.543%. The remaining 32.1% lacks an honest runnable population proxy.

## Packaged candidate

`grimmsnarl_emergency_phase_router` uses A2 for setup, main decisions, search/evolution/energy, and all other development contexts. It uses d842 only for unambiguous combat/targeting follow-ups: switch/to-active, attack selection, damage/counter allocation, effect targets, and their count choices. Tactical shield is applied once after policy selection.

On 9,968 live replay decisions it changed 0.73% versus A2 and 6.52% versus d842 (0.95% versus A2 when actually second), with zero exceptions and zero illegal actions.

Validation: 20 complete games, 3,782 decisions, 0 policy errors, p99 latency 1.46 ms, maximum 19.17 ms. The archive was built twice deterministically and passed sterile extraction/import.

| Artifact | SHA-256 |
|---|---|
| submission archive | `624F8CA55F663A27793527A8CDC6E3E887A0BA298B215520A0644E1387A49AAC` |
| deck | `92B92BAC9F9163ECFF933B3DC39294D2CC154C8684F3C8497877661419EBC59D` |
| d842 model | `D842F85ABFC44AF9F41979F91795E22C92C179B62E04D5A0A2F9C734E70AF1C3` |
| A2 model | `B19871A9F1499C2460AE266E58194ACAB1D8C90B390FA5CF24ED94B9A2B6BDA8` |
| `main.py` | `232C755C4B0CB2EB648C9709A206805B9D03A2F5A9528A5C4F8E126E4CF6AFB9` |
| `mix_config.json` | `E94AD0A39EA3FE0916639DEC292F975492CEEB1F2D4524906002804049B19834` |
| `ptcg_ai/logit_mix.py` | `EA5F4B3C176B41FBE4155DA15EEEDF85DD6E18251ADA6E58D5D6FBA5B4C4371A` |

Archive size: 10,048,148 bytes.

## Recommendation

**Classification: neutral overall; likely slightly weaker than A2 on the highest-confidence slice.** Keep exact d842 as the robustness hedge and keep active A2 as the upside policy. Do not spend the A2 slot on this hybrid unless live diversification is valued more than the measured expected-strength estimate. The archive is valid and ready if that tradeoff is chosen manually.
