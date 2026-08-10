# Loss Pattern Report — Submission 55389103

**Agent:** `grim_5k_guardrail_search_disabled_v1` (original 5k Grimmsnarl model + deck, narrow guardrails, runtime search disabled)
**Date of analysis:** 2026-08-09
**Sample:** first 15 rated games (9W–6L), all replays pulled from Kaggle
**Replays:** `artifacts/wave1_push/live/replays/55389103/`

---

## 1. Headline

The losses are **not caused by the guardrail update**. They are a pre-existing base-model
failure that the guardrails happen to be pushing against — just not widely enough.

One defect explains five of the six losses:

> **Our Active slot is repeatedly occupied by a Pokémon that physically cannot attack with
> our deck, and the agent does not fix it.** It does not retreat, does not attach energy to
> the Active to make retreat legal, and does not promote the Grimmsnarl ex.

Across the four most recent losses we attacked **8 times in ~26 of our turns**. We are not
losing damage races; we are not showing up.

---

## 2. Method

For every hero decision in each replay, the shipped agent and the bare 5k model were both
re-run against the recorded observation, using the exact extracted submission package
(`artifacts/grim_guardrail_candidate/extracted_search_disabled_v1/`) so the runtime path
matches what Kaggle executed. Three quantities were compared per decision:

1. `baseline` — `sanitize_selection(...)` on the raw 5k model ranking (no guardrails)
2. `shipped` — `GrimRuntimePolicy.choose(...)` (guardrails, search disabled)
3. `live` — the action actually recorded in the replay

**Local reproduction matched the live action on 100% of decisions in every game analyzed**
(0 mismatches across 6 games). The agent is deterministic and the replays are faithful, so
the counterfactual below is exact, not inferred.

---

## 3. The six losses

| Episode | Seat | Opponent archetype | Turns | Our attacks | Their attacks | Prizes (us–them) |
|---|---|---|---|---|---|---|
| 91427733 | 0 | Grimmsnarl (mirror) | 14 | 3 | 3 | 0–5 |
| 91430333 | 1 | Mega Lucario ex | 12 | 3 | 4 | 3–5 |
| 91434875 | 0 | Grimmsnarl (mirror) | 12 | 3 | 3 | 2–5 |
| 91435775 | 0 | Alakazam / Dudunsparce | 12 | 2 | 6 | 2–5 |
| 91436677 | 0 | Archaludon ex | 14 | 3 | 7 | 2–5 |
| 91437814 | 0 | Iono's Bellibolt ex | 14 | **0** | 6 | 0–5 |

Only **91430333** (Mega Lucario ex, 440 HP) looks like an ordinary matchup loss: we took 3
prizes and traded attacks at a normal rate. The other five share the pattern below.

---

## 4. Root cause: dead Pokémon in the Active slot

Our deck runs **Basic {D} Energy only**. Several of its Pokémon cannot attack with it:

| Pokémon | Attack | Cost | Attackable with our deck? |
|---|---|---|---|
| Snorunt | Chilly | `{W}` | **No** |
| Froslass | Frost Smash | `{W}` | **No** |
| Munkidori | Mind Bend | `{P}` | **No** |
| Marnie's Impidimp | Corkscrew Punch | `{D}` | Only at E≥1 |
| Marnie's Morgrem | Corkscrew Punch | `{D}{D}` | Only at E≥2 |
| Marnie's Grimmsnarl ex | Shadow Bullet | `{D}{D}` | Yes — 180 + 30 bench |

Froslass (Freezing Shroud) and Munkidori (Adrena-Brain) are **bench support** — their value is
an Ability that works from the bench. Parking them Active converts them from engine pieces
into wasted turns.

### Evidence per game

**91435775 (Alakazam)** — Snorunt Active at E0 for turns 1–6. First attack on turn 7, by
which point Alakazam had attacked four times.

**91436677 (Archaludon ex)** — attacked T3/T5/T7, then Impidimp-or-Snorunt at E0 in the Active
slot for T9–T14. Six consecutive turns, zero damage.

