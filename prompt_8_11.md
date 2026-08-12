You are working in the repository:

`bagel786/PokemonTCG2.0`

The relevant remote branch is:

`festival-dipplin-d0-d1`

This is a Pokémon TCG AI competition agent. We have approximately 4 days remaining. Do not turn this into an open-ended research project.

Your job is to improve the **general gameplay strength** of the existing Thwackey/Dipplin agent as much as possible while preserving its already-good deterministic floor.

Read this entire prompt before modifying anything.

# 0. Non-negotiable objective

We want the strongest GENERAL Thwackey/Dipplin competition agent we can produce.

Known accepted D0 results:

| Opponent                | Overall | Actual first | Actual second |
| ----------------------- | ------: | -----------: | ------------: |
| exact d842 Grimmsnarl   |   53.0% |          60% |           46% |
| exact A2 Grimmsnarl     |   49.5% |          61% |           38% |
| authentic Alakazam 2.7  |   42.0% |          48% |           36% |
| authentic Alakazam 2.4a |   38.0% |          44% |           32% |
| equal-weight            |   45.6% |      ~53.25% |        ~38.0% |

These are evaluation anchors, NOT opponents to hard-code against.

Our development goals are:

### Minimum meaningful improvement

* materially exceed accepted D0 on the pooled four-agent suite;
* improve actual-second performance substantially;
* preserve the existing first-order floor;
* zero illegal selections;
* zero policy exceptions;
* no broad-regression signal on additional runnable opponent types.

### Strong target

* > =60% pooled against the four primary authentic agents;
* ideally >=60% in BOTH actual-first and actual-second play order;
* no individual major matchup catastrophically weak;
* additional-opponent confirmation shows general strength.

### Stretch target

* 65–70%+ in BOTH actual play orders against a BROADER suite.

A 70% result against only A2/d842/Alakazam is NOT sufficient if it comes from overfitting to those exact packages.

Never add runtime conditions such as:

```python
if opponent_is_a2:
if opponent_is_alakazam_2_7:
if evaluation_package == ...
```

Never use evaluator package identity.

Opponent-specific reasoning is allowed only from PUBLIC game state, such as:

* visible card IDs;
* visible HP;
* rule-box status;
* Weakness;
* Resistance;
* visible Tools/Stadiums;
* visible prevention;
* publicly inferred archetype compatible with observed cards.

The same decision rule must make sense against an unseen ladder opponent.

# 1. Git state: use the correct checkpoints

First run:

```bash
git fetch origin
git status --short
git branch -a
git log --oneline --decorate -20 origin/festival-dipplin-d0-d1
```

If the working tree contains unrelated uncommitted user work, STOP and report it.
Do not reset, stash, delete, or overwrite user changes.

Important checkpoints:

Accepted D0:

`db59ce5f97a0cf06a61f119a703b3cb4854e22d1`

Preserved D1:

`2b27c599199a6eb9f237a848fe19518ce205f4c7`

Current branch HEAD at the time this prompt was written:

`6b0f31b2557c399960ad3d2a0db45773bac5761c`

The current HEAD contains a mechanically sensible but UNQUALIFIED smarter
Xerosic discard resolver. Do NOT treat HEAD as the accepted strength baseline.

Create a fresh development branch from the D1 checkpoint:

```bash
git switch -c opencode-dipplin-strength 2b27c599199a6eb9f237a848fe19518ce205f4c7
```

If that branch already exists, create a timestamped equivalent.

Why start from `2b27c59`:

* it contains accepted D0;
* it contains the preserved D1 implementation;
* it predates the unqualified Xerosic gameplay correction;
* we want D0 as immutable reference plus D1 available for controlled improvement.

Do NOT edit `db59ce5`.
Do NOT rewrite history.
Create checkpoint commits for every accepted experiment.

# 2. Read these files completely before coding

Read, in this order:

