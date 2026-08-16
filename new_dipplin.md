You are working in:

```
bagel786/PokemonTCG2.0
```

Branch:

```
festival-dipplin-d0-d1
```

Current branch HEAD at task start should be approximately:

```
a1b4acbfce51ffdb944bde9bcb03186bfedce443
```

VERIFY HEAD before doing anything. If it has moved forward, use the new branch HEAD and record it.

This is a competition-strength sprint. Do not turn it into another open-ended architecture project.

The two objectives are:

1. Fix the remaining large ACTUAL-SECOND weakness of the Dipplin agent.
2. Establish whether the resulting improvement is likely GENERAL rather than merely tuned to our Grimmsnarl and Alakazam development opponents.

Do not upload anything to Kaggle.

===============================================================================
0. CRITICAL CONTEXT
===================

The accepted current candidate is D1:

```
D0 deterministic Festival planner
+
narrow bounded completed-turn search
+
CONTINUITY_PROOF
```

Current merged Stage B+C result:

```
A2 Grimmsnarl:       50.25%
d842 Grimmsnarl:     55.00%
Alakazam 2.4a:       48.75%
Alakazam 2.7:        48.25%

pooled:              50.56% = 809/1600
```

Accepted D0 over the same merged population:

```
pooled:              43.31% = 693/1600
```

The D1 improvement is therefore real and statistically meaningful.

Do NOT redesign D1 from scratch.

However, the known order asymmetry remains severe.

Earlier 400-game mechanism screen:

```
D0 actual first:     ~53.0%
D0 actual second:    ~37.5%

D1 actual first:     ~59.5%
D1 actual second:    ~42.5%
```

D1 improved both orders but did NOT solve the basic order gap.

We need a serious forced-order baseline at the CURRENT D1 bytes before changing gameplay.

===============================================================================

1. VERY IMPORTANT: BEHAVIOR CLONES ARE NOT STRENGTH BENCHMARKS
   ===============================================================================

The repository contains behavioral clones for decks such as:

```
Lucario
Crustle
Ogerpon
Bellibolt
Starmie/Froslass
```

These clones are EXTREMELY WEAK.

Known strong Grimmsnarl and Alakazam agents can score approximately 90%+ against
them.

Therefore:

DO NOT use behavior-clone win rate as evidence that Dipplin is strong.

DO NOT use:

```
candidate wins 95% vs clone
D0 wins 92% vs clone
therefore candidate is +3%
```

That comparison is meaningless because both agents are near the ceiling.

Behavior clones are allowed only for:

* exposing the Dipplin policy to different public cards/mechanics;
* checking for illegal actions;
* checking for crashes;
* checking unknown prompts;
* observing D1 search behavior in mechanically different states;
* detecting obviously insane decisions;
* generating public-state coverage.

Their game outcomes MUST NOT appear in the strength promotion score.

If both candidate and incumbent exceed roughly 80–85% against a weak clone,
explicitly mark the outcome as:

```
CEILINGED — NOT A STRENGTH METRIC
```

===============================================================================
2. ACCEPTED CONTROL MUST REMAIN IMMUTABLE
=========================================

Record:

```
git status --short
git rev-parse HEAD
git log --oneline -15
```

Create a new development branch from current HEAD:

```
opencode-second-order-general
```

Do not edit the historical accepted commits.

Preserve the current D1 package and hash.

Current sprint report:

```
docs/DIPPLIN_GENERAL_STRENGTH_SPRINT.md
```

Current final archive:

```
artifacts/dipplin_d1/submission.tar.gz
```

Current archive SHA reported by the prior sprint:

```
E5B932DB2DFFC2A860F8B5B883785885F73FD820665119687BB0C29969583BA6
```

Recompute and verify it locally rather than trusting this prompt.

The incumbent for every experiment is CURRENT D1, not old D0.

D0 remains useful as a lower control and for same-deck policy comparison.

===============================================================================
3. READ BEFORE MODIFYING
========================

Read completely:

