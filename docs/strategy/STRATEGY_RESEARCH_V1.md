# Pokémon TCG Strategic Research & Strategy Document — V1

**Deliverable:** §1 of the Opus 4.8 Plan (*Pokémon Strategic Game-Plan Reasoner*) — the Pokémon
research and strategy document that precedes the blind competency exam.
**Status:** DRAFT for user review. No implementation is authorized by this document.
**Author pass:** Opus, 2026-08-09.
**Authority:** The pinned competition engine (`cg/`, `engine/ptcgProgram/`) and its card metadata
(`freshstart/data/EN_Card_Data.csv`, 2,102 rows) are Tier‑1 and override everything below. Every
numeric claim in this document was read from that card CSV or the engine constants unless a Tier tag
says otherwise.

---

## 0. How to read this document

The plan's §1 asks for a strategy document that covers, for **both players**: win conditions,
milestones, resource prerequisites, attacker schedules, protected/expendable assets, opponent
counterplans, and prize routes — plus counterexamples showing why width, Energy, damage, prizes, HP,
or attacking each mislead **in isolation**, and an explicit separation of correlation from causation.

The map from plan section to this document:

| Plan §1 requirement | Where |
|---|---|
| Research-source hierarchy, per-claim tiering | §1 (this doc), and the `[Tier n]` tags throughout |
| Both players' win conditions & multi-turn plans | §4 (per archetype), §5 (Grimmsnarl deep-dive) |
| Milestones, resource prerequisites, attacker schedules | §4 tables, §5 |
| Protected vs expendable assets | §4 "assets" rows, §6.5 |
| Opponent counterplans | §4 "how it loses / counterplay", §7 |
| Prize routes (2→2→2 etc.) | §3.1, §4 prize-route rows, §5.4 |
| Counterexamples (width/energy/damage/prizes/HP/attacking misleading alone) | §6 |
| Correlation vs causation | §8 (register), and §5.3 |
| Decisive-turn annotations (curriculum) | §9 |
| Competency-exam readiness | §10 |

**A note on the curriculum literalism.** The plan's curriculum text ("study ≥40 expert-commentated
matches", "verifiably successful competitive players and coaches") is written in the vocabulary of
the *real-world* Pokémon TCG. This competition does **not** use the real card pool: cards such as
*Marnie's Grimmsnarl ex*, *Team Rocket's Mewtwo ex*, *Iono's Bellibolt ex*, and *Mega Lucario ex* are
specific to the pinned engine's set list (DRI/MEG/TWM/etc.), and there is no external commentary
corpus that plays *these* cards. The research-source hierarchy resolves this cleanly, and I have
followed it rather than the surface wording:

- **Tier 1 (engine + card metadata)** carries all mechanical truth — legality, damage, HP, costs,
  timing, ability text. Verified directly.
- **Tier 2 (official rules, general TCG mechanics)** supplies the *transferable* strategic
  invariants — prize math, weakness ×2, tempo, resource economy, "attacking ends your turn." These
  are format-independent and true in any Pokémon TCG.
- **Tier 3–4 (expert principles, deck stats)** are applied *only as transferable priors*: general
  Pokémon-TCG strategic doctrine (prize trading, don't over-extend into a snipe deck, protect your
  engine) mapped onto the engine's cards. Deck prevalence is a prior, not proof of a line.
- **Tier 5 (repository & high-rated replays)** is the *primary empirical* source for how these
  specific cards actually play out in this specific engine: the 567-game Grimmsnarl loss corpus, the
  4,669-episode top-rated daily export (2026-08-08), and the daily decision logs.
- **Tier 6 (community discussion)** — the `freshstart/TOP_PLAYERS.md` write-up of the "30,000 games"
  forum thread — hypothesis generation only.

So "40 matches / 100 decisive turns" is satisfied by structured annotation of the **replay corpus**
(§9), and every strategic claim carries a source tier and is falsifiable against the engine.

**A note on staleness.** `freshstart/META.md` is dated 2026-07-29 (11 days old at time of writing);
the leaderboard has since grown from 5,950 to **6,679 teams** and the top score has risen from 1190.9
to **1217.4** (`kaggle competitions leaderboard`, 2026-08-09). The archetype *mechanics* below are
Tier‑1 and do not drift; the archetype *shares* in §4 are refreshed from the 2026-08-08 top-rated
export (§4.0) and flagged as a Tier‑4 prior to be re-pulled before the exam.

---

## 1. Research-source hierarchy (instantiated)

Every strategic claim records `[Tier n]` and, where it matters, its evidence. Conflicts resolve
**down** the list toward Tier 1.

1. **Pinned engine & card metadata** — `engine/ptcgProgram/Core.h` (constants),
   `freshstart/data/EN_Card_Data.csv` (card behaviour), `cg/api.py` (types, search API). Sole
   authority for legality, damage, HP, cost, timing, weakness, and search transitions.
2. **Official rules / general TCG mechanics** — [rules link in `freshstart/COMPETITION.md`]. Prize
   math, ×2 weakness, turn structure. Transferable and format-independent.
3. **General competitive doctrine** — transferable principles (prize trading, engine protection,
   tempo, non-greedy sequencing) applied to engine cards; never a substitute for a Tier‑1 check.
4. **Deck prevalence & aggregate stats** — leaderboard CSVs, the 2026-08-08 top-rated export census
   (§4.0). Priors on *what you will face*, not proof a line is correct.
5. **Repository & high-rated replays** — 567-game Grim corpus (`GRIM_5K_LOSS_ANALYSIS.md`), daily
   decision logs (`data/daily_extracted/`), worked episodes (91427733 et al.). Primary empirical
   evidence for *this* engine.
6. **Community discussion** — `freshstart/TOP_PLAYERS.md`. Hypothesis only.

Mechanical conflicts resolve to the engine. Strategic disagreements stay explicit as alternative
hypotheses or acceptable-line equivalence sets (§9 uses this), never forced into false consensus.

---

## 2. Format fundamentals (Tier 1 — engine constants)

From `engine/ptcgProgram/Core.h` and `freshstart/COMPETITION.md`:

