# Representation repair under distribution shift — processed methods package

This companion package independently verifies the fresh primary frozen
seed/order/pair-index/seat schedule, candidate/control/opponent/source digests,
counts, effect, discordant counts, and exact McNemar calculation. It regenerates
five table fragments and six figures from sanitized processed rows and recorded
summary files. It intentionally does **not** contain the competition engine or
its source, card data or assets, deck files, private replays, credentials,
third-party opponent implementations, or deployable policy packages.

## Reproduce

Create the environment described in `environment.yml`, then run from this
directory:

```bash
python evaluation/verify_processed.py
python scripts/generate_tables.py
python scripts/build_figures.py
```

`verify_processed.py` fails closed on the exact canonical CSV and primary-summary
schemas. It validates row-level outcome flags, hashes, relative source
paths, the exact frozen seed/order/pair-index/seat schedule, 14-cell balance,
duplicates, errors, primary arithmetic, and the released canonical digest. It
does not recompute the paired-bootstrap interval or the secondary summaries.
Those values are recorded processed results, and the plotting/table scripts
consume them. The other commands write TeX table material under `generated/`
and PDF/PNG figures under `figures/`.

Every shipped file except `MANIFEST.sha256` is listed in that manifest. The
release builder constructs and verifies a clean exact-allow-list staging tree
before atomically exchanging it with this directory on supported systems (and
fails without publishing when an atomic exchange is unavailable); symlinks,
unlisted files, model packages, archives, Python bytecode, and executable
binaries are rejected.

## Scope

The processed data describe seven fixed local opponent packages under neutral
identifiers, two actual orders, and one identified engine build. Team and
opponent-derived labels, absolute local paths, and restricted local-resource
URIs are sanitized in the released copies; `statistical_summary.json` records
both the source canonical digest and the digest of the sanitized released CSV.
Opponents are not a random sample, so
the package does not support inference to all agents or all card-game settings.
Approval in the held-out files is conditional on candidate--control disagreement
and is not a gameplay win rate.

Exact engine-level reruns require separately authorized access from the
competition organizer. See `docs/environment_access.md` and the manuscript Data
Availability Statement.

## Rights status

This is a review snapshot, not an authorized open-source release. Ownership and
licensing of the newly authored material require human and legal confirmation;
`LICENSE` grants no permission. Do not redistribute until the corresponding
author replaces that notice with an approved license and completes the author,
repository, and archival identifier/DOI metadata in `CITATION.cff`.

**Release readiness: BLOCKED** until those license, authorship, and archival
metadata requirements are resolved by an authorized human.
