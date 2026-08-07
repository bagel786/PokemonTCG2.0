# Loss-bucket analysis — submission 55307529 (master v2)

Pulled 2026-08-06 (local replays in `data/replays/55307529/`, 24 episodes, 1 validation + 23 public ladder games).

## Bottom line

**15W-8L (65.2%)** on the 23 public games; ELO 600 → ~833. The record is good against the mid-band (9W-1L vs <750) and collapses specifically at **750-849: 4W-6L (40%)** — every loss except one is to an off-meta/tech or mirror deck in that band. The losses split into **five buckets**, and four of the eight losses share one root cause: **the hero's Grimmsnarl ex comes online too late (turn 8-17, or never), letting walls, snipers, and aggro run away with prizes first.** One loss (90545355) is a pure policy bug — the hero passed 16+ consecutive turns with a ready attacker.

## Record vs archetype / elo

| Opponent ELO tier | Record | WR |
|---|---|---|
| Elite (850+) | 1W-1L | 50% |
| High (750-849) | 4W-6L | 40% |
| Mid (650-749) | 9W-1L | 90% |
| Low (<650) | 1W-0L | 100% |

Seat split: Seat 0 (1st) 5W-3L, Seat 1 (2nd) 10W-5L. Six of the eight losses were the harder going-second matchups against fast/tempo decks.

## Loss buckets (8 losses)

| # | Episode | Seat | Opp ELO | Opponent deck (verified from replay) | Final | Bucket |
|---|---|---:|---:|---|---|---|
| 1 | 90551564 | 1 | 836.2 | Crustle + **Cornerstone Mask Ogerpon ex** + Munkidori | 1-6 | **Anti-ex wall** |
| 2 | 90550005 | 1 | 824.8 | **Alakazam** / Dudunsparce / Fezandipiti ex | 1-6 | **Bench snipe** |
| 3 | 90549223 | 0 | 852.6 | Grimmsnarl (exact mirror, J=1.00) | 4-6 | **Mirror endgame race** |
| 4 | 90543803 | 1 | 836.9 | Grimmsnarl + Munkidori/Morpeko | 4-6 | **Mirror endgame race** |
| 5 | 90545355 | 0 | 782.9 | Iono's Bellibolt ex (Voltorb "Voltaic Chain") | 4-6 | **Endgame stall → OTK** |
| 6 | 90536826 | 1 | 760.2 | Crustle + Mega Kangaskhan ex | 3-6 | **Tank attrition** |
| 7 | 90539926 | 0 | 757.4 | Froslass / Starmie ex / Cinderace | 3-6 | **Disruption attrition** |
| 8 | 90537600 | 1 | 711.8 | Lucario / Makuhita / Hariyama (Fighting) | 1-6 | **Fast aggro blitz** |

## Bucket details and why the hero lost

### 1. Anti-ex wall — Cornerstone Ogerpon ex (90551564, 1-6)
Cornerstone Mask Ogerpon ex **takes no damage from ex Pokémon**. The deck's only non-ex damage source is Froslass (Cursed Breath counters) + Munkidori spreading; the hero didn't evolve Froslass until step ~156 (turn ~15), so Grimmsnarl ex (the main attacker) literally could not damage the wall. Opponent took 5 prizes unopposed, hero got 1.

### 2. Bench snipe — Alakazam (90550005, 1-6)
Alakazam's Dimensional Hand snipes bench Pokémon for prizes. The hero played 3-4 bench targets and its own Grimmsnarl didn't come online until step ~163 (turn ~17) — after Alakazam had picked the bench apart. Hero took 1 prize.

### 3-4. Mirror endgame race (90549223 4-6, 90543803 4-6)
Both mirror losses are narrow (4-6) vs strong mirrors (852, 836). 90543803: opponent went first, opened Morpeko → Grimmsnarl, took first prize on T5 (hero T7) and never gave the lead back. 90549223: a 4-4 prize tie resolved on the final turn by the opponent finishing the 6th prize first. These are the pure "prize-race micro" losses — the only bucket where the opponent was a better player, not a better plan.