| Constant | Value |
|---|---|
| Deck size | 60 exactly |
| Copies of a card | ≤4 (Basic Energy exempt) |
| ACE SPEC | ≤1 per deck |
| Opening hand | 7 (mulligan if no Basic Pokémon) |
| Prize cards | 6 |
| Bench | 5 (→8 with a Tera Pokémon + Area Zero Underdepths) |
| Time budget | 600 s per agent per game |

**Turn structure (one turn):** draw → any number of Item / Ability / evolve / bench plays → **one**
Supporter → **one** Stadium → **one** manual Energy attach → **one** retreat → optionally **one
attack, which immediately ends the turn.** The first player cannot attack or play Rare Candy on
turn 1.

**Win conditions** (`LogType.RESULT.reason`): (1) take your last Prize; (2) opponent starts a turn
with an empty deck; (3) opponent has no Active after a KO; (4) a card effect wins.

**Prize values** — the scoreboard that matters: non-ex KO = **1** prize, Pokémon ex = **2**, Mega
Evolution ex = **3**. Six prizes ends the game.

**Weakness = ×2 damage** (not +30); Resistance subtracts; neither applies to Benched Pokémon.

These six facts constrain every plan below and are the backbone of the counterexamples in §6.

---

## 3. The axes that decide games

These are the load-bearing strategic invariants of the format. Each is Tier‑1 mechanically and
Tier‑2/3 in doctrine.

### 3.1 Prize math is the real scoreboard [Tier 1 mechanics / Tier 3 doctrine]

A KO is worth 1, 2, or 3 prizes depending on the target's rule box. A deck of Mega ex attackers
(Grimmsnarl, Lucario, Kangaskhan, Garchomp, Dragapult) **wins in 2–3 KOs but also loses in 2–3**; a
non-ex deck (Crustle, Dipplin, Alakazam, Passimian) needs 6 KOs but only concedes 6. The canonical
route signatures:

- **2→2→2** — the standard two-prize-ex plan: three KOs on ex bodies. Grimmsnarl's default.
- **3→3** or **3→2→1** — Mega-ex plans, fewer KOs but each concession is catastrophic.
- **1×6** — the grind plan (Dipplin/Crustle/Passimian): six single-prize trades, each cheap to give.

**Board evaluation that counts HP or bodies without weighting prize value misvalues every trade.**
This is the single most important lesson for the value model (see §6.4).

### 3.2 Effect immunity is a wall, not a modifier [Tier 1]

Nothing about HP predicts whether an attack *does anything*. Before evaluating damage, the target
must be checked against the immunity table. Verified against card text:

| Card / effect | Blanks |
|---|---|
| Repelling Veil (TR Articuno) | all *effects* of attacks on Basic TR Pokémon |
| Mysterious Rock Inn (Crustle) | all damage from **Pokémon ex** attacks |
| Cornerstone Stance (Cornerstone Ogerpon ex) | all damage from Pokémon **with an Ability** |
| Tera (Ogerpon ex, Dragapult ex) | all damage while **Benched** |
| Mist / Rock Fighting Energy | all *effects* of attacks on the holder |
| Battle Cage | damage **counters** on any Bench |
| Flower Curtain (Shaymin) | damage to non-rule-box Bench |

Decks that deal damage via **counters or effects** — Alakazam's Powerful Hand, Munkidori's
Adrena-Brain, Dragapult spread, Froslass's Shroud — hit **zero** through several of these. Attacks
whose text says "isn't affected by any effects on your opponent's Active" (Superb Scissors, Nebula
Beam, Metal Defender-class) are specifically built to cross the wall. A damage forecast that ignores
immunity is not merely miscalibrated; it is categorically wrong for those matchups.

### 3.3 Weakness is ×2 and decisive [Tier 1]

The field is a weakness rock-paper-scissors. Key edges verified from card data:

- **Grimmsnarl ex** (`{D}`, 320 HP) is **Grass-weak** → 160 Grass one-shots a full-health
  Grimmsnarl. The Grass attackers (Crustle, Dipplin, Teal Mask Ogerpon, Roserade) are played partly
  for this.
- **Alakazam** and **TR Mewtwo ex** (`{P}`) are **Dark-weak** → Grimmsnarl's Shadow Bullet (`{D}`,
  180) becomes **360** and instantly KOs. Grimmsnarl eats both.
- **Kangaskhan / Meowth** (`{C}`) are **Fighting-weak** → Mega Lucario ex (`{F}`) punishes them.
- **Mega Lucario ex** (`{F}`, 340 HP) is **Psychic-weak**; **Mega Kangaskhan** is Fighting-weak;
  Lillie's Clefairy ex can *rewrite* a Dark Pokémon's weakness to Psychic.

Weakness turns a two-shot into a one-shot, which changes the whole prize clock.

### 3.4 Hand size is both a resource and a liability [Tier 1]

- **Alakazam** turns your own hand size *into* damage (Powerful Hand = 2 counters × hand size).
- **Mega Froslass ex** turns the *opponent's* hand size into damage (50 × opponent hand).
- Xerosic's Machinations, Judge, Unfair Stamp, and Iono *attack* hand size.

Every card played is damage given up in one matchup and safety bought in another. There is no
universal "draw more = better."

### 3.5 The Stadium is a contested single slot [Tier 1]

Only one Stadium is in play; playing yours discards theirs. Spikemuth Gym *is* Grimmsnarl's
consistency engine; Festival Grounds *is* Dipplin's damage and tutor; Area Zero Underdepths *is* the
toolbox's 8-bench. Stadium denial is a cheap, real lever against three top archetypes.

### 3.6 Attacking ends your turn [Tier 1]

Every non-attack action — draw, bench, evolve, attach, Abilities — must happen **before** the
attack or not at all. With Powerful Hand, Erasure Ball, Do the Wave, and Coordinated Throwing, the
pre-attack actions also change *how much* the attack does. This is why "one complete-turn policy," not
"one action," is the correct unit of planning (and the plan's search horizon is completed turns).

---

## 4. Archetype strategic profiles

Each profile gives, per the plan: **win condition, milestones, resource prerequisites, attacker
schedule, protected/expendable assets, opponent counterplans (both against it and its own
counterplay), and prize route.** All card numbers Tier‑1 verified.

### 4.0 Current meta shares [Tier 4 — refreshed 2026-08-08 top-rated export]

Fresh census: **1,400 sampled episodes / 2,800 seat-decks** from the 2026-08-08 top-rated daily
export (`kaggle/pokemon-tcg-ai-battle-episodes-2026-08-08`, 4,669 episodes total), classified with the
repo's own signature classifier (`ptcg_ai.archetypes` + `freshstart/decklists`, ≥0.55 multiset
overlap). This **materially updates** the 11-day-old `freshstart/META.md` snapshot.

