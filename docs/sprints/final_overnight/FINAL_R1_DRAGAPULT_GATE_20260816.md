# FINAL R1 DRAGAPULT GATE — 2026-08-16

- **Verdict:** `KILL_R1_NO_CAUSAL_SUPPORT`
- **Branch:** `final/r1-dragapult-final-gate-20260816`
- **Starting SHA:** `a1021117eca413070431b0ecf86df875dc996211`
- **Final pushed SHA:** (see git log)
- **Elapsed time:** ~20 minutes (freeze respected)
- **Full R1 SHA256:** `cda7d969657159ae350ebf7e807a35fb63acf71dc15f4746b59dceb53bca618f`
- **Recommendation:** `KEEP_EXP23_DIP_B`
- **NO KAGGLE SUBMISSION MADE. No package built.**

## 1. Replay harness

Production-like chronological replay of 8 episodes (5 normal-tempo losses,
2 structural controls, 1 win control) through two complete package runtimes:
exact production EXP23 (CEFE6118, `exp23_identity_trained`) and frozen R1
(`r1_tree` = DIP_B tree with policy_first/second/weights replaced by
`R1.npz`, hash `cda7d969…`). One fresh subprocess per episode
(`maxtasksperchild=1`), deck-select reset first, identical actual-order and
identity-feature configuration, semantic action equivalence (frozen
certification semantic identity).

Public detector: opponent active/bench/discard + pre-evolutions contain
Dreepy(119)/Drakloak(120)/Dragapult ex(121). Pre-detection all decisions are
exact EXP23 by construction; route locks at the first hero MAIN context after
detection and stays locked. Zero policy errors in all 8 replays.

| episode | class | detected | lock step | hero decisions | post-lock divergences |
|---|---|---|---|---|---|
| 93755661 | loss, normal | yes | 23 | 212 | 17 (1 distinct family) |
| 93673237 | loss, normal | yes | 29 | 231 | 1 |
| 93671387 | loss, normal | yes | 12 | 185 | 0 |
| 93730597 | loss, normal | yes | 9 | 194 | 0 |
| 93745631 | loss, normal | yes | 4 | 206 | 0 |
| 93685951 | loss, structural | yes | 24 | 236 | 2 |
| 93699067 | loss, structural | yes | 14 | 260 | 0 |
| 93679642 | win control | yes | 5 | 143 | 0 |

Distinct divergence families:
1. **93755661 (normal loss)**: EXP23 END vs R1 EVOLVE Grim→Morgrem at turn 5
   (active Impidimp 70HP vs Drakloak 90; Grim evolution held). Repeats across
   17 consecutive prompts — EXP23 keeps passing, R1 commits the Marnie line.
2. **93673237 (normal loss)**: EXP23 PLAY Munkidori vs R1 ABILITY
   (Adrena-Brain) on bench Munkidori, turn 9 (2v1 prize race).
3. **93685951 (structural)**: same PLAY-vs-ABILITY Munkidori family + one
   EVOLVE-vs-ABILITY.

Early gate: ≥2 distinct normal-tempo losses changed with non-trivial
semantics → PASSED.

## 2. Complete-turn root evaluation

`evaluate_complete_turn_correction` (certified machinery), fresh EXP23
continuation for BOTH branches, 4 common-random worlds, max 64 turn steps,
120s timeout, one fresh process per root, hidden determinization from replay
handshakes. Metric vector (higher is better, lexicographic):
terminal_result, prizes, ko_value, ready_attackers, route_progress,
exposed_prizes, retained_critical_resources.

| root | baseline (EXP23) | candidate (R1) | coverage | verdict |
|---|---|---|---|---|
| 93755661:58 | END (pass) | EVOLVE Grim→Morgrem | 4/4 worlds | **ADMITTED** |
| 93673237:162 | PLAY Munkidori | Adrena-Brain | 4/4 worlds | regression_in_world:0 |
| 93685951:124 | PLAY Munkidori | Adrena-Brain | 4/4 worlds | regression_in_world:0 |

### Admitted root detail — 93755661:58 (turn 5)

All 4 worlds identical:
- baseline vector `[0, 0, 0, 0, 3.25, 0, -2.0]` (1 step: END)
- candidate vector `[0, 1, 0.429, 1, 4.25, 0, -3.0]` (14 steps: evolve →
  Punk Up energy pull → development)

Candidate strictly better in all four worlds: prizes 0→1 (a KO completed
within the turn), ko_value 0→0.429, ready_attackers 0→1 (a ready Grim
attacker exists where baseline had none), route_progress 3.25→4.25. Only
retained_critical_resources is lower (-2.0→-3.0, the evolution piece
committed). This is a concrete tempo benefit: R1 builds the Marnie line
while EXP23 passes.

### Rejected roots

- 93673237:162 — candidate loses route_progress 4.4→3.65 in every world
  (R1 spends the turn on Adrena-Brain instead of expanding the board).
- 93685951:124 (structural) — same family, candidate worse in world 0.

## 3. Promotion gate

1. ≥2 distinct normal-tempo loss episodes changed: **PASS** (93755661,
   93673237).
2. ≥2 distinct loss episodes contain an ADMITTED R1 root: **FAIL** — only
   93755661 is admitted; 93673237's single root regressed in world 0, and the
   structural 93685951 root also regressed. The frozen gate requires two
   distinct episodes with admitted alternatives; one admitted root in one
   episode does not qualify.
3. Admitted alternative concrete benefit: PASS (for 93755661 only).
4. Win control (93679642): 0 divergences → PASS trivially.
5. Zero policy errors: PASS (0 in all 8 replays, 0 in all root evaluations).
6. No pre-detection R1 use: PASS by construction.
7. Every changed action resolved semantically: PASS.
8. Not the rejected Tera-splash family: PASS.

Gate 2 fails → verdict per frozen rules: `KILL_R1_NO_CAUSAL_SUPPORT`.

## 4. Safety notes (no package path reached)

- No package built; certified DIP_B archive untouched.
- Off-target parity: all 8 replays run with exact EXP23 before detection;
  post-lock divergences exist only inside publicly detected Dragapult games.
- Dipplin route: no Dipplin games in scope; nothing in the certified DIP_B
  tree was modified (R1 tree is a separate copy under
  `artifacts/final_r1_drag_gate_20260816/r1_tree`).
- The single admitted root is one episode (93755661) with 4/4-world support.
  That is real but insufficient under the frozen multi-episode gate, and
  packaging a route for one episode-class of states is exactly the
  one-replay pattern the gate exists to prevent.

## 5. Artifacts

- `artifacts/final_r1_drag_gate_20260816/live_divergences.json`
- `artifacts/final_r1_drag_gate_20260816/complete_turn_results.json`
- scripts: `scripts/r1_drag_gate.py`, `scripts/r1_complete_turn.py`

**NO PACKAGE BUILT. NO KAGGLE SUBMISSION MADE.**