```
docs/DIPPLIN_GENERAL_STRENGTH_SPRINT.md

ptcg_ai/dipplin/policy.py
ptcg_ai/dipplin/search.py
ptcg_ai/dipplin/objective.py
ptcg_ai/dipplin/plan.py
ptcg_ai/dipplin/resolvers.py
ptcg_ai/dipplin/damage.py
ptcg_ai/dipplin/snapshot.py
ptcg_ai/dipplin/telemetry.py

scripts/evaluate_dipplin.py
scripts/analyze_dipplin_strength.py

training/evaluate_forced_order.py

tests/test_dipplin_search.py
tests/test_dipplin_objective.py
tests/test_dipplin_tutors.py
tests/test_dipplin_sequencing.py
tests/test_dipplin_recovery.py
```

Also inspect:

```
data/meta/top_decklists.json
data/meta/rank_bands.json
```

Do not retrain any model.

Do not activate imitation.py as the main policy.

Do not activate PTCG_DIPPLIN_ROUTE_V2 by default. It was neutral in gameplay and
is not the current candidate.

===============================================================================
4. FIRST TASK: ESTABLISH CURRENT FORCED-ORDER BASELINES
=======================================================

The Stage B+C report lacks a large final actual-order matrix. Produce one BEFORE
changing gameplay.

Use:

```
training/evaluate_forced_order.py
```

Primary strong opponents:

```
exact A2 Grimmsnarl
exact d842 Grimmsnarl
authentic Alakazam 2.4a
authentic Alakazam 2.7
```

Use the immutable authentic packages already used by the prior sprint.

Run CURRENT D1:

```
200 games actual-second vs each primary opponent
100 games actual-first vs each primary opponent
```

If runtime permits, use 300 actual-second games/opponent.

Record:

```
overall
physical seat split
policy errors
opponent errors
decisions
artifact SHA
```

Do not interpret Python seed equality as paired randomness. The native deals are
unpaired.

Primary baseline statistic:

```
second_anchor_macro =
    mean(
        D1-second-vs-A2,
        D1-second-vs-d842,
        D1-second-vs-AZ2.4a,
        D1-second-vs-AZ2.7
    )
```

===============================================================================
5. RUN SAME-DECK MIRROR TESTS
=============================

This is important because it separates:

```
"our going-second policy is bad"
```

from:

```
"going second is intrinsically disadvantaged for this deck"
```

Create two sterile extracted copies of the SAME current D1 package so module state
cannot leak between hero/opponent instances.

Run:

```
D1 vs D1
    400 games hero forced actual-first
    400 games hero forced actual-second
```

Also run:

```
current D1 vs accepted D0
    300 games D1 forced actual-first
    300 games D1 forced actual-second
```

If practical, reverse package roles for sanity.

Interpretation:

D1-vs-D1 tells us the intrinsic first-player advantage of THIS deck/policy.

Example:

```
D1 mirror:
    first = 60%
    second = 40%
```

Then a 42–45% second-player result against another good agent may not indicate a
15-point policy bug. It may mostly be inherent initiative advantage.

Conversely:

```
D1 mirror:
    first = 52%
    second = 48%
```

while anchor second remains 42%

means there is still a major policy/matchup execution defect.

D1-vs-D0 is an opponent-ARCHETYPE-independent strength check because both sides use
the exact same Dipplin deck.

A major D1 advantage over D0 in the mirror is valuable evidence that D1 is not
merely exploiting Grim/AZ behavior.

===============================================================================
6. PRIMARY CODE DEFECT TO INVESTIGATE
=====================================

Current policy contains a special case equivalent to:

```
if Quick Sign is legal
and own_turn_ordinal == 1
and actual_order == second:
    QUICK SIGN IMMEDIATELY
```

This happens before the normal opening sequence containing:

```
Poffin
Poké Pad
Bug Catching Set
Hilda
Lillie
manual Basic placement
```

The intent was reasonable:

```
don't fill the Bench and accidentally make Quick Sign useless
```

But the implementation throws away much of the second player's first-turn action
advantage.