| Share (2026-08-08) | 2026-07-29 | Archetype | Type / prize | In-sample WR |
|---|---|---|---|---|
| **30.9%** | ~54% | Marnie's Grimmsnarl ex | Dark, weak Grass; 2-prize | **46.9%** |
| **18.4%** | 10% | Alakazam / Dudunsparce | Psychic, weak Dark; **1-prize** | 50.0% |
| **14.8%** | 2% | Mega Lopunny ex | Colorless pivot; 3-prize Mega | 49.2% |
| 10.2% | — | *other / unclassified* | — | 53.1% |
| 7.5% | 4% | Dragapult ex | Tera spread; 2-prize | **58.1%** |
| 6.0% | 8% | Kangaskhan / Crustle | lock / 3-prize Mega | 48.5% |
| 3.5% | 2% | Teal Mask Ogerpon toolbox | all-Basic; 2-prize | 39.4% |
| 3.3% | 2% | Mega Lucario ex (variant 2) | Fighting, weak Psychic; 3-prize Mega | **58.1%** |
| 3.1% | 2% | Dipplin / Thwackey | Grass; **1-prize** | **58.1%** |
| 1.0% | 4% | Cynthia's Garchomp ex | weak Grass; 2-prize | 44.4% |
| **0.7%** | **14%** | Team Rocket's Mewtwo ex | Psychic, weak Dark; 2-prize | 45.0% |

**What changed, and why it matters strategically:**

1. **Grimmsnarl fell from ~54% to ~31% and now wins *below 50%* among top agents (46.9%).** It is
   *still the single most common deck* and it is the deck the frozen baseline ships — a most-common,
   under-performing archetype is exactly where reasoning improvement has the most leverage. This
   *strengthens* the plan's choice of Grimmsnarl as first validation target.
2. **Mega Lopunny ex exploded from 2% to ~15%** — a one-Energy Bench→Active pivot deck (§4.7) is now a
   top-3 matchup and must be modelled seriously (its 230-for-one-Energy swing and rotation tech).
3. **Alakazam rose to ~18%** — the 1-prize hand-size combo is now the **#2** deck; the Dark-weakness
   edge Grimmsnarl holds over it (§3.3) is now a higher-value edge than before.
4. **Team Rocket's Mewtwo collapsed from 14% to <1%.** The §4.2 profile is retained for completeness
   but Mewtwo is no longer a priority matchup. (Dark weakness may have made it prey once Grimmsnarl
   saturated; it has largely left the top.)
5. **Dragapult, Mega Lucario v2, and Dipplin are the high-win-rate tail (58%)** — smaller shares but
   over-performing; the spread/immunity-crossing/1-prize-grind plans are working against the field.

**Caveats [Tier 4].** (a) This is a *top-rated episode* export, so it oversamples decks that strong
agents play and that appear in many rated games; in-sample win rates cluster near 50% by construction
(these decks mostly play each other) and are **not** ladder win rates. (b) The 10.2% "other" bucket is
decks below the 0.55-overlap threshold — some are genuinely novel lists, some are stale-signature
misses; the classifier's signatures are from `freshstart/decklists` and should be refreshed. (c) Shares
are a **Tier‑4 prior on what you will face**, not proof of what beats what — re-pull before the exam.
Priority matchups by this census: **Grimmsnarl mirror, Alakazam, Mega Lopunny**, then the Dragapult/
Lucario/Dipplin over-performing tail.

### 4.1 Marnie's Grimmsnarl ex — the first validation target

- **Win condition [Tier 1].** Evolve Impidimp → Morgrem → **Marnie's Grimmsnarl ex** (320 HP, `{D}`,
  weak `{G}`, retreat 2). On evolving, **Punk Up** searches up to **5 Basic `{D}` Energy** from deck
  and attaches them anywhere on your Marnie's Pokémon — erasing the attachment bottleneck. Then
  **Shadow Bullet** (`{D}{D}`, **180 + 30 to a benched Pokémon**) every turn from a 320 HP body. 180
  two-shots almost everything; the 30 chip sets up later one-shots.
- **Milestones.** (1) ≥2 Marnie's basics benched by ~T2–3; (2) 3 Marnie's bodies + ≥3 bench by T4
  (the empirical sweet spot — §5.3); (3) first Grimmsnarl online T5–6 or earlier; (4) Punk Up fired
  with full 5-Energy value; (5) Shadow Bullet online and *stays* online (fuel protected).
- **Resource prerequisites.** Basic `{D}` Energy only (card 7). Spikemuth Gym (search a Marnie's
  Pokémon every turn), Rare Candy (skip Morgrem), Buddy-Buddy Poffin (fetch the 70 HP Impidimp),
  Lillie's Determination (draw 6), Team Rocket's Petrel (fetch any Trainer).
- **Attacker schedule.** Shadow Bullet is a **repeatable** every-turn attack (no cooldown) once
  fuelled — the deck's tempo strength. Impidimp/Morgrem can chip early (Corkscrew Punch) but the real
  clock starts when Grimmsnarl attacks.
- **Protected assets:** the *fuelled* Grimmsnarl (its Energy, not just the body); the Munkidori/
  Froslass **bench engine** (their value is Abilities *from the bench* — parking them Active is a dead
  turn, §5.2). **Expendable:** early Impidimp/Morgrem bodies once the line is up; a 3rd/4th Marnie's
  body beyond the T4 sweet spot is *prize liability*, not fuel (§6.1).
- **Reach package [Tier 1].** 4× **Munkidori** (110 HP, `{P}`; Adrena-Brain: move up to 3 damage
  counters from your Pokémon to theirs — a heal *and* +30 reach for a KO); 2× **Froslass** (90 HP,
  `{W}`; Freezing Shroud: each Checkup, a damage counter on every Pokémon *with an Ability*).
- **Prize route:** **2→2→2** (three KOs on ex bodies), with Munkidori/Froslass chip converting a
  two-shot into a one-turn KO to compress the clock.
