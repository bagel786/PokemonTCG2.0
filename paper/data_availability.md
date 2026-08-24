# Data Availability Statement

The intended sanitized private-review companion package under `paper/release/` is
designed to contain the processed one-row-per-paired-unit outcome tables,
statistical summaries, figure inputs, analysis scripts, protocols, hashes, and
environment specification needed to regenerate reported tables and figures from
processed outcomes and recorded summary files. Its verifier is intended to
check the primary row schedule, marginal counts, discordant counts, exact
McNemar calculation, and equal-weight point estimate. It will also preserve the
failed four-cell validation result, including all repeated C1 outcomes and the
210/2,800 mismatch count, rather than deleting mismatched units. It does not
independently recompute every interval or statistic from engine trajectories.

The underlying tournament engine, engine source and binaries, card database,
deck files, private replay observations, and third-party opponent packages are
not redistributed. They are subject to organizer terms, third-party rights,
and privacy constraints. Exact end-to-end gameplay regeneration therefore
requires separately authorized access from the competition organizer and the
same engine build identified by SHA-256 in the protocols. The repository's
competition-use license also imposes retention and redistribution restrictions;
the authors cannot grant access rights they do not possess.

The retained identity feature corpus and original policy packages are local,
ignored artifacts. Their cryptographic digests, row counts, transformation
rules, and derived aggregate results are reported, but the corpus and packages
are not part of the sanitized release pending a rights review. The original
Aug. 14--15 replay observations used to mine that corpus no longer survive, so
feature extraction cannot be reconstructed from those raw replays.

The processed primary results document an engine-seed-, order-, and seat-matched
schedule, not complete opponent-randomness coupling. Starmie and Dipplin use
wall-clock-bounded search, and the released processed records cannot recover or
resample unrecorded process-scheduling and runtime-state variation.

Repository DOI, archival location, maintainer contact, and any controlled-access
request procedure: **to be supplied by the corresponding author before
submission**. Once supplied, the authors must add a formal reference-list
citation for the released data/software package (creators, title, year, version,
repository, and persistent identifier) and cite it in the manuscript Data
Availability Statement.
