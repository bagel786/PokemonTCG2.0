# Data Availability Statement

The sanitized companion package under `release/` contains the processed
one-row-per-paired-unit outcome table, statistical summaries, figure inputs,
analysis scripts, protocols, hashes, and environment specification needed to
regenerate the reported tables and figures from processed outcomes and recorded
summary files. The package independently verifies the primary row schedule,
marginal counts, discordant counts, exact McNemar calculation, and equal-weight
point estimate, but it does not independently recompute every interval or
statistic from engine trajectories.

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

Repository DOI, archival location, maintainer contact, and any controlled-access
request procedure: **to be supplied by the corresponding author before
submission**. Once supplied, the authors must add a formal reference-list
citation for the released data/software package (creators, title, year, version,
repository, and persistent identifier) and cite it in the manuscript Data
Availability Statement.
