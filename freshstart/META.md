# The meta — what the top of the ladder plays and how it wins

**Public leaderboard, 2026-07-29 22:32 UTC** (`kaggle competitions leaderboard -c
pokemon-tcg-ai-battle`):

| | |
|---|---|
| Teams scored | 5,950 |
| Rank 1 | **1190.9** (flg) |
| Rank 10 | 1129.1 |
| 90th percentile | 842.5 |
| Median | 640.5 |

Decklists are recovered from replays — the 60-card list an agent returns on its first decision is
visible in the episode file.

| Share | Archetype | Decklist |
|---|---|---|
| **54%** | Marnie's Grimmsnarl ex | [grimmsnarl_marnie.txt](decklists/grimmsnarl_marnie.txt) |
| 14% | Team Rocket's Mewtwo ex | [team_rockets_mewtwo_ex.txt](decklists/team_rockets_mewtwo_ex.txt) |
| 10% | Alakazam / Dudunsparce | [alakazam_dudunsparce.txt](decklists/alakazam_dudunsparce.txt) |
| 8% | Mega Kangaskhan ex / Crustle | [kangaskhan_crustle.txt](decklists/kangaskhan_crustle.txt) |
| 4% | Dragapult ex | [dragapult_ex.txt](decklists/dragapult_ex.txt) |
| 4% | Cynthia's Garchomp ex | [cynthias_garchomp_ex.txt](decklists/cynthias_garchomp_ex.txt) |
| 2% | Mega Kangaskhan ex / Ogerpon toolbox | [mega_kangaskhan_toolbox.txt](decklists/mega_kangaskhan_toolbox.txt) |
| 2% | Mega Lopunny ex | [mega_lopunny_ex.txt](decklists/mega_lopunny_ex.txt) |
| 2% | Dipplin / Thwackey | [dipplin_thwackey.txt](decklists/dipplin_thwackey.txt) |
| — | Mega Starmie ex / Mega Froslass ex | [mega_starmie_froslass.txt](decklists/mega_starmie_froslass.txt) |

Shares are over the **41 of the top 100 leaderboard teams whose deck could be recovered**. A
sample of the top, not a complete census; the ordering holds at top-50 and top-200 cuts too.
Every `.txt` has a matching `.deck.csv` you can copy straight over `deck.csv`.

**Two things to know before you pick a deck.**

**Roughly half the top field is one archetype.** Whatever else you tune, tune the Grimmsnarl
matchup.

**A team's score belongs to one submission, not to a deck.** A leaderboard row shows the
higher-rated of that team's two live submissions, and the strongest teams run *different* decks
on the two — rank 1 has been seen on four different archetypes across its submissions. So when a
decklist here is labelled with a team's rank, the rank is the team's, and the list may be from
their other agent.

**Copying a top list is free and buys little.** Two players are running the exact same 60-card
Cynthia's Garchomp list at rank 70 (1033.9) and rank 147 (987.4). Many of the Grimmsnarl lists
are likewise identical to each other and spread over hundreds of points.

---

## Marnie's Grimmsnarl ex — 54% of the top field

**Line:** Marnie's Impidimp (70 HP) → Morgrem → **Marnie's Grimmsnarl ex, 320 HP, Dark,
weak to Grass**.

**Wincon.** `Punk Up` — *when you evolve into Grimmsnarl ex, search your deck for up to 5
Basic {D} Energy and attach them to your Marnie's Pokémon in any way you like.* That single
Ability erases the energy-attachment bottleneck that every other deck pays for. It then swings
`Shadow Bullet` ({D}{D}, **180 + 30 to a benched Pokémon**) from a 320 HP body every turn.
180 two-shots almost everything in the format while 30 chip damage accumulates on the bench,
setting up later one-shots.

**Engine.** 4× **Spikemuth Gym** (search a Marnie's Pokémon every turn — the deck never bricks
on its own line), 3× Rare Candy to skip Morgrem, 4× Buddy-Buddy Poffin to fetch the 70 HP
Impidimp, 4× Lillie's Determination (shuffle-draw 6), 4× Team Rocket's Petrel (fetch any
Trainer), 10× Basic {D} Energy.

