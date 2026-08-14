# Grim final brief push — corrected dead-support escape

Date: 2026-08-14
Branch: `grim-5k-variance-floor`

## Decision

**REJECT the escape-only candidate. Retain exact A2+Damage V0. Stop Grim development.**

The corrected dead-support escape layer lost all six discordant matched games
in its one registered strength screen. Across 500 deterministic common-random-
number pairs, the candidate won 239 games and exact A2+Damage V0 won 245:
**-1.20 percentage points**, paired 95% CI **[-2.16, -0.24]**. There were zero
candidate-only wins and six control-only wins. The candidate was also negative
in both actual orders.

No second candidate was opened. Nothing was trained, packaged for submission,
or uploaded.

## Why this was the final credible mechanism

All broader post-A2 paths had already failed final confirmation: elite
fine-tuning/A2-ERR, PPO, empirical routing, strategic overlays, PLAY residuals,
temporal takeover, and sequence search. The remaining escape mechanism was
different in one important respect: its paid-retreat state machine had been
fixed after the old mixed B3 screen so that the mandatory
`ENERGY/DISCARD_ENERGY` payment prompt preserves the intended ready-Grim
promotion.

The experiment therefore isolated only this corrected sequence:

`dead support Active -> legal retreat`, or
`attach Basic Darkness to pay retreat -> retreat -> promote an attack-ready Grim`.

Punk Up, legacy Grim guardrails, opponent routing, search, reranking, training,
and deck changes were disabled.

## Immutable control

| Item | SHA-256 |
|---|---|
| A2+Damage V0 winner archive | `A44B676F5CA135747B5D4D6923C7FB350A66369D188315B6AC0F291D23CA69E7` |
| `policy_weights.npz` / `policy_first.npz` / `policy_second.npz` | `B19871A9F1499C2460AE266E58194ACAB1D8C90B390FA5CF24ED94B9A2B6BDA8` |
| Deck | `92B92BAC9F9163ECFF933B3DC39294D2CC154C8684F3C8497877661419EBC59D` |
| Exact A2+Damage V0 tree | `13426288358D597EAD809E45C364C7F7B9274A6EEBF55DDD942142E3326535C3` |
| Production engine before/after | `EAE88634E26DC31D94150A4D8202FC9D32596B8C688EF67E14CB4088CD4D5771` |

All hashes were reverified after the run. The fallback package was not edited.

## Isolation and safety gates

Candidate tree:
`artifacts/grim_final_escape/candidate`, SHA-256
`6B17428FDC373A693902F2661C179779DE52E1E1FD918FA1A6EC799E51681DE7`.

- Focused mechanics tests: **33 passed, 1 platform-dependent test skipped**.
- Authentic A2 replay audit: **8/4,659** semantic action changes
  (**0.1717%**) in four games and both actual orders.
- Out-of-scope changes: **0**.
- Illegal actions: **0**.
- Candidate/control replay errors: **0/0**.
- Fresh eight-game A2+Damage replay slice: **0/739** changes.
- Determinism proof: passed across repeat and four-worker runs; no mismatches.
- Candidate p99 replay latency: **1.01 ms**; max **39.43 ms**.

These gates show that the loss was not caused by broad policy drift, an illegal
action, a package error, or nondeterministic evaluation.

## Strength gate

Opponent and control were both exact A2+Damage V0. The seeded engine used
`BattleStartSeeded` with matched seed, actual order, and physical seat within
each pair. Base seed was `202608145000`; 250 pairs were run per order (500
pairs / 1,000 engine games), with zero hero or opponent policy errors.

| Actual order | Candidate | Control | Candidate-only / control-only | Delta | Paired 95% CI |
|---|---:|---:|---:|---:|---:|
| First | 132/250 | 136/250 | 0 / 4 | -1.60 pp | [-3.16, -0.04] |
| Second | 107/250 | 109/250 | 0 / 2 | -0.80 pp | [-1.91, +0.31] |
| **Overall** | **239/500** | **245/500** | **0 / 6** | **-1.20 pp** | **[-2.16, -0.24]** |

The predeclared acceptance condition required a positive overall effect with a
positive one-sided 95% lower bound, zero errors, and neither order below
-0.5 pp. The candidate failed the strength condition and both order floors.

## Interpretation

The recovery sequence is mechanically legal but not strategically dominant.
The most plausible explanation, now supported by the all-negative discordant
outcomes, is that paying an Energy and exposing a two-Prize Grim can be worse
than leaving or sacrificing a one-Prize support. “A ready attacker exists” is
therefore insufficient to decide the prize/tempo trade. This is an inference
from the paired outcome pattern, not a claim that every individual escape was
wrong for the same reason.

This closes the last narrow, post-fix recovery rail. Exact A2+Damage V0 remains
the strongest validated Grimmsnarl artifact in the repository.

## Evidence

- `artifacts/grim_final_escape/build_manifest.json`
- `artifacts/grim_final_escape/replay_scope_55399728.json`
- `artifacts/grim_final_escape/replay_scope_55491464.json`
- `artifacts/grim_final_escape/determinism_proof.json`
- `artifacts/grim_final_escape/escape_vs_a2_damage_mirror_500pairs.json`
- `artifacts/grim_final_escape/decision.json`
