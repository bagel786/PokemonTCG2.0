# DRAGAPULT CAUSAL SPRINT — 2026-08-16

- **Decision label:** `KILL_NO_REPEATED_CAUSAL_PATTERN`
- **Starting branch/SHA:** `final/dragapult-semantic-sprint-20260816` @ `3bad90f2184940ade642b9eb0f2e9942bec7b1a1` (fetched from `origin/final/surgical-portfolio-20260816`, includes the DIP_B route-verification commit)
- **Final branch/SHA:** `final/dragapult-semantic-sprint-20260816` @ (see git log after push)
- **Elapsed time:** ~35 minutes (hard stop respected)
- **Dragapult games inspected:** 7 (6 EXP23: 5 losses + 1 win; 1 DIP_B loss)
- **Normal-tempo losses inspected:** 4 (93730597, 93673237, 93671387, 93745631)
- **Repeated semantic pattern found:** one candidate, REJECTED (see below). No qualifying pattern.
- **Candidate rule name:** `NONE`
- **Affected games:** n/a
- **Rescued games:** 0
- **Regressions:** n/a
- **Non-Dragapult fires:** n/a (nothing built)
- **Package path/SHA:** `NOT BUILT`
- **Final recommendation for the active Kaggle pair:** keep `EXP23 (55556726)` + `DIP_B (55562629)` unchanged. Do NOT burn a submission slot on a Dragapult intervention.

---

## 1. Case table

See `docs/sprints/final_overnight/dragapult_case_table_20260816.csv` (7 rows). Summary:

| episode | policy | order | result | first Grim | tempo | final prizes |
|---|---|---|---|---|---|---|
| 93730597 | EXP23 | second | LOSS | t4 | normal | 2v1 |
| 93673237 | EXP23 | first | LOSS | t5 | normal | 2v1 |
| 93671387 | EXP23 | second | LOSS | t6 | normal | 2v5 |
| 93745631 | DIP_B (=EXP23 base) | first | LOSS | t7 | normal | 2v1 |
| 93699067 | EXP23 | second | LOSS | t14 | structural | 2v1 |
| 93685951 | EXP23 | first | LOSS | t11 | structural | 1v1 |
| 93679642 | EXP23 | first | WIN | t7 | normal | 1v5 |

Replay root: `/Users/safiullahbaig/Projects/PokemonTCG2.0-overnight/data/replays/55556726` and `.../55562629` (already-local, no new download). Transcript generator written for this audit: `scripts/dragapult_transcript.py`.

## 2. Method (complete-turn semantics)

Each hero decision was decoded from raw replay `select.option` + `current` into
semantic actions (PLAY / ATTACH / EVOLVE / RETREAT / ATTACK w/ attackId /
ABILITY / damage-placement ctx15/16 targets with `playerIndex`-aware zone
resolution). Board snapshots (active, bench, HP, energies, prizes) are printed
at each turn boundary. This is the same zone-resolution logic used by the
existing Dipplin prompt resolvers (`ptcg_ai/dipplin/resolvers.py`).

## 3. The one mechanical candidate found — and why it is REJECTED

**Candidate:** Shadow Bullet's 30 bench splash being selected onto a *benched
Tera Dragapult ex* (Tera rule: "prevent all damage done to this Pokémon by
attacks while on your Bench"), wasting the 30 damage.

Evidence:

- `93745631` (DIP_B loss, t9, si110): single ctx15 prompt, action `[0]` = bench
  index 0 = `Dragapult ex[290]`. Next-turn board shows it still at 290 → the
  30 was silently prevented. Legal non-Tera targets existed (Drakloak[30],
  Munkidori[40]).
- `93673237` (EXP23 loss, t7, si132-133): first ctx15 selection `[0]` =
  benched `Dragapult ex[300]`, immediately followed by a re-prompt where the
  agent selected Munkidori `[1]`.
- **But `93679642` (the EXP23 Dragapult WIN, t7, si118) makes the identical
  selection** — splash `[0]` on benched Tera `Dragapult ex[300]` — and won the
  game 5 prizes to 1.

Rejection reasons (per evidence threshold):

1. Fails criterion "absent/rare/harmless in Dragapult wins": the exact choice
   appears in the dominant win.
2. Fails the causal chain requirement: 30 bench damage that would otherwise
   land on a 90-HP Drakloak or 110-HP Munkidori changes no prize, KO, or
   survival within 1-2 turns in any inspected game; those targets died to
   Froslass checkup accumulation regardless.
3. In `93673237` the engine re-prompted after the Tera selection, meaning
   live-engine behavior on this selection is not even consistently
   no-op (the wasted-damage effect only clearly occurred in `93745631`).

## 4. What the rest of the semantic audit showed

- `93730597`: single-Grim game. Grim KO'd Meowth ex t4, attacked twice,
  retreated at 130 HP, promoted a 10-HP Munkidori that accomplished nothing
  and died; no second attacker was ever energized. The failure is a general
  "second attacker not built" deficit, not one crisp public-state choice.
- `93673237`: second Grim arrived t7 but the race was already 3-2 against
  double-Dragapult + Fez board.
- `93671387`: double-Grim line actually present by t8 (the "correct" plan),
  still lost 2v5 against two Dragapult ex + Latias ex + Fezandipiti. No single
  rerankable decision stands out; splash went to Drakloaks (legal, optimal-ish).
- The three normal-tempo losses share no single repeated, mechanically
  dominated action beyond the rejected Tera-splash candidate. Their shared
  deficit (attacker pipeline vs 320-HP two-prize threats with 200-damage
  attacks) is exactly the broad strategic lane that prior sprints already
  showed generic retraining/playbooks cannot fix cheaply.

## 5. Explicitly not done

- No DIP_B router changes (verified machinery, per locked evidence).
- No mirror work, no Crustle rule, no broad heuristics, no training, no search.
- No evaluation harness runs (nothing was implemented).

## 6. Limitations / uncertainty

- Bench-zone index stability across prompts was assumed; two board
  re-snapshots disagreed by 10 HP in one cell of `93673237`, so single-cell
  forensics in this sprint were kept to choices visible in adjacent-turn
  boards.
- The engine's ctx15 re-prompt behavior after Tera-immune selections differs
  between the two losses; not fully understood and not worth resolving for a
  30-damage non-causal effect.
- Did not inspect older-policy Dragapult games (out of time); win/loss
  enrichment was assessed on the 7-game EXP23/DIP_B corpus, which is small.

## 7. Commands run (for reproducibility)

```
git fetch --all --prune
git checkout -b final/dragapult-semantic-sprint-20260816 origin/final/surgical-portfolio-20260816
python3 scripts/dragapult_transcript.py <replay-json> <sub-id> <seat>
python3 - <<EOF  (raw ctx15 dumps for 93673237, 93745631, 93679642)
```
