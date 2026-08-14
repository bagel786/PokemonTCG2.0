# Dipplin strategy model for the PP kawada 60

Status: research-grounded hypotheses, not policy rules. Starting SHA:
`a2ad27fec34e0e38e177a650b498cf1e6ea52e4a`.

## Scope and sources

This model applies to deck id `291b0afd6ead` only: 4–4 Grookey/Thwackey,
4–4 Applin/Dipplin, three Volbeat, one Shaymin, eight Grass Energy, four each
of Poffin/Bug Catching Set/Poké Pad/Hilda/Lillie/Festival Grounds, and the
single-copy Boss, Brave Bangle, Black Belt, Brock, Unfair Stamp, and Sacred
Ash package. The canonical multiset hash is
`e8e9908e4943584bcbf4d54c91feda6ccfd5a39c0a0cf7d30e5db4a5de7ebd7b`.

Competitive evidence establishes that Festival Lead is a real tournament
archetype rather than a setup novelty: Limitless records three Regional Top
8s and 866 points, while recent high-level analyses describe the deck's edge as
single-Prize attackers producing one-hit knockouts and strong offensive
pressure. Sources: [Limitless Festival Lead results](https://www.limitlesstcg.com/decks/336),
[Natalie Millar's Festival Lead guide](https://www.tcgplayer.com/content/article/Festival-Lead-Deck-Guide-Pok%C3%A9mon-TCG/0193ad25-046f-4766-906d-d9161462cbe1/),
and [Grant Manley's competitive analysis](https://www.pokebeach.com/2026/05/booming-and-grooving-festival-lead-analysis).

The exact interaction model comes from the repository's audited native-engine
traces. In particular, Do the Wave is 20 damage per Benched Pokémon; Festival
Lead grants a second printed attack only with Festival Grounds; Boom Boom
Groove requires a Festival Lead Pokémon Active; and the second attack has no
intervening MAIN window. The official Twilight Masquerade FAQ independently
confirms that Festival Lead cannot use a TM attack:
[PokéGym rules FAQ](https://pokegym.net/wp-content/uploads/2024/05/FAQ-SV06-Twilight-Masquerade.pdf).

## General Festival Lead principles

Festival Lead converts board width into both damage and tutoring. The board is
therefore not an end in itself: every Bench slot must justify its immediate
damage, tutor access, protection, or attacker continuity. Once a Dipplin can
attack, the primary optimization is the Prize route over the complete two-hit
turn, in this order:

1. Can strike one take a knockout and unlock a second target?
2. If not, do two strikes take a valuable 2- or 3-Prize Active?
3. Can one deterministic action—Boss, Bangle, Black Belt, Festival, or one
   extra Bench body—improve that result?
4. Only after the best current Prize route is preserved should remaining
   resources improve next-turn continuity.

This ordering follows the competitive descriptions of the deck as an
offensive-pressure and favorable-Prize-trade deck. It is also mechanically
necessary: setup after the first attack is impossible, so all threshold work
must happen before committing to Do the Wave.

## Win conditions for this exact list

### Against single-Prize decks

The target is initiative plus occasional two-KO turns. A five-card Bench makes
Do the Wave 100 damage per hit. The best turn KOs a low-HP Active on strike one
and the promoted target on strike two. When a first-hit KO is unavailable,
two-hit KO damage can still maintain a one-for-one exchange, but it does not
generate the deck's ceiling. Boss is valuable when it changes a no-Prize or
one-Prize turn into a guaranteed knockout; using the only Boss merely to select
an equivalent target is wasteful.

### Against 2-Prize Pokémon ex decks

The base full-Bench turn deals 200 total damage. Brave Bangle raises this to
260, Black Belt to 280, and both to 340 before Weakness/Resistance. Taking two
Prizes with one single-Prize Dipplin is already a favorable trade. A modifier
is even better when it converts a two-hit KO into a first-hit KO, because that
unlocks a second target and potentially another Prize. The deck should not
delay a provable two-Prize knockout to build an ornamental “perfect” board.

### Against 3-Prize Mega or mixed boards

The preferred route is a two-hit Mega knockout when its remaining HP is within
the public 200/260/280/340 thresholds, or a Boss route to a lower-HP 2-Prize
target when that produces more guaranteed Prizes. The single Bangle and Black
Belt are scarce closing resources. They should be tutored when they cross the
current threshold, not consumed merely because an ex is Active. Against a Mega
outside every provable threshold, current damage plus a prepared follow-up may
be correct, but “continuity” must not displace an available multi-Prize route.

## Decisions after the engine comes online

### Attack immediately

Attack now when Do the Wave is productive and no legal deterministic setup
action increases guaranteed Prizes, converts strike one into a knockout, or
restores the Festival second strike. This remains true with an imperfect Bench
or no ready replacement. Damage now is tempo; a hypothetical later board is
not.

### Build the Bench

Add a Bench body before attacking when it enables Do the Wave, restores a
Festival/Thwackey line, or crosses a current knockout threshold. Bench expansion
that leaves the same guaranteed Prize result is lower priority, especially
against spread damage or easy Boss targets.

### Prepare a replacement

Prepare one replacement line when the current attacker is likely to be lost
and doing so does not reduce the current guaranteed Prize route. A ready
replacement is not a universal precondition for the first attack. In the fresh
expert DEV+VALIDATION sample, only 10/94 had a fully ready replacement at the
first strict engine-online turn; the expert commonly attacked with an
Applin/Dipplin line present but not fully energized.

### Boom Boom Groove for setup

When no attack is available, tutor the smallest missing prerequisite that makes
the current turn functional: Dipplin/evolution, Energy, Festival, an escape
route, or a required Bench body. If the engine is already attacking but taking
no Prize, setup tutoring remains justified only when it changes the current
turn or prevents a clearly forced extinction.

### Boom Boom Groove for immediate pressure

When an attack is available, test Boss, Brave Bangle, Black Belt, Festival,
and one additional Bench body against the complete two-strike route. Tutor the
card that increases guaranteed current Prizes or unlocks the second target.
This exact list lacks the multi-card compression of Secret Box, so a Thwackey
tutor must be more selective than modern lists that can turn one ability into
four combo pieces.

## Good and bad first Do the Wave turns

A good first attack is early, has Festival when that adds useful damage, and
either takes a Prize, establishes a two-hit multi-Prize knockout, or deals
damage that the opponent cannot erase without losing tempo. Bench count matters
through damage, not as a cosmetic target. A replacement can still be only an
Applin if current pressure is preserved.

A bad first attack is one of the following:

- delayed for setup that does not change the Prize route;
- made with too few Bench bodies when one legal body crosses a KO threshold;
- made without Festival despite an immediately playable Festival and useful
  second strike;
- aimed at the wrong Active when the only Boss produces a strictly better
  route; or
- made after spending the only Bangle/Black Belt without crossing a threshold.

The current evidence does **not** show a broad first-attack delay. Fresh experts
and S1 both have a median first Do the Wave on own turn 2. The live gap appears
later: only 3/9 live games took a Prize on the first strict engine-online turn,
versus 53/94 in fresh expert DEV+VALIDATION. The working hypothesis is
therefore Prize conversion, not generic setup speed.

## Recovering awkward openings

### Grookey Active

Grookey Active is not automatically a lost game. The recovery objective is an
attack-capable Dipplin Active by own turn 2 or 3, with enough Bench width to
make the attack meaningful. Evolving Grookey before retreat is useful when the
resulting Thwackey can tutor immediately after Dipplin becomes Active; it is
bad when it consumes the turn without creating the escape or attack. Energy
should go to the Active only when it pays the actual retreat/attack path;
otherwise it belongs on the current or next Dipplin line.

Fresh expert Grookey openings attacked at mean own turn 2.29 and won 25/35 in
DEV+VALIDATION. The nine-game live sample attacked at 2.33 but went 0/3 and
took zero Prizes across all eight strict engine turns from those games. This
falsifies “Grookey only causes setup delay” and instead points to weak damage
or target conversion after escape. The local S1-vs-Grim forced-second Grookey
sample is slower (mean 2.59 first attack; 19% never attack), so recovery speed
remains a secondary defect, not the principal live failure. Most fresh Grookey
evidence comes from similar modern lists; the three exact-list Grookey games
averaged turn 3.33, so this comparison cannot justify copying their pivot
package into the exact 60.

### Applin Active

An Active Applin can evolve in place and avoids paying a retreat cost. The
priority is to bank its Grass Energy and find Dipplin, Festival, and at least
one Thwackey line. The Dragon Applin can Find a Friend with one Colorless but
cannot normally pay its `{G}{R}` attack; the Grass Applin can attack for 10 plus
a coin result. Neither low-value attack should replace an available Dipplin
evolution. A second Applin line is useful but not mandatory before the first
Do the Wave.

## When the perfect board is too slow

A “perfect” board—full Bench, multiple Thwackey, Festival, two energized
Dipplin—is unnecessary whenever a smaller board already proves the same Prize
result. It becomes actively harmful when reaching it consumes the attack,
exposes extra 40-HP targets, strands the Active, or spends Boss/modifier cards
that were needed to close. Modern tournament lists often use Air Balloon,
Goldeen/Seaking, Rabsca, and Secret Box to reduce these risks; none is available
in this exact 60.

## Modern-list strategies that must not be copied blindly

Recent guides commonly rely on cards absent here: Secret Box for a four-piece
combo, Air Balloon for a tutorable pivot, Goldeen/Seaking as alternative
Festival Lead attackers, Rabsca for spread protection, and extra Boss/Bangle
copies. The TCGplayer guide's one-Thwackey Secret Box knockout line and Air
Balloon protection are valid general evidence about why immediate conversion
and pivots matter, but they are not executable actions for this agent.

This exact list instead has three Volbeat plus Quick Sign, four Hilda, Brock,
eight Energy, and only one each of Boss/Bangle/Black Belt. Its policy must use
Quick Sign for initial width, Hilda/Brock for the evolution/Energy bridge, and
Boom Boom Groove for one precise missing card at a time.

## Replay-testable hypotheses

1. **Prize conversion:** S1 has a higher zero-Prize first-engine-turn rate and
   lower first-hit-KO rate than experts at similar Bench counts.
2. **Grookey recovery:** expert and S1 first-attack clocks are similar in live
   games, but S1 arrives with lower Bench damage or uses tutor/attachments that
   fail to cross a knockout threshold.
3. **Tutor objective:** with Do the Wave available, experts select Boss or a
   modifier more often specifically when it increases guaranteed Prizes; S1
   favors prerequisites or replacement resources.
4. **Replacement bias:** expert wins do not require a ready replacement at the
   first attack; excessive S1 replacement spending should appear as current
   Prize regret if it is causal.
5. **Prize structure:** modifiers should matter most against 2-/3-Prize boards,
   while Boss/Bench width and first-hit KOs should dominate single-Prize routes.

Each hypothesis is falsified if episode-level regret shows no repeated expert
dominance and the deterministic public Prize-route evaluator finds no positive
S1 regret in that family. No policy change follows from this document alone.
