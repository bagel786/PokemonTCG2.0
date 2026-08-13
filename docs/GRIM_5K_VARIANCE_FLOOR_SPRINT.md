# GRIM 5K VARIANCE FLOOR — SCREENING / DISCOVERY SPRINT

Working repository: bagel786/PokemonTCG2.0
Branch: grim-5k-variance-floor
Time budget: approximately two days (Pokémon TCG AI Battle competition)

THIS IS A SCREENING / DISCOVERY SPRINT.

NOT authorized to:
- upload anything to Kaggle
- run any 1,000+ game expansion
- run a final promotion gate
- combine several experimental mechanisms
- rewrite the architecture broadly
- replace the qualified baseline

Even if an experiment looks extremely strong, STOP before the expensive
confirmation and leave it for an independent Codex Ultra code review.

============================================================
0. OPERATING PRINCIPLE
============================================================

The goal is NOT "make something different from A2."

The goal is:

Find ONE mechanism with credible potential for approximately +4 percentage
points overall strength, or produce enough negative evidence to stop Grim
development safely.

Small +1 pp improvements are not the goal of this sprint.

Do not optimize validation loss, replay agreement, or aesthetically pleasing
architecture.

Gameplay is the target.

============================================================
1. PRESERVE THE EXACT BASELINE
============================================================

The immutable control is the already-qualified:

A2 + Damage V0

It should exist under something similar to:

artifacts/grim_damage_conversion/winner/grim_a2_damage_v0.tar.gz

The authoritative report is:

docs/GRIM_DAMAGE_CONVERSION_MICROSPRINT.md

Before modifying anything:

- inspect git status
- do NOT destroy or reset uncommitted work
- record the exact starting branch and commit
- if appropriate, create a separate sprint branch/worktree
- locate the exact qualified Damage V0 archive
- verify its documented SHA256
- verify the A2 model hash
- verify the deck hash
- verify tactical shield configuration
- verify Damage V0 is enabled exactly as qualified
- verify runtime search is absent/disabled as qualified

Current remote branch head was:

8e4240d3bea70611bc12aabc98ddfe8ef6d1f341

when this prompt was written.

VERIFY rather than blindly resetting to that SHA if newer local work exists.

Define this exact behavior as:

R0 = exact qualified A2 + Damage V0

Every control game must use R0.

Every challenger must be implemented as a thin change ON TOP OF R0.

If the qualified archive is missing:

do not silently substitute plain A2.

You may reconstruct R0 only if the resulting archive/model/configuration can
be proven to match the documented qualified package or reproduce its exact
behavior. Otherwise STOP and report "QUALIFIED BASELINE NOT REPRODUCIBLE."

============================================================
2. IMPORTANT CORRECTION ABOUT THE PLAY BUG
============================================================

A2 uses schema 2.

Current code indicates that MAIN/PLAY options are not cleanly relationally
bound to the actual hand card represented by that option.

The state representation knows which cards exist somewhere in our hand,
but the option scorer does not reliably receive:

    this PLAY option = Team Rocket's Petrel
    this PLAY option = Rare Candy
    this PLAY option = Unfair Stamp

Instead it has historically depended heavily on positional/index information.

This is a REAL representation defect.

However:

DO NOT call the previously reported ~38.1% number "gameplay accuracy."

It is replay/teacher agreement.

A recorded winning action is NOT guaranteed to be the optimal action.

Your first job is to measure whether this defect has enough opportunity
surface to matter in gameplay.

============================================================
3. EXPERIMENT A0 — PLAY OPPORTUNITY + BLINDNESS AUDIT
============================================================

Do this before training or behavior modification.

Use authentic exact-Grim replay data.

Analyze MAIN/PLAY prompts.

Break out:

- actual first
- actual second
- own-turn ordinal
- especially first two own turns
- wins
- losses
- opponent family where known

Measure:

- total decisions
- total MAIN/PLAY prompts
- prompts with >=2 distinct playable CARD identities
- games containing >=1 such prompt
- losses containing >=1 such prompt
- early-second games containing >=1 such prompt
- early-second losses containing >=1 such prompt

For recorded-action comparisons report:

"A2 top-1 agreement with recorded action"

NOT:

"A2 accuracy"

Break agreement out by important Trainer identity where possible:
- Team Rocket's Petrel
- Rare Candy
- Unfair Stamp
- Dawn
- Hilda
- Boss's Orders
- Night Stretcher
- setup/search cards
- other common Grim trainers

Use stable semantic card identities, not raw prompt-local option indices.

DUPLICATES:

