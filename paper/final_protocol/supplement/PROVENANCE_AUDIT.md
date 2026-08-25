# Protocol Article provenance audit

This audit applies the article's source-of-truth hierarchy: immutable result
rows; prospectively frozen protocol; validated analyzer output; executable
code; artifact hashes; generated TeX; manuscript prose; historical reports;
conversation summaries.

## Repository lineage

- Source branch: `paper/aps-open-science-202608`.
- Audited source commit: `23b91060cb38d2ece0f6569f5d5d0b8ee361d3b6`.
- Final working branch: `paper/apsos-trace-protocol-final-202608`.
- Frozen protocol commit:
  `803257f102232763fc88d28c14b668f9b62eb277`.
- Frozen protocol SHA-256:
  `8b9329b948a054fc7252b9c2662490890e0a8439ad852393c6e25f537c8b887e`.
- Retained prospective result artifacts first appear in source commit
  `23b91060cb38d2ece0f6569f5d5d0b8ee361d3b6`, a descendant of the protocol
  commit.

Git establishes commit ancestry and the bytes recorded in each commit. It does
not independently establish when a human inspected uncommitted files; any
stronger noninspection statement requires human attestation.

## Canonical evidence identities

The checked generator and independent verifier pin the exact SHA-256 identities
of the synthetic results, historical summary and units, preflight summary,
timed-search summary, factorial summary and units, seed-namespace audit,
stochastic-source audit, and protocol. The machine-readable identities and
verification results are in:

- `source_data/artifact_identity.json`;
- `source_data/statistics_verification.json`;
- `source_data/build_report.json`;
- `REPRODUCTION_REPORT.json`.

The canonical verifier also checks every declared preflight source, all 15
declared factorial sources, both retained timed-search proof sources, the seven
seed-audit inputs, and canonical tree/file digests for all 13 inventoried
artifacts. Public-review verification uses neutralized processed rows and the
release manifest; it does not claim to reproduce restricted acquisition.

## Evidence boundaries

- Historical mismatch flags are independently reconstructed from three
  retained control records per schedule unit. The invalidated historical
  factorial inference is not included as Protocol Article evidence.
- Preflight and timed-search records carry the declared trace projection.
  Factorial records intentionally contain no trace digest and are verified only
  on schedule, outcome, error, and decision fields.
- The stochastic-source audit is a bounded Python AST/pattern scan of 11
  package trees. Two binary engines were hash checked but not source assessed.
- All central manuscript quantities are generated from validated inputs. Manual
  prose may not override raw rows, the frozen protocol, or checked analyzer
  output.

No raw result file is rewritten by the final Protocol Article workflow, and no
new outcome-driven policy experiment is part of it.
