# FREEZE RECORD

**Freeze commit:** recorded at push time (see git log for "PROTOCOL FREEZE" commit)
**Branch:** paper/claim-specific-prospective-redesign-20260826
**Frozen artifacts:**
- PROSPECTIVE_PROTOCOL.md
- ANALYSIS_PLAN.md
- METRICS_PREDECLARED.md
- SYSTEM_MANIFEST.json
- SEED_MANIFEST.json (pilot 12 / final 40, disjoint, derivation documented)
- FAILURE_INJECTION_MANIFEST.json
- EXPECTED_DECISION_TABLE.json

**Order of operations enforced:** this commit is pushed BEFORE any final-seed execution. Pilot seeds may run earlier for timing only. Final raw rows land exclusively under redesign/results/final/raw/ after the freeze push.

**Sample-size justification (from pilot timing probe, result-excluded):**
- holdem: ~0.02–0.05 s/arm-run → full grid ≈ minutes.
- ising L=20, sweeps=90+20: ~0.6–1.2 s/arm-run × 4 executions/row × 11 scenarios × 40 seeds ≈ 35–70 min.
- Total well under the 3 CPU-hour budget; N=40 gives Wilson intervals on proportions with half-width ≤ ~0.14 at p≈0.5 and ≤ ~0.05 near p≈0 or 1 across pooled cells (hundreds of cases per method×branch), adequate for the predeclared criteria.

**Timing probe values:** recorded in results/pilot_timing.json (pilot seeds only; no outcome inspection).
