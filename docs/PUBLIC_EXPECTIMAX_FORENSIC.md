# Public “Probabilistic Expectimax” forensic

Date: 2026-08-13. Branch: `grim-5k-variance-floor`, starting commit
`816f537548d7733642e32c7ffa59c48151a4e3ce`.

## Decision

**SEQUENCE_ORACLE.** The notebook does not contain a portable expectimax
mechanism. Its search is operationally inert, and the package’s behavior is a
deck-specific deterministic heuristic. A tiny current screen was favorable
against three Grim-family opponents but collapsed 0-4 against authentic
Alakazam 2.7 full-search. Do not hybridize this code into A2+Damage V0 and do
not treat the historical 967.7 display as current-strength evidence.

Arm B remains permanently rejected and was not used.

## Source provenance

The authenticated Kaggle CLI pulled both current notebook snapshots:

- `safm1rza/improved-probabilistic-agent` (private current edit, notebook ID
  130704189);
- `aristophanivan/improved-probabilistic-agent` (public, V1 of 1, notebook ID
  124476619).

Both `.ipynb` files are byte-identical:

`68a93212f5d63a8013bddffdff08147f10f4a0d9c62c59db494ac71852b332d8`.

Kaggle’s private-kernel API did not expose a numbered safm1rza version, so its
version is recorded as the current pulled snapshot. Its code is nevertheless
byte-identical to public aristophanivan V1. Metadata differs only in ownership,
notebook ID, and privacy. Neither notebook declares datasets, models, or other
kernel sources; both declare only the Pokémon competition input and the same
Kaggle Python image. Runtime dependencies are Python’s standard library plus
the competition-provided `cg` SDK/native engine and card database.

## Deck

The reference uses a Fighting Mega Lucario deck, not Grim:

| Card | Count |
|---|---:|
| Makuhita / Hariyama | 2 / 2 |
| Lunatone / Solrock | 2 / 3 |
| Riolu / Mega Lucario ex | 4 / 4 |
| Dusk Ball | 4 |
| Switch | 2 |
| Premium Power Pro / Fighting Gong | 4 / 4 |
| Poké Pad | 2 |
| Hero’s Cape | 1 |
| Boss’s Orders | 3 |
| Carmine / Lillie’s Determination | 4 / 4 |
| Gravity Mountain | 1 |
| Basic Fighting Energy | 14 |

The policy explicitly recognizes its own evolution lines, Mega Brave, the
Crustle wall, Snorlax, Water decks, and several individual opposing card IDs.

## What the code actually does

### State and information boundary

At a live decision it uses the complete public observation: own hand, board,
discard and counts; opponent public board/discard/counts; stadium; turn flags;
legal options; public card metadata; and a small amount of within-turn global
state (`AttackPlan`, whether Lunatone’s ability was selected, previous engine
turn). It does not read the opponent’s hidden hand, deck, or face-down prizes.

The intended simulator samples `deckCount` entries uniformly without
replacement from the original full 60-card **own** deck. It does not subtract
known hand/board/discard cards, so sampled worlds can duplicate already-visible
cards and are not conditionally valid hidden states. It never samples or models
the opponent’s hidden cards.

### Action generation and sequencing

`AdvancedPolicy` scores every legal option at the current prompt using raw
option indices and card/board lookups. It also builds a global attack plan at a
MAIN prompt: desired attacker, target, attack, and whether an attachment is
needed. Later nested prompts consult that plan.

There is no semantic duplicate collapse, macro-action representation, or
transposition cache. Intended rollouts select one root action, then follow
`AdvancedPolicy` through at most 20 further hero prompts until the turn passes.
There is no opponent reply.

### The “expectimax” is inert

`SEARCH_ALGO` requests the first eight actions from
`AdvancedPolicy(obs).choose()`. But `choose()` already truncates its ranking to
`select.maxCount`; MAIN prompts have `maxCount == 1`. Therefore the candidate
list has one member and `SEARCH_ALGO` returns it immediately before calling
`simulate_action`.

Instrumentation across four complete games observed:

- 288 hero decisions;
- 176 MAIN calls returning a non-`None` search result;
- **0 simulation calls**;
- **0 search changes** from `AdvancedPolicy`.

