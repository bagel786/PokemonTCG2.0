You are working in the private repository:

    bagel786/PokemonTCG2.0

This is a SMALL, CONSERVATIVE gameplay-floor experiment.

Do not redesign the agent.
Do not train anything.
Do not add search.
Do not modify the deck.
Do not build a final submission archive.
Do not upload anything.
Do not use Kaggle/network APIs.

The task is:

    Preserve the exact high-ceiling d842 / Grimmsnarl-5k neural policy,
    but add a VERY SMALL deterministic "insurance layer" intended to reduce
    catastrophic early-game outcomes without materially changing ordinary play.

The user is specifically worried about the first 5–10 live games because the
competition rating system has extremely large early rating movements.

The same byte-identical d842 agent has historically produced very different live
scores. This task cannot eliminate matchmaking/draw variance. The objective is
instead to reduce PREVENTABLE lower-tail gameplay outcomes:

    - games where we never attack;
    - games where we take zero prizes;
    - late dead-Active turns;
    - being trapped behind Munkidori / Snorunt / Froslass while a powered
      Grimmsnarl is waiting on the Bench;
    - failing to build enough usable Marnie's bodies / Energy early;
    - ending with a productive attack available.

We MUST NOT lower the high ceiling of the original 5k model to accomplish this.

===============================================================================
0. THE MOST IMPORTANT CONSTRAINT
===============================================================================

The original d842 model remains the policy owner.

Think of the architecture as:

    exact d842 ranking
           |
           v
    narrow deterministic guardrails
           |
           v
    existing tactical attack safety
           |
           v
    legal sanitizer

NOT:

    new deterministic strategy
           |
           v
    d842 as fallback

That distinction matters.

For at least ~97–99% of ordinary decisions, the candidate should behave exactly
like d842.

Do NOT attempt to "play Pokémon better" generally.

Only intervene where we can describe a concrete low-floor failure that is both:

    A. mechanically obvious from public state/current legal options;
    B. plausibly harmful regardless of opponent archetype.

===============================================================================
1. STARTING STATE
===============================================================================

First run:

    git fetch origin
    git status --short
    git branch -a
    git log --oneline -10 origin/main

If there are unrelated uncommitted user changes:

    STOP.
    Report them.
    Do not stash/reset/delete them.

Otherwise:

    git switch main
    git pull --ff-only
    git switch -c grim-5k-variance-floor

Record the exact starting SHA.

The frozen base is:

    grimmsnarl_5k_reference.tar.gz

Pinned identities already present in the repository:

    frozen archive SHA256:
    3ECB0BBF119E23C31905E39E19ECA8F6145104AAEFFC0A5675D2FE03855BB458

    frozen model SHA256:
    D842F85ABFC44AF9F41979F91795E22C92C179B62E04D5A0A2F9C734E70AF1C3

    frozen raw deck SHA256:
    92B92BAC9F9163ECFF933B3DC39294D2CC154C8684F3C8497877661419EBC59D

    frozen canonical deck SHA256:
    C20A8A46F5C635773754F03103652F5C534B13DC622448ED2255A97234C103AF

The model weights and deck must remain byte-identical.

Do not retrain, convert, interpolate, temperature-sample, or otherwise alter the
model.

Temperature must remain 0.

===============================================================================
2. READ THESE FILES COMPLETELY BEFORE CODING
===============================================================================

Read:

    GRIM_5K_LOSS_ANALYSIS.md
    docs/LIVE_LADDER_D842_VS_A2.md
    docs/STRATEGIC_PLAYBOOK_V2.md

    ptcg_ai/grim_guardrails.py
    ptcg_ai/grim_runtime_policy.py
    ptcg_ai/tactical_shield.py
    ptcg_ai/wave1_rails.py
    ptcg_ai/grim_floor_controller.py
    ptcg_ai/prevention.py
    ptcg_ai/view.py
    ptcg_ai/safety.py

    scripts/analyze_grim_floor.py
    scripts/build_grim_guardrail_candidate.py
    scripts/audit_grim_guardrail_candidate.py
    scripts/package_gate_grim_correction.py

    tests/test_grim_guardrails.py
    tests/test_grim_runtime_policy.py
    tests/test_tactical_shield.py
    tests/test_grim_floor_controller.py

Also inspect locally available replay/evaluation artifacts under:

    artifacts/grim_5k_history/
    artifacts/grim_5k_training_bank/
    artifacts/grim_loss_buckets/
    artifacts/grim_floor_analysis/
    artifacts/grim_guardrail_candidate/
    artifacts/recovery_final/

Do not make new Kaggle downloads.

===============================================================================
3. WHAT THE EXISTING EVIDENCE ALREADY SAYS
===============================================================================

Do not rediscover these facts.

Across the existing 5k Grim deck-family replay corpus:

    567 games
    258 losses
    309 wins
    3,660 hero turns

Important broad correlations:

