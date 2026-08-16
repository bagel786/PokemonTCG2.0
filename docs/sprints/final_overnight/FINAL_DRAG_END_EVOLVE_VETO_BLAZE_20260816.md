# FINAL DRAG END→EVOLVE VETO BLAZE — 2026-08-16

- **Verdict:** `PROMOTE_ONE_SHOT_VETO`
- **Branch:** `final/drag-end-evolve-veto-blaze-20260816`
- **Starting SHA:** `38896d93ed64a389c20d857717602dc522858ebe`
- **Final pushed SHA:** (see git log)
- **Archive:** `artifacts/final_r1_drag_gate_20260816/exp23_dip_drag_end_evolve_veto_blaze.tar.gz`
- **Archive SHA256:** `8ddab14a628d7cb1e2fb54f4b2de68da720bca6812155503d96547184644353c`
- **Recommendation:** manual upload of this archive if the team decides to spend a slot; otherwise keep DIP_B.
- **NO KAGGLE SUBMISSION MADE.**

## 1. Exact predicate

Base = certified DIP_B (EXP23 CEFE6118 policies, Dipplin surgery byte-identical,
`977f9e6e…` archive provenance). One-shot veto, fires at most once per game:

1. Opponent public zones (active, bench, pre-evolutions, discard, stadium) reveal
   Dreepy(119) / Drakloak(120) / Dragapult ex(121) → pending.
2. Lock at the next hero MAIN context; stays locked.
3. On a MAIN prompt where the base action is exactly END:
   - no ready Grimmsnarl attacker (no 648 on our active/bench with ≥2 energy);
   - opponent active is 119/120/121;
   - a legal Marnie-line evolution exists: source ∈ {647,648}, target ∈ {646,647},
     source == target+1 (the admitted 93755661 family, source 648 → target 647);
   - frozen R1 (`cda7d969…`, loaded from `policy_r1.npz`) proposes exactly that
     single EVOLVE option as its chosen action.
4. Override the END with that EVOLVE option. All later decisions return to
   certified DIP_B/EXP23.

Fail-closed everywhere else. Forbidden families (PLAY-vs-ABILITY, ATTACH,
ATTACK, Boss, damage movement, supporter, bench, END-vs-non-EVOLVE) are
structurally unreachable by the predicate. Dipplin/Lucario routes are
untouched (veto runs only when `route is None`).

## 2. Static family audit (mined dev+holdout Dragapult winner rows)

EXP23=END ∧ R1=Grim-line-EVOLVE ∧ MAIN context:

- dev: **0 states**, holdout: **0 states** (0 episodes).
- No negative expert evidence exists (the family is absent from the winner
  corpus — R1's static divergence comes from other families). The veto
  therefore only fires on states like the admitted live root.

## 3. Current-replay audit (fresh processes)

| episode | class | veto fires | changed decisions | errors |
|---|---|---|---|---|
| 93755661 | normal loss | **1** (step 58: END→EVOLVE 648→647) | 1 | 0 |
| 93673237 | normal loss | 0 | 0 | 0 |
| 93671387 | normal loss | 0 | 0 | 0 |
| 93730597 | normal loss | 0 | 0 | 0 |
| 93745631 | normal loss | 0 | 0 | 0 |
| 93685951 | structural | 0 | 0 | 0 |
| 93699067 | structural | 0 | 0 | 0 |
| 93679642 | win control | 0 | 0 | 0 |

- The single fire is exactly the admitted 4/4-world root (base END, candidate
  EVOLVE 648→647, same semantic action as the complete-turn evaluation).
- Munkidori/Adrena-Brain regressions (93673237, 93685951) do not fire.
- Win control has zero fires.
- **Non-Dragapult games: 54 of 54 replayed (EXP23 + DIP_B non-Dragapult
  episodes) — zero fires, zero errors.** (One fire listed in the raw audit
  JSON under the non-drag bucket is episode 93755661 itself, a Dragapult game
  accidentally included in that list — it is the on-target fire above.)
- Max one fire per game, zero illegal actions, zero policy errors.

## 4. Package / smoke

- Sterile extract to a fresh temp dir: PASS.
- Import smoke (ExternalSubmissionAgent on extracted tree): PASS.
- Deck-select smoke: PASS (60 cards).
- Short fresh-process engine smoke on 93755661: 57 decisions, veto fired once
  (source 648 → target 647), 0 errors.
- Policy identity inside archive: base = `cefe6118…` (EXP23), shadow =
  `cda7d969…` (R1). Only intended files differ from certified DIP_B:
  `ptcg_ai/target_router.py` (4-line hook), `ptcg_ai/drag_veto.py` (new),
  `policy_r1.npz` (new).

## 5. Limitations

- Static family support is empty (0 states), so the elite-approval gate is
  vacuous — promotion rests on the live 93755661 root admitted 4/4 worlds plus
  the structural impossibility of the known-bad families firing.
- The veto is expected to fire in very few games (only states matching the
  admitted family). Expected value is positive but small.
- One-shot latch means at most one intervention per game.

**NO KAGGLE SUBMISSION MADE. I will upload manually.**
