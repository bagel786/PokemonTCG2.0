# 5k Grimmsnarl Loss-Bucket Survey — Search-Addressable Failure Modes

**Question:** across all past 5k Grimmsnarl submissions, are there other loss buckets like the
Active-slot defect in [LOSS_PATTERN_REPORT_55389103.md](LOSS_PATTERN_REPORT_55389103.md), and
could a properly implemented 1-ply search fix them?

**Short answer:** yes, they exist and they are real — but they are **small**. A correct 1-ply
search cleanly addresses about **7% of losses**. Extending it to multi-action sequences within a
turn reaches about **16%**. The dominant loss signature is a board-development failure that no
amount of within-turn search can fix.

**Date:** 2026-08-09
**Miner:** [scripts/mine_grim_loss_buckets.py](scripts/mine_grim_loss_buckets.py)
**Raw output:** `artifacts/grim_loss_buckets/report.json`

---

## 1. Corpus

Every submission in `artifacts/grim_5k_history/manifest.partial.json` whose 60-card deck matches
the frozen original Grim list (`deck_class == exact_original_grim`), plus today's 55389103.

| | |
|---|---|
| Submissions | 13 |
| Games with local replays | 567 |
| Losses / wins | 258 / 309 |
| Hero turns analyzed | 3,660 |

Submissions covered: 55280582, 55283588, 55287852, 55303334, 55305247, 55307529, 55323436,
55323437, 55335500, 55358290, 55358291, 55370075, 55389103.

---

## 2. Method

Detectors read only what the engine actually offered at each decision (`select.option`) plus the
public board state. A flagged turn is therefore a situation the agent **could** have played
differently — not a hypothetical. Each bucket is tagged by the lookahead a search would need:

- **1-ply** — the remedy is a single legal option at the flagged decision.
- **n-ply** — the remedy is a *sequence* of main-phase actions in one turn (attach → retreat →
  attack). No single option improves the position on its own, so a one-step search cannot find it.
- **structural** — no legal remedy existed. Search cannot help.

Critical implementation note: the option list must be scanned across the **whole turn**, not at
the turn's final decision. The Energy that could have freed a trapped Active is already gone from
the option list by the time the agent ends the turn. Checking only the final decision
misclassified episode 91427733 turn 9 as unfixable; it is in fact fixable.

---

## 3. Results

### Rates per hero turn

| Bucket | Depth needed | Loss turns | /turn | Win turns | /turn | Loss skew |
|---|---|---|---|---|---|---|
| B3 dead Active, no bench attacker | structural | 705 | 0.427 | 510 | 0.254 | **1.7×** |
| B3 dead Active, stranded | structural | 38 | 0.023 | 46 | 0.023 | 1.0× |
| B1 attack offered, turn ended anyway | **1-ply** | 25 | 0.0151 | 16 | 0.0080 | **1.9×** |
| B2b dead Active, attach would free it | **n-ply** | 25 | 0.0151 | 16 | 0.0080 | **1.9×** |
| B2a dead Active, retreat was legal | **n-ply (2)** | 9 | 0.0054 | 9 | 0.0045 | 1.2× |
| B4 bench-snipe KO declined | **1-ply** | 8 | 0.0048 | 19 | 0.0095 | **0.5×** |

### Incidence per game

| Bucket | Losses with ≥1 | Wins with ≥1 |
|---|---|---|
| B3 (any dead Active) | 242/258 (94%) | 259/309 (84%) |
| B2b | 21/258 (8%) | 13/309 (4%) |
| B1 | 17/258 (7%) | 12/309 (4%) |
| B2a | 8/258 (3%) | 7/309 (2%) |
| B4 | 8/258 (3%) | 19/309 (6%) |
| **B1 ∪ B2a ∪ B2b (search-addressable)** | **40/258 (16%)** | **29/309 (9%)** |

---

## 4. The dominant signature is *late* dead Active — and search can't fix it

Splitting the big B3 bucket by turn number is what separates wins from losses:

| | Turns ≤4 | Turns ≥7 |
|---|---|---|
| **Wins** | 407 (73%) | 83 (15%) |
| **Losses** | 377 (51%) | 278 (37%) |

Per game, late (turn ≥7) dead-Active turns:

- **Losses: 1.08 per game**
- **Wins: 0.27 per game**
- **4× difference**

A dead Active on turns 1–4 is normal setup and appears in wins just as much. A dead Active on
turn 7+ is the loss signature. This is exactly the pattern found by hand in 55389103.

**But** the overwhelming majority of these turns fall in `B3_dead_active_no_bench_attacker` —
there was nothing on the bench to retreat *to*. That is a board-development and tempo failure
(Grimmsnarl never got online, or got knocked out and nothing replaced it), not a decision the
agent got wrong at that moment. Episode 91437814 is the pure case: 14 turns, zero attacks, all
seven hero turns flagged, never a fuelled attacker anywhere on board.