- **How it loses / opponent counterplay [Tier 1 + Tier 5].** (a) **Grass weakness** — 160 Grass
  one-shots. (b) Punk Up fires **only on the evolution**, so pressuring the fragile Impidimp/Morgrem
  turns, or stripping Rare Candy, delays the whole deck. (c) It's a 2-prize ex — three KOs is the
  game. (d) **Boss's Orders / Gust** dragging the Energy-less Munkidori Active while the fuelled
  Grimmsnarl is benched is the archetype's signature loss (episode 91427733 — §5, §9). (e) Empirically
  (§5.3) it loses far more often by **arriving at T8 with half a board** than by any single misclick.

### 4.2 Team Rocket's Mewtwo ex — was 14%, now <1% (§4.0); retained for completeness

- **Win condition [Tier 1].** **Erasure Ball** (`{P}{P}●`, **160 + 60 per Energy discarded from your
  Bench**, up to 280) off a 280 HP Basic (no evolution line to disrupt).
- **Defining constraint [Tier 1].** **Power Saver** — Mewtwo ex **cannot attack unless you have ≥4
  Team Rocket's Pokémon in play.** The whole deck floods a wide TR board fast (Tarountula/Spidops/
  Mimikyu/Articuno).
- **Resource engine.** Spidops `Charging Up` attaches a Basic Energy **from discard** each turn;
  combined with Erasure Ball's discard cost, energy is effectively infinite.
- **Its real weapon is denial.** `Repelling Veil` (Articuno) blanks all *effects* on Basic TR
  Pokémon; `Gemstone Mimicry` (Mimikyu) steals the opponent's Active Tera Pokémon's attack.