**91437814 (Iono's Bellibolt ex)** — **never attacked once in 14 turns.** Active progression:
Impidimp E0 → Morgrem E1 → Munkidori E1. Grimmsnarl never came online. Opponent won on
Voltorb attacks alone.

**91434875 (mirror)** — Snorunt/Froslass Active for turns 1–6; first attack T7 against their
T6. Lost the mirror race by roughly one turn.

**91427733 (mirror)** — see the worked example below.

---

## 5. Worked example: episode 91427733 (game 2, mirror, 0 prizes)

The clearest single instance, and the one with a provably available better line.

- **Turn 1 — setup, no agency.** Opening hand: Lillie's Determination ×2, Night Stretcher ×2,
  Rare Candy, Dawn, Morgrem. No basics to bench, no energy. The engine offered exactly one
  legal option: `END`. We benched nothing; the opponent benched five. This is a dead hand, not
  a decision.
- **Turn 8 — the lock.** Opponent played Boss's Orders and dragged our energy-less Munkidori
  into the Active spot, benching our powered Grimmsnarl ex. Munkidori cannot attack (`{P}`) and
  cannot retreat (retreat cost 1, zero energy attached).
- **Turn 9 — the miss.** We held a Basic {D} Energy and the engine offered
  `ATTACH → Active (inPlayArea 4, inPlayIndex 0)` as option 4. Attaching makes retreat legal,
  promoting the benched Grimmsnarl ex (already at E2) for Shadow Bullet 180. **Instead the
  agent played a second Munkidori to the bench and attached the energy to that one**, then
  ended the turn with no attack.
- **Turn 11** — genuinely stuck: no energy left in hand, no `ATTACH` option offered.

Net: 3 attacks in 7 turns. We chipped their Grimmsnarl ex to 30/320 but never converted a KO,
and took zero prizes.

---

## 6. Counterfactual: what the guardrails did

| Episode | Hero decisions | Guardrail overrides vs bare 5k | Live vs local mismatches |
|---|---|---|---|
| 91427733 | 90 | **0** | 0 |
| 91430333 | 97 | 1 | 0 |
| 91434875 | 82 | 2 | 0 |
| 91435775 | 59 | 1 | 0 |
| 91436677 | 56 | 1 | 0 |
| 91437814 | 49 | 1 | 0 |

**Every override was beneficial**, and none of them caused a loss:

- **Setup (`context 2`, three of the four recent losses):** the bare 5k model chose to bench
  **nothing**; the guardrail benched a basic instead.
- **91434875, T9:** base model chose `RETREAT`; guardrail chose `Shadow Bullet` (`attackId 937`).
- **91436677, T3:** base model chose to play a card; guardrail chose `Shadow Bullet`.

In episode 91427733 the guardrails **fired zero times** — the original 5k model plays that
game move-for-move identically. That game is a clean proof that the update did not cause it.

---

## 7. Conclusions

1. **The update is not the regression.** Guardrail overrides are rare (0–2 per game) and every
   observed one was an improvement. The worst loss in the sample had zero overrides.
2. **Mostly bad play, not bad luck.** Bad luck contributes — 91437814 had a poor draw made
   worse by Iono disruption, and 91427733 opened on a dead hand — but a 14-turn game with zero
   attacks is not variance, and the same pattern repeating across four distinct opponent
   archetypes rules out a matchup-specific explanation.
3. **The guardrails are aimed correctly but too narrowly.** The setup guardrail is already
   fixing the "bench nothing" failure; the productive-attack guardrail is already converting
   dawdle-turns into Shadow Bullets. Neither covers the mid-game Active-slot case.

---

## 8. Highest-value next guardrail

> **If the Active Pokémon has no legal attack and a benched Pokémon does, spend the turn
> fixing the Active slot** — attach to the Active to make retreat legal, retreat, and promote
> the attacker.

This is the same shape as the guardrails already shipped: a narrow, checkable precondition
with a deterministic remedy. It is directly observable in the `select` options (an Active with
no `ATTACK` option while a benched Pokémon is fuelled), and episode 91427733 turn 9 is a
concrete regression test — the correct action was legal and offered at option index 4.

Secondary, lower-confidence: avoid promoting Froslass/Snorunt/Munkidori to Active when a
Marnie's-line Pokémon is available, since their value is an Ability that works from the bench.

---

## 9. Caveats

- 15 games is a small sample, and per
  [PTCG ladder is not a measurement](.claude/memory), sub-1000 ladder results are not a
  reliable gate. Treat the *mechanism* identified here as the finding, not the win rate.
- Only one loss (91427733) was traced option-by-option; the other five were characterized from
  per-turn board state, attack logs, and the counterfactual diff.
- The "better line existed" claim at 91427733 T9 rests on the engine having offered the
  `ATTACH → Active` option and Munkidori's retreat cost being 1. It was not verified by
  forward-simulating the alternative through the engine.
