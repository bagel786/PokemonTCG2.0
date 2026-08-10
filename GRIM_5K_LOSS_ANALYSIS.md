# 5k Grimmsnarl — Consolidated Loss Analysis

**Date:** 2026-08-09
**Scope:** every submission shipping the exact original Grim deck that has local replays, plus
live submission 55389103.
**Supersedes:** `LOSS_PATTERN_REPORT_55389103.md` (folded in below; file removed 2026-08-10) and
`GRIM_5K_LOSS_BUCKET_SURVEY.md` (folded in below).

## Reproduce

```bash
python scripts/mine_grim_loss_buckets.py  --extra-games "55389103=artifacts/wave1_push/live/games/55389103.json"
python scripts/mine_grim_development.py   --extra-games "55389103=artifacts/wave1_push/live/games/55389103.json"
```

| Artifact | Contents |
|---|---|
| `artifacts/grim_loss_buckets/report.json` | per-episode bucket hits with turn + step anchors |
| `artifacts/grim_loss_buckets/development.json` | per-episode development trajectory metrics |
| `artifacts/grim_5k_history/manifest.partial.json` | submission/episode/deck inventory |

---

## 0. Bottom line

**The real lever is early board width converting into fuel — not search.**

Win rate as a function of Energy in play at turn 8 runs from **27.9% to 84.1%**. Search-fixable
mis-clicks, by contrast, appear in only **7–16% of losses**. The agent does not mainly lose by
choosing the wrong option at a decision; it loses by arriving at turn 8 with half a board.

| Lever | Addressable surface | Confidence |
|---|---|---|
| Early development → fuel | ~40-point win-rate spread | **High**, but partly correlational |
| B1 attack declined (1-ply) | 7% of losses | High, clean |
| B2b trapped Active (n-ply rule) | 8% of losses | High, clean |
| B4 bench-snipe KO | — | **Anti-correlated. Do not build.** |

---

## 1. Corpus

| | |
|---|---|
| Submissions | 13 |
| Games with local replays | 567 |
| Losses / wins | 258 / 309 |
| Hero turns analyzed | 3,660 |

55280582, 55283588, 55287852, 55303334, 55305247, 55307529, 55323436, 55323437, 55335500,
55358290, 55358291, 55370075, 55389103.

---

## 2. The real lever: development

All figures are hero-seat, across all 567 games.

### Win rate by Energy in play at turn 8 — the strongest single signal

| Energy at T8 | n | Win rate |
|---|---|---|
| 0–1 | 68 | **27.9%** |
| 2–3 | 123 | 39.0% |
| 4–5 | 131 | 52.7% |
| 6–7 | 201 | 67.7% |
| ≥8 | 44 | **84.1%** |

Monotonic across 567 games, 56-point spread. Shadow Bullet costs 2 Energy; each step is roughly
one more attacker you can keep online.

### Win rate by Energy at turn 6 and turn 4

| Energy at T6 | n | Win rate | | Energy at T4 | n | Win rate |
|---|---|---|---|---|---|---|
| 0–1 | 168 | 44.0% | | 0 | 92 | 44.6% |
| 2–3 | 159 | 49.7% | | 1 | 281 | 53.0% |
| 4–5 | 77 | 54.5% | | 2 | 109 | 57.8% |
| ≥6 | 163 | **69.9%** | | ≥3 | 85 | **65.9%** |

### Win rate by board width at turn 4 *(order-robust)*

| Bench at T4 | n | Win rate | | Marnie's bodies at T4 | n | Win rate |
|---|---|---|---|---|---|---|
| 0–1 | 48 | **37.5%** | | 0–1 | 131 | **40.5%** |
| 2 | 93 | 44.1% | | 2 | 176 | 55.1% |
| 3 | 132 | 55.3% | | 3 | 204 | **63.2%** |
| 4 | 150 | 52.7% | | ≥4 | 56 | 53.6% |
| ≥5 | 144 | **68.1%** | | | | |

Note the non-monotonicity: **3 Marnie's bodies at turn 4 is the sweet spot; 4+ is worse.**
Over-committing the Marnie's line gives the opponent extra prize fodder without adding fuel.

### Width and fuel compound — they are not the same variable

| | Energy at T8 ≤3 | Energy at T8 ≥4 |
|---|---|---|
| **Bench at T2 ≤1** | 34.4% (n=122) | 54.1% (n=183) |
| **Bench at T2 ≥2** | 36.2% (n=69) | **74.1%** (n=193) |

