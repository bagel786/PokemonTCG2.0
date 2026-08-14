# Grimmsnarl recovery analysis

## What the historical submissions say

The audited history contains 26 complete Grimmsnarl submissions and 1,403 public
games. Their aggregate win rate was 57.2%, but the aggregate hides the decisive
asymmetry: seat 0 won 64.1% while seat 1 won only 50.5%. Contemporary top agents
were around 58.3% from seat 1. This makes the missing seat-1 performance a much
larger and more repeatable problem than the occasional unusual matchup.

The exact same d842 archive also produced public convergence paths ranging from
roughly 660 to 970, with a peak around 1010. Therefore a low opening score is not
enough to identify a code regression. TrueSkill explicitly represents skill as a
mean plus uncertainty and makes larger updates while uncertainty is high; that is
why the rollout policy waits for games rather than reacting to the first score
([Microsoft TrueSkill overview](https://www.microsoft.com/en-us/research/project/trueskill-ranking-system/),
[original TrueSkill paper](https://www.microsoft.com/en-us/research/?p=154591)).

## Why earlier methodology stalled below 1000

1. **Winner-only imitation omitted recovery states.** The legacy corpus taught
   actions under the expert/winner state distribution, not the states reached
   after our own mistakes or from seat 1. This is the standard behavior-cloning
   covariate-shift failure: small errors move the learner off the demonstration
   distribution and later errors compound. DAgger and DART were developed around
   exactly this limitation
   ([Ross et al.](https://proceedings.mlr.press/v15/ross11a/ross11a.pdf),
   [DART](https://proceedings.mlr.press/v78/laskey17a.html)).

2. **The data and split unit were wrong for the question.** Winner-only extraction,
   decision-level splitting, and exact-name/exact-list archetype matching could
   leak mirror episodes across splits while excluding current deck variants.
   Whole-episode and team grouping is the appropriate protection; group-aware
   splitting is specifically designed to keep a domain-defined group out of both
   train and test
   ([scikit-learn GroupShuffleSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.GroupShuffleSplit.html)).

3. **Seat imbalance was averaged away.** Overall mirror win rate could look
   acceptable while seat 1 remained near a coin flip. A candidate can therefore
   win an offline aggregate gate and still lose the public games that distinguish
   top agents. Every current gate treats seat 0 and seat 1 as separate required
   populations.

4. **Unexpected archetypes were not truly tested.** Hardcoded/stale identifiers
   and exact 60-card equality silently missed variants. The corrected crawler uses
   current card/deck signatures for presence and classification, and the final
   population uses representative decks from actual recent episodes. Current
   Crustle and Starmie/Froslass representatives already differ from the old
   canonical files. Distribution-shift research likewise warns that models can
   rely on source-specific/spurious features that fail under a changed input
   distribution
   ([Zhou et al.](https://proceedings.mlr.press/v139/zhou21g.html),
   [Wen et al.](https://proceedings.mlr.press/v32/wen14.html)).

5. **Several gates were capable of false confidence.** Missing nested seat fields
   were replaced by 0.5/zero defaults, printed thresholds diverged from enforced
   thresholds, packaging could proceed without an explicit pass, and engine games
   were treated as paired despite using independent `std::random_device` entropy.
   The new schema rejects absent totals, seat results, errors, confidence metrics,
   or hashes. Wilson intervals are used for binomial win rates; NIST recommends the
   Wilson method for its coverage properties
   ([NIST confidence-interval guidance](https://itl.nist.gov/div898/handbook/prc/section2/prc241.htm)).

6. **Runtime changes confounded model changes.** Temperature, one-ply search,
   forced promotion, hardcoded opponent models, and broad tactical rails created
   policies materially different from the model that was trained and validated.
   The recovery runtime is deterministic policy inference plus only three audited
   interventions: setup benching, rejecting a fully nullified attack, and rejecting
   `END` when a productive attack exists.

7. **Operational defects consumed scarce submissions.** Package/import errors,
   stale artifacts, order-dependent tests, absent hashes, and late uploads made a
   sound model indistinguishable from a broken shipment. Packages now run on clean
   Ubuntu workers, submission archives and weights have separate SHA-256 fields,
   and every Kaggle ID is reconciled back to its immutable promotion manifest.

## Corrected evidence and current decisions

- The certified crawl processed 41 days through the first valid family-zero day,
  2026-06-27. It contains 5,738,033 exact-current-deck decisions, 113,673 Grim
  family seat-units, 59,597 exact-current seat-units, and zero failed manifests.
- Splits are by whole episode: 4,433,825 train, 492,190 validation, 554,092 team
  holdout, and 257,926 August 6 temporal-holdout decisions. Both mirror seats stay
  together.
- A1 failed its mirror gate. A2 passed 30,000 mirror games at 53.657% with a
  53.092% Wilson lower bound, +3.50 points seat 0 and +4.26 points seat 1 versus
  structural d842, plus zero errors.
- Authentic A2 reads were +0.85 points versus Alakazam 2.4a and +2.85 versus 2.7.
  Kaggle submission 55323436 is A2; byte-identical d842 submission 55323437 was
  uploaded second and is the newest fallback.
- B2 correction mining examined 5,000 recent stratified losses (74% seat 1,
  12 archetypes), retaining 42 alternatives for which all eight hidden-state
  determinizations were nonnegative, at least half were strictly better, mean
  advantage was at least 0.50, and search errors were zero.
- B1/B2 use 200,000 recent winning decisions, 20,000 projected legacy rehearsal
  decisions, a strong d842 KL anchor, and no runtime value policy. Each correction
  receives at most 32 exposures, preventing a small corrective set from dominating.

## Decision rule

Do not infer quality from the first ladder block. Replace immediately only for a
crash, invalid action, or package defect. At 75 games require credible progress and
no persistent seat-1 collapse. Final success still requires at least 75 public
games, a 1025+ checkpoint, and 48 continuous hours above 1000. Offline promotion
requires the predeclared independent-population confidence bounds; a candidate
that misses them is not shipped merely because its training loss improved.
