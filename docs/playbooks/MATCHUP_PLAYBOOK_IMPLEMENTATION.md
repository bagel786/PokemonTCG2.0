# Matchup playbook implementation

## Result

The submission-ready candidate is `grimmsnarl_matchup_playbook`. It keeps the exact legal Grimmsnarl/Marnie's deck, uses full A2 as its broad policy, and adds a small public-information semantic reranker. Exact d842 is loaded only as the fail-closed fallback. No A2/d842 logit blend was selected because the earlier large comparison favored full A2.

The final independent population screen was positive but close: 986/1,440 (68.47%) versus A2's 974/1,440 (67.64%). Live-weighted results were 73.97% versus 73.79%. This is a candidate-level ranking signal, not a statistically resolved superiority claim.

## Router and public state

The stateful router accumulates only opposing Active, Bench, public pre-evolutions, and discard Pokemon IDs. It never reads the opponent hand, deck, prizes, replay labels, or handshake deck. A route locks only at high confidence; ambiguous support Pokemon alone are insufficient. Contradictory main-line evidence drops to unknown rather than forcing a route.

On 1,513 replay episodes / 138,996 decisions:

- decision coverage: 84.03%; routed-decision accuracy: 91.60%; high-confidence accuracy: 92.56%;
- final supported-route accuracy: 97.99%; overall final accuracy including unknown: 90.95%;
- mean first routed turn: 2.05;
- known-route decision activation: Grim 95.2%, Alakazam 93.8%, Lopunny 60.8%, Dragapult 76.0%, Ogerpon 95.3%, Lucario 97.5%, Dipplin 87.3%, Garchomp 97.2%, Mewtwo 96.6%, Bellibolt 97.3%, Starmie 89.8%, and Crustle 96.0% (classification only).

All twelve route classifiers completed two full smoke games. The unknown state was exercised on 22,198 replay decisions; unknown uses A2 plus the global actual-second layer. Any classifier/model/runtime exception fails closed to exact d842.

## Active and reduced plans

Active tactical routes are Grim, Alakazam, Mega Lopunny, Dragapult, Ogerpon toolbox, Mega Lucario, Dipplin, Garchomp, Mewtwo, Bellibolt, and Starmie/Froslass. Their final surgical layer is limited to public target pressure, relevant Stadium denial, and hard public damage-prevention checks.

Crustle is still recognized, but its matchup override is disabled. Across accumulated proxy screens the earlier Crustle target policy trailed A2 by about 3.5 points and could steer Grimmsnarl into the wall it should avoid. The ordinary A2 policy and tactical shield therefore handle this matchup. Morgrem-preservation, speculative bench caps, broad support suppression, and extra Boss/Froslass timing bonuses were also disabled for lack of repeatable evidence.

The global actual-second adjustment is intentionally narrow. It favors an available Rare Candy into an established Impidimp, first Grimmsnarl evolution, Energy on an attacker with a real attack deficit, attacker-line search, Punk Up continuity, and promotion of a ready Grimmsnarl; it penalizes Energy stranded on support Pokemon. It does not change the chosen first-player preference: the agent still requests first, then uses `current.firstPlayer` to detect the actual order.

## Population and evaluation

The current 84-game public sample was Alakazam 25.0%, Grim 20.2%, Lucario 13.1%, Archaludon 9.5%, Kangaskhan 7.1%, Garchomp 3.6%, Crustle 3.6%, and long tail 17.9%. The main runnable weights used 25.0 points of authentic direct-policy Alakazam and 20.2 points split across five authentic Grim policies. Lucario 13.1%, Crustle 3.6%, and Bellibolt/Ogerpon/Starmie at 2.0% each were proxy stress tests, not claims against exact ladder agents. The remaining 32.1% had no honest runnable proxy.

Only 8/84 public opponents were rated 850+, and only 3/84 were at least 75 points above the submission. No reliable stronger-opponent estimate is possible, so none is claimed.

Candidates screened included A2 parity control, conservative/balanced/bold overlays, actual-second-only, matchup-only, pruned, surgical, and repaired variants. The broad conservative candidate first led a 560-game-per-arm screen, then was essentially tied/slightly behind in a 1,400-game confirmation. That motivated the surgical reduction and Crustle disable.

Final forced-order screen (independent engine RNG, 60 games per order against each of 12 opponents):

| Policy | Games | Raw | Weighted | Actual first | Actual second | Grim | Alakazam | Other proxies | Errors |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| final playbook | 1,440 | **68.47%** | **73.97%** | **71.53%** | **65.42%** | **53.00%** | 88.75% | **75.83%** | 0 |
| full A2 | 1,440 | 67.64% | 73.79% | 70.42% | 64.86% | 51.67% | **89.17%** | 75.00% | 0 |

On 10,000 live replay decisions, the final archive changed 0.52% versus A2 (0.16% actual-first, 0.96% actual-second) and 7.56% versus d842. It produced zero illegal actions, exceptions, or replay failures. Route-specific changes versus A2 were concentrated in Grim (23), Lucario (8), Alakazam (7), Garchomp (4), and the global actual-second layer while classified Crustle (5); all other routes had at most two changes in this slice.

## Package and validation

- archive: `artifacts/matchup_playbook/grimmsnarl_matchup_playbook.tar.gz`
- archive SHA-256: `79A76075E70D3A924BD9D835382FE37F8EE31A32DA66A60C8E6FE019C15BAE59`
- size: 10,053,137 bytes
- deck SHA-256: `92B92BAC9F9163ECFF933B3DC39294D2CC154C8684F3C8497877661419EBC59D`
- A2 model SHA-256: `B19871A9F1499C2460AE266E58194ACAB1D8C90B390FA5CF24ED94B9A2B6BDA8`
- d842 fallback model SHA-256: `D842F85ABFC44AF9F41979F91795E22C92C179B62E04D5A0A2F9C734E70AF1C3`
- runtime SHA-256: `01FF95556E9171D77AB2A2A26DA9F12AD1DD85CCA3AC019BC1FF6BCEC0DB4B72`
- configuration SHA-256: `D00202994F402DD785689F45B9E17EAA050953B5AEC96DC516F3D21271726979`
- entry-point SHA-256: `EDD2871101D89299846C455E82807A601E37177A44077DCF8FA36AB78B739BE9`
- deterministic base archive SHA-256: `0958BD8847266EFBC38658D62B9AC4DCD62A9AAED3D1098F093A677AFCBFED4C`

The builder produced byte-identical archives on two builds. The exact final archive passed clean extraction, no-`__file__` entry-point execution, conventional isolated import, initial deck return, and 60 complete self-play validation games. The last 30-game run covered 5,759 decisions with zero errors; latency was p50 0.587 ms, p95 1.256 ms, p99 1.776 ms, and max 20.139 ms. Final-equivalent population, route-smoke, and package tests covered 1,526 complete games / 257,506 decisions with zero hero policy errors.

## Recommendation

Use this archive as the next experimental replacement for A2 if a slot is intentionally opened: it was the strongest valid new candidate in the final screen and improved both observed orders while preserving 99.48% A2 decision parity. Confidence is moderate, not conclusive, because the lift is small and several non-Grim matchups are represented only by proxies. No live slot was changed and no upload was performed, as required.