```text
ptcg_ai/dipplin/cards.py
ptcg_ai/dipplin/snapshot.py
ptcg_ai/dipplin/plan.py
ptcg_ai/dipplin/damage.py
ptcg_ai/dipplin/resolvers.py
ptcg_ai/dipplin/policy.py
ptcg_ai/dipplin/search.py
ptcg_ai/dipplin/telemetry.py

ptcg_ai/dipplin/imitation.py
ptcg_ai/dipplin/imitation_weights.json

scripts/evaluate_dipplin.py
scripts/compare_dipplin_d0_d1.py
scripts/package_dipplin.py

tests/test_dipplin_setup.py
tests/test_dipplin_snapshot.py
tests/test_dipplin_damage.py
tests/test_dipplin_tutors.py
tests/test_dipplin_sequencing.py
tests/test_dipplin_recovery.py
tests/test_dipplin_search.py
tests/test_dipplin_packaging.py
tests/test_dipplin_imitation.py
tests/test_evaluate_dipplin.py
tests/test_compare_dipplin_d0_d1.py
```

Also inspect:

```text
data/meta/top_decklists.json
data/meta/top_team_archetypes.json
data/meta/rank_bands.json
```

And inspect all locally available PP Kawada replay/forensic artifacts under:

```text
artifacts/dipplin_forensics/
artifacts/dipplin_prompt_audit/
```

Do not make new Kaggle downloads unless explicitly necessary.
Prefer the local replay corpus.

# 3. Source-of-truth hierarchy

Whenever you reach uncertainty, DO NOT improvise.

Use this priority:

1. pinned competition engine behavior;
2. `freshstart/data/EN_Card_Data.csv`;
3. real engine-generated observations;
4. existing regression fixtures;
5. exact PP Kawada replays;
6. accepted D0 behavior;
7. public current meta data;
8. only then a new general strategy rule.

If card mechanics or prompt semantics are uncertain:

* inspect the engine;
* construct one tiny fixture;
* prove the behavior;
* then implement it.

Do not reason from memory about Pokémon card text.

# 4. Exact deck must remain unchanged initially

Use exact deck ID:

`291b0afd6ead`

Exact list:

```text
8x Basic Grass Energy

3x Applin id 42
1x Applin id 92
3x Volbeat id 88
4x Grookey id 89
4x Thwackey id 90
4x Dipplin id 93
1x Shaymin id 343

1x Unfair Stamp id 1080
4x Buddy-Buddy Poffin id 1086
4x Bug Catching Set id 1094
2x Night Stretcher id 1097
1x Sacred Ash id 1129
4x Poké Pad id 1152
1x Brave Bangle id 1175
1x Boss's Orders id 1182
1x Brock's Scouting id 1210
1x Black Belt's Training id 1211
4x Hilda id 1225
4x Lillie's Determination id 1227
4x Festival Grounds id 1245
```

Do NOT begin by tuning the deck list.

The demonstrated deck bytes are not our first suspect. The policy is.

Only consider a one-card deck change after an improved policy is qualified and
a repeated matchup-independent resource problem is demonstrated.

# 5. Important facts about the existing architecture

Do not rediscover these.

## D0

`FestivalD0Planner` is a deterministic requirement-tier planner.

Preserve:

* public-state-only decision making;
* stable lineage identity across evolution;
* exact damage calculations;
* parent-aware prompt resolvers;
* the hard invariant that the second Festival Lead attack is always taken;
* legal sanitation;
* fail-closed unknown prompt behavior;
* current/replacement attacker concepts;
* actual first/second tracking;
* zero-error baseline.

Do NOT replace D0 with:

* a generic weighted card score;
* the sparse imitation ranker;
* a neural network;
* PPO;
* Q-learning;
* a value function.

D0 is the floor.

## D1

The existing D1 is already substantial.

It includes:

* semantic option capture/remapping;
* bounded complete-turn search;
* maximum four root candidates;
* multiple public hidden-world determinizations;
* public deck-list beliefs;
* no evaluator-package identity;
* adversarial legal opponent promotion;
* fail-closed baseline fallback;
* forward/reverse replay certification for RNG/deck-touch roots;
* lexicographic completed-turn metrics;
* strict multi-world dominance;
* search cleanup;
* tight latency budgets.

Do NOT throw `search.py` away and build MCTS from scratch.

First find out why existing D1 does or does not help.

# 6. Critical evaluator fact: games are NOT paired

Read this carefully.

The native engine uses independent randomness from `std::random_device`.

Therefore:

