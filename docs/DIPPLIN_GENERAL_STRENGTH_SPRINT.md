# Dipplin General Strength Sprint

Status: **CANDIDATE SELECTED — ship D1 (continuity-gated bounded search)**
Branch: `opencode-dipplin-strength`. HEAD: `e863d56`.

## 1. Objective and accepted baseline

Goal: improve the Thwackey/Dipplin agent's general gameplay strength without
regressing the accepted D0 floor (`db59ce5`). D0 is the pinned deterministic
planner/runtime with `PTCG_DIPPLIN_SEARCH=0`. The candidate is D1: the same
runtime with a bounded, continuity-gated multi-action search (`search.py`)
behind `PTCG_DIPPLIN_SEARCH=1`.

Matchups (4 opponents): a2 (Grimmsnarl, exact), d842 (Grimmsnarl, exact),
Alakazam 2.4a (elite), Alakazam 2.7 (elite).

## 2. Sprint steps

1. **C1 TurnRoute v2 (route-v2 overlay, `a03e96e`)** — unified fallback so
   `_boss_improves`, `_modifier_crosses_threshold`, `_damage_expansion_needed`
   always run when the new route abstains. Gross screen: broken build (if/else
   replaced D0 fragments) pooled 32.0% — killed; fixed overlay pooled 45.0% vs
   D0 45.2% — **neutral, not promotable**. Left behind `PTCG_DIPPLIN_ROUTE_V2`.
2. **Mechanism report (D0 control, 400 games)** — going second costs ~15pp
   (first 0.530 vs second 0.375); second player attacks -1.12/game and
   first-attack KOs -0.52; `replacement_attacker_ready_end_turn` is a narrow
   counter, not predictive (win 0.14 vs 0.38) and is **not** used as a driver.
   Deterministic tiers structurally sound; defect is tempo/search -> D1.
3. **D1 bounded multi-action search** (`2b27c59`, `a5d040d`) — soft 0.65s /
   hard 1.5s timeouts, max 32 searches/game, MAIN/MIN-gated (cannot override a
   forced discard prompt).
4. **D1 CONTINUITY_PROOF** (`f6a90a5`, `6cf6d0e`) — only admit an override when
   it is continuity-causal from a root card (Night Stretcher, Poffin, Poké Pad,
   Sacred Ash, Brock, Hilda, Thwackey: Energy to Applin/Dipplin bench, bench
   Applin->Dipplin evolve, search/recover), preserves the D0 equivalence
   indices, never regresses attacker-ready / festival / core-attacker-resource
   metrics, and replaces an unreplaced attacker (baseline 0 -> candidate 1).
   Gate: `if tactical or continuity:`. Counters
   `d1_continuity_proof_checked`/`d1_continuity_proof_admitted`. Deliberately
   conservative (~2 admissions per 100 a2 games) and intervention games stay
   net-positive (0.571 vs 0.481 on the a2 screen).
5. **Xerosic resolver** (`e863d56`) — accepted D0 relied on the unknown-context
   fallback (`sanitize_selection(select, [], minCount)`) for forced discards
   (card 1197, engine-order = first N options). Added named
   `xerosic_discard` resolver reproducing that exact D0 behavior with
   `known_context=True`. Not present in the Dipplin deck (60 cards audited);
   behaviorally inert for this submission, completes the resolver table.
   The unqualified "smart" variant from `git show 6b0f31b` hurt A2.7 and was
   rejected.

## 3. Stage A — gross screen (100 games/opponent)

| metric | D0 | D1 | delta |
|---|---:|---:|---:|
| a2 | 0.550 | 0.550 | 0.000 |
| d842 | 0.460 | 0.540 | +0.080 |
| A2.4a | 0.360 | 0.490 | +0.130 |
| A2.7 | 0.440 | 0.460 | +0.020 |
| **pooled** | **0.452** (181/400) | **0.510** (204/400) | **+0.058** |

Order: first 0.530 -> 0.595; second 0.375 -> 0.425. Search ~55% completion,
zero errors. Latency mean 170ms, p95 654ms, p99 657ms, max 752ms (D1Config
soft 0.65s / hard 1.5s, max 32/game enforced). Intervention games win more
than abstention on a2 (0.667 vs 0.513) and d842 (0.581 vs 0.522).

## 4. Stage B — serious screen (200 games/opponent/arm)

D0 is pooled stageA control (100) + extra control (100) per opponent.

| opponent | D0 | D1 | D1-D0 | 95% unpaired CI |
|---|---:|---:|---:|---:|
| a2 | 0.500 (100/200) | 0.475 (95/200) | -0.025 | [-0.122, +0.072] |
| d842 | 0.490 (98/200) | 0.510 (102/200) | +0.020 | [-0.077, +0.117] |
| A2.4a | 0.355 (71/200) | 0.475 (95/200) | +0.120 | [+0.025, +0.215] |
| A2.7 | 0.405 (81/200) | 0.480 (96/200) | +0.075 | [-0.021, +0.171] |
| **pooled** | **0.4375 (350/800)** | **0.485 (388/800)** | **+0.0475** | [-0.001, +0.096] |