The desired strategy is NOT:

```
fill Bench blindly
then Quick Sign
```

and NOT:

```
Quick Sign immediately
```

It is:

```
reserve only the Bench slots Quick Sign still needs
→ perform useful setup that does not consume those required slots
→ use the second-player Supporter opportunity intelligently
→ Quick Sign
→ end with the best next-turn attack configuration
```

===============================================================================
7. EXPERIMENT S1: SECOND-OPENING-V2
===================================

Implement this behind:

```
PTCG_DIPPLIN_SECOND_OPENING_V2=1
```

Default OFF until qualified.

This is the ONLY deterministic gameplay change allowed in Experiment S1.

Do not simultaneously modify:

```
midgame D1
continuity proof
damage math
Boss rules
deck list
D1 belief worlds
route-v2
Xerosic behavior
```

---

## 7.1 Applicability

S1 applies only when ALL are true:

```
actual_order == "second"
own_turn_ordinal == 1
Active is Volbeat
Quick Sign is legal
```

Outside this context, candidate behavior MUST be byte/semantically equivalent to
current D1 baseline.

Add a regression test proving candidate and incumbent choose identical actions
outside this exact context.

---

## 7.2 Compute useful Quick Sign capacity

Do NOT always reserve exactly two Bench slots.

Calculate current board:

```
applin_lines =
    count(Applin 42 + Applin 92 + Dipplin)

engine_lines =
    count(Grookey + Thwackey)
```

Primary opening target:

```
at least 2 Applin lines
at least 1 engine line
```

A second engine line is useful but lower priority.

Define:

```
missing_applin = max(0, 2 - applin_lines)
missing_engine = max(0, 1 - engine_lines)
```

Then:

```
useful_quick_sign_slots =
    min(2, missing_applin + missing_engine)
```

Recompute this after every setup action.

If a needed Basic is already in hand and can be safely Benched before Quick Sign,
doing so may reduce the number of Quick Sign slots that need to remain free.

Never allow pre-Quick-Sign actions to leave fewer free Bench slots than
useful_quick_sign_slots unless the action itself satisfies that missing Basic
requirement.

---

## 7.3 Pre-Quick-Sign action priority

Do NOT use one flat list.

Use this decision process.

A. If Hilda is legal and materially improves NEXT TURN:

Hilda is considered useful when, after projected Quick Sign setup:

```
at least one Applin line will exist
```

AND Hilda can bank either:

```
missing Dipplin
missing Grass Energy
preferably both stages of its legal effect
```

Important:

The existing Hilda resolver currently reasons mostly from Pokémon ALREADY on the
board.

For SECOND_OPENING_V2, Hilda must understand:

```
"Quick Sign is guaranteed to place an Applin later this turn."
```

Therefore Hilda may legally bank a Dipplin for that future Applin even if no
Applin currently exists in play.

This behavior must be limited to the second-opening context.

B. If Hilda is not materially useful:

Lillie may be used if:

```
hand is depleted / low quality
```

Use a simple audited threshold such as handCount <= 4 initially.

Do not search cards into hand and then immediately shuffle them away with Lillie.

If Lillie is going to be used:

```
play safe permanent Basics first
→ Lillie
→ deck-search Items afterward
```

C. Non-Supporter search actions:

Use:

```
Bug Catching Set
Poké Pad
```

when they improve known next-turn requirements and do not interfere with Quick Sign.

D. Poffin/manual Basic placement:

Use them only while preserving useful_quick_sign_slots.

When Quick Sign is expected to supply missing Applin lines:

```
Poffin should prioritize Grookey
```

rather than redundantly filling the same attacker slots Quick Sign is about to fill.

When the engine line already exists:

```
Poffin/manual placement may supply Applin
```

if doing so reduces useful_quick_sign_slots appropriately.

E. Finally:

Use Quick Sign.

Quick Sign target priority in this context must fill the remaining opening
requirements:

```
missing Applin lines first
missing first Grookey line second
optional second Grookey / useful body afterward
```