* setting the same Python seed does NOT pair deals;
* running D0 and candidate on the same `--seed` does NOT create common random numbers;
* do not report paired deltas;
* do not use McNemar on ordinary evaluation games;
* do not claim a 2–5 percentage-point difference is deterministic evidence.

`scripts/compare_dipplin_d0_d1.py` already treats qualification as UNPAIRED.

Use:

* independent candidate/control arms;
* Wilson intervals;
* Newcombe differences where implemented;
* multiple fresh blocks;
* substantially larger samples for final confirmation.

Replay-fork tests from the SAME captured engine state are a different case and
may be compared directly, but ordinary game evaluation is unpaired.

# 7. First deliverable: a concise baseline audit

Before changing gameplay, create:

`scripts/analyze_dipplin_strength.py`

The script must consume existing evaluation JSON and/or newly generated games
and produce machine-readable JSON plus a short Markdown report.

Do NOT create another 100-page postmortem.

For accepted D0, report:

```text
overall win rate
actual-first win rate
actual-second win rate
physical seat 0
physical seat 1

per opponent:
    overall
    first
    second

first productive attack own-turn ordinal
first Festival double-attack own-turn ordinal
bench size at first attack
Thwackey present at first attack
Festival active at first attack
replacement attacker ready at end of first attack turn

frequency of:
    Quick Sign
    Hilda
    Lillie
    Boom Boom Groove
    Poffin
    Bug Catching Set
    Poké Pad
    Boss
    Bangle
    Black Belt
    Unfair Stamp

late turn with no productive attack
support Pokémon trapped Active
Festival attack offered/taken
replacement attacker unavailable after current attacker KO
unknown resolver
policy fallback
policy error
illegal action
```

Most importantly, split all mechanism rates by:

```text
D0 win / D0 loss
actual first / actual second
```

We care about causal differences, especially the current ~15-point actual-order gap.

# 8. PP Kawada replay audit: narrowly focused

Do not train a model.

Do not optimize exact-action agreement.

Use the locally cached exact PP Kawada replays only to identify general piloting
principles.

Compare expert behavior by actual order for the first three own turns.

Measure:

```text
setup Active
setup Bench
Quick Sign frequency
Quick Sign targets
Bench width after own turn 1
Bench width before first attack
number of Applin lines
number of Grookey/Thwackey lines
Energy target
Hilda versus Lillie
Festival timing
first Dipplin attack turn
replacement attacker status
Boom Boom Groove usage
attack immediately versus continue developing
```

Do not treat PP Kawada as infallible.

Do not copy exact decisions merely because the expert made them.

A replay disagreement becomes actionable only when:

1. it is repeated;
2. it expresses a general strategy principle;
3. engine mechanics support it;
4. it plausibly affects future attack/prize continuity.

# 9. Main strategic correction: unify complete-turn prize reasoning

This is the most important code improvement to investigate first.

Current D0 separately reasons about:

* `_boss_improves`
* `_modifier_crosses_threshold`
* `_damage_expansion_needed`
* replacement setup
* whether to attack

That fragmentation can make individually rational rules produce a globally
inferior turn.

Create a small explicit helper, preferably:

`ptcg_ai/dipplin/objective.py`

Do NOT place another 500 lines inside `policy.py`.

Implement a structure similar to:

```python
@dataclass(frozen=True)
class TurnRoute:
    target_serial: int | None
    bench_count: int

    attack_available: bool
    festival_double_attack: bool

    first_hit_damage: int
    first_hit_ko: bool
    first_hit_prizes: int

    second_hit_guaranteed: bool
    second_hit_min_damage: int
    second_hit_min_prizes: int

    completed_turn_guaranteed_prizes: int

    boss_used: bool
    black_belt_used: bool
    bangle_required: bool

    current_attacker_ready: bool
    replacement_ready: bool

    fragile_bench_count: int
```

Exact names may differ, but the semantics must exist.

## TurnRoute must reason about Festival Lead correctly

Festival Lead is unusual because:

* attack 1 may damage but not KO;
* attack 2 may finish the same Active;
* OR attack 1 may KO;
* the opponent then promotes;
* attack 2 hits the new Active.

Therefore:

`200 total damage` is NOT interchangeable with `100 + KO + 100 onto a new target`.

The planner must understand the prize consequences.

