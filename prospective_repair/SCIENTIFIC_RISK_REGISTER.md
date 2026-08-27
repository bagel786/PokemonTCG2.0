# Scientific Risk Register — prospective repair campaign

**Status:** living document through freeze; entries closed only with cited evidence. Opened 2026-08-27.

| # | Risk | Likelihood | Impact | Mitigation / kill criterion | Status |
|---|------|-----------|--------|------------------------------|--------|
| R01 | Freeze push cannot be verified on origin (permissions) → confirmatory status impossible | Low | Fatal to confirmation | Phase-3 hard stop: if tag/SHA not resolvable on remote, do NOT run holdout; deliver regression-checkpoint + no-go | open |
| R02 | RLCard legacy API differences (env.np_random aliasing) silently defeat keyed/logging hooks | Medium | High (invalid game arm evidence) | Direct integration tests assert hook identity (`env.game.np_random is hook`) and dealer-log growth per hand; run on installed rlcard 1.2.0 only | open |
| R03 | Ising toolkit consumes RNG at a point we do not control (fast path / numba), so keyed or logging wrapper never used | Medium | High | Read toolkit source; construct sampler after RNG replacement; draw-count integration test; if impossible, event-keyed Ising scenario DELETED before freeze (labeled, not faked) | open |
| R04 | Wall-clock think budgets make runs nondeterministic in DURATION but deterministic in draws (desired); accidental dependence of outcomes on scheduler timing would break replay semantics tests | Medium | Medium | Think loop must burn from an ISOLATED stream and outcomes must be invariant to budget magnitude within fixed draw count; metamorphic test: two budget scalings ⇒ same draws-per-event multiset where construction claims invariance | open |
| R05 | Aug-30 deadline pressure induces skipped gates | Medium | Fatal to integrity | Explicit rule adopted: better an honest NO-GO checkpoint than any simulated completion; every phase has machine-checkable gate before proceeding | open |
| R06 | New fault constructions accidentally equivalent to V1 scenarios (self-plagiarism of bank) | Low-Med | Medium (weakens novelty of confirmation) | Disjointness checker compares scenario IDs AND seed sets vs redesign manifests; ≥1 genuinely new construction per branch documented in fault grammar | open |
| R07 | Baselines rebuilt "competent" but tuned (directly or not) against dev-bank performance rather than spec | Medium | High (invalid comparison) | Baseline specs frozen BEFORE implementation sees dev outcomes; dev inspections limited to crashes/schema/mechanics; holdout untouched until post-freeze; capability table fixed pre-implementation | open |
| R08 | Cost timings dominated by noise (laptop load) making cost gates meaningless | Medium | Low-Med | Cost bank = 50 seeds × 3 randomized-order repetitions; report median+p95+run-to-run spread; cost used for Pareto check at coarse granularity only | open |
| R09 | Exact McNemar invalid due to clustering across seeds within case | Medium | Medium (statistical validity) | Predeclared primary contrast: case-level paired summaries with sign-flip permutation over cases + seed-cluster bootstrap uncertainty; McNemar applied only where independent-cell assumption defensible (documented per output) | open |
| R10 | Compound-fault labels ambiguous (which branch truth applies when faults interact) | Medium | Medium | Ground-truth labels derived mechanically from the fault grammar composition rules; every compound case carries a derivation record auditable pre-freeze | open |
| R11 | AI-assisted construction bias (faults shaped to what B7 can detect → inflated framework) | Real risk acknowledged | High | Fault grammar written from failure-mechanism taxonomy independent of classifier internals; baselines tested with mutation suite proving each CAN detect its targets; negative results reported regardless of direction; human review explicitly asked about this risk in portal | open |
| R12 | Holdout results inspected early (even accidentally) destroying prospective status | Low | Fatal | Holdout runner writes to append-only raw store; no aggregate tooling executable until freeze-SHA guard passes; pilot/dev analysis tools take explicit `--allow-dev` flag that hard-fails on holdout paths | open |
| R13 | Novelty erodes further as 2026 literature moves fast | Medium | Medium | Cite Sabot/ASMR-Bench/MLE-Sabotage/entrapment-FDR line prominently; final novelty recheck is a REQUIRED human task before submission; contribution framed strictly as evaluation object | open |
| R14 | Manuscript numerics drift from aggregates (manual transcription) | Medium | Medium | Macro-injection pipeline only; claim_ledger.csv maps number→source hash→script→command; doc scan forbids bare percentages outside macros in Results sections | open |
| R15 | Inadvertent modification of redesign/ historical tree during repair work | Low | High (provenance loss) | test_redesign_untouched.py pins SHA256 inventory of redesign/** captured at campaign start; CI-style gate at each commit checkpoint | open |
| R16 | Ising S5/S6-equivalent mechanics turn out unimplementable faithfully → temptation to relabel GT instead | Medium | High | Decision pre-committed: implement-and-test OR delete-scenario-before-freeze with logged rationale; NEVER relabel to match observed behavior (hard gate) | open |
| R17 | Cross-process context tests flaky in sandboxed environments | Low | Low | Subprocess spawn uses sys.executable with tiny worker script; if environment forbids subprocesses, that scenario's cross-process claim is removed (not weakened silently) | open |
| R18 | PDF/render tooling unavailable for manuscript stage | Low | Low | Prefer available LaTeX toolchain; fallback documented; visual page-by-page inspection remains REQUIRED human/computer step | open |

## Kill-gate restatement (from P0 audit §4)

If any of the following becomes true, the campaign produces a repair checkpoint + explicit NO-GO handoff instead of continuing:
1. The verified protocol freeze cannot be pushed & resolved on origin.
2. Any labeled fault mechanism cannot be implemented and independently tested honestly.
3. Any promised frozen metric turns out non-estimable from the retained schema after acquisition (fail closed; no proxy substitution).
