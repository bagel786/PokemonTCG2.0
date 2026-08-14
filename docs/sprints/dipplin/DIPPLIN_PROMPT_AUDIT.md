# Dipplin engine and prompt audit

## Audit identity

- Starting synchronized commit: `f4451863ea61e007a184695b01f7b4224dff85a6`.
- Working branch: `festival-dipplin-d0-d1`.
- Exact deck source: `data/meta/top_decklists.json`, id `291b0afd6ead`, PP kawada, rank 34.
- Deck expansion: exactly 60 cards. The complete ordered ID list and counts are in
  `artifacts/dipplin_prompt_audit/summary.json`.
- Native engine used on macOS: `freshstart/submission_template/cg/libcg.dylib`, SHA-256
  `77BB978A8129B094452679E0DAF0DA69593AFDA7331685F4642C0D4A94D39D82`.
- Linux competition engine: `freshstart/submission_template/cg/libcg.so`, SHA-256
  `FFD89BF923525A3E6FEB5E6201E96A866C0F456895499ED5C4A566303CAAE67C`.
- English card data SHA-256:
  `A0EA63CF7ADCB65D35436CE0EB390DE6E2E35654A7C67C065A45F4ABAA00F373`.
- Prompt collection: 80 complete exact-deck games, 10,444 decisions, both actual orders,
  zero illegal actions, and zero audit-driver exceptions. All 34 required trace contracts were
  observed; summary SHA-256 is
  `E1B1499904BB35554BB3387CD25CCB5BAE5E561E80B60DC19BB9C24208E1039C`.

The trace harness is `scripts/trace_dipplin_prompts.py`. It is an offline coverage driver,
not the competition policy. Every fixture is a public observation with
`search_begin_input` removed; no opponent hand, facedown Prize identity, or private simulator
field appears in a fixture. Option indices are examples from that observation only.

## Exact card distinctions

The two Applin printings must remain separate:

| ID | Type | HP | Attacks | Search implications |
|---:|---|---:|---|---|
| 42 | Dragon | 40 | 37 Find a Friend (`{C}`); 38 Rolling Tackle (`{G}{R}`) | Legal for Quick Sign, Poffin, Brock, and Poké Pad. Illegal for Bug Catching Set because it is not Grass. The exact deck cannot normally pay Rolling Tackle's Fire cost. |
| 92 | Grass | 40 | 114 Tumbling Attack (`{G}`, 10 plus a coin-dependent 20) | Legal for every Basic/non-rule-box search above and for Bug Catching Set. Fire-weak. |

Both evolve legally into card 93 because the engine checks the evolution name `Applin`, not the
Basic's type. Card 93 Dipplin has attack 115 Do the Wave (`{G}`) and Ability Festival Lead. Card 88
Volbeat has attack 107 Quick Sign (`{C}`). These values come from the pinned native card table and
`freshstart/engine/ptcgProgram/CardImpl.h`.

## Verified prompt and rules contracts

1. **Quick Sign attack ID:** 107. The cost is one Colorless, so any attached Basic Grass pays it.
2. **Do the Wave attack ID:** 115. The cost is one Grass.
3. **Go-first prompt:** `SelectType.YES_NO(9)`, `SelectContext.IS_FIRST(41)`, `min=max=1`.
   Option 0 is YES and option 1 is NO. Player 0 receives the choice. See `is_first_yes.json` and
   `is_first_no.json`.
4. **Turn-one Quick Sign:** confirmed in a real exact-deck turn-one trace. Before Energy attachment,
   attack 107 was absent; after Grass was attached to Active Volbeat, attack 107 was offered. Its
   resolution ended the turn. See `main_quick_sign_turn1.json` and
   `quick_sign_turn1_first.json`.
5. **Quick Sign conditions:** Active Volbeat; a payable Colorless; no attack lock; not Asleep or
   Paralyzed; non-full Bench; and a nonempty deck containing an eligible Basic. Its selection is one
   direct `CARD/TO_BENCH`, `min=0,max<=2` prompt with `effect.id=88`, DECK options, and visible
   `select.deck`. There is no separate target/count prompt.
6. **First-turn restrictions:** the starting player cannot play ordinary Supporters or ordinary
   attacks on global turn 1. Items, Tools, Stadiums, Basics, and manual Energy are normally legal.
   Quick Sign is the explicit attack exception. Neither player can normally evolve on their first
   turn (`turn<=2`), and Rare Candy additionally requires global turn 3 or later. The exact deck has
   no Rare Candy.