If two identical copies of the same card appear in hand, do not count choosing
copy A instead of copy B as a semantic error unless the copies genuinely differ
in a meaningful visible way.

------------------------------------------------------------
A0.1 OPPORTUNITY CEILING
------------------------------------------------------------

Calculate a crude but useful upper bound.

For the proposed intervention scope, count:

baseline LOSS games that contain at least one eligible PLAY opportunity.

If a mechanism can only act in those games, then even a magical perfect fix
cannot convert more losses than that.

Report:

- eligible-loss games / total games
- eligible-second-loss games / total second games
- corresponding theoretical maximum absolute uplift

This is an upper bound, not an expected gain.

If the opportunity surface is clearly too small to support a meaningful gain,
STOP the PLAY track rather than training because the architecture looks
interesting.

------------------------------------------------------------
A0.2 HAND-POSITION SENSITIVITY
------------------------------------------------------------

Perform only as a DIAGNOSTIC.

Where mechanically reconstructable, create semantically equivalent feature
views in which:

- hand card ordering is permuted
- the PLAY option's hand index is consistently updated
- the multiset of cards and all legal semantic choices stay the same

Measure whether A2's chosen SEMANTIC CARD changes.

Important caveat:

hand position can correlate with draw history in the real engine, so
permutation sensitivity is evidence of reliance on a brittle positional proxy,
NOT proof that every changed choice is wrong.

Do not use this diagnostic as promotion evidence.

Produce A0 report before proceeding.

============================================================
4. EXPERIMENT A1 — P0 FROZEN PLAY-IDENTITY PROBE
============================================================

Only run if A0 shows a meaningful opportunity surface.

Create the smallest possible candidate.

For OptionType.PLAY only, expose the actual hand card represented by:

hand[option.index]

as the PLAY option's source card identity.

Do NOT:

- enable full schema 4
- enable schema 5
- change global feature dimensions
- change numeric dimensions
- retrain A2
- change A2 weights
- change count prediction
- change Damage V0
- change tactical shield
- enable search
- change non-PLAY encoding

This is an OUT-OF-DISTRIBUTION probe.

Frozen A2 was not trained to interpret PLAY source embeddings this way.
Therefore failure does NOT falsify the concept of a learned PLAY-aware model.

Before gameplay, prove:

- non-PLAY feature tensors are unchanged
- non-PLAY semantic decisions match R0
- Damage V0 contexts still behave exactly as R0 unless the root trajectory
  changed because of an earlier PLAY choice

Choose the P0 intervention scope from the A0 evidence BEFORE seeing P0 gameplay
results.

Prefer a narrow scope if the opportunity is concentrated, e.g. actual-second
early turns.

Do not try many scopes and select the luckiest gameplay result.

Run only approximately:

150-200 paired games

for this probe.

Use an untouched screening seed set.

Report:

- pairs
- candidate wins
- R0 wins
- candidate-only wins
- R0-only wins
- paired delta
- paired 95% CI
- intervention frequency
- semantic decisions changed
- order breakdown
- opponent breakdown
- errors
- latency

Do not require the small screen CI to exclude zero.

But we are looking for a LARGE point estimate.

Clearly negative / near zero / ~+1-2 pp:
REJECT P0.

Roughly +4-5 pp or larger in its relevant stratum with no obvious regression:
mark

PASSING SCREEN — CODE REVIEW REQUIRED

and DO NOT EXPAND.

============================================================
5. EXPERIMENT A2 — CAUSALLY LABELED PLAY-ONLY RESIDUAL
============================================================

Attempt this ONLY if:

1. A0 says PLAY has enough opportunity surface
AND
2. P0 does not already provide a clean passing candidate
AND
3. enough trustworthy training signal can be generated in the remaining time

Do NOT build a replacement global policy.

R0 stays frozen.

Build the smallest practical residual that can only adjust rankings among
eligible MAIN/PLAY options.

Concept:

R0 produces normal option logits.

For PLAY options only, a tiny specialist can see the ACTUAL card identity and
a small amount of already-public context, and add a bounded correction to R0's
PLAY logits.

Every non-PLAY decision must remain exact R0.

Fail closed to R0 for:
- exceptions
- unsupported contexts
- malformed state
- nonfinite values
- residual load failure

Keep the model small.

Do NOT create a new general-purpose neural policy.

------------------------------------------------------------
5.1 DO NOT BLINDLY IMITATE WINNING REPLAYS
------------------------------------------------------------

A winning replay action is a HYPOTHESIS, not ground truth.

Recent community discussion suggested generating many strategy-preserving
agents from replays and using them as training data.

Do NOT do that here.

