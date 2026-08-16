# OVERNIGHT CERTIFICATION PROTOCOL — 2026-08-16

**Branch:** `final/overnight-20260816`
**Starting SHA (origin/main):** `0b27410ca2af00990cd9bb300723bce90c68a3b7`
**Written BEFORE any overnight evaluation was run.** No thresholds in this
document may be changed after seeing results.

## 1. Frozen subjects

| Subject | Path | SHA256 |
|---|---|---|
| C0 (A2+Damage V0) package tree | `artifacts/grim_damage_conversion/winner/extracted` | (computed at freeze time, see frozen_hashes.json) |
| EXP-23 package tree | `artifacts/final_sprint/exp23_identity_trained` | 83489E0C80C631763C65375D2A7A34D28D6AA9FBB1D11E89D130C83B1E27F1C0 (CLERICAL CORRECTION 2026-08-16: earlier value 9F12… was stale; frozen_hashes.json is authoritative) |
| EXP-23 archive | `artifacts/final_sprint/exp23_identity_trained.tar.gz` | 0734B60C089EEA9C2E40550B8E9C6DC3983957210794BA245C4C00BD9D4E7096 |
| EXP-20 archive | `artifacts/final_sprint/exp20_punk_first_only.tar.gz` | 6D26061ED9F33B0ED0966BFDA542F6DCACB27EE887C61668FFE4267D52ACFF59 |
| EXP-23 model | policy_first/second/weights.npz in EXP-23 pkg | CEFE61189BC6F4E316212B19C99450E4B91FF1E5493F4467A95041C30FD96984 |
| C0 model (A2) | policy_first/second/weights.npz in C0 pkg | B19871A9F1499C2460AE266E58194ACAB1D8C90B390FA5CF24ED94B9A2B6BDA8 |
| d842 model | policy_d842_exact.npz in C0 pkg | D842F85ABFC44AF9F41979F91795E22C92C179B62E04D5A0A2F9C734E70AF1C3 |
| Deterministic engine | `artifacts/deterministic_engine/bin/libcg_seeded.dylib` | 867E3F9BB87E0B48889A44B5D4B04F5D2D434B2A0788D1B2BCFE0CAEB5AB78 |
| Production engine | `vendor/cg/libcg.dylib` | 7A157F045D333F99D1996D49C12BDBDD148072A619AF246385C7295518776E30 |
| Identity corpus (merged) | `artifacts/final_sprint/identity_train/merged_decisions.jsonl.gz` | (see frozen_hashes.json) |
| Identity train manifest | `artifacts/final_sprint/identity_train/train_manifest.json` | (see frozen_hashes.json) |

Full hash inventory: `artifacts/overnight_20260816/frozen_hashes.json` (computed at
freeze time). C0 tree hash + corpus hashes are recorded there; the values above
were verified by the file-level sha256sum run at freeze time.

## 2. EXP-23 training-purity audit (team_holdout exposure)

Evidence that the six team-holdout teams had **zero gradient and zero selection
exposure** in EXP-23 training:

- `training/replay_refresh.py::classify_fresh_row` (line ~117): rows whose team is
  in `manifest["heldout_teams"]` return `"team_holdout"` BEFORE the
  `internal_validation`/`train` buckets are considered.
- `training/replay_refresh.py::iter_split_rows` (line ~226): the fresh training
  stream requires `classify_fresh_row(row) == split` with `split == "train"`; the
  rehearsal stream explicitly skips heldout teams (`rehearsal_heldout_excluded`
  = 6038 rows, matching the team-holdout row count exactly).
- `training/replay_refresh.py::validation_loss` (line ~452): early-stopping /
  best-checkpoint selection uses the `internal_validation` split only
  (crc32(episode_id) % 10 == 0 episodes). Heldout teams never appear.
- `scripts/train_identity_fix.py`: single run, fixed hyperparameters
  (lr 1e-4, 3 epochs, fresh_weight 0.999, distill_weight 0.5, seed 20260816,
  heads-only). `identity_train/train/` contains exactly ONE output checkpoint
  (`identity_heads_1e4.npz`, sha CEFE6118… = shipped model). No candidate
  selection among checkpoints occurred.
- Gates (`training/evaluate_deterministic_crn.py paired`): synthetic seeded-engine
  games only; no replay data.
- Train log (`train/train.log`): validation = internal_validation only
  (3,361 records), train = 38,254 records; 3 epochs; ~74s CPU.

**Audit verdict: CLEAN.** Team-holdout rows never entered gradients, never
entered validation/early-stopping, never influenced model selection.

## 3. Held-out team split (frozen)

Six teams were excluded from EXP-23 training by the pre-existing manifest
(`stable_team_bucket(team) == 0`). Their raw episodes are the evaluation
material for the disagreement metric.

Per-team corpus size (rows / episodes in merged corpus):