Do not blindly force two Applin when two Applin lines already exist.

---

## 7.4 No overfilling

The resulting turn should prefer approximately:

```
2 attacker lines
1 engine line
optionally second engine / useful fifth body
```

Do not fill the Bench merely because space exists.

Preserve future flexibility.

===============================================================================
8. S1 TELEMETRY
===============

Add counters:

```
second_opening_v2_opportunities
second_opening_v2_hilda
second_opening_v2_lillie
second_opening_v2_poffin
second_opening_v2_pad
second_opening_v2_bug_set
second_opening_v2_manual_basic
second_opening_v2_quick_sign
```

At end of first actual-second hero turn record:

```
opening_applin_lines
opening_engine_lines
opening_bench_count
opening_hand_count
opening_has_dipplin_in_hand
opening_has_energy_in_hand
opening_has_festival_in_hand
opening_quick_sign_targets
```

Also track later:

```
first_productive_attack_turn
productive_attacks_per_game
first_attack_KOs
dead/attackless later turns
```

The prior mechanism audit showed going second produced roughly:

```
-1.12 attacks/game
-0.52 first-attack KOs/game
```

We want to see whether S1 fixes that causal chain.

===============================================================================
9. S1 EVALUATION
================

First run focused unit tests.

Then gross screen:

CURRENT D1 incumbent:
existing forced-second baseline

S1 candidate:
100 forced-second games/opponent
across A2, d842, AZ2.4a, AZ2.7

Promotion to serious screen requires:

```
zero errors
zero illegal actions
pooled second-order point estimate >= incumbent + 0.04
```

AND:

```
no individual anchor falls >0.10
```

If delta is between +0.02 and +0.04:

```
INCONCLUSIVE
allow a larger second-order screen if mechanism metrics improved clearly
```

If <= +0.01:

```
reject S1
```

If negative:

```
reject immediately
```

Serious S1 screen:

```
200–300 forced-second games per primary opponent
```

Then forced-first regression:

```
100–200 forced-first games per primary opponent
```

Required:

```
first-order pooled regression <= 0.03
```

Preferred final S1 target:

```
actual-second anchor macro >= 0.50
```

Strong:

```
>= 0.55
```

Do NOT force the implementation to hit those numbers. Reject it if it cannot.

===============================================================================
10. IF S1 FAILS: DO NOT ADD RANDOM RULES
========================================

If the deterministic second-opening route does NOT materially improve forced-second
performance:

REVERT/disable S1.

Then implement exactly ONE alternative:

```
SECOND_OPENING_PROOF
```

inside D1.

Do not run both systems simultaneously.

===============================================================================
11. SECOND_OPENING_PROOF — ONLY IF S1 FAILS
===========================================

Applicability:

```
actual second
own turn 1
Active Volbeat
Quick Sign legal
```

This proof is separate from:

```
TACTICAL_PROOF
CONTINUITY_PROOF
```

It is allowed to value next-turn setup because ordinary continuity proof cannot.

Current CONTINUITY_PROOF requires:

```
baseline replacement_ready = 0
candidate replacement_ready = 1
```

That is too strict for turn-one setup because an Applin placed this turn usually
cannot already be an attack-ready Dipplin.

---

## 11.1 Specialized opening candidates

Do NOT use the generic root candidate priority for this context.

Always include baseline Quick Sign.

Then fill remaining root slots from:

```
Hilda if useful
Poffin if engine/attacker line missing
Poké Pad if exact evolution/engine card missing
Bug Set if useful
Lillie if low-hand rebuild is useful
```

Maximum roots remains 4 total.

Preference when all are legal:

```
baseline Quick Sign
Hilda
Poffin
best(Poké Pad, Bug Set, Lillie) by missing requirement
```

Do not let generic Hilda/Lillie numeric scores silently exclude Poffin.

---

## 11.2 Opening proof boundary

Roll each candidate until:

```
Quick Sign resolves / turn ends
```

or terminal state.

Compare END-OF-OPENING state.

Do not compare unfinished roots.

---

