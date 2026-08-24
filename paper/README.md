# APS Open Science research paper

This directory contains the complete research-paper workspace for
**Representation Repair under Distribution Shift in a Partially Observable
Card Game**. It is intentionally separated from the competition-development
workspace at the repository root.

## Start here

- [Compiled manuscript](main.pdf)
- [REVTeX source](main.tex) and [bibliography](references.bib)
- [Cover letter](cover_letter.md)
- [Statistical results](data/statistical_summary.json) and [canonical paired outcomes](data/canonical_results.csv)
- [Claim ledger](claim_ledger.csv)
- [Frozen confirmation protocol](protocol/FRESH_CONFIRMATION_PROTOCOL.md) and [ablation protocol](protocol/REPRESENTATION_ABLATION_PROTOCOL.md)
- [Provenance audit](supplement/PROVENANCE_AUDIT.md) and [rights/access audit](supplement/RIGHTS_AND_ACCESS_AUDIT.md)
- [Final red-team audit](supplement/FINAL_RED_TEAM.json)
- [Reproducibility checklist](supplement/REPRODUCIBILITY_CHECKLIST.md)
- [Sanitized companion release](release/README.md) and [release manifest](release/MANIFEST.sha256)

## Directory map

| Path | Contents |
| --- | --- |
| `data/` | Canonical outcomes, machine-readable summaries, fresh raw evaluation records, and ablation evidence |
| `figures/` | Six generated figures in PDF and PNG formats |
| `tables/` | Generated REVTeX table fragments |
| `protocol/` | Prospectively frozen confirmation and ablation protocols |
| `scripts/` | Analysis, table/figure generation, release assembly, and audit programs |
| `supplement/` | Provenance, data/model cards, rights review, literature audit, checklist, and final audit |
| `release/` | Sanitized processed-data package for private manuscript review |

Core numerical prose is generated from the machine-readable results through
`results.tex`, `results_macros.tex`, and `diagnostic_macros.tex`. The claim
ledger records the evidence, commit, artifact hash, statistical method,
limitation, and disposition for every reviewed claim.

## Verification

From the repository root:

```bash
python -B paper/release/evaluation/verify_processed.py
python -B paper/scripts/red_team_audit.py
```

To rebuild the sanitized release atomically and rerun its verifier:

```bash
python -B paper/scripts/build_release.py
```

To compile the manuscript, run REVTeX from this directory:

```bash
cd paper
tectonic main.tex
```

## Current release status

The scientific package passes its automated data, provenance, citation,
figure, manifest, and restricted-content checks. Public release and journal
submission still require author-confirmed metadata, an approved license and
rights review, and archival DOI metadata. The placeholder license grants no
redistribution rights.
