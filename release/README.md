# Representation repair under distribution shift — processed methods package

This companion package regenerates the manuscript's statistics, tables, and six
figures from sanitized processed outcomes. It intentionally does **not** contain
the competition engine or its source, card data or assets, deck files, private
replays, credentials, third-party opponent implementations, or deployable policy
packages.

## Reproduce

Create the environment described in `environment.yml`, then run from this
directory:

```bash
python evaluation/verify_processed.py
python scripts/generate_tables.py
python scripts/build_figures.py
```

`verify_processed.py` reconstructs the fresh primary paired effect and checks the
canonical schema, 14-cell balance, discordant counts, and error totals against
the frozen statistical summary. The other commands write TeX/CSV table material
under `generated/` and PDF/PNG figures under `figures/`.

## Scope

The processed data describe seven fixed local opponent packages, two actual
orders, and one identified engine build. Opponents are not a random sample, so
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
author replaces that notice with an approved license and completes the citation
metadata.
