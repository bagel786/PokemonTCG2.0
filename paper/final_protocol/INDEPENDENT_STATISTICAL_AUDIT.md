# Independent Statistical Audit

## Verdict

**PASS, with one protocol-interpretation note and no factual numerical conflict.**

This audit recalculates the central results from 58 Git-tracked retained raw
acquisition files. It does not import the production analyzer and does not use
processed summaries, the processed factorial unit CSV, macros, figures, or
manuscript prose as numerical inputs. Those later artifacts are comparison
targets only.

The machine-readable record is
`source_data/independent_statistics_verification.json`. The executable is
`scripts/independent_statistics_audit.py`, and its independent tests are
`tests/test_independent_statistics.py`.

## Authoritative source hierarchy used

1. The retained execution-row arrays in `paper/data/ablation/raw/`,
   `paper/data/fresh_confirmation/raw/`, and `paper/data/pevl/*/raw/`.
2. The prospectively frozen protocol, SHA-256
   `8b9329b948a054fc7252b9c2662490890e0a8439ad852393c6e25f537c8b887e`.
3. The executable frozen at protocol commit `803257f1` when the prose leaves an
   implementation detail ambiguous. The frozen analyzer blob has SHA-256
   `e258049cedeff13cc84c82e69a43f3416639c98d4e70d25c0799f06e33ba4f7a`.
   It is inspected only to interpret the declared empirical reweighting rule; it supplies
   no rows, mismatch flags, or numerical inputs to this audit.
4. This independently written raw-row reaggregation.
5. Processed summaries, generated macros, figure source data, and prose, used
   only to test whether displayed claims reproduce the raw calculation.

All 58 raw-file hashes matched the frozen audit manifest: 21 historical, 20
preflight, 2 timed-search, and 15 factorial files. Exact top-level schemas and
32,600 exact execution-row schemas passed. The audit inspected 422,475 numeric
JSON values and found no nonfinite value. The combined source-manifest digest
is `b7e9395df9816ec62e487b605949c7c2cf58860ccacc2b50353a7cda49e2eab9`.

## Historical repeated-control audit

The analysis unit is an opponent × actual-order × seed-condition cluster with
three separately acquired C1 control executions. The 21 acquisition files
contain 16,800 rows; 8,400 control executions form 2,800 comparison units in
14 opponent-by-order strata. The other 8,400 candidate executions do not enter
the repeated-control mismatch count.

Direct comparison of the three C1 rows per unit gives:

| Projection or field | Disagreement units | Rate |
|---|---:|---:|
| Win and draw | 210 / 2,800 | 7.50% |
| Error counts | 0 / 2,800 | 0.00% |
| Decision count alone | 457 / 2,800 | 16.32% |
| Full available record: win, draw, errors, decisions | 458 / 2,800 | 16.36% |

The distinction between 457 and 458 is real: the full-record count is the union
of outcome, error, and decision-count disagreements, not the decision-count
count alone. The manuscript's 458-unit “after decision count was added” claim
is correct.

The mismatches are confined to two contexts. One has 191/400 outcome
disagreements (47.75%) and 377/400 full-record disagreements (94.25%); the
other has 19/400 (4.75%) and 81/400 (20.25%). Each of the other five contexts
has zero disagreement on both projections. These sum exactly to 210 and 458.

## Deterministic preflight

The analysis unit is an arm × opponent × actual-order × seed-condition unit
containing three executions: two fresh one-worker profiles and one eight-worker
profile. The raw layout is 20 arm-context jobs × 50 units × 3 profiles.

The independent totals are 1,000 trajectory units and 3,000 executions. Every
required mismatch count is zero:

- trace digest: 0;
- trace byte count: 0;
- combined recorded-trace projection: 0;
- terminal win/draw outcome: 0;
- hero/opponent error counts: 0;
- decision count: 0;
- union of required fields: 0.

All jobs contain 25 units in each actual order, preserve alternating physical
seat, and use the declared 1,000,000 second-order seed offset.

## Timed-search stress test

The analysis and resampling unit is one opponent × actual-order ×
seed-condition cluster containing all four serial/parallel and forward/reverse
executions. The raw data contain 200 clusters and 800 executions.

The independent disagreement counts are:

| Endpoint | Clusters | Rate |
|---|---:|---:|
| Complete trace digest | 99 / 200 | 49.5% |
| Trace byte count | 96 / 200 | 48.0% |
| Digest-or-byte trace projection | 99 / 200 | 49.5% |
| Terminal outcome | 47 / 200 | 23.5% |
| Decision count | 93 / 200 | 46.5% |
| Error record | 0 / 200 | 0.0% |

