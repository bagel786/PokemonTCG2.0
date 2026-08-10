# Competitive Pokémon TCG Strategy as a Player Model

**Purpose:** Independent strategy research for the Codex implementation pass  
**Date:** 2026-08-09  
**Status:** Research synthesis, not an implementation specification  
**Scope:** General competitive Pokémon TCG principles, interpreted for this repository's pinned competition engine and the exact Grimmsnarl validation deck

## 1. Bottom line

A strong Pokémon TCG player does not ask only, “Which action produces the largest immediate number?” The player continuously compares two evolving plans:

1. How quickly and reliably can I reach a winning condition?
2. How quickly and reliably can my opponent reach theirs, and what can I do to change that?

The important unit is therefore not an isolated action or even an isolated board state. It is a **plan interaction**:

> current public state + beliefs about hidden cards → attainable milestones → attacker and Prize schedules → opponent response → revised route to winning

Damage, Energy, cards, board width, and Prize cards matter because they change one of those schedules. None is a universal objective by itself.

For code, this means the agent should represent and compare:

- our likely win condition and the opponent's likely win condition;
- the next attacker, replacement attacker, and enabling engine for each side;
- both players' likely Prize routes;
- the probability and timing of relevant damage thresholds;
- resources that are committed, recoverable, scarce, or still required;
- which player is forcing the other to react;
- uncertainty about hidden information and alternative opponent plans;
- the conditions under which the current plan should be abandoned.

The goal is not to hardcode “expert moves.” It is to encode the reusable questions that lead experts to those moves.

## 2. Sources and authority

### 2.1 Hierarchy

Mechanical claims should be resolved in this order:

1. **Pinned competition engine and its card data.** This is the final authority for this project. Real-world rules or card text do not override the local engine.
2. **Official Pokémon rules.** The current official rulebook establishes the normal turn structure, victory conditions, zones, Prize cards, and general mechanics.
3. **Official Pokémon strategy articles by accomplished competitors.** These are strong evidence for how good players transform mechanics into matchup plans.
4. **Long-form competitive strategy writing.** These sources help define concepts such as Prize trade, pressure, sequencing, contingency plans, and Prize checking.
5. **Tournament results and deck lists.** These establish what succeeds and what opponents are likely to play, but do not prove why a particular line is correct.
6. **Community discussion.** Useful for generating hypotheses and counterexamples, not for settling mechanics or declaring a line optimal.

### 2.2 Principal public sources used

