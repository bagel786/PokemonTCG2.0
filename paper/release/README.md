# Paired Evaluation Validity Ladder — processed methods package

This companion package supports **A Validity Ladder for Seed-Matched
Evaluation of Game-Playing Agents**. It contains the sanitized processed
evidence for the Paired Evaluation Validity Ladder (PEVL), an executable
standard-library-only synthetic validation suite, frozen protocols, audit
records, and code-generated manuscript artifacts. It intentionally contains no
competition engine or engine source, card data or assets, deck files, private
replays, credentials, third-party opponent implementations, or deployable
policy packages.

PEVL separates a matched schedule from reproducible execution and from
event-aligned stochastic coupling. The package preserves both positive and
fail-closed evidence: the retrospective 210-of-2,800 identical-control outcome
record mismatch, the prospective four-arm trace preflight, the completed timed
search stress analysis, and either an admitted seed-matched factorial result or
an explicit terminal suppression record. It does not infer event-level coupling
where event identities and event-keyed random quantities were unavailable.

## Verify

Create the environment described in [`environment.yml`](environment.yml), then
run from this directory:

```bash
python -B evaluation/verify_processed.py
python -B evaluation/verify_pevl.py
python -B synthetic/pevl_synthetic.py verify
```

[`verify_processed.py`](evaluation/verify_processed.py) independently checks the
historical canonical paired-result schema and arithmetic.
[`verify_pevl.py`](evaluation/verify_pevl.py) fails closed unless the released
trace preflight and timed-search stress analyses are complete, the standalone
and combined PEVL summaries agree, the seed-namespace and bounded
stochastic-source audits are internally consistent, and the synthetic fixture
tree verifies exactly. If the factorial branch is
`ADMITTED_SEED_MATCHED`, the verifier requires and reaggregates exactly 2,000
released unit rows. For a terminal suppression branch, it requires the unit
file and factorial figure/table to be absent.

To regenerate all released tables and figures from the processed records:

```bash
python -B scripts/generate_tables.py
python -B scripts/build_figures.py
python -B scripts/build_pevl_artifacts.py \
  --synthetic synthetic/results/pevl_results.json \
  --historical data/processed/ablation_summary.json \
  --preflight data/processed/pevl_trace_preflight_summary.json \
  --stress data/processed/pevl_timed_search_stress_summary.json \
  --factorial data/processed/pevl_factorial_summary.json \
  --combined data/processed/pevl_summary.json \
  --figures-dir figures \
  --tables-dir generated/tables
```

The PEVL artifact builder always creates the ladder, synthetic-validation, and
retrospective-parity artifacts. It creates the stress artifact only from a
terminal stress summary and creates factorial artifacts only from an admitted,
internally consistent factorial summary. It removes stale conditional outputs
for nonadmitted branches.

Every shipped file except [`MANIFEST.sha256`](MANIFEST.sha256) is listed in that
manifest. The release builder constructs and verifies a clean exact-allow-list
staging tree before atomically exchanging it with this directory on supported
systems. Symlinks, unlisted files, model packages, archives, Python bytecode,
and executable binaries are rejected. The synthetic results also carry their
own nested exact manifest.

## Evidence scope

The processed case study covers fixed, hashed local artifacts rather than a
random sample of agents or environments. Identifying opponent/team labels,
absolute paths, and restricted local-resource URIs are neutralized in released
text and data. The prospective trace preflight concerns the five frozen
determinism-eligible opponent packages and the exercised serial/eight-worker
contexts. The timed-search stress analysis concerns two frozen timed-search
packages under four serial/parallel and enqueue-order variants. These bounded
checks do not prove source-level determinism, a unique nondeterminism mechanism,
or cross-arm event alignment.

The earlier representation, held-out, negative-result, and invalidated
four-cell files remain as case-study appendix evidence. The historical
bootstrap interval is conditional on one realized execution. The post hoc
five-opponent sensitivity is descriptive and is not a replacement for the
failed planned seven-opponent gate.

Exact engine-level reruns require separately authorized access from the
competition organizer. See
[`docs/environment_access.md`](docs/environment_access.md) and the manuscript
Data Availability Statement.

## Rights status

This is a review snapshot, not an authorized open-source release. Ownership and
licensing of the newly authored material require human and legal confirmation;
[`LICENSE`](LICENSE) grants no permission. Do not redistribute until the
corresponding author replaces that notice with an approved license and
completes the author, repository, and archival identifier/DOI metadata in
[`CITATION.cff`](CITATION.cff).

**Release readiness: BLOCKED** until those license, authorship, and archival
metadata requirements are resolved by an authorized human.