Energy in play at turn 8:

    0–1: 27.9% WR
    2–3: 39.0%
    4–5: 52.7%
    6–7: 67.7%
    >=8: 84.1%

But DO NOT assume the entire T8 Energy relationship is causal.
Winning preserves Energy too.

The earlier and more credible signals are more useful.

Bench width at global turn 4:

    0–1: 37.5%
    2:   44.1%
    3:   55.3%
    4:   52.7%
    >=5: 68.1%

Marnie's bodies at turn 4:

    0–1: 40.5%
    2:   55.1%
    3:   63.2%
    >=4: 53.6%

IMPORTANT:

    Three Marnie's bodies appears to be a useful early target.
    DO NOT force four or more merely to increase width.

First attacker timing:

    first attack T1–3: 64.6%
    T4–5:             56.9%
    T6–7:             54.0%
    >=T8:             37.2%
    never:             6.2%

Clean tactical buckets:

    B1:
        legal attack offered but turn ended

        appeared in ~7% of losses vs ~4% of wins

    B2a:
        dead Active but retreat already legal

        ~3% losses vs ~2% wins

    B2b:
        dead Active,
        ready attacker on Bench,
        attachment to Active can enable retreat

        ~8% losses vs ~4% wins

Late dead Active is a symptom:

    late dead-active turns/game:
        wins:  0.27
        losses: 1.08

But most late dead-Active states have no ready replacement at all.

Therefore:

    DO NOT try to fix all late dead Active states with retreat rules.

The real structural problem happened earlier.

===============================================================================
4. IMPORTANT EXISTING ARCHITECTURE
===============================================================================

The repository already contains the architecture to build on.

DO NOT use GrimFloorController as the runtime.

It is too broad.

Use the narrow:

    GrimGuardrailDirector

and:

    GrimRuntimePolicy

The runtime coordinator already:

    - preserves exact sanitized d842 as fallback;
    - lets narrow guardrails reorder d842's current legal ranking;
    - allows only approved tactical shield attack invariants;
    - fails closed;
    - does not retain option indices;
    - can run with SearchDisabledProof.

Keep search disabled.

The existing narrow guardrail already handles:

    1. setup role/width floor;
    2. Shadow Bullet over an obviously bad retreat;
    3. Shadow Bullet over Boss when current Active is already the best
       immediate public KO.

The tactical shield already handles:

    - nullified attack safety;
    - END while a productive attack exists.

DO NOT duplicate those rules.

===============================================================================
5. DO NOT REUSE THESE BROAD SYSTEMS
===============================================================================

Read them for historical context only:

    GrimFloorController
    Wave1Rail full "tempo" mode
    Strategic Playbook v2
    generic search / proof-search systems

Do not turn any of them on wholesale.

In particular DO NOT add:

    broad matchup routing
    generic Boss target rewriting
    general discard policies
    generic promotion rules
    broad early-game card ordering
    generic "always build replacement" rules
    search
    value functions
    learned rankers

Strategic Playbook v2 changed ~6% of replay decisions and regressed badly.

Our variance-floor agent should be MUCH less invasive.

===============================================================================
6. BUILD A WRAPPER, NOT A REPLACEMENT
===============================================================================

Create:

    ptcg_ai/grim_variance_floor.py

Do not replace grim_guardrails.py.

Implement:

    GrimVarianceFloorDirector

using COMPOSITION around:

    GrimGuardrailDirector

Conceptually:

    class GrimVarianceFloorDirector:
        def __init__(...):
            self.base = GrimGuardrailDirector(...)
            ...

        def apply(obs, ranked, desired):
            first ask existing base guardrail

            if existing base guardrail changes action:
                return that

            otherwise consider ONLY the new explicitly enabled
            variance-floor rules

            otherwise return exact ranking/count unchanged

        def commit(obs, final_action):
            self.base.commit(obs, final_action)
            update only semantic state needed for the narrow escape sequence

        def reset():
            self.base.reset()
            clear own state

        def telemetry():
            expose base telemetry plus new named intervention counts

Do not persist raw option indices between observations.

Persistent state may contain only semantic information such as:

    turn number
    player index
    active Pokemon serial/card ID
    pending escape stage
    whether a specific escape was initiated

===============================================================================
7. FEATURE FLAGS / ABLATION
===============================================================================

Implement each new intervention as a separately toggleable feature.

Use something simple, e.g.:

    GrimVarianceConfig(
        punk_up_floor=False,
        dead_active_escape=False,
        early_poffin_floor=False,
    )

or equivalent environment/config flags.

We need to evaluate each addition separately.

Do NOT bundle all three and then guess which one helped.

Required candidate identities:

    B0 = exact bare d842

    B1 = current existing narrow GrimGuardrailDirector
         + existing tactical attack shield
         + NO new variance rule

    B2 = B1 + useful-capacity Punk Up

    B3 = B2 + dead-Active escape

Only construct:

    B4 = B3 + early Poffin floor

IF AND ONLY IF the mechanism audit described later shows early width is still
a major unresolved candidate-side floor defect.