7. **Setup Active:** `CARD/SETUP_ACTIVE_POKEMON`, `min=max=1`; each option is a Basic in HAND with
   `area,index,playerIndex`. See `setup_active_volbeat.json`.
8. **Setup Bench:** `CARD/SETUP_BENCH_POKEMON`, `min=0`, and
   `max=min(eligible Basics, remaining Bench slots)`. It is a direct ordered multi-selection; there
   is no count prompt. See `setup_bench.json`.
9. **Buddy-Buddy Poffin:** one `CARD/TO_BENCH`, `min=0,max<=2` prompt with DECK options and
   `effect.id=1086`. Cards 42, 92, Volbeat, and Grookey are legal; 80-HP Shaymin is not. No separate
   count prompt. See `buddy_buddy_poffin.json`.
10. **Bug Catching Set:** the top seven appear in `current.looking`. Legal choices alone are
    `CARD/TO_HAND` options with `area=LOOKING`, `min=0,max<=2`, `effect.id=1094`, and
    `select.deck=null`. Grass Pokémon of any stage and Basic Grass Energy are legal. Card 92 is
    legal and card 42 is not. It is one ordered multi-selection; unchosen looking cards are returned
    and shuffled. See `bug_catching_set.json`.
11. **Hilda:** two sequential optional `CARD/TO_HAND`, `min=0,max=1` prompts, both with
    `effect.id=1225`: Evolution first, Energy second. See `hilda_evolution.json` and
    `hilda_energy.json`.
12. **Brock's Scouting:** the first optional `CARD/TO_HAND`, `min=0,max=1` prompt contains Basics
    and Evolutions. Selecting an Evolution ends the search. Selecting a Basic produces a second
    optional Basic-only prompt for the second Basic. Selecting nothing also skips the second branch.
    See `brock_first_choice.json` and `brock_second_basic.json`.
13. **Poké Pad:** one optional `CARD/TO_HAND`, `min=0,max=1`, `effect.id=1152` prompt containing
    every non-rule-box Pokémon in deck, including both Applin printings and Evolutions. See
    `poke_pad.json`.
14. **Night Stretcher:** after the Item is played the prompt is mandatory:
    `CARD/TO_HAND`, `min=max=1`, `effect.id=1097`, with DISCARD options filtered to Pokémon or Basic
    Energy. See `night_stretcher.json`.
15. **Sacred Ash:** `CARD/TO_DECK`, `min=1,max=min(5, eligible discarded Pokémon)`,
    `effect.id=1129`. It is one direct multi-selection and is followed by a shuffle, so selection
    order does not establish deck order. See `sacred_ash_multi.json`.
16. **Brave Bangle:** no nested prompt. Each legal main-menu `ATTACH(8)` option identifies the Tool
    by HAND `area,index` and the target by `inPlayArea,inPlayIndex`. Resolve both against the current
    observation. See `main_attach_brave_bangle.json`.
17. **Boss's Orders:** mandatory `CARD/SWITCH`, `min=max=1`, `effect.id=1182`; options identify the
    opponent's current BENCH entries. See `boss_orders.json`.
18. **Black Belt's Training:** no nested prompt. It adds 40 damage against the opponent's Active
    Pokémon ex for the entire current turn, including both Festival attacks. It is cleared at turn
    end and applies before Weakness and Resistance.
19. **Festival Grounds:** a direct main-menu PLAY. It discards/replaces the current Stadium, marks
    the Stadium play for the turn, and refreshes continual effects before the next prompt. Playing a
    second same-name Festival over one's own Festival is not offered. See `main_play_festival.json`.
20. **Thwackey:** Boom Boom Groove is available if the Active has Festival Lead; Festival Grounds
    itself is not required for the tutor. The main option is `ABILITY(10)` with board
    `area,index`. The mandatory tutor is `CARD/TO_HAND`, `min=max=1`, every deck card, and
    `effect={id:90, serial:<activating Thwackey>}`. Multiple Thwackey each activate once per turn.
    Engine traces showed two distinct Ability options, then only the unused serial after the first
    resolved. See `main_two_thwackey_abilities.json`, `main_second_thwackey_available.json`, and
    `boom_boom_groove.json`.
21. **After the first Dipplin attack without a KO:** the engine immediately offers an optional
    second attack: `SelectType.ATTACK(6)`, `SelectContext.ATTACK(35)`, `min=0,max=1`, with option
    `ATTACK(13), attackId=115`. Returning `[]` declines and ends the turn; selecting the option uses
    Do the Wave again. There is no intervening MAIN window. See `festival_second_attack.json`.
