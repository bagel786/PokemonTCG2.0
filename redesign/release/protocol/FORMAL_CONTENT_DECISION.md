# Formal Content Decision: PATH B — Tested Implementation Invariants

**Decision:** Path B. The old manuscript's "formal properties" were software invariants dressed in theorem-like language. We state them honestly as tested invariants of the reference implementation, documented here and in the software appendix; we claim no theorems.

## Invariants (each enforced by an executable test)

| # | Invariant | Test |
|---|-----------|------|
| I1 | **Result exclusion:** classifier inputs contain no final outcome values; decisions depend only on structural evidence | `tests/test_result_exclusion.py`: perturbing `outcome` fields leaves all decisions identical |
| I2 | **Monotonicity under evidence removal:** removing any required evidence can never upgrade a decision | `tests/test_monotone.py`: for every bundle fixture, all 2^n evidence-subset degradations yield decision ranks ≥ full-evidence rank (order ADMIT < DOWNGRADE < SUPPRESS < FAIL_CLOSED) |
| I3 | **Fail-closed unknowns:** missing repeats/contexts/event maps produce FAIL_CLOSED, never ADMIT | `tests/test_fail_closed.py` |
| I4 | **Projection scoping:** replay admissions are scoped to declared projection digests; out-of-projection field changes do not affect Branch C decisions but are logged | `tests/test_projection_scope.py` |
| I5 | **Deterministic classification:** identical bundles → identical decisions across runs and process instances | `tests/test_determinism.py` |

## What this does NOT establish

- No soundness theorem about real systems: labels are construction-known for the benchmark harness only.
- No completeness claim: scenarios S0–S10 do not exhaust failure space.
- No statistical guarantee beyond those stated per-procedure in STATISTICAL_DESIGN.md.

Manuscript language rule: section titled "Tested safety invariants of the reference implementation"; no "theorem", "proof", "guarantee" vocabulary anywhere near these five items.