**No within-turn search fixes this.** The mistake, if there is one, happened several turns
earlier.

---

## 5. What a 1-ply search would actually buy

### B1 — attack offered, turn ended anyway *(genuinely 1-ply)*

The agent was offered an `ATTACK` option, took other actions, then chose `END` without attacking.
25 loss turns across 17 losses (7%). Loss skew 1.9×. This is the clean case: a one-step search
that scores each option against "does this take a prize / deal damage" finds the attack
immediately. **This is the bucket worth building for.**

### B2b — dead Active, attach would free it *(needs 3 actions, not 1)*

25 loss turns across 21 losses (8%). Loss skew 1.9× — the largest search-adjacent bucket. But
the remedy is `attach to Active → retreat → promote → attack`. **A naive 1-ply search will not
find this**, because attaching Energy to a Pokémon that cannot attack looks strictly bad one step
ahead. This needs either a within-turn sequence search or a hand-written rule of the shape
already shipped in the guardrails. Episode 91427733 turn 9 is the canonical instance.

### B2a — dead Active, retreat was legal *(2 actions)*

Only 9 loss turns, and **no loss skew** (9 in wins too). Low priority.

### B4 — Shadow Bullet bench snipe declining a KO *(genuinely 1-ply)*

**Do not chase this.** It occurs *more* in wins (19) than losses (8), rate 0.0095 vs 0.0048. The
obvious reading is that you only get to snipe when you are already attacking freely, i.e. already
winning. It is not a loss driver.

---

## 6. Weak evidence from a natural experiment

Submission **55303334** shipped *"AFBC + Hardcoded 1-Ply Search"* and scored **677.4** — the
second-worst in the corpus. Its search-addressable bucket rates are not better than its peers
(B1=1, B2a=0, B2b=2 over 15 games; late-B3 0.67/game against a corpus range of 0.28–1.11).

This is **weak** evidence and should not be over-read: only 15 local replays, and per
[the existing note on 55303334](.claude/memory), its Elo drop was attributed to temperature
sampling and that attribution was never proven. It is mentioned only because it is the one prior
attempt at this exact idea, and it did not visibly move these buckets.

---

## 7. Recommendation

1. **Build the 1-ply search for B1 only, as a narrow guardrail.** Scope it to: "if an `ATTACK`
   option is legal and the turn is about to end without attacking, take the attack." Addressable
   surface ~7% of losses with a 1.9× loss skew, and it is verifiable one step ahead — the exact
   property today's rejected search implementation lacked.
2. **Handle B2b as a rule, not a search.** It is the bigger bucket (8% of losses) but is
   structurally invisible to 1-ply. It is the same shape as the guardrails already shipped:
   narrow precondition (Active has no `ATTACK` option, a benched Marnie's Pokémon is fuelled, an
   `ATTACH → Active` option exists) with a deterministic remedy.
3. **Do not build for B4.** Anti-correlated with losing.
4. **The real lever is not search.** 94% of losses contain a dead-Active turn and the late-game
   version is 4× more common in losses, but almost all of it is "nothing on the bench could
   attack either." That is a board-development problem — getting and keeping a fuelled Grimmsnarl
   ex online. It sits upstream of any within-turn decision procedure, and it is where the win
   rate actually lives.

**Calibration:** even executing 1 and 2 perfectly touches ~16% of losses, and would not convert
all of them. This is a real but incremental gain, not a breakthrough.

---

## 8. Caveats

- **Deck identity ≠ model identity.** The corpus is selected by exact deck match. Only
  55323437, 55358290 and 55358291 are hash-proven D842 lineage. Other submissions ship the same
  deck but their policy identity is not proven, so this is "the 5k Grimmsnarl deck family," not a
  certified single-model population.
- **Detectors are heuristic, not simulated.** B1 counts every declined attack as a candidate
  error; in some positions declining is correct. None of these were verified by forward-simulating
  the alternative through the engine. Treat the counts as upper bounds on the addressable surface.
- **B2b assumes retreat becomes legal after attaching** to a retreat-cost-1 Active. Read from
  card data and the offered option list, not confirmed by engine simulation. This is the same
  unverified assumption flagged in the 55389103 report and it should be settled before either
  remedy is built.
- **Coverage is partial.** 567 of ~700 rated episodes have local replays; some downloads failed
  on HTTP 429. 55389103 contributes only 9 replays and 55280582 only 5.
- **Win/loss contrast is correlational.** These buckets co-occur with losing; the survey does not
  establish that fixing them causes wins.