Do not train a large "agent swarm."

Do not treat an LLM-generated rule agent as a positive teacher.

Instead use:
- winning replays
- recent losses
- opponent strategies
- human/LLM hypotheses

only to identify INTERESTING STATES and CANDIDATE ALTERNATIVES.

Let the simulator decide which alternatives are actually better.

------------------------------------------------------------
5.2 CAUSAL PLAY LABEL GENERATION
------------------------------------------------------------

For an eligible PLAY state:

1. identify meaningful distinct legal PLAY-card choices
2. represent choices semantically by card identity
3. compare R0's choice with plausible alternatives
4. branch from matched initial conditions / determinizations
5. force only the tested PLAY choice
6. afterward return to R0
7. evaluate longer-horizon / terminal outcome when feasible
8. repeat across multiple determinizations/seeds
9. retain only clear, repeatable preferences
10. discard ambiguous comparisons

WHY returning to R0 is appropriate:

The proposed deployment changes only the PLAY decision.
Therefore the counterfactual should answer:

"If we changed this PLAY choice and then let our actual deployed baseline
continue, would we do better?"

Do NOT assume a human/LLM teacher will execute the rest of the plan for us.

------------------------------------------------------------
5.3 EXISTING COMPLETE-TURN ORACLE CAUTION
------------------------------------------------------------

Inspect:

training/complete_turn_corrections.py

It already contains useful machinery for:

- stable semantic actions
- prompt-index-independent replay
- common determinizations
- fail-closed branch coverage
- completing the current turn

Reuse this machinery where useful instead of reinventing it.

BUT:

its complete-turn public board score is NOT automatically a terminal win label.

A move can look better at the end of this turn and still lose later.

Use complete-turn metrics to:
- reject nonsensical alternatives
- shortlist candidates
- validate mechanical completion

Prefer terminal or sufficiently long continuation for the actual causal
training preference whenever feasible.

If only a proxy score is available, label the evidence as proxy evidence and
do not promote it to "certified win improvement."

------------------------------------------------------------
5.4 RNG / CRN HONESTY
------------------------------------------------------------

Do NOT falsely claim downstream randomness is identical if the alternative
action changes RNG consumption.

Playing search/draw/shuffle cards can cause the two branches to consume random
numbers differently.

Determine and DOCUMENT how the engine forks/clones RNG state.

If search forks provide truly cloned deterministic state, say so and prove it.

If not, use paired INITIAL seeds / determinizations and describe the comparison
accurately.

Do not write "same hidden randomness throughout the game" unless that is
actually guaranteed.

------------------------------------------------------------
5.5 DATA SUFFICIENCY GATE
------------------------------------------------------------

Before training P1, report:

- unique certified PLAY states
- unique episodes
- opponent lineages
- cards represented
- actual-order distribution
- own-turn distribution
- preference margins
- contradictory/ambiguous states discarded

Do not train a generic residual from three clever examples.

As a default sanity floor, I want on the order of dozens to ~100 distinct
high-quality states spread across many episodes/opponents, not a tiny cluster.

If the certified set is obviously too sparse or concentrated:

SKIP P1 AND REPORT INSUFFICIENT CAUSAL LABELS.

------------------------------------------------------------
5.6 TRAINING + SCREEN SEPARATION
------------------------------------------------------------

Do not tune against the final cheap gameplay screen.

Use separate:

- mining/training data
- validation data
- development seeds if necessary
- untouched screening seeds

Do not run fifteen variants on the same 500 screening games and pick the winner.

At most a very small number of residual training seeds/hyperparameters may be
selected using training/validation evidence.

Only ONE chosen P1 candidate should enter the untouched gameplay screen.

Use conservative rehearsal / zero-residual regularization so ordinary PLAY
states do not drift unnecessarily.

Screen:

maximum approximately 300-500 paired games.

If weak:
REJECT.

If approximately +4-5 pp or better in a relevant stratum with a credible
mechanism:
mark

PASSING SCREEN — CODE REVIEW REQUIRED

and STOP.

DO NOT RUN 1,000+ GAMES.

============================================================
6. EXPERIMENT B — TEMPORAL TWO-TURN TAKEOVER
============================================================

This tests a DIFFERENT hypothesis:

Maybe the remaining problem is not one bad Trainer selection.
Maybe A2 cannot execute one coherent early setup plan.

Use the existing temporal continuation policy.

Important:

Temporal schema also has legacy representation limitations.
This is NOT a PLAY-identity fix.

It is a coherent-plan test.

Run only ONE predefined takeover variant:

If hero is actually FIRST:
R0 controls the whole game.

