# Novelty audit — FINAL (machine-finalization refresh)

Audit date: 2026-08-25. Method: primary/official sources only; every existing
bibliography entry re-verified against arXiv/publisher records by an
independent literature pass this date; fresh searches for newer overlapping
work through 2026-08 executed. Full per-reference results in
`REFERENCE_AUDIT_FINAL.csv`; component-level matrix in `NOVELTY_MATRIX_FINAL.csv`;
search log in `NOVELTY_SEARCH_LOG_FINAL.json`.

## Scope of the contribution under audit

An executable, fail-closed protocol deciding whether same-seed evaluations of
black-box stochastic agents may be analyzed as paired comparisons, via seven
components:

1. boundary-seed verification;
2. same-artifact trace repetition across execution contexts;
3. within-arm vs cross-arm distinction;
4. result-independent evidence-to-claim map;
5. automatic suppression after failed pairing evidence;
6. synthetic coupling-failure suite;
7. black-box empirical suppression example.

## Verification summary

All 23 bibliography entries were checked against primary sources:
**23/23 VERIFIED_MATCH** (two cosmetic notes only: Paduraru et al. full title
already includes its subtitle in our entry; Sharma v1 carried a different title
before revision — cited version/title are the current ones). No citation
required invention or repair. No unverifiable reference remains in
`references.bib`.

## Closest works and what they lack

| Work | What it establishes | Missing components |
|---|---|---|
| Kaliyev & Maryanskyy 2026 (paired noise-floor) | Configuration byte audits (~C1), trial-index distinction (=C3), self-suppressed favorable finding (~C7) | No artifact-to-execution trace ladder (C2), no automatic rule (C4/C5), no synthetic suite (C6); suppression is a one-off self-retraction |
| Rollout Cards (Masters et al. 2026) | Preserved rollouts, declared views, reporting rules (~C4 adjacent) | Never validates seed-to-execution coupling (C1–C2); no suppression semantics (C5); no failure suite (C6) |
| Trace-assurance framework (Paduraru et al. 2026) | Contracts, replay, fault injection, localization | No paired statistics, seeds, or claim admission (C3–C5) |
| AEVAL (Anand et al. 2026) | Deterministic evaluation-contract tests | Same as above; no coupling validation or suppression rule |
| Event-keyed CRN (Buffalo et al. 2026) | Stateful draw-shift problem; white-box event-keyed repair (our Stage-7 prior art) | White-box assumption; no admission/suppression machinery (C4–C5), no black-box case (C7) |
| Sharma 2025 (paired seeds) | Conditional precision gain when seed outcomes correlate | Assumes rather than validates coupling (anti-C1/C2) |
| Bjarnason et al. 2026; Mustahsan et al. 2025 | Randomness/inconsistency quantification in agent evals | Measurement, not gating; none of C4–C7 |
| Zot 2026 (claim-licensing protocol); ReplayBench-PG 2026 | Preregistered gate→downgrade matrix (~C4/C5); fault-injection detection (~C6) | Each holds one ingredient in unrelated domains; no seeds/traces/coupling ladder, no black-box example |

Newer 2026 items scanned (Yadav et al. RLJ 2026 CRN planning; Mudasiru
`agrepl` replay; GAIATrace/Vidur-Agent; Liu et al. tool-calling sensitivity;
Hydari & Iqbal stochasticity typology; Rover et al. LLM-API nondeterminism;
Agentick benchmark seeding) each touch at most one component and none
implements the evidence ladder or automatic suppression.

## Fatal novelty test

**Result: PASS (novelty survives).** No single work, and no straightforward
pair among all verified works, contains substantially all seven components.
The strongest pair tested — Kaliyev & Maryanskyy 2026 combined with Buffalo et
al. 2026 — still lacks executable result-independent admission (C4),
automatic fail-closed suppression wired to gate evidence (C5), and the
synthetic coupling-failure suite bound to the same rules (C6).

Qualification (narrow and conditional): the contribution is an operational
integration for black-box settings, valid as described for artifacts exposing
a seeded entry point, hashable artifacts, and recordable projections; it is
not a claim that no prior framework combines *some* of these elements, and it
is not prospectively validated beyond the reported case study.

**Conclusion:** proceed without a scientific pivot on novelty grounds. Any
wording using "first/novel/unprecedented" remains prohibited; the manuscript
uses integration language exclusively.