When a first-hit KO occurs, evaluate the second strike against all PUBLICLY legal
opponent promotions.

The opponent controls promotion.

For a deterministic general floor, use a conservative/worst-public-promotion
second-strike result.

Do not assume the opponent promotes the target most convenient for us.

## Compare Boss using complete-turn route

Boss is good when it improves the whole two-strike outcome.

It is NOT enough to compare only:

```text
current target prizes
vs
Boss target prizes
```

Examples:

* Boss may create a one-hit KO worth 1 prize and preserve attack #2.
* Leaving the current Active may require both attacks for 2 prizes.
* Depending on the second promoted target, either route can be better.

Use the complete-turn route.

## Compare Bangle / Black Belt using complete-turn route

Do not play a modifier merely because it increases damage.

Do not reject it merely because the final two-hit KO was already possible.

The critical question is:

> Does the modifier convert a two-hit KO into a FIRST-HIT KO, thereby creating
> another Festival attack target or improving the prize clock?

Explicitly test this.

# 10. Remove the unconditional four-Bench concept from prize logic

Current code effectively treats fewer than four Bench Pokémon as an automatic
reason to continue Bench expansion.

Do not blindly delete that behavior.

Replace the DAMAGE decision with exact threshold reasoning.

Calculate:

```text
minimum Bench count needed for:
    productive damage
    two-hit KO
    first-hit KO
    current intended prize route
```

If three Bench already secures the same complete-turn prize result as four:

* do not force a fourth Bench body solely because “four is the expert floor”;
* consider replacement development, fragility, and future slot value.

If four Bench changes the KO/prize route:

* aggressively reach four.

If five Bench changes the KO/prize route:

* consider reaching five.

Bench expansion should therefore be:

```text
threshold-driven first
safe free development second
```

not:

```text
always reach 4
```

Shaymin must also be conditional.

Its value can include:

* +20 Do the Wave damage as a Bench body;
* relevant Bench protection.

Its costs can include:

* consuming the final Bench slot;
* becoming an exposed target;
* blocking a replacement attacker or engine line.

Do not automatically Bench Shaymin whenever structural priorities are exhausted.

# 11. Preserve D0's current floor while changing main-turn logic

Every proposed D0 correction must be implemented behind a small feature switch
first.

Example:

```text
PTCG_DIPPLIN_ROUTE_V2=1
```

Default should remain accepted behavior until qualification.

Do not modify five independent policies at once.

Candidate sequence:

```text
C0 = accepted db59ce5 D0
C1 = route/prize reasoning only
C2 = C1 + one validated actual-second/general tempo correction
C3 = D1 over the best deterministic candidate
```

Maximum THREE substantive candidate families.

Do not produce C4, C5, C6, C7 from random parameter tweaks.

# 12. Actual-second weakness: diagnosis and correction decision tree

Current pooled numbers are approximately:

```text
actual first:  53.25%
actual second: 38.0%
```

This is the largest known weakness.

Do NOT assume why it occurs.

Use the mechanism report.

Follow this exact decision tree.

## Case A: first productive attack is materially later going second

Condition:

```text
median/mean first-attack own-turn OR
no-attack rate through own turn 2
is clearly worse going second
```

Then inspect which prerequisite causes the delay:

```text
no Dipplin
no Grass Energy
no Festival
no Thwackey
Active trapped
insufficient Bench
replacement over-development
```

Implement only the dominant cause.

A valid correction may use:

```python
plan.actual_order == "second"
plan.own_turn_ordinal
```

because play order is public and universal.

It may NOT use opponent identity.

When behind in tempo, prioritize:

```text
establish a productive current attacker
before redundant second-engine development
```

unless the extra setup is free and cannot affect the current attack/prize line.

## Case B: first attack timing is similar but second loses more after attacking

Then the defect is likely continuity.

Measure:

```text
replacement ready after attack turn
replacement ready after current Dipplin KO
dead Active turns
trapped support Active
```

If continuity is substantially worse going second, do NOT add arbitrary
second-order card priorities.

Improve replacement planning or D1 continuity search.

## Case C: attack timing and continuity are similar, but prizes differ

Then inspect:

