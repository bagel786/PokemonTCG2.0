# Reproducibility checklist

- [x] Fresh hypothesis, endpoint, sample size, seeds, stop rule, and error handling frozen before result access.
- [x] Candidate, control, opponents, runner, seeded engine, and production sentinel identified by SHA-256.
- [x] Candidate/control pairing validated on seed, order, and physical seat.
- [x] One row per paired unit emitted with source-artifact digest.
- [x] Primary interval uses 100,000 paired within-cell bootstrap draws.
- [x] Exact McNemar test and 14-cell Holm adjustment reported.
- [x] Missing four-cell ablation trained and evaluated under a frozen matched protocol.
- [x] Negative results included only when surviving raw artifacts permit independent aggregation.
- [x] Unsupported historical macro/meta-weighted claims labeled and omitted.
- [x] Per-game latency reported as unavailable, not inferred from wall time.
- [x] Six figures generated from checked-in code in PDF and PNG.
- [x] Manuscript compiled with REVTeX 4.2 and final PDF rendered to page images for inspection.
- [x] Sanitized release scanned for prohibited engine, card, replay, deck, credential, and opponent-code content.
- [ ] Author names, affiliations, emails, ORCIDs, and CRediT roles confirmed.
- [ ] Conflicts, funding, acknowledgments, and prior/public report overlap confirmed.
- [ ] Complete historical AI-tool use confirmed by the authors.
- [ ] Archive DOI, maintainer/contact information, and formal repository citation supplied and cited in the Data Availability Statement.
- [ ] Release rights and a valid open-source/data license approved by rights holders.
- [ ] End-to-end reproduction independently performed from an authorized engine copy.

Unchecked items are submission or release blockers.