## 11.3 Opening metric

Use a separate named vector.

Suggested semantics:

```
(
    quick_sign_completed_when_useful,
    attacker_line_floor,
    engine_line_floor,
    next_turn_attacker_path,
    next_turn_energy_path,
    next_turn_festival_or_tutor_path,
    retained_core_resources,
    free_bench_flexibility,
    negative_fragile_bench
)
```

Definitions:

attacker_line_floor:
min(2, number of Applin/Dipplin lines)

engine_line_floor:
min(1, number of Grookey/Thwackey lines)

next_turn_attacker_path = 1 if:
Applin exists in play
AND one of:
Dipplin already in hand
Hilda/Pad/Thwackey path is concretely retained
another deterministic known route exists

next_turn_energy_path = 1 if:
relevant Energy already attached
OR Basic Grass Energy in hand
OR retained Hilda provides a deterministic path

next_turn_festival_or_tutor_path = 1 if:
Festival already held/in play
OR a real Thwackey search path is established

Do NOT count vague draw probability as deterministic readiness.

Candidate must:

```
be >= baseline across EVERY valid world
```

AND
strictly improve one of:
attacker_line_floor
engine_line_floor
next_turn_attacker_path
next_turn_energy_path

AND:

```
not skip a useful Quick Sign without proving a better opening floor
```

This proof is legal only in the exact first actual-second opening context.

===============================================================================
12. GENERALIZATION: USE THREE TYPES OF EVIDENCE
===============================================

We do NOT have strong authentic local agents for every archetype.

Therefore generalization must be assessed using:

A. strong anchor outcomes
B. same-deck mirror strength
C. mechanic/property robustness

Do not fake certainty from weak clones.

===============================================================================
13. GENERALITY CHECK A: SAME-DECK POLICY STRENGTH
=================================================

This is important.

Use:

```
current D1 vs accepted D0
```

same exact Dipplin deck.

Run both actual orders.

If improved candidate beats D0 in the Dipplin mirror, especially while moving
second, that is evidence of general POLICY improvement that cannot come from
memorizing Grim/AZ opponent behavior.

Report:

```
candidate-as-first vs D0
candidate-as-second vs D0
```

Also report D1/D1 mirror order baseline.

===============================================================================
14. GENERALITY CHECK B: META MECHANICS FIXTURE SUITE
====================================================

Create:

```
tests/test_dipplin_meta_mechanics.py
```

This suite must test public-board PROPERTIES, not archetype names.

Use engine/card metadata where possible.

At minimum test:

1. Single-prize non-ex target:
   don't waste Bangle/Black Belt when they change no prize route.

2. Two-prize ex:
   modifier threshold arithmetic correct.

3. Three-prize Mega ex:
   prize value is 3;
   completed-turn reasoning values the KO appropriately.

4. Grass-weak high-HP target:
   correct Weakness math;
   minimum Bench requirement changes correctly.

5. First-hit KO versus two-hit KO:
   first-hit KO is recognized as potentially unlocking strike #2.

6. Boss:
   low-HP Bench target can be preferred when
   KO #1 unlocks another Festival strike.

7. Jamming Tower:
   Brave Bangle is disabled.

8. Crustle-style ex attack immunity:
   Dipplin is non-ex;
   ex-only immunity must NOT nullify Do the Wave.

9. Ability-based attack immunity:
   if a defender genuinely prevents attacks from Pokémon with Abilities,
   Dipplin should be recognized as nullified.

10. Neutralization Zone:
    apply exact engine semantics;
    do not invent ex restrictions for non-ex Dipplin.

11. Bench threshold:
    adding a Bench body when it changes a KO/prize threshold = useful.

12. Bench threshold no-change:
    do not force an unnecessary body solely to reach an arbitrary count.

13. Fragile Bench:
    when two prize routes are equal, prefer not to expose unnecessary
    <=50 HP Bench bodies.

14. Replacement continuity:
    equal current prizes + ready replacement can qualify only through the
    strict continuity contract.

