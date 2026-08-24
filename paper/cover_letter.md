# Draft cover letter — APS Open Science

Dear Editors,

We submit “A Validity Ladder for Seed-Matched Evaluation of Game-Playing
Agents” for consideration as a Regular Article in *APS Open Science*.

Paired seeds can improve precision in stochastic comparisons, but a matching
seed schedule, reproducible executions, and alignment of the same semantic
random events are distinct properties. The manuscript introduces the Paired
Evaluation Validity Ladder (PEVL), an eight-level, fail-closed workflow that
connects artifact identity, exact engine-seed namespaces, schedule parity,
identical-arm trace tests, worker-context tests, stochastic-source auditing,
cross-arm event alignment, and a prespecified statistical admission rule. Its
aim is practical: to determine which paired claims black-box evidence permits
when researchers cannot replace or instrument a restricted simulator's random
number generator.

A self-contained standard-library testbed separates five controlled modes.
It shows that a seed collision can escape identical-arm repetition, that
injected clock and process state can break byte-identical executions, and that
a stateful draw shift can pass every within-arm repeat test while misaligning
four of five later shared events. Event-keyed randomness restores alignment in
the logged synthetic event set.

The restricted game-agent case study demonstrates why the admission rule
matters. A favorable historical one-execution estimate of +2.786 percentage
points coexisted with repeated-control disagreement on 210 of 2,800 terminal
outcome records and 458 of 2,800 fuller serialized records, confined to two
wall-clock-limited search opponents. Under the frozen rule, the planned
representation-by-training decomposition was suppressed rather than rescued by
selecting the five agreeing opponents. A prospectively committed revision then
passed all 20 four-arm trace-preflight jobs: 1,000 arm–seed trajectories and
3,000 executions across two fresh serial profiles and one eight-worker profile
had zero complete public-trace, terminal-record, error, or decision-count
mismatches.

[TERMINAL PROSPECTIVE STRESS AND FACTORIAL RESULT — GENERATED AFTER THE FROZEN
ADMISSION ANALYSIS]

We believe the manuscript fits the journal's emphasis on computational and
data-intensive methods, artificial intelligence, reproducible software, and
negative or null results. The contribution is not that common random numbers
require assumptions, nor that seed pairing is generally invalid. It is an
operational black-box validation and reporting system that distinguishes the
evidence needed for schedule-matched, reproducible seed-matched, and
event-aligned claims.

The submission package is designed to include the REVTeX manuscript, frozen
protocols, claim ledger, processed audit records, deterministic result and
figure generators, automated release verification, and a sanitized companion
package. The simulator, third-party opponent packages, protected game data,
private replays, policy packages, and restricted full traces are not
redistributed. The manuscript states these access limits and does not imply
end-to-end public reproducibility. Public release remains blocked until the
authors approve ownership, licensing, and archival metadata.

**This draft must not be submitted until a human corresponding author confirms
the following:** the work is original and not under consideration elsewhere;
all related competition reports, public writeups, preprints, and overlapping
materials have been disclosed and cited; every author has approved the
manuscript, author order, contributions, conflicts, funding, and AI-assistance
disclosure; the release rights and license are approved; and the repository DOI
and data/software citation are complete.

Suggested reviewers: **[names, affiliations, expertise, and email addresses
require author input]**.

Reviewers to exclude, with reasons: **[author input required, or state none]**.

Sincerely,

**[Corresponding author name, affiliation, postal address, email, and ORCID]**
