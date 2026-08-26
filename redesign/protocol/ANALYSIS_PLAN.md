# ANALYSIS PLAN (FROZEN)

**Frozen:** 2026-08-26 · Consumes: raw JSONL decision + outcome_pair rows · Produces: results tables, figures, macros.

## A. Decision-metric pipeline (M1–M3)

1. Load `results/final/raw/decisions.jsonl`.
2. Drop NOT_APPLICABLE cells per branch; record denominators.
3. Per (method × branch × system): pooled detection (M1), false-suppression soft/hard (M2), missed-failure hard/caveat-blind (M3) with Wilson 95% intervals.
4. Method-vs-framework contrasts on M1/M2: two-proportion z-tests, Holm-corrected across the primary family.
5. Output: `results/final/aggregates/decision_metrics.csv` + `.json`.

## B. Statistical-validity pipeline (M4–M6)

Constructed replicates from stored outcome pairs:
- **Null bank:** holdem mirror pairs (identical policies, different seeds); ising equal-temperature pairs → true difference 0 by construction.
- **Alternative bank:** frozen arms contrasts (holdem random-vs-conservative; ising 2.269 vs 2.9).
- Procedures compared at α=0.05: (i) paired t on coupled differences, (ii) independent-samples Welch, (iii) hierarchical (seed random intercept) via restricted bootstrap.
- Coverage: empirical proportion of 95% intervals containing truth over B=2000 resamples; Clopper–Pearson interval around coverage; MCSE reported.
- Type-I/power curves at N ∈ {10,20,40,80} via subsampling without replacement.

## C. Variance-reduction pipeline (M7)

R = Var(paired diff)/Var(independent diff). Independent differences formed by seeded cross-seed matching of the SAME outcome bank (documented permutation; no new outcomes). log R ± delta-method CI. Reported per system × scenario ∈ {S0,S3,S4,S8}.

## D. Cost pipelines (M9–M11)

M9: medians from runtime fields; M10: bytes fields; M11: instrumented/bare microbenchmark (50 runs/system) executed once during analysis stage, logged to `results/final/aggregates/overhead.json`.

## E. Complexity count (M12)

Enumerated programmatically from method configuration constants into `complexity_counts.json`; counts are code facts, not judgments.

## F. Cross-system consistency (M13)

Kendall τ between systems' method rankings on pooled (M1 − M2) score; sign agreement table for {R<1, framework-beats-B0, B5-within-5pp-of-B7}.

## G. Figures & tables

Generated exclusively by `redesign/analysis/make_figures.py` reading aggregates; each figure emits its source-data CSV alongside the PDF/PNG. No color-only encoding; direct labels; no decorative graphics.

## H. Manuscript number discipline

All prose numbers injected via generated macros file (`results_macros.tex` equivalents under redesign/manuscript/); manual transcription forbidden. Every macro maps to a script + commit in claim_ledger.csv.

## I. Deviation handling

Empty at freeze. Any entry in DEVIATIONS_LOG.md must be reflected here as an appendix note before manuscript assembly.
