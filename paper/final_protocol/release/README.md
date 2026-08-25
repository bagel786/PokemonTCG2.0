# Pairing-assumption validation protocol: review and reproducibility package

This engine-independent package accompanies the Protocol Article **“A Protocol
for Validating Pairing Assumptions in Seed-Matched Evaluations of Black-Box
Game-Playing Agents.”** It contains the synthetic conformance implementation, expected
fixtures, neutralized processed diagnostics, processed factorial rows, sanitized
protocol transcriptions, analysis checks, figure/table code, tests, hashes, and
source data. It does not contain the restricted game engine or source, engine
binaries, third-party opponent packages, game assets or metadata, policy
packages, private observations, raw restricted traces, credentials, or archives.

## Quick start

From this directory:

```bash
python -B -m pevl_bench generate
python -B -m pevl_bench verify
python -B -m pevl_bench admit examples/example_evidence.json
python -B -m pevl_bench explain examples/example_evidence.json
python -B -m pevl_bench report
python -B -m pevl_bench report --decision-table
python -B scripts/verify_release.py
python -B scripts/build_figures_tables.py
python -B -m pytest -q -p no:cacheprovider
```

When this directory is used inside the complete repository checkout, run the
full article-level rebuild from the repository root:

```bash
python -B paper/final_protocol/scripts/reproduce_all.py
```

`generate` deterministically recreates the four synthetic fixture files in
`pevl_bench/results/` and the two synthetic-admission adapter files in
`pevl_bench/admission_results/`; `verify` compares those bytes with the executable
models and executes the bundled JSON Schema through the checked standard-library
validator. `admit` accepts only the closed file-bound record-bundle
schema, checks its canonical evidence hash, verifies every declared bundle-relative
regular single-link artifact and trace file against its SHA-256 (and trace byte
count), derives gate states, and then invokes the common classifier. This verifies
declared bytes and internal record consistency; scientific roles and provenance
still require an external trust anchor. `classify-trusted` remains available for explicitly
prevalidated state files, but its output clearly records that it did not verify
scientific evidence. `explain` identifies the blocking gate, wording boundary,
and required redesign; and `report` prints the retained headline diagnostics or
the generated admission decision table. `verify_release.py`
independently reaggregates 2,800 historical repeated-control units, 1,000
deterministic preflight units (3,000 executions), 200 timed-search clusters, and
2,000 factorial units, including the frozen 100,000-draw empirical reweighting
procedures. Those quantiles describe the retained fixed batteries and are not
population confidence intervals.

## Evidence boundary

The historical CSV retains only the three available control records (win, draw,
and decision count), not complete traces. The preflight CSV retains trace digests
and byte counts plus outcome/error/decision summaries, not raw observations or
opaque search state. The stress file retains cluster-level disagreement flags and
explicitly omits unverifiable earliest-event or actor localization, not raw traces. The factorial CSV retains schedule,
outcome, and decision-count fields; trace digests were not captured for that
acquisition. Neutral context labels are stable within this package but are not
external entity identifiers.

## Integrity and status

`MANIFEST.sha256` covers every staged payload except itself. The release
builder rejects extra files, links, executable/archive formats, local absolute
paths, secret-like assignments, and known private identifiers. The runtime
manifest checker requires the exact manifest tree and rejects caches, `.pyc` or
`.pyo` files, links, and every other extra entry. Running it without an external
pin establishes internal consistency only and says so in its JSON report. If an
independently recorded manifest digest is available, pass it with
`--expected-manifest-sha256` to bind verification to that external trust anchor.

This is a local review candidate, not an authorized archive deposit or public
release.
Human author metadata, ownership, and license remain unconfirmed. Consequently
no DOI is supplied and `LICENSE` grants no permission. Do not cite the incomplete
`CITATION.cff` as final metadata.