22. **Festival Lead's second attack:** this non-MAIN prompt is the only place the exact Dipplin
    chooses its second attack. D0 must explicitly accept it; generic MAIN-only attack shields do not
    cover it.
23. **First-attack KO sequence:** attacker chooses a Prize; the defender receives
    `CARD/TO_ACTIVE` and promotes from its current Bench; control returns to the attacker; then the
    optional attack-115 prompt is emitted. See `festival_second_attack_after_ko.json`.
24. **New target after KO:** Do the Wave has no target prompt; the newly promoted Active is the
    target. Exact Dipplin owns only attack 115, although the generic Festival engine can enumerate
    another legal attack for a different Festival Lead Pokémon.
25. **Festival replaced or removed:** continual effects are refreshed after the first attack and KO
    processing. The second prompt exists only if the original attacker remains Active, its refreshed
    `doubleAttack` flag is true, it is not Asleep/Paralyzed, and it still owns and can pay a legal
    attack. If Festival is removed by an attack/trigger before that refresh, no second attack is
    offered.
26. **Evolution serials:** a Pokémon's public `serial` is the physical top card, not a stable line
    identity. An observed card-42 Applin serial 13 became card-93 Dipplin serial 29; the Energy kept
    its serial; `preEvolution` retained `{id:42,serial:13}`; the EVOLVE log mapped target serial 13 to
    new serial 29. Planning therefore uses the underlying Basic's serial as a lineage key while
    prompt resolution always uses the current physical serial.
27. **Actual order:** `current.firstPlayer` is authoritative. Global turns 1/3/5 belong to the first
    player and 2/4/6 to the second. `yourIndex` is the current selector and can temporarily flip to
    the defender during promotion. Both hero orders were observed in `hero_actual_first.json` and
    `hero_actual_second.json`.

## Damage and prevention truth

Do the Wave recalculates `20 × current Bench count` for each attack. With five Benched Pokémon:

| Modifiers against Active Pokémon ex | Before Weakness | Two attacks before Weakness |
|---|---:|---:|
| none | 100 | 200 |
| Brave Bangle | 130 | 260 |
| Black Belt | 140 | 280 |
| Bangle + Black Belt | 170 | 340 |

Bangle and Black Belt are added before Weakness/Resistance. Bangle is disabled by Jamming Tower.
Black Belt remains active for both attacks. Weakness is applied independently to each hit, and the
promoted target after a first-hit KO is recomputed from scratch.

Festival Grounds gives every Energy-attached Pokémon on both sides `NoSpecialCondition`: current
Special Conditions are cleared on refresh, and new poison, burn, sleep, paralysis, or confusion
fails while protection remains. Conditions cleared this way do not return after Festival leaves.

The engine still offers legal attacks that deal zero through prevention; Python must evaluate the
public effects. Important exact interactions:

- Dipplin is non-ex, so Crustle's Mysterious Rock Inn and Neutralization Zone do not block it.
- Cornerstone Mask Ogerpon ex (117) does block it because Dipplin has Festival Lead and Cornerstone
  prevents damage from attackers with an Ability.
- Effect-only prevention does not stop Do the Wave's pure damage.
- The existing `ptcg_ai.prevention.attack_nullified` cannot be reused unchanged: attack 115 has
  metadata damage zero because its damage is dynamic, and that helper early-returns for such
  attacks. D0 therefore requires a dynamic-damage-aware prevention path.

## Runtime implications frozen before D0

- Dispatch nested prompts by a composite of selection type, context, `effect.id`,
  `contextCard.id`, option shape, and staged parent history. Context alone is not strict.
- Never retain option indices across observations. Resolve semantic targets against every fresh
  prompt and sanitize exactly once.
- Optional prompt counts are intentional. The generic sanitizer defaults to `maxCount`, which is
  wrong for optional search/recovery when no useful target exists.
- Persistent memory supplements rather than replaces observations. Board, order, flags, legal
  actions, and public logs are reconstructed on every decision.
- D1 must treat the offered Festival second attack as an incomplete leaf and continue through it.
- A zero-option optional effect may be elided entirely or surfaced as `min=max=0`; resolvers must be
  legal in either case.

## Reproduction

```bash
python scripts/trace_dipplin_prompts.py --games 240 --minimum-complete-games 80
```

The harness stops once the declared contracts have all appeared and the minimum complete-game count
is reached. It does not seed or call the production engine deterministic: the pinned engine uses
independent randomness, so these traces establish prompt mechanics rather than paired evaluation.
