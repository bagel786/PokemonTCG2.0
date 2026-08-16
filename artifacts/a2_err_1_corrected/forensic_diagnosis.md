# A2-ERR-1 forensic diagnosis

Baseline parent: `6e87e6e9652686e9c412a325172fffac242a8181`  
Original ERR commit: `d9c5b6db3b6abbea82eedc720ca916d0c522d219`

## Original run

| Stage | Status | Exact result |
|---|---|---|
| Corpus certification | PASS as implemented, but invalid for final inference | 42,810 train corrections; strict membership used inferred median team ratings; four draw episodes were admitted across the six source dates |
| Epochs 1/2/3 | PASS mechanically | Exact A2 base hash; only `option_linear` and `score` changed; all frozen arrays byte-identical; zero non-finite/runtime errors |
| Aug. 13 Gate A | FAIL all epochs | Epoch 1 strict loss -1.011 pp, win -2.172 pp, first -1.382 pp, second -1.599 pp, top-3 -0.333 pp |
| Aug. 6 Gate B | FAIL all epochs | Epoch 1 top-1 -3.533 pp, top-3 -0.556 pp, greedy change 11.930%, KL 0.07040 |
| Gameplay | NOT REACHED | Offline gates did not authorize gameplay |

Original-run classification: **A. INVALID_CORPUS**. The strict population and draw handling were wrong, and the margin operated on raw option indices instead of semantic equivalence-class maxima.

## Confirmed defects and corrections

1. The pairwise margin now compares the maximum student logit in the elite semantic class with the maximum student logit in the rejected-A2 semantic class. A duplicate-raw-option unit test proves the group maxima are used.
2. Strict Aug. 13 membership now uses the official episode manifest condition `min_score >= 1050`, independently of top-70 teacher qualification. This exactly reconstructs 156 game-seat units, 65 wins, 91 losses, and 13,694 decisions.
3. A complete game must have exactly one winner and one loser. Four 0/0 exact-Grim draw episodes were excluded: Aug. 8 (1), Aug. 10 (2), Aug. 13 (1).
4. The approximate source-date top-70 method was retained. It ranked 353-399 observed active teams per date and admitted 57 teachers. Only eight admitted game-seats had an episode-assigned score more than 100 points below that day's inferred top-70 cutoff, so no material contamination requiring a rank-method change was established.

No learning rate, seed, epoch count, margin, KL weight, trainable module, batch mass, or promotion threshold changed.

## Corrected corpus

| Measure | Result |
|---|---:|
| Train corrections | 42,802 |
| Train loss corrections | 18,787 |
| Qualified pilots | 57 |
| Qualified episodes | 2,980 |
| Strict Aug. 13 game-seat units | 156 |
| Strict Aug. 13 wins / losses | 65 / 91 |
| Strict Aug. 13 decisions | 13,694 |

All corpus hard checks passed. Correction mass remained 25% in each win/loss by first/second bucket; pilot and date caps passed.

## Corrected train-correction learning

| Model | Semantic top-1 / promoted | Semantic top-3 | Mean elite semantic max minus rejected semantic max |
|---|---:|---:|---:|
| Exact A2 | 0.000% | 100.000% | -1.1789 |
| Epoch 1 | 27.473% | 96.881% | -0.5737 |
| Epoch 2 | 31.538% | 96.311% | -0.4111 |
| Epoch 3 | 34.358% | 96.045% | -0.3131 |

Epoch-1 semantic top-1 by recovery bucket: loss-first 26.02%, loss-second 27.51%, win-first 27.26%, win-second 28.90%.

Epoch-1 semantic top-1 by rank band: rank 1-20 24.44%, rank 21-40 28.37%, rank 41-70 28.40%.

Epoch-1 semantic top-1 by action family: ABILITY 9.58%, ATTACH 42.94%, EVOLVE 6.64%, PLAY 38.02%, SWITCH/promotion 12.03%, other 39.19%, target selection 22.63%.

## Corrected offline gates

| Epoch | Gate A loss | Gate A win | Gate A first | Gate A second | Gate A top-3 | Gate B top-1 | Gate B top-3 | Change | KL |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | -1.036 pp | -2.491 pp | -1.435 pp | -1.930 pp | -0.260 pp | -3.511 pp | -0.486 pp | 11.968% | 0.06922 |
| 2 | -2.141 pp | -3.848 pp | -2.886 pp | -2.917 pp | -0.528 pp | -4.874 pp | -0.765 pp | 14.512% | 0.09990 |
| 3 | -3.190 pp | -4.673 pp | -4.059 pp | -3.646 pp | -0.635 pp | -5.744 pp | -0.841 pp | 16.244% | 0.12144 |

All epochs preserved count/value outputs exactly, kept every frozen array byte-identical, and had zero non-finite values and runtime errors. Every epoch failed both behavioral gates. Gameplay was not run.

Corrected-run classification: **C. GENERALIZATION_FAILURE**. The model materially moved its own selected training corrections, but the learned shared reranking changes reduced agreement on untouched Aug. 13 and also exceeded every behavioral preservation bound. This is not category E and therefore is not strong gameplay evidence against the underlying recovery-strength hypothesis; it is a conclusive failure of the frozen A2-ERR-1 candidate under its unchanged offline gates.

## Immutable fallback

- Exact A2 policy SHA-256: `b19871a9f1499c2460ae266e58194acab1d8c90b390fa5cf24ed94b9a2b6bda8`
- A2+Damage V0 winner SHA-256: `a44b676f5ca135747b5d4d6923c7fb350a66369d188315b6ac0f291d23ca69e7`
