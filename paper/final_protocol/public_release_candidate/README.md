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

Clean-environment verification passed: a fresh virtual environment built from
`requirements-lock.txt` (Python 3.11.5, NumPy 2.4.6, Matplotlib 3.10.5,
pytest 9.1.1) ran every command below successfully; see
`CLEAN_ENV_REPRODUCTION.json` in the article repository for the recorded
transitive freeze, platform scope, and commands.

For a new conda environment:

```bash
conda env create --file environment.yml
conda activate trace-validation-review
python -B scripts/verify_release.py
python -B -m pytest -q -p no:cacheprovider
```

For a new virtual environment created outside this exact-tree release directory:

```bash
python3 -m venv ../trace-validation-review-venv
source ../trace-validation-review-venv/bin/activate
python -m pip install --requirement requirements-lock.txt
python -B scripts/verify_release.py
python -B -m pytest -q -p no:cacheprovider
```

`requirements-lock.txt` and `environment.yml` pin the directly requested
packages only; neither is a transitive dependency lock. The recorded clean run
observed the transitive versions listed in `CLEAN_ENV_REPRODUCTION.json`
(contourpy 1.3.3, cycler 0.12.1, fonttools 4.63.0, iniconfig 2.3.0,
kiwisolver 1.5.0, packaging 26.3, pillow 12.3.0, pluggy 1.6.0,
Pygments 2.21.0, pyparsing 3.3.2, python-dateutil 2.9.0.post0, six 1.17.0)
on macOS arm64 with CPython 3.11.5; universal cross-platform portability is
not claimed.

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
2,000 factorial units, including the 100,000-draw computations prespecified as
paired bootstrap procedures. Under the later reporting restriction, those
quantiles are labeled empirical reweighting sensitivities: they describe the
retained fixed batteries and are not population confidence intervals.

## Frozen plan and current reporting restriction

The frozen case-study protocols prespecified finite-population paired percentile
bootstrap intervals and secondary exact two-sided McNemar inference. That
original language remains visible in `docs/protocols/`. The bundled Level-6
fixed-battery descriptive-only taxonomy is a later, post-acquisition conservative
reporting restriction. It is not part of the frozen provenance and is not
evidence of prospective validation. Future adopters must freeze the taxonomy,
gate-to-claim mapping, estimands, and uncertainty rules before data acquisition.

## Evidence boundary

The historical CSV retains only the three available control records (win, draw,
and decision count), not complete traces. The preflight CSV retains trace digests
and byte counts plus outcome/error/decision summaries, not raw observations or
opaque search state. The stress file retains cluster-level disagreement flags,
recovered acting-side first-divergence counts, and per-profile wall-clock timing
aggregates; it contains no raw trace lines. The factorial CSV retains schedule,
outcome, and decision-count fields; trace digests were not captured for that
acquisition. Neutral context labels are stable within this package but are not
external entity identifiers.

The frozen stress protocol also promised first-divergence positions and actors
and timing summaries. Acting-side first-divergence counts (all 99 disagreeing
clusters localized to the opponent side) and timing aggregates were recovered
from hash-pinned retained evidence and are included as processed aggregates with
their source digest recorded; their public redistribution still awaits explicit
human approval. First-divergence positions were never recorded in any retained
artifact, and raw trace payloads remain restricted, so position-level
localization cannot be verified from this package and no position-level claim
is made. The omitted positions do not change the primary complete-trace digest
mismatch count; the omission remains a reporting/access deviation pending human
signoff; see `docs/PROTOCOL_DEVIATIONS.md`.

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