```text
Boss target selection
first-hit KO conversion
Bangle/Belt timing
attack into prevention
Bench threshold
single-prize versus multi-prize routes
```

Use TurnRoute.

## Case D: none of the above differs enough

Do NOT invent an order-specific rule.

The order gap may partly be intrinsic or opponent tempo.

Move to D1/general search.

# 13. Xerosic: separate mechanical support from policy choice

Current branch HEAD contains a smart Xerosic forced-discard resolver that was
NOT accepted because:

```text
Alakazam 2.4a:
38% → 48%

Alakazam 2.7:
42% → 31%
```

Do not copy that resolver blindly.

But leaving Xerosic as an unknown prompt is mechanically undesirable.

Do this:

1. Reconstruct exactly what accepted `db59ce5` did on the Xerosic fixture.
2. Add explicit recognition of the Xerosic discard contract.
3. Make the initial named resolver reproduce the accepted D0 semantic discard
   behavior exactly.
4. Confirm behavior equivalence on the fixture.
5. Count the prompt as known rather than fallback.
6. Keep the smarter discard ordering as an EXPERIMENTAL variant only.

Only promote smarter discard logic if it improves a broad independent evaluation.

Do NOT tune Xerosic to Alakazam 2.4a or 2.7 specifically.

# 14. D1: audit before changing it

After C1/C2 deterministic work, evaluate CURRENT preserved D1 without rewriting it.

Collect:

```text
D1 attempts
D1 completed searches
D1 overrides
override rate
abstention reasons
timeout rate
engine errors
cleanup errors
root candidate count
world coverage
RNG replay agreement/disagreement
planning branch points
override categories
override transitions
latency p50/p95/p99/max
```

Also record outcomes for:

```text
games with >=1 override
games with zero override
actual-first override games
actual-second override games
```

The intervention analysis is mandatory.

Our previous Turn Director failed because intervention games were worse.

# 15. D1 potential ceiling problem: continuity cannot currently prove itself

Read `METRIC_FIELDS` and `LOAD_BEARING_INDICES` carefully.

The existing first five load-bearing metrics are immediate tactical outcomes:

```text
terminal_win
prizes_taken_this_turn
productive_attacks_completed
opponent_central_attacker_ko
first_attack_ko_unlocked_second_target
```

Replacement readiness is later in the tuple.

Therefore D1 cannot justify an override solely because:

```text
both lines take the same prize now
but candidate leaves a ready replacement
and D0 does not
```

This conservatism was intentional because earlier search overvalued generic setup.

Do NOT simply change:

```python
LOAD_BEARING_INDICES = range(...)
```

That could recreate the harmful Turn Director.

Instead, only if telemetry/loss analysis demonstrates continuity failures, add a
SECOND explicit admissibility mode:

```text
TACTICAL_PROOF
or
CONTINUITY_PROOF
```

## TACTICAL_PROOF

Keep existing requirements.

## CONTINUITY_PROOF

Permit an override only if ALL are true in EVERY valid public world:

```text
terminal result equal
current-turn prizes equal
productive attacks equal
central KO result equal
first-KO/second-target result equal

candidate current attacker readiness >= baseline
candidate Festival state >= baseline
candidate does not increase fragile Bench count

baseline replacement_ready == 0
candidate replacement_ready == 1

candidate does not consume the current attack
candidate does not produce fewer retained core attacker resources
candidate has no unsupported/random comparison disagreement
```

And require the root to have a direct causal relationship to continuity, e.g.:

```text
attach Energy to replacement
evolve replacement
search for a replacement component
recover a replacement component
```

Do NOT let:

```text
random Stadium play
extra Grookey
generic draw
cosmetic Bench body
```

qualify as continuity proof without a direct chain.

Add dedicated tests.

This is the safe way to let search improve the multi-turn floor without reverting
to generic “board looks nicer” scoring.

# 16. D1 public-belief worlds: inspect selection quality

Current D1 filters the 30 public top-decklists by visible opponent card
multiplicity.

This is good.

However, in early states with little visible information, many decks are
compatible.

Inspect how worlds are selected.

If they are effectively selected by arbitrary deck-ID ordering/digest rotation,
measure whether this causes excessive:

```text
no_dominance
baseline_world_coverage
rng_replay_disagreement
```