Do not create B5/B6/B7.

===============================================================================
8. NEW RULE #1 — USEFUL-CAPACITY PUNK UP
===============================================================================

This is the first new intervention to implement.

Reuse the already-existing Punk Up prompt handling patterns in:

    ptcg_ai/wave1_rails.py

But DO NOT import/activate the rest of Wave1Rail tempo mode.

Only reuse the mechanics necessary to resolve Punk Up.

IMPORTANT IMPROVEMENT:

The existing helper's generic capacity can over-count useful Energy on
Marnie's Impidimp.

Use exact ATTACK-READINESS capacities:

    Marnie's Impidimp:
        useful cap = 1 Dark Energy

    Marnie's Morgrem:
        useful cap = 2 Dark Energy

    Marnie's Grimmsnarl ex:
        useful cap = 2 Dark Energy

"Useful capacity" means:

    sum(
        max(0, useful_cap[card_id] - attached_energy)
        for each Marnie's Pokemon in play
    )

Never attach a third Energy to Grimmsnarl merely because Punk Up allows it.

Never attach a second Energy to Impidimp merely to spend Energy.

===============================================================================
8A. Punk Up activation
===============================================================================

When the exact effect source is Marnie's Grimmsnarl ex / Punk Up and the engine
asks ACTIVATE:

Choose YES only when:

    useful_capacity > 0

AND:

    the engine has legally offered YES

AND:

    there is still a deck from which the effect can operate.

If useful_capacity == 0:

    do not force YES.

If the prompt cannot be identified with high confidence:

    fall through unchanged.

===============================================================================
8B. Punk Up count
===============================================================================

When Punk Up asks how many Basic Darkness Energy to attach:

Desired number:

    min(
        engine legal maximum,
        useful_capacity,
        5
    )

Respect minCount/maxCount exactly.

Do NOT guess prompt encoding.

Reuse the audited engine handling already present in wave1_rails.py.

If the engine expresses count using option.number rather than desiredCount:

    select the legal option representing the intended count.

Verify with existing fixtures or create a tiny engine-derived regression test.

===============================================================================
8C. Punk Up target order
===============================================================================

When choosing where each Punk Up Energy goes, use this order:

Tier 1:
    Active Marnie's Grimmsnarl ex below 2 Energy

Tier 2:
    Benched Marnie's Grimmsnarl ex below 2 Energy
    Prefer one that is immediately promotable/usable.

Tier 3:
    Marnie's Morgrem below 2 Energy
    Prefer an older/evolvable line over one that appeared this turn when that
    distinction is public.

Tier 4:
    Marnie's Impidimp with 0 Energy
    Prefer an older/evolvable line.

Never target:

    Grimmsnarl already at >=2
    Morgrem already at >=2
    Impidimp already at >=1

The objective is:

    create attack-ready current and future Marnie's attackers

NOT:

    maximize raw Energy count.

===============================================================================
8D. Punk Up safety
===============================================================================

This rule must NOT depend on:

    opponent archetype
    opponent package
    opponent hidden information
    current evaluation opponent

It is purely own-board resource readiness.

Track telemetry:

    punk_up_seen
    punk_up_forced_yes
    punk_up_count_changed
    punk_up_target_changed
    punk_up_energy_attached
    punk_up_prevented_excess_energy
    post_punk_ready_attackers

===============================================================================
9. NEW RULE #2 — PROVABLE DEAD-ACTIVE ESCAPE
===============================================================================

This must be extremely narrow.

Canonical historical example:

    episode 91427733
    hero turn around T9

The model had:

    Energy-less Munkidori Active
    powered Grimmsnarl ex on Bench
    Basic Darkness Energy in hand

A legal attachment to Munkidori would pay its retreat cost.

The better mechanical line was:

    attach Darkness to dead Active
    → retreat
    → promote powered Grimmsnarl
    → resume real play

The original agent instead attached elsewhere and remained trapped.

We want to prevent THAT class.

We do NOT want a generic retreat planner.

===============================================================================
9A. Define "dead support Active"
===============================================================================

Only allow this new escape rule when the Active is one of the deck's support
Pokemon that cannot productively use the deck's Basic Darkness Energy for its
normal role:

    Munkidori
    Snorunt
    Froslass variants used by the exact deck

Use card IDs/constants from card_ids.py / deck metadata.

Do not include:

    Marnie's Impidimp
    Marnie's Morgrem
    Marnie's Grimmsnarl ex

in this first version.

Those Pokemon have meaningful Darkness attacks / strategic roles and require
more judgment.

===============================================================================
9B. Direct retreat case
===============================================================================

At MAIN:

If ALL are true:

    active is dead-support Active;
    active has no productive non-nullified attack;
    retreat has not already been used;
    a RETREAT option is currently legal;
    there is a ready Marnie's Grimmsnarl ex on Bench;

then promote RETREAT above d842's current choice.

Do not force this when:

    no ready Grimmsnarl exists;
    Active has a productive attack;
    retreat would promote only another dead support Pokemon;
    state interpretation is uncertain.