`BEAM_WIDTH` and `MCTS_ITERATIONS` are unused. Thus the submitted runtime is
not expectimax, MCTS, beam search, or even one-ply search. It is the
deterministic `AdvancedPolicy` heuristic.

Had the early return not made it inert, the code would still be Monte Carlo
root-action evaluation with UCB1 allocation, not expectimax: independently
sampled own-deck worlds, a heuristic completion of the current hero turn, and
an additive leaf evaluator. It has no MIN/opponent node, no opponent-policy
node, no explicit chance tree, no probability weights, and no multi-turn
horizon. Sibling actions are not compared on matched hidden worlds.

### Intended evaluation function

The unused simulator leaf score is additive and heavily deck-specific:

- terminal win/loss: `+/-9,999,999`;
- prize-count differential: `10,000` per prize;
- own attached Energy: `+200` each;
- own line pieces: versus Crustle, Hariyama `+1,500`, Makuhita `+800`; otherwise
  Mega Lucario `+500`, Hariyama `+300`, Riolu/Makuhita `+100`;
- Crustle hand conservation: Hariyama `+1,000`, Makuhita `+500`;
- own Active HP: `+2/HP`; two or more Energy: `+500`;
- opponent HP: `-1.5/HP`;
- opponent next-turn threat: assume one attachment, use hard-coded damage for
  known attackers or `40 * assumed Energy`; if lethal, subtract `4,000` per
  exposed prize, otherwise subtract `1.5 * damage`;
- ordinary hand size: `+10/card`; versus stall: `+2/card` and `+30/deck card`;
- own deck below five cards: `-10,000`.

This contains useful interactions (stall changes hand/deck value; matchup
changes attacker value; lethal risk includes prize liability), but its scales
and identities are inseparable from the Lucario/Hariyama deck.

### Failure and runtime

Normal exceptions fail to the first legal indices, not to a strong baseline.
Malformed parsing can return `[0]`; simulator errors would score an action as
negative infinity. Globals are reset on an engine-turn change rather than an
explicit game reset.

Because the search never simulates, observed policy latency over four games was
p50 approximately 0.15 ms, p95 0.28 ms, maximum 0.39 ms. The advertised
1.5-second budget and UCB loop are not exercised.

## Comparison with existing search

| Property | Public notebook | Retired Grim Turn Director | Alakazam 2.7 as packaged | Proposed Grim sequence planner |
|---|---|---|---|---|
| Effective decision-maker | deck-specific heuristic | search override | learned MAIN policy + tactical vetoes; search only robust same-turn lethal | A2+V0 default, selective oracle proposal |
| Horizon | none; intended current hero turn | hero turn + one opponent reply, sometimes partial leaves | normal path is direct policy; lethal DFS completes current turn | completed hero turn → opponent turn → next hero turn |
| Hidden information | invalid own-deck resampling; no opponent model | exact opponent list offline | public-conditioned determinizations/filler/posterior machinery | public belief worlds; no exact live opponent list |
| Opponent model | none | unconditional worst-case heuristic reply | irrelevant for configured direct path except lethal robustness | plan-posterior-weighted response plus downside constraint |
| Chance/probability | none effective; intended uniform Monte Carlo samples | determinizations, then worst-case | multiple determinizations for lethal proof | matched-world expectation and uncertainty-aware abstention |
| Candidates | all legal scored, accidentally truncated to one | complete-action enumeration and circular beam pruning | learned prior, forced tactical candidates, vetoes | semantic complete-turn candidates, always including A2 |
| Leaf value | unused Lucario additive heuristic | Grim immediate-prize board vector | direct learned policy; terminal proof for lethal | terminal causal outcomes first; completed-turn metrics only for discovery |
| Baseline anchoring | none | weak/fixed override threshold | heuristic/legal fallback | exact A2+V0 fallback and paired baseline branch |
| Runtime/failure | ~0.15 ms; first-index fallback | one 300 s attempt | bounded/direct path, robust fallback | offline oracle first; any unequal coverage/error rejects comparison |