Do NOT immediately rewrite beliefs.

Only if this is a major abstention source, change world selection to a deterministic
PUBLIC meta prior:

Priority:

1. compatible exact decklists;
2. larger `teams` count in `data/meta/top_decklists.json`;
3. distinct strategic/prize archetype when a second world is needed;
4. stable deterministic tie-break.

Never use evaluator opponent package identity.

Example desired behavior with no public information:

```text
world 1 = a highly prevalent compatible current-meta deck
world 2 = another high-weight but strategically distinct compatible deck
```

not:

```text
two arbitrary hashes
```

With visible identifying cards, beliefs should naturally collapse.

The goal is GENERAL ladder robustness, not Grim/AZ specialization.

# 17. Do not activate the imitation ranker as the primary policy

There is existing code:

```text
ptcg_ai/dipplin/imitation.py
ptcg_ai/dipplin/imitation_weights.json
```

It came from PP Kawada replay work.

Do not make it the owner of D0 decisions.

A previous branch experiment already explored replay-ranker sequencing and was
superseded by the stronger deterministic correction.

Only consider the imitation model after C1/C2/D1 have been tested.

If used at all:

* use it only as an extra ROOT PROPOSAL for ambiguous MAIN decisions;
* never let it bypass deterministic safety;
* never let it control Festival second attack;
* never let it control legality;
* never let replay agreement become a promotion metric;
* require gameplay confirmation.

If implementation time becomes tight, SKIP imitation entirely.

# 18. Evaluation opponents

Primary development anchors:

```text
exact d842 Grimmsnarl
exact A2 Grimmsnarl
authentic Alakazam 2.7
authentic Alakazam 2.4a
```

Use existing immutable packages through the repository's isolated external-agent
adapter.

Do not reconstruct them.

Do not silently disable Alakazam search and call it authentic.

If a no-search Alakazam mode is used for throughput, label it explicitly and do
not use it for final confirmation.

## Generality holdout

Search the repository for already-runnable agents/proxies for:

```text
Crustle / Mega Kangaskhan
Dudunsparce / Mega Lopunny ex
Dragapult
Hydrapple
Mega Lucario
Garchomp
```

Do NOT spend a day building new opponent agents.

Use what already runs.

Classify each as:

```text
AUTHENTIC
HIGH_CONFIDENCE_PROXY
LOW_CONFIDENCE_PROXY
```

The diversity suite is primarily a regression alarm.

Do not pretend weak proxies precisely estimate ladder strength.

# 19. Staged evaluation budget

Do not run a 2,000-game confirmation after every code edit.

Use stages.

## Stage S: mechanics

Run focused unit tests.

Required:

```bash
pytest -q \
  tests/test_dipplin_setup.py \
  tests/test_dipplin_snapshot.py \
  tests/test_dipplin_damage.py \
  tests/test_dipplin_tutors.py \
  tests/test_dipplin_sequencing.py \
  tests/test_dipplin_recovery.py \
  tests/test_dipplin_search.py \
  tests/test_evaluate_dipplin.py \
  tests/test_compare_dipplin_d0_d1.py
```

All must pass.

## Stage A: gross screen

For a new candidate:

* ~50–100 games per primary opponent;
* balanced physical seats;
* report actual order;
* zero errors required.

Purpose:

* kill catastrophic candidates;
* NOT promotion.

Reject immediately if:

* errors appear;
* pooled result collapses;
* first-order strength collapses;
* a general mechanism obviously breaks.

## Stage B: serious screen

Only for survivors:

* > =200 games per primary opponent;
* independent unpaired runs;
* both actual orders;
* fresh schedule/base seed;
* same opponent package bytes.

Compare to accepted D0 using unpaired interval methods.

Do not call +/-3 points significant without evidence.

## Stage C: replicate

For the best candidate only:

* second independent block;
* > =200 games/opponent where practical;
* completely fresh native games.

Candidate must show the same directional broad improvement.

## Stage D: diversity holdout

Run the best candidate and accepted D0 against available diversity opponents.

Prioritize:

```text
Crustle
Lopunny
Dragapult
Hydrapple
Lucario
```

Do not tune against these after observing holdout unless there is a universal
mechanical bug.

# 20. Promotion score

Report all raw cells.