Early width does nothing on its own (34.4% vs 36.2% when fuel is absent), but it is worth
**+20 points** once fuel arrives. Fuel and bodies are complements: you need both.

### Engine-online timing

| First Grimmsnarl in play | n | Win rate | | First attack | n | Win rate |
|---|---|---|---|---|---|---|
| T1–4 | 93 | 65.6% | | T1–3 | 181 | 64.6% |
| T5–6 | 194 | 58.8% | | T4–5 | 153 | 56.9% |
| T7–8 | 164 | 55.5% | | T6–7 | 139 | 54.0% |
| ≥T9 | 80 | 40.0% | | ≥T8 | 78 | 37.2% |
| never | 36 | **30.6%** | | never | 16 | **6.2%** |

### Aggregate loss-vs-win medians

| Metric | Loss median | Win median | Loss mean | Win mean |
|---|---|---|---|---|
| Energy at T8 | 4 | **6** | 3.83 | 5.30 |
| Energy at T6 | 2 | **4** | 2.83 | 3.83 |
| Bench at T4 | 3 | 4 | 3.16 | 3.63 |
| First Grimmsnarl turn | 7 | 6 | 7.13 | 6.36 |
| First attacker online | 6 | 5 | 6.20 | 5.30 |
| Attacks made | 3 | 4 | 3.21 | 4.21 |
| Prizes taken | 2 | 5 | 2.42 | 4.12 |
| Prizes conceded | 5 | 2 | 4.56 | 2.25 |
| Game length (turns) | 13 | 12 | 13.30 | 12.37 |

Never got a Grimmsnarl into play at all: **10% of losses vs 4% of wins.**
Never attacked at all: **6% of losses vs 0.3% of wins.**

---

## 3. The loss buckets (search-addressable)

Detectors read only what the engine actually offered (`select.option`) plus public board state, so
a flagged turn is a situation the agent *could* have played differently. Depth tags:
**1-ply** = one legal option fixes it; **n-ply** = needs an action *sequence* within one turn;
**structural** = no legal remedy existed.

| Bucket | Depth | Loss turns | /turn | Win turns | /turn | Skew | Losses w/ ≥1 | Wins w/ ≥1 |
|---|---|---|---|---|---|---|---|---|
| B3 dead Active, no bench attacker | structural | 705 | 0.427 | 510 | 0.254 | 1.7× | 94% | 84% |
| B3 dead Active, stranded | structural | 38 | 0.023 | 46 | 0.023 | 1.0× | — | — |
| B1 attack offered, turn ended | **1-ply** | 25 | 0.0151 | 16 | 0.0080 | **1.9×** | 7% | 4% |
| B2b dead Active, attach would free | **n-ply (3)** | 25 | 0.0151 | 16 | 0.0080 | **1.9×** | 8% | 4% |
| B2a dead Active, retreat legal | **n-ply (2)** | 9 | 0.0054 | 9 | 0.0045 | 1.2× | 3% | 2% |
| B4 bench-snipe KO declined | 1-ply | 8 | 0.0048 | 19 | 0.0095 | **0.5×** | 3% | 6% |
| **B1 ∪ B2a ∪ B2b** | | | | | | | **16%** | **9%** |

### Late dead-Active is the loss signature — but it is a symptom

| Dead-Active turns | Turns ≤4 | Turns ≥7 | Late per game |
|---|---|---|---|
| Wins | 407 (73%) | 83 (15%) | **0.27** |
| Losses | 377 (51%) | 278 (37%) | **1.08** |

A dead Active on turns 1–4 is normal setup and is just as common in wins. On turn 7+ it is **4×**
more common in losses. But the overwhelming majority sit in `no_bench_attacker` — there was
nothing to retreat *to*. That is section 2's problem, surfacing late. No within-turn search fixes
it; the mistake happened several turns earlier.

### Per submission

