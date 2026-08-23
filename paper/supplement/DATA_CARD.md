# Data card: retained identity-feature and paired-evaluation data

## Purpose and composition

The private retained identity corpus contains 47,653 feature/action rows from
472 episodes and 69 team labels. Its training manifest assigns 38,254 rows to
training, 3,361 to internal validation, and 6,038 to a six-team holdout. The
paper's public processed gameplay data contain one row per matched random seed,
actual order, physical seat, opponent label, and candidate/control outcome.

## Collection and transformations

Identity rows were historically mined from Aug. 14--15 competition replays
with the PLAY-source binding flag enabled. Those original replay observations no
longer survive. The missing blind ablation corpus was deterministically derived
from retained rows by setting the source identifier to zero only for ordinary
PLAY options with no raw area; all transformation counts and hashes are recorded.

## Splits and leakage controls

The six-team holdout is disjoint by team label and duplicate decision key. The
internal validation split is episode-based. A purported temporal holdout is not
valid: it consists of eight empty stub files and contributes no rows. The holdout
was not evaluated by the historical training script; paper diagnostics evaluate
it separately and identify their estimand.

## Uses and nonuses

Appropriate uses are reproduction of the disclosed training transform,
head-only policy diagnostics, and aggregate evaluation. The corpus is not a
representative sample of all games, players, decks, or agents. It must not be
used to identify participants, reconstruct private play, infer population-wide
performance, or train an unrestricted commercial game agent without independent
rights review.

## Distribution, privacy, and maintenance

Raw feature rows, replay observations, card identifiers, deck data, and team
names are excluded from the sanitized release. Public tables use anonymous or
functional labels and numerical outcomes. The corresponding author must name a
maintainer, retention period, archival repository, request process (if any), and
withdrawal/error-correction policy before release.