### 5. Endgame stall → one-shot (90545355, 4-6) — **policy bug**
With a **full-HP (320) Grimmsnarl, 3 energies, 4 cards in hand**, the hero passed **every step from t230 to t250 (16+ consecutive passes)** while the opponent's Iono's Bellibolt ex freely attached lightning energy to Voltorb ("Voltaic Chain": 20 + 20 per attached {L} energy). The Voltorb then dealt **exactly 320 damage** — one-shotting the Grimmsnarl for 2 prizes and the win. No paralysis, no lock, no timeout (596s overage banked). The policy simply refused to act. This is the most fixable loss in the set.

### 6. Tank attrition — Kangaskhan/Crustle (90536826, 3-6)
Hero took **0 prizes for 16 turns**; never evolved Froslass at all; Grimmsnarl only at step 73 (~T8). Kangaskhan (300+ HP) + Crustle traded favorably against a slow setup. Lost 3-6.

### 7. Disruption attrition — Froslass/Starmie (90539926, 3-6)
27-turn grind; hero's Grimmsnarl at step 127 (~T13); opponent's Froslass/Starmie disrupted the bench and out-lasted it. Hero 3-6.

### 8. Fast aggro blitz — Lucario (90537600, 1-6)
Opponent went Riolu → Mega Lucario, **first prize T4, five prizes by T13**; the hero **never set up a single Grimmsnarl ex** all game. Pure tempo run-over of a slow setup.

## Cross-cutting findings

1. **Setup speed is the #1 lever.** Grimmsnarl-online step across losses: 73 (90536826), 127 (90539926), 156-Froslass (90551564), 163 (90550005), **never** (90537600). In four of eight losses the hero took ≤1 prize. The deck has 4 Poffin + 3 Rare Candy + 3 Grimmsnarl — the policy isn't prioritizing the T2/T3 Grimmsnarl that the deck is built for, and it's punished by anything that pressures early.

2. **Anti-tech line isn't executed.** Froslass is the only answer to Cornerstone Ogerpon and the chip answer to Kangaskhan/Crustle, and it was never/too-late (90536826, 90551564). The policy needs an explicit "wall detected → Froslass first" line.

3. **Elo cliff at 750-849 (4W-6L).** The hero beats meta decks (Fighting 4-1, Grass 3-1) but the whole losing side is tech/anti-meta + mirrors. Worth weighting the training league toward these.

4. **Endgame pass-loop is a real bug** (90545355). Regardless of the matchup, the value/search policy must not stall with a live attacker, and must respect the opponent's lethal (one-shot = 2 prizes on an ex).

## Recommended improvements (in order of ROI)

1. **Fix the stall/pass bug** (recovers 90545355 + any similar). Add a "if a legal attack exists and opponent threatens lethal, always act" guard; have the search value include opponent's next-turn lethal and ex = 2 prizes.
2. **Speed the setup line.** Re-weight the policy toward Poffin Impidimp → Rare Candy Grimmsnarl on T2-T3, especially going second and when the opponent shows early aggression (recovers 90537600, 90536826, 90550005).
3. **Execute the Froslass anti-wall line** (recovers 90551564, 90536826). Detect Cornerstone Ogerpon / Kangaskhan on T1 and prioritize Snorunt→Froslass + Munkidori. Consider a non-ex attacker tech if the meta shifts to Cornerstone walls.
4. **Mirror endgame polish** (recovers 90549223, 90543803). Mine the two 4-6 mirror losses for the exact prize-race mis-sequencing; the opening seat-1 tempo in 90543803 (Morpeko pressure) is a good imitation target.
5. **Bench hygiene vs snipers** (recovers 90550005, 90539926). vs Alakazam/Froslass, limit valuable bench pieces exposed to Dimensional Hand.

Replays: `data/replays/55307529/` (episodes_metadata.json + 24 episode-*-replay.json). Analysis script: `scripts/forensic_55307529_losses.py`.
