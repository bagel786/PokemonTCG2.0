# Engine certification — episode 91427733 T9 (B2b retreat-legality)

**Date:** 2026-08-09. **Engine:** `cg` ctypes binary from `artifacts/master_v1_repackage/cg`
(loads via ctypes here; the `kaggle.exe` App-Control block does not affect the `.dll`).
**Method:** deterministic fork with `cg.api.search_begin(manual_coin=True, **determinize_state(...))`,
hero+opponent decks read from the replay handshake (mirror), forked from the recorded hero
observation, actions applied with `search_step`. Scripts: `scratchpad/certify_b2b.py`,
`certify_min.py`.

## Claim under test

`GRIM_5K_LOSS_ANALYSIS.md` and `STRATEGY_RESEARCH_V1.md` §5.4/A2 assert (previously **unverified**):
*attaching a Basic `{D}` Energy to the 0-energy, retreat-cost-1 Munkidori Active makes RETREAT legal,
enabling promote-Grimmsnarl → Shadow Bullet 180.*

## Result

**✅ CERTIFIED — the retreat-legality core.** At turn 9 (replay step 139): Active = Munkidori
(id 112), energies `[]`, hp 80/110, bench `[648 Grimmsnarl, 104 Froslass, 860 Snorunt, 646 Impidimp]`.

| State | RETREAT in legal options? |
|---|---|
| Root (0 energy on Active) | **No** — options were EVOLVE/PLAY×3/ATTACH×5/ABILITY/END |
| After `ATTACH {D}(id 7) → Active` | **Yes** — RETREAT appears (Active energies now `[7]`) |

Reproduced independently at step 140 (after a 2nd Munkidori was benched): attach→Active again makes
RETREAT legal. Deterministic across seeds.

**⚠ PARTIAL — the lethal tail.** Stepping RETREAT in the determinized fork consumed the attached `{D}`
(retreat cost paid, Active energies → `[]`) but the returned observation was a MAIN menu still showing
Munkidori Active with no ATTACK option, i.e. the post-retreat *promote-select* was not surfaced/handled
in this harness pass. This is a fork-observation handling detail, **not** evidence the line fails. The
plan's dedicated runtime-proof harness (`ptcg_ai/runtime_proof_director.py`) with correct promote-select
handling should complete the promote→Shadow-Bullet leg before B2b is used as a correction target.

## Bearing on the plan

- The **load-bearing** half of the B2b claim (retreat becomes legal after the attach) is now
  engine-proven; the strategy doc's "unverified" flag on this specific mechanic is resolved.
- B2b remains an **n-ply rule candidate** (attach→retreat→promote→attack), not a 1-ply fix; the
  regression test is this episode/turn.
- Per `GRIM_5K_LOSS_ANALYSIS.md`, B2b touches ~8% of losses — a real but secondary lever behind
  development (the §5.3 win-rate driver).
