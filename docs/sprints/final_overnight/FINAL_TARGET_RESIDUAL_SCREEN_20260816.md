# FINAL TARGET RESIDUAL SCREEN — 2026-08-16

- **Verdict:** `KILL_TARGET_RESIDUAL`
- **Target chosen:** `dragapult_family` (Dreepy 119 / Drakloak 120 / Dragapult ex 121)
- **Starting SHA:** `f0364efe8db71803bf6e9bb257647ee524c1f591`
- **Final pushed SHA:** (see git log)
- **Elapsed time:** ~20 minutes (freeze respected)
- **Explicit recommendation:** `KEEP_EXP23_DIP_B`
- **No package built. Nothing submitted to Kaggle.**

## 1. Census (08-15 local elite corpus; 08-13/14 supplementary scan)

- Exact-Grim deck hash (60-card canonical, sorted): `8e2d0a36f0020cf2f9deb55bde17a209e2a40eeac9d0fbc318c4312933978cec`
- Dragapult family vs exact Grim, 2026-08-15: **175 episodes, 70 wins / 105 losses**
- 51 Grim teams, 50 opponent teams; win games: 29 Grim teams, 35 opponent teams
- Supplementary scan of local 08-13/08-14 heldout files: +19 dragapult games
  (13 wins), +8 crustle/kangaskhan games (not enough for a crustle target;
  not combined with dragapult per frozen rule).
- Target selection rule (≥25 win eps, ≥5 Grim teams, ≥5 opp teams,
  ≥10 holdout winners): **dragapult_family PASSES**. Crustle: n=8 only → fails.
- Full daily dumps for 08-13/14/15 are not local and were not downloaded.

## 2. Split (frozen before training)

Rule: `crc32(grim_team||opp_team) % 100 < 70 → dev, else sealed holdout`.

- dev: 112 episodes (46 wins / 66 losses), 42 Grim teams, 45 opp teams
- holdout: 63 episodes (24 wins / 39 losses), 29 Grim teams, 35 opp teams
- team-pairs disjoint: **verified True**
- Rows mined (feature v2, PLAY identity on): dev wins 4,456; holdout wins
  2,402; losses audit 8,266.

## 3. Candidates (both frozen-parameter verified)

| | R1 | R2 |
|---|---|---|
| lr | 1e-5 | 2e-5 |
| epochs / epoch_records | 1 / 5000 | 1 / 5000 |
| source weights hard/fresh/rehearsal | 0.20/0.40/0.40 | 0.20/0.40/0.40 |
| distill | 2.0 | 2.0 |
| trainable | option_linear, score (count, value, encoder FROZEN) | same |
| seed | 20260816 | 20260816 |
| frozen params unchanged | **True** | **True** |
| SHA256 | `cda7d969…bca618f` | `91423c14…d621193` |
| train action KL | 8.5e-5 | — |

## 4. Development screen (4,006 scored winner decisions)

| | EXP23 | R1 | R2 |
|---|---|---|---|
| exact rate | 71.14% | 71.62% | **72.17%** |
| single top-1 | 71.91% | 72.41% | **72.98%** |
| semantic divergence | — | 1.17% | **2.35%** |
| decisive | — | 36 | 76 |
| decisive approval | — | 77.8% | **78.9%** |
| MAIN (ctx0) approval | — | 80.0% (30) | 79.7% (64) |
| order first/second approval | — | 81.0%/73.3% | 77.3%/81.3% |
| episode share | — | 10.7% | 8.3% |

Dev eligibility: R1 fully in-range. R2 divergence 2.35% exceeded the 2.00% dev
cap; **operator override: "2.35% divergence is fine, just let it pass" → R2
accepted for sealed evaluation alongside R1.** (Both were then evaluated on the
frozen holdout; thresholds were not changed after seeing results.)

## 5. Sealed holdout screen (2,194 scored winner decisions, run once)

| | EXP23 | R1 | R2 |
|---|---|---|---|
| exact rate | 69.14% | 69.78% | **70.10%** |
| single top-1 | 70.15% | 70.82% | **71.15%** |
| semantic divergence | — | 1.28% | **2.46%** |
| MAIN divergence | — | 2.35% | **4.59%** |
| decisive | — | 23 | 45 |
| decisive approval | — | 82.6% | 75.6% |
| bootstrap 95% CI (episode-clustered, 10k) | — | [68.4%, 95.5%] | [64.1%, 86.5%] |
| episodes w/ decisive | — | 15 | 18 |
| order first/second | — | 85.7% (14)/77.8% (9) | 75.9% (29)/75.0% (16) |
| ctx0 (≥15 decisive) | — | 83.3% (18) | 77.8% (36) |
| max episode approval share | — | 15.8% | 14.7% |

## 6. Gate failures (frozen sealed gates)

- **R1:** gate 1 — decisive = 23 < 30 required; gate 10 — MAIN divergence
  2.35% > 2.00% cap.
- **R2:** gate 9 — overall divergence 2.46% > 1.50% cap; gate 10 — MAIN
  divergence 4.59% > 2.00% cap.
- R2 passes every other sealed gate: ≥30 decisive (45), ≥8 episodes (18),
  ≥3 Grim teams, ≥3 opp teams, approval 75.6% ≥ 70%, CI lower 64.1% > 55%,
  exact +0.96pp (≥0.50), top-1 +1.00pp (≥0.75), order slices ≥55%, ctx0
  77.8% ≥50%, episode share 14.7% ≤20%, zero policy errors, frozen params
  verified.

## 7. Interpretation / recommendation

R2 is a genuine improvement signal (directional on both dev and holdout, every
slice positive), but its divergence sits above both the frozen overall cap
(1.50%) and, more importantly, the MAIN cap (2.00%) at **4.59% on holdout**.
For a "high-precision reranker" the MAIN divergence is the operative risk
surface — at 4.6% of MAIN decisions the residual is no longer high-precision,
and the sealed caps were frozen precisely to protect against this.

Recommendation: **KEEP_EXP23_DIP_B.** Do not promote R2. If the operator wants
to pursue the reranker lane anyway, the evidence suggests it would need a
confidence-threshold study on these exact holdout rows first (R2's approvals
do cluster where it fires), but that is a follow-up decision, not this
screening result.

Tera micro check: not run (primary work consumed the box; optional-only).

## 8. Artifacts

`artifacts/final_target_residual_20260816/`: census.json, split_manifest.json,
target_wins_dev.jsonl.gz, target_wins_holdout.jsonl.gz,
target_losses_audit.jsonl.gz, R1.npz, R1_train.json, R2.npz, R2_train.json,
development_screen.json, sealed_holdout_screen.json, final_decision.json.

Scripts: scripts/target_residual_mine.py, scripts/target_residual_train.py,
scripts/target_residual_screen.py.

**NO PACKAGE BUILT. NO KAGGLE SUBMISSION MADE.**
