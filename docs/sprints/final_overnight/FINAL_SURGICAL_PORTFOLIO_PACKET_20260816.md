# FINAL SURGICAL PORTFOLIO PACKET — 2026-08-16 (CORRECTED RECORD, V1.1 AUDIT)

## 0. FINAL DECISION

**DEMOTE ENDGAME_LETHAL. PROMOTE DIP_B-ONLY.**

Recommended next Kaggle submission:

- Archive: `artifacts/anti_meta_20260816/exp23_dip_surgical.tar.gz` (anti-meta worktree)
- **SHA256: `977f9e6e23c1898c4726fb630560a45e1218848a51e2b0de822cd7e0526048ce`** (bytes re-verified 16:05 CDT)
- Base: exact EXP23 (CEFE6118), DIP_B surgical only, no endgame layer, no neural specialists.

## 1. Time, branch, commit

- Packet written: 16:10 CDT (2026-08-16)
- Branch: `final/surgical-portfolio-20260816` @ pushed head (see git log; last commit = hardening + audit)
- Frozen bases untouched: `final/overnight-20260816` @ `de532fa`, `experiment/anti-meta-data-20260816` @ `84f4cfe`

## 2. Record corrections (REQUIRED)

- **Do not pool pre-fix (wall-clock budget) CRN cells.** They were produced by a
  nondeterministic solver build (commit `d4a08fd` documents the fix). They are
  exploratory only. The "4/520 mirror rescues" claim is WITHDRAWN.
- **The old homework output is SUPERSEDED.** It had two bugs (replay action
  alignment off-by-one; unparsed obs passed to determinization) and used the
  pre-hardening solver. Corrected results in section 3.
- **The single post-fix B0 rescue does not survive hardening.** With base-first +
  hidden-zone pruning + 3-world proof, fresh B0 (80 pairs, ENDGAME on vs off) shows
  0 discordants in either direction.
- **The single hardened D1 discordant is a process-history artifact, NOT a rescue.**
  Reproduced: fresh-process replays of seed 2026081777 (candidate arm) lose with
  101 decisions (identical across 4 runs); the same seed after 5 warmup games of the
  OTHER arm in the same process wins with 121 decisions. The paired pool interleaves
  arms, so candidate/control games run under different process histories. Any
  single-discordant cell from the shared-process pool is not evidence. (DIP_B's
  large 12-4 / 6-2 signals are far beyond this artifact rate and remain valid.)

## 3. Corrected ENDGAME evidence (hardened build, all on-vs-off, 0 policy errors)

Hardening implemented and verified by code inspection + replay:
1. hidden-zone fail-closed (kill branches at select.deck / LOOK; deck-order plays excluded)
2. base-first (override only if EXP23's own action lacks a proven terminal continuation)
3. 3-world determinization proof required for any override
4. exact searched action == sanitized executed action
5. stale base damage-solver state + surgical latch cleared on override

- Live homework (corrected alignment, hardened solver, all 30 EXP23 live games):
  653 eligible decisions; BASE_ALREADY_LETHAL 29, NO_PROVED 620, MISSED 4.
  **Distinct lost games rescuable: 0 / 12.** All 4 missed lethals are in won games.
  Zero false positives.
- B0 (80 pairs, on vs off): 0-0 discordants, exact parity.
- Alakazam (60 pairs, on vs off): 0-0 discordants, exact parity.
- Dipplin D0 (60 pairs, DIP_B+ENDGAME vs DIP_B): 0-0 discordants, exact parity.
- Dipplin D1 (60 pairs, DIP_B+ENDGAME vs DIP_B): 1 candidate-only discordant —
  NOT reproducible in fresh processes (history artifact, section 2) → treated as 0.
- Verdict: the hardened layer is behaviorally inert (no genuine rescue found
  anywhere) at non-trivial added live-runtime surface (first-ever live use of the
  C++ search API, 3-world searches on every endgame prompt). Per the promotion
  criteria (zero historical/synthetic loss rescues → demote): **DEMOTED.**

## 4. DIP_B (PROMOTE — unchanged, re-verified)

- Evidence unchanged from certification: D0 +6.67pp (12-4), D1 +3.33pp (6-2),
  all four order cells positive, exact off-target parity, 0 errors.
- Archive hash re-verified byte-identical this session.
- Fresh sterile smoke vs B0 on the extracted certified tree: TBD (4 pairs/order
  running at write time; certification smoke already existed from packaging day).

## 5. What ships / what doesn't

- SHIPS: DIP_B-only archive (`977f9e6e...`).
- DOES NOT SHIP: ENDGAME_LETHAL (demoted), dip_a, luc_veto, any specialist npz.

## 6. Incomplete / untouched (NOT promoted)

- Crustle: no opponent package exists; no rule built. (Hardened ENDGAME would
  have subsumed Crustle endgame escapes, but it is demoted.)
- Lucario: not run this sprint (LUC_VETO remains killed).
- Dragapult: evaluator nondeterministic; no rule.

## 7. Process-level finding for the higher-reasoning review (IMPORTANT)

The shared-process paired harness shows cross-game history dependence for some
agent pairs (same seed + same arm gives different outcomes depending on which
other games ran in the worker process before it). Magnitude appears small
(0 discordants in 240+ parity pairs), but any single-discordant cell must be
treated as noise, and future sprint evals should run each game in a fresh
process (or at least re-run suspicious single-discordant pairs in isolation).

## 8. Remaining risks (DIP_B-only)

- None new. DIP_B risk posture unchanged from certification.

## 9. Recommended Kaggle action

- **SUBMIT the DIP_B-only archive** (`977f9e6e...`) as the next submission.
- Do NOT submit exp23_portfolio_v1 (`b654b050...`).
- If review finds any correctness issue in DIP_B (none known), fall back to EXP23.