Reason:

    variance_floor:dead_support_retreat_to_ready_grim

===============================================================================
9C. Attach-to-escape case
===============================================================================

At MAIN:

If ALL are true:

    active is dead-support Active;
    active has no productive non-nullified attack;
    no RETREAT option is currently legal;
    retreat has not already been used;
    at least one ready Marnie's Grimmsnarl ex is on Bench;
    a legal manual Basic Darkness Energy attachment option targets the Active;
    adding exactly that Energy would satisfy the Active's retreat cost;
    the attachment is not needed to satisfy some impossible color requirement;
    there is sufficient public information to prove the resulting retreat;

then promote:

    ATTACH Basic Darkness → current Active

Reason:

    variance_floor:attach_to_escape_dead_support

Do not attach merely because the Active has no attack.

The existence of the READY BENCH GRIMMSNARL is mandatory.

===============================================================================
9D. Follow-up state
===============================================================================

This is the only new multi-prompt state machine allowed in the task.

After the final sanitized action actually commits the attach-to-escape action,
remember semantically:

    escape_pending = True
    root_turn = current turn
    dead_active_serial = current Active serial

Do NOT store the option index.

On the next MAIN prompt in the same turn:

If:

    escape_pending
    same Active is still Active
    RETREAT is now legal
    ready Grimmsnarl is still on Bench

then force RETREAT.

Reason:

    variance_floor:complete_escape_retreat

If any prerequisite disappears:

    clear escape_pending
    fall through to d842

===============================================================================
9E. Promotion after the escape
===============================================================================

After the forced RETREAT, if the engine asks which Pokemon to promote:

Only if the prompt belongs to the pending escape sequence:

    choose an attack-ready Marnie's Grimmsnarl ex.

If multiple ready Grimmsnarl exist:

    prefer:
        highest current HP
        then highest attached Energy up to useful cap
        then stable board order

Do not build a generic promotion rule.

Outside the exact escape state:

    promotion remains d842's decision.

Reason:

    variance_floor:escape_promote_ready_grim

After promotion:

    clear escape state.

Do NOT force immediate Shadow Bullet merely because we escaped.

Return control to d842.

The existing tactical shield will still stop an eventual END if a productive
attack remains available.

===============================================================================
9F. Escape state clearing
===============================================================================

Always clear escape state on:

    game reset
    deck handshake
    turn change
    player change
    target disappears
    final committed action does not match expected semantic transition
    malformed observation
    exception

Fail closed.

===============================================================================
10. OPTIONAL RULE #3 — EARLY POFFIN FLOOR
===============================================================================

DO NOT IMPLEMENT THIS IMMEDIATELY.

First run B1/B2/B3 diagnostics.

Only implement this rule if B3 still frequently reaches own turn 2 with:

    fewer than 3 total Marnie's-line bodies

AND:

    Buddy-Buddy Poffin was legally available earlier

AND:

    d842 declined to play it

in a meaningful number of losing/catastrophic games.

A suggested trigger threshold:

    at least 10 independent development episodes

or:

    >=5% of catastrophic development games

must show the pattern.

If that threshold is not met:

    SKIP B4.

===============================================================================
10A. If justified, Poffin MAIN rule
===============================================================================

At MAIN, own-turn ordinal 1 or 2 only:

Consider forcing Poffin when ALL are true:

    Poffin is legally playable;
    Bench has room;
    total Marnie's-line bodies in play < 3;
    no existing variance-floor rule is active;
    no malformed prompt;
    the effect can legally find at least one missing useful Basic.

Do not force beyond:

    3 total Marnie's-line bodies

merely to create more bodies.

Do not create 4+ Marnie's-line bodies as a target.

Do not force Poffin in later game.

Do not force it as a matchup rule.

===============================================================================
10B. Poffin target order
===============================================================================

For the Poffin nested target prompt:

Priority:

    1. Marnie's Impidimp until enough independent Marnie's lines exist;
    2. Snorunt only when no Snorunt/Froslass line exists and Bench room remains;
    3. another legal useful Impidimp if still below 3 Marnie's-line bodies.

Do not fill the Bench indiscriminately.

Respect exact 70-HP / engine search legality.

Never invent an illegal target.

===============================================================================
11. WHAT NOT TO IMPLEMENT
===============================================================================

This section is mandatory.

DO NOT implement:

    search
    MCTS
    proof search
    value search
    neural training
    PPO
    behavior cloning
    Q learning
    another model
    deck changes
    matchup routing
    Alakazam-specific rules
    mirror-specific rules
    Lucario-specific rules
    Boss rewrite beyond existing guardrail
    general promotion logic
    general retreat logic
    general resource scoring
    generic "build replacement attacker"
    generic "always play Poffin"
    generic "always attack"
    new prize-routing system
    Handheld Fan strategy
    broad Wave1Rail tempo mode

Do not turn this into Strategic Playbook v3.