**Reach package.** 4× **Munkidori** (`Adrena-Brain`: move up to 3 damage counters from your
Pokémon to theirs — simultaneously a heal and 30 extra reach for a KO) and 2× **Froslass**
(`Freezing Shroud`: during every Checkup, put a damage counter on each Pokémon that *has an
Ability* — passive chip that punishes ability-dense boards and feeds Munkidori's math).

**How it loses.** Grass weakness — ×2 means 160 Grass damage kills a full-health 320 HP
Grimmsnarl. `Punk Up` only fires on the evolution, so pressuring the fragile Impidimp/Morgrem
turns or stripping Rare Candy delays the whole deck. And it's a 2-prize ex: three KOs on
Grimmsnarl is the game.

## Team Rocket's Mewtwo ex — 14%

**Wincon.** `Erasure Ball` ({P}{P}●, **160, +60 per Energy discarded from your Bench**, up to
280) off a 280 HP Basic. No evolution line to disrupt at all.

**The constraint that defines it:** `Power Saver` — Mewtwo ex **can't attack unless you have 4
or more Team Rocket's Pokémon in play**. The whole deck is built to flood a wide TR board fast
(4× Tarountula, 4× Spidops, 3× Mimikyu, 2× Articuno).

**Engine.** Spidops `Charging Up` attaches a Basic Energy **from the discard pile** once per
turn — combined with Erasure Ball's discard cost, energy is effectively infinite. Spidops also
attacks for `Rocket Rush` (30× TR Pokémon in play = 210+ as a backup).

**Its real weapon is denial.** `Repelling Veil` (Articuno): *prevent all **effects** of your
opponent's attacks done to your Basic Team Rocket's Pokémon.* Damage still lands, but damage
*counters*, snipes, status, and forced switches do not — this single Ability blanks entire
archetypes. `Gemstone Mimicry` (Mimikyu) steals the attack of the opponent's Active Tera
Pokémon, turning the format's best attackers against them.

**How it loses.** Dark weakness on Mewtwo (Grimmsnarl's Shadow Bullet is Dark — ×2 = 360, an
instant KO). Kill or strand TR Pokémon early and `Power Saver` locks their attacker off.

## Alakazam / Dudunsparce — 10%

**Wincon.** `Powerful Hand` — for **one {P} Energy**, *place 2 damage counters on the
opponent's Active Pokémon for each card in your hand.* That's **20 × hand size**, uncapped. A
9-card hand is 180; a 14-card hand is 280 and one-shots almost anything in the format, off a
single energy, from a **1-prize** 140 HP attacker.

**Everything in the deck exists to grow the hand:** `Psychic Draw` on both Kadabra (+2) and
Alakazam (+3) triggers on evolving; Dudunsparce's `Run Away Draw` draws 3 and shuffles itself
back for reuse; 4× Hilda and 4× Dawn tutor the full evolution line; Telepath Psychic Energy
both pays for the attack and fetches 2 Basic {P} Pokémon; 4× Poké Pad, 4× Buddy-Buddy Poffin,
3× Rare Candy. Hand size *is* the damage stat.

**Tech.** 4× Enhanced Hammer (kill Mist/Spiky/TR Energy), 2× Nighttime Mine (taxes every Tera
attacker +{C}), Shaymin's `Flower Curtain` (protects non-rule-box benched Pokémon), 3× Xerosic's
Machinations (strip their hand to 3).

**How it loses.** Powerful Hand places **damage counters**, which are an *effect* — so
Repelling Veil, Battle Cage, Mist Energy, and Rock Fighting Energy shut it off completely.
Dark weakness makes the Grimmsnarl matchup brutal. And it needs a Stage 2 online *and* a big
hand *in the same turn*; anything that empties the hand (or forces the attack early) costs
damage proportionally.

## Mega Kangaskhan ex — 10%, in two opposite builds

Two very different builds share the same 300 HP Basic.

### Ogerpon toolbox (2%) — run by the rank-2 team

**All Basic Pokémon, no evolution lines, nine different attackers.** 4× **Area Zero
Underdepths** gives an **8-wide Bench** as long as a Tera Pokémon is in play (Teal Mask and
Wellspring Ogerpon ex are Tera, and Tera Pokémon take no damage at all while benched).

The glue: **Latias ex** `Skyliner` — *your Basic Pokémon in play have no Retreat Cost*. Free
pivoting across an 8-card bench means the right attacker is always one action away.

Attackers: Mega Kangaskhan ex (`Rapid-Fire Combo` ●●● 200 +50 per heads, flipping until tails);
Teal Mask Ogerpon ex (`Teal Dance`: free Basic {G} attach + a draw every turn, then
`Myriad Leaf Shower` scaling on total attached Energy); Raging Bolt ex (`Bellowing Thunder`
70× Basic Energy discarded — the burst finisher); Wellspring Ogerpon ex (100 + 120 to a
benched); Lillie's Clefairy ex (`Fairy Zone` rewrites their Dark Pokémon's weakness to
Psychic — an explicit Grimmsnarl answer); Passimian (20× your Basic Pokémon = 180 on a full
board, for 1 prize).