| Submission | Games | W–L | B1 | B2a | B2b | Late-B3/game |
|---|---|---|---|---|---|---|
| 55280582 | 5 | 0–5 | 0 | 1 | 1 | 0.80 |
| 55283588 | 45 | 27–18 | 2 | 2 | 4 | 0.53 |
| 55287852 | 57 | 36–21 | 2 | 0 | 1 | **0.28** |
| 55303334 | 15 | 7–8 | 1 | 0 | 2 | 0.67 |
| 55305247 | 60 | 34–26 | 1 | 0 | 3 | 0.87 |
| 55307529 | 56 | 27–29 | 1 | 2 | 2 | 0.96 |
| 55323436 | 57 | 29–28 | 12 | 0 | 7 | 0.51 |
| 55323437 | 67 | 33–34 | 4 | 1 | 7 | 0.58 |
| 55335500 | 56 | 32–24 | 6 | 0 | 2 | 0.54 |
| 55358290 | 44 | 27–17 | 3 | 4 | 2 | 0.84 |
| 55358291 | 53 | 29–24 | 1 | 2 | 5 | 0.51 |
| 55370075 | 43 | 25–18 | 8 | 6 | 3 | 0.67 |
| 55389103 | 9 | 3–6 | 0 | 0 | 2 | **1.11** |

---

## 4. Worked example — episode 91427733 (55389103 game 2, mirror, 0 prizes)

The clearest single instance, with a provably available better line.

- **T1 — no agency.** Hand: Lillie's Determination ×2, Night Stretcher ×2, Rare Candy, Dawn,
  Morgrem. No basics, no Energy. Engine offered exactly one option: `END`. We benched nothing;
  the opponent benched five.
- **T8 — the lock.** Opponent's Boss's Orders dragged our Energy-less Munkidori into the Active
  spot, benching our powered Grimmsnarl ex. Munkidori cannot attack (`{P}` cost) and cannot
  retreat (cost 1, zero Energy attached).
- **T9 — the miss.** We held a Basic {D} Energy and the engine offered
  `ATTACH → Active (inPlayArea 4, inPlayIndex 0)` at option index 4. Attaching makes retreat
  legal → promote Grimmsnarl ex (already E2) → Shadow Bullet 180. **Instead the agent played a
  second Munkidori to the bench and attached the Energy to that one**, then ended the turn.
- **T11 —** genuinely stranded: no Energy in hand, no `ATTACH` offered.

3 attacks in 7 turns; chipped their Grimmsnarl ex to 30/320 without ever converting a KO.

### Why our Pokémon cannot attack

The deck runs **Basic {D} Energy only**:

| Pokémon | Attack | Cost | Attackable? |
|---|---|---|---|
| Snorunt | Chilly | `{W}` | **Never** |
| Froslass | Frost Smash | `{W}` | **Never** |
| Munkidori | Mind Bend | `{P}` | **Never** |
| Marnie's Impidimp | Corkscrew Punch | `{D}` | E≥1 |
| Marnie's Morgrem | Corkscrew Punch | `{D}{D}` | E≥2 |
| Marnie's Grimmsnarl ex | Shadow Bullet | `{D}{D}` | E≥2 — 180 + 30 bench |

Froslass (Freezing Shroud) and Munkidori (Adrena-Brain) are **bench support**; their value is an
Ability that works from the bench. Parking them Active converts engine pieces into dead turns.

### The four most recent 55389103 losses

| Episode | Opponent | Turns | Our attacks | Their attacks | Prizes |
|---|---|---|---|---|---|
| 91434875 | Grimmsnarl (mirror) | 12 | 3 | 3 | 2–5 |
| 91435775 | Alakazam / Dudunsparce | 12 | 2 | 6 | 2–5 |
| 91436677 | Archaludon ex | 14 | 3 | 7 | 2–5 |
| 91437814 | Iono's Bellibolt ex | 14 | **0** | 6 | 0–5 |

91437814 is the pure structural case: 14 turns, zero attacks, all seven hero turns flagged, never
a fuelled attacker anywhere on board.

---

## 5. The guardrail update is not the regression

Shipped agent vs bare 5k model, re-run on the recorded observations using the exact extracted
package. **Local reproduction matched the live action on 100% of decisions in all six games**, so
this counterfactual is exact.

| Episode | Hero decisions | Guardrail overrides | Live vs local mismatches |
|---|---|---|---|
| 91427733 | 90 | **0** | 0 |
| 91430333 | 97 | 1 | 0 |
| 91434875 | 82 | 2 | 0 |
| 91435775 | 59 | 1 | 0 |
| 91436677 | 56 | 1 | 0 |
| 91437814 | 49 | 1 | 0 |