The four separately reported strata reproduce as follows; each range gives the
2.5th and 97.5th quantiles from 100,000 whole-cluster empirical reweighting
draws with seed `2026083118`:

| Stratum | Trace disagreements | Estimate | Reweighting quantiles | Outcome | Decision count | Error |
|---|---:|---:|---:|---:|---:|---:|
| Timed-search A, order 1 | 44 / 50 | 88% | [78%, 96%] | 19 | 43 | 0 |
| Timed-search A, order 2 | 48 / 50 | 96% | [90%, 100%] | 28 | 47 | 0 |
| Timed-search B, order 1 | 4 / 50 | 8% | [2%, 16%] | 0 | 3 | 0 |
| Timed-search B, order 2 | 3 / 50 | 6% | [0%, 14%] | 0 | 0 | 0 |

### Overall reweighting interpretation

The frozen prose is not fully explicit about the overall resampling. It says
that the seed-condition is the resampling cluster and that results are
stratified by opponent and order, but its timed-search uncertainty paragraph
says only “cluster bootstrap draws over seed-condition units.” Unlike the
factorial rule, it does not say “within each stratum.”

The prospectively frozen executable resolves that ambiguity. It computes four
separate stratum resampling distributions and computes the overall distribution
by passing all 200 cluster indicators to one pooled binary resampling
procedure. The specified pooled whole-cluster result is therefore **49.5%,
[42.5%, 56.5%]**, with 100,000 draws and seed `2026083118`. Those endpoints are
reported as empirical reweighting quantiles, not a confidence interval. The
current macros, manuscript, cover letter, and figure source match them.

For sensitivity, reweighting 50 whole clusters independently inside each of the
four strata and equally averaging the stratum means gives **49.5%, [46.0%,
53.0%]** under the same draw count and seed. This is an alternative
fixed-composition sensitivity, not a correction to the frozen executable
result. The pooled and fixed-composition quantiles describe different empirical
reweightings of the fixed battery; neither estimates coverage for a population.

## Admitted factorial

The 15 raw candidate-control acquisitions contain 12,000 execution rows. They
form 2,000 aligned C1/C2/C3/C4 unit vectors in 10 opponent-by-order strata of
200 units. C1 was acquired three times per unit; all 2,000 repeated-control
units agree on schedule, win/draw, error counts, and decision count. All 12,000
executions have zero policy-error records.

Cell counts and rates are:

| Cell | Wins | Units | Win rate |
|---|---:|---:|---:|
| C1 | 1,236 | 2,000 | 61.80% |
| C2 | 1,242 | 2,000 | 62.10% |
| C3 | 1,215 | 2,000 | 60.75% |
| C4 | 1,247 | 2,000 | 62.35% |

The independent contrasts and the 2.5th/97.5th quantiles from 100,000 paired
within-stratum empirical reweighting draws with seed `2026083117` are:

| Contrast | Estimate (percentage points) | Reweighting quantiles (percentage points) |
|---|---:|---:|
| C4 − C1 | +0.55 | [−2.05, +3.15] |
| Representation main contrast | +0.95 | [−1.08, +3.00] |
| Training main contrast | −0.40 | [−2.03, +1.25] |
| Interaction | +1.30 | [−1.85, +4.45] |

For C4 versus C1, there are 358 C4-only wins and 347 C1-only wins, 705
discordant units total, and the independently recalculated exact two-sided
McNemar value is `0.7064831563628252`. This number is retained only as a
numerical verification of the frozen analysis and is not displayed or admitted
as manuscript inference because the required reference-distribution assumptions
are not established. The empirical reweighting quantiles span zero; the audit
does not convert that fact into equivalence, a null test, or “no effect.”

## Display audit and limitations

Every central count, percentage, percentage-point contrast, and reweighting
quantile currently displayed through `results_macros.tex`,
`figure_4_timed_search.csv`, and `figure_5_factorial.csv` matches the raw-row
calculation under the frozen executable interpretation. No factual conflict was
found.

The tracked stress rows contain trace digests and byte counts, not the
restricted trace lines. Earliest-divergence actor localization is therefore
outside this row-level numerical audit and is not retained in evidentiary prose.
All empirical reweighting quantiles condition on the fixed engineering battery;
they are not population intervals over new opponents, seeds, hardware contexts,
or training runs.

## Reproduction

Run:

```bash
python paper/final_protocol/scripts/independent_statistics_audit.py
python paper/final_protocol/scripts/independent_statistics_audit.py --check
python -m pytest -q paper/final_protocol/tests/test_independent_statistics.py
```

The independent suite currently reports `8 passed`.