The public code does not explain why the old Director failed or offer a repair.
The Director intervened with a mispriced evaluator; the public notebook simply
does not intervene through search at all. Alakazam’s current package likewise
does not rely on broad rollout search: `DIRECT_POLICY=1` makes its learned policy
the ordinary MAIN decision-maker, retaining search only for verified lethal.

## Reproduction and current triage

The notebook code and deck were extracted without strategy changes. The only
compatibility addition is an unused empty `ptcg_ai` namespace required by the
repository’s isolated loader. The package passed a 60-card handshake, complete
games, legal-action checks, zero-error checks, and repeat/single/parallel trace
determinism.

The cheap screen used 20 paired schedules per opponent, ten per actual order.
It compares total agents/decks, not a same-deck policy intervention:

| Opponent | Reference | A2+V0 | Ref-only / A2-only | Delta | 95% CI |
|---|---:|---:|---:|---:|---:|
| exact d842 | 12 | 10 | 4 / 2 | +10 pp | [-14.2, +34.2] |
| master_v1 | 11 | 9 | 4 / 2 | +10 pp | [-14.2, +34.2] |
| replay_refresh | 13 | 8 | 7 / 2 | +25 pp | [-3.0, +53.0] |
| pooled Grim-family diagnostic | 36 | 27 | 15 / 6 | +15 pp | [+0.4, +29.6] |

This is unexpectedly favorable but small and matchup-concentrated. A separate
four-pair authentic Alakazam 2.7 full-search smoke was reference 0, A2+V0 4 on
both actual orders. Four pairs cannot estimate a rate, but the complete collapse
is enough to reject a current-strength claim and exposes severe matchup
fragility. All runs had zero policy/opponent errors and preserved the production
engine.

The user’s current-ladder update (~860 for the author/team) is treated as the
current prior; the historical notebook display (~967.7) is not used as evidence
of current 900+ strength.

## Portable mechanisms and deck dependence

The apparent strength is most plausibly attributable to:

1. the Lucario/Hariyama deck and its matchup against Grim-family packages;
2. extensive card- and matchup-specific tactical scoring;
3. a coherent within-turn `AttackPlan` carried across nested prompts.

The only broadly portable idea is coherent complete-turn sequencing. The code
does not validate probability-weighted planning, opponent modeling, or
expectimax because none of those mechanisms controls a decision. Porting its
weights, card IDs, invalid resampling, unmatched-world UCB, or first-index
fallback would repeat known Grim search failures.

## Exact next experiment

Run one **offline Sequence Oracle discovery**, with no runtime candidate yet:

1. Freeze A2+Damage V0 and sample 60 authentic Grim MAIN states, stratified by
   actual order and own-turn ordinal, emphasizing early development losses.
2. Enumerate semantic legal root alternatives and follow each through a
   complete current turn; exact A2+V0 is always one branch and continues all
   nested hero decisions after the forced root.
3. Compare siblings on eight matched, public-consistent hidden worlds with
   explicitly seeded fork RNG. Reject any state with unequal/incomplete turn
   coverage.
4. Continue each completed-turn branch to terminal with exact A2+V0 versus the
   authentic opponent package on matched determinizations. Use terminal paired
   wins as the causal label; completed-turn board metrics are diagnostic only.
5. Proceed to one runtime mechanism only if a recurrent semantic sequence wins
   in at least 12 independent states across at least two opponent lineages with
   no world-level regression. Otherwise stop Grim search development.

This tests the one idea the notebook gestures toward but does not actually
execute: whether coherent full-turn alternatives beat A2 under matched causal
continuation.

## Artifacts and hashes

- Both source notebooks: `68a93212…32d8`
- Extracted `main.py`: `a81eab3e…d2b`
- Deck: `2a541d7b…c19`
- Reproduction package tree: `b77646f4…66d1`
- Reproduction archive: `7362c81a…950e`
- Determinism proof: `97c44914…aea2`
- d842 screen: `280c79bb…d2a`
- master_v1 screen: `6944963f…74ce`
- replay_refresh screen: `70815121…ecf`
- Alakazam smoke: `2a2538cd…862`

All files are under `artifacts/public_expectimax_reference/`. No Kaggle upload
was performed.