===============================================================================
12. PRESERVE THE EXISTING TACTICAL SHIELD
===============================================================================

The existing tactical shield already handles:

    selected nullified attack when a better legal alternative exists;
    END while a productive attack exists.

Do not replace it.

Do not broaden it.

Do not duplicate `end_with_productive_attack`.

The variance-floor director is only adding:

    useful Punk Up
    dead-support escape
    optional narrowly proven Poffin floor

===============================================================================
13. TESTS — REQUIRED BEFORE ANY GAMEPLAY EVALUATION
===============================================================================

Create:

    tests/test_grim_variance_floor.py

Do not edit old tests merely to make them pass.

Run existing relevant tests too.

Required new tests:

-------------------------------------------------------------------------------
13A. Exact fallthrough
-------------------------------------------------------------------------------

When no variance rule matches:

    resulting ranked list == input ranked list
    desired count == original desired count
    reason is None

Test many ordinary MAIN and nested prompts.

-------------------------------------------------------------------------------
13B. Existing guardrail remains intact
-------------------------------------------------------------------------------

Test that wrapper preserves:

    existing setup behavior
    shadow-over-retreat
    shadow-over-Boss active-KO behavior

exactly.

-------------------------------------------------------------------------------
13C. Punk Up useful cap
-------------------------------------------------------------------------------

Fixtures:

1. Impidimp E0:
       useful capacity contribution = 1

2. Impidimp E1:
       contribution = 0

3. Morgrem E0:
       contribution = 2

4. Morgrem E1:
       contribution = 1

5. Morgrem E2:
       contribution = 0

6. Grimmsnarl E0:
       contribution = 2

7. Grimmsnarl E1:
       contribution = 1

8. Grimmsnarl E2:
       contribution = 0

9. board:
       Grim E2
       Morgrem E2
       Impidimp E1
   total useful capacity = 0
   rule must not force Punk Up activation

10. board:
        Active Grim E1
        Bench Morgrem E0
        Bench Imp E0
    capacity = 1 + 2 + 1 = 4
    intended count = 4 if engine permits

11. target order:
        Active Grim E1
        Bench Grim E0
        Morgrem E0
        Imp E0

    Energy should finish:
        Active Grim
        then Bench Grim
        then Morgrem
        then Imp

without exceeding caps.

-------------------------------------------------------------------------------
13D. Dead support — no false positives
-------------------------------------------------------------------------------

No intervention if:

    Active is ready Grimmsnarl
    Active is Impidimp
    Active is Morgrem
    no ready Bench Grim exists
    retreat already used
    no Dark attachment to Active exists
    attachment would still not pay retreat
    Active has productive legal attack
    candidate only has another support Pokemon on Bench

-------------------------------------------------------------------------------
13E. Dead support direct retreat
-------------------------------------------------------------------------------

Fixture:

    Munkidori Active
    retreat legal
    ready Grim E2 on Bench

d842 ranks something else first.

Variance floor must rank RETREAT first.

-------------------------------------------------------------------------------
13F. Canonical attach escape
-------------------------------------------------------------------------------

Recreate episode 91427733 T9 mechanics as closely as existing fixture data allows:

    Munkidori Active, E0
    ready Grim E2 on Bench
    Basic Darkness Energy in hand
    legal ATTACH → Active
    retreat currently unavailable

Expected:

    choose attachment to Active

Then next MAIN state:

    Munk Active E1
    RETREAT legal
    Grim still ready

Expected:

    choose RETREAT

Then promotion:

    choose ready Grim

Then clear state.

-------------------------------------------------------------------------------
13G. State cleanup
-------------------------------------------------------------------------------

Test:

    reset
    new turn
    target disappearance
    failed/malformed prompt
    alternate final committed action

all clear pending escape safely.

-------------------------------------------------------------------------------
13H. No raw option persistence
-------------------------------------------------------------------------------

Reorder option indices between prompts.

The state machine must still resolve by semantic current state.

-------------------------------------------------------------------------------
13I. Optional Poffin tests
-------------------------------------------------------------------------------

Only add these if B4 is implemented.

Test:

    own turn 1, 1 Marnie's body → Poffin can intervene
    own turn 2, 2 Marnie's bodies → Poffin can intervene
    own turn 3 → no intervention
    already 3 Marnie's bodies → no intervention
    Bench full → no intervention

===============================================================================
14. TEST COMMAND
===============================================================================

At minimum run:

    pytest -q \
      tests/test_grim_variance_floor.py \
      tests/test_grim_guardrails.py \
      tests/test_grim_runtime_policy.py \
      tests/test_tactical_shield.py

Also run:

    pytest -q tests/test_grim_floor_controller.py

If old GrimFloorController tests fail for a pre-existing reason:

    report them separately.

Do not change GrimFloorController unless the same underlying helper bug also
affects our runtime.

===============================================================================
15. INTERVENTION AUDIT BEFORE FULL GAMES
===============================================================================

Use existing development replay infrastructure.