- **Protected assets:** the ≥4 TR-Pokémon count (Power Saver's gate) and Articuno. **Expendable:**
  individual small TR bodies once the count is safely above 4.
- **Prize route:** 2→2→2 off a single Basic attacker.
- **How it loses [Tier 1].** **Dark weakness** on Mewtwo — Grimmsnarl's Shadow Bullet ×2 = 360,
  instant KO. Kill or strand TR Pokémon early and Power Saver locks the attacker off (the count is
  the asset to attack).

### 4.3 Alakazam / Dudunsparce — now ~18% (#2 deck, §4.0), a 1-prize combo deck

- **Win condition [Tier 1].** **Powerful Hand** (`{P}`) — *place 2 damage counters on the opponent's
  Active for each card in your hand.* That is **20 × hand size**, uncapped, off a **1-prize** 140 HP
  Stage-2. A 14-card hand = 280 = one-shots almost anything, for a single Energy.
- **Milestones/resources.** Stage-2 Alakazam online **and** a large hand **in the same turn**.
  Everything grows the hand: Psychic Draw on Kadabra (+2) and Alakazam (+3 on evolve), Dudunsparce
  `Run Away Draw` (+3, reusable), Hilda/Dawn tutors, Telepath Psychic Energy.
- **Protected asset:** hand size itself (it *is* the damage stat). **Expendable:** almost nothing —
  the deck is fragile.
- **Prize route:** **1×6** — six one-prize KOs; but each is a full-power Powerful Hand.
- **How it loses [Tier 1].** Powerful Hand places **damage counters = an effect**, so Repelling Veil,
  Battle Cage, Mist/Rock Energy shut it **off completely** (§3.2). **Dark weakness** makes the
  Grimmsnarl matchup brutal. Anything that empties the hand or forces the attack early costs damage
  proportionally.

### 4.4 Mega Kangaskhan ex — 10%, two opposite builds

- **Ogerpon toolbox (2%)** — all-Basic, nine attackers, 8-wide bench via Area Zero Underdepths;
  Latias ex `Skyliner` gives all Basics zero retreat. **The deck's strength *is* decision quality**
  — no scripted line; choosing the right attacker/target each turn is the whole game. Attackers
  include Mega Kangaskhan ex (`Rapid-Fire Combo` 200 + 50/heads), Raging Bolt ex (burst finisher),
  Lillie's Clefairy ex (rewrites Dark weakness → an explicit Grimmsnarl answer). **Loses** because
  almost every body is a 2-prize ex and Kangaskhan is a 3-prize Mega — six prizes in 2–3 KOs;
  Fighting weakness.
- **Crustle lock (8%)** — a **prison deck**: Crustle (`Mysterious Rock Inn`: prevent all damage from
  Pokémon **ex** attacks) simply cannot be attacked by the all-ex Mega decks; `Superb Scissors` (120,
  *ignores all effects on their Active*) punches through protection. Plus Cornerstone Ogerpon, Mist/
  Spiky Energy, Battle Cage. **Plan:** make the opponent's damage *illegal*, win at 120/turn trading
  1-for-2. **Loses** to anything **non-ex, Fire-typed, or effect-independent** — those go straight
  through the wall.

### 4.5 Cynthia's Garchomp ex — 4%

- **Win condition [Tier 1].** Gible → Gabite → **Garchomp ex** (330 HP) + 3× Cynthia's Power Weight
  (+70 HP = 400 HP). `Draconic Buster` (`{F}{F}`) hits **260**; Roserade's Cheer On to Glory (+30)
  makes it **290** — one-shots every ex.
- **Defining tension [Tier 1].** Draconic Buster **discards all Energy** from Garchomp → cannot
  attack on consecutive turns without rebuilding. `Corkscrew Dive` (`{F}`, 100 + draw 6) is the filler
  turn. Every rebuild turn is a **free turn** for the opponent — the attacker schedule is *every other
  turn*, a key difference from Grimmsnarl's every-turn clock.
- **Consistency:** Gabite `Champion's Call` searches a Cynthia's Pokémon every turn for free.
- **Prize route:** 2→2→2 but slower (rebuild turns). **Loses** to Grass weakness on both halves and
  to any tempo that punishes the rebuild turn.

### 4.6 Dragapult ex — 4%

- **Win condition [Tier 1].** Dreepy → Drakloak → **Dragapult ex** (320 HP, Tera). `Phantom Dive`
  (`{R}{P}`, **200 to Active + 6 damage counters spread on their Bench**). Spread sets up multi-prize
  turns no single-target deck answers; Tera = **zero damage while benched** (waits safely).
- **Denial half:** 4× Crushing Hammer (coin-flip Energy discard), Budew (`Itchy Pollen`: opponent
  can't play Items next turn), Jamming Tower (Tools off), Judge/Unfair Stamp; 2× Munkidori converts
  spread into KOs.
- **Prize route:** multi-prize spread turns (e.g. 2 + a benched 1 in one turn). **Loses** if its one
  attacker/one-Energy line is denied (Crushing Hammer against *it*), and spread counters are an
  *effect* (Battle Cage / Flower Curtain blank the bench half).

### 4.7 The one-Energy & pivot decks (Mega Lopunny now ~15%, a top-3 matchup — §4.0)

- **Mega Lucario ex** (340 HP, `{F}`, weak `{P}`, retreat 2) [Tier 1]. **Aura Jab** (`{F}`, **130** +
  attach up to 3 Basic `{F}` from **discard** to your Bench — builds fuel while attacking). **Mega
  Brave** (`{F}{F}`, **270**, then *can't use Mega Brave next turn*) — an **every-other-turn 270
  nuke**. A 3-prize Mega. Support basics (Solrock, Lunatone, Makuhita/Hariyama) are **engine/expendable**
  — Solrock is a fetch/support body, *not* a win condition. This deck is the plan's Mega-Lucario
  scenario: **KOing an irrelevant Solrock vs investing damage into the central attacker** (§9).
- **Mega Lopunny ex** (330 HP): `Gale Thrust` `{C}` for 60, **+170 if it moved from Bench to Active
  this turn** = 230/turn for one Energy. Pure rotation tech (Air Balloon, Switch, Dunsparce).
- **Mega Starmie ex** (330 HP): `Jetting Blow` `{W}` 120 + 50 bench; `Nebula Beam` 210 ignoring
  Weakness/Resistance/effects. Partner **Mega Froslass ex** (310 HP): `Resentful Refrain` `{W}` =
  **50 × opponent hand size** — 400–500 vs draw-engine decks (Alakazam, Grimmsnarl, Garchomp).
- **Iono's Bellibolt ex** (280 HP, `{L}`, weak `{F}`) [Tier 1]. `Electric Streamer`: attach a Basic
  `{L}` from hand to an Iono's Pokémon **as often as you like** each turn (uncapped acceleration);
  `Thunderous Bolt` (`{L}{L}{L}●`, **230**, then can't attack next turn) — another every-other-turn
  attacker. Appears in the recent Grim loss corpus (episode 91437814, §5.4).

---

## 5. Grimmsnarl deep-dive (first validation target)

Grimmsnarl is the plan's first validation archetype and the deck the frozen baseline (`55389103`
d842-plus-rails) ships. This section is grounded almost entirely in **Tier 5** (the 567-game corpus,
`GRIM_5K_LOSS_ANALYSIS.md`) and Tier‑1 card data.

### 5.1 The plan, stated as an interaction

`develop 3 Marnie's bodies + fuel → evolve into Grimmsnarl (Punk Up: 5 {D} from deck) → Shadow Bullet
180+30 every turn → Munkidori/Froslass chip converts the next KO from two-shot to one-shot → 2→2→2`.

The causal spine is **width → fuel → a Grimmsnarl that stays online → repeatable 180**. Break any
link and the clock stalls.

### 5.2 Why the bench engine must stay benched [Tier 1]

The deck runs **Basic `{D}` Energy only**. Consequences (verified against attack costs):

| Pokémon | Attack | Cost | Can attack? |
|---|---|---|---|
| Snorunt | Chilly | `{W}` | **Never** |
| Froslass | Frost Smash | `{W}` | **Never** |
| Munkidori | Mind Bend | `{P}` | **Never** |
| Marnie's Impidimp | Corkscrew Punch | `{D}` | E≥1 |
| Marnie's Morgrem | Corkscrew Punch | `{D}{D}` | E≥2 |
| Marnie's Grimmsnarl ex | Shadow Bullet | `{D}{D}` | E≥2 → 180 + 30 bench |

Froslass and Munkidori are **bench-Ability engines**. Parking either in the Active spot — or attaching
`{D}` to one — converts an engine piece into a dead turn. This is the mechanism behind the signature
loss (§5.4) and behind loss bucket **B2b** (§5.3).

### 5.3 What actually decides Grim games — correlation vs causation [Tier 5]

From the 567-game corpus (258 losses / 309 wins, 3,660 hero turns). **The real lever is early board
width converting into fuel — not search.**

**Development → win-rate (the strongest single signal):**

| Energy in play at T8 | n | Win rate |
|---|---|---|
| 0–1 | 68 | **27.9%** |
| 2–3 | 123 | 39.0% |
| 4–5 | 131 | 52.7% |
| 6–7 | 201 | 67.7% |
| ≥8 | 44 | **84.1%** |

**Order-robust early metrics** (the ones to trust — see causation note):

| Marnie's bodies at T4 | n | Win rate |
|---|---|---|
| 0–1 | 131 | 40.5% |
| 2 | 176 | 55.1% |
| **3** | 204 | **63.2%** |
| ≥4 | 56 | 53.6% |

**3 Marnie's bodies at T4 is the sweet spot; 4+ is worse** — over-committing the Marnie's line hands
the opponent prize fodder without adding fuel (a direct §6.1 counterexample). Width and fuel are
**complements, not the same variable**: early bench width does *nothing* on its own (34.4% vs 36.2%
win when fuel is absent) but is worth **+20 points** once fuel arrives (74.1% with both).

**Correlation vs causation — the discipline this section exists to enforce:**

- `energy_at_t8` and `attacks_made` are **partly effects of winning** (a player ahead keeps more
  Pokémon and Energy alive). Their 56-point spread is inflated by reverse causation.
- The **early** metrics (`bench_at_t4`, `marnies_at_t4`, `energy_at_t4`) are far more credibly
  causal, with **smaller** spreads (17–30 points). **Weight the early numbers when deciding what to
  build.** (`GRIM_5K_LOSS_ANALYSIS.md` §7.)
- `bench_at_t2` conflates play order (T2 is hero's first turn when going second, opponent's when
  going first) — prefer the T4 order-robust metrics.

**Search-addressable loss buckets** (detectors read only what the engine offered, so a flag is a
situation the agent *could* have played differently — treat counts as **upper bounds**):

| Bucket | Depth | Losses w/ ≥1 | Skew vs wins | Verdict |
|---|---|---|---|---|
| B1 attack offered, turn ended | **1-ply** | 7% | 1.9× | Clean, buildable as a rule |
| B2b dead Active, attach would free retreat | **n-ply (3)** | 8% | 1.9× | Buildable as a rule; **core assumption unverified** |
| B2a dead Active, retreat legal | n-ply (2) | 3% | 1.2× | Marginal |
| B4 bench-snipe KO declined | 1-ply | 3% | **0.5×** | **Anti-correlated — do NOT build** |
| B1 ∪ B2a ∪ B2b | | **16%** | | Full search-addressable surface |

**Bottom line for the reasoner:** the win rate lives in **development (arrive at T8 with a full
board and fuel)**, which is a *plan-quality* problem, not a within-turn search problem. Search
addresses ~16% of losses at most, and one candidate bucket (B4, bench-snipe) is *anti-correlated*
with winning — a direct warning against a damage-greedy value head (§6.3).

### 5.4 The signature loss — episode 91427733 (worked) [Tier 5 + Tier 1]

The clearest single instance with a provably better line (mirror, 0 prizes taken, 3 attacks in 7
turns, chipped their Grimmsnarl to 30/320 without a KO):

- **T1 — no agency.** Hand had no basics and no Energy; engine offered only `END`. Benched nothing
  while opponent benched five. (Setup variance — not a decision error, but the hole the whole game
  falls into.)
- **T8 — the lock.** Opponent's **Boss's Orders** dragged our **Energy-less Munkidori** Active,
  benching our fuelled Grimmsnarl. Munkidori can't attack (`{P}` cost, no `{P}` in deck) and can't
  retreat (cost 1, zero Energy attached).
- **T9 — the miss.** We held a Basic `{D}` Energy; the engine offered `ATTACH → Active`. Attaching
  makes retreat legal → promote Grimmsnarl (already E2) → Shadow Bullet 180. **Instead the agent
  benched a second Munkidori and attached the Energy to it**, then ended the turn. This is loss bucket
  **B2b**, and this episode is its regression test.
- **Update [Tier 1, now certified]:** the retreat-legality half of this line is **engine-verified** —
  forking the recorded T9 observation and applying `ATTACH {D}→Active` makes RETREAT appear in the
  legal option set where it was absent (reproduced at steps 139 and 140; see
  `CERTIFICATION_91427733_B2b.md`). The full promote→Shadow-Bullet tail is not yet cleanly reproduced
  in the determinized-fork harness and must be completed in the runtime-proof harness before B2b is
  used as a correction target.

**The four most recent 55389103 losses** show the pattern is not mirror-specific:

| Episode | Opponent | Our attacks | Their attacks | Prizes |
|---|---|---|---|---|
| 91434875 | Grimmsnarl (mirror) | 3 | 3 | 2–5 |
| 91435775 | Alakazam / Dudunsparce | 2 | 6 | 2–5 |
| 91436677 | Archaludon ex | 3 | 7 | 2–5 |
| 91437814 | Iono's Bellibolt ex | **0** | 6 | **0–5** |

91437814 is the pure structural case: 14 turns, **zero** attacks, never a fuelled attacker anywhere —
§5.3's development failure surfacing as a shutout.

### 5.5 The frozen baseline behaves correctly at the margin, too small in magnitude [Tier 5]

Re-running the shipped agent vs the bare 5k model on recorded observations reproduced the live action
on **100% of decisions across six games** (an exact counterfactual). Every guardrail override was
**beneficial** (benched a basic at setup where the base model benched none; chose Shadow Bullet where
the base chose Retreat or a card play). The **direction is right; the magnitude is too small** — the
setup guardrail already nudges toward the §5.3 lever but not hard enough. This is important context for
the postmortem (§2.2 of the plan): the baseline is not broken so much as *under-developed*.

---

## 6. Counterexamples — why each single signal misleads in isolation

The plan explicitly requires these. Each is a case where optimizing the named quantity **alone**
loses. All are Tier‑1 mechanically; the Grim ones are Tier‑5 empirically grounded.

### 6.1 Board **width** without fuel is worthless — and 4+ Marnie's bodies is *negative*

§5.3: early bench width moves win rate by ~0 when fuel is absent (34.4% vs 36.2%). And **3 Marnie's
bodies at T4 beats 4+** (63.2% vs 53.6%) — the 4th body is prize fodder for a 2-prize-ex opponent, not
fuel. A reasoner that rewards "bodies in play" walks straight into this. *Width matters only when it
converts to fuel and readiness.*

### 6.2 **Energy** in play is partly an *effect* of winning, not only a cause

§5.3 / §7: `energy_at_t8`'s 56-point spread is inflated by reverse causation — the winning player
keeps Energy alive. Treating the raw late-Energy correlation as a build target over-credits it; the
causal signal is the *early* attach cadence (17–30 point spread). A value model trained on late-state
Energy will learn to predict the scoreboard, not to *cause* the win.

### 6.3 **Damage** dealt / KOs taken greedily can be anti-correlated with winning

The **B4 bench-snipe KO** bucket is **anti-correlated with losing** (0.5× skew): games where the
agent took the offered bench snipe *won less*. Taking the immediately-available KO/most-damage line
can spend tempo on the wrong target (an expendable body) instead of developing or hitting the central
attacker. This is the mechanism the plan's **Mega Lucario scenario** dramatizes — see §6.6.

### 6.4 **Prizes** taken, counted without prize *value*, misvalues every trade

§3.1: a KO is 1/2/3 prizes by rule box. "We're ahead, we've taken 3 to their 2" is meaningless
without knowing *which* bodies. Trading a 3-prize Mega KO to take a 1-prize non-ex is losing the race
by two prizes while "being ahead on KOs." Any evaluation that counts prizes or KOs as scalars without
the rule-box weighting is wrong (Crustle/Dipplin exist precisely to exploit this).

### 6.5 **HP** predicts nothing about whether your attack *does anything*

§3.2: against Crustle's Mysterious Rock Inn, Cornerstone Ogerpon, Repelling Veil, Battle Cage, or a
benched Tera, a full-damage attack does **zero**. HP-based board evaluation rates a Crustle at "150 HP,
easy KO" when it is in fact *unkillable by your ex attackers*. Effect immunity is a wall, not a
number.

### 6.6 **Attacking** (and attacking the biggest/nearest target) can be the losing move

§3.6 + §6.3. Two forms: (a) attacking when you should **develop or pass** (the deck that skips a setup
turn to chip for 30 often arrives at T8 with half a board — §5.3); (b) attacking the **wrong** target
— the **Mega Lucario scenario**: KOing an *irrelevant Solrock* (a 1-prize engine body) for immediate
tempo, versus **investing 130–270 into the central Lucario attacker** to force a heal/retreat, disrupt
its every-other-turn Mega Brave schedule, and change the prize route. The immediate KO scores on the
scoreboard *now*; the damage investment changes *both game plans*. A reasoner that maximizes
immediate prizes/damage takes the Solrock every time and loses the race.

**Synthesis:** every one of width, Energy, damage, prizes, HP, and attacking is a *component of
evidence*, valid only inside the interaction between the two game plans — never a standalone score to
maximize. This is the core justification for the plan's interaction-first architecture over
independently-weighted prediction heads.

---

## 7. Opponent counterplans — the denial/disruption layer

Beyond each deck's own plan, the format has a cross-cutting **disruption toolkit** every plan must
survive. Consolidated so the reasoner models the opponent's *counter*-plan, not just its clock:

| Lever | Cards | What it attacks | Who it hurts most |
|---|---|---|---|
| **Gust / drag** | Boss's Orders, Prime Catcher | pulls your bench engine/liability Active | Grimmsnarl (Munkidori lock, §5.4) |
| **Energy denial** | Crushing Hammer, Enhanced Hammer | strips the one-Energy line | Dragapult, one-Energy decks, Garchomp rebuild |
| **Hand disruption** | Iono, Judge, Unfair Stamp, Xerosic | shrinks/​resets hand | Alakazam (hand = damage), any combo turn |
| **Effect immunity** | Repelling Veil, Rock Inn, Cornerstone, Battle Cage, Mist | blanks counter/effect damage | Alakazam, Munkidori, Dragapult spread, Froslass |
| **Stadium denial** | play-over any Stadium | turns off engine/damage/bench | Grimmsnarl (Spikemuth), Dipplin (Festival), toolbox (Area Zero) |
| **Weakness exploit** | Grass vs Dark, Dark vs Psychic, etc. | doubles damage | whoever is on the wrong side (§3.3) |

The plan's opponent-plan model (a posterior over multi-turn plans: race / develop / deny / trap / heal
/ closer) must include these as *intents*, and observed actions update the posterior without being
treated as proof of the underlying plan.

---

## 8. Correlation-vs-causation register

Explicit list of "looks causal, is partly/entirely correlational" traps, so the benchmark and value
model don't bake them in. [Tier 5 unless noted.]

| Signal | Naïve reading | Reality | Handling |
|---|---|---|---|
| Energy at T8 | "attach more late" | partly an *effect* of already winning | weight early attach cadence instead (§6.2) |
| Attacks made | "attack more" | winners get more turns to attack | count *productive* attacks, not raw count |
| Prizes taken | "take prizes fast" | ignores rule-box value | weight by 1/2/3 prize class (§6.4) |
| Bench width | "go wide" | worthless without fuel; 4+ Marnie's is negative | reward width only conditional on fuel (§6.1) |
| Board HP total | "more HP = safer" | zero vs effect-immunity walls | check immunity before valuing (§6.5) |
| Bench-snipe KO | "free damage is good" | anti-correlated with winning (B4) | do not reward greedy snipe (§6.3) |
| `bench_at_t2` | order-neutral metric | conflates play order | use T4 order-robust metrics |
| Deck prevalence | "beat the popular deck" | prior on *frequency*, not on *what beats it* | Tier‑4 prior only (§4.0) |

**Method commitment [Tier 3 doctrine].** Wherever this document or the benchmark uses a
state-feature → outcome correlation, it must be either (a) an *early* order-robust metric with a
plausible causal story, or (b) validated by a **matched-world counterfactual** (identical hidden
worlds and random schedules, one action changed) — the plan's §3 "PlanInteractionV1" mechanism —
before it informs a build decision.

---

## 9. Decisive-turn annotation set (curriculum)

The plan asks for ≥40 matches and ≥100 annotated decisive turns spanning setup, recovery, prize
racing, threat denial, damage investment, passing, and comeback. Because no external commentary
exists for this card pool (§0), the annotation set is drawn from the **replay corpus** and structured
so each entry is falsifiable against the engine. This section defines the **annotation schema and a
worked seed set**; the full 100-turn corpus is built by applying the schema across the 567-game Grim
corpus and the 2026-08-08 top-rated export.

**Annotation schema (per decisive turn):**

```
episode, turn, seat, matchup, decision-family
public state digest (board, energy, prizes, hand-count, stadium)
both game plans (hero objective + opponent inferred plan)
the decision the agent faced (legal options offered by engine)
principal acceptable line  + acceptable alternatives (equivalence set)
causal explanation  (engine-transition-supported chain)
what was actually played  + correct? (yes / no / acceptable)
source tier + confidence
```

**Decision families** (the plan's five interaction families, used for stratification):
1. Setup / resource → attacker conversion
2. Tempo & prize-route trades
3. Threat / engine denial / targeting
4. Damage investment, pressure, forced responses
5. Recovery, comeback, passing, non-greedy sequencing

**Seed annotations (worked, Tier‑1/5 grounded):**

- **A1 — Setup (family 1), episode 91427733 T1 [Tier 5].** Hand: 2× Lillie's Determination, 2× Night
  Stretcher, Rare Candy, Dawn, Morgrem — no basic, no Energy. Engine offered only `END`. *Principal
  line: END (forced).* Correct — but flags the mulligan/opening-variance risk. **Causal:** no legal
  development action existed; the loss originates in draw variance, not a decision.
- **A2 — Recovery/targeting (family 3+5), episode 91427733 T9 [Tier 5, B2b].** Munkidori locked
  Active (Boss's Orders), fuelled Grimmsnarl benched, `{D}` in hand, `ATTACH → Active` offered.
  *Principal line: attach `{D}` to Active → retreat → promote Grimmsnarl → Shadow Bullet 180.*
  Actual: benched a 2nd Munkidori, attached to it, ended turn — **wrong**. **Causal:** attaching frees
  retreat (cost 1) → the fuelled 180 attacker comes online and takes a prize instead of a dead turn.
  *(Line pending engine-certification per §5.4 caveat — this is exactly the kind of claim the plan
  requires proving in-engine before use.)*
- **A3 — Damage investment vs immediate KO (family 4), Mega Lucario matchup [Tier 1 doctrine].**
  Choice: Shadow Bullet the opponent's benched **Solrock** (1-prize engine body, immediate KO) vs
  Shadow Bullet the **Lucario** line (invest 180 into the 340 HP central attacker + 30 bench chip).
  *Principal line: pressure Lucario*, forcing a heal/retreat and disrupting its every-other-turn Mega
  Brave clock. **Causal:** the Solrock KO scores 1 prize now but leaves the 270 attacker on schedule;
  investing into Lucario changes the opponent's plan (must heal/retreat) and the prize route. Acceptable
  alt: take the Solrock **only if** it is the last piece enabling a lethal next turn or Lucario is
  effect-immune this turn.
- **A4 — Non-greedy (family 5), B4 bench-snipe [Tier 5].** A bench-snipe KO is offered. *Principal
  line: usually decline* — B4 is anti-correlated with winning (§6.3); prefer development or hitting the
  central attacker. **Causal:** the snipe spends the turn's attack on an expendable body; the corpus
  shows these games won *less*.
- **A5 — Prize-route trade (family 2), any Mega mirror [Tier 1 doctrine].** Offered a trade that takes
  a 1-prize non-ex while exposing your 3-prize Mega. *Principal line: refuse the trade that concedes
  the worse prize class*; re-evaluate via route signature (§3.1). **Causal:** 3-for-1 prize trades lose
  the race even while "ahead on KOs" (§6.4).

**Coverage target for the full set:** ≥100 turns, ≥8 per (matchup × family) cell where data allows,
with the five families each ≥15 turns, and every "wrong/acceptable" verdict traceable to an engine
transition or a matched-world counterfactual. Building the full corpus is a data task (apply the
schema across the corpus) and is listed as the remaining §1 work in §10.

---

## 10. Competency-exam readiness & what remains

**Done in this document:**
- Source hierarchy instantiated with per-claim tiers (§1), all card numbers Tier‑1 verified.
- Format fundamentals and the six deciding axes (§2–3).
- Both-player strategic profiles for every top archetype (§4), Grimmsnarl deep-dive with empirical
  grounding (§5).
- The six required counterexamples (§6), the disruption/counterplan layer (§7), and an explicit
  correlation-vs-causation register (§8).
- The decisive-turn annotation **schema** and a worked seed set (§9).

**Remaining §1 work before the blind exam:**
1. **Refresh the meta census** (§4.0) from the 2026-08-08 top-rated export — **done** (1,400
   episodes); re-pull the latest export and refresh the classifier signatures immediately before the
   exam, since the meta shifted sharply in the 11 days before this pass.
2. **Build the full ≥100-turn annotated corpus** (§9) by applying the schema across the 567-game
   Grim corpus and the top-rated export, stratified by matchup × family.
3. **Engine-certify** the Tier‑5 lines this document leans on. **Done for the B2b retreat-legality
   core** (attach→retreat-legal, engine-verified, `CERTIFICATION_91427733_B2b.md`). Remaining: complete
   the promote→Shadow-Bullet tail in the runtime-proof harness before B2b is used as a correction
   target.

**The blind competency exam is user-gated.** Per the plan, the user holds **50 public-information-only
positions unseen during this research**, balanced across matchup / play order / decision family, and
adjudicates the pass thresholds (≥85% acceptable principal lines, ≥80% win-condition ID, ≥80%
prize-map/threat reasoning, mean causal score ≥4/5, ≥70% per matchup and family, zero illegal/
private-info/prize-count/catastrophic errors, plus explicit approval). I cannot self-administer it —
the positions and answer keys must stay outside my context.

**Ask to proceed:** provide the 50 exam positions (public-information-only board states) in any
consistent format — I will return, per position, both plans, milestones/prerequisites, protected/
expendable pieces, counterplans, a decomposed threat analysis, an abstract prize map, an
incoming-damage forecast, one principal complete-turn line, acceptable alternatives, and a causal
explanation — for you to score against your sealed keys.

---

### Appendix A — Card fact provenance (Tier 1, `EN_Card_Data.csv`)

| Card (ID) | HP | Type | Weak | Retreat | Key attack / ability |
|---|---|---|---|---|---|
| Marnie's Grimmsnarl ex (648) | 320 | {D} | {G} | 2 | Punk Up (5 {D} from deck on evolve); Shadow Bullet {D}{D} 180 +30 bench |
| Marnie's Impidimp (646) | 70 | {D} | {G} | 1 | Corkscrew Punch {D} 10; Filch (draw 1) |
| Marnie's Morgrem (647) | 100 | {D} | {G} | 1 | Corkscrew Punch {D}{D} 60 |
| Munkidori (112) | 110 | {P} | {D} | 1 | Adrena-Brain (move 3 counters); Mind Bend {P}● 60 |
| Froslass (104) | 90 | {W} | {M} | 1 | Freezing Shroud (counter on Ability-havers at Checkup) |
| TR Mewtwo ex (431) | 280 | {P} | {D} | 3 | Power Saver (≥4 TR); Erasure Ball {P}{P}● 160 +60/discard |
| Alakazam (743, MEG) | 140 | {P} | {D} | 1 | Psychic Draw (+3 on evolve); Powerful Hand {P} = 20×hand |
| Mega Lucario ex (678) | 340 | {F} | {P} | 2 | Aura Jab {F} 130 +3 {F} from discard; Mega Brave {F}{F} 270 (cooldown) |
| Iono's Bellibolt ex (269) | 280 | {L} | {F} | 2 | Electric Streamer (uncapped {L} attach); Thunderous Bolt {L}{L}{L}● 230 (cooldown) |
| Archaludon ex (190) | 300 | {M} | {R} | 2 | Assemble Alloy (2 {M} from discard on evolve); Metal Defender {M}{M}{M} 220 |

**Energy card IDs:** 1={G} 2={R} 3={W} 4={L} 5={P} 6={F} 7={D} 8={M}.