For development, compute:

```python
grim = mean(d842, A2)
alakazam = mean(alakazam_2_7, alakazam_2_4a)

anchor_equal = mean(all four)

actual_first = pooled actual-first result
actual_second = pooled actual-second result

robust_order = min(actual_first, actual_second)
```

Primary optimization priority:

1. zero errors;
2. improve `robust_order`;
3. improve `anchor_equal`;
4. preserve broad generality;
5. only then maximize easiest individual matchup.

This prevents the strong first-order policy from hiding a terrible second-order
policy.

Targets:

```text
GOOD:
    anchor_equal >= 55%
    robust_order >= 50%

STRONG:
    anchor_equal >= 60%
    actual_first >= 55%
    actual_second >= 55%

VERY STRONG:
    anchor_equal >= 60%
    actual_first >= 60%
    actual_second >= 60%
    no diversity collapse

STRETCH:
    >=65–70% on BOTH actual orders
    over primary + meaningful diversity evidence
```

Do NOT manipulate policy until these numbers are reached.

They are evaluation targets, not instructions to overfit.

# 21. Generality anti-overfit gates

Reject a candidate even if Grim/Alakazam improves when any of the following is
true:

```text
policy contains exact evaluation-agent identity
policy branches on local package/path/hash
opponent hidden cards are used
exact hidden opponent deck is used
diversity aggregate falls >5 percentage points from D0 without a strong reason
one common diversity matchup catastrophically collapses
actual-second improvement is purchased by a similar first-order collapse
policy exceptions >0
illegal actions >0
unknown prompt rate materially increases
D1 p99 exceeds deployment budget
D1 intervention games are materially worse than abstention games
```

Public visible-card reasoning is allowed.

Current meta deck priors in D1 are allowed because they are public and multiple
archetypes are considered.

# 22. Specific tests to add for TurnRoute

At minimum add tests for:

### Base damage route

```text
3 Bench:
60/hit
120 total before weakness over two attacks

4 Bench:
80/hit
160 total

5 Bench:
100/hit
200 total
```

Use actual engine/card weakness behavior where relevant.

### First-hit versus second-hit KO

Construct:

```text
target A survives hit 1, dies hit 2
```

and:

```text
target B dies hit 1, opponent promotes target C,
Dipplin receives attack 2
```

Ensure these are not scored as equivalent when prize outcomes differ.

### Black Belt / Brave Bangle

Test:

```text
modifier changes no KO threshold → low strategic value
modifier changes 2-hit KO to 1-hit KO → high strategic value
1-hit KO unlocks meaningful second attack
```

### Boss

Test:

```text
Boss target worth fewer prizes but first-hit KO unlocks second strike
vs
current target worth more prizes but consumes both attacks
```

Complete-turn result must decide.

### Bench expansion

Test:

```text
3→4 changes KO → expand
3→4 does not change current prize route and final slot is valuable → don't force
4→5 creates first-hit KO → expand
```

### Continuity

Test:

```text
same current prizes
same attacks
same current target result
candidate has ready replacement
baseline has none
```

D1 continuity proof should be allowed only under the strict contract above.

# 23. Do not optimize physical seat instead of actual order

Report both:

```text
physical seat
actual play order
```

But strategy should primarily respond to actual order.

Physical seat should not matter after controlling for actual order unless an
engine artifact exists.

If it does, investigate the engine/evaluator rather than adding:

```python
if seat == 0:
```

policy logic.

# 24. D0 must remain available at every step

Maintain environment flags so we can reproduce:

```text
accepted D0
candidate deterministic D0+
candidate D1
```

Search OFF must not silently change D0 behavior.

If D1 fails:

ship the best deterministic policy.

If deterministic corrections fail:

retain `db59ce5`.

Do not leave us with only an experimental branch.

# 25. Commit protocol

Commit after each meaningful accepted state.

Examples:

```text
checkpoint: reproduce accepted Dipplin D0
feat: add complete-turn Festival prize-route model
checkpoint: qualify Dipplin route-v2 screen
feat: add strict D1 continuity proof
checkpoint: qualify Dipplin D1 general-strength candidate
```

If an experiment fails, preserve its result in JSON/Markdown but do NOT make it
the default policy.

