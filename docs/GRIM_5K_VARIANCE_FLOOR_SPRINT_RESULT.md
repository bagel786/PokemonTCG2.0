# Grim 5K Variance Floor — Screening / Discovery Sprint: Final Report

Sprint prompt: `docs/GRIM_5K_VARIANCE_FLOOR_SPRINT.md` (main checkout)
`/Users/safiullahbaig/Projects/pokemonTCG2.0/docs/GRIM_5K_VARIANCE_FLOOR_SPRINT.md`)

Date: 2026-08-13. Screening sprint only. Nothing uploaded. No 1,000+ game
expansion was run for any arm.

## 1. Starting git state

- Working repo (main checkout): `bagel786/PokemonTCG2.0`, branch `main`,
  HEAD `f445186` ("fucking hell"). Untracked prior work preserved:
  `data/dipplin_replay_eval/`, `scripts/upload_damage_v0_copies.py`.
- Sprint worktree: `/Users/safiullahbaig/Projects/pokemonTCG2.0-grim-fix`,
  branch `grim-5k-variance-floor`, HEAD `8e4240d` ("add exact Grim damage
  conversion solver") — matches the quoted remote head
  `8e4240d3bea70611bc12aabc98ddfe8ef6d1f341`.
- Pre-existing uncommitted edits in the sprint worktree were NOT modified or
  reset: `docs/GRIM_5K_VARIANCE_FLOOR_RESULT.md`,
  `ptcg_ai/grim_variance_floor.py`, `scripts/build_grim_guardrail_candidate.py`,
  `tests/test_build_grim_guardrail_candidate.py`,
  `tests/test_grim_variance_floor.py`. A byte snapshot of that diff was saved
  to `/var/folders/d8/k9njndpd09nfsv4y2_dgs1z40000gp/T/opencode/grimfix_presession_diff.patch`.
- No commits were made during this sprint (per policy).

## 2. R0 provenance (immutable control)

R0 = qualified A2 + Damage V0, verified against
`docs/GRIM_DAMAGE_CONVERSION_MICROSPRINT.md`.

| Item | Value | Verified |
|---|---|---|
| Archive | `artifacts/grim_damage_conversion/winner/grim_a2_damage_v0.tar.gz` | exists |
| Archive SHA-256 | `A44B676F5CA135747B5D4D6923C7FB350A66369D188315B6AC0F291D23CA69E7` | MATCH |
| Model SHA-256 (policy_weights / policy_first / policy_second) | `B19871A9F1499C2460AE266E58194ACAB1D8C90B390FA5CF24ED94B9A2B6BDA8` | MATCH |
| Deck SHA-256 | `92B92BAC9F9163ECFF933B3DC39294D2CC154C8684F3C8497877661419EBC59D` | MATCH |
| Extracted tree | `artifacts/grim_damage_conversion/winner/extracted` (same tree as candidates/a2_damage_v0, tree SHA `13426288358D…`) | MATCH |
| Runtime | `main.py -> ActualOrderAgent -> policy_first/policy_second` (both exact A2, schema 2); exact d842 model as fail-closed fallback | confirmed |
| Tactical shield | applied unconditionally inside the A2 model (`ptcg_ai/model.py`) | confirmed |
| Damage V0 | enabled via `PTCG_GRIM_DAMAGE_SOLVER=v0` in `main.py`; acts only at Munkidori destination and Shadow Bullet Bench-target prompts | confirmed |
| Runtime search | absent/structurally disabled in R0 | confirmed |

Evaluation control dir used for all paired screens:
`artifacts/grim_damage_conversion/candidates/a2_damage_v0` (tree SHA identical
to the winner archive extraction). Opponent "exact d842" =
`artifacts/grim_variance_floor/candidates/B0`.

## 3. A0 — PLAY opportunity + blindness audit

Script: `scripts/audit_play_blindness_a0.py`
Input: 50 authentic live A2 replays, `data/replays/55399728` (submission
55399728), reconstructed with the exact R0 model (`policy_weights.npz`,
SHA-verified). 4,659 hero decisions, 2,062 MAIN/PLAY prompts, zero parse
failures. Damage V0 does not act at MAIN prompts, so MAIN-prompt
reconstruction equals R0 behavior.

Opportunity surface:

| Metric | Value |
|---|---|
| Total hero decisions | 4,659 |
| MAIN/PLAY prompts | 2,062 |
| Prompts with >=2 distinct playable card identities | 775 (37.6%) |
| Games containing >=1 such prompt | 50 / 50 |
| Loss games containing >=1 such prompt | 23 / 50 |
| Actual-second games | 18 |
| Second-order loss games with eligible prompt | 9 / 18 |
| Early (first two own turns) second-order multi prompts | 86 across 16 games (9 losses) |
| Multi prompts by order | first 523 / second 252 |

A0.1 opportunity ceiling (upper bound; a mechanism acting only in eligible
games cannot convert more than this):

- eligible-loss games / total games = 23/50 -> theoretical max uplift **46 pp**
- eligible-second-loss / second games = 9/18 -> **50 pp**
- early-second eligible losses = 9/18 second games -> **50 pp**

**Gate: surface is meaningful. PLAY track proceeds.**

Replay agreement (correctly named — NOT "accuracy"): A2 top-1 agreement with
recorded action = 100% (2,062/2,062 card-level, 2,062/2,062 strict option
level). This is trivially expected: the replays record A2's own actions and
the reconstruction is positionally exact. It does not contradict the PLAY
blindness defect; it is not gameplay evidence. Trainer-level breakdowns
(Petrel, Rare Candy, Unfair Stamp, Dawn, Boss's Orders, Night Stretcher, Poké
Pad, Pokégear, Poffin, Lillie's, Tool Scrapper, Spikemuth) are all 100% for
the same reason; full table in `artifacts/play_blindness_a0.json`. Hilda is
not in the deck.

A0.2 hand-position sensitivity diagnostic (NOT promotion evidence):

- 775 eligible prompts x cyclic hand rotations = 3,918 permuted feature views
  (hand list rotated; PLAY and HAND-area option indices remapped so the card
  multiset and all legal semantic choices are unchanged; state tokens are
  sum-pooled, so the only changed model inputs are the option index numerics).
- 1,578 / 3,918 rotations (40.3%) change A2's chosen semantic card.
- 484 / 775 prompts (62.5%) change under at least one rotation; many change
  under every rotation.
- Example: ep 91574390 step 5 — playable {Poké Pad, Snorunt, Spikemuth Gym},
  A2 plays Snorunt; all 7 rotations flip the choice.

Conclusion: A2's PLAY choice leans heavily on a brittle hand-position proxy.
Caveat acknowledged: hand position correlates with draw history, so
permutation sensitivity is evidence of positional reliance, not proof that
changed choices are wrong.

## 4. P0 (A1) — frozen PLAY-identity probe

Candidate: `artifacts/grim_play_identity/candidates/p0` (R0 tree + one patch).
Exactly what can this candidate change compared with R0? For MAIN/PLAY
options only, it feeds the actual hand-card identity (`hand[option.index]`)
into the frozen A2 `source_card` embedding slot instead of constant 0; nothing
else.

Isolation proof (`scripts/verify_p0_parity.py`, 4,659 replay decisions):
- Flag off: byte-identical features and decisions to R0 (0 diffs).
- Flag on: 0 feature diffs outside PLAY `source_card` (2,853 PLAY options
  gain identity); decisions differ only at MAIN/MAIN prompts (658/4,659);
  0 non-MAIN decision diffs; Damage V0 contexts untouched.

Screen (deterministic CRN harness, exact d842 opponent, untouched base seed
202608152001, 200 pairs):

| Order | Pairs | P0 | R0 | P0-only / R0-only | Paired delta | 95% CI |
|---|---:|---:|---:|---:|---:|---:|
| first | 100 | 57 | 57 | 20 / 20 | 0.0 pp | [-12.5, +12.5] |
| second | 100 | 49 | 51 | 20 / 22 | -2.0 pp | [-14.8, +10.8] |
| overall | 200 | 106 | 108 | 40 / 42 | **-1.0 pp** | [-9.9, +7.9] |

Errors: candidate 0, control 0, opponent 0.

**REJECT P0** (clearly negative/near zero). Expected OOD risk materialized;
this does NOT falsify the learned-PLAY-aware concept.

## 5. P1 (A2) — causally labeled PLAY-only residual

### 5.1 Causal label generation

Script: `scripts/generate_p1_causal_labels.py`. Seeded engine
(`BattleStartSeeded`) with real state forks (`SearchBegin`). Harvest:
hero MAIN prompts with >=2 distinct playable PLAY cards, cap 2 states/game.
Per state, branches force the R0-chosen card + top-2 R0-logit alternatives,
each continued to TERMINAL by the exact R0 package policy (shield + Damage
V0 + sanitize) versus the authentic opponent package policy; hidden cards
determinized via `determinize_known_matchup`.

RNG honesty (§5.4), empirically established this sprint:

- `SearchBegin` roots are byte-identical for identical inputs.
- Without `SearchSetSeed`, two identical forks DIVERGE (opponent search
  results differ within 2 steps): the engine's internal draw order is not
  reset by `SearchBegin` in this build.
- The seeded engine exports `SearchSetSeed(agent_ptr, u32)`. Called before
  `SearchBegin`, it makes identical forks byte-reproducible (proven: 4/4
  trials identical (win, 192 steps)).
- Fork activity does not perturb the main battle's RNG stream (100/100 trace
  entries identical after a fork point with and without forks).
- Per-branch determinism probe (same state, same fork seed, same forced card,
  rerun) passes: 0 failures after fixes. Claim: same determinization + same
  fork seed = identical downstream randomness; different fork seeds =
  independent determinizations.

### 5.2 Data sufficiency gate

| Metric | Value |
|---|---|
| Mining games | 300 (seeded, 6 workers) |
| Certified PLAY states | 596 across 298 episodes |
| Opponents | d842 200, master_v1 200, replay_refresh 196 |
| Orders | first 298 / second 298 |
| Own-turn ordinals | 1: 412, 2: 140, 3: 24, 4+: 20 |
| Cards represented | all 14 deck trainers/Pokémon appear playable |
| Clear preferences (>=2/3 terminal-win margin, full 3-det coverage) | 54 (46 episodes) |
| Ambiguous/discarded comparisons | 792 |
| Preference margins | 2: 50, 3: 4 |
| Mean chosen-card determinization win rate | 55.9% |

Gate: dozens of clear preferences across many episodes/opponents — PASSES
(at the low end; state population is broad even though preference yield is
~18%).

### 5.3 P1 residual

Exactly what can this candidate change compared with R0? At MAIN/MAIN
prompts it adds a bounded correction (tanh, |c|<=scale, scale chosen 1.0) to
PLAY-option logits only, from a 49-parameter linear model over the frozen R0
card embedding + public context; every non-PLAY decision remains exact R0 and
any failure returns unmodified logits.

Training (`scripts/train_p1_residual.py`): hinge on preference pairs +
weight decay + zero-residual rehearsal on all 596 state cards; input
standardization; 41 train / 13 val pairs (5-fold by game). Chosen
hyperparameters (scale 1.0, lam 0.5, val_acc 0.846). Package:
`artifacts/grim_play_identity/candidates/p1` (R0 tree +
`p1_residual.npz` + model.py hook, env-gated `PTCG_PLAY_RESIDUAL=1`).

Isolation proof (`scripts/verify_p0_parity.py` reuse): residual off =
byte-identical to R0; residual on = features identical, 327/4,659 decisions
changed, all MAIN/MAIN, 0 non-MAIN.

Screen (untouched seeds 202608170301 / 202608170601, 500 pairs):

| Opponent | Pairs | P1 | R0 | P1-only / R0-only | Paired delta | Order deltas |
|---|---:|---:|---:|---:|---:|---:|
| d842 | 200 | 104 | 100 | 41 / 37 | +2.0 pp [-6.7, +10.7] | first +7.0 / second -3.0 |
| master_v1 | 150 | 75 | 71 | 28 / 24 | +2.7 pp [-6.8, +12.1] | first +16.0 / second -10.7 |
| replay_refresh | 150 | 79 | 82 | 24 / 27 | -2.0 pp [-11.4, +7.4] | first -8.0 / second +4.0 |
| pooled | 500 | 258 | 253 | 93 / 88 | **+1.0 pp** | order-inconsistent |

Errors: 0 everywhere.

**REJECT P1** — pooled +1.0 pp with strongly order-inconsistent effects
across opponents (same pattern that killed earlier arms). Residual learned
the causal labels (val 0.85) but the population effect is not the target.

## 6. B — temporal two-turn takeover

Artifact recovery (per user instruction): the exact temporal continuation
checkpoint was found inside the preserved uploaded-router archive:

- `artifacts/elite_policy_candidates/empirical_router_v2_broad/package/empirical_policy_router.tar.gz`
  SHA-256 `CC567C0AD1787C39D1186075F85041DAFB9EC50D664F478C800682032C5EDC6D` — MATCH.
- Extracted `policy_continuation.npz` SHA-256
  `D4EFD8A8EEF1F617109DB80E74BB7EF667C74184BD3D579A3EFFFAD00B9BAB31` — MATCH.

Candidate: `artifacts/grim_temporal_takeover/candidates/b_takeover` (R0 tree +
`policy_continuation.npz` + takeover logic in `order_router.py`, env-gated
`PTCG_TEMPORAL_TAKEOVER=1`). Exactly what can this candidate change compared
with R0? When the hero is actually SECOND, the temporal continuation policy
controls every hero decision from the start of the hero's first in-game own
turn (engine turn 2) through the end of the second complete own turn (turn
4), then R0 resumes permanently; if the hero is actually first, or on any
temporal error (permanent disable for that game), R0 controls everything.

State synchronization: Damage V0 pending state is turn-keyed
(`_turn_key = (yourIndex, turn)`) so both policies start each turn clean;
each policy object keeps its own solver state; the takeover window contains
complete action sequences (MAIN, searches, switches, attachments, targets,
counts, attacks, nested prompts) with no per-decision alternation, no logit
mixing, and no learned gate. Setup/pregame (turn 0/1, IS_FIRST) remains R0.

Parity (`scripts/verify_b_takeover_parity.py`, 50 replay episodes, stateful
agent-level comparison): 4,659 prompts; 371 in-window (actual-second, turns
2-4); 13 window decision diffs (3.5% of window prompts; contexts MAIN,
TO_BENCH, SWITCH, TO_HAND); **0 non-window diffs**; 0 errors.

Screen (untouched seeds; actual-second pairs only):

| Opponent | Pairs | B | R0 | B-only / R0-only | Paired delta | 95% CI |
|---|---:|---:|---:|---:|---:|---:|
| d842 | 300 | 150 | 137 | 29 / 16 | +4.33 pp | [-0.0, +8.7] |
| master_v1 | 100 | 50 | 48 | 6 / 4 | +2.0 pp | [-4.2, +8.2] |
| pooled | 400 | 200 | 185 | 35 / 20 | **+3.75 pp** | ~[+0.2, +7.3] |

Errors: candidate 0, control 0, opponent 0.

**REJECT B.** Pooled actual-second delta (+3.75 pp) is below the +4 pp bar
and far below the strong-screen band (+6-8 pp); the master_v1 cell is weak
(+2.0 pp); the d842-only +4.33 pp is a single-opponent cell whose CI touches
zero. Actual-second coverage is ~half of games, so the implied overall
strength is well under the sprint's +4 pp target. No expansion was run.

## 7. C0 — Alakazam Petrel -> Unfair Stamp opportunity audit

Script: `scripts/audit_c0_petrel_stamp.py`. 80 seeded games, exact R0 vs the
authentic Alakazam 2.7 package (`freshstart/elite_submissions/alakazam_2_7`,
`NO_SEARCH=1` for tractability — noted as a confound below). Eligibility is
mechanically established at hero MAIN prompts: opponent Knocked Out one of
our Pokémon on their previous turn (public serial/discard inference), Petrel
playable, Stamp not in hand. The sequence is proven through actual engine
forks, never from hidden deck knowledge.

| Metric | Value |
|---|---|
| Games | 80 (70 wins / 10 losses vs this Alakazam setting) |
| Eligible opportunities | 45 across 29 games |
| Stamp present in legal Petrel search results | 27 |
| Stamp playable after retrieval | 27 / 27 |
| Complete-line games | 20 / 80 |
| R0 played Petrel at an opportunity | 2 / 45 |
| Loss games with opportunity | 5 (4 with complete line) |
| Theoretical max uplift (all eligible losses converted) | **6.25 pp** (5.0 pp complete-line only) |
| Opponent hand size at opportunity | median ~16 (range 6-22) |

**STOP TRACK C.** The line is mechanically real but too rare to plausibly
contribute meaningful strength: even magical perfect execution converts at
most ~5-6 pp against ONE opponent, before any downside in the 24 winning
opportunity games (Petrel consumes the Supporter slot and displaces R0's
development play), and the realistic conversion is a fraction of the ceiling.
C1 was not run per the gate.

## 8. Strategy-swamp idea

Not built (per prompt). The replay-derived insight was used only as guidance:
P1 labels come from simulator-decided terminal comparisons, never from
imitation of winning replay actions.

## 9. Seed / data split methodology

- A0: authentic replay data only (no seeds).
- P0 screen: CRN paired harness, base seed 202608152001 (unused by any prior
  arm), 100 pairs/order, physical seat alternates.
- P1 labels: mining base seed 202608160101, 300 games, 6 workers; training
  split by game (every 5th game to validation, 41/13 preference pairs);
  hyperparameters chosen on validation only (4 combos); ONE candidate entered
  the untouched screen (base seeds 202608170301, 202608170601).
- B screen: untouched base seeds 202608180201 (d842), 202608180301
  (master_v1), actual-second only.
- C0: base seed 202608190101.
- No screen seed set was reused across arms or used twice for selection.

## 10. RNG behavior

- Screen harness: seeded engine (`BattleStartSeeded`, mt19937); same seed,
  order, and physical seat within each candidate/control pair. Downstream
  streams diverge once policies act differently (documented in harness
  report).
- Fork machinery: roots byte-identical for identical inputs; `SearchSetSeed`
  before `SearchBegin` gives byte-reproducible forks (proven); fork RNG is
  isolated from the main battle RNG (proven). Without `SearchSetSeed`, the
  engine's internal draw order is not reset by `SearchBegin` (proven).
- Determinism probes passed for the P1 label pipeline (0 failures).

## 11. Opponent population

- exact d842 (`artifacts/grim_variance_floor/candidates/B0`)
- master_v1 (`artifacts/grim_damage_conversion/opponents/master_v1`)
- replay-refresh Grim challenger (`artifacts/grim_damage_conversion/opponents/replay_refresh`)
- Alakazam 2.7 authentic package (C0 only, `NO_SEARCH=1`)
All authentic packages already present in the repo; no new opponent policy
was built.

## 12. Modified / created files

Sprint worktree (`pokemonTCG2.0-grim-fix`):

- `scripts/audit_play_blindness_a0.py` (new)
- `scripts/verify_p0_parity.py` (new)
- `scripts/generate_p1_causal_labels.py` (new)
- `scripts/p1_data_sufficiency.py` (new)
- `scripts/train_p1_residual.py` (new)
- `scripts/verify_b_takeover_parity.py` (new)
- `scripts/audit_c0_petrel_stamp.py` (new)
- `scripts/debug_b_turn_numbering.py`, `scripts/debug_p1_*.py` (scratch
  diagnostics, kept for transparency)
- artifacts in grim-fix `artifacts/`: `play_blindness_a0*.json(l)`,
  `p0_parity.json`, `p0_vs_d842_screen_200pairs.json`,
  `p1_*` (labels, errors, sufficiency, training report, residual, parity,
  screens), `b_takeover_parity.json`, `b_takeover_vs_*_second_*.json`,
  `c0_*` (audit + rows).

Main checkout (`pokemonTCG2.0`):

- `docs/GRIM_5K_VARIANCE_FLOOR_SPRINT.md` (sprint prompt archive)
- `artifacts/grim_play_identity/candidates/p0` and `p1` (candidate packages)
- `artifacts/grim_temporal_takeover/candidates/b_takeover` (candidate
  package, includes recovered `policy_continuation.npz`)

No files inside `vendor/cg/`, the R0 winner tree, or any opponent package
were modified. No commits were created.

## 13. Reproduction commands

```bash
# worktree: /Users/safiullahbaig/Projects/pokemonTCG2.0-grim-fix (branch grim-5k-variance-floor)

# A0 audit
python3 scripts/audit_play_blindness_a0.py

# P0 parity + screen (200 pairs vs d842)
python3 scripts/verify_p0_parity.py --p0 .../grim_play_identity/candidates/p0 \
  --candidate-env '{"PTCG_PLAY_IDENTITY": "1"}' --output artifacts/p0_parity.json
python3 training/evaluate_deterministic_crn.py paired \
  --engine .../artifacts/deterministic_engine/bin/libcg_seeded.dylib \
  --candidate .../grim_play_identity/candidates/p0 \
  --control .../grim_damage_conversion/candidates/a2_damage_v0 \
  --opponent .../grim_variance_floor/candidates/B0 \
  --production-engine vendor/cg/cg.dll \
  --output artifacts/p0_vs_d842_screen_200pairs.json \
  --base-seed 202608152001 --pairs-per-order 100 --workers 8

# P1 labels (300 games), sufficiency, training, parity, screens
python3 scripts/generate_p1_causal_labels.py --mining-games 300 --base-seed 202608160101 --workers 6
python3 scripts/p1_data_sufficiency.py
python3 scripts/train_p1_residual.py
python3 scripts/verify_p0_parity.py --p0 .../grim_play_identity/candidates/p1 \
  --candidate-env '{"PTCG_PLAY_RESIDUAL": "1"}' --output artifacts/p1_parity.json
# screens: same CRN harness, --candidate .../p1, base seeds 202608170301 (d842), 202608170601 (master_v1, replay_refresh)

# B parity + screens
python3 scripts/verify_b_takeover_parity.py
python3 training/evaluate_deterministic_crn.py paired \
  --candidate .../grim_temporal_takeover/candidates/b_takeover \
  --control .../grim_damage_conversion/candidates/a2_damage_v0 \
  --opponent .../grim_variance_floor/candidates/B0 \
  --output artifacts/b_takeover_vs_d842_second_300pairs.json \
  --base-seed 202608180201 --pairs-per-order 300 --actual-order second --workers 8
# (repeat with --opponent master_v1, --base-seed 202608180301, --pairs-per-order 100)

# C0 audit
python3 scripts/audit_c0_petrel_stamp.py --games 80 --base-seed 202608190101
```

## 14. Runtime / errors

- All parity runs: 0 candidate/control policy errors; P1/B screens: 0 errors.
- P1 label mining: 300 games, 596 states, 0 errors, ~6 min (6 workers).
- Total sprint wall-clock: well under the two-day budget; no timeout or
  resource incidents.
- Latency impact: P1 residual adds a tiny vector product at MAIN prompts;
  B takeover adds one schema-3 inference per in-window decision; P0 adds
  nothing measurable. No latency gate was exceeded (no formal gate run —
  screening scope).

## 15. Known limitations / suspected confounds

- A0 replay corpus is 50 live games from one submission window; opponent
  families skew to Alakazam/Grimmsnarl/Crustle.
- P0 is an OOD probe by design; its failure says little about learned
  PLAY-aware models.
- P1 labels use 3 determinizations per state (binary outcomes, noisy); only
  >=2/3-margin preferences were used (54); the residual was trained on a
  narrow preference set and its screen was order-inconsistent — small-sample
  and matchup effects are confounded.
- B used the recovered temporal continuation checkpoint; the takeover window
  (turns 2-4) was defined from the seeded engine's turn numbering; the
  master_v1 cell is only 100 pairs.
- C0 used `NO_SEARCH=1` Alakazam (weaker than the ladder build) so the loss
  surface and ceiling are likely understated versus the real matchup; the
  ceiling still fails the meaningful-strength test.
- CRN pairing holds until trajectories diverge; downstream randomness after
  divergence is not "identical hidden randomness" (documented per §5.4).
- No candidate was tested against an authentic Crustle package (none was
  readily runnable in the harness); meta coverage is partial.

## 16. Candidates — one-sentence scope statements

- P0: exposes the actual hand-card identity of PLAY options to the frozen A2
  embeddings, changing nothing else.
- P1: adds a bounded, learned correction to PLAY-option logits at MAIN
  prompts only, leaving all non-PLAY decisions exact R0.
- B: hands full decision control to the temporal continuation policy for the
  hero's first two own turns when actually second, otherwise exact R0.
- C1 (not built): would force the coherent Petrel->Unfair Stamp macro at KO
  opportunities against Alakazam, then return to R0.

## 17. Rejected and passing arms

- Rejected: P0 (screen -1.0 pp), P1 (+1.0 pp pooled, order-inconsistent),
  B (+3.75 pp actual-second pooled, below threshold), C0 (opportunity too
  thin; C1 skipped).
- Passing arms: NONE.

---

# NO ARM PASSED SCREEN — STOP GRIM DEVELOPMENT