If hero is actually SECOND:

- R0 controls pregame/setup unless the current implementation proves setup is
  intentionally part of the existing temporal policy
- starting with hero's first real in-game own turn, temporal controls EVERY
  hero decision
- temporal keeps control through the end of hero's second complete own turn
- then R0 takes over permanently

During the temporal window it controls complete action sequences:
- Trainer plays
- searches
- card selections
- attachments
- evolution
- targets
- counts
- attacks
- nested prompts

Do not alternate A2/temporal per decision.

Do not use the old learned temporal gate.

Do not mix logits.

Do not test turn-1, turn-2, turn-3 windows and pick the luckiest.
This sprint tests FIRST TWO COMPLETE OWN TURNS only.

------------------------------------------------------------
6.1 STATE SYNCHRONIZATION
------------------------------------------------------------

Inspect whether temporal/A2 agents have stateful history.

Prove that whichever policy takes over has correct internal state.

If a noncontrolling policy needs observations to stay synchronized, implement
that safely.

Do not let a "shadow" policy mutate shared game state or accidentally affect
the returned action.

If temporal errors or synchronization fails:

fall back permanently to R0 for that game and record the error.

Do not re-enter temporal later.

Damage V0 and common tactical post-processing must remain identical to R0
where mechanically applicable.

Screen:

300-500 paired ACTUAL-SECOND games maximum.

Use untouched seeds.

Report full paired statistics.

< ~+4 pp:
REJECT.

Approximately +4-5 pp:
interesting but marginal.

~+6-8 pp or more actual-second:
strong screen.

Any passing result:

PASSING SCREEN — CODE REVIEW REQUIRED

STOP.

NO 1,000+ EXPANSION.

============================================================
7. EXPERIMENT C — ALAKAZAM PETREL -> UNFAIR STAMP
============================================================

This is SECONDARY.

Do not spend large engineering time unless opportunity is clearly meaningful.

Mechanic hypothesis:

after the opponent KOs one of our Pokémon,
Unfair Stamp may become legal.

Team Rocket's Petrel can search for a Trainer.

Therefore some states permit a coherent line approximately:

opponent KO
-> our turn
-> Team Rocket's Petrel
-> search Unfair Stamp
-> play Unfair Stamp

This can reduce Alakazam's hand before its next turn.

BUT DO NOT ASSUME THIS IS GOOD.

Alakazam may:
- draw for turn
- use Pokémon abilities
- evolve and draw
- use other draw/search cards
- rebuild enough hand to attack hard anyway

Petrel also consumes our Supporter for the turn.

Stamp can even improve a very small opponent hand.

Therefore immediate post-Stamp hand size is NOT the outcome metric.

------------------------------------------------------------
7.1 C0 OPPORTUNITY AUDIT
------------------------------------------------------------

Use authentic Grim vs Alakazam data / simulator states.

Do not infer that Stamp is searchable from hidden deck knowledge.

Prefer mechanically proving the sequence through actual legal options:

- KO condition happened
- Petrel is legally playable
- after Petrel, Stamp actually appears among legal search results
- after retrieval, Stamp is legally playable

Count:

- opportunities
- games with opportunity
- loss games with opportunity
- opponent hand size at opportunity
- what R0 does instead

Calculate an opportunity ceiling as in A0.

If the line is too rare to plausibly contribute meaningful strength:

STOP TRACK C.

------------------------------------------------------------
7.2 C1 SMALL MACRO COUNTERFACTUAL
------------------------------------------------------------

Only if C0 passes the opportunity gate.

Compare:

R0 normal line

versus

coherent Petrel -> Stamp line

Do not force Petrel and immediately return to R0 before Stamp.

The macro must complete enough of the intended sequence to represent the idea.

Then return to R0.

Evaluate:

- terminal win/loss where feasible
- opponent hand size BEFORE Stamp
- opponent hand size at start of their turn
- opponent hand size immediately before Powerful Hand / attack
- attack damage/counters
- whether opponent obtained a KO
- prize swing
- our own development sacrificed by spending Petrel
- errors

Remember RNG caveat:
Stamp/search/shuffle may make downstream random streams diverge.

Report that honestly.

Only run a SMALL screen.

Never run a 1,000-game Alakazam gate in this DeepSeek pass.

If strong:

PASSING SCREEN — CODE REVIEW REQUIRED

STOP.

============================================================
8. REPLAY-DERIVED "STRATEGY SWAMP" IDEA
============================================================

A recent discussion proposed:

replay
-> infer strategy
-> create many rule/behavior agents that preserve the strategy under different
draws
-> use them for RL/training

