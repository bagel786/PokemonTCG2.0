# DRAGAPULT SPRINT — FINAL LEDGER (2026-08-15/16)

Branch: `dragapult` (off grimmsnarl @ a5dac02). No interference with the parallel
Grimmsnarl session (separate branch, separate artifacts, own opponent dirs).

## Verdict

**DRAGAPULT_KILLED — do NOT submit. Preserve the remaining Kaggle slots.**

Best candidate achieved ~8-10% win rate vs Starmie and A2+Damage V0 against a
55% aggregate requirement. The gap is structural, not tunable within the
remaining time.

## Phase 0/1 — Census + deck freeze

- flg (rank 1, 1214.9) re-uploaded: current primary 55530210 pilots
  `bbdc6c274df3642c` — Team Rocket's Watchtower x2 + Risky Ruins x1 + Judge x2,
  dropping Dawn/Jamming Tower and one Fire. **The stored
  `freshstart/decklists/dragapult_ex.txt` (bbe68b1e00e51226) is OUTDATED.**
- Secondary flg build (55529968, f51cda…) adds Dunsparce/Dudunsparce.
- Kh0a (1110.2), 213tubo, Raihan, atsushi all still on the old list.
- FROZEN: `bbdc6c274df3642c` (rank-1 current build). CSV at
  artifacts/dragapult_frozen/deck.csv.

## Dataset (mined official episodes)

- 17 elite teacher submissions, ~1,250 episodes, **128,131 hero decisions**
  (wins AND losses), opponent tags (grim/starmie/dipplin/alakazam), deck-hash
  per row, actual-order per row, episode-level weights.
- New-deck support: 61 episodes / 6,639 decisions (flg 55530210, 75% WR).
- Starmie opponents = 27% of teacher decisions; Grim ≈ 10% (old meta) — the
  current ladder mix (25% Grim) is under-sampled in teacher history.

## Candidates trained

| Name | Mechanism | Val top1 (sem) |
|---|---|---|
| c1_pool | pooled BC, semantic loss, frozen×1/others×0.4, team ranks, 4ep/80k | 64.5% (65.0%) |
| c1_full (azure) | same, 4ep/120k rows | 64.4% (65.2%) |
| c2_outcome (azure) | c1 + win×1.15/loss×0.85 | ~65% |
| c3_grimstar (azure) | c1 + grim×3/starmie×2 | ~65% |
| grim_specialist | BC on Grim-opponent rows only, 5ep | 46.3% (on general holdout) |
| starmie_specialist | BC on Starmie-opponent rows only, 5ep | n/a at kill time |

Per-context: ctx-0 (main-phase plays: Poffin/Crispin/energy/Boss sequencing)
agreement = **50.2%** — the weakest bucket and exactly where Dragapult's
t3 Phantom Dive tempo line lives.

## Gates (seat-balanced, fresh seeds, zero policy errors)

| Candidate | vs Starmie v2 | vs A2+Damage V0 |
|---|---|---|
| c1_pool | **10.0%** (6/60) | **8.3%** (5/60) |
| old bc_combined_sem (Aug 14) | 22.5% (9/40) | 16% (100) |
| old bc_flg_full | 5% (1/20) | 6% |
| no-model heuristic floor | 2.5% (1/40) | — |

Gate 1 (Starmie) and Gate 2 (A2) both failed catastrophically; per mission
rules the candidate never reaches Dipplin/Alakazam gates. Aggregated estimate
≈ 9-13% vs the required ≥55%.

## Root cause

- Dragapult's plan is razor-thin on tempo: Poffin t1 → 4 Dreepy → Drakloak t2 →
  Dragapult ex t3 → Crispin → Phantom Dive ({R}{P}) t3/4. Teacher replays show
  this; clone traces show Dragapult ex arriving t5 and dying to Mega Froslass
  t4 pressure.
- 65% decision-level agreement compounds: 35% drift per decision puts the
  clone off-distribution within ~3 turns (ctx-0 alone at 50%).
- No Dragapult rule baseline exists anywhere (ptcg_ai falls back to
  GrimmsnarlHeuristic — wrong deck, 2.5% floor). BC had no safe scaffold.
- Matchup specialists trained on filtered rows only reach ~46% agreement on
  general holdout — routing them in would replace, not rescue, the main policy.
- Repo RL (schema-5 PPO) requires D2 relational actor + rollout collection +
  critic; hours of pipeline + known instability (P0.81 report). Out of scope
  for the remaining window.

## What would be needed (not tonight)

1. A proper Dragapult rule baseline (setup/Crispin/Phantom Dive/Hammer/Boss)
   to scaffold BC and cap compounding errors.
2. ~2-3x more current-meta teacher data with the new deck (Grim at 25% share
   is underrepresented in teacher history).
3. Advantage-aware or residual learning on top of the rule policy, gated by
   the existing paired-CRN funnel.

## Recommendation

Use the remaining submissions on the Grimmsnarl workstream. Dragapult does not
earn a slot from this sprint.
