# Limitations

The strongest result is limited to a frozen population of seven local opponent
packages and one deterministic engine build. Opponents were deliberately chosen
for engineering coverage, not sampled from a population, so uncertainty
intervals characterize paired seed variation within this battery and do not
license population-wide claims about card-game agents.

The evaluation changes a representation flag and trained neural heads together.
The matched four-cell ablation separates those factors, but its identity-only
cell applies a feature to weights trained while that feature was zero and is
therefore mechanistic rather than deployment-valid. One seed and one retained
corpus were used. The historical sampler was configured for a 0.1% rehearsal
share but batch rounding yielded zero rehearsal examples; “conservative” here
means frozen trunk plus KL distillation, not realized rehearsal mixing.

The retained corpus contains feature rows rather than the original replay
observations. Original Aug. 14--15 replay files were deleted by the historical
mining process, the nominal temporal holdout contains only empty stubs, and the
original software environment was not locked. The corpus can be transformed and
retrained from retained rows, but its feature extraction cannot be independently
rerun from raw replays.

Historical seven-policy macro and meta-weighted claims are omitted because their
raw wave files and frozen weight table do not survive. Historical expert-action
rows also do not survive; the paper uses a new reanalysis only where retained raw
replays permit it. Several other negative-result documents survive without their
raw rows and are treated as historical summaries, not exact evidence.

Per-game latency was not recorded by the frozen runner. Parallel wall-clock time
is not substituted for latency. The engine, card data, decks, private replays,
and opponent implementations cannot be redistributed under the available rights
and privacy constraints, limiting end-to-end independent reproduction.

Finally, author identity, affiliations, ORCID, contributions, conflicts,
funding, full historical AI-tool use, archive DOI, and release licensing require
human confirmation. These are submission blockers, not clerical details to infer
from Git configuration.