We want to know how much the candidate changes d842.

For B1/B2/B3, report:

    hero decisions
    changed decisions vs exact d842
    percentage changed

by reason:

    existing setup
    existing shadow-over-retreat
    existing shadow-over-Boss
    Punk Up activation
    Punk Up count
    Punk Up target
    attach-to-escape
    escape retreat
    escape promotion
    optional Poffin

Also report change rate by own-turn ordinal:

    0/setup
    1
    2
    3
    4+
    
And actual order:

    first
    second

Target:

    <=3% total decision disagreement with d842

Prefer:

    <=2%

The setup prompts may cause many games to contain an intervention while still
keeping total decision disagreement very small.

If total decision disagreement exceeds 5%:

    STOP.
    Do not evaluate further.
    Something became too broad.

===============================================================================
16. MECHANISM METRICS
===============================================================================

Create:

    scripts/evaluate_grim_variance_floor.py

or extend an existing diagnostic script cleanly.

Do not duplicate the whole evaluation framework.

The output must report these GAME-LEVEL metrics:

    win
    actual order
    physical seat

    ever attacked
    total attacks
    Shadow Bullet attacks

    prizes taken
    prizes conceded

    zero-attack game
    zero-prize game
    blowout loss

Define blowout loss for diagnostic purposes as:

    loss with public final prize margin >=4

Use the same approximate terminal/public-prize convention already used by the
repository.

Also report:

    first Marnie's Grimmsnarl own-turn ordinal
    first ready Grimmsnarl own-turn ordinal
    first productive attack own-turn ordinal

    total board width after own turn 1
    total board width after own turn 2

    Marnie's-line bodies after own turn 1
    Marnie's-line bodies after own turn 2

    Energy in play after own turn 2
    Energy in play after own turn 3
    Energy in play after own turn 4

    ready attackers after own turn 2/3/4

    late dead-support Active turns
    dead-support Active with ready Bench Grim
    trapped support Active turns

    Punk Up activation/count/targets
    useful Energy produced by Punk Up
    excess Energy placed above attack-readiness cap

    guardrail intervention reasons
    policy errors
    illegal actions

"Late" should primarily use own-turn ordinal rather than raw global turn to
avoid first/second-order confounding.

Suggested:

    own-turn ordinal >=4

for the new metric.

Also retain existing global-turn metrics when available for continuity with
older reports.

===============================================================================
17. COMPOSITE CATASTROPHIC FLOOR RATE
===============================================================================

Report all components separately.

Also define one diagnostic union:

    catastrophic_floor_game =
        zero_attack_game
        OR zero_prize_game
        OR blowout_loss

Do not double-count a game containing multiple failures.

Report:

    catastrophic_floor_rate

overall and by:

    actual first
    actual second

This is NOT the only promotion criterion.

It is a lower-tail diagnostic.

===============================================================================
18. BURN-IN RISK DIAGNOSTIC
===============================================================================

The user's concern is the first 5–10 live games.

Do NOT claim to reproduce Kaggle TrueSkill.

Instead build a clearly labelled LOCAL DIAGNOSTIC.

From the completed local evaluation games, bootstrap 20,000 random sequences
with replacement.

For each policy estimate:

For a 5-game block:

    P(wins <= 1)
    P(wins <= 2)
    P(at least one zero-attack game)
    P(at least one catastrophic-floor game)
    distribution of longest loss streak

For a 10-game block:

    P(wins <= 3)
    P(wins <= 4)
    P(at least one zero-attack game)
    P(at least one catastrophic-floor game)
    distribution of longest loss streak

Stratify once by mixed actual order and once 50/50 first/second.

Label output prominently:

    LOCAL BURN-IN RISK PROXY
    NOT A KAGGLE SCORE FORECAST

Do not calculate a fake expected leaderboard rating.

===============================================================================
19. EVALUATION STRUCTURE
===============================================================================

We need both:

    A. floor-risk evidence
    B. broad strength non-regression

Do not optimize entirely on one opponent.

===============================================================================
19A. Exact d842 direct mirror
===============================================================================

This is the cleanest strength anchor.

Run candidate directly against exact d842 with the same exact deck.

Balance actual play order.

Stage A:

    at least 200 games total
    100 candidate actually first
    100 candidate actually second

If candidate is obviously terrible:

    stop.

Stage B for surviving candidate:

    at least 800 games total if runtime permits
    400 first
    400 second

Report:

    candidate WR
    actual-first WR
    actual-second WR
    Wilson intervals

Interpretation:

    >50% means candidate is directly outperforming frozen d842 in the mirror
    on that sample.

Do NOT assume a tiny 51% result is proven.

The point is primarily to catch regression.

===============================================================================
19B. Broad external opponent suite
===============================================================================

Use existing immutable/runnable agents only.

Locate and verify locally existing implementations for:

    master_v1
    replay_refresh
    v2_2
    A2 if exact immutable artifact is available
    Alakazam 2.4a
    Alakazam 2.7