Zero illegal actions, zero policy errors, zero failed games. All D1 runs share
hero artifact `790a8e24448f`; all D0 runs share `e0b0b6dd20d6`; opponent
hashes consistent per matchup across arms.

## 5. Stage C — final confirmation (fresh seeds, 200 games/opponent/arm)

| opponent | D0 | D1 | D1-D0 | 95% unpaired CI |
|---|---:|---:|---:|---:|
| a2 | 0.415 (83/200) | 0.530 (106/200) | +0.115 | [+0.019, +0.211] |
| d842 | 0.500 (100/200) | 0.590 (118/200) | +0.090 | [-0.006, +0.186] |
| A2.4a | 0.440 (88/200) | 0.500 (100/200) | +0.060 | [-0.037, +0.157] |
| A2.7 | 0.360 (72/200) | 0.485 (97/200) | +0.125 | [+0.030, +0.220] |
| **pooled** | **0.4288 (343/800)** | **0.5262 (421/800)** | **+0.0975** | [+0.049, +0.146] |

Replication reproduced and exceeded the Stage B estimate. Zero errors.

## 6. Merged Stage B + C (400 games/opponent/arm, 1600 vs 1600)

| opponent | D0 | D1 | D1-D0 | 95% unpaired CI |
|---|---:|---:|---:|---:|
| a2 | 0.4575 | 0.5025 | +0.045 | [-0.024, +0.114] |
| d842 | 0.4950 | 0.5500 | +0.055 | [-0.014, +0.124] |
| A2.4a | 0.3975 | 0.4875 | +0.090 | [+0.022, +0.158] |
| A2.7 | 0.3825 | 0.4825 | +0.100 | [+0.032, +0.168] |
| **pooled** | **0.4331 (693/1600)** | **0.5056 (809/1600)** | **+0.0725** | **[+0.038, +0.107]** |

Every opponent cell non-negative, two individually significant (A2.4a, A2.7),
pooled effect statistically significant at 95%. Zero errors across all 3200
evaluated games.

## 7. Robustness and cost

- Zero illegal actions, zero policy errors, zero failed games across Stages
  A/B/C (D0 and D1 arms).
- D1 latency well within budget (p99 ~0.66s < 1.5s hard timeout).
- `PTCG_DIPPLIN_SEARCH=0` instantiates the exact D0 runtime; C1 route-v2
  remains behind `PTCG_DIPPLIN_ROUTE_V2` and is inert by default.
- Tests: 113 passed across the dipplin + evaluate suites (10 CONTINUITY_PROOF
  search tests, 1 Xerosic resolver test). Torch-based collection-error files
  (`test_train_*`, `test_schema*`, `test_evaluate_elite_topk`) remain excluded
  (pre-existing, unrelated to this sprint).

## 8. Final package and gates

`artifacts/dipplin_d1/submission.tar.gz` — built from HEAD (includes Xerosic
resolver; card 1197 is not in the audited 60-card deck, so it is inert for
this submission). Packager gates:

- deterministic double build (two fresh stages identical)
- archive structure audit (sorted members, normalized metadata, zero mtime)
- sterile import under `python -I -B` (search_enabled=true, 60 cards,
  deck.csv identity `269BC580...`, cache-free)
- equivalence smoke vs a2: 10/20, zero errors

```
archive_sha256:          E5B932DB2DFFC2A860F8B5B883785885F73FD820665119687BB0C29969583BA6
runtime_source_tree:     538EB4850EC3C9B95D03F14269835DF26175992615226158C0B2BF502790509C
linux_amd64_complete_game: pending_external_complete_game (heldout evaluator)
```

Note: Stage A/B/C evidence was produced with the functionally identical
pre-Xerosic artifact (`790a8e24448f`). The final HEAD package differs only in
the inert Xerosic resolver, verified by the equivalence smoke above.

## 9. Decision

Ship **D1** (`PTCG_DIPPLIN_SEARCH=1`, CONTINUITY_PROOF gate). Heldout /
diversity confirmation is performed by the separate evaluation agent using
`artifacts/dipplin_d1/submission.tar.gz`.

## 10. Artifact references (all under `artifacts/dipplin_forensics/`)

- Stage A: `stageA_d1_*_100.json`, `stageA_*_control_100.json`,
  `stageA_d1_audit_summary.json`, `stageA_d1cont_a2_100.json`
- Stage B: `stageB_d1_*_200.json`, `stageB_d0_*_extra_100.json`
- Stage C: `stageC_d1_*_200.json`, `stageC_d0_*_200.json`
- Analysis: `analyze_stageb.py`, `analyze_stagec.py`
- Evaluated D1 artifact: `artifacts/dipplin_d1_audit/extracted`
- Final package: `artifacts/dipplin_d1/submission.tar.gz` (+ `.manifest.json`)