| Team | Rows | Episodes |
|---|---|---|
| matsurih | 2042 | 21 |
| lollipop947 | 1638 | 17 |
| Mint120 | 1078 | 11 |
| GrimmsnaRL | 1075 | 10 |
| Dreamer | 108 | 1 |
| TMTA | 97 | 1 |

**Frozen assignment (predeclared, deterministic; v2 re-freeze BEFORE any
candidate evaluation — v1 assigned by team-name alphabetics, v2 incorporates
the pre-existing team-quality metadata below, which existed before the freeze
and was not derived from any EXP-23 evaluation):**

Pre-existing quality metadata (`data/meta/top_team_archetypes_147.json`):
matsurih rank 23 (1083.6), lollipop947 rank 73 (1017.6, pure Grim identity),
TMTA rank 162 (968.7), Mint120 rank 221 (948.8), Dreamer/GrimmsnaRL below
top-147.

- **CERT-B (certification) = {Dreamer, GrimmsnaRL, lollipop947, Mint120, TMTA}**
  (5 teams, 40 episodes, 3,996 mined rows). Primary evaluation set for full
  EXP-23. Includes the strongest pure-Grim unseen identity available
  (lollipop947); excludes the single strongest identity (matsurih) to keep an
  untouched high-quality judge.
- **CERT-C (sealed reserve) = {matsurih}**
  (1 team, 21 episodes, 2,042 mined rows; rank 23). NOT inspected for full
  EXP-23. Reserved as the untouched judge for any router/shield built after
  seeing CERT-B evidence. Single-team size is deliberate: 2,042 rows is ample
  power for a small-router gate, and concentrating the seal in one identity
  maximizes its independence.
- **CERT-A (temporal holdout): NOT AVAILABLE.** No fresh dump exists that
  post-dates EXP-23 training; the next daily dump publishes after the
  submission deadline. Per explicit directive, we do NOT fabricate CERT-A.
  A secondary, clearly-labeled layer is available: 104 raw episodes from the
  2026-08-13 daily dump involving the six heldout teams
  (`artifacts/overnight_20260816/episodes_0813_holdout_teams/`). These are
  identity-holdout (same six teams) and training-temporal-holdout (08-13 was
  never mined into the corpus) but PRE-date the training window, so they are
  reported separately as "CERT-B(0813)", never as CERT-A.

## 4. Evaluation units (mined rows vs runtime replay)

The merged-corpus rows carry `observation: null`, so the metric is computed by
**replaying raw episodes through the complete package runtimes**:

- One fresh subprocess per (episode, package). The package is loaded exactly as
  in production (`main.py` import), then the episode is walked in chronological
  order: the step-0 deck-select observation is fed first (triggers the runtime
  reset/latch path), then every ACTIVE decision observation for the hero seat
  in order. Runtime state (actual-order latch, damage-solver pending state,
  mirror/telemetry latches) therefore advances exactly as live.
- Only decisions of the winning exact-Grim seat are scored (same population the
  corpus mines).
- Raw episode files are re-downloaded from the official daily episode datasets
  (`kaggle/pokemon-tcg-ai-battle-episodes-2026-08-14`,
  `…-2026-08-15`) by `source_episode_file`. Local copy:
  `artifacts/overnight_20260816/heldout_raw/`.
- Package policy errors (illegal/exception answers) are recorded and excluded
  from the metric; error counts are reported.

## 5. Semantic identity (frozen function)

For every action (elite recorded, C0, EXP-23 — all index the same raw option
list), build the key:

```
(option.type, select.context, source_card, target_card, attack_id,
 option.area, option.inPlayArea,
 number/20, count/10, hp/400, maxHp/400, n_energies/10, n_tools/4,
 prize_value/3, appearThisTurn, playerIndex==yourIndex)
```

- `source_card`: identity-bound resolution — for PLAY options, the id of
  `hand[option.index]`; otherwise `resolve_area_card(obs, area, index,
  playerIndex)` id (falls back to `option.cardId or 0`).
- `target_card`: id of `resolve_area_card(obs, inPlayArea, inPlayIndex,
  yourIndex)` or 0.
- Hand-position index, bench-position index, and attached energy/tool index are
  intentionally NOT in the key (duplicate-equivalent engine indices collapse).
- Numeric slots rounded to 6 decimals.
- Multi-count actions compare as **sorted tuples of keys**; single-select
  compares the key directly. Mixed cardinality => different semantics.

This is the same equivalence class family as
`training/evaluate_elite_topk.py::option_key`, applied to raw options with the
PLAY identity fix. C0, EXP-23, and the elite all receive this same treatment.

## 6. Decision filters

Scored decisions: valid, non-forced decisions from the hero seat, where

- row status is ACTIVE and the observation has `select` with options,
- `minCount <= len(action) <= maxCount`, distinct in-range indices (elite side;
  package side must also be legal, else policy error),
- excluded: deck submission (no `select`), `SelectContext.IS_FIRST` (context 41;
  both packages are hardwired to request first),
- excluded: forced decisions (`len(options) == 1` or
  `minCount == maxCount == len(options)`).