Never rewrite the accepted checkpoint.

# 26. Hard crossroads instructions

If you become uncertain, follow these exact rules.

## “Should I add another heuristic?”

NO, unless:

* a repeated failure class is measured;
* the rule is general;
* an engine/replay fixture demonstrates why it is correct.

Otherwise use search or do nothing.

## “Should I retrain a model?”

NO.

## “Should I turn on the imitation ranker?”

NO, unless deterministic route-v2 and D1 have both already been evaluated and
failed to provide improvement.

## “Should I broaden D1?”

Only by:

* improving complete-turn route understanding;
* strict continuity proof;
* better public-belief selection when telemetry proves belief selection is the
  blocker.

Do not create generic deep MCTS.

## “Should I hard-code a matchup?”

NO.

Use visible mechanics:

```text
rule-box
HP
Weakness
prevention
Tools
Stadium
prize value
bench threats
```

not archetype/package identity.

## “Should I change the deck?”

NO during the first policy sprint.

## “Candidate got +3% in 80 games?”

INCONCLUSIVE. Do not promote.

## “Candidate got -15% in 80 games?”

Kill it unless a clear evaluator defect exists.

## “D1 rarely overrides?”

Inspect abstention reasons.

Do not simply reduce all proof thresholds.

## “D1 overrides frequently but loses?”

Tighten or reject the responsible override class.

Do not average it away.

## “Going second remains weak?”

Identify whether failure is:

* attack timing;
* continuity;
* prize routing;
* inherent opponent tempo.

Only modify the corresponding mechanism.

# 27. Time discipline

Do not work endlessly.

The first sprint should produce a substantive result, not seven hours of autonomous
wandering.

Order:

```text
1. audit/reproduce
2. mechanism analysis
3. TurnRoute C1
4. gross screen
5. serious screen if alive
6. one actual-second correction if supported
7. D1 audit
8. strict D1 continuity enhancement if supported
9. final confirmation
10. package
```

Do not parallelize five speculative architectures.

Do not spend hours on documentation during gameplay development.

Do not spend hours provisioning unrelated Linux infrastructure until a strength
candidate exists.

# 28. Final package gates

For the selected finalist:

* package direct Dipplin runtime;
* exact deck;
* sterile extraction;
* deterministic build;
* archive SHA-256;
* extracted-tree SHA-256;
* zero accidental Grim/A2 weights;
* search setting explicit;
* complete package game;
* zero policy errors;
* zero illegal actions;
* latency p50/p95/p99/max;
* clean import in the best available Linux validation environment.

Do not upload to Kaggle.

# 29. Required final report

Create:

`docs/DIPPLIN_GENERAL_STRENGTH_SPRINT.md`

Keep it concise but complete.

Include:

```text
starting SHA
accepted D0 SHA
final candidate SHA

mechanism changes

accepted D0:
    four primary opponents
    actual first/second
    pooled

each tested candidate:
    same table
    independent block sizes
    intervals
    errors

D1:
    attempt rate
    override rate
    intervention-game outcomes
    abstention reasons
    latency

diversity:
    opponent
    confidence/authenticity
    D0
    candidate

final verdict
package path
hashes
remaining risks
```

Allowed verdicts:

```text
KEEP_DB59CE5_D0
PROMOTE_D0_PLUS
PROMOTE_D1
NEEDS_ONE_MORE_CONFIRMATION
REJECT_CURRENT_DIPPLIN_ARCHITECTURE
```

# 30. Final guiding principle

The current D0 is already approximately competitive with our established Grim
agents and is zero-error.

Do not destroy that floor trying to manufacture a flashy local score.

The likely path to a truly stronger agent is:

```text
accepted deterministic fundamentals
+
correct complete-turn Festival prize reasoning
+
better actual-second continuity/tempo
+
narrow proof-based search for genuinely ambiguous turns
```

not:

```text
more unrelated if-statements
```

and not:

```text
another neural-network research project
```

Our desired local score is high because we want a serious ladder agent, but the
actual objective is GENERAL GAMEPLAY STRENGTH.

Begin now with the repository audit and baseline mechanism report. Do not modify
gameplay until you can explain, quantitatively, what separates D0's actual-first
53% performance from its actual-second 38% performance.