15. Support Active:
    complete retreat→Dipplin→attack line outranks dead setup.

The test names may reference mechanics/card IDs, but runtime policy must not branch
on opponent archetype names.

===============================================================================
15. GENERALITY CHECK C: WEAK CLONE COVERAGE
===========================================

Use existing weak clones only as mechanical state generators.

Run approximately:

```
30–50 games each
```

against available:

```
Lucario
Crustle
Ogerpon
Bellibolt
Starmie/Froslass
```

If Dragapult/Lopunny clones already exist and require no new training, include them.

DO NOT TRAIN NEW CLONES FOR THIS SPRINT.

Ignore their win rates for promotion.

For each clone report only:

```
games completed
illegal actions
policy errors
unknown contexts
D1 attempts
D1 overrides
continuity admissions
timeout/error rate
important public mechanic states reached
```

Also sample at least 5 D1 override decisions from non-Grim/AZ clone games and
manually/automatically validate that the reason is mechanically sensible.

Example acceptable:

```
attach replacement Energy
because current prize result is equal and continuity is proven
```

Example suspicious:

```
arbitrary Supporter chosen because public belief world ordering happened to
prefer it
```

If clones are beaten >85%, mark:

```
outcome = CEILINGED / NOT USED
```

===============================================================================
16. SEARCH FOR REAL STRONG NON-GRIM/AZ HOLDOUTS
===============================================

Search existing repository artifacts only.

Do not build new agents.

Look for already-packaged agents with documented competitive evidence for:

```
Garchomp
Lucario
Crustle
Ogerpon
Dragapult
Lopunny
other former elite submissions
```

Use a candidate as a TRUE strength holdout only if the repository already has
credible evidence that it is not trivially weak.

Examples of credible evidence:

```
old ladder rating
elite-submission designation
strong authentic head-to-head history
competition placement
documented evaluation against strong agents
```

If no such package exists:

REPORT:

```
NO STRONG DIVERSITY HOLDOUT AVAILABLE
```

Do NOT substitute a 10%-strength behavior clone and pretend it is useful.

===============================================================================
17. OPTIONAL PUBLIC-BELIEF AUDIT
================================

Do not modify belief selection until after S1/SECOND_OPENING_PROOF evaluation.

Then audit current D1 public beliefs.

Current behavior selects compatible decklists through deterministic hash rotation.

Measure on a sample of D1 search states:

```
number compatible decklists
number compatible archetypes
selected archetypes
selected teams-weight
same-archetype-world frequency
```

If most early ambiguous searches use two arbitrary or duplicate low-value archetype
worlds, implement PUBLIC_BELIEF_V2 behind a flag.

PUBLIC_BELIEF_V2 may use ONLY:

```
data/meta/top_decklists.json
```

and public visible cards.

Compile into package:

```
deck_id
archetype
teams
exact 60 cards
```

Selection when many archetypes remain compatible:

```
world 1 = highest-team-count compatible deck
world 2 = highest-team-count compatible deck from a DIFFERENT archetype
```

If three worlds fit latency:

```
world 3 = highest-team-count compatible deck from a third archetype
```

Once visible cards narrow the opponent, naturally use the compatible archetypes.

Never use evaluator package identity.

Do NOT promote PUBLIC_BELIEF_V2 merely because it sounds more general.

Require:

```
no anchor regression
acceptable latency
reasonable override/admission behavior
```

===============================================================================
18. CURRENT D1 SEARCH MUST REMAIN CONSERVATIVE
==============================================

Do NOT globally loosen:

```
LOAD_BEARING_INDICES
TACTICAL_PROOF
CONTINUITY_PROOF
```

Do NOT increase generic search depth.

Do NOT replace lexicographic comparison with a learned scalar.

Do NOT enable generic MCTS.

Do NOT extend search into a speculative opponent turn.

Current completed-turn search remains the floor.

Only add SECOND_OPENING_PROOF if deterministic S1 fails.

===============================================================================
19. PERFORMANCE PROMOTION RULES
===============================

Primary strength data:

