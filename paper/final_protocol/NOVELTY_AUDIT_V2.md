# Novelty audit V2 — closeout refresh (2026-08-25)

Scope: re-run of the novelty boundary search against current 2026 literature,
performed during the submission-closeout phase. This document supersedes the
narrative conclusions (not the machine bindings) of `NOVELTY_AUDIT.md`; the
machine-checked records remain `REFERENCE_AUDIT.csv` and `NOVELTY_MATRIX.csv`
(both extended in this refresh) and the raw query log is
`NOVELTY_SEARCH_LOG_V2.json`.

## What changed since V1

Two close 2026 works were identified, verified, and added to the manuscript and
both audit CSVs:

1. **Kaliyev & Maryanskyy 2026 — “How Much Coordination Gain Is Real? A Paired
   Noise-Floor Protocol for Multi-Agent LLM Benchmarks”** (KDD Workshop on
   Evaluation and Trustworthiness of Agentic AI; non-archival; also
   arXiv:2606.20695). Measures a same-model configuration-equivalent paired-gap
   envelope across repeated seeds and **retracts** a favorable contrast that did
   not replicate at a second seed. This is the closest existing work in spirit:
   skeptical paired-seed reporting with an actual retraction. It differs from
   this protocol in mechanism: it quantifies API/server stochasticity by
   repetition, and does not verify boundary seeds, artifact identity, or
   within-artifact trace repeatability across worker/enqueue/pool contexts; it
   has no within-arm vs cross-arm coupling distinction, no executable admission
   map, and no synthetic conformance suite.

2. **Zhang & Lee 2026 — “Beyond Leaderboards: Protocol Cards for Trustworthy
   Coding-Agent Evaluation”** (same workshop; non-archival). Discloses the
   protocol conditions behind coding-agent scores (information/procedure/
   measurement protocol dimensions) with task-paired bootstrap intervals. It is
   a disclosure layer over declared protocols; it never verifies that a shared
   seed produced repeatable executions and has no suppression consequence.

Both are cited and contrasted in the Related-work section; both rows are marked
`verified=TRUE` in the audit CSVs with the exact manuscript sentence recorded.
Neither is described as peer reviewed beyond its non-archival workshop status.

## Fatal novelty test

If any single paper, or straightforward combination of two papers, already
provided substantially all of —

- observable seed boundary verification;
- same-artifact trace repetition across execution contexts;
- explicit within-arm vs cross-arm distinction;
- result-independent statistical claim map;
- suppression after failed pairing evidence;
- synthetic coupling failure suite;
- black-box empirical suppression demonstration;

— then the Protocol Article's novelty would be insufficient.

**Verdict: NO such work or combination exists as of this search. The novelty
boundary survives.** The closest two-paper combinations considered:

- *Noise-floor + event-keyed CRN*: retraction discipline plus white-box repair
  still lacks every verification stage and the claim map.
- *Protocol cards + Rollout Cards*: disclosure and preservation layers without
  coupling verification or automatic suppression.
- *Sharma + Bjarnason*: statistical theory and variance measurement without any
  implementation-validity workflow.

## Standing boundary (unchanged from V1)

Common-random-number theory \cite{glasserman1992crn}, streams/substreams
\cite{lecuyer2002streams}, counter-based parallel RNGs
\cite{salmon2011parallel}, event-keyed randomness
\cite{buffalo2026eventkeyed}, paired-seed statistics
\cite{sharma2025pairedseeds}, rollout preservation
\cite{masters2026rolloutcards}, trace assurance
\cite{paduraru2026traceassurance}, deterministic workflow contracts
\cite{anand2026aeval}, agent-evaluation randomness studies
\cite{bjarnason2026randomness,mustahsan2025stochasticity}, metamorphic testing,
simulation V&V, and A/A diagnostics are all prior art. The contribution remains
the operational integration into an executable black-box evidence-to-claim
workflow.

No priority claim is made over any component ingredient; the words "first",
"novel", "unprecedented", and "groundbreaking" are not used in the manuscript.

## Limitations of this audit

- Coverage is limited to indexed web literature retrieved on 2026-08-25.
- Human author countersignature is required (`HUMAN_CLOSEOUT_FORM.md`,
  Section 12, item 12.3) before the boundary is treated as author-approved.
