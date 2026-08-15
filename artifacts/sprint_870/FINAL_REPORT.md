# SPRINT-870 FINAL REPORT — 6-7h strength search on exact A2+Damage V0

Date: 2026-08-15. Baseline: exact A2+Damage V0 (`grim_a2_damage_v0` winner; archive sha A44B676F…, tree sha 13426288…, model B19871A9…, deck 92B92BAC…). Nothing was uploaded; this is experiment-only.

## 1. What was run

56 paired common-random-number cells (candidate vs control on identical seeds, same physical seat, seeded engine `libcg_seeded`), plus replays/probes. **Every cell had zero policy errors.** All candidates built from the byte-identical frozen winner; diffs are minimal and attributable.

## 2. Results (paired diff vs control, control=C0 unless noted)

### Positive signals
| Experiment | Cell | Pairs | Diff | CI | Notes |
|---|---|---|---|---|---|
| punk bundle (EXP-1) | B0 | 1200 | +1.33pp | [-1.3,+3.9] | |
| punk bundle | master_v1 | 800 | +1.00pp | [-2.1,+4.1] | |
| punk bundle | replay_refresh | 800 | +2.88pp | [-0.3,+6.1] | |
| punk bundle | A2-ordered | 800 | -0.63pp | | ~0 vs our own lineage |
| **punk TARGET tier only (EXP-11b)** | **replay_refresh** | 600 | **+2.17pp** | **[+0.4,+3.9] SIGNIFICANT** | disc 21/8 |
| punk target only | B0 | 600 | +1.67pp | [-0.1,+3.5] | disc 20/10 |
| punk target only | master_v1 | 600 | -1.17pp | ns | |
| punk target only | Alakazam 2.4a | 400 | -0.50pp | ~0 | |
| punk target only | Dipplin D1 | 200 | -1.00pp | ns | 2 disc pairs |
| punk count only (EXP-11c) | B0 | 600 | +1.17pp | ns | |
| PLAY identity binding (EXP-7) | grim family pooled | 2000 | ~+1.1pp | noisy | |
| PLAY identity | Dipplin D1 | 400 | -3.50pp | ns | caution |
| PLAY identity | Starmie v2 | 200 | +2.00pp | ns | |
| mirror specialist (EXP-10) | B0 first cell | 600 | +1.33pp | ns | not reproducible |

### Killed (hard evidence)
| Experiment | Worst cell | Verdict |
|---|---|---|
| attach tier (EXP-5) | **-27.5pp** vs m1 | model's attach choices vastly better than blind tier |
| tempo dev rails (EXP-3) | -6.3pp vs C0 | d842-era rules actively harm A2 |
| seat-1 winner-BC 2nd arm (EXP-9) | **-7.3pp sig** vs m1 | winner-only BC covariate shift confirmed again |
| munk heal-source rail (EXP-2) | -4.4pp | model's own source choice is better |
| guardrails (EXP-4) | -1.8pp vs C0 | d842-era guardrails don't transfer to A2 |
| punk activate+count (EXP-11a) | -2.2pp | forced punk YES is harmful |
| punk_ct bundle (EXP-13) | -2.2pp B0, first-seat -5.7 m1 | count+target interact badly first seat |
| punk_ct+playid (EXP-14) | -2.0pp | |
| punk_ct second-only (EXP-15) | -0.3pp | m1 second-seat +4.7 was noise |
| damage v1 chip breakpoints (EXP-12) | -0.3pp (2 disc) | keep v0 |
| boss target solver (EXP-6) | 0 interventions | inert, A2 already optimal |
| mirror specialist vs master_v1 | -2.0pp | matchup-fragile |
| model zoo 2nd arm (9 models) | master_v1 +0.3 best; bc_v3 -39.3 worst | A2 is the best available model |
| seat-1 holdout imitation | +0.78pp imitation, gameplay negative | imitation ≠ strength (again) |

### Matchup matrix of C0 (control win rates observed across cells)
- vs B0 (d842 exact): 53-56%
- vs master_v1: ~51%
- vs replay_refresh: ~52%
- vs Alakazam 2.4a NO_SEARCH proxy: 88-90%
- vs Alakazam 2.7 NO_SEARCH proxy: ~88%
- vs Dipplin D1: ~53% (second-seat only 43.5% — a real weakness)
- vs Starmie v2: ~67%

## 3. Structural findings

