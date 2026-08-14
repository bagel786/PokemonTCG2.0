# Grim Sequence Oracle V0

Date: 2026-08-14. Branch: `grim-5k-variance-floor`. Starting commit:
`22ce89c6752ac7fc63fe227b3602ab73de650015`.

## Decision

The sequence-search hypothesis is weak. Across 960 fresh matched confirmation
worlds, A2+Damage V0 won 510 and the selected oracle plans won 513. The paired
win-rate delta was **+0.3125 pp**, with a root-cluster bootstrap 95% interval of
**[-1.458, +1.979] pp**.

Only three independent rescue roots executed two real deviations, below the
registered five-to-six-state requirement for a marginal +3 to +5 pp result.
The three traces were `attach Darkness -> END`, an exact Damage V0
damage-counter conversion followed by its target, and damage-counter count
followed by Team Rocket's Petrel. They do not form a recurrent, novel sequence
mechanism, and none is the hypothesized stranded-Munk attach/retreat/attack
sequence.

Arm B remained archived and unused. The qualified A2+Damage V0 package was not
modified. Nothing was trained, packaged, or uploaded. The completed experiment
was committed only after its pre-registered conclusion was fixed.

## Architecture

Each candidate is an index-free sparse plan of zero, one, or two semantic
deviations from exact deployed A2+Damage V0. A2 remains the continuation at all
other current-turn boundaries and on every future hero turn. Nested selections
are branchable; setup, order, forced, and one-choice prompts are not. Candidate
ordering uses only frozen A2 option/count logits. The value head and hand-coded
board evaluation are never used.

The planner executes the complete current hero turn, including repeated MAIN
and nested prompts. A semantic boundary/action mismatch invalidates the
remaining plan and immediately returns control to exact A2+Damage V0. Attack
ends planning through the native turn boundary. The run generated 3,561 unique
plans. Fifty-two roots reached the registered 64-plan cap; the other eight had
8, 9, 19, 20, 28, 37, 54, and 58 legal plans. All roots contained generated
two-deviation candidates, and nested deviations were present.

## State sampling

Sixty independently seeded authentic games supplied exactly one root each:

- 20 d842, 20 master_v1, and 20 replay_refresh;
- within every opponent, 10 actual-first and 10 actual-second;
- alternating physical seats;
- first branching MAIN decision on Grim's second own turn.

This deterministic outcome-blind rule produced 60 unique game seeds and 60
unique public-state hashes. No terminal result was consulted during selection.
The raw roots include game seed, physical seat, actual order, lineage, engine
turn, own-turn ordinal, public-state hash, observation, and the pre-root policy
history needed to reconstruct branch-local policy state.

## Hidden worlds and terminal evaluation

The final run used fresh, mutually disjoint registered seed blocks: source
games `4200000000`, generation `4101000000`, proposal `4102000000`, and
confirmation `4103000000`. Plan generation used one fixed registered-opponent
determinization. Proposal ranking used four matched worlds per root. The
selected nonbaseline plan was confirmed on 16 fresh worlds only when its
proposal mean terminal advantage was positive; otherwise the registered choice
was the exact baseline. Proposal and confirmation seed pairs were disjoint.

Every baseline and candidate arm received:

1. the same public-consistent hidden determinization;
2. the same explicit `SearchSetSeed` rollout seed;
3. an independently reconstructed fresh native root;
4. freshly reset and history-replayed hero/opponent policy state.

After the planned current turn, exact A2+Damage V0 controlled the hero and the
exact lineage package controlled the opponent until a real terminal result.
Scores were win `+1`, draw `0`, loss `-1`. Nonterminal truncation had no score
and would have invalidated the experiment. There were no truncations.

The run evaluated 3,561 unique plans over 14,244 proposal plan-world rows, then
960 fresh confirmation worlds. Total wall time was 1,023.09 seconds with eight
workers.

## Confirmed results

| Cell | Worlds | A2 wins | Oracle wins | Candidate-only | Baseline-only | Paired win delta |
|---|---:|---:|---:|---:|---:|---:|
| d842 | 320 | 169 | 166 | 18 | 21 | -0.938 pp |
| master_v1 | 320 | 177 | 182 | 20 | 15 | +1.563 pp |
| replay_refresh | 320 | 164 | 165 | 18 | 17 | +0.313 pp |
| **Overall** | **960** | **510** | **513** | **56** | **53** | **+0.313 pp** |