Then locate any ALREADY runnable diversity agents/proxies for:

    Lucario
    Crustle / Kangaskhan
    Lopunny
    Garchomp
    Bellibolt
    Dragapult

Do not build missing opponents.

Do not spend hours making new proxies.

Classify every opponent:

    AUTHENTIC
    HIGH_CONFIDENCE_PROXY
    LOW_CONFIDENCE_PROXY

===============================================================================
20. DEVELOPMENT VS HOLDOUT
===============================================================================

To reduce accidental overfitting:

Use as development anchors initially:

    exact d842 mirror
    master_v1 if available
    Alakazam 2.4a

Do not inspect final candidate performance against every available opponent after
every tweak.

Reserve at least:

    Alakazam 2.7

and:

    one non-Grim/non-Alakazam runnable opponent

as final directional holdouts.

If exact A2 is easily runnable, it may also be part of final confirmation rather
than early tuning.

No rule may mention any of these opponent identities at runtime.

===============================================================================
21. EVALUATION SAMPLE STAGES
===============================================================================

Do not burn hours on weak variants.

Stage 0:
    focused tests

Stage 1:
    replay intervention audit

Stage 2:
    gross gameplay screen
    ~50 games/opponent/actual-order where practical

Purpose:
    kill catastrophic candidates only

Stage 3:
    serious screen for best candidate only

Use:

    d842 direct mirror
    development population

At least several hundred games.

Stage 4:
    one independent final holdout

Only after code is frozen.

Do not repeatedly tune after seeing holdout.

===============================================================================
22. STATISTICS
===============================================================================

Do not pretend native games are paired merely because the same Python seed was
used.

Unless the currently used engine runner explicitly proves deterministic common
randomness:

    treat arms as UNPAIRED.

Use:

    raw W/L
    Wilson 95% interval
    absolute percentage-point difference

For broad independent baseline/candidate arms, use an unpaired difference
interval where the repository already supports one.

Do not say:

    "candidate is +2% proven"

from a tiny screen.

===============================================================================
23. NON-REGRESSION STANDARD
===============================================================================

Because this experiment is primarily about the lower tail, we do not require
statistically significant WR improvement.

But we DO require no evidence of meaningful regression.

A candidate is ELIGIBLE FOR USER REVIEW when:

HARD:

    zero policy errors
    zero illegal actions
    exact model hash unchanged
    exact deck hash unchanged
    no search
    no hidden information
    total decision disagreement <=3%, preferably <=2%

AND:

    catastrophic_floor_rate improves meaningfully
    OR one major catastrophic component improves materially

AND:

    there is no clear broad WR regression.

"Clear broad WR regression" means ANY of:

    direct d842 mirror point estimate <47%

OR:

    broad development aggregate drops >=5 percentage points

OR:

    actual-first OR actual-second drops >=7 points

OR:

    one common authentic opponent collapses >=10 points and the effect
    survives a reasonable replicate

OR:

    new intervention games are consistently worse in every screen.

These are kill thresholds, not statistical promotion claims.

===============================================================================
24. PREFERRED SUCCESS SIGNAL
===============================================================================

Ideal outcome:

    d842 mirror:
        roughly >=50%, preferably trends above 50

    broad aggregate:
        flat or higher

    zero-attack rate:
        materially lower

    zero-prize rate:
        lower

    catastrophic_floor union:
        materially lower

    late dead-support Active:
        materially lower

    first attacker timing:
        same or earlier

    actual-first:
        no regression

    actual-second:
        no regression, ideally improved

A particularly attractive result would be:

    similar mean WR
    but 30–50% relative reduction in zero-attack / catastrophic-floor games

because that is exactly the insurance behavior we want.

===============================================================================
25. INTERVENTION-LEVEL ANALYSIS
===============================================================================

For every new reason, report:

    number of decisions
    number of games containing reason
    first/second split

For games containing:

    punk_up_floor

report:

    win rate
    zero-attack rate
    zero-prize rate
    post-Punk ready attackers

For games containing:

    dead_active_escape

report:

    how often sequence completed
    attach succeeded
    retreat succeeded
    ready Grim promoted
    subsequent productive attack occurred
    game outcome

This is descriptive only.

Do not infer causality from intervention-game WR because intervention states are
not random; hard games trigger more guardrails.

===============================================================================
26. OPTIONAL POFFIN DECISION
===============================================================================

After B3 evaluation, make this mechanical decision:

IF:

    B3 still has substantial early underdevelopment

AND:

    replay audit identifies >=10 independent catastrophic games where:
        Poffin was available during own turn 1–2
        Marnie's-line body count <3
        d842 declined to play Poffin
        board remained underdeveloped

THEN:

    implement B4 as the narrowly defined Poffin floor.

ELSE:

    do not implement B4.

Do not "try it anyway."

===============================================================================
27. CROSSROADS INSTRUCTIONS
===============================================================================

If uncertain whether to add a rule:

    DO NOT ADD IT.

