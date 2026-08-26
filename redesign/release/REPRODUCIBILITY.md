# Reproducibility Guide

## Status boundary

This guide reproduces the retained campaign. It does not repair missing A/A
null banks or S8 repeat outcomes. Re-running new outcomes after result inspection
would be a new study and must use a new protocol freeze and seed bank.

## Environment

- Tested platform: macOS arm64, Darwin 25.1.0
- Python: 3.11.5 in an isolated venv
- Dependency lock: `environment/requirements-lock.txt`
- Protocol freeze commit: `62ad878`
- Raw JSONL SHA-256:
  `ead6dd392c61767c914f9bb1956b7a82213c5889f3e95faf15c4a3f3ec5d2540`

## Reproduce retained analysis

The release archive is an evidence snapshot with the raw data, processed data,
code, and outputs. The analysis scripts retain the study repository's directory
contract. To regenerate outputs, check out the closeout commit named in the
handoff, verify this package's manifest, and run from that repository root:

```bash
python3.11 -m venv redesign/.venv
redesign/.venv/bin/pip install -r redesign/release/environment/requirements-lock.txt
redesign/.venv/bin/python redesign/analysis/complete_analysis.py
redesign/.venv/bin/python redesign/analysis/interval_checks.py
redesign/.venv/bin/python redesign/analysis/independent_reaggregate.py
redesign/.venv/bin/python redesign/analysis/make_figures.py
redesign/.venv/bin/python redesign/analysis/make_tables.py
redesign/.venv/bin/python redesign/manuscript/build_manuscript.py
```

`analyze.py` is preserved as the prospectively written historical entry point;
its post-freeze implementation repairs are documented in
`protocol/DEVIATIONS_LOG.md`. It is not part of the release regeneration command
because its old centered-bootstrap output did not carry the mandatory
non-confirmatory label. `complete_analysis.py` emits the complete audit-friendly
output set and an `estimability.json` register; the explicitly labeled
`statistical_diagnostics.*` files replace that old proxy.

## Verify

```bash
cd redesign/release
shasum -a 256 -c MANIFEST.sha256
cd ../..
pdfinfo redesign/manuscript/FINAL_MANUSCRIPT_FOR_REVIEW.pdf
```

Expected integrity facts:

- 35,014 raw rows total;
- 34,160 decision rows;
- 854 outcome-pair rows;
- S7 retains 27/40 pairs in each system by construction;
- every retained seed has 40 decision rows (8 methods x 5 branches);
- independent Branch-B reaggregation status `PASS`.

## Final-run command (historical reconstruction only)

The following reconstructs the campaign from the frozen seed manifest and will
take about 25 minutes on the tested laptop. Do not use the output to claim a new
prospective campaign unless a new protocol has been frozen first.

```bash
PYTHONPATH=redesign redesign/.venv/bin/python -m benchmark.runner \
  --manifest redesign/protocol/SEED_MANIFEST.json \
  --out redesign/results/reproduction/decisions_and_pairs.jsonl
```

## Known non-reproducible claims

M4 confirmatory coverage, M5 confirmatory Type-I error, M6 confirmatory power,
per-method M9 runtime, and full per-method M10 storage cannot be reconstructed
from the retained schema. Centered bootstrap files are diagnostics only.

## Archive integrity

`build_manifest.py` hashes every release file except the manifest itself.
`build_archive.py` creates a deterministic gzip-compressed tar archive under
`redesign/dist/` and writes its digest to `redesign/dist/SHA256SUMS`.