The high-level insight is useful:

ONE REPLAY SHOULD NOT BE TREATED AS THE ONLY REALIZATION OF A STRATEGY.

However DO NOT build a large synthetic strategy-agent population in this
two-day screening sprint.

Reasons:

- inferred "intent" can be wrong
- LLM-written rules are unvalidated
- a synthetic opponent can become a strawman
- training against synthetic mistakes can move us away from the real ladder
- authentic opponent packages already exist in this repo
- implementation/debug time competes directly with the core experiments

Use the discussion only as GUIDANCE.

Prefer existing authentic/frozen opponents and known behavior clones.

If, AFTER all core screens are finished, a strategy-preserving opponent can be
created almost for free using existing infrastructure, it may be used ONLY as
a diagnostic stress opponent.

It cannot:
- supply automatic positive training labels
- certify strength
- replace authentic opponents

Do not delay A0/P0/P1/Temporal for it.

============================================================
9. OPPONENTS / META
============================================================

Do not optimize only against exact d842.

Use the strongest deterministic authentic opponents already available.

Likely useful:
- exact d842 / strong Grim mirror
- authentic A2-family reference
- master_v1 if deterministic/reproducible
- authentic Alakazam 2.7
- any genuinely strong Crustle package already present

Do NOT build a new Crustle policy for this sprint.

If the only Crustle opponent available is a weak proxy:
use it as diagnostics only, not strength certification.

Prefer recent relevant field opponents, but do not blindly trust public
discussion anecdotes about the meta.

============================================================
10. EVALUATION DISCIPLINE
============================================================

For every candidate report:

- exact R0 provenance
- exact candidate code delta
- number of paired games
- candidate wins
- R0 wins
- candidate-only wins
- R0-only wins
- paired delta
- paired 95% CI
- actual-order breakdown
- opponent breakdown
- seed methodology
- intervention frequency
- semantic decision change rate
- errors
- fallback count
- latency
- deterministic reproducibility where expected
- whether downstream RNG remains paired or diverges

Do not call an unpaired raw win-rate difference causal if paired evidence is
available.

Do not reuse the untouched screen repeatedly for hyperparameter selection.

Do not hide rejected arms.

============================================================
11. HARD STOP BEFORE EXPANSION
============================================================

THIS IS CRITICAL.

Do NOT run:

- 1,000 games
- 2,000 games
- final population gate
- final promotion gate
- final upload experiment
- Kaggle submission

If any candidate passes:

write:

PASSING SCREEN — CODE REVIEW REQUIRED BEFORE EXPANSION

and stop that arm.

Codex Ultra will independently inspect:

- baseline contamination
- Damage V0 preservation
- PLAY scope isolation
- temporal turn-window logic
- state synchronization
- RNG claims
- data leakage
- seed reuse
- multiple-comparison / selection bias
- fallback correctness
- packaging configuration

Only after that review will a separate decision be made about a 1,000+
confirmation.

============================================================
12. HARD EXCLUSIONS
============================================================

Do NOT start:

- PPO
- terminal-only RL
- generic MCTS
- old Director
- generic runtime search
- schema-5 resurrection
- broad strategic rails
- general Trainer heuristic rewrite
- logit soup
- phase router
- new deck project
- Crustle rewrite
- Dipplin
- huge LLM-generated opponent swarm
- unrelated repository cleanup

============================================================
13. FINAL DELIVERABLE
============================================================

Create one markdown report.

It must include:

- starting git state
- exact R0 provenance/hashes
- A0 PLAY opportunity audit
- opportunity upper bound
- replay agreement results, correctly named
- hand-position diagnostic
- P0 implementation/result
- P1 causal-label statistics if attempted
- P1 implementation/result if attempted
- temporal implementation/result
- Petrel->Stamp opportunity/result if attempted
- all rejected arms
- all passing arms
- seed/data split methodology
- RNG behavior
- opponent population
- modified files
- reproduction commands
- runtime/errors
- known limitations
- suspected confounds

For every candidate, explain in ONE sentence:

"Exactly what can this candidate change compared with R0?"

End with exactly one of:

NO ARM PASSED SCREEN — STOP GRIM DEVELOPMENT

or

ARM(S) PASSED SCREEN — CODE REVIEW REQUIRED BEFORE EXPANSION

If multiple arms pass, rank them by:

1. estimated strength upside
2. evidence quality
3. implementation risk
4. intervention coverage

DO NOT COMBINE THEM.

DO NOT EXPAND THEM.

STOP AND HAND OFF TO CODEX ULTRA.
