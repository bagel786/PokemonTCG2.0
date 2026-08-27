# ANALYSIS PLAN (binding at freeze)

Consumes raw JSONL only via frozen schema (OUTPUT_SCHEMAS.json). No manual numbers; every manuscript token injected from machine-readable aggregates with a claim-ledger entry.

## A. Decision pipeline
1. Load decision rows; validate provenance payload presence + predicate trace per row.
2. Per (method, branch, system): covered-cell counts, abstentions, M1 strict detection (+caveat-only count), M2 soft/hard, Wilson intervals.
3. Case-level (system×construction) tables: per-seed correctness fractions; macro-over-constructions; family macros.
4. Contrasts per METRICS_AND_GATES (permutation primary, McNemar secondary, Holm).

## B. Cost pipeline
From cost-bank rows: per-method wall/cpu medians+p95+spread; execution counts; bytes per method bundle; equal-work narrative; Pareto checks for recommendation gate.

## C. Variance-benefit (exploratory)
For G01/G02 (valid coupling constructions), system-wise: R̂ = Var(paired diff)/Var(derangement diff); uncertainty via percentile bootstrap resampling SEED INDICES JOINTLY (B=2000, rng=20260827) recomputing both variances from the same resample (no independence assumption); report with explicit exploratory label; zero-variance rows flagged DEGENERATE_NOT_BENEFIT without invented intervals.

## D. Conclusion-change (secondary descriptive)
Per construction×seed: recommended-analysis substantive contrast (paired if B-admitted-design, else unpaired) vs always-unpaired estimator: record sign/significance agreement; summarize per case; label descriptive.

## E. Figures/tables plan
F1 claim-class routing diagram; F2 grammar×branch ground-truth matrix; F3 detection vs false suppression scatter (bubble=coverage); F4 per-case detection heat-strip with seed-fractions; F5 cost panel (executions/time/bytes); F6 variance-benefit exploratory; T1 systems/licenses; T2 grammar mechanisms+labels(+derivations); T3 baseline capabilities; T4 main results by branch×method; T5 contrasts+effects; T6 limitations/estimability. All emitted with source CSV/PDF+PNG; no color-only encoding.

## F. Exclusions / crash policy / stopping
No data-driven exclusions. Infrastructure crashes: rerun permitted ONLY pre-analysis, logged to results/crash_log.txt (result-excluded), max 2 attempts/cell then recorded missing-and-reported. Any scientific defect discovered after outcome visibility ⇒ fail closed (no patch-rerun-as-confirmatory). Single-pass holdout; no interim aggregation; compute cap 4 CPU-hours then halt+report partial.

## G. Independent verification requirements
Independent reaggregate script (stdlib-only) reproduces every headline number directly from raw JSONL; equation fixtures hand-computed (Wilson toy x=38,n=40⇒[0.835,0.986]; permutation fixture; bootstrap-seed determinism fixture); schema validators enforce units/denominators/nonzero timings.