Every override was beneficial:

- **Setup (`context 2`), 3 of the 4 recent losses:** the bare 5k model chose to bench
  **nothing**; the guardrail benched a basic.
- **91434875 T9:** base chose `RETREAT`; guardrail chose `Shadow Bullet`.
- **91436677 T3:** base chose to play a card; guardrail chose `Shadow Bullet`.

The worst game in the sample (91427733) had **zero** overrides — the original 5k model plays it
move-for-move identically.

**This matters for section 2:** the setup guardrail already benches a basic where the base model
benches none. That is precisely the lever the development data identifies. The direction is
right; the magnitude is too small.

---

## 6. Recommendations, in priority order

1. **Widen the setup/development guardrail — highest value.** Target **3 Marnie's bodies and ≥3
   bench by turn 4**, and treat Buddy-Buddy Poffin / Poké Pad / Spikemuth Gym as development
   tools to be spent early rather than held. The base model benches nothing at setup in a
   measurable share of games; the existing guardrail already corrects this and correlates with a
   17–30 point win-rate difference. Do **not** push past 3 Marnie's bodies — 4+ is worse.
2. **Protect fuel, not just bodies.** Energy at T8 is the strongest correlate in the corpus.
   Under-using Punk Up (up to 5 Basic {D} from deck on evolving into Grimmsnarl ex) is the
   likeliest mechanism and is worth measuring directly — it was **not** measured here.
3. **Build the 1-ply search for B1 only.** Scope: "if an `ATTACK` option is legal and the turn is
   about to end without attacking, take the attack." ~7% of losses, 1.9× skew, verifiable one
   step ahead — the property today's rejected search implementation lacked.
4. **Handle B2b as a rule, not a search.** Bigger bucket (8%) but invisible to 1-ply: attaching
   Energy to a Pokémon that cannot attack looks strictly bad one step ahead. Precondition: Active
   has no `ATTACK` option, a benched Marnie's Pokémon is fuelled, an `ATTACH → Active` option
   exists anywhere in the turn. Regression test: episode 91427733 T9.
5. **Do not build for B4.** Anti-correlated with losing.

**Calibration:** items 3 and 4 executed perfectly touch ~16% of losses and will not convert all
of them. Items 1 and 2 are where the win rate lives.

---

## 7. Caveats

- **Reverse causation.** `energy_at_t8` and `attacks` are partly *effects* of winning — a player
  ahead on board keeps more Pokémon and Energy alive. The early metrics (`bench_at_t4`,
  `marnies_at_t4`, `energy_at_t4`) are far more credibly causal, and their spreads are smaller
  (17–30 points, not 56). **Weight the early numbers when deciding what to build.**
- **`bench_at_t2` conflates play order.** Turn 2 is the hero's first turn when going second but
  the opponent's when going first, so the n=209 zero-bench bucket is inflated. The T4 metrics are
  order-robust; prefer them. Play order was not extracted in this pass.
- **Detectors are heuristic, not simulated.** B1 counts every declined attack as a candidate
  error; in some positions declining is correct. Treat bucket counts as **upper bounds** on the
  addressable surface.
- **B2b's core assumption is still unverified.** That attaching to a retreat-cost-1 Active makes
  retreat legal is read from card data and the offered option list, not confirmed by forward
  simulation. Recommendation 4 depends on it. **Settle this first.**
- **Deck identity ≠ model identity.** The corpus is selected by exact deck match; only 55323437,
  55358290 and 55358291 are hash-proven D842 lineage. This is "the 5k Grimmsnarl deck family."
- **Coverage is partial.** 567 of ~700 rated episodes have local replays; some downloads failed
  on HTTP 429. 55389103 contributes 9 replays, 55280582 only 5.
- **Ladder caveat stands.** Per the existing note, sub-1000 ladder results are not a reliable
  gate. Treat mechanisms as the finding, not win rates.
- **Weak prior evidence on search.** 55303334 shipped *"AFBC + Hardcoded 1-Ply Search"* and
  scored 677.4, second-worst in the corpus, with no better bucket rates than its peers. Only 15
  local replays, and its Elo drop was previously attributed to temperature sampling — an
  attribution never proven. Mentioned only because it is the one prior attempt at this idea.
- **Correlational throughout.** These metrics co-occur with winning; nothing here establishes
  that forcing them causes wins. That requires an offline gate.
