# Limitations

The strongest result is limited to a frozen population of seven local opponent
packages and one deterministic engine build. Opponents were deliberately chosen
for engineering coverage, not sampled from a population, so uncertainty
intervals characterize paired seed variation within this battery and do not
license population-wide claims about card-game agents.

The evaluation changes a representation flag and four trained output-side modules together.
The matched four-cell ablation estimates frozen contrasts among four realized
packages; it does not fully separate causal encoder and training contributions
because C3 and C4 were fitted separately, the identity-only C2 package activates
a feature against weights trained while that feature was zero, and only one
training seed was used. One retained corpus was used. Every retained
training/validation/holdout row came from a
positive-reward `daily_top_episode` unit; demonstrator expertise or action
optimality was not independently established. The newly run Aug. 13 replay
reanalysis uses already inspected historical certification material and is
secondary refresh-held-out evidence, not an untouched external test. It is
additionally restricted to winning units from five prespecified teams using the
exact target deck; only two of the five teams contributed eligible units. The
historical sampler was configured for a 0.1% rehearsal
share but batch rounding yielded zero rehearsal examples; “conservative” here
means frozen trunk plus KL distillation, not realized rehearsal mixing.

The retained corpus contains feature rows rather than the original replay
observations. Original Aug. 14--15 replay files were deleted by the historical
mining process, the nominal temporal holdout contains only empty stubs, and the
original software environment was not locked. The corpus can be transformed and
retrained from retained rows, but its feature extraction cannot be independently
rerun from raw replays.

Historical seven-policy macro and meta-weighted claims are omitted because their
raw wave files and frozen weight table do not survive. Historical demonstrator-action
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