## 7. Classification and primary metric

At each scored decision with semantic keys `K_e` (elite), `K_c0`, `K_e23`:

- `K_e23 == K_c0` → **IGNORED** (agreement; not decisive).
- `K_e == K_e23 != K_c0` → **EXP23_APPROVED**
- `K_e == K_c0 != K_e23` → **C0_APPROVED**
- `K_e` equals neither (or differs from both) → **ABSTAIN** (elite third action)
- Duplicate-equivalent differences are already collapsed by the identity
  function (no separate tie bucket).

**Primary metric:** `EXP23_APPROVED / (EXP23_APPROVED + C0_APPROVED)` computed
on decisive disagreements, with:

- disagreement frequency, decisive count, abstain count,
- episode-level clustered bootstrap 95% CI (resample episodes with
  replacement, 10,000 iterations; percentile method),
- team-balanced approval (mean of per-team ratios),
- breakdowns: by turn band (early 1–3 / mid 4–7 / late 8+), by actual order,
  by context, by source card, by action family, by team, by episode,
  by teacher tier (top-20/top-50/top-100 team rank where identifiable),
  first- vs second-order.

## 8. Calibration (run BEFORE any EXP-23 evaluation)

On the CERT-B certification episodes only:

1. **Positive control:** C0 vs d842 runtime (d842 package = C0 tree with
   policy_first/second replaced by `policy_d842_exact.npz`). Expectation: elite
   approval should reasonably favor C0.
2. **False-positive control:** EXP-20 vs C0 (EXP-20 = historical first-order
   punk rail; weak live evidence). Expectation: the metric must NOT show EXP-20
   massively superior to C0. If it does, the metric is suspect.

Both runs use the same frozen semantic identity, filters, and bootstrap.

## 9. Predeclared held-out pass bar (frozen)

Strong held-out pass for full EXP-23:

- **>= 55%** EXP-23 approval on decisive CERT-B disagreements,
- episode-clustered 95% CI lower bound **> 50%**,
- **>= 300** decisive disagreements preferred (report honestly if fewer),
- many independent episodes and several independent unseen teams,
- no high-support context with an obvious regression.

- 58–62% on unseen identities = exceptionally encouraging.
- 49–51% despite +5pp field results = BENCHMARK OVERFITTING WARNING → do NOT
  submit full EXP-23.
- CERT-C remains sealed unless a router/shield is built after CERT-B exposure.

## 10. Field battery (Phase 2) — frozen weights

Opponents (authentic packages, paired CRN, fresh seed blocks, zero errors
required):

- Grim family: B0, master_v1, replay_refresh, d842
- Other: starmie_v2_boss_atk, dipplin_d1, alakazam_2_4a (NO_SEARCH cheap first),
  alakazam_2_4a search-on (expensive, LAST), Crustle/Kangaskhan if an authentic
  package exists (TBD from repo inventory)
- 100 pairs/order/opponent screen; expand close cells to 200–400.

Aggregates (weights frozen before ANY candidate results are seen):

- **MACRO:** equal weight per distinct opponent policy.
- **META-WEIGHTED:** from the most recent local meta census
  (`data/meta/replay_progress.json` team_decks + `top_team_archetypes.json`),
  computed and frozen in `artifacts/overnight_20260816/meta_weights.json`
  before running the battery. Not adjusted afterwards.

## 11. H23-S order shield (Phase 3) — frozen design

`actual-first -> exact C0 (A2)`, `actual-second -> EXP-23`. No new training, no
opponent detection, pure actual-order router. Constructed by copying the C0
tree and replacing `policy_second.npz` with the EXP-23 model
(sha CEFE6118…). Evaluated on fresh field seeds + CERT-C (if CERT-A/B influenced
the design — they did not, but CERT-C use is permitted and predeclared here).

## 12. Counterfactual oracle (Phase 4) — offline only

`training/complete_turn_corrections.py` machinery for turn-completion
comparisons; terminal-outcome intervention studies where feasible. Results are
supporting evidence; terminal win-rate is the gold standard. No handcrafted
board scores.

## 13. Kaggle policy (frozen)

- Max ONE overnight submission, only on PASS_STRONG (all seven evidence
  sources coherent: held-out identity, calibration, broad field, causal,
  order stability, zero runtime errors, sterile packaging).
- Preferred final state: Slot A = known-safe C0, Slot B = certified challenger.
- Live state at handoff: active two = 55537754 (735.1) + 55537760 (582.0),
  both C0. 0 submissions used on 2026-08-16 UTC at freeze time.
- The September strategy competition is IGNORED (per directive).

## 14. Runtime/state replay correctness

- Packages are stateful (actual-order latch, damage-solver pending moves).
  Decisions are replayed only in full-episode chronological order with the
  deck-select reset first; anything else is a protocol violation.
- Per-episode subprocess isolation matches the paired-CRN gate harness
  (`training/evaluate_deterministic_crn.py`, spawn context).