```
A2
d842
Alakazam 2.4a
Alakazam 2.7
```

Primary order metric:

```
forced_actual_second_macro
```

Secondary:

```
forced_actual_first_macro
four-anchor overall
same-deck candidate-vs-D0 mirror
```

A candidate is PROMOTABLE only if:

```
zero illegal actions
zero policy errors
```

AND:

```
actual-second improves materially
```

AND:

```
actual-first does not materially regress
```

AND:

```
same-deck mirror gives no evidence the change is merely matchup exploitation
```

AND:

```
meta-mechanics suite passes
```

AND:

```
weak-clone mechanical coverage shows no catastrophic failure
```

Suggested final levels:

BASIC IMPROVEMENT:
second anchor macro >= incumbent + 4pp

GOOD:
second anchor macro >= 50%
first anchor macro >= 55%

STRONG:
second >= 55%
first >= 55%
four-anchor pooled >= 55%

VERY STRONG:
both orders >=60%
while same-deck and mechanic generalization also pass

70% from both orders remains a stretch target, not an instruction to overfit.

===============================================================================
20. CROSSROADS
==============

If S1 improves second by >=5pp:
keep S1 and perform confirmation.

If S1 is neutral:
reject it and test SECOND_OPENING_PROOF.

If S1 hurts:
revert immediately.

If SECOND_OPENING_PROOF is neutral:
do NOT make it looser.
retain incumbent D1.

If anchor performance improves but same-deck mirror does not:
suspect matchup-specific exploitation.
do not promote until inspected.

If weak clone win rate changes:
ignore it unless the clone becomes unexpectedly competitive.
inspect only mechanics/errors.

If a weak clone causes crashes/unknown prompts:
fix the GENERAL mechanical defect.
do not tune gameplay to beat the clone.

If a top-meta mechanic fixture fails:
fix the property-level bug.
rerun anchors.

If there are no credible strong non-Grim/AZ local agents:
state that general strength cannot be fully proven offline.
do not manufacture evidence.

===============================================================================
21. TIME/COMPUTE DISCIPLINE
===========================

This should be a bounded sprint.

Do not spend hours training.

Do not download another huge replay corpus.

Do not write another neural model.

Do not build new weak opponent agents.

Do not run giant confirmation screens for candidates that failed 100-game gross
screens.

Order:

```
1. current forced-order baseline
2. D1/D1 and D1/D0 mirror
3. S1 implementation
4. S1 gross forced-second screen
5. serious screen if alive
6. first-order regression
7. mechanic generality suite
8. weak-clone mechanical coverage
9. strong holdout search
10. SECOND_OPENING_PROOF only if S1 failed
11. optional belief-v2 only after all of the above
```

===============================================================================
22. DELIVERABLE
===============

Create:

```
docs/DIPPLIN_SECOND_ORDER_GENERALITY.md
```

Include:

```
starting SHA
incumbent D1 archive/hash
candidate SHA

forced-second baseline table
forced-first baseline table

D1-vs-D1 mirror
D1-vs-D0 same-deck mirror

S1 result
or SECOND_OPENING_PROOF result

mechanism changes:
    attacks/game
    first productive attack
    first-hit KOs
    opening board composition

strong anchor results

meta mechanics test summary

weak clone COVERAGE summary
    explicitly label clone outcomes ceilinged and excluded

any credible strong diversity holdout

latency
errors
package hash
```

Final allowed verdicts:

```
KEEP_CURRENT_D1
PROMOTE_SECOND_OPENING_V2
PROMOTE_SECOND_OPENING_PROOF
NEEDS_LIVE_GENERALITY_TEST
REJECT_DIPPLIN_DIRECTION
```

Do not upload anything.

The most important question at the end is NOT:

```
"Did we beat Grim/AZ more?"
```

It is:

```
"Did the agent become a better Dipplin pilot, especially when moving second,
 in a way that remains justified by general game mechanics?"
```

Begin by reproducing the current D1 forced-order baseline and same-deck mirror.
Do not modify gameplay before those numbers exist.
