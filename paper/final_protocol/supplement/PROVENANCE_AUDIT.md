# Protocol Article provenance audit

This audit applies the article's source-of-truth hierarchy: immutable result
rows; the frozen protocol interpreted according to its acquisition-specific
chronology; validated analyzer output; executable code; artifact hashes;
generated TeX; manuscript prose; historical reports; conversation summaries.

## Repository lineage

- Source branch: `paper/aps-open-science-202608`.
- Audited source commit: `23b91060cb38d2ece0f6569f5d5d0b8ee361d3b6`.
- Final working branch: `paper/apsos-final-desk-gate-202608`.
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

## Frozen plan versus later reporting taxonomy

For the retained preflight, stress, and five-context factorial acquisitions,
the case-study protocol was committed before the result artifacts. Its operative
decisions were binary: a trace-preflight mismatch blocked factorial acquisition,
and any invalidating acquisition or repeated-C1 mismatch suppressed every
planned factorial contrast. Conditional on a pass, the frozen analysis called
for finite-population seed-matched paired bootstrap intervals and a secondary
exact two-sided McNemar analysis for the primary binary contrast.

The multi-level generic admission taxonomy and its executable rule bundle were
formalized after acquisition. The final article also makes a conservative
post-acquisition reporting change: it calls the paired-bootstrap output
fixed-battery empirical reweighting quantiles and retains the McNemar value only
for numerical audit, not inference. Those changes narrow the claims; they do
not show that the later taxonomy was prospectively frozen or validated. Any
future study claiming prospective validation must freeze the taxonomy, its
inputs, and its reporting consequences before acquisition.

The historical repeated-control audit has separate chronology. Historical
outcomes already existed when its available-record gate and suppression rule
were frozen. Retaining all mismatches and applying that rule without an
outcome-favorability input is auditable retrospective control, not prospective
blinding evidence.

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
  factorial inference is not included as Protocol Article evidence. The gate's
  retrospective freeze is not represented as prospective validation.
- Preflight and timed-search records carry the declared trace projection.
  Factorial records intentionally contain no trace digest and are verified only
  on schedule, outcome, error, and decision fields.
- The frozen stress primary endpoint was equality of complete public-state/action
  trace digests. The byte-count component of the later `(digest, byte_count)`
  tuple is integrity hardening added after acquisition. Both endpoint versions
  produce 99/200 disagreement clusters; all 96 byte-count disagreements occur
  within the 99 digest-disagreement clusters.
- The frozen protocol promised first-divergence position,
  acting-side/actor localization, and timing summaries as secondary public
  outputs. The release omits these outputs, and the retained evidence available
  to this audit contains no raw trace lines from which localization can be
  independently reconstructed. This reporting/access deviation does not alter
  the primary digest result, but it leaves localization and timing unverified.
  Human confirmation and an amendment decision remain PENDING.
- The stochastic-source audit is a bounded Python AST/pattern scan of 11
  package trees. Two binary engines were hash checked but not source assessed.
- All central manuscript quantities are generated from validated inputs. Manual
  prose may not override raw rows, the frozen protocol, or checked analyzer
  output.

No raw result file is rewritten by the final Protocol Article workflow, and no
new outcome-driven policy experiment is part of it. The detailed deviation
record is `PROTOCOL_DEVIATIONS.md`; its status is **UNSIGNED/PENDING**, so this
audit neither asserts author approval nor invents a protocol amendment.
