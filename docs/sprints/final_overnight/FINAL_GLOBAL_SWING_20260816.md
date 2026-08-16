# FINAL GLOBAL SWING — 2026-08-16

## 0. VERDICT

**NO GLOBAL IMPROVEMENT — KEEP DIP_B + EXP23.**

Do NOT consume any of the remaining 3 Kaggle submissions on a new candidate.
The A2-shrinkage hypothesis is falsified on both designated holdouts: elite
approval is strictly monotone in alpha with the maximum at alpha = 1.0
(exact EXP23). No finalist candidate exists.

## 1. Branch / head

- Branch: `final/surgical-portfolio-20260816`
- Head at write time: pushed commit `a1c4d5a` (global-swing commits follow; see git log)
- Frozen bases untouched: `experiment/anti-meta-data-20260816` @ `84f4cfe`,
  `final/overnight-20260816` @ `de532fa`

## 2. Model identity

- A2 (policy_weights.npz): `artifacts/grim_damage_conversion/winner/extracted/policy_weights.npz`
- EXP23 (policy_weights.npz): `artifacts/final_sprint/exp23_identity_trained/policy_weights.npz`
- 19 NPZ keys in both; identical key sets.
- 8 arrays differ, all heads: count_b(61), count_w(144x61), option_b(128),
  option_w(280x128), score_b(1), score_w(128x1), value_b(1), value_w(128x1).
- Encoder arrays byte-identical (no drift outside the fine-tuned heads) —
  interpolation is structurally valid.
- max|delta|: value_w 0.0357, count_w 0.0221, option_w 0.0209.
- Note: policy_weights.npz / policy_first.npz / policy_second.npz in the EXP23
  package are byte-identical copies; policy_d842_exact.npz == A2 (untouched).

## 3. Alpha sweep built

W(alpha) = A2 + alpha*(EXP23 - A2), applied to the three differing npz files.

| alpha | policy npz sha256 (all three files identical per alpha) |
|---|---|
| 0.60 | 8727a7bac53087db4e749abd036c1f22c60c657910fc3a95c75992edbb16aa92 |
| 0.75 | 4703d42df2845b31a78c65176d5c8603dcf8f5d4d87d0f69d8cf8764d7f63e94 |
| 0.875 | c6e534c3c0ba431fd9733ba695c20746856abd4fe78a0eb7a67994f1ba42aa9e |
| 0.95 | f657b808eadc53cb66deb5729afae622eceaa753e73bf2396b3bdb80e24d1715 |
| 1.00 | e7c91ac276764de7627736ec88e997b2f6f9ce047eaa8ddfa754107309e0c616 |

Packages preserved exact EXP23 runtime structure (PLAY identity on, Damage V0,
actual-order routing, exact deck). Manifest: `artifacts/global_swing_20260816/packages/sweep_manifest.json`.

## 4. Replay screen (elite approval on decisive disagreements vs A2)

Evaluator: identity-aware runtime replay walker (`replay_disagreement.py`
machinery) on the CERT holdouts; candidate semantic action vs recorded elite
action, decisive = candidate != A2 semantics. 0 errors for every package.

### CERT-B(0813) (16 units)

| package | decisive | elite approval ratio | early/mid/late approved | first/second approved | disagreements vs EXP23 |
|---|---|---|---|---|---|
| exp23 (1.0) | 169 | **0.455** | 36/22/2 | 25/35 | 0 |
| a95 | 178 | 0.437 | 36/24/2 | 27/35 | 16 |
| a875 | 193 | 0.388 | 34/23/2 | 27/32 | 49 |
| a75 | 215 | 0.331 | 31/22/2 | 27/28 | 86 |
| a60 | 243 | 0.270 | 27/21/2 | 28/22 | 132 |

### CERT-B (0814+0815, 40 units)

| package | decisive | elite approval ratio | early/mid/late approved | first/second approved | disagreements vs EXP23 |
|---|---|---|---|---|---|
| exp23 (1.0) | 529 | **0.440** | 109/65/1 | 79/96 | 0 |
| a95 | 554 | 0.404 | 108/60/1 | 76/93 | 48 |
| a875 | 584 | 0.376 | 102/63/1 | 77/89 | 119 |
| a75 | 652 | 0.323 | 98/62/1 | 77/84 | 247 |
| a60 | 699 | 0.279 | 91/58/1 | 72/78 | 353 |

Interpretation: EXP23's fine-tune direction IS the elite direction on heldout
teams. Every shrinkage step moves approved decisions back toward A2-rejected
actions; there is no optimum below alpha = 1.0. Disagreement vs EXP23 grows
super-linearly with shrinkage (132/353 decisions at 0.60), so smaller alphas
are not merely weaker — they diverge substantially.

Caveat: late-band decisive counts are tiny (2 and 1 rows), so a late-specific
optimum cannot be ruled out from CERT-B alone; nothing in the data hints at one
(all bands degrade monotonically with shrinkage).

## 5. Iteration 1B (late-only router) — NOT ENTERED

Trigger condition not met: no alpha improved late behavior (or any band)
relative to EXP23. KILL.

## 6. Iteration 2 (multi-seed delta ensemble) — NOT ENTERED

Trigger condition not met: Priority 1 produced a clear alpha winner (1.0),
not a noisy tie. KILL.

## 7. Loss mining (10-minute diagnostic) — KILL

EXP23-vs-A2 semantic disagreements on 29 live games (12 losses, 17 wins,
2725 decisions, 300 disagreements). Top clusters:

| c0 family | exp23 family | context | lost eps | won eps |
|---|---|---|---|---|
| PLAY | PLAY (different card) | MAIN | 10 | 17 |
| ABILITY | PLAY | MAIN | 10 | 14 |
| ATTACK | ATTACK (different target) | DAMAGE | 3 | 4 |
| PLAY | ATTACK | MAIN | 6 | 8 |

No cluster satisfies: >=3 distinct losses AND rare in wins AND same transition.
Every loss cluster is more common in wins. KILL — no rule.

## 8. Deck census lane — NOT ENTERED

Model-calibration lane died decisively (not inconclusively) at ~4:25, and the
deck lane requires a several-hundred-game behavioral diagnostic that cannot
finish before the 4:35 experiment freeze. High regression prior (model was
trained on the current deck). Not pursued. Correctly left alone.

## 9. Errors

- Zero policy errors in every replay walk (all six packages, both datasets).
- No CRN games were run this sprint (no finalist to screen; CRN not needed
  to falsify the shrink hypothesis).

## 10. Final archive

- None produced. Nothing promoted.
- Active plan unchanged: DIP_B + EXP23 (DIP_B archive sha
  `977f9e6e23c1898c4726fb630560a45e1218848a51e2b0de822cd7e0526048ce`).

## 11. Remaining risks

- None new for the submitted agents.

## 12. Files for the audit

- `scripts/build_alpha_sweep.py` (builder + manifest)
- `scripts/screen_alpha_sweep.py` (replay screen; NOTE: two bugs were found and
  fixed during the sprint — walker records use `package_action`/`elite_action`
  fields, not `action`; an earlier global replace left one `c0rec["action"]`
  reference behind, which inflated decisive counts in an intermediate run —
  final numbers above are from the corrected run)
- `scripts/loss_mining_diagnostic.py`
- `artifacts/global_swing_20260816/alpha_sweep_screen.json` (full screen output)
- `artifacts/global_swing_20260816/loss_mining.json`
- `artifacts/global_swing_20260816/packages/sweep_manifest.json` (hashes)
