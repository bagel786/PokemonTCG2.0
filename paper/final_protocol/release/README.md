# Trace-based validation protocol: review and reproducibility package

This engine-independent package accompanies the Protocol Article **“A Trace-Based
Validation Protocol for Seed-Matched Evaluations of Black-Box Game-Playing
Agents.”** It contains the synthetic conformance implementation, expected
fixtures, neutralized processed diagnostics, processed factorial rows, sanitized
protocol transcriptions, analysis checks, figure/table code, tests, hashes, and
source data. It does not contain the restricted game engine or source, engine
binaries, third-party opponent packages, game assets or metadata, policy
packages, private observations, raw restricted traces, credentials, or archives.

## Quick start

From this directory:

```bash
python -m pevl_bench generate
python -m pevl_bench verify
python -m pevl_bench report
python -B scripts/verify_release.py
python -B scripts/build_figures_tables.py
python -B -m pytest -q -p no:cacheprovider
```

When this directory is used inside the complete repository checkout, the full
article-level rebuild is:

```bash
python paper/final_protocol/scripts/reproduce_all.py
```

`generate` deterministically recreates the four synthetic fixture files in
`pevl_bench/results/`; `verify` compares those bytes with the executable model;
and `report` prints the retained headline diagnostics. `verify_release.py`
independently reaggregates 2,800 historical repeated-control units, 1,000
deterministic preflight units (3,000 executions), 200 timed-search clusters, and
2,000 factorial units, including the frozen 100,000-draw bootstrap procedures.

## Evidence boundary

The historical CSV retains only the three available control records (win, draw,
and decision count), not complete traces. The preflight CSV retains trace digests
and byte counts plus outcome/error/decision summaries, not raw observations or
opaque search state. The stress file retains cluster-level disagreement flags and
localized actor counts, not raw traces. The factorial CSV retains schedule,
outcome, and decision-count fields; trace digests were not captured for that
acquisition. Neutral context labels are stable within this package but are not
external entity identifiers.

## Integrity and status

`MANIFEST.sha256` covers every staged payload except itself. The release
builder rejects extra files, links, executable/archive formats, local absolute
paths, secret-like assignments, and known private identifiers. Python cache
files created during local verification are explicitly ignored by the runtime manifest
checker; they are absent from the built package.

This is a local review candidate, not an authorized archive deposit or public
release.
Human author metadata, ownership, and license remain unconfirmed. Consequently
no DOI is supplied and `LICENSE` grants no permission. Do not cite the incomplete
`CITATION.cff` as final metadata.