If a rule requires knowing opponent archetype:

    DO NOT ADD IT.

If a rule would change an ordinary successful d842 line:

    DO NOT ADD IT without a repeated measured floor failure.

If a rule needs search:

    SKIP IT.

If dead-Active escape requires more than:
    attach → retreat → ready-Grim promotion

    SKIP IT.

If Punk Up prompt semantics are unclear:

    inspect existing wave1_rails.py and engine fixtures;
    do not invent behavior.

If broad win rate rises but catastrophic outcomes rise too:

    candidate fails the purpose of this experiment.

If catastrophic outcomes improve but WR is clearly worse:

    candidate is rejected.

If catastrophic outcomes improve and WR is statistically inconclusive/flat:

    mark PROMISING_FOR_USER_REVIEW.

If tiny local WR changes direction between runs:

    do not chase them with another rule.

If optional Poffin is ambiguous:

    leave it disabled.

===============================================================================
28. NO FINAL PACKAGING
===============================================================================

IMPORTANT:

Do NOT create the final Kaggle submission archive.

Do NOT run upload scripts.

Do NOT run final Linux packaging infrastructure.

Temporary extraction/staging directories required for local native evaluation are
allowed.

Temporary local archives are allowed ONLY if an existing evaluator absolutely
requires an archive input.

Do not retain or label them as a submission candidate.

The user will review the result before packaging.

===============================================================================
29. OUTPUT FILES
===============================================================================

Create:

    ptcg_ai/grim_variance_floor.py

    tests/test_grim_variance_floor.py

    scripts/evaluate_grim_variance_floor.py

    docs/GRIM_5K_VARIANCE_FLOOR_RESULT.md

And evaluation artifacts under:

    artifacts/grim_variance_floor/

Suggested:

    baseline_d842.json
    existing_guardrail_b1.json
    punk_b2.json
    escape_b3.json
    poffin_b4.json              # only if B4 justified
    final_holdout.json
    intervention_audit.json
    burnin_proxy.json

===============================================================================
30. REPORT FORMAT
===============================================================================

`docs/GRIM_5K_VARIANCE_FLOOR_RESULT.md` must start with:

    STARTING SHA:
    FROZEN MODEL SHA:
    FROZEN DECK SHA:
    FINAL EXPERIMENT SHA:

Then a table:

| Policy | Mirror WR | First | Second | Broad WR | Zero attack | Zero prize | Catastrophic floor |
|--------|-----------|-------|--------|----------|-------------|------------|--------------------|

Include:

    B0 exact d842
    B1 existing narrow guardrail
    B2 + Punk Up
    B3 + escape
    B4 if attempted

Then:

### Intervention rates

### First/second mechanism differences

### Punk Up results

### Dead Active escape results

### Optional Poffin decision

### Local 5-game burn-in proxy

### Local 10-game burn-in proxy

### Diversity / holdout

### Known statistical limitations

### Recommendation

Allowed recommendation labels:

    KEEP_EXACT_D842
    EXISTING_GUARDRAIL_ONLY
    PROMISING_VARIANCE_FLOOR_B2
    PROMISING_VARIANCE_FLOOR_B3
    PROMISING_VARIANCE_FLOOR_B4
    INCONCLUSIVE_DO_NOT_PACKAGE
    REJECT_VARIANCE_FLOOR

Do not say:

    "this will lower Kaggle rating SD"

Instead say precisely what was measured, e.g.:

    "reduced local zero-attack rate from X to Y without a detected broad
     gameplay regression"

===============================================================================
31. COMMIT POLICY
===============================================================================

Commit code once tests pass:

    feat: add conservative d842 variance-floor guardrails

After evaluation/report:

    docs: record Grim 5k variance-floor experiment

Do not merge to main.

Do not push unless explicitly instructed.

===============================================================================
32. TIME / ITERATION LIMIT
===============================================================================

This is NOT an all-day autonomous task.

Maximum:

    B0
    B1
    B2
    B3
    optional B4 only if precondition is met

One implementation cycle per feature.

Do not invent additional candidate families.

Do not retrain.

Do not start a new architecture.

If B2/B3 are neutral or harmful:

    stop and report.

If B3 is clearly promising:

    stop after final holdout and report.

Do not package.

===============================================================================
33. FINAL MENTAL MODEL
===============================================================================

The objective is not:

    make d842 "more strategic"

It is:

    let the high-ceiling neural policy play normally,
    but prevent a tiny number of mechanically obvious ways it can throw away
    one of the extremely valuable early ladder games.

The ideal agent should feel exactly like d842 in normal games.

The deterministic layer should become visible only when d842 is about to do
something like:

    start with an unnecessarily empty board;
    waste/decline useful Punk Up fuel;
    remain trapped behind a support Active while a ready Grim is waiting;
    end despite a productive attack.

If you find yourself implementing a general Pokémon strategy engine:

    STOP.

Begin by reproducing exact d842 and B1 behavior before writing the two new
variance-floor rules.