- [Official Pokémon TCG rulebook](https://www.pokemon.com/static-assets/content-assets/cms2/pdf/trading-card-game/rulebook/par_rulebook_en.pdf): basic mechanics and victory conditions.
- [Arceus VSTAR and Inteleon Deck Strategy, Xander Pero](https://www.pokemon.com/us/strategy/arceus-vstar-and-inteleon-deck-strategy): attacker continuity, Prize denial, and deliberately forcing a “seven-Prize game.”
- [Archaludon ex Strategy: Testing Your Metal, Stéphane Ivanoff](https://www.pokemon.com/us/strategy/archaludon-ex-strategy-testing-your-metal): resource preservation and sequencing search, thinning, recovery, and stochastic effects.
- [Building a Mega Lucario ex Deck, Natalie Millar](https://www.pokemon.com/uk/strategy/pokemon-tcg-deck-list-and-strategy-building-a-mega-lucario-ex-deck): the current Lucario plan, single-Prize staging, acceleration, secondary attackers, and gust access.
- [Tord Reklev on Battle Styles](https://www.pokemon.com/us/strategy/tord-reklev-best-cards-to-watch-for-in-pokemon-tcg-sword-shield-battle-styles): pressure through spread damage, support-Pokémon targeting, and transitions between attacks.
- [Surging Sparks Top Competitive Cards, Ellis Longhurst](https://www.pokemon.com/us/strategy/pokemon-tcg-scarlet-violet-surging-sparks-top-competitive-cards): intentionally conceding a Prize to accelerate Energy and unlock comeback effects.
- [Silver Tempest Top Competitive Cards](https://www.pokemon.com/us/strategy/pokemon-tcg-sword-shield-silver-tempest-top-competitive-cards): denial that forces inefficient attachments, alternate attackers, or a missed attack.
- [Finding Your Path—How to Win at the Pokémon TCG, Sam V](https://www.pokebeach.com/2018/10/finding-your-path): Prize trades, pressure, threat comparison, win conditions, and replanning.
- [Steps for Success—How to Master Sequencing, Ciaran Farah](https://www.pokebeach.com/2024/02/steps-for-success-how-to-master-sequencing): goal-first sequencing, subgoals, backup goals, and conditional turn planning.
- [The 3 Principles of Prize Checking, Natalie Millar](https://www.tcgplayer.com/content/article/The-3-Principles-of-Prize-Checking/a015ad58-7ec5-41ea-ba50-56db0ee9d67f): using deck search to infer face-down Prize cards and prioritizing strategically important checks.
- [JustInBasil's Alternate Formats](https://www.justinbasil.com/league/formats): examples where flexible win conditions, resource management, risk assessment, and the option cost of discarding dominate play.

These sources span different card pools. Their examples are not copied as deck-specific rules. They are used to identify strategic invariants that remain meaningful when cards rotate.

## 3. A useful model of the game

The normal Prize game can be viewed as a race between two stochastic schedules.

For each player, estimate:

- **setup schedule:** when the engine and first attacker become functional;
- **attack schedule:** the probability of making a relevant attack on each future turn;
- **KO schedule:** when each target crosses a KO threshold;
- **replacement schedule:** whether another attacker can respond after a KO;
- **Prize schedule:** how many Prize cards each successful attack or effect is expected to convert;
- **disruption schedule:** when the opponent can delay, strand, deny, or remove required pieces;
- **exhaustion schedule:** when deck, Energy, recovery, or attackers become insufficient.

A plan is attractive when it improves our time-to-win distribution, worsens the opponent's, or both. A line that takes no Prize cards can be excellent if it causes a missed attack, removes the only replacement attacker, forces an expensive retreat, or turns a future two-hit KO into a reliable one-hit KO. A line that takes Prize cards can be poor if it exposes a decisive multi-Prize liability or spends the only resource required to finish the game.

This also explains why evaluation should not be one fixed linear score. Strategic priorities change sharply near boundaries:

- zero versus one available attacker;
- survives versus is Knocked Out;
- five versus six Prize cards taken;
- can versus cannot retreat;
- one versus zero copies of the required recovery or gust effect;
- opponent can versus cannot answer on the next turn.

Those are plan-feasibility transitions, not small numeric changes.

## 4. Tempo in Pokémon TCG

“Tempo” is not an official numerical statistic. For this project, the most useful operational definition is:

> **Tempo is control over the timing of the two players' credible win plans—especially who can make relevant attacks, reach Prize milestones, and force responses first.**

Tempo is not synonymous with damage, attacking, going first, or taking the first Prize. It has several interacting parts.

### 4.1 Development tempo

Development tempo measures how quickly a player converts cards and attachments into a functioning board:

- turns until the first relevant attack;
- turns until a replacement attacker is ready;
- turns until the draw or acceleration engine is online;
- number of manual attachments still required;
- evolution waiting time and Rare Candy access;
- switching or retreat requirements before attacking.

An early attack that leaves no replacement may have worse development tempo than a setup turn that establishes two attackers. Conversely, an elaborate board that will not attack before the opponent wins is development without useful tempo.

### 4.2 Prize tempo

Prize tempo is the projected rate of converting attacks into the remaining Prize cards. It depends on:

- Prize value of accessible targets;
- number of attacks or KOs still required;
- whether damage is being placed on future targets;
- whether a target can heal, retreat, evolve, or become protected;
- whether taking a Prize activates the opponent's comeback cards;
- whether the current attacker survives to attack again.

The player ahead on the visible Prize count may be behind on Prize tempo if their next two attacks take one Prize each while the opponent threatens two or three per KO.

### 4.3 Denial tempo

Denial tempo is time removed from the opponent's schedule. Examples include:

- Knocking Out the only prepared attacker;
- removing an acceleration or draw engine before it produces another attacker;
- forcing a high-retreat-cost Pokémon Active;
- increasing an attack cost so the opponent needs another attachment;
- removing Energy when recovery is unlikely;
- forcing the opponent to spend its Supporter, retreat, or Stadium for repair rather than progress;
- damaging a central attacker enough that it must retreat, heal, or accept a losing trade.

The official Silver Tempest strategy article illustrates this directly: attack-cost pressure can force unusual Energy attachments, force a normally protected Pokémon to attack, or cause a missed attack. The important value is the change in the opponent's schedule, not the nominal card removed.

### 4.4 Initiative and forcing play

A player has initiative when their threat requires a narrow or costly response. Examples:

- a threatened game-winning gust;
- a prepared attacker that KOs the opponent's only replacement;
- spread damage that creates multiple simultaneous KO threats;
- a damaged three-Prize Pokémon that must retreat or be lost;
- an Active Pokémon the opponent cannot easily move.

Pressure is valuable because it restricts the opponent's useful choices. Tord Reklev's Urshifu discussion treats early damage and spread as a way to create later multi-target KOs and attack developing support Pokémon. The opponent must respond to the future conversion, not merely the damage already dealt.

### 4.5 Tempo debt

Some actions create future obligations:

- attaching all Energy to one vulnerable attacker;
- filling every Bench slot;
- using the only switching effect early;
- discarding the only late-game gust or recovery card;
- promoting a Pokémon that will require multiple Energy to retreat;
- taking a Prize that enables a powerful comeback effect before the board can absorb it.

This is **tempo debt**: apparent progress now that consumes future actions or makes a future interruption likely. The agent should explicitly track obligations created by a line.

### 4.6 A computable tempo summary

For each candidate plan, estimate at minimum:

- probability we make a relevant attack this turn and next turn;
- probability the opponent does the same;
- expected turns to our next meaningful Prize conversion;
- expected turns to the opponent's;
- probability each side has a replacement attacker after the next KO;
- opponent repair actions forced by our line;
- our repair actions created by our line.

Tempo should emerge from these predictions rather than from a hand-written “tempo bonus.”

## 5. Prize mapping is a dynamic route, not a counter

Prize mapping means planning the sequence of targets and attacks that reaches the final Prize card. Both maps matter:

- our route through the opponent's liabilities;
- the opponent's route through ours.

The map should extend beyond the explicit search horizon using an abstract continuation. If search reaches only the next turn, the evaluator should still ask what Prize sequence the resulting board enables.

### 5.1 Route representation

A useful route record contains:

- target role and Prize value;
- damage or effect required;
- earliest accessible turn;
- gust or mobility requirement;
- probability the target remains available;
- likely retaliation after the KO;
- next attacker and next target;
- total attacks and turns to finish.

Represent equivalence sets when several targets serve the same route. The point is not to name a fixed Pokémon three turns early when the future board is uncertain; it is to preserve the route structure.

### 5.2 Prize parity and forcing extra work

The official Arceus/Inteleon article gives a clear example of deliberately inserting a single-Prize attacker so the opponent must effectively take seven Prize cards' worth of KOs. This is not magic parity arithmetic. It works only when the opponent cannot bypass the single-Prize Active with gust or another target.

Therefore an “odd-Prize” or “seven-Prize” plan requires:

- the low-value Pokémon can attack or otherwise advance the plan;
- it can be forced into the opponent's route;
- the opponent cannot cheaply gust around it;
- the resulting extra turn is usable;
- benching it does not create a different, easier liability.

### 5.3 Target value is two-dimensional

Every target has at least two kinds of value:

1. **Conversion value:** Prize cards and damage progress gained.
2. **Denial value:** future attacks, draw, acceleration, switching, recovery, or strategic options removed.

The best target often advances both. A support Pokémon can be the correct target when removing it causes missed attacks. A harmless two-Prize support liability can be the correct target when it completes a reliable winning route before the opponent can respond. Neither “always attack the engine” nor “always take the most Prizes” is sound.

### 5.4 Recompute after every material event

Prize routes should be revised after:

- a KO or Prize draw;
- a new multi-Prize Pokémon enters play;
- evolution changes HP, Prize value, attack access, or immunity;
- a key gust, recovery, or switching card is used or discarded;
- damage creates or removes a future KO threshold;
- the opponent reveals an alternative attacker;
- a comeback effect becomes active;
- a target becomes inaccessible or protected.

## 6. Win conditions and plan graphs

“Take six Prize cards” is a victory rule, not a sufficient game plan. A matchup plan should state:

- the intended win condition;
- milestones that make it feasible;
- required and optional resources;
- attacker schedule;
- preferred Prize route;
- what must be protected;
- what may be sacrificed;
- the opponent's strongest counterplan;
- backup win conditions and switch triggers.

A plan can be represented as a dependency graph:

```text
win
├── complete Prize route
│   ├── make attacker A ready
│   ├── preserve gust for target B
│   └── keep replacement attacker C available
├── survive opponent's next conversion
│   ├── deny attacker X
│   └── avoid exposing liability Y
└── maintain access
    ├── draw/search engine
    ├── switching
    └── recovery
```

The graph is conditional. If a prerequisite becomes improbable, the agent should switch to a backup route rather than continue maximizing progress toward a dead plan.

The PokeBeach sequencing framework is useful here: define a main goal, required subgoals, and backup goals before choosing the order of cards. The same idea should organize candidate generation in code.

## 7. Pokémon roles are contextual

A Pokémon does not have one permanent strategic label. It can simultaneously or sequentially be:

- primary attacker;
- bridge attacker;
- late-game closer;
- Energy accelerator;
- draw/search engine;
- gust or mobility engine;
- wall or pivot;
- spread/damage-counter enabler;
- recovery engine;
- sacrificial Prize buffer;
- dangerous Prize liability.

Roles change with the state. A damaged primary attacker may become an expendable pivot. A support Pokémon may become the only viable attacker through Weakness. A normally expendable Basic may be the only remaining evolution path and therefore must be protected.

### 7.1 The Mega Lucario correction

The existing brief uses Mega Lucario as an example of a deck where “Mega Lucario is the deck.” That is a useful warning against treating it as an ordinary body, but it is strategically incomplete.

Pokémon's current official Mega Lucario guide describes a more flexible interaction:

- the deck often presents a single-Prize board;
- Mega Lucario can accelerate Hariyama;
- Hariyama can attack for meaningful damage and provide gust access;
- Mega Lucario is used to confront large multi-Prize Pokémon;
- Solrock and Lunatone provide additional draw and attack options;
- the plan can take two Prizes, then two with a single-Prize attacker, then finish with Mega Brave.

Consequently, damaging Mega Lucario instead of Knocking Out Solrock is not automatically correct. The comparison must include:

- whether Lucario is currently required to attack or only to accelerate;
- whether Hariyama is already prepared;
- whether removing Solrock or Lunatone changes draw, Energy, mobility, or the single-Prize route;
- whether 180 damage changes Lucario's survival against an actual follow-up;
- whether Lucario can retreat, heal, or remain protected;
- how each target changes both Prize maps.

This is the kind of correction a generalized player model must make.

## 8. Threat assessment must predict impact

Raw HP, printed damage, Energy count, or Prize value alone does not define threat. For every important Pokémon, assess:

1. **Immediate output:** attacks or Abilities available now and their target set.
2. **Readiness:** cards, attachments, evolution steps, switches, and turns still required.
3. **Scaling:** how output changes with Energy, hand, discard, damage, board width, or Prize count.
4. **Engine dependence:** which other cards or Pokémon must remain functional.
5. **Continuity:** whether it can attack repeatedly and whether replacements exist.
6. **Mobility:** retreat cost, switching access, pivot value, and susceptibility to being stranded.
7. **Reach:** Active-only, gust, Bench damage, spread, damage counters, devolve, or alternate effects.
8. **Resilience:** HP, Weakness, Resistance, immunity, healing, evolution, pickup, and recovery.
9. **Prize liability:** Prize cards conceded and how easily the opponent can force that KO.
10. **Denial value:** how much of the opponent's future plan disappears if it is removed or damaged.

A threat is relational. The same attacker may be terrifying against one board and irrelevant against immunity, Weakness, an unfavorable Prize race, or a faster opposing threat.

## 9. Board development and the Bench

The Bench is simultaneously:

- future attacking capacity;
- engine capacity;
- mobility and promotion capacity;
- a limited set of slots;
- a collection of possible Prize liabilities;
- a surface vulnerable to gust, spread, and damage-counter attacks.

“Fill the Bench” and “keep the Bench small” are both bad universal rules.

For each possible bench placement, ask:

- Which future milestone requires this Pokémon?
- How likely is that milestone to occur before the game ends?
- Does this improve attacker continuity or engine reliability?
- What Prize route does it offer the opponent?
- Does it consume a slot needed for a later attacker, pivot, or tech?
- Can the opponent damage or gust it before it produces value?
- Is it recoverable if discarded instead?

The local Grimmsnarl analysis reinforces this interaction. Early width and later Energy are complements, but the observed performance is not monotonic in Marnie's bodies: three early bodies performed better than four or more. That is exactly what a constrained-role model predicts—development helps until extra bodies cease enabling fuel or continuity and become congestion or liability.

## 10. Resource management is option management

Cards are valuable because of what they keep possible. A large hand is not necessarily a strong hand, and a small hand is not necessarily weak when it contains searchable or reusable access to the required plan.

Track resources in functional groups:

- manual and accelerated Energy;
- Pokémon search and evolution access;
- draw and hand refresh;
- gust and switching;
- retreat payment;
- recovery;
- healing or pickup;
- Stadium access and removal;
- damage modifiers;
- disruption;
- once-per-turn and once-per-game effects;
- deck cards and remaining attackers;
- Bench slots;
- the Supporter, attachment, retreat, and Stadium permissions for the turn.

### 10.1 Committed, recoverable, and irreplaceable

For every important card or attachment, record whether it is:

- available now;
- committed in play;
- in discard but recoverable;
- known unavailable;
- possibly Prized or hidden;
- the last effective copy for the plan.

Discarding a redundant card can improve consistency. Discarding the last recovery or gust needed by the only viable Prize route can make that route impossible. Stéphane Ivanoff's Archaludon discussion makes this concrete: a stochastic Stadium activation can be safe early when resources are recoverable, but dangerous late when the last Boss's Orders is required to win.

### 10.2 Energy is scheduled capacity

Energy should be evaluated by the future attacks it enables, not simply counted.

Important distinctions include:

- Energy on the next attacker versus a doomed Active;
- the final unit that crosses an attack threshold versus surplus Energy;
- Energy protected on several attackers versus concentrated on one target;
- recoverable Energy versus a scarce special Energy;
- an attachment that preserves retreat access versus one that commits the retreat resource;
- acceleration that shortens the schedule versus acceleration added after all relevant attackers are ready.

### 10.3 Comeback resources change the value of being ahead

The official Surging Sparks article describes intentionally conceding a Prize to accelerate Energy and activate cards that work while behind. Therefore Prize lead is not purely beneficial. Taking a Prize can alter:

- Counter Catcher or analogous gust access;
- reduced attack costs;
- hand disruption strength;
- damage scaling;
- self-KO acceleration lines.

The agent must evaluate the post-Prize rules state, not only the Prize gained.

## 11. Sequencing: build a dependency order

Good sequencing is not captured by one slogan such as “thin before draw” or “draw before search.” The correct order depends on the turn goal, information value, failure branches, and which actions are irreversible.

### 11.1 Goal-first method

Before acting, identify:

1. main turn goal;
2. mandatory subgoals;
3. optional improvements;
4. backup goal if a stochastic step fails;
5. resources that must not be consumed before the backup remains safe.

Then order actions according to their dependencies.

### 11.2 Sequencing principles

- Obtain free or deterministic information before making irreversible commitments when that information can change the choice.
- Delay the one-per-turn Supporter, attachment, retreat, and Stadium commitment until its opportunity cost is understood.
- Use search and thinning before a random draw when removing known unwanted cards improves the draw and does not consume a card the draw could make unnecessary.
- Draw before narrow search when the draw may reveal what should be searched for or allow the search to take a different required piece.
- Pay discard costs only after identifying protected resources and backup lines.
- Perform recovery before search when search needs the recovered targets in the deck; perform recovery after a stochastic mill when returning cards first would expose them to the mill.
- Use once-per-turn Abilities before attacking, but not automatically before effects that can improve their targets or probabilities.
- Resolve damage movement, gust, retreat, and promotion in the order that preserves legal targets and intended attack math.
- Stop developing when additional plays add liability, reveal information, consume recovery, or weaken the post-attack hand without improving the plan.

Ivanoff's Archaludon examples demonstrate that sequencing can reverse based on card interaction: remove non-Items from the deck before a PokéStop activation, but return non-Items with Pal Pad or Super Rod after that activation. The general rule is dependency and probability management, not memorized ordering.

### 11.3 Complete turns, not isolated clicks

A legal first action can be bad because it destroys the best completion of the turn. Candidate generation should therefore propose coherent turn programs:

```text
goal → information actions → searches/draws → commitments → target selection → attack/end
```

The evaluator should compare complete or conditionally complete turns, including a stopping rule. “Play every legal card” is not a valid completion policy.

## 12. Damage planning under uncertainty

Strong play reasons about damage as a distribution, not a single number.

For each relevant opposing attack, model:

- legal attacker and target probability;
- required Energy and acceleration;
- required evolution or switch;
- damage modifiers and stadiums;
- Weakness, Resistance, immunity, and effect prevention;
- damage counters and spread already placed;
- healing, evolution, pickup, or retreat escape;
- gust probability;
- whether the opponent prefers a different strategic objective.

The useful outputs are:

- probability of no relevant attack;
- damage distribution by target;
- KO probability for each important Pokémon;
- expected Prize conversion;
- probability of a missed attack after disruption;
- probability the opponent chooses pressure, setup, or denial instead.

Expected damage alone is inadequate near a KO threshold. A 50% chance of 340 and 50% chance of zero has the same mean as guaranteed 170 but a completely different effect on a 320-HP three-Prize Pokémon.

## 13. Opponent modeling means predicting plans

The opponent model should not merely predict the next observed action. It should maintain beliefs over:

- archetype or deck family;
- primary and alternative win conditions;
- likely attacker sequence;
- likely Prize route;
- important hidden cards based on public evidence;
- recovery, gust, switch, and disruption availability;
- current intent: setup, attack, gust, deny, heal, stall, or pivot;
- how intent changes after our candidate line.

### 13.1 Public-information belief state

Update beliefs from:

- revealed Pokémon and Energy;
- cards played, discarded, recovered, or returned;
- deck and hand counts;
- searched card classes;
- unusual attachments or promotions;
- Prize cards taken and known revealed effects;
- failure to take an action that was likely available;
- tournament or replay priors, kept separate from direct evidence.

Never convert a likely hidden card into a known card. Store probability and provenance.

### 13.2 Intent is conditional

Predicting “Boss's Orders” is less useful than predicting:

> The opponent is trying to remove our only replacement attacker and complete a 2→2 route; gust is one way to execute that plan.

This allows search to defend against several actions serving the same intent and to recognize when our move changes the opponent's best plan.

## 14. Pressure, greed, and target selection

Pressure is progress that also constrains the opponent. Greed is immediate conversion that weakens the eventual win probability.

For each attack or gust target, ask:

- What Prize route does this advance?
- What opposing schedule does it delay?
- What response does it force?
- Does the damage persist and remain convertible?
- Is the target likely to heal, retreat, evolve, or become inaccessible?
- What attacker and Energy do we expose?
- Can we continue attacking after retaliation?
- Does the opponent gain a comeback resource?

The PokeBeach “Finding Your Path” framework is especially relevant: taking easy Prize cards can be wrong when it does not slow a faster opposing plan, while removing a lower-value attacker or engine can create the missed turn needed to win. But denial is also wrong when a direct Prize route wins first. The correct choice depends on the comparative clocks.

## 15. Defensive play and sacrifice

Defensive play is not merely maximizing HP. It includes:

- forcing the opponent to take an extra KO;
- presenting a low-Prize Active that cannot be bypassed;
- removing a damaged liability from play;
- preserving a future attacker on the Bench;
- denying spread or damage-counter conversion;
- promoting a pivot that makes the next turn possible;
- accepting a KO that activates recovery or comeback tools;
- refusing to bench an unnecessary target.

A sacrifice is good only if the gained turn or changed Prize route has a planned conversion. Sacrificing a Pokémon while failing to prepare the next attacker merely delays the same loss.

## 16. Alternative win conditions

The player model should always check the engine's actual victory conditions. Besides taking Prize cards, a position may permit:

- winning because the opponent has no Pokémon in play;
- deck-out;
- a card-specific victory effect;
- a lock or exhaustion plan that makes one of those inevitable.

The official Snorlax stall strategy describes deck-out as a legitimate plan whose strength depends heavily on the opponent's list. More generally, alternate win conditions become relevant when the ordinary Prize trade is losing or when the opponent has over-consumed switching, recovery, attackers, or deck cards.

## 17. Phase model and replanning

Useful phases are defined by strategic state, not a fixed turn number.

### Development

- establish engine and attackers;
- infer opponent archetype and initial route;
- avoid unnecessary liabilities;
- identify possibly unavailable key cards;
- decide whether speed or disruption is required.

### Contest

- compare attacker continuity and Prize clocks;
- choose whether to enter, delay, or break the Prize trade;
- apply pressure to the relevant plan component;
- preserve the resources needed to finish.

### Conversion

- reduce the remaining route to reliable attacks;
- protect gust, switching, and damage thresholds;
- deny the opponent's checkmate line;
- thin dead cards and minimize response surface.

### Exhaustion or lock

- count remaining attackers, Energy, recovery, switches, and deck cards;
- assess whether the opponent can still execute an ordinary Prize route;
- consider deck-out, trapping, or resource denial.

Replan whenever a material assumption changes. The plan record should list explicit switch triggers, such as “second attacker cannot be prepared next turn,” “last gust is unavailable,” or “opponent reveals a single-Prize route that adds a required KO.”

## 18. Implications for the new agent

This section is a research bridge, not authorization to implement before the four Opus documents and competency results are audited.

### 18.1 Strategic state

The strategic layer should derive, for both players:

- active plan hypotheses and probabilities;
- milestones completed and missing;
- Pokémon role distributions;
- attacker readiness and continuity;
- abstract Prize routes;
- damage and KO distributions;
- key resource availability beliefs;
- exposed liabilities;
- forced repair actions;
- plan switch triggers.

### 18.2 Candidate generation

Generate candidates from meaningful plan changes, including:

- fastest feasible setup;
- best continuation of attacker schedule;
- direct Prize conversion;
- pressure on the opponent's main plan;
- forced missed attack;
- Prize-route distortion;
- liability removal or defensive sacrifice;
- recovery or conservation;
- alternate win condition;
- safe end-turn line when further development is harmful.

Candidate width should be empirical. Expand when plans disagree, uncertainty is high, Prize or KO thresholds are near, or several targets change future routes. Contract for forced or strategically equivalent choices.

### 18.3 Evaluation

Evaluate complete turn plans using predictions such as:

- probability of winning by route and horizon;
- feasibility of our milestones;
- feasibility of opponent milestones;
- time-to-Prize distributions;
- attacker continuity;
- KO and incoming-damage distributions;
- resource sufficiency and irrecoverable losses;
- option value retained;
- uncertainty and model disagreement.

Avoid a universal handcrafted claim that a particular feature is worth a fixed number of points. Calibrate the relationship between predictions and game outcomes on held-out games, and preserve hard mechanical constraints separately from learned strategic values.

### 18.4 Search horizon

Use detailed engine simulation where tactical precision matters, then attach an abstract strategic continuation:

```text
exact current turn → exact/limited reply → abstract attacker, Prize, and resource schedule
```

This lets the system value a line whose benefit occurs outside the explicit tree without pretending to know exact future cards.

### 18.5 Explanations as diagnostics

For every meaningful override, log:

- selected plan and option;
- expected Prize route for each side;
- pivotal threat and role dimensions;
- incoming-damage distribution;
- resource or milestone changed;
- strongest alternative;
- confidence and uncertainty source;
- condition that would reverse the decision.

These explanations are not proof, but they make systematic misunderstandings measurable.

## 19. Anti-overfitting requirements

The 50-position Opus exam is a competency gate for the designer, not training data for the finished agent. It must not become a list of exceptions.

Generalization requires:

- features based on roles, schedules, Prize values, dependencies, and probabilities rather than opponent names;
- card text and engine mechanics as inputs, not one rule per card ID;
- broad replay and engine-generated training/evaluation data;
- episode-, opponent-, time-, and archetype-level holdouts;
- counterfactual perturbations of HP, Energy, Prize count, player order, targets, and resource availability;
- full-game evaluation, not only isolated positions;
- ablations showing which strategic components cause improvements;
- a final sealed benchmark not used to tune either the documents or code.

Card-specific handling is acceptable only for mechanical semantics that cannot yet be derived reliably from card data. It should not encode an unconditional tactic.

## 20. Questions to ask on every consequential turn

The following checklist is a compact player loop:

1. What are the credible win conditions for both players now?
2. If both sides execute their current plan without missing, who wins first?
3. Which milestones and resources make those plans feasible?
4. What are the next and replacement attackers?
5. What Prize routes are available, and can either player force an extra KO?
6. Which Pokémon are threats across readiness, reach, continuity, resilience, and denial value?
7. What damage can the opponent probably produce next turn, as a distribution?
8. Can we both advance our plan and delay theirs?
9. What liabilities or tempo debt does each line create?
10. What hidden assumptions are we making, and how confident are they?
11. What is the best backup if the main line misses?
12. What observable event should make us replan?

If the implemented system cannot answer these questions in computable form, it is not yet modeling player strategy; it is still scoring moves.

## 21. Research limitations

- Public strategy articles demonstrate principles with particular historical decks. They do not establish universal optimality.
- “Tempo” has no single official Pokémon TCG formula. The operational definition here is a synthesis intended for prediction and evaluation.
- The competition engine may differ from contemporary paper Pokémon in card text, timing, bugs, or legal sets. Local engine truth always wins.
- The local replay corpus is concentrated on exact-deck Grimmsnarl. It supports that first implementation target but not universal competence with every deck.
- Aggregate correlations such as board width or Energy in play can reflect both cause and game state. Counterfactual engine tests are needed before assigning causal value.
- A strategic model can still fail through poor probability calibration, incomplete card semantics, candidate omission, or latency. Full-game evidence remains the final test.

## 22. What I will carry into the coding audit

When the four Opus documents and exam answers arrive, I will check whether the proposed design:

- compares interacting plans rather than independent predictions;
- represents abstract continuation beyond the explicit search horizon;
- treats Pokémon roles as contextual and multi-dimensional;
- predicts opponent intent and alternative plans;
- produces calibrated damage and KO distributions;
- represents both Prize routes and ways to distort them;
- preserves uncertainty about hidden information;
- generates complete turn programs with backup and stopping rules;
- learns candidate width and override thresholds empirically;
- avoids card-name tactics disguised as strategy;
- can be evaluated on unseen positions and complete games.

Only the parts that survive that audit, mechanical verification, and test evidence should become code.