1. **PLAY identity blindness (confirmed).** The shipped v2 encoder gives every PLAY option `source_card=0` — 110,966/110,966 PLAY options in the training data. The frozen model cannot see WHICH trainer card it plays (Boss vs Poffin vs Petrel) at train OR inference time; it must infer from context/position. Runtime binding of hand identity (EXP-7) is the only fix possible without retraining: +1.1pp pooled vs grim family, noisy, -3.5pp vs Dipplin (ns). **The real fix is retraining with identity features** — requires raw-observation corpus re-extraction (not possible locally; the 5.7M-decision pipeline exists in the repo).
2. **A2's neural board play beats all deterministic rails.** Every behavioral rail (attach, tempo, guardrail, munk source) regressed. Only narrow CONVERSION prompts (punk target, damage destination) have headroom. Count overrides are harmful — the count head is well-calibrated.
3. **Winner-only BC is confirmed harmful** (EXP-9: imitation +0.78pp, gameplay -7.3pp sig). The covariate-shift trap from `grim_recovery_analysis.md` reproduced exactly. Any future training needs counterfactual/outcome-filtered labels (plan.MD's search-filter design) or online RL with better reward shaping.
4. **The model zoo is exhausted.** 9 locally available grim models screened as second-arm replacements; none beats A2 (best +0.3pp ns). A2 is the correct model.
5. **Seat gap persists but is not fixable by the above.** C0: ~56% first / ~51% second vs d842-family. punk/playid/seat-1-BC all failed to move second-seat robustly.
6. **Alakazam is not the bleed** (vs proxies we win ~88%). Dipplin second-seat (43.5%) and the mirror (~51-54%) are the real matchup gaps.

## 4. Best available candidate

**C0 + punk_target (EXP-11b)** — reorder-only tier on Punk Up ATTACH_FROM target choice:
- +2.17pp significant vs replay_refresh, +1.67pp vs B0, -1.17 vs m1, ~0 vs Alakazam/Dipplin.
- Pooled ≈ +0.3pp over the pool; ~+0.9pp over grim-family opponents.
- Zero errors, zero illegal actions, 100% fail-closed (unknown prompts fall through).
- Below the +2pp promotion bar, but it is the only repeatable, signficant-positive component found.

Runner-up component: PLAY identity binding (+1.1pp grim-family, but Dipplin regression and OOD-embedding risk).

Honest verdict: **C0 remains the champion.** No ≥+2pp robust improvement was found within the runtime-accessible change space in this window. C0+punk_target is the only candidate I would even consider, and only with the replay_refresh/B0 evidence on the record.

## 5. What to look into next (ranked)

1. **Retrain with PLAY identity features** (fix the confirmed feature gap properly). Needs the raw-observation extraction pipeline re-run (5.7M-decision corpus build exists in `training/` + Azure runbooks). Highest expected value of anything found this sprint — the model is currently blind to a whole decision family.
2. **Counterfactual label mining for B1/B2b-style corrections** (plan.MD's search-filter design): 42 certified alternatives were mined previously; the pipeline to produce causal labels exists. Target the Dipplin second-seat weakness (43.5%) and the mirror.
3. **Trace-dump loss mining**: the `prove` mode of the CRN evaluator captures full game traces; extend it to dump per-decision traces for C0-vs-Dipplin/m1 losses, then hunt one repeated upstream mistake (the attach/tempo results show a blanket rule won't survive; a single certified mechanism might).
4. **punk_target deep-dive**: it won 21/8 discordant pairs vs replay_refresh — inspect WHY (probably energy distribution onto the right Grim before combat). A refined predicate (e.g., only when opponent shows pressure) could enlarge the win set.
5. **Order-conditional punk_target** (second-arm only) — cheap to test with the wrapper built for EXP-15 (change mode to punk_target). The punk_ct result says no, but target-only behaves differently (its B0/m1 first-seat cells were +2.3/-2.0 — mixed).
6. **Alakazam authentic-search cell** — the NO_SEARCH proxies understate the matchup; the authentic cell kept crashing/slow. Worth one clean run with more workers/time.
7. **Don't repeat**: broad rails, count overrides, winner-only BC, model-zoo swaps, attach tiers, generic search — all now have hard negative evidence.

## 6. Artifacts

- All candidates: `artifacts/sprint_870/exp*` and `zoo/*` (built from frozen winner; diffs recorded in each package).
- All 56 result JSONs: `artifacts/sprint_870/*.json`.
- Ledger: `artifacts/sprint_870/LEDGER.md`.
- Harness additions: `training/evaluate_deterministic_crn.py` (--hero-env/--opponent-env, additive).
- Training outputs: `artifacts/sprint_870/seat1_train/` (killed), `mirror_train/` (killed).