By actual order, first was +0.417 pp (277 versus 275 wins) and second was
+0.208 pp (236 versus 235). Every sampled root was own-turn ordinal two.
Terminal utility comparisons were 56 better, 54 worse, and 850 equal; the mean
paired utility delta was +0.00521 and downside rate was 5.625%.

Selected plans by registered length were 38 baseline, seven one-deviation, and
15 two-deviation. Realized confirmation worlds were 608 with zero deviations,
272 with one, and 80 with two. Twelve candidate-only wins executed two actual
deviations, distributed across three independent roots.

The three two-deviation rescue roots were isolated:

- d842, actual-second: `attach Darkness -> END`, +4 net wins in 16 worlds;
- replay_refresh, actual-second: damage-counter count -> Munkidori target,
  +1 net win, overlapping the already-qualified Damage V0 mechanism;
- master_v1, actual-second: damage-counter count -> Team Rocket's Petrel,
  +1 net win.

No two-deviation family recurred. The largest recurring selected nonbaseline
family appeared at only four roots, and the overall effect remained far below
the registered +3 pp threshold.

## Correctness and coverage

All required structural checks passed:

- fixed world/seed repeat stability;
- A->B versus B->A evaluation-order invariance;
- one fresh root per evaluated arm and no sibling/shared mutable RNG;
- semantic resolution under option reordering;
- no persisted prompt-local option indices;
- reveal divergence invalidates and falls back to A2;
- synthetic stranded-Munk `attach active -> retreat -> promote Grim -> attack`
  is discoverable with two deviations without a runtime hard-coded rule;
- attack terminates further current-turn planning;
- nested alternatives are branchable;
- truncation cannot become a draw;
- policy/engine errors fail closed.

The run had 60/60 roots, 960/960 confirmation worlds, zero policy errors, zero
engine errors, zero plan/world errors, zero incomplete rollouts, and zero
cleanup errors. Focused tests: `35 passed, 2 skipped` across the oracle,
complete-turn, deterministic-CRN, and shared seeded-Q backend suites.

## Integrity and artifacts

- Production engine before/after:
  `EAE88634E26DC31D94150A4D8202FC9D32596B8C688EF67E14CB4088CD4D5771`
- Seeded evaluation engine:
  `C257A121C07943C13B81CD276CFD6A88E035820E1678C64701A38692183B172E`
- A2 package tree before/after:
  `13426288358D597EAD809E45C364C7F7B9274A6EEBF55DDD942142E3326535C3`
- d842 package tree before/after:
  `0C15B56ADF3B09C654505A152309FDC9F8401579A495DA714347D98AE735003C`
- master_v1 package tree before/after:
  `8A06EBAB47CC60ED981DFADA85972EB8A62E732E349F01C2A3085262079F06E8`
- replay_refresh package tree before/after:
  `30E45955B67893514C8EE077CAC15D46FC207EFE781CBCE1B94242DEFDA4CBDC`
- Manifest: `artifacts/grim_sequence_oracle_v0/manifest.json`
  (`D5E66F88878591D7F2A6D0270C9949AA9F4E591BB44B2855F8E072C57BED6846`)
- Root states: `artifacts/grim_sequence_oracle_v0/stage1_roots.jsonl.gz`
  (`FD98F2792F349E75A77917FB94C380B26409C604CDFB04DE2622D3A418765032`)
- Raw proposal and confirmation results:
  `artifacts/grim_sequence_oracle_v0/stage1_raw_results.jsonl.gz`
  (`4FED0067E8A2C04533428459379D0B25ABC07F4E9FADD08FF03CA3A5F389D953`)
- Implementation: `scripts/run_grim_sequence_oracle_v0.py`
  (`48B168EB1632A1338C71A089124A33444C55EEC8B123D452ED92DF19D35681B8`)
- Focused tests: `tests/test_grim_sequence_oracle_v0.py`
  (`78812A2881467D0F411CFD7426DA6A09CA26FF41514B42429A829D46A3F48711`)

The hard `< +3 pp` gate is missed decisively, and the required five to six
independent two-deviation rescue states are absent. Do not retune, add a third
deviation, or continue Grim search development. Pivot away from Grim while
retaining A2+Damage V0 as the qualified package.

SEQUENCE_SEARCH_WEAK