Support is all tutor: 4× Crispin (fetch + attach Energy from deck), 2× Cyrano (fetch 3 Pokémon
ex), 3× Meowth ex (`Last-Ditch Catch`: benching it fetches any Supporter), 4× Energy Switch,
Glass Trumpet, Prime Catcher.

**Why it's strong and why it's hard:** nothing to disrupt, an answer to everything, and no
forced line — which means the deck's strength *is* decision quality. Choosing the right attacker
and target every turn is the whole game with this deck — there is no scripted sequence to fall
back on.

**How it loses.** Almost every attacker is a 2-prize ex and Kangaskhan is a 3-prize Mega ex.
Six prizes arrive in two or three KOs. Fighting weakness on Kangaskhan and Meowth.

### Crustle lock (8%) — one of the rank-1 team's decks

The other half of the Kangaskhan share is a **prison deck**, not a damage deck:

- **Crustle** (150 HP, non-ex, 1 prize): `Mysterious Rock Inn` — *prevent all damage done to
  this Pokémon by attacks from your opponent's Pokémon ex.* Against the all-ex Mega decks,
  Crustle simply cannot be attacked. `Superb Scissors` hits 120 and *ignores all effects on
  their Active*, so it punches through the format's protection abilities.
- **Cornerstone Mask Ogerpon ex**: prevent all damage from opponent's Pokémon that **have an
  Ability** — which is most of the field.
- 4× **Mist Energy** (prevent all effects of the opponent's attacks on the holder), 4× Spiky
  Energy, 4× Grow Grass Energy (+20 HP), Jumbo Ice Cream (heal 80), **Battle Cage** (no damage
  counters on any bench).

Its plan is to make the opponent's damage *illegal*, then win at 120 a turn while trading
1 prize for 2 or 3. Anything non-ex, Fire-typed, or effect-independent goes straight through.

## Cynthia's Garchomp ex — 4%

**Wincon.** Gible → Gabite → **Cynthia's Garchomp ex, 330 HP**, plus 3× **Cynthia's Power
Weight** (+70 HP) = a **400 HP** attacker. `Draconic Buster` ({F}{F}) hits **260**, and
Roserade's `Cheer On to Glory` (*attacks by your Cynthia's Pokémon do +30*) makes it **290** —
enough to one-shot every ex in the format.

**Consistency engine.** Gabite's `Champion's Call` searches a Cynthia's Pokémon **every turn**
for free. Plus 4× Lillie's Determination, 3× Hilda, 4× Fighting Gong, 4× Buddy-Buddy Poffin.
Forest of Vitality lets the Grass half evolve on the turn it's played.

**The tension:** Draconic Buster discards **all** Energy from Garchomp, so it can't attack on
consecutive turns without rebuilding. The alternate `Corkscrew Dive` ({F}, 100, then draw up to
6) is the filler turn. Spiritomb's `Raging Curse` (10× damage counters on your benched
Cynthia's Pokémon, weakness-independent) turns accumulated damage into a finisher.

**How it loses.** Grass weakness on both halves, and every rebuild turn is a free turn for the
opponent.

## Dragapult ex — 4%, one of the rank-1 team's decks

**Wincon.** Dreepy → Drakloak → **Dragapult ex, 320 HP, Tera**. `Phantom Dive` ({R}{P},
**200 to the Active plus 6 damage counters spread anywhere on their Bench**). Spread damage
sets up multi-prize turns that no single-target deck can answer, and Tera means Dragapult takes
zero damage while it sits on the bench waiting.

**The other half of the deck is denial:** 4× **Crushing Hammer** (coin-flip discard an Energy
from their Pokémon), 2× **Budew** (`Itchy Pollen`: *your opponent can't play Item cards next
turn*), 2× **Jamming Tower** (all Pokémon Tools have no effect), 1× Judge / 1× Unfair Stamp
(hand disruption). Against decks with one attacker and one Energy requirement, Crushing Hammer
alone can end the game. 2× Munkidori converts the spread counters into KOs.

## Dipplin / Thwackey — 2%

**Wincon.** `Festival Lead` (Dipplin) — *if **Festival Grounds** is in play, this Pokémon may
use an attack twice; and if the first attack Knocks Out their Active, you may attack again after
they promote.* `Do the Wave` is {G} for 20× your Benched Pokémon = 100 on a full bench, **×2 =
200 a turn for one Energy** from an 80 HP **non-ex**. 3× Brave Bangle adds +30 vs Pokémon ex,
making it 130 × 2 = **260** against the ex-heavy top field.

**Engine.** Thwackey's `Boom Boom Groove` searches **any card** from the deck each turn while
Festival Lead is active. 4× Festival Grounds, 4× Bug Catching Set, 4× Pokégear 3.0, 4× Poké Pad.

**How it loses.** It's a Stadium-dependent deck: take Festival Grounds off the table and its
damage halves and its tutor turns off. Every list runs 4 copies for exactly that reason.

## Mega Lopunny ex / Mega Starmie ex — the pivot and one-energy decks

**Mega Lopunny ex** (330 HP): `Gale Thrust` costs **one colorless** for 60, **+170 if this
Pokémon moved from your Bench to the Active Spot this turn** = **230 a turn for one Energy**.
The whole deck is rotation tech — 4× Air Balloon, Switch, and Dunsparce/Dudunsparce (whose
`Trading Places`/`Run Away Draw` both pivot *and* draw). Fan Rotom's `Fan Call` fetches three
colorless Pokémon on turn 1.

**Mega Starmie ex** (330 HP): `Jetting Blow` is **{W} for 120 + 50 to a benched Pokémon** —
170 total damage for a single Energy — and `Nebula Beam` hits 210 ignoring Weakness, Resistance,
*and* all effects on their Active. Its partner **Mega Froslass ex** (310 HP) is a pure meta
tech: `Resentful Refrain` costs {W} and does **50 × the number of cards in the opponent's
hand**. Against the draw-engine decks (Alakazam, Grimmsnarl, Garchomp) that's routinely
400–500 damage. Cinderace's `Turbo Flare` attaches 3 Basic Energy to the bench at once.

---

## The axes that decide games in this format

**1. Prize math is the real scoreboard.** Non-ex KO = 1 prize, ex = 2, Mega ex = 3. Six prizes
ends it. A non-ex deck (Crustle, Dipplin, Alakazam, Passimian) needs six KOs but only gives up
six; the Mega decks need two or three but lose in two or three. Board evaluation that counts
HP without weighting prize value will misvalue every trade.

**2. Effect immunity is a hard wall, not a modifier.** Nothing about HP predicts whether your
attack does anything. Before evaluating damage, check the target against:

| Card | What it blanks |
|---|---|
| Repelling Veil (TR Articuno) | all *effects* of attacks on their Basic TR Pokémon |
| Mysterious Rock Inn (Crustle) | all damage from **Pokémon ex** attacks |
| Cornerstone Stance (Cornerstone Ogerpon ex) | all damage from Pokémon **with an Ability** |
| Tera (Ogerpon ex, Dragapult ex) | all damage while **on the Bench** |
| Mist Energy / Rock Fighting Energy | all *effects* of attacks on the holder |
| Battle Cage | damage **counters** on any Bench |
| Flower Curtain (Shaymin) | damage to your non-rule-box Bench |
| Neutralization Zone | damage to non-rule-box Pokémon from ex/V |

Decks that deal damage via *counters* or *effects* — Alakazam's Powerful Hand, Munkidori,
Dragapult's spread, Froslass's Shroud — hit zero against several of these. Decks whose text
says "isn't affected by any effects on your opponent's Active Pokémon" (Superb Scissors,
Nebula Beam, Demolish, Spiky Hopper) are specifically built to cross the wall.

**3. Weakness is ×2 and it is decisive.** The whole field is a weakness rock-paper-scissors:
Grimmsnarl (Dark) is Grass-weak, and the Grass attackers (Crustle, Dipplin, Teal Mask Ogerpon,
Roserade) are half the reason they're played. Alakazam and TR Mewtwo (Psychic) are Dark-weak,
so Grimmsnarl eats them. Kangaskhan and Meowth (Colorless) are Fighting-weak. Lillie's Clefairy
ex can *rewrite* Dark Pokémon's weakness to Psychic.

**4. Hand size is a resource and a liability.** Alakazam turns hand size directly into damage;
Mega Froslass ex turns the opponent's hand size directly into damage; Xerosic's Machinations,
Judge, Unfair Stamp, and Iono attack it. Every card played out of hand is damage given up in
one matchup and safety bought in another.

**5. Stadiums are a contested slot.** Only one is in play at a time, and playing yours discards
theirs. Spikemuth Gym *is* Grimmsnarl's consistency; Festival Grounds *is* Dipplin's damage;
Area Zero Underdepths *is* the toolbox's 8-card bench. Stadium denial is a real, cheap lever
against three of the top archetypes.

**6. Attacking ends your turn.** Every non-attack action — draw, bench, evolve, attach, use
Abilities — must happen first, or it doesn't happen at all. With Alakazam's Powerful Hand,
Passimian's Coordinated Throwing, Dipplin's Do the Wave and Mewtwo's Erasure Ball, the actions
you take before attacking also change how much the attack does.